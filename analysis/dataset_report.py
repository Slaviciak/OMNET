#!/usr/bin/env python3
"""
Generate a lightweight sanity report for the linkdegradation dataset.

Assumptions:
- The dataset CSV was produced by analysis/build_dataset.py.
- Empty strings represent missing values.
- Only simple summary and data quality checks are needed at this stage.
- The report should stay robust even if some expected columns are missing.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "analysis" / "output" / "linkdegradation_dataset.csv"
REPORT_PATH = PROJECT_ROOT / "analysis" / "output" / "dataset_report.txt"
MISSING_CSV_PATH = PROJECT_ROOT / "analysis" / "output" / "dataset_missing_values.csv"
PER_CONFIG_CSV_PATH = PROJECT_ROOT / "analysis" / "output" / "dataset_per_config_summary.csv"

EXPECTED_CONFIGS = ["MildLinear", "StrongLinear", "UnstableLinear"]
KEY_NUMERIC_COLUMNS = [
    "controller_delay_mean_s",
    "controller_packet_error_rate_mean",
    "receiver_total_packet_count",
    "receiver_app0_e2e_delay_mean_s",
    "receiver_app1_e2e_delay_mean_s",
]


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def count_missing(rows: list[dict[str, str]], columns: list[str]) -> dict[str, int]:
    missing = {}
    for column in columns:
        missing[column] = sum(1 for row in rows if row.get(column, "") == "")
    return missing


def numeric_values(rows: list[dict[str, str]], column: str) -> list[float]:
    values = []
    for row in rows:
        value = parse_float(row.get(column))
        if value is not None:
            values.append(value)
    return values


def describe_numeric(values: list[float]) -> dict[str, float | int | str]:
    if not values:
        return {
            "count": 0,
            "mean": "",
            "median": "",
            "min": "",
            "max": "",
        }
    return {
        "count": len(values),
        "mean": fmean(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def per_config_numeric_summary(rows: list[dict[str, str]], features: list[str]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("config_name", "")].append(row)

    summary_rows: list[dict[str, object]] = []
    for config_name in sorted(grouped):
        summary_row: dict[str, object] = {"config_name": config_name, "row_count": len(grouped[config_name])}
        for feature in features:
            values = numeric_values(grouped[config_name], feature)
            stats = describe_numeric(values)
            summary_row[f"{feature}_count"] = stats["count"]
            summary_row[f"{feature}_mean"] = stats["mean"]
            summary_row[f"{feature}_min"] = stats["min"]
            summary_row[f"{feature}_max"] = stats["max"]
        summary_rows.append(summary_row)
    return summary_rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", newline="", encoding="utf-8") as handle:
            handle.write("")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def format_counter(title: str, counter: Counter) -> list[str]:
    lines = [title]
    if not counter:
        lines.append("  <none>")
        return lines
    for key, value in sorted(counter.items(), key=lambda item: str(item[0])):
        lines.append(f"  {key}: {value}")
    return lines


def format_numeric_section(title: str, rows: list[dict[str, str]], columns: list[str]) -> list[str]:
    lines = [title]
    for column in columns:
        values = numeric_values(rows, column)
        stats = describe_numeric(values)
        lines.append(f"  {column}:")
        lines.append(f"    count={stats['count']}")
        lines.append(f"    mean={stats['mean']}")
        lines.append(f"    median={stats['median']}")
        lines.append(f"    min={stats['min']}")
        lines.append(f"    max={stats['max']}")
    return lines


def build_report(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "Dataset is empty.\n"

    columns = list(rows[0].keys())
    config_counts = Counter(row.get("config_name", "") for row in rows)
    label_counts = Counter(row.get("label", "") for row in rows)
    run_counts = Counter(row.get("run_number", "") for row in rows)
    missing_counts = count_missing(rows, columns)
    missing_expected_configs = [config for config in EXPECTED_CONFIGS if config not in config_counts]
    key_columns_present = [column for column in KEY_NUMERIC_COLUMNS if column in columns]
    key_columns_missing = [column for column in KEY_NUMERIC_COLUMNS if column not in columns]

    lines: list[str] = []
    lines.append("LinkDegradation Dataset Sanity Report")
    lines.append("====================================")
    lines.append("")
    lines.append("Dataset Shape")
    lines.append(f"  rows: {len(rows)}")
    lines.append(f"  columns: {len(columns)}")
    lines.append("")
    lines.extend(format_counter("Rows Per Config", config_counts))
    lines.append("")
    lines.extend(format_counter("Rows Per Label", label_counts))
    lines.append("")
    lines.extend(format_counter("Rows Per Run", run_counts))
    lines.append("")
    lines.append("Missing Value Counts Per Column")
    for column in columns:
        lines.append(f"  {column}: {missing_counts[column]}")
    lines.append("")
    if missing_expected_configs:
        lines.append("Expected Configs Missing From Dataset")
        for config in missing_expected_configs:
            lines.append(f"  {config}")
        lines.append("")
    if key_columns_missing:
        lines.append("Expected Numeric Columns Missing From Dataset")
        for column in key_columns_missing:
            lines.append(f"  {column}")
        lines.append("")
    lines.extend(format_numeric_section("Descriptive Stats For Key Numeric Columns", rows, key_columns_present))
    lines.append("")

    per_config_rows = per_config_numeric_summary(rows, key_columns_present)
    lines.append("Per-Config Summary For Key Features")
    for summary_row in per_config_rows:
        config_name = summary_row["config_name"]
        row_count = summary_row["row_count"]
        lines.append(f"  {config_name} (rows={row_count})")
        for feature in key_columns_present:
            lines.append(
                "    "
                f"{feature}: "
                f"count={summary_row[f'{feature}_count']}, "
                f"mean={summary_row[f'{feature}_mean']}, "
                f"min={summary_row[f'{feature}_min']}, "
                f"max={summary_row[f'{feature}_max']}"
            )
    lines.append("")
    lines.append("Generated Files")
    lines.append(f"  report: {REPORT_PATH}")
    lines.append(f"  missing-values csv: {MISSING_CSV_PATH}")
    lines.append(f"  per-config summary csv: {PER_CONFIG_CSV_PATH}")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not DATASET_PATH.exists():
        raise SystemExit(f"Dataset CSV not found: {DATASET_PATH}")

    rows = load_rows(DATASET_PATH)
    report_text = build_report(rows)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_text, encoding="utf-8")

    columns = list(rows[0].keys()) if rows else []
    missing_counts = count_missing(rows, columns)
    missing_rows = [{"column": column, "missing_count": missing_counts[column]} for column in columns]
    per_config_rows = per_config_numeric_summary(rows, [column for column in KEY_NUMERIC_COLUMNS if column in columns])

    write_csv(MISSING_CSV_PATH, missing_rows)
    write_csv(PER_CONFIG_CSV_PATH, per_config_rows)

    print(f"Wrote report to {REPORT_PATH}")
    print(f"Wrote missing-value summary to {MISSING_CSV_PATH}")
    print(f"Wrote per-config summary to {PER_CONFIG_CSV_PATH}")


if __name__ == "__main__":
    main()
