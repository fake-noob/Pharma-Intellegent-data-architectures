#!/usr/bin/env python3
"""Stream-profile the Pharma Supply Chain CSVs without loading whole files."""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import pandas as pd
from docx import Document


CSV_FILES = [
    "01_master_data.csv",
    "02_manufacturing_data.csv",
    "03_manufacturer_delivery_data.csv",
    "04_warehouse_data.csv",
    "05_pharmacy_sales_data.csv",
    "06_hospital_demand_data.csv",
    "07_iot_streaming_data.csv",
]
DATE_COLUMN = re.compile(r"date|time|timestamp", re.IGNORECASE)


def extract_guide(path: Path) -> list[str]:
    document = Document(path)
    lines = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        lines.append("")
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip().replace("\n", " / ") for cell in row.cells))
    return lines


def profile_csv(path: Path, chunksize: int) -> dict:
    columns = list(pd.read_csv(path, nrows=0).columns)
    missing = {column: 0 for column in columns}
    dtypes = {column: set() for column in columns}
    dates = {
        column: {"min": None, "max": None, "invalid": 0}
        for column in columns
        if DATE_COLUMN.search(str(column))
    }
    numeric = {
        column: {
            "count": 0,
            "mean": 0.0,
            "m2": 0.0,
            "min": None,
            "max": None,
            "non_numeric": 0,
        }
        for column in columns
    }
    row_count = 0

    for chunk in pd.read_csv(path, chunksize=chunksize):
        row_count += len(chunk)
        for column in columns:
            series = chunk[column]
            missing[column] += int(series.isna().sum())
            dtypes[column].add(str(series.dtype))

            if column in dates:
                present = series.dropna()
                parsed = pd.to_datetime(present, errors="coerce", format="mixed", utc=True)
                dates[column]["invalid"] += int(parsed.isna().sum())
                parsed = parsed.dropna()
                if not parsed.empty:
                    low, high = parsed.min(), parsed.max()
                    if dates[column]["min"] is None or low < dates[column]["min"]:
                        dates[column]["min"] = low
                    if dates[column]["max"] is None or high > dates[column]["max"]:
                        dates[column]["max"] = high

            values = pd.to_numeric(series, errors="coerce")
            state = numeric[column]
            present_count = int(series.notna().sum())
            valid = values.dropna()
            state["non_numeric"] += present_count - len(valid)
            if valid.empty:
                continue

            count = len(valid)
            batch_mean = float(valid.mean())
            batch_m2 = float(((valid - batch_mean) ** 2).sum())
            previous_count = state["count"]
            total_count = previous_count + count
            delta = batch_mean - state["mean"]
            state["mean"] += delta * count / total_count
            state["m2"] += batch_m2 + delta * delta * previous_count * count / total_count
            state["count"] = total_count
            low, high = valid.min(), valid.max()
            state["min"] = low if state["min"] is None else min(state["min"], low)
            state["max"] = high if state["max"] is None else max(state["max"], high)

    columns_info = []
    for column in columns:
        present_count = row_count - missing[column]
        info = {
            "name": column,
            "dtypes": sorted(dtypes[column]),
            "missing": missing[column],
            "missing_pct": (missing[column] / row_count * 100) if row_count else 0,
        }
        if column in dates:
            info["date_range"] = dates[column]
        state = numeric[column]
        if state["count"] and state["non_numeric"] == 0:
            info["numeric"] = {
                "count": state["count"],
                "mean": state["mean"],
                "std": math.sqrt(state["m2"] / (state["count"] - 1))
                if state["count"] > 1
                else 0,
                "min": state["min"],
                "max": state["max"],
            }
        info["non_missing"] = present_count
        columns_info.append(info)

    return {"path": path, "rows": row_count, "columns": columns_info}


def render_profile(data_dir: Path, guide_path: Path | None, chunksize: int) -> str:
    output = [
        "# Pharma Supply Chain Dataset Profile",
        "",
        f"Data directory: `{data_dir}`",
        f"CSV chunk size: {chunksize:,} rows (files are processed incrementally)",
        "",
    ]

    if guide_path and guide_path.is_file():
        output.extend(["## Dataset guide", ""])
        output.extend(extract_guide(guide_path))
        output.append("")
    else:
        output.extend(["## Dataset guide", "", "Guide document not found.", ""])

    for filename in CSV_FILES:
        path = data_dir / filename
        output.extend([f"## {filename}", ""])
        if not path.is_file():
            output.extend(["**Not found; table was not profiled.**", ""])
            continue

        profile = profile_csv(path, chunksize)
        output.extend(
            [
                f"- Rows: {profile['rows']:,}",
                f"- Columns: {len(profile['columns'])}",
                "",
                "| Column | Inferred dtype(s) | Missing | Missing % | Date range (UTC) | Numeric summary |",
                "|---|---|---:|---:|---|---|",
            ]
        )
        for column in profile["columns"]:
            date_range = column.get("date_range")
            date_text = ""
            if date_range:
                low, high = date_range["min"], date_range["max"]
                date_text = f"{low} to {high}" if low is not None else "No parseable dates"
                if date_range["invalid"]:
                    date_text += f"; unparseable: {date_range['invalid']:,}"
            stats = column.get("numeric")
            stats_text = ""
            if stats:
                stats_text = (
                    f"count={stats['count']:,}, mean={stats['mean']:.6g}, "
                    f"std={stats['std']:.6g}, min={stats['min']}, max={stats['max']}"
                )
            dtype_text = ", ".join(column["dtypes"])
            output.append(
                f"| {column['name']} | {dtype_text} | {column['missing']:,} | "
                f"{column['missing_pct']:.2f}% | {date_text} | {stats_text} |"
            )
        output.append("")

    return "\n".join(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Directory containing CSVs and the Word guide (defaults to repository root)",
    )
    parser.add_argument(
        "--guide",
        type=Path,
        help="Optional explicit path to the Word guide",
    )
    parser.add_argument("--chunksize", type=int, default=100_000)
    parser.add_argument("--output", type=Path, help="Optional Markdown report destination")
    args = parser.parse_args()
    if args.chunksize < 1:
        parser.error("--chunksize must be a positive integer")

    guide_path = args.guide
    if guide_path is None:
        guides = sorted(args.data_dir.glob("Pharma Supply Chain Dataset Guide*.docx"))
        guide_path = guides[0] if guides else None
    report = render_profile(args.data_dir, guide_path, args.chunksize)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Profile written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
