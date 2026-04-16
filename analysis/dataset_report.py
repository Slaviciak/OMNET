#!/usr/bin/env python3
"""
Generate a lightweight sanity report for a scenario dataset.

Assumptions:
- The dataset CSV was produced by analysis/build_dataset.py.
- Empty strings represent missing values.
- Only simple summary and data quality checks are needed at this stage.
- The report should stay robust even if some expected columns are missing.
- Version 1 uses scenario presets and a simple CLI so the
  same workflow can be extended later without changing the reporting style.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = "linkdegradation"

SCENARIO_PRESETS = {
    "linkdegradation": {
        "dataset_path": PROJECT_ROOT / "analysis" / "output" / "linkdegradation_dataset.csv",
        "report_path": PROJECT_ROOT / "analysis" / "output" / "linkdegradation_report.txt",
        "missing_csv_path": PROJECT_ROOT / "analysis" / "output" / "linkdegradation_missing_values.csv",
        "per_config_csv_path": PROJECT_ROOT / "analysis" / "output" / "linkdegradation_per_config_summary.csv",
        "report_title": "LinkDegradation Dataset Sanity Report",
        "expected_configs": ["MildLinear", "StrongLinear", "UnstableLinear", "StagedRealistic"],
        "key_numeric_columns": [
            "controller_delay_mean_s",
            "controller_packet_error_rate_mean",
            "receiver_total_packet_count",
            "receiver_app0_e2e_delay_mean_s",
            "receiver_app1_e2e_delay_mean_s",
        ],
    },
    "congestiondegradation": {
        "dataset_path": PROJECT_ROOT / "analysis" / "output" / "congestiondegradation_dataset.csv",
        "report_path": PROJECT_ROOT / "analysis" / "output" / "congestiondegradation_report.txt",
        "missing_csv_path": PROJECT_ROOT / "analysis" / "output" / "congestiondegradation_missing_values.csv",
        "per_config_csv_path": PROJECT_ROOT / "analysis" / "output" / "congestiondegradation_per_config_summary.csv",
        "report_title": "CongestionDegradation Dataset Sanity Report",
        "expected_configs": ["CongestionDegradation", "CongestionDegradationMild"],
        "key_numeric_columns": [
            "bottleneck_queue_length_mean_pk",
            "bottleneck_queue_bit_length_mean_b",
            "bottleneck_queueing_time_mean_s",
            "receiver_total_packet_count",
            "receiver_app0_e2e_delay_mean_s",
            "receiver_app0_throughput_mean_bps",
        ],
    },
    "regionalbackbone": {
        "dataset_path": PROJECT_ROOT / "analysis" / "output" / "regionalbackbone_dataset.csv",
        "report_path": PROJECT_ROOT / "analysis" / "output" / "regionalbackbone_report.txt",
        "missing_csv_path": PROJECT_ROOT / "analysis" / "output" / "regionalbackbone_missing_values.csv",
        "per_config_csv_path": PROJECT_ROOT / "analysis" / "output" / "regionalbackbone_per_config_summary.csv",
        "report_title": "RegionalBackbone Dataset Sanity Report",
        "expected_configs": [
            "RegionalBackboneBaseline",
            "RegionalBackboneReactiveFailure",
            "RegionalBackboneControlledDegradation",
            "RegionalBackboneCongestionDegradation",
        ],
        "key_numeric_columns": [
            "receiver_total_packet_count",
            "receiver_app0_e2e_delay_mean_s",
            "receiver_app0_throughput_mean_bps",
            "controller_delay_mean_s",
            "controller_packet_error_rate_mean",
            "bottleneck_queue_length_mean_pk",
            "bottleneck_queue_bit_length_mean_b",
            "bottleneck_queueing_time_mean_s",
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a lightweight sanity report for a dataset CSV.")
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help=f"Scenario preset to use for defaults. Currently supported: {', '.join(sorted(SCENARIO_PRESETS))}.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Input dataset CSV path. Defaults to analysis/output/<scenario>_dataset.csv.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Report text path. Defaults to analysis/output/<scenario>_report.txt.",
    )
    parser.add_argument(
        "--missing-output",
        type=Path,
        help="CSV path for missing-value counts. Defaults to analysis/output/<scenario>_missing_values.csv.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="CSV path for per-config numeric summaries. Defaults to analysis/output/<scenario>_per_config_summary.csv.",
    )
    return parser.parse_args()


def get_scenario_preset(scenario: str) -> dict[str, object]:
    preset = SCENARIO_PRESETS.get(scenario)
    if preset is None:
        supported = ", ".join(sorted(SCENARIO_PRESETS))
        raise SystemExit(f"Unsupported scenario '{scenario}'. Supported scenarios: {supported}")
    return preset


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


def build_report(
    rows: list[dict[str, str]],
    report_title: str,
    expected_configs: list[str],
    key_numeric_columns: list[str],
    dataset_path: Path,
    report_path: Path,
    missing_csv_path: Path,
    per_config_csv_path: Path,
) -> str:
    if not rows:
        return "Dataset is empty.\n"

    columns = list(rows[0].keys())
    config_counts = Counter(row.get("config_name", "") for row in rows)
    label_counts = Counter(row.get("label", "") for row in rows)
    run_counts = Counter(row.get("run_number", "") for row in rows)
    missing_counts = count_missing(rows, columns)
    missing_expected_configs = [config for config in expected_configs if config not in config_counts]
    key_columns_present = [column for column in key_numeric_columns if column in columns]
    key_columns_missing = [column for column in key_numeric_columns if column not in columns]

    lines: list[str] = []
    lines.append(report_title)
    lines.append("=" * len(report_title))
    lines.append("")
    lines.append("Input Dataset")
    lines.append(f"  {dataset_path}")
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
    lines.append(f"  report: {report_path}")
    lines.append(f"  missing-values csv: {missing_csv_path}")
    lines.append(f"  per-config summary csv: {per_config_csv_path}")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    preset = get_scenario_preset(args.scenario)

    dataset_path = args.input if args.input is not None else preset["dataset_path"]
    report_path = args.output if args.output is not None else preset["report_path"]
    missing_csv_path = args.missing_output if args.missing_output is not None else preset["missing_csv_path"]
    per_config_csv_path = args.summary_output if args.summary_output is not None else preset["per_config_csv_path"]
    report_title = preset["report_title"]
    expected_configs = preset["expected_configs"]
    key_numeric_columns = preset["key_numeric_columns"]

    if not dataset_path.exists():
        raise SystemExit(f"Dataset CSV not found: {dataset_path}")

    rows = load_rows(dataset_path)
    report_text = build_report(
        rows,
        report_title,
        expected_configs,
        key_numeric_columns,
        dataset_path,
        report_path,
        missing_csv_path,
        per_config_csv_path,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    columns = list(rows[0].keys()) if rows else []
    missing_counts = count_missing(rows, columns)
    missing_rows = [{"column": column, "missing_count": missing_counts[column]} for column in columns]
    per_config_rows = per_config_numeric_summary(rows, [column for column in key_numeric_columns if column in columns])

    write_csv(missing_csv_path, missing_rows)
    write_csv(per_config_csv_path, per_config_rows)

    print(f"Wrote report to {report_path}")
    print(f"Wrote missing-value summary to {missing_csv_path}")
    print(f"Wrote per-config summary to {per_config_csv_path}")


if __name__ == "__main__":
    main()
