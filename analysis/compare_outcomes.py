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
- Historical sequence-gap "missing" fields are forward-jump estimates kept for
  compatibility, not direct packet-loss claims. Reordering-aware
  unobserved/reordered fields distinguish apparent loss from repair-path
  overtaking of queued packets.
- The after_reference continuity fields preserve the operational reference used
  for each run, while after_hard_failure and activation-to-failure fields keep
  post-failure protection benefit separate from pre-failure switch penalty.
- Queue-normalized activation-to-failure ratios are descriptive diagnostics for
  relating switch-side effects to activation-time queue state. They are not
  runtime control thresholds and do not claim seamless make-before-break.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
OUTCOMES_DIR = OUTPUT_ROOT / "outcomes"

SUPPORTED_SCENARIOS = (
    "regionalbackbone",
    "regionalbackbone_failure_detection_degraded_link_model_family",
    "regionalbackbone_failure_detection_degradation_sensitivity",
    "regionalbackbone_failure_detection_cost_aware_backup",
    "regionalbackbone_failure_detection_cost_aware_transport_impact",
    "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented",
)
DEFAULT_SCENARIOS = (
    "regionalbackbone_failure_detection_degraded_link_model_family",
)

TRAFFIC_NUMERIC_METRICS = [
    "monitored_flow_packet_size_bytes",
    "monitored_flow_send_interval_s",
    "monitored_flow_expected_packet_rate_pps",
    "monitored_flow_expected_packets_per_window",
    "monitored_flow_expected_throughput_bps",
]

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
    "packet_sequence_gap_total_unobserved_after_reference",
    "packet_sequence_gap_total_reordered_after_reference",
    "max_packet_sequence_gap_after_reference",
    "max_packet_interarrival_gap_after_reference_s",
    "packet_interarrival_gap_exceedance_count_after_reference",
    "packet_sequence_out_of_order_event_count_after_reference",
    "packet_sequence_out_of_order_packet_count_after_reference",
    "first_packet_after_reference_delay_s",
    "packet_sequence_gap_count_after_hard_failure",
    "packet_sequence_gap_total_missing_after_hard_failure",
    "packet_sequence_gap_total_unobserved_after_hard_failure",
    "packet_sequence_gap_total_reordered_after_hard_failure",
    "max_packet_sequence_gap_after_hard_failure",
    "max_packet_interarrival_gap_after_hard_failure_s",
    "packet_interarrival_gap_exceedance_count_after_hard_failure",
    "packet_sequence_out_of_order_event_count_after_hard_failure",
    "packet_sequence_out_of_order_packet_count_after_hard_failure",
    "first_packet_after_hard_failure_delay_s",
    "packet_sequence_gap_count_after_protection_activation",
    "packet_sequence_gap_total_missing_after_protection_activation",
    "packet_sequence_gap_total_unobserved_after_protection_activation",
    "packet_sequence_gap_total_reordered_after_protection_activation",
    "max_packet_sequence_gap_after_protection_activation",
    "max_packet_interarrival_gap_after_protection_activation_s",
    "packet_interarrival_gap_exceedance_count_after_protection_activation",
    "packet_sequence_out_of_order_event_count_after_protection_activation",
    "packet_sequence_out_of_order_packet_count_after_protection_activation",
    "first_packet_after_protection_activation_delay_s",
    "packet_sequence_gap_count_between_activation_and_failure",
    "packet_sequence_gap_total_missing_between_activation_and_failure",
    "packet_sequence_gap_total_unobserved_between_activation_and_failure",
    "packet_sequence_gap_total_reordered_between_activation_and_failure",
    "max_packet_sequence_gap_between_activation_and_failure",
    "max_packet_interarrival_gap_between_activation_and_failure_s",
    "packet_interarrival_gap_exceedance_count_between_activation_and_failure",
    "packet_sequence_out_of_order_event_count_between_activation_and_failure",
    "packet_sequence_out_of_order_packet_count_between_activation_and_failure",
    "first_packet_between_activation_and_failure_delay_s",
    "activation_to_failure_unobserved_per_activation_queue_packet",
    "activation_to_failure_reordered_per_activation_queue_packet",
    "packet_sequence_gap_count_after_critical_start",
    "packet_sequence_gap_total_missing_after_critical_start",
    "packet_sequence_gap_total_unobserved_after_critical_start",
    "packet_sequence_gap_total_reordered_after_critical_start",
    "max_packet_sequence_gap_after_critical_start",
    "max_packet_interarrival_gap_after_critical_start_s",
    "packet_interarrival_gap_exceedance_count_after_critical_start",
    "packet_sequence_out_of_order_event_count_after_critical_start",
    "packet_sequence_out_of_order_packet_count_after_critical_start",
    "first_packet_after_critical_start_delay_s",
]

TCP_NUMERIC_METRICS = [
    "tcp_service_interruption_duration_s",
    "tcp_zero_goodput_window_count_after_reference",
    "tcp_max_zero_goodput_window_streak_after_reference",
    "tcp_endpoint_receive_event_count_after_reference",
    "tcp_first_endpoint_receive_delay_after_reference_s",
    "tcp_max_endpoint_receive_gap_after_reference_s",
    "receiver_tcp_total_received_bytes",
    "receiver_tcp_goodput_mean_bps",
    "receiver_tcp_active_app_count",
]

PROTECTION_ACTION_NUMERIC_METRICS = [
    "protection_trigger_source_code",
    "repair_route_count",
    "repair_route_install_time_s",
    "aimrce_policy_code",
    "runtime_model_artifact_required",
    "runtime_model_loaded",
    "runtime_model_feature_count",
    "runtime_model_threshold",
    "runtime_model_fallback_used",
    "runtime_model_fallback_reason_code",
    "aimrce_evaluation_interval_s",
    "aimrce_activation_consecutive_cycles_configured",
    "bfd_like_detection_time_s",
    "bfd_like_detect_multiplier",
    "bfd_like_detection_interval_s",
    "bfd_like_expected_detection_time_s",
    "bfd_like_missed_probe_count",
    "bfd_like_max_missed_probe_count",
    "bfd_like_probe_checks",
    "bfd_like_probe_successes",
    "bfd_like_probe_misses",
    "bfd_like_probe_loss_rate_observed",
    "bfd_like_modeled_probe_loss_probability_last",
    "bfd_like_modeled_probe_loss_probability_max",
    "bfd_like_modeled_probe_loss_probability_at_detection",
    "bfd_like_trigger_reason_code",
    "bfd_like_lead_time_before_failure_s",
    "hard_failure_to_bfd_detection_time_s",
    "hard_failure_time_configured_s",
    "activation_risk_score",
    "activation_decision_threshold",
    "activation_positive_decision_streak",
    "activation_queue_length_pk",
    "activation_queue_bit_length_b",
    "activation_probe_delay_mean_s",
    "activation_probe_throughput_bps",
    "activation_probe_packet_count",
]

