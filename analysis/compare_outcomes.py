#!/usr/bin/env python3
"""
Compare run-level protection and recovery outcome summaries.

Assumptions:
- Inputs are one-row-per-run CSV files produced by analysis/dataset_report.py.
- This is a project-local practical comparison layer for internal mechanism
  evaluation. It does not change simulator behavior, routing logic, or the
  offline classifier training workflow.
- The underlying outcome metrics remain operational simulator-side definitions
  derived from observable receiver-side telemetry plus known scripted event
  metadata and shared controller scalars where available.
- These summaries are descriptive only. The script does not claim statistical
  significance or universal properties of FRR mechanisms.
- Comparison cohorts are explicit project-local grouping rules that keep unlike
  scenarios separate so the report does not silently average incompatible runs.
- Mixed UDP/TCP regional cohorts include optional application-endpoint TCP
  useful-goodput proxy fields. Those fields are descriptive and do not imply
  protocol-standard TCP recovery measurements.
- Packet-continuity fields summarize receiver-observed sequence-number and
  interarrival gaps. They are descriptive evidence of application delivery
  disruption, not protocol-standard restoration timers.
- The after_reference continuity fields preserve the operational reference used
  for each run, while after_hard_failure and activation-to-failure fields keep
  post-failure protection benefit separate from pre-failure switch penalty.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
OUTCOMES_DIR = OUTPUT_ROOT / "outcomes"

SUPPORTED_SCENARIOS = (
    "regionalbackbone",
    "regionalbackbone_congestion_protection",
    "regionalbackbone_mixed_traffic_protection",
    "reactivefailure",
    "proactiveswitch",
)
DEFAULT_SCENARIOS = (
    "regionalbackbone",
    "regionalbackbone_congestion_protection",
    "regionalbackbone_mixed_traffic_protection",
)

BASE_NUMERIC_METRICS = [
    "protection_activation_time_s",
    "protection_lead_time_before_failure_s",
    "service_interruption_duration_s",
    "recovery_time_after_failure_s",
    "zero_progress_window_count_after_reference",
    "max_zero_progress_window_streak_after_reference",
]

PACKET_NUMERIC_METRICS = [
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
]

TCP_NUMERIC_METRICS = [
    "tcp_service_interruption_duration_s",
    "tcp_zero_goodput_window_count_after_reference",
    "tcp_max_zero_goodput_window_streak_after_reference",
    "tcp_endpoint_receive_event_count_after_reference",
    "tcp_first_endpoint_receive_delay_after_reference_s",
    "tcp_max_endpoint_receive_gap_after_reference_s",
]

PROTECTION_ACTION_NUMERIC_METRICS = [
    "repair_route_count",
]

NUMERIC_METRICS = BASE_NUMERIC_METRICS + PROTECTION_ACTION_NUMERIC_METRICS + PACKET_NUMERIC_METRICS + TCP_NUMERIC_METRICS

BASE_FLAG_METRICS = [
    "protection_activated",
    "protection_activated_before_failure",
    "service_interruption_observed",
    "recovery_observed",
    "throughput_restored_after_failure",
    "missed_protection",
    "unnecessary_protection",
]

PACKET_FLAG_METRICS = [
    "packet_sequence_gap_observed_after_reference",
    "packet_interarrival_gap_exceeded_nominal_threshold",
    "packet_sequence_gap_observed_after_hard_failure",
    "packet_interarrival_gap_exceeded_nominal_threshold_after_hard_failure",
    "packet_sequence_gap_observed_after_protection_activation",
    "packet_interarrival_gap_exceeded_nominal_threshold_after_protection_activation",
    "packet_sequence_gap_observed_between_activation_and_failure",
    "packet_interarrival_gap_exceeded_nominal_threshold_between_activation_and_failure",
    "packet_sequence_gap_observed_after_critical_start",
    "packet_interarrival_gap_exceeded_nominal_threshold_after_critical_start",
]

TCP_FLAG_METRICS = [
    "tcp_service_interruption_observed",
    "tcp_useful_goodput_restored_after_failure",
]

PROTECTION_ACTION_FLAG_METRICS = [
    "repair_routes_installed",
]

FLAG_METRICS = BASE_FLAG_METRICS + PROTECTION_ACTION_FLAG_METRICS + PACKET_FLAG_METRICS + TCP_FLAG_METRICS

BASE_PASSTHROUGH_COLUMNS = [
    "config_name",
    "run_number",
    "protection_mode",
    "protection_activation_source",
    "hard_failure_time_s",
] + BASE_NUMERIC_METRICS + BASE_FLAG_METRICS

OPTIONAL_PASSTHROUGH_COLUMNS = (
    ["protection_action_code"]
    + PROTECTION_ACTION_NUMERIC_METRICS
    + PROTECTION_ACTION_FLAG_METRICS
    + PACKET_NUMERIC_METRICS
    + PACKET_FLAG_METRICS
    + TCP_NUMERIC_METRICS
    + TCP_FLAG_METRICS
)
PASSTHROUGH_COLUMNS = BASE_PASSTHROUGH_COLUMNS + OPTIONAL_PASSTHROUGH_COLUMNS

REQUIRED_COLUMNS = set(BASE_PASSTHROUGH_COLUMNS)

SCENARIO_PRESETS = {
    "regionalbackbone": OUTCOMES_DIR / "regionalbackbone_outcome_summary.csv",
    "regionalbackbone_congestion_protection": OUTCOMES_DIR / "regionalbackbone_congestion_protection_multirun_outcome_summary.csv",
    "regionalbackbone_mixed_traffic_protection": OUTCOMES_DIR / "regionalbackbone_mixed_traffic_protection_multirun_outcome_summary.csv",
    "reactivefailure": OUTCOMES_DIR / "reactivefailure_outcome_summary.csv",
    "proactiveswitch": OUTCOMES_DIR / "proactiveswitch_outcome_summary.csv",
}

MECHANISM_LABELS = {
    "reactive_only": "Reactive baseline",
    "deterministic_admin_protection": "Deterministic proactive baseline",
    "aimrce_rule_based": "AI-MRCE rule-based",
    "aimrce_logistic_regression": "AI-MRCE logistic-regression",
    "aimrce_linear_svm": "AI-MRCE linear-SVM",
    "aimrce_shallow_tree": "AI-MRCE shallow-tree",
    "no_protection_baseline": "No-protection baseline",
}

MECHANISM_ORDER = {
    "no_protection_baseline": 0,
    "reactive_only": 1,
    "deterministic_admin_protection": 2,
    "aimrce_rule_based": 3,
    "aimrce_logistic_regression": 4,
    "aimrce_linear_svm": 5,
    "aimrce_shallow_tree": 6,
}

COHORT_LABELS = {
    "small_topology_primary_path_failure": "Small-topology primary-path failure cohort",
    "regionalbackbone_no_protection_baseline": "Regional backbone no-protection baseline cohort",
    "regionalbackbone_reactive_failure": "Regional backbone reactive-failure cohort",
    "regionalbackbone_controlled_degradation": "Regional backbone controlled-degradation cohort",
    "regionalbackbone_congestion_single_run": "Regional backbone congestion single-run evaluation",
    "regionalbackbone_aimrce_single_run": "Regional backbone AI-MRCE single-run evaluation",
    "regionalbackbone_congestion_protection": "Regional backbone congestion protection cohort",
    "regionalbackbone_mixed_traffic_protection": "Regional backbone mixed UDP/TCP protection cohort",
    "regionalbackbone_other": "Regional backbone other cohort",
}

COHORT_ORDER = {
    "small_topology_primary_path_failure": 0,
    "regionalbackbone_no_protection_baseline": 1,
    "regionalbackbone_reactive_failure": 2,
    "regionalbackbone_controlled_degradation": 3,
    "regionalbackbone_congestion_single_run": 4,
    "regionalbackbone_aimrce_single_run": 5,
    "regionalbackbone_congestion_protection": 6,
    "regionalbackbone_mixed_traffic_protection": 7,
    "regionalbackbone_other": 8,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare run-level protection and recovery outcomes across baseline and AI-MRCE summaries."
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        type=Path,
        help=(
            "Explicit *_outcome_summary.csv files to compare. If omitted, the "
            "script uses the preset paths for the selected scenarios."
        ),
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=list(DEFAULT_SCENARIOS),
        choices=SUPPORTED_SCENARIOS,
        help="Scenario presets to include when --inputs is not provided.",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=OUTCOMES_DIR / "outcome_comparison",
        help="Output prefix for the consolidated run table, summary CSV, and text report.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip preset or explicit input files that are missing instead of failing.",
    )
    return parser.parse_args()


def humanize_identifier(value: str) -> str:
    return value.replace("_", " ").strip().title()


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


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def resolve_input_paths(args: argparse.Namespace) -> tuple[list[Path], list[str]]:
    selected_paths = list(args.inputs) if args.inputs else [SCENARIO_PRESETS[scenario] for scenario in args.scenarios]
    resolved_paths: list[Path] = []
    skipped_paths: list[str] = []

    for path in selected_paths:
        if path.exists():
            resolved_paths.append(path)
            continue
        if args.allow_missing:
            skipped_paths.append(str(path))
            continue
        raise SystemExit(f"Outcome summary CSV not found: {path}")

    if not resolved_paths:
        raise SystemExit("No outcome summary CSV inputs were available after applying the current filters.")

    return resolved_paths, skipped_paths


def validate_columns(path: Path, fieldnames: list[str]) -> None:
    missing_columns = sorted(REQUIRED_COLUMNS.difference(fieldnames))
    if missing_columns:
        raise SystemExit(
            "Outcome summary is missing required columns for comparison "
            f"({path}): {', '.join(missing_columns)}"
        )


def infer_scenario_name(path: Path, rows: list[dict[str, str]]) -> str:
    stem_lower = path.stem.lower()
    for scenario in sorted(SUPPORTED_SCENARIOS, key=len, reverse=True):
        if scenario in stem_lower:
            return scenario

    config_names = {row.get("config_name", "") for row in rows}
    if any(config_name.startswith("RegionalBackbone") for config_name in config_names):
        return "regionalbackbone"
    if "ReactiveFailure" in config_names:
        return "reactivefailure"
    if "ProactiveSwitch" in config_names:
        return "proactiveswitch"

    raise SystemExit(f"Could not infer the scenario group for outcome summary: {path}")


def normalize_mechanism_family(protection_mode: str, config_name: str) -> str:
    normalized_mode = protection_mode.strip()
    if normalized_mode:
        return normalized_mode

    # Fallback for older or manually edited summary files where the explicit
    # mechanism field might be absent. The preferred path is still the
    # protection_mode value written by the current dataset/report pipeline.
    if config_name in {
        "ReactiveFailure",
        "RegionalBackboneReactiveFailure",
        "RegionalBackboneMixedTrafficCongestionDegradation",
    }:
        return "reactive_only"
    if config_name == "ProactiveSwitch":
        return "deterministic_admin_protection"
    if config_name in {"RegionalBackboneAiMrceRuleBased", "RegionalBackboneAiMrceRuleBasedMixedTraffic"}:
        return "aimrce_rule_based"
    if config_name in {"RegionalBackboneAiMrceLogReg", "RegionalBackboneAiMrceLogRegMixedTraffic"}:
        return "aimrce_logistic_regression"
    if config_name == "RegionalBackboneAiMrceLinearSvm":
        return "aimrce_linear_svm"
    if config_name == "RegionalBackboneAiMrceShallowTree":
        return "aimrce_shallow_tree"
    if config_name.startswith("RegionalBackboneAiMrce"):
        return "aimrce_runtime_candidate"
    if config_name == "RegionalBackboneBaseline":
        return "no_protection_baseline"
    return "unknown_mechanism"


def resolve_comparison_cohort(scenario_name: str, config_name: str, mechanism_family: str) -> str:
    # These cohorts are project-local analysis buckets for internal comparison.
    # They intentionally preserve scenario/context boundaries instead of
    # collapsing every run with the same mechanism label into one global mean.
    if scenario_name in {"reactivefailure", "proactiveswitch"}:
        return "small_topology_primary_path_failure"

    if scenario_name == "regionalbackbone_mixed_traffic_protection":
        return "regionalbackbone_mixed_traffic_protection"

    if scenario_name == "regionalbackbone":
        if config_name == "RegionalBackboneBaseline" or mechanism_family == "no_protection_baseline":
            return "regionalbackbone_no_protection_baseline"
        if config_name == "RegionalBackboneReactiveFailure":
            return "regionalbackbone_reactive_failure"
        if config_name == "RegionalBackboneControlledDegradation":
            return "regionalbackbone_controlled_degradation"
        if config_name == "RegionalBackboneCongestionDegradation":
            return "regionalbackbone_congestion_single_run"
        if config_name.startswith("RegionalBackboneAiMrce") or mechanism_family.startswith("aimrce_"):
            return "regionalbackbone_aimrce_single_run"
        return "regionalbackbone_other"

    if scenario_name == "regionalbackbone_congestion_protection":
        if config_name == "RegionalBackboneCongestionDegradation":
            return "regionalbackbone_congestion_protection"
        if config_name.startswith("RegionalBackboneAiMrce") or mechanism_family.startswith("aimrce_"):
            return "regionalbackbone_congestion_protection"
        return "regionalbackbone_other"

    return f"{scenario_name}_other"


def normalize_run_rows(path: Path, rows: list[dict[str, str]]) -> list[dict[str, object]]:
    scenario_name = infer_scenario_name(path, rows)
    normalized_rows: list[dict[str, object]] = []

    for row in rows:
        mechanism_family = normalize_mechanism_family(row.get("protection_mode", ""), row.get("config_name", ""))
        comparison_cohort = resolve_comparison_cohort(
            scenario_name=scenario_name,
            config_name=row.get("config_name", ""),
            mechanism_family=mechanism_family,
        )

        normalized_row: dict[str, object] = {
            "source_file": str(path),
            "source_file_label": path.name,
            "source_dataset_variant": path.stem,
            "source_scenario": scenario_name,
            "comparison_cohort": comparison_cohort,
            "comparison_cohort_label": COHORT_LABELS.get(comparison_cohort, humanize_identifier(comparison_cohort)),
            "config_name": row.get("config_name", ""),
            "run_number": row.get("run_number", ""),
            "mechanism_family": mechanism_family,
            "mechanism_label": MECHANISM_LABELS.get(mechanism_family, humanize_identifier(mechanism_family)),
            "protection_mode_original": row.get("protection_mode", ""),
        }

        for column in PASSTHROUGH_COLUMNS:
            normalized_row[column] = row.get(column, "")

        normalized_rows.append(normalized_row)

    return normalized_rows


def collect_rows(paths: list[Path]) -> list[dict[str, object]]:
    normalized_rows: list[dict[str, object]] = []
    seen_run_keys: dict[tuple[str, str, str], str] = {}

    for path in paths:
        fieldnames, rows = load_rows(path)
        validate_columns(path, fieldnames)
        for normalized_row in normalize_run_rows(path, rows):
            run_key = (
                str(normalized_row["source_scenario"]),
                str(normalized_row["config_name"]),
                str(normalized_row["run_number"]),
            )
            previous_source = seen_run_keys.get(run_key)
            if previous_source is not None:
                raise SystemExit(
                    "Duplicate run detected across outcome summaries for "
                    f"{run_key[0]} / {run_key[1]} / run {run_key[2]} "
                    f"({previous_source} and {normalized_row['source_file']})."
                )
            seen_run_keys[run_key] = str(normalized_row["source_file"])
            normalized_rows.append(normalized_row)

    if not normalized_rows:
        raise SystemExit("No run rows were available after loading the selected outcome summaries.")

    return normalized_rows


def summarize_numeric(values: list[float]) -> dict[str, float | int | str]:
    if not values:
        return {"count": 0, "mean": "", "min": "", "max": ""}
    return {
        "count": len(values),
        "mean": fmean(values),
        "min": min(values),
        "max": max(values),
    }


def summarize_flags(values: list[int]) -> dict[str, float | int | str]:
    applicable_count = len(values)
    if applicable_count == 0:
        return {
            "applicable_count": 0,
            "true_count": 0,
            "false_count": 0,
            "true_rate": "",
        }
    true_count = sum(values)
    false_count = applicable_count - true_count
    return {
        "applicable_count": applicable_count,
        "true_count": true_count,
        "false_count": false_count,
        "true_rate": true_count / applicable_count,
    }


def grouped_summary_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["comparison_cohort"]), str(row["mechanism_family"]))].append(row)

    summary_rows: list[dict[str, object]] = []
    for (comparison_cohort, mechanism_family), group_rows in grouped.items():
        config_names = sorted({str(row["config_name"]) for row in group_rows})
        source_scenarios = sorted({str(row["source_scenario"]) for row in group_rows})
        dataset_variants = sorted({str(row["source_dataset_variant"]) for row in group_rows})

        summary_row: dict[str, object] = {
            "comparison_cohort": comparison_cohort,
            "comparison_cohort_label": COHORT_LABELS.get(comparison_cohort, humanize_identifier(comparison_cohort)),
            "mechanism_family": mechanism_family,
            "mechanism_label": MECHANISM_LABELS.get(mechanism_family, humanize_identifier(mechanism_family)),
            "run_count": len(group_rows),
            "config_count": len(config_names),
            "config_names": "; ".join(config_names),
            "source_scenarios": "; ".join(source_scenarios),
            "source_dataset_variants": "; ".join(dataset_variants),
        }

        for metric in NUMERIC_METRICS:
            values = [
                parsed_value
                for row in group_rows
                if (parsed_value := parse_float(str(row.get(metric, "")))) is not None
            ]
            stats = summarize_numeric(values)
            summary_row[f"{metric}_count"] = stats["count"]
            summary_row[f"{metric}_mean"] = stats["mean"]
            summary_row[f"{metric}_min"] = stats["min"]
            summary_row[f"{metric}_max"] = stats["max"]

        for metric in FLAG_METRICS:
            values = [
                parsed_value
                for row in group_rows
                if (parsed_value := parse_flag(str(row.get(metric, "")))) is not None
            ]
            stats = summarize_flags(values)
            summary_row[f"{metric}_applicable_count"] = stats["applicable_count"]
            summary_row[f"{metric}_true_count"] = stats["true_count"]
            summary_row[f"{metric}_false_count"] = stats["false_count"]
            summary_row[f"{metric}_true_rate"] = stats["true_rate"]

        summary_rows.append(summary_row)

    return sorted(
        summary_rows,
        key=lambda row: (
            COHORT_ORDER.get(str(row["comparison_cohort"]), 999),
            str(row["comparison_cohort"]),
            MECHANISM_ORDER.get(str(row["mechanism_family"]), 999),
            str(row["mechanism_family"]),
        ),
    )


def rate_text(summary_row: dict[str, object], metric: str) -> str:
    applicable_count = int(summary_row[f"{metric}_applicable_count"])
    true_count = int(summary_row[f"{metric}_true_count"])
    if applicable_count == 0:
        return "n/a"
    return f"{true_count}/{applicable_count} ({(true_count / applicable_count) * 100.0:.1f}%)"


def numeric_text(summary_row: dict[str, object], metric: str) -> str:
    count = int(summary_row[f"{metric}_count"])
    if count == 0:
        return "n/a"
    mean_value = summary_row[f"{metric}_mean"]
    min_value = summary_row[f"{metric}_min"]
    max_value = summary_row[f"{metric}_max"]
    return f"mean={mean_value}, min={min_value}, max={max_value}, n={count}"


def mean_value(summary_row: dict[str, object], metric: str) -> float | None:
    count = int(summary_row[f"{metric}_count"])
    if count == 0:
        return None
    return float(summary_row[f"{metric}_mean"])


def descriptive_delta_text(baseline_row: dict[str, object], candidate_row: dict[str, object], metric: str) -> str:
    baseline_mean = mean_value(baseline_row, metric)
    candidate_mean = mean_value(candidate_row, metric)
    if baseline_mean is None or candidate_mean is None:
        return "n/a"
    delta = candidate_mean - baseline_mean
    return f"{delta:+.6g}"


def format_counter(counter: Counter) -> list[str]:
    if not counter:
        return ["  <none>"]
    return [f"  {key}: {value}" for key, value in sorted(counter.items(), key=lambda item: str(item[0]))]


def render_report(
    input_paths: list[Path],
    skipped_paths: list[str],
    rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
    output_paths: dict[str, Path],
) -> str:
    title = "Outcome Comparison Report"
    lines: list[str] = [title, "=" * len(title), ""]

    lines.append("Inputs")
    for path in input_paths:
        lines.append(f"  {path}")
    if skipped_paths:
        lines.append("  skipped missing inputs:")
        for path in skipped_paths:
            lines.append(f"    {path}")
    lines.append("")

    lines.append("Method Note")
    lines.append("  This is a project-local practical comparison layer built on top of the")
    lines.append("  run-level outcome summaries. The underlying metrics remain operational")
    lines.append("  simulator-side definitions derived from observable telemetry plus scripted")
    lines.append("  event metadata and shared controller scalars where available.")
    lines.append("  Packet sequence-gap diagnostics are receiver-observed continuity evidence;")
    lines.append("  they complement, rather than replace, the coarse one-second availability")
    lines.append("  and zero-progress-window metrics.")
    lines.append("  These summaries are descriptive only and should be used for internal")
    lines.append("  AI-MRCE-versus-baseline validation, not as universal FRR claims.")
    lines.append("")

    lines.append("Run Coverage")
    lines.append(f"  total runs: {len(rows)}")
    cohort_counts = Counter(str(row["comparison_cohort"]) for row in rows)
    mechanism_counts = Counter(str(row["mechanism_family"]) for row in rows)
    lines.append("  runs by cohort:")
    lines.extend(format_counter(cohort_counts))
    lines.append("  runs by mechanism family:")
    lines.extend(format_counter(mechanism_counts))
    lines.append("")

    cohort_grouped_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    for summary_row in summary_rows:
        cohort_grouped_rows[str(summary_row["comparison_cohort"])].append(summary_row)

    lines.append("Cohort Summaries")
    for comparison_cohort, cohort_rows in sorted(
        cohort_grouped_rows.items(),
        key=lambda item: (COHORT_ORDER.get(item[0], 999), item[0]),
    ):
        cohort_label = COHORT_LABELS.get(comparison_cohort, humanize_identifier(comparison_cohort))
        lines.append(f"  {cohort_label}")
        for summary_row in cohort_rows:
            lines.append(
                "    "
                f"{summary_row['mechanism_label']} ({summary_row['mechanism_family']}): "
                f"runs={summary_row['run_count']}, configs={summary_row['config_names']}"
            )
            lines.append(
                "      "
                f"protection_before_failure={rate_text(summary_row, 'protection_activated_before_failure')}, "
                f"service_interruption_observed={rate_text(summary_row, 'service_interruption_observed')}, "
                f"recovery_observed={rate_text(summary_row, 'recovery_observed')}"
            )
            lines.append(
                "      "
                f"throughput_restored_after_failure={rate_text(summary_row, 'throughput_restored_after_failure')}, "
                f"packet_sequence_gap_observed={rate_text(summary_row, 'packet_sequence_gap_observed_after_reference')}, "
                f"missed_protection={rate_text(summary_row, 'missed_protection')}, "
                f"unnecessary_protection={rate_text(summary_row, 'unnecessary_protection')}"
            )
            lines.append(
                "      "
                f"tcp_service_interruption_observed={rate_text(summary_row, 'tcp_service_interruption_observed')}, "
                f"tcp_useful_goodput_restored_after_failure={rate_text(summary_row, 'tcp_useful_goodput_restored_after_failure')}"
            )
            lines.append(
                "      "
                f"lead_time={numeric_text(summary_row, 'protection_lead_time_before_failure_s')}, "
                f"interruption_duration={numeric_text(summary_row, 'service_interruption_duration_s')}"
            )
            lines.append(
                "      "
                f"packet_sequence_missing={numeric_text(summary_row, 'packet_sequence_gap_total_missing_after_reference')}, "
                f"max_sequence_gap={numeric_text(summary_row, 'max_packet_sequence_gap_after_reference')}, "
                f"max_interarrival_gap={numeric_text(summary_row, 'max_packet_interarrival_gap_after_reference_s')}"
            )
            lines.append(
                "      "
                f"post_failure_sequence_missing={numeric_text(summary_row, 'packet_sequence_gap_total_missing_after_hard_failure')}, "
                f"post_failure_max_sequence_gap={numeric_text(summary_row, 'max_packet_sequence_gap_after_hard_failure')}, "
                f"activation_to_failure_sequence_missing={numeric_text(summary_row, 'packet_sequence_gap_total_missing_between_activation_and_failure')}"
            )
            lines.append(
                "      "
                f"after_activation_sequence_missing={numeric_text(summary_row, 'packet_sequence_gap_total_missing_after_protection_activation')}, "
                f"critical_interval_sequence_missing={numeric_text(summary_row, 'packet_sequence_gap_total_missing_after_critical_start')}, "
                f"critical_interval_max_sequence_gap={numeric_text(summary_row, 'max_packet_sequence_gap_after_critical_start')}"
            )
            lines.append(
                "      "
                f"tcp_interruption_duration={numeric_text(summary_row, 'tcp_service_interruption_duration_s')}, "
                f"tcp_zero_goodput_windows={numeric_text(summary_row, 'tcp_zero_goodput_window_count_after_reference')}, "
                f"tcp_endpoint_receive_gap={numeric_text(summary_row, 'tcp_max_endpoint_receive_gap_after_reference_s')}"
            )
            lines.append(
                "      "
                f"recovery_time={numeric_text(summary_row, 'recovery_time_after_failure_s')}, "
                f"zero_progress_windows={numeric_text(summary_row, 'zero_progress_window_count_after_reference')}"
            )

        reactive_baseline = next(
            (row for row in cohort_rows if str(row["mechanism_family"]) == "reactive_only"),
            None,
        )
        if reactive_baseline is not None and len(cohort_rows) > 1:
            lines.append("    Descriptive contrasts vs reactive_only:")
            for summary_row in cohort_rows:
                if summary_row is reactive_baseline:
                    continue
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"protection_before_failure {rate_text(summary_row, 'protection_activated_before_failure')} "
                    f"vs {rate_text(reactive_baseline, 'protection_activated_before_failure')}; "
                    f"interruption_observed {rate_text(summary_row, 'service_interruption_observed')} "
                    f"vs {rate_text(reactive_baseline, 'service_interruption_observed')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"service_interruption_duration_s mean difference "
                    f"(candidate - reactive) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'service_interruption_duration_s')}; "
                    f"recovery_time_after_failure_s mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'recovery_time_after_failure_s')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"tcp_service_interruption_duration_s mean difference "
                    f"(candidate - reactive) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'tcp_service_interruption_duration_s')}; "
                    f"tcp_zero_goodput_window_count_after_reference mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'tcp_zero_goodput_window_count_after_reference')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"zero_progress_window_count_after_reference mean difference "
                    f"(candidate - reactive) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'zero_progress_window_count_after_reference')}; "
                    f"missed_protection {rate_text(summary_row, 'missed_protection')} "
                    f"vs {rate_text(reactive_baseline, 'missed_protection')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"packet_sequence_gap_total_missing_after_reference mean difference "
                    f"(candidate - reactive) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_missing_after_reference')}; "
                    f"max_packet_interarrival_gap_after_reference_s mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'max_packet_interarrival_gap_after_reference_s')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"packet_sequence_gap_total_missing_after_hard_failure mean difference "
                    f"(candidate - reactive) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_missing_after_hard_failure')}; "
                    f"critical-interval missing mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_missing_after_critical_start')}"
                )
        lines.append("")

    lines.append("Generated Files")
    lines.append(f"  consolidated runs: {output_paths['runs']}")
    lines.append(f"  cohort summary: {output_paths['summary']}")
    lines.append(f"  report: {output_paths['report']}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    input_paths, skipped_paths = resolve_input_paths(args)
    rows = collect_rows(input_paths)
    summary_rows = grouped_summary_rows(rows)

    output_prefix = args.output_prefix
    output_paths = {
        "runs": output_prefix.with_name(f"{output_prefix.name}_runs.csv"),
        "summary": output_prefix.with_name(f"{output_prefix.name}_summary.csv"),
        "report": output_prefix.with_name(f"{output_prefix.name}_report.txt"),
    }

    write_csv(output_paths["runs"], rows)
    write_csv(output_paths["summary"], summary_rows)

    report_text = render_report(
        input_paths=input_paths,
        skipped_paths=skipped_paths,
        rows=rows,
        summary_rows=summary_rows,
        output_paths=output_paths,
    )
    output_paths["report"].parent.mkdir(parents=True, exist_ok=True)
    output_paths["report"].write_text(report_text, encoding="utf-8")

    print(f"Wrote consolidated run table to {output_paths['runs']}")
    print(f"Wrote cohort summary to {output_paths['summary']}")
    print(f"Wrote report to {output_paths['report']}")


if __name__ == "__main__":
    main()
