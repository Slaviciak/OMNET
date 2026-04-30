#!/usr/bin/env python3
"""
Generate a lightweight sanity and outcome report for a scenario dataset.

Assumptions:
- The dataset CSV was produced by analysis/build_dataset.py.
- Empty strings represent missing values.
- Only simple summary and data quality checks are needed at this stage.
- The report should stay robust even if some expected columns are missing.
- Recovery and protection outcome fields are treated as project-local
  measurement outputs derived from receiver-side telemetry and controller
  scalars. They remain distinct from the scenario-phase supervision labels.
- Packet-continuity fields use receiver-observed sequence numbers and receive
  timestamps to expose short loss/gap symptoms that may not create a full
  one-second zero-progress window.
- Packet-continuity summaries intentionally separate gaps after the operational
  reference event, after the hard failure, after protection activation, and
  between activation and failure. This keeps activation transition cost visible
  instead of mixing it with post-failure protection benefit.
- Mixed UDP/TCP regional reports include application-endpoint TCP useful-goodput proxy
  fields when present. These are operational simulator-side summaries, not
  protocol-internal TCP restoration measurements.
- Version 1 uses scenario presets and a simple CLI so the same workflow can be
  extended later without changing the reporting style.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
DATASETS_DIR = OUTPUT_ROOT / "datasets"
REPORTS_DIR = OUTPUT_ROOT / "reports"
OUTCOMES_DIR = OUTPUT_ROOT / "outcomes"
DEBUG_OUTPUT_DIR = OUTPUT_ROOT / "debug"
DEFAULT_SCENARIO = "regionalbackbone"

OUTCOME_COLUMNS = [
    "config_name",
    "run_number",
    "protection_mode",
    "protection_activated",
    "protection_activation_time_s",
    "protection_activation_source",
    "protection_action_code",
    "repair_routes_installed",
    "repair_route_count",
    "hard_failure_time_s",
    "protection_activated_before_failure",
    "protection_lead_time_before_failure_s",
    "service_interruption_reference_event",
    "service_interruption_reference_time_s",
    "service_interruption_observed",
    "service_interruption_start_time_s",
    "service_interruption_end_time_s",
    "service_interruption_duration_s",
    "recovery_observed",
    "recovery_time_after_failure_s",
    "zero_progress_window_count_after_reference",
    "max_zero_progress_window_streak_after_reference",
    "throughput_restored_after_failure",
    "packet_sequence_gap_observed_after_reference",
    "packet_sequence_gap_count_after_reference",
    "packet_sequence_gap_total_missing_after_reference",
    "max_packet_sequence_gap_after_reference",
    "max_packet_interarrival_gap_after_reference_s",
    "packet_interarrival_nominal_gap_threshold_s",
    "packet_interarrival_gap_exceedance_count_after_reference",
    "packet_interarrival_gap_exceeded_nominal_threshold",
    "first_packet_after_reference_delay_s",
    "packet_sequence_gap_observed_after_hard_failure",
    "packet_sequence_gap_count_after_hard_failure",
    "packet_sequence_gap_total_missing_after_hard_failure",
    "max_packet_sequence_gap_after_hard_failure",
    "max_packet_interarrival_gap_after_hard_failure_s",
    "packet_interarrival_gap_exceedance_count_after_hard_failure",
    "packet_interarrival_gap_exceeded_nominal_threshold_after_hard_failure",
    "first_packet_after_hard_failure_delay_s",
    "packet_sequence_gap_observed_after_protection_activation",
    "packet_sequence_gap_count_after_protection_activation",
    "packet_sequence_gap_total_missing_after_protection_activation",
    "max_packet_sequence_gap_after_protection_activation",
    "max_packet_interarrival_gap_after_protection_activation_s",
    "packet_interarrival_gap_exceedance_count_after_protection_activation",
    "packet_interarrival_gap_exceeded_nominal_threshold_after_protection_activation",
    "first_packet_after_protection_activation_delay_s",
    "packet_sequence_gap_observed_between_activation_and_failure",
    "packet_sequence_gap_count_between_activation_and_failure",
    "packet_sequence_gap_total_missing_between_activation_and_failure",
    "max_packet_sequence_gap_between_activation_and_failure",
    "max_packet_interarrival_gap_between_activation_and_failure_s",
    "packet_interarrival_gap_exceedance_count_between_activation_and_failure",
    "packet_interarrival_gap_exceeded_nominal_threshold_between_activation_and_failure",
    "first_packet_between_activation_and_failure_delay_s",
    "packet_sequence_gap_observed_after_critical_start",
    "packet_sequence_gap_count_after_critical_start",
    "packet_sequence_gap_total_missing_after_critical_start",
    "max_packet_sequence_gap_after_critical_start",
    "max_packet_interarrival_gap_after_critical_start_s",
    "packet_interarrival_gap_exceedance_count_after_critical_start",
    "packet_interarrival_gap_exceeded_nominal_threshold_after_critical_start",
    "first_packet_after_critical_start_delay_s",
    "tcp_service_interruption_observed",
    "tcp_service_interruption_start_time_s",
    "tcp_service_interruption_end_time_s",
    "tcp_service_interruption_duration_s",
    "tcp_zero_goodput_window_count_after_reference",
    "tcp_max_zero_goodput_window_streak_after_reference",
    "tcp_useful_goodput_restored_after_failure",
    "tcp_endpoint_receive_event_count_after_reference",
    "tcp_first_endpoint_receive_delay_after_reference_s",
    "tcp_max_endpoint_receive_gap_after_reference_s",
    "unnecessary_protection",
    "missed_protection",
]

SCENARIO_PRESETS = {
    "linkdegradation": {
        "dataset_path": DATASETS_DIR / "linkdegradation_dataset.csv",
        "report_path": REPORTS_DIR / "linkdegradation_report.txt",
        "missing_csv_path": DEBUG_OUTPUT_DIR / "linkdegradation_missing_values.csv",
        "per_config_csv_path": DEBUG_OUTPUT_DIR / "linkdegradation_per_config_summary.csv",
        "outcome_csv_path": OUTCOMES_DIR / "linkdegradation_outcome_summary.csv",
        "report_title": "LinkDegradation Dataset Sanity Report",
        "expected_configs": ["MildLinear", "StrongLinear", "UnstableLinear", "StagedRealistic"],
        "key_numeric_columns": [
            "controller_delay_mean_s",
            "controller_packet_error_rate_mean",
            "receiver_total_packet_count",
            "receiver_app0_e2e_delay_mean_s",
            "receiver_app1_e2e_delay_mean_s",
            "service_interruption_duration_s",
            "recovery_time_after_failure_s",
            "packet_sequence_gap_total_missing_after_reference",
            "max_packet_interarrival_gap_after_reference_s",
        ],
    },
    "congestiondegradation": {
        "dataset_path": DATASETS_DIR / "congestiondegradation_dataset.csv",
        "report_path": REPORTS_DIR / "congestiondegradation_report.txt",
        "missing_csv_path": DEBUG_OUTPUT_DIR / "congestiondegradation_missing_values.csv",
        "per_config_csv_path": DEBUG_OUTPUT_DIR / "congestiondegradation_per_config_summary.csv",
        "outcome_csv_path": OUTCOMES_DIR / "congestiondegradation_outcome_summary.csv",
        "report_title": "CongestionDegradation Dataset Sanity Report",
        "expected_configs": ["CongestionDegradation", "CongestionDegradationMild"],
        "key_numeric_columns": [
            "bottleneck_queue_length_mean_pk",
            "bottleneck_queue_bit_length_mean_b",
            "bottleneck_queueing_time_mean_s",
            "receiver_total_packet_count",
            "receiver_app0_e2e_delay_mean_s",
            "receiver_app0_throughput_mean_bps",
            "service_interruption_duration_s",
            "recovery_time_after_failure_s",
            "packet_sequence_gap_total_missing_after_reference",
            "max_packet_interarrival_gap_after_reference_s",
        ],
    },
    "reactivefailure": {
        "dataset_path": DATASETS_DIR / "reactivefailure_dataset.csv",
        "report_path": REPORTS_DIR / "reactivefailure_report.txt",
        "missing_csv_path": DEBUG_OUTPUT_DIR / "reactivefailure_missing_values.csv",
        "per_config_csv_path": DEBUG_OUTPUT_DIR / "reactivefailure_per_config_summary.csv",
        "outcome_csv_path": OUTCOMES_DIR / "reactivefailure_outcome_summary.csv",
        "report_title": "ReactiveFailure Dataset Sanity Report",
        "expected_configs": ["ReactiveFailure"],
        "key_numeric_columns": [
            "receiver_total_packet_count",
            "receiver_app0_throughput_mean_bps",
            "service_interruption_duration_s",
            "recovery_time_after_failure_s",
            "zero_progress_window_count_after_reference",
            "packet_sequence_gap_total_missing_after_reference",
        ],
    },
    "proactiveswitch": {
        "dataset_path": DATASETS_DIR / "proactiveswitch_dataset.csv",
        "report_path": REPORTS_DIR / "proactiveswitch_report.txt",
        "missing_csv_path": DEBUG_OUTPUT_DIR / "proactiveswitch_missing_values.csv",
        "per_config_csv_path": DEBUG_OUTPUT_DIR / "proactiveswitch_per_config_summary.csv",
        "outcome_csv_path": OUTCOMES_DIR / "proactiveswitch_outcome_summary.csv",
        "report_title": "ProactiveSwitch Dataset Sanity Report",
        "expected_configs": ["ProactiveSwitch"],
        "key_numeric_columns": [
            "receiver_total_packet_count",
            "receiver_app0_throughput_mean_bps",
            "protection_lead_time_before_failure_s",
            "service_interruption_duration_s",
            "recovery_time_after_failure_s",
            "packet_sequence_gap_total_missing_after_reference",
        ],
    },
    "regionalbackbone": {
        "dataset_path": DATASETS_DIR / "regionalbackbone_dataset.csv",
        "report_path": REPORTS_DIR / "regionalbackbone_report.txt",
        "missing_csv_path": DEBUG_OUTPUT_DIR / "regionalbackbone_missing_values.csv",
        "per_config_csv_path": DEBUG_OUTPUT_DIR / "regionalbackbone_per_config_summary.csv",
        "outcome_csv_path": OUTCOMES_DIR / "regionalbackbone_outcome_summary.csv",
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
            "service_interruption_duration_s",
            "recovery_time_after_failure_s",
            "protection_lead_time_before_failure_s",
            "packet_sequence_gap_total_missing_after_reference",
            "max_packet_interarrival_gap_after_reference_s",
        ],
    },
    "regionalbackbone_congestion_protection": {
        "dataset_path": DATASETS_DIR / "regionalbackbone_congestion_protection_multirun_dataset.csv",
        "report_path": REPORTS_DIR / "regionalbackbone_congestion_protection_multirun_report.txt",
        "missing_csv_path": DEBUG_OUTPUT_DIR / "regionalbackbone_congestion_protection_multirun_missing_values.csv",
        "per_config_csv_path": DEBUG_OUTPUT_DIR / "regionalbackbone_congestion_protection_multirun_per_config_summary.csv",
        "outcome_csv_path": OUTCOMES_DIR / "regionalbackbone_congestion_protection_multirun_outcome_summary.csv",
        "report_title": "RegionalBackbone Congestion Protection Multi-Run Dataset Sanity Report",
        "expected_configs": [
            "RegionalBackboneCongestionDegradation",
            "RegionalBackboneAiMrceRuleBased",
            "RegionalBackboneAiMrceLogReg",
            "RegionalBackboneAiMrceLinearSvm",
            "RegionalBackboneAiMrceShallowTree",
        ],
        "key_numeric_columns": [
            "receiver_total_packet_count",
            "receiver_app0_e2e_delay_mean_s",
            "receiver_app0_throughput_mean_bps",
            "bottleneck_queue_length_mean_pk",
            "bottleneck_queue_bit_length_mean_b",
            "bottleneck_queueing_time_mean_s",
            "service_interruption_duration_s",
            "recovery_time_after_failure_s",
            "protection_lead_time_before_failure_s",
            "packet_sequence_gap_total_missing_after_reference",
            "max_packet_sequence_gap_after_reference",
            "max_packet_interarrival_gap_after_reference_s",
        ],
    },
    "regionalbackbone_mixed_traffic_protection": {
        "dataset_path": DATASETS_DIR / "regionalbackbone_mixed_traffic_protection_multirun_dataset.csv",
        "report_path": REPORTS_DIR / "regionalbackbone_mixed_traffic_protection_multirun_report.txt",
        "missing_csv_path": DEBUG_OUTPUT_DIR / "regionalbackbone_mixed_traffic_protection_multirun_missing_values.csv",
        "per_config_csv_path": DEBUG_OUTPUT_DIR / "regionalbackbone_mixed_traffic_protection_multirun_per_config_summary.csv",
        "outcome_csv_path": OUTCOMES_DIR / "regionalbackbone_mixed_traffic_protection_multirun_outcome_summary.csv",
        "report_title": "RegionalBackbone Mixed UDP/TCP Protection Multi-Run Dataset Sanity Report",
        "expected_configs": [
            "RegionalBackboneMixedTrafficCongestionDegradation",
            "RegionalBackboneAiMrceRuleBasedMixedTraffic",
            "RegionalBackboneAiMrceLogRegMixedTraffic",
        ],
        "key_numeric_columns": [
            "receiver_total_packet_count",
            "receiver_app0_e2e_delay_mean_s",
            "receiver_app0_throughput_mean_bps",
            "receiver_app3_goodput_mean_bps",
            "receiver_app4_goodput_mean_bps",
            "receiver_tcp_goodput_mean_bps",
            "bottleneck_queue_length_mean_pk",
            "bottleneck_queue_bit_length_mean_b",
            "bottleneck_queueing_time_mean_s",
            "service_interruption_duration_s",
            "tcp_service_interruption_duration_s",
            "tcp_zero_goodput_window_count_after_reference",
            "recovery_time_after_failure_s",
            "protection_lead_time_before_failure_s",
            "packet_sequence_gap_total_missing_after_reference",
            "max_packet_sequence_gap_after_reference",
            "max_packet_interarrival_gap_after_reference_s",
            "tcp_max_endpoint_receive_gap_after_reference_s",
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
        help="Input dataset CSV path. Defaults to analysis/output/datasets/<scenario>_dataset.csv.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Report text path. Defaults to analysis/output/reports/<scenario>_report.txt.",
    )
    parser.add_argument(
        "--missing-output",
        type=Path,
        help="CSV path for missing-value counts. Defaults to analysis/output/debug/<scenario>_missing_values.csv.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="CSV path for per-config numeric summaries. Defaults to analysis/output/debug/<scenario>_per_config_summary.csv.",
    )
    parser.add_argument(
        "--outcome-output",
        type=Path,
        help="CSV path for one-row-per-run protection and recovery outcome summaries.",
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


def parse_flag(value: str | None) -> int | None:
    numeric_value = parse_float(value)
    if numeric_value is None:
        return None
    return 1 if numeric_value >= 0.5 else 0


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


def dedupe_run_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_run: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("config_name", ""), row.get("run_number", ""))
        by_run.setdefault(key, row)
    return [by_run[key] for key in sorted(by_run, key=lambda item: (item[0], item[1]))]


def outcome_csv_rows(run_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for run_row in run_rows:
        row: dict[str, str] = {}
        for column in OUTCOME_COLUMNS:
            if column in run_row:
                row[column] = run_row.get(column, "")
        rows.append(row)
    return rows


def true_flag_count(rows: list[dict[str, str]], column: str) -> int:
    return sum(1 for row in rows if parse_flag(row.get(column)) == 1)


def first_nonempty(rows: list[dict[str, str]], column: str) -> str:
    for row in rows:
        value = row.get(column, "")
        if value != "":
            return value
    return ""


def per_config_outcome_summary(run_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in run_rows:
        grouped[row.get("config_name", "")].append(row)

    summary_rows: list[dict[str, object]] = []
    numeric_columns = [
        "protection_lead_time_before_failure_s",
        "service_interruption_duration_s",
        "recovery_time_after_failure_s",
        "zero_progress_window_count_after_reference",
        "max_zero_progress_window_streak_after_reference",
        "packet_sequence_gap_count_after_reference",
        "packet_sequence_gap_total_missing_after_reference",
        "max_packet_sequence_gap_after_reference",
        "max_packet_interarrival_gap_after_reference_s",
        "packet_interarrival_gap_exceedance_count_after_reference",
        "first_packet_after_reference_delay_s",
        "packet_sequence_gap_count_after_hard_failure",
        "packet_sequence_gap_total_missing_after_hard_failure",
        "max_packet_sequence_gap_after_hard_failure",
        "max_packet_interarrival_gap_after_hard_failure_s",
        "packet_interarrival_gap_exceedance_count_after_hard_failure",
        "first_packet_after_hard_failure_delay_s",
        "packet_sequence_gap_count_after_protection_activation",
        "packet_sequence_gap_total_missing_after_protection_activation",
        "max_packet_sequence_gap_after_protection_activation",
        "max_packet_interarrival_gap_after_protection_activation_s",
        "packet_interarrival_gap_exceedance_count_after_protection_activation",
        "first_packet_after_protection_activation_delay_s",
        "packet_sequence_gap_count_between_activation_and_failure",
        "packet_sequence_gap_total_missing_between_activation_and_failure",
        "max_packet_sequence_gap_between_activation_and_failure",
        "max_packet_interarrival_gap_between_activation_and_failure_s",
        "packet_interarrival_gap_exceedance_count_between_activation_and_failure",
        "first_packet_between_activation_and_failure_delay_s",
        "packet_sequence_gap_count_after_critical_start",
        "packet_sequence_gap_total_missing_after_critical_start",
        "max_packet_sequence_gap_after_critical_start",
        "max_packet_interarrival_gap_after_critical_start_s",
        "packet_interarrival_gap_exceedance_count_after_critical_start",
        "first_packet_after_critical_start_delay_s",
        "repair_route_count",
        "tcp_service_interruption_duration_s",
        "tcp_zero_goodput_window_count_after_reference",
        "tcp_max_zero_goodput_window_streak_after_reference",
        "tcp_endpoint_receive_event_count_after_reference",
        "tcp_first_endpoint_receive_delay_after_reference_s",
        "tcp_max_endpoint_receive_gap_after_reference_s",
    ]
    for config_name in sorted(grouped):
        config_rows = grouped[config_name]
        summary_row: dict[str, object] = {
            "config_name": config_name,
            "protection_mode": first_nonempty(config_rows, "protection_mode"),
            "run_count": len(config_rows),
            "protection_activated_runs": true_flag_count(config_rows, "protection_activated"),
            "protection_before_failure_runs": true_flag_count(config_rows, "protection_activated_before_failure"),
            "repair_routes_installed_runs": true_flag_count(config_rows, "repair_routes_installed"),
            "service_interruption_observed_runs": true_flag_count(config_rows, "service_interruption_observed"),
            "recovery_observed_runs": true_flag_count(config_rows, "recovery_observed"),
            "throughput_restored_after_failure_runs": true_flag_count(config_rows, "throughput_restored_after_failure"),
            "packet_sequence_gap_observed_after_reference_runs": true_flag_count(config_rows, "packet_sequence_gap_observed_after_reference"),
            "packet_interarrival_gap_exceeded_nominal_threshold_runs": true_flag_count(config_rows, "packet_interarrival_gap_exceeded_nominal_threshold"),
            "packet_sequence_gap_observed_after_hard_failure_runs": true_flag_count(config_rows, "packet_sequence_gap_observed_after_hard_failure"),
            "packet_sequence_gap_observed_after_protection_activation_runs": true_flag_count(config_rows, "packet_sequence_gap_observed_after_protection_activation"),
            "packet_sequence_gap_observed_between_activation_and_failure_runs": true_flag_count(config_rows, "packet_sequence_gap_observed_between_activation_and_failure"),
            "packet_sequence_gap_observed_after_critical_start_runs": true_flag_count(config_rows, "packet_sequence_gap_observed_after_critical_start"),
            "tcp_service_interruption_observed_runs": true_flag_count(config_rows, "tcp_service_interruption_observed"),
            "tcp_useful_goodput_restored_after_failure_runs": true_flag_count(config_rows, "tcp_useful_goodput_restored_after_failure"),
            "missed_protection_runs": true_flag_count(config_rows, "missed_protection"),
            "unnecessary_protection_runs": true_flag_count(config_rows, "unnecessary_protection"),
        }
        for column in numeric_columns:
            stats = describe_numeric(numeric_values(config_rows, column))
            summary_row[f"{column}_count"] = stats["count"]
            summary_row[f"{column}_mean"] = stats["mean"]
            summary_row[f"{column}_min"] = stats["min"]
            summary_row[f"{column}_max"] = stats["max"]
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


def format_outcome_summary_section(run_rows: list[dict[str, str]]) -> list[str]:
    lines = ["Run-Level Outcome Summary"]
    if not run_rows:
        lines.append("  <none>")
        return lines

    lines.append("  Method note:")
    lines.append("    Outcome fields are derived from receiver-side continuity and throughput plus")
    lines.append("    known scripted event times and shared controller scalars where available.")
    lines.append("    They are project-local operational metrics, not RFC-defined protocol fields.")
    lines.append("    Packet sequence-gap fields expose receiver-observed packet continuity loss")
    lines.append("    that can be hidden by coarse one-second service-availability windows.")
    lines.append("    TCP fields, when present, are application-endpoint useful-goodput proxies from INET")
    lines.append("    application vectors and are not protocol-internal TCP recovery counters.")

    for summary_row in per_config_outcome_summary(run_rows):
        config_name = summary_row["config_name"]
        lines.append(
            f"  {config_name} "
            f"(mode={summary_row['protection_mode']}, runs={summary_row['run_count']})"
        )
        lines.append(
            "    "
            f"protection_activated_runs={summary_row['protection_activated_runs']}, "
            f"protection_before_failure_runs={summary_row['protection_before_failure_runs']}, "
            f"service_interruption_observed_runs={summary_row['service_interruption_observed_runs']}, "
            f"recovery_observed_runs={summary_row['recovery_observed_runs']}"
        )
        lines.append(
            "    "
            f"throughput_restored_after_failure_runs={summary_row['throughput_restored_after_failure_runs']}, "
            f"packet_sequence_gap_observed_runs={summary_row['packet_sequence_gap_observed_after_reference_runs']}, "
            f"tcp_useful_goodput_restored_after_failure_runs={summary_row['tcp_useful_goodput_restored_after_failure_runs']}, "
            f"missed_protection_runs={summary_row['missed_protection_runs']}, "
            f"unnecessary_protection_runs={summary_row['unnecessary_protection_runs']}"
        )
        lines.append(
            "    "
            f"tcp_service_interruption_observed_runs={summary_row['tcp_service_interruption_observed_runs']}, "
            f"tcp_service_interruption_duration_s_mean={summary_row['tcp_service_interruption_duration_s_mean']}, "
            f"tcp_zero_goodput_window_count_after_reference_mean={summary_row['tcp_zero_goodput_window_count_after_reference_mean']}"
        )
        lines.append(
            "    "
            f"service_interruption_duration_s_mean={summary_row['service_interruption_duration_s_mean']}, "
            f"recovery_time_after_failure_s_mean={summary_row['recovery_time_after_failure_s_mean']}, "
            f"protection_lead_time_before_failure_s_mean={summary_row['protection_lead_time_before_failure_s_mean']}"
        )
        lines.append(
            "    "
            f"packet_sequence_gap_total_missing_after_reference_mean={summary_row['packet_sequence_gap_total_missing_after_reference_mean']}, "
            f"max_packet_sequence_gap_after_reference_mean={summary_row['max_packet_sequence_gap_after_reference_mean']}, "
            f"max_packet_interarrival_gap_after_reference_s_mean={summary_row['max_packet_interarrival_gap_after_reference_s_mean']}"
        )
        lines.append(
            "    "
            f"packet_sequence_gap_total_missing_after_hard_failure_mean={summary_row['packet_sequence_gap_total_missing_after_hard_failure_mean']}, "
            f"max_packet_sequence_gap_after_hard_failure_mean={summary_row['max_packet_sequence_gap_after_hard_failure_mean']}, "
            f"packet_sequence_gap_total_missing_between_activation_and_failure_mean={summary_row['packet_sequence_gap_total_missing_between_activation_and_failure_mean']}"
        )
        lines.append(
            "    "
            f"packet_sequence_gap_total_missing_after_protection_activation_mean={summary_row['packet_sequence_gap_total_missing_after_protection_activation_mean']}, "
            f"packet_sequence_gap_total_missing_after_critical_start_mean={summary_row['packet_sequence_gap_total_missing_after_critical_start_mean']}, "
            f"max_packet_sequence_gap_after_critical_start_mean={summary_row['max_packet_sequence_gap_after_critical_start_mean']}"
        )
        lines.append(
            "    "
            f"zero_progress_window_count_after_reference_mean={summary_row['zero_progress_window_count_after_reference_mean']}, "
            f"max_zero_progress_window_streak_after_reference_mean={summary_row['max_zero_progress_window_streak_after_reference_mean']}"
        )
        lines.append(
            "    "
            f"packet_interarrival_gap_exceeded_nominal_threshold_runs={summary_row['packet_interarrival_gap_exceeded_nominal_threshold_runs']}, "
            f"tcp_max_endpoint_receive_gap_after_reference_s_mean={summary_row['tcp_max_endpoint_receive_gap_after_reference_s_mean']}"
        )
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
    outcome_csv_path: Path,
) -> str:
    if not rows:
        return "Dataset is empty.\n"

    columns = list(rows[0].keys())
    run_rows = dedupe_run_rows(rows)
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
    lines.append(f"  distinct runs: {len(run_rows)}")
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
    lines.extend(format_outcome_summary_section(run_rows))
    lines.append("")
    lines.append("Generated Files")
    lines.append(f"  report: {report_path}")
    lines.append(f"  missing-values csv: {missing_csv_path}")
    lines.append(f"  per-config summary csv: {per_config_csv_path}")
    lines.append(f"  outcome summary csv: {outcome_csv_path}")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    preset = get_scenario_preset(args.scenario)

    dataset_path = args.input if args.input is not None else preset["dataset_path"]
    report_path = args.output if args.output is not None else preset["report_path"]
    missing_csv_path = args.missing_output if args.missing_output is not None else preset["missing_csv_path"]
    per_config_csv_path = args.summary_output if args.summary_output is not None else preset["per_config_csv_path"]
    outcome_csv_path = args.outcome_output if args.outcome_output is not None else preset["outcome_csv_path"]
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
        outcome_csv_path,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    columns = list(rows[0].keys()) if rows else []
    missing_counts = count_missing(rows, columns)
    missing_rows = [{"column": column, "missing_count": missing_counts[column]} for column in columns]
    per_config_rows = per_config_numeric_summary(rows, [column for column in key_numeric_columns if column in columns])
    run_rows = dedupe_run_rows(rows)
    outcome_rows = outcome_csv_rows(run_rows)

    write_csv(missing_csv_path, missing_rows)
    write_csv(per_config_csv_path, per_config_rows)
    write_csv(outcome_csv_path, outcome_rows)

    print(f"Wrote report to {report_path}")
    print(f"Wrote missing-value summary to {missing_csv_path}")
    print(f"Wrote per-config summary to {per_config_csv_path}")
    print(f"Wrote outcome summary to {outcome_csv_path}")


if __name__ == "__main__":
    main()