NUMERIC_METRICS = TRAFFIC_NUMERIC_METRICS + BASE_NUMERIC_METRICS + PROTECTION_ACTION_NUMERIC_METRICS + PACKET_NUMERIC_METRICS + TCP_NUMERIC_METRICS

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
    "tcp_service_available_operational",
    "tcp_service_materially_degraded_operational",
]

PROTECTION_ACTION_FLAG_METRICS = [
    "repair_routes_installed",
    "enable_aimrce_decision",
    "enable_bfd_like_detection",
    "bfd_like_use_modeled_probe_loss",
    "bfd_like_detection_activated",
    "bfd_like_detection_before_hard_failure",
    "bfd_like_protected_span_up_at_detection",
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
    [
        "degradation_profile",
        "degradation_profile_key",
        "degradation_start_time_s",
        "degradation_end_time_s",
        "degradation_target_delay_s",
        "degradation_target_packet_error_rate",
        "degradation_hard_failure_time_s",
        "backup_path_penalty_model",
        "backup_path_data_rate_bps",
        "backup_path_extra_delay_s",
        "primary_path_normal_data_rate_bps",
        "primary_path_normal_extra_delay_s",
        "traffic_profile",
        "traffic_mix_model",
        "tcp_app_indices",
        "tcp_flow_start_time_s",
        "tcp_metric_scope",
        "instrumentation_mode",
        "tcp_receiver_app_indices",
        "tcp_useful_goodput_floor_bps",
        "runtime_model_type",
        "runtime_model_path",
        "aimrce_policy_name",
        "monitored_flow_app_index",
        "protection_action_code",
        "protection_trigger_source",
        "bfd_like_trigger_reason_text",
    ]
    + TRAFFIC_NUMERIC_METRICS
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
    "regionalbackbone_failure_detection_degraded_link_model_family": OUTCOMES_DIR / "regionalbackbone_failure_detection_degraded_link_model_family_outcome_summary.csv",
    "regionalbackbone_failure_detection_degradation_sensitivity": OUTCOMES_DIR / "regionalbackbone_failure_detection_degradation_sensitivity_outcome_summary.csv",
    "regionalbackbone_failure_detection_cost_aware_backup": OUTCOMES_DIR / "regionalbackbone_failure_detection_cost_aware_backup_outcome_summary.csv",
    "regionalbackbone_failure_detection_cost_aware_transport_impact": OUTCOMES_DIR / "regionalbackbone_failure_detection_cost_aware_transport_impact_outcome_summary.csv",
    "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented": OUTCOMES_DIR / "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented_outcome_summary.csv",
}

MECHANISM_LABELS = {
    "reactive_only": "Reactive baseline",
    "deterministic_admin_protection": "Deterministic proactive baseline",
    "aimrce_rule_based": "AI-MRCE rule-based",
    "aimrce_logistic_regression": "AI-MRCE logistic-regression",
    "aimrce_linear_svm": "AI-MRCE linear-SVM",
    "aimrce_shallow_tree": "AI-MRCE shallow-tree",
    "ospf_only": "OSPF only",
    "bfd_like_frr": "OSPF + BFD-like + FRR",
    "aimrce_frr": "OSPF + AI-MRCE + FRR",
    "aimrce_rule_based_frr": "OSPF + AI-MRCE rule-based + FRR",
    "aimrce_logistic_regression_frr": "OSPF + AI-MRCE logistic-regression + FRR",
    "aimrce_linear_svm_frr": "OSPF + AI-MRCE linear-SVM + FRR",
    "aimrce_shallow_tree_frr": "OSPF + AI-MRCE shallow-tree + FRR",
    "hybrid_bfd_like_aimrce_frr": "OSPF + BFD-like + AI-MRCE + FRR",
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
    "ospf_only": 10,
    "bfd_like_frr": 11,
    "aimrce_frr": 12,
    "aimrce_rule_based_frr": 13,
    "aimrce_logistic_regression_frr": 14,
    "aimrce_linear_svm_frr": 15,
    "aimrce_shallow_tree_frr": 16,
    "hybrid_bfd_like_aimrce_frr": 17,
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
    "regionalbackbone_failure_detection_comparison": "Regional backbone failure-detection comparison cohort",
    "regionalbackbone_failure_detection_comparison_ms_traffic": "Regional backbone failure-detection 2 ms monitored-traffic cohort",
    "regionalbackbone_failure_detection_degraded_link": "Regional backbone failure-detection degraded-link cohort",
    "regionalbackbone_failure_detection_degraded_link_model_family": "Regional backbone degraded-link AI-MRCE model-family cohort",
    "regionalbackbone_failure_detection_degradation_sensitivity": "Regional backbone degradation-sensitivity cohort",
    "regionalbackbone_failure_detection_cost_aware_backup": "Regional backbone cost-aware backup-path cohort",
    "regionalbackbone_failure_detection_cost_aware_transport_impact": "Regional backbone cost-aware mixed UDP/TCP transport-impact cohort",
    "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented": "Regional backbone instrumented cost-aware mixed UDP/TCP transport-impact cohort",
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
    "regionalbackbone_failure_detection_comparison": 8,
    "regionalbackbone_failure_detection_comparison_ms_traffic": 9,
    "regionalbackbone_failure_detection_degraded_link": 10,
    "regionalbackbone_failure_detection_degraded_link_model_family": 11,
    "regionalbackbone_failure_detection_degradation_sensitivity": 12,
    "regionalbackbone_failure_detection_cost_aware_backup": 13,
    "regionalbackbone_failure_detection_cost_aware_transport_impact": 14,
    "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented": 15,
    "regionalbackbone_other": 16,
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


def resolve_project_path(path: Path) -> Path:
    # Explicit CLI paths are treated as project-root relative when not
    # absolute. This preserves documented commands and avoids cwd-dependent
    # failures when invoking the script directly from analysis\.
    return path if path.is_absolute() else PROJECT_ROOT / path


def atomic_temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.tmp")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = atomic_temp_path(path)
    try:
        temp_path.write_text(text, encoding="utf-8")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = atomic_temp_path(path)
    try:
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            if not rows:
                handle.write("")
            else:
                resolved_fieldnames = list(fieldnames or [])
                if not resolved_fieldnames:
                    for row in rows:
                        for key in row:
                            if key not in resolved_fieldnames:
                                resolved_fieldnames.append(key)
                writer = csv.DictWriter(handle, fieldnames=resolved_fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def elapsed_text(start_time: float) -> str:
    return f"{time.perf_counter() - start_time:.2f}s"


def latest_mtime(paths: list[Path]) -> float | None:
    mtimes = [path.stat().st_mtime for path in paths if path.exists()]
    return max(mtimes) if mtimes else None


def warn_if_existing_output_stale(output_path: Path, source_paths: list[Path], regenerate_command: str) -> None:
    if not output_path.exists():
        return
    newest_source = latest_mtime(source_paths)
    if newest_source is None or output_path.stat().st_mtime >= newest_source:
        return
    newest_inputs = [path for path in source_paths if path.exists() and path.stat().st_mtime == newest_source]
    source_text = newest_inputs[0] if newest_inputs else "input outcome summary"
    print(
        "Warning: existing comparison artifact appears stale before regeneration: "
        f"{output_path} is older than {source_text}. Regenerate with: {regenerate_command}"
    )


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
    if not rows:
        atomic_write_csv(path, rows, [])
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    atomic_write_csv(path, rows, fieldnames)


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def resolve_input_paths(args: argparse.Namespace) -> tuple[list[Path], list[str]]:
    selected_paths = (
        [resolve_project_path(path) for path in args.inputs]
        if args.inputs
        else [SCENARIO_PRESETS[scenario] for scenario in args.scenarios]
    )
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
    if config_name == "RegionalBackboneFailureComparisonOspfOnly":
        return "ospf_only"
    if config_name == "RegionalBackboneFailureComparisonBfdLikeFrr":
        return "bfd_like_frr"
    if config_name == "RegionalBackboneFailureComparisonAiMrceFrr":
        return "aimrce_frr"
    if config_name == "RegionalBackboneFailureComparisonHybrid":
        return "hybrid_bfd_like_aimrce_frr"
    if config_name == "RegionalBackboneFailureComparisonOspfOnlyMsTraffic":
        return "ospf_only"
    if config_name == "RegionalBackboneFailureComparisonBfdLikeFrrMsTraffic":
        return "bfd_like_frr"
    if config_name == "RegionalBackboneFailureComparisonAiMrceFrrMsTraffic":
        return "aimrce_frr"
    if config_name == "RegionalBackboneFailureComparisonHybridMsTraffic":
        return "hybrid_bfd_like_aimrce_frr"
    if config_name == "RegionalBackboneFailureComparisonOspfOnlyDegradedLink":
        return "ospf_only"
    if config_name == "RegionalBackboneFailureComparisonBfdLikeFrrDegradedLink":
        return "bfd_like_frr"
    if config_name == "RegionalBackboneFailureComparisonAiMrceFrrDegradedLink":
        return "aimrce_frr"
    if config_name == "RegionalBackboneFailureComparisonHybridDegradedLink":
        return "hybrid_bfd_like_aimrce_frr"
    if config_name == "RegionalBackboneFailureDegradedLinkOspfOnly":
        return "ospf_only"
    if config_name == "RegionalBackboneFailureDegradedLinkBfdLikeFrr":
        return "bfd_like_frr"
    if config_name == "RegionalBackboneFailureDegradedLinkAiMrceRuleBased":
        return "aimrce_rule_based_frr"
    if config_name == "RegionalBackboneFailureDegradedLinkAiMrceLogReg":
        return "aimrce_logistic_regression_frr"
    if config_name == "RegionalBackboneFailureDegradedLinkAiMrceLinearSvm":
        return "aimrce_linear_svm_frr"
    if config_name == "RegionalBackboneFailureDegradedLinkAiMrceShallowTree":
        return "aimrce_shallow_tree_frr"
    if config_name == "RegionalBackboneFailureDegradedLinkHybrid":
        return "hybrid_bfd_like_aimrce_frr"
    if config_name.startswith("RegionalBackboneSensitivity"):
        if config_name.endswith("OspfOnly"):
            return "ospf_only"
        if config_name.endswith("BfdLikeFrr"):
            return "bfd_like_frr"
        if config_name.endswith("AiMrceRuleBased"):
            return "aimrce_rule_based_frr"
        if config_name.endswith("AiMrceLogReg"):
            return "aimrce_logistic_regression_frr"
        if config_name.endswith("AiMrceLinearSvm"):
            return "aimrce_linear_svm_frr"
        if config_name.endswith("AiMrceShallowTree"):
            return "aimrce_shallow_tree_frr"
        if config_name.endswith("Hybrid"):
            return "hybrid_bfd_like_aimrce_frr"
    if config_name.startswith("RegionalBackboneCostAware"):
        if config_name.endswith("OspfOnly"):
            return "ospf_only"
        if config_name.endswith("BfdLikeFrr"):
            return "bfd_like_frr"
        if config_name.endswith("AiMrceRuleBased"):
            return "aimrce_rule_based_frr"
        if config_name.endswith("AiMrceLogReg"):
            return "aimrce_logistic_regression_frr"
        if config_name.endswith("AiMrceLinearSvm"):
            return "aimrce_linear_svm_frr"
        if config_name.endswith("AiMrceShallowTree"):
            return "aimrce_shallow_tree_frr"
        if config_name.endswith("Hybrid"):
            return "hybrid_bfd_like_aimrce_frr"
    return "unknown_mechanism"


def resolve_comparison_cohort(scenario_name: str, config_name: str, mechanism_family: str) -> str:
    # These cohorts are project-local analysis buckets for internal comparison.
    # They intentionally preserve scenario/context boundaries instead of
    # collapsing every run with the same mechanism label into one global mean.
    if scenario_name in {"reactivefailure", "proactiveswitch"}:
        return "small_topology_primary_path_failure"

    if scenario_name == "regionalbackbone_mixed_traffic_protection":
        return "regionalbackbone_mixed_traffic_protection"

    if scenario_name == "regionalbackbone_failure_detection_comparison":
        return "regionalbackbone_failure_detection_comparison"

    if scenario_name == "regionalbackbone_failure_detection_comparison_ms_traffic":
        return "regionalbackbone_failure_detection_comparison_ms_traffic"

    if scenario_name == "regionalbackbone_failure_detection_degraded_link":
        return "regionalbackbone_failure_detection_degraded_link"

    if scenario_name == "regionalbackbone_failure_detection_degraded_link_model_family":
        return "regionalbackbone_failure_detection_degraded_link_model_family"

    if scenario_name == "regionalbackbone_failure_detection_degradation_sensitivity":
        return "regionalbackbone_failure_detection_degradation_sensitivity"

    if scenario_name == "regionalbackbone_failure_detection_cost_aware_backup":
        return "regionalbackbone_failure_detection_cost_aware_backup"

    if scenario_name == "regionalbackbone_failure_detection_cost_aware_transport_impact":
        return "regionalbackbone_failure_detection_cost_aware_transport_impact"

    if scenario_name == "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented":
        return "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented"

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
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                str(row["comparison_cohort"]),
                str(row.get("degradation_profile", "")),
                str(row["mechanism_family"]),
            )
        ].append(row)

    summary_rows: list[dict[str, object]] = []
    for (comparison_cohort, degradation_profile, mechanism_family), group_rows in grouped.items():
        config_names = sorted({str(row["config_name"]) for row in group_rows})
        source_scenarios = sorted({str(row["source_scenario"]) for row in group_rows})
        dataset_variants = sorted({str(row["source_dataset_variant"]) for row in group_rows})
        traffic_profiles = sorted({str(row.get("traffic_profile", "")) for row in group_rows if str(row.get("traffic_profile", ""))})
        runtime_model_types = sorted({str(row.get("runtime_model_type", "")) for row in group_rows if str(row.get("runtime_model_type", ""))})
        runtime_model_paths = sorted({str(row.get("runtime_model_path", "")) for row in group_rows if str(row.get("runtime_model_path", ""))})
        trigger_sources = Counter(str(row.get("protection_trigger_source", "") or "none") for row in group_rows)
        bfd_trigger_reasons = Counter(str(row.get("bfd_like_trigger_reason_text", "") or "none") for row in group_rows)

        summary_row: dict[str, object] = {
            "comparison_cohort": comparison_cohort,
            "comparison_cohort_label": COHORT_LABELS.get(comparison_cohort, humanize_identifier(comparison_cohort)),
            "degradation_profile": degradation_profile,
            "mechanism_family": mechanism_family,
            "mechanism_label": MECHANISM_LABELS.get(mechanism_family, humanize_identifier(mechanism_family)),
            "run_count": len(group_rows),
            "config_count": len(config_names),
            "config_names": "; ".join(config_names),
            "source_scenarios": "; ".join(source_scenarios),
            "source_dataset_variants": "; ".join(dataset_variants),
            "traffic_profiles": "; ".join(traffic_profiles),
            "runtime_model_types": "; ".join(runtime_model_types),
            "runtime_model_paths": "; ".join(runtime_model_paths),
            "protection_trigger_sources": "; ".join(
                f"{source}:{count}" for source, count in sorted(trigger_sources.items())
            ),
            "bfd_like_trigger_reasons": "; ".join(
                f"{reason}:{count}" for reason, count in sorted(bfd_trigger_reasons.items())
            ),
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
            str(row.get("degradation_profile", "")),
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


DEGRADED_LINK_COHORT = "regionalbackbone_failure_detection_degraded_link"
DEGRADED_LINK_MODEL_FAMILY_COHORT = "regionalbackbone_failure_detection_degraded_link_model_family"
DEGRADATION_SENSITIVITY_COHORT = "regionalbackbone_failure_detection_degradation_sensitivity"
COST_AWARE_BACKUP_COHORT = "regionalbackbone_failure_detection_cost_aware_backup"
COST_AWARE_TRANSPORT_COHORT = "regionalbackbone_failure_detection_cost_aware_transport_impact"
COST_AWARE_TRANSPORT_INSTRUMENTED_COHORT = "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented"
DEGRADED_LINK_HEADLINE_COHORTS = {
    DEGRADED_LINK_COHORT,
    DEGRADED_LINK_MODEL_FAMILY_COHORT,
    DEGRADATION_SENSITIVITY_COHORT,
    COST_AWARE_BACKUP_COHORT,
    COST_AWARE_TRANSPORT_COHORT,
    COST_AWARE_TRANSPORT_INSTRUMENTED_COHORT,
}


def summary_mean(summary_row: dict[str, object], metric: str) -> object:
    return summary_row.get(f"{metric}_mean", "")


def summary_rate(summary_row: dict[str, object], metric: str) -> object:
    return summary_row.get(f"{metric}_true_rate", "")


def degraded_link_short_interpretation(summary_row: dict[str, object]) -> str:
    comparison_cohort = str(summary_row.get("comparison_cohort", ""))
    mechanism_family = str(summary_row.get("mechanism_family", ""))
    if mechanism_family == "ospf_only":
        return (
            "OSPF-only has no protection trigger in this cohort and remains the "
            "post-hard-failure unobserved-gap baseline."
        )
    if mechanism_family == "bfd_like_frr":
        if comparison_cohort == DEGRADATION_SENSITIVITY_COHORT:
            return (
                "Project-local BFD-like detection is profile-sensitive in the "
                "degradation-sensitivity cohort; inspect trigger time, lead "
                "time, and post-failure unobserved gaps per profile."
            )
        return (
            "Project-local BFD-like detection triggers before hard failure only "
            "after modeled probe loss is severe; it removes post-failure "
            "unobserved gaps but has a large brownout/activation interval cost."
        )
    if mechanism_family == "aimrce_frr":
        return (
            "AI-MRCE triggers proactively from telemetry risk much earlier than "
            "hard failure; it removes post-failure unobserved gaps and avoids "
            "activation-to-failure unobserved gaps, but repair-route reordering "
            "remains visible."
        )
    if mechanism_family == "aimrce_rule_based_frr":
        return (
            "Rule-based AI-MRCE is the transparent non-ML runtime reference. It "
            "uses the same telemetry and repair-route action as the learned "
            "models, making its activation cost directly comparable."
        )
    if mechanism_family == "aimrce_logistic_regression_frr":
        return (
            "Logistic-regression AI-MRCE is a compact learned runtime artifact. "
            "Report its activation timing and transition side effects separately "
            "from post-failure continuity."
        )
    if mechanism_family == "aimrce_linear_svm_frr":
        return (
            "Linear-SVM AI-MRCE is a lightweight margin-based runtime artifact "
            "with a bounded score transform. It is included for interpretable "
            "model-family comparison, not as a production predictor."
        )
    if mechanism_family == "aimrce_shallow_tree_frr":
        return (
            "Shallow-tree AI-MRCE is an auditable threshold-branch runtime "
            "artifact. Its value is transparency and robustness rather than "
            "black-box complexity."
        )
    if mechanism_family == "hybrid_bfd_like_aimrce_frr":
        return (
            "Hybrid triggers AI-MRCE first in this progressive degraded-link "
            "profile; the BFD-like path remains a reactive safety-net diagnostic."
        )
    return "Descriptive mechanism summary; inspect the detailed comparison report before making claims."


def build_degraded_link_headline_rows(summary_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    # This compact artifact is intentionally descriptive and scenario-specific.
    # It highlights the dissertation-relevant degraded-link result without
    # changing any metric definitions or hiding activation-time side effects.
    selected_rows = [
        row
        for row in summary_rows
        if str(row.get("comparison_cohort", "")) in DEGRADED_LINK_HEADLINE_COHORTS
    ]
    selected_rows.sort(
        key=lambda row: (
            str(row.get("degradation_profile", "")),
            MECHANISM_ORDER.get(str(row.get("mechanism_family", "")), 999),
            str(row.get("mechanism_family", "")),
        )
    )

    headline_rows: list[dict[str, object]] = []
    for row in selected_rows:
        mechanism_family = str(row.get("mechanism_family", ""))
        mean_activation_risk_score = (
            summary_mean(row, "activation_risk_score")
            if mechanism_family in {
                "aimrce_frr",
                "aimrce_rule_based_frr",
                "aimrce_logistic_regression_frr",
                "aimrce_linear_svm_frr",
                "aimrce_shallow_tree_frr",
                "hybrid_bfd_like_aimrce_frr",
            }
            else ""
        )
        mean_bfd_detection_time = (
            summary_mean(row, "bfd_like_detection_time_s")
            if mechanism_family == "bfd_like_frr"
            else ""
        )
        mean_bfd_modeled_loss_at_detection = (
            summary_mean(row, "bfd_like_modeled_probe_loss_probability_at_detection")
            if mechanism_family == "bfd_like_frr"
            else ""
        )
        headline_rows.append(
            {
                "mechanism_family": row.get("mechanism_family", ""),
                "mechanism_label": row.get("mechanism_label", ""),
                "comparison_cohort": row.get("comparison_cohort", ""),
                "degradation_profile": row.get("degradation_profile", ""),
                "runtime_model_type": row.get("runtime_model_types", ""),
                "runtime_model_path": row.get("runtime_model_paths", ""),
                "trigger_source_summary": row.get("protection_trigger_sources", ""),
                "run_count": row.get("run_count", ""),
                "protection_before_failure_rate": summary_rate(row, "protection_activated_before_failure"),
                "mean_activation_time_s": summary_mean(row, "protection_activation_time_s"),
                "activation_time_mean": summary_mean(row, "protection_activation_time_s"),
                "mean_lead_time_before_failure_s": summary_mean(row, "protection_lead_time_before_failure_s"),
                "lead_time_mean": summary_mean(row, "protection_lead_time_before_failure_s"),
                "mean_activation_queue_pk": summary_mean(row, "activation_queue_length_pk"),
                "mean_runtime_model_loaded": summary_mean(row, "runtime_model_loaded")
                if mechanism_family in {
                    "aimrce_frr",
                    "aimrce_rule_based_frr",
                    "aimrce_logistic_regression_frr",
                    "aimrce_linear_svm_frr",
                    "aimrce_shallow_tree_frr",
                    "hybrid_bfd_like_aimrce_frr",
                }
                else "",
                "mean_runtime_model_fallback_used": summary_mean(row, "runtime_model_fallback_used")
                if mechanism_family in {
                    "aimrce_frr",
                    "aimrce_rule_based_frr",
                    "aimrce_logistic_regression_frr",
                    "aimrce_linear_svm_frr",
                    "aimrce_shallow_tree_frr",
                    "hybrid_bfd_like_aimrce_frr",
                }
                else "",
                "mean_runtime_model_feature_count": summary_mean(row, "runtime_model_feature_count")
                if mechanism_family in {
                    "aimrce_logistic_regression_frr",
                    "aimrce_linear_svm_frr",
                    "aimrce_shallow_tree_frr",
                }
                else "",
                "mean_activation_risk_score": mean_activation_risk_score,
                "mean_activation_threshold": summary_mean(row, "activation_decision_threshold")
                if mechanism_family in {
                    "aimrce_frr",
                    "aimrce_rule_based_frr",
                    "aimrce_logistic_regression_frr",
                    "aimrce_linear_svm_frr",
                    "aimrce_shallow_tree_frr",
                    "hybrid_bfd_like_aimrce_frr",
                }
                else "",
                "mean_bfd_detection_time_s": mean_bfd_detection_time,
                "mean_bfd_modeled_loss_at_detection": mean_bfd_modeled_loss_at_detection,
                "mean_post_failure_unobserved": summary_mean(
                    row,
                    "packet_sequence_gap_total_unobserved_after_hard_failure",
                ),
                "post_failure_unobserved_mean": summary_mean(
                    row,
                    "packet_sequence_gap_total_unobserved_after_hard_failure",
                ),
                "mean_activation_to_failure_unobserved": summary_mean(
                    row,
                    "packet_sequence_gap_total_unobserved_between_activation_and_failure",
                ),
                "activation_to_failure_unobserved_mean": summary_mean(
                    row,
                    "packet_sequence_gap_total_unobserved_between_activation_and_failure",
                ),
                "mean_activation_to_failure_reordered": summary_mean(
                    row,
                    "packet_sequence_gap_total_reordered_between_activation_and_failure",
                ),
                "activation_to_failure_reordered_mean": summary_mean(
                    row,
                    "packet_sequence_gap_total_reordered_between_activation_and_failure",
                ),
                "short_interpretation": degraded_link_short_interpretation(row),
                "interpretation": degraded_link_short_interpretation(row),
            }
        )
    return headline_rows


def render_degraded_link_headline_summary(headline_rows: list[dict[str, object]]) -> str:
    title = "Degraded-Link Failure Detection Headline Summary"
    lines = [title, "=" * len(title), ""]
    lines.append("Method note")
    lines.append(
        "  This compact summary is descriptive and scenario-conditioned to the "
        "deterministic progressive degraded-link/brownout cohort. BFD-like is a "
        "project-local reactive detector, AI-MRCE is a proactive telemetry "
        "trigger, and repair routes are project-local FRR-like abstractions."
    )
    lines.append(
        "  Five publication runs provide reproducibility and workflow coverage for "
        "this controlled cohort; they are not broad stochastic statistical "
        "significance evidence."
    )
    lines.append(
        "  Use post-hard-failure unobserved gaps as the headline loss-like metric. "
        "Use activation-to-failure unobserved/reordered packets as brownout and "
        "repair-route transition side-effect metrics."
    )
    lines.append("")
    for row in headline_rows:
        profile = str(row.get("degradation_profile", "")).strip()
        profile_suffix = f", profile={profile}" if profile else ""
        lines.append(f"{row['mechanism_label']} ({row['mechanism_family']}{profile_suffix})")
        if profile:
            lines.append(f"  degradation_profile: {profile}")
        lines.append(f"  runtime_model_type: {row['runtime_model_type']}")
        lines.append(f"  runtime_model_path: {row['runtime_model_path']}")
        lines.append(f"  trigger_source_summary: {row['trigger_source_summary']}")
        lines.append(f"  run_count: {row['run_count']}")
        lines.append(f"  protection_before_failure_rate: {row['protection_before_failure_rate']}")
        lines.append(f"  mean_activation_time_s: {row['mean_activation_time_s']}")
        lines.append(f"  mean_lead_time_before_failure_s: {row['mean_lead_time_before_failure_s']}")
        lines.append(f"  mean_activation_queue_pk: {row['mean_activation_queue_pk']}")
        lines.append(f"  mean_runtime_model_loaded: {row['mean_runtime_model_loaded']}")
        lines.append(f"  mean_runtime_model_fallback_used: {row['mean_runtime_model_fallback_used']}")
        lines.append(f"  mean_runtime_model_feature_count: {row['mean_runtime_model_feature_count']}")
        lines.append(f"  mean_activation_risk_score: {row['mean_activation_risk_score']}")
        lines.append(f"  mean_activation_threshold: {row['mean_activation_threshold']}")
        lines.append(f"  mean_bfd_detection_time_s: {row['mean_bfd_detection_time_s']}")
        lines.append(
            "  mean_bfd_modeled_loss_at_detection: "
            f"{row['mean_bfd_modeled_loss_at_detection']}"
        )
        lines.append(f"  mean_post_failure_unobserved: {row['mean_post_failure_unobserved']}")
        lines.append(
            "  mean_activation_to_failure_unobserved: "
            f"{row['mean_activation_to_failure_unobserved']}"
        )
        lines.append(
            "  mean_activation_to_failure_reordered: "
            f"{row['mean_activation_to_failure_reordered']}"
        )
        lines.append(f"  interpretation: {row['short_interpretation']}")
        lines.append("")
    return "\n".join(lines)


def render_report(
    input_paths: list[Path],
    skipped_paths: list[str],
    rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
    headline_rows: list[dict[str, object]],
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
    lines.append("  The active cohort is deterministic and scenario-conditioned; its five runs")
    lines.append("  provide reproducibility/coverage rather than broad stochastic significance.")
    lines.append("  Use post-hard-failure unobserved gaps as the headline loss-like comparison.")
    lines.append("  Use activation-to-failure reordered/out-of-order fields to report AI-MRCE")
    lines.append("  repair-route switch side effects. Legacy missing fields are forward jumps")
    lines.append("  retained for compatibility, not direct packet-loss claims.")
    lines.append("  Queue-normalized activation-to-failure ratios are descriptive diagnostics")
    lines.append("  for relating switch side effects to the observed activation-time queue state;")
    lines.append("  they are not controller thresholds.")
    lines.append("  BFD-like fields describe a project-local reactive detector. In degraded-link")
    lines.append("  variants, modeled probe loss is derived from current channel packet error")
    lines.append("  rate and detect-multiplier state, not from future hard-failure time.")
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

    if headline_rows:
        headline_cohorts = {str(row.get("comparison_cohort", "")) for row in headline_rows}
        if DEGRADED_LINK_MODEL_FAMILY_COHORT in headline_cohorts:
            lines.append("Main Dissertation Finding: AI-MRCE Model-Family Behavior in Degraded-Link Detection")
            lines.append(
                "  The model-family degraded-link cohort keeps OSPF-only, "
                "BFD-like+FRR, and hybrid references visible while separating "
                "AI-MRCE rule-based, logistic-regression, linear-SVM, and "
                "shallow-tree decision policies under the same repair-route "
                "actuator and degradation timeline."
            )
        else:
            lines.append("Main Dissertation Finding: Degraded-Link Failure Detection")
            lines.append(
                "  The degraded-link cohort is the clearest current comparison of "
                "OSPF-only, project-local BFD-like reactive protection, proactive "
                "AI-MRCE protection, and the hybrid safety-net design."
            )
        lines.append(
            "  OSPF-only remains the no-protection post-hard-failure baseline. "
            "BFD-like protection is reactive: it fires only after modeled probe "
            "loss becomes severe shortly before hard failure. AI-MRCE policies "
            "are proactive: they fire from telemetry risk before hard failure. "
            "Hybrid rows record which trigger wins first."
        )
        lines.append(
            "  Post-hard-failure unobserved packet gaps are the headline loss-like "
            "metric. Activation-to-failure unobserved and reordered packets are "
            "reported separately as brownout/switch side effects. Reordered "
            "packets are not counted as direct loss."
        )
        if DEGRADED_LINK_MODEL_FAMILY_COHORT in headline_cohorts:
            aimrce_rows = [
                row
                for row in headline_rows
                if str(row.get("mechanism_family", "")).startswith("aimrce_")
                and str(row.get("mechanism_family", "")) != "aimrce_frr"
            ]
            if aimrce_rows:
                def mean_or_none(row: dict[str, object], field: str) -> float | None:
                    try:
                        value = row.get(field, "")
                        return None if value == "" else float(value)
                    except (TypeError, ValueError):
                        return None

                activation_rows = [(row, mean_or_none(row, "mean_activation_time_s")) for row in aimrce_rows]
                activation_rows = [(row, value) for row, value in activation_rows if value is not None]
                reordered_rows = [(row, mean_or_none(row, "mean_activation_to_failure_reordered")) for row in aimrce_rows]
                reordered_rows = [(row, value) for row, value in reordered_rows if value is not None]
                unobserved_rows = [(row, mean_or_none(row, "mean_activation_to_failure_unobserved")) for row in aimrce_rows]
                unobserved_rows = [(row, value) for row, value in unobserved_rows if value is not None]
                post_failure_rows = [(row, mean_or_none(row, "mean_post_failure_unobserved")) for row in aimrce_rows]
                post_failure_rows = [(row, value) for row, value in post_failure_rows if value is not None]

                if activation_rows:
                    earliest = min(activation_rows, key=lambda item: item[1])
                    latest = max(activation_rows, key=lambda item: item[1])
                    lines.append(
                        "  AI-MRCE activation timing: "
                        f"earliest={earliest[0]['mechanism_label']} at {earliest[1]}s; "
                        f"latest={latest[0]['mechanism_label']} at {latest[1]}s."
                    )
                if unobserved_rows:
                    lowest_unobserved = min(unobserved_rows, key=lambda item: item[1])
                    lines.append(
                        "  Lowest activation-to-failure unobserved cost among AI-MRCE policies: "
                        f"{lowest_unobserved[0]['mechanism_label']} with mean={lowest_unobserved[1]}."
                    )
                if reordered_rows:
                    lowest_reordered = min(reordered_rows, key=lambda item: item[1])
                    lines.append(
                        "  Lowest activation-to-failure reordering among AI-MRCE policies: "
                        f"{lowest_reordered[0]['mechanism_label']} with mean={lowest_reordered[1]}."
                    )
                if post_failure_rows and all(value == 0 for _, value in post_failure_rows):
                    lines.append(
                        "  All AI-MRCE model-family policies show zero post-hard-failure "
                        "unobserved gaps in this descriptive cohort."
                    )
        for row in headline_rows:
            lines.append(
                "  "
                f"{row['mechanism_label']}: runs={row['run_count']}, "
                f"runtime_model={row['runtime_model_type'] or 'n/a'}, "
                f"trigger={row['trigger_source_summary']}, "
                f"protection_before_failure_rate={row['protection_before_failure_rate']}, "
                f"activation_time={row['mean_activation_time_s']}, "
                f"lead_time={row['mean_lead_time_before_failure_s']}, "
                f"runtime_loaded={row['mean_runtime_model_loaded']}, "
                f"fallback_used={row['mean_runtime_model_fallback_used']}, "
                f"threshold={row['mean_activation_threshold']}, "
                f"post_failure_unobserved={row['mean_post_failure_unobserved']}, "
                f"activation_to_failure_unobserved={row['mean_activation_to_failure_unobserved']}, "
                f"activation_to_failure_reordered={row['mean_activation_to_failure_reordered']}"
            )
            lines.append(f"    {row['short_interpretation']}")
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
            profile_text = (
                f", profile={summary_row.get('degradation_profile')}"
                if str(summary_row.get("degradation_profile", "")).strip()
                else ""
            )
            lines.append(
                "    "
                f"{summary_row['mechanism_label']} ({summary_row['mechanism_family']}): "
                f"runs={summary_row['run_count']}, configs={summary_row['config_names']}{profile_text}"
            )
            lines.append(
                "      "
                f"trigger_sources={summary_row.get('protection_trigger_sources', '')}"
            )
            lines.append(
                "      "
                f"traffic_profile={summary_row.get('traffic_profiles', '')}, "
                f"monitored_send_interval={numeric_text(summary_row, 'monitored_flow_send_interval_s')}, "
                f"monitored_packet_rate_pps={numeric_text(summary_row, 'monitored_flow_expected_packet_rate_pps')}, "
                f"expected_packets_per_1s_window={numeric_text(summary_row, 'monitored_flow_expected_packets_per_window')}"
            )
            lines.append(
                "      "
                f"protection_before_failure={rate_text(summary_row, 'protection_activated_before_failure')}, "
                f"bfd_like_detection={rate_text(summary_row, 'bfd_like_detection_activated')}, "
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
                f"interruption_duration={numeric_text(summary_row, 'service_interruption_duration_s')}, "
                f"repair_route_install_time={numeric_text(summary_row, 'repair_route_install_time_s')}"
            )
            lines.append(
                "      "
                f"activation_score={numeric_text(summary_row, 'activation_risk_score')}, "
                f"activation_threshold={numeric_text(summary_row, 'activation_decision_threshold')}, "
                f"activation_queue_pk={numeric_text(summary_row, 'activation_queue_length_pk')}, "
                f"activation_probe_delay={numeric_text(summary_row, 'activation_probe_delay_mean_s')}"
            )
            lines.append(
                "      "
                f"bfd_detection_time={numeric_text(summary_row, 'bfd_like_detection_time_s')}, "
                f"bfd_detection_interval={numeric_text(summary_row, 'bfd_like_detection_interval_s')}, "
                f"bfd_expected_detection_time={numeric_text(summary_row, 'bfd_like_expected_detection_time_s')}, "
                f"bfd_detect_multiplier={numeric_text(summary_row, 'bfd_like_detect_multiplier')}, "
                f"bfd_missed_probe_count={numeric_text(summary_row, 'bfd_like_missed_probe_count')}, "
                f"bfd_detection_before_failure={rate_text(summary_row, 'bfd_like_detection_before_hard_failure')}, "
                f"bfd_lead_time={numeric_text(summary_row, 'bfd_like_lead_time_before_failure_s')}, "
                f"bfd_protected_span_up_at_detection={rate_text(summary_row, 'bfd_like_protected_span_up_at_detection')}"
            )
            lines.append(
                "      "
                f"bfd_modeled_probe_loss_enabled={rate_text(summary_row, 'bfd_like_use_modeled_probe_loss')}, "
                f"bfd_probe_checks={numeric_text(summary_row, 'bfd_like_probe_checks')}, "
                f"bfd_probe_misses={numeric_text(summary_row, 'bfd_like_probe_misses')}, "
                f"bfd_probe_loss_rate={numeric_text(summary_row, 'bfd_like_probe_loss_rate_observed')}, "
                f"bfd_modeled_loss_at_detection={numeric_text(summary_row, 'bfd_like_modeled_probe_loss_probability_at_detection')}, "
                f"hard_failure_to_bfd_detection={numeric_text(summary_row, 'hard_failure_to_bfd_detection_time_s')}, "
                f"bfd_trigger_reasons={summary_row.get('bfd_like_trigger_reasons', '')}"
            )
            lines.append(
                "      "
                f"packet_sequence_unobserved={numeric_text(summary_row, 'packet_sequence_gap_total_unobserved_after_reference')}, "
                f"packet_sequence_reordered={numeric_text(summary_row, 'packet_sequence_gap_total_reordered_after_reference')}, "
                f"packet_sequence_forward_jumps={numeric_text(summary_row, 'packet_sequence_gap_total_missing_after_reference')}, "
                f"max_sequence_gap={numeric_text(summary_row, 'max_packet_sequence_gap_after_reference')}, "
                f"max_interarrival_gap={numeric_text(summary_row, 'max_packet_interarrival_gap_after_reference_s')}"
            )
            lines.append(
                "      "
                f"post_failure_unobserved={numeric_text(summary_row, 'packet_sequence_gap_total_unobserved_after_hard_failure')}, "
                f"post_failure_reordered={numeric_text(summary_row, 'packet_sequence_gap_total_reordered_after_hard_failure')}, "
                f"post_failure_forward_jumps={numeric_text(summary_row, 'packet_sequence_gap_total_missing_after_hard_failure')}, "
                f"post_failure_max_sequence_gap={numeric_text(summary_row, 'max_packet_sequence_gap_after_hard_failure')}, "
                f"activation_to_failure_unobserved={numeric_text(summary_row, 'packet_sequence_gap_total_unobserved_between_activation_and_failure')}"
            )
            lines.append(
                "      "
                f"activation_to_failure_reordered={numeric_text(summary_row, 'packet_sequence_gap_total_reordered_between_activation_and_failure')}, "
                f"activation_to_failure_out_of_order_events={numeric_text(summary_row, 'packet_sequence_out_of_order_event_count_between_activation_and_failure')}, "
                f"activation_to_failure_forward_jumps={numeric_text(summary_row, 'packet_sequence_gap_total_missing_between_activation_and_failure')}"
            )
            lines.append(
                "      "
                f"activation_to_failure_unobserved_per_activation_queue_packet={numeric_text(summary_row, 'activation_to_failure_unobserved_per_activation_queue_packet')}, "
                f"activation_to_failure_reordered_per_activation_queue_packet={numeric_text(summary_row, 'activation_to_failure_reordered_per_activation_queue_packet')}"
            )
            lines.append(
                "      "
                f"after_activation_unobserved={numeric_text(summary_row, 'packet_sequence_gap_total_unobserved_after_protection_activation')}, "
                f"after_activation_reordered={numeric_text(summary_row, 'packet_sequence_gap_total_reordered_after_protection_activation')}, "
                f"critical_interval_unobserved={numeric_text(summary_row, 'packet_sequence_gap_total_unobserved_after_critical_start')}, "
                f"critical_interval_reordered={numeric_text(summary_row, 'packet_sequence_gap_total_reordered_after_critical_start')}, "
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
        if reactive_baseline is None:
            reactive_baseline = next(
                (row for row in cohort_rows if str(row["mechanism_family"]) == "ospf_only"),
                None,
            )
        if reactive_baseline is not None and len(cohort_rows) > 1:
            lines.append(f"    Descriptive contrasts vs {reactive_baseline['mechanism_family']}:")
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
                    f"(candidate - baseline) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'service_interruption_duration_s')}; "
                    f"recovery_time_after_failure_s mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'recovery_time_after_failure_s')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"tcp_service_interruption_duration_s mean difference "
                    f"(candidate - baseline) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'tcp_service_interruption_duration_s')}; "
                    f"tcp_zero_goodput_window_count_after_reference mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'tcp_zero_goodput_window_count_after_reference')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"zero_progress_window_count_after_reference mean difference "
                    f"(candidate - baseline) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'zero_progress_window_count_after_reference')}; "
                    f"missed_protection {rate_text(summary_row, 'missed_protection')} "
                    f"vs {rate_text(reactive_baseline, 'missed_protection')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"packet_sequence_gap_total_unobserved_after_reference mean difference "
                    f"(candidate - baseline) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_unobserved_after_reference')}; "
                    f"packet_sequence_gap_total_reordered_after_reference mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_reordered_after_reference')}; "
                    f"legacy forward-jump mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_missing_after_reference')}; "
                    f"max_packet_interarrival_gap_after_reference_s mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'max_packet_interarrival_gap_after_reference_s')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"post-failure unobserved mean difference "
                    f"(candidate - baseline) = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_unobserved_after_hard_failure')}; "
                    f"post-failure reordered mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_reordered_after_hard_failure')}; "
                    f"critical-interval unobserved mean difference = "
                    f"{descriptive_delta_text(reactive_baseline, summary_row, 'packet_sequence_gap_total_unobserved_after_critical_start')}"
                )
                lines.append(
                    "      "
                    f"{summary_row['mechanism_label']}: "
                    f"activation-to-failure unobserved mean = "
                    f"{numeric_text(summary_row, 'packet_sequence_gap_total_unobserved_between_activation_and_failure')}; "
                    f"activation-to-failure reordered mean = "
                    f"{numeric_text(summary_row, 'packet_sequence_gap_total_reordered_between_activation_and_failure')}; "
                    f"queue-normalized reordered mean = "
                    f"{numeric_text(summary_row, 'activation_to_failure_reordered_per_activation_queue_packet')}"
                )
        lines.append("")

    lines.append("Generated Files")
    lines.append(f"  consolidated runs: {output_paths['runs']}")
    lines.append(f"  cohort summary: {output_paths['summary']}")
    lines.append(f"  report: {output_paths['report']}")
    if headline_rows:
        lines.append(f"  degraded-link headline summary CSV: {output_paths['headline_csv']}")
        lines.append(f"  degraded-link headline summary TXT: {output_paths['headline_txt']}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    total_start = time.perf_counter()
    args = parse_args()
    print("[compare_outcomes] Loading outcome inputs")
    input_paths, skipped_paths = resolve_input_paths(args)
    print(f"[compare_outcomes] Inputs: {', '.join(str(path) for path in input_paths)}")
    rows = collect_rows(input_paths)
    print(f"[compare_outcomes] Loaded {len(rows)} run-level outcome row(s)")
    summary_rows = grouped_summary_rows(rows)
    headline_rows = build_degraded_link_headline_rows(summary_rows)

    output_prefix = resolve_project_path(args.output_prefix)
    output_paths = {
        "runs": output_prefix.with_name(f"{output_prefix.name}_runs.csv"),
        "summary": output_prefix.with_name(f"{output_prefix.name}_summary.csv"),
        "report": output_prefix.with_name(f"{output_prefix.name}_report.txt"),
        "headline_csv": output_prefix.with_name(f"{output_prefix.name}_headline_summary.csv"),
        "headline_txt": output_prefix.with_name(f"{output_prefix.name}_headline_summary.txt"),
    }

    regenerate_command = (
        "py -3 analysis\\compare_outcomes.py --inputs "
        f"{' '.join(str(path) for path in input_paths)} --output-prefix {output_prefix}"
    )
    for output_path in output_paths.values():
        warn_if_existing_output_stale(output_path, input_paths, regenerate_command)

    write_csv(output_paths["runs"], rows)
    write_csv(output_paths["summary"], summary_rows)
    if headline_rows:
        write_csv(output_paths["headline_csv"], headline_rows)
        atomic_write_text(
            output_paths["headline_txt"],
            render_degraded_link_headline_summary(headline_rows),
        )

    report_text = render_report(
        input_paths=input_paths,
        skipped_paths=skipped_paths,
        rows=rows,
        summary_rows=summary_rows,
        headline_rows=headline_rows,
        output_paths=output_paths,
    )
    atomic_write_text(output_paths["report"], report_text)

    print(f"Wrote consolidated run table to {output_paths['runs']}")
    print(f"Wrote cohort summary to {output_paths['summary']}")
    if headline_rows:
        print(f"Wrote degraded-link headline summary to {output_paths['headline_csv']}")
        print(f"Wrote degraded-link headline report to {output_paths['headline_txt']}")
    print(f"Wrote report to {output_paths['report']}")
    print(f"[compare_outcomes] Total elapsed: {elapsed_text(total_start)}")


if __name__ == "__main__":
    main()
