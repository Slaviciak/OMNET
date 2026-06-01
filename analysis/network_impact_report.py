#!/usr/bin/env python3
"""Generate an analysis-only network-impact report for the active cohort.

The report reads existing compact dataset/outcome CSV artifacts. It does not
parse raw .vec files, change existing schemas, or modify simulator behavior.
Continuity metrics are receiver-observed diagnostics; ratio fields are proxies
unless exact sent/received accounting is explicitly available.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from collections import defaultdict
from pathlib import Path
from statistics import fmean, stdev


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
DATASET_DIR = OUTPUT_ROOT / "datasets"
OUTCOMES_DIR = OUTPUT_ROOT / "outcomes"
NETWORK_IMPACT_DIR = OUTPUT_ROOT / "network_impact"

DEFAULT_SCENARIO = "regionalbackbone_failure_detection_degraded_link_model_family"
COST_AWARE_BACKUP_SCENARIO = "regionalbackbone_failure_detection_cost_aware_backup"
COST_AWARE_TRANSPORT_SCENARIO = "regionalbackbone_failure_detection_cost_aware_transport_impact"
COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO = "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented"
TRANSPORT_SCENARIOS = {COST_AWARE_TRANSPORT_SCENARIO, COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO}

MECHANISM_ORDER = {
    "ospf_only": 0,
    "bfd_like_frr": 1,
    "aimrce_rule_based_frr": 2,
    "aimrce_logistic_regression_frr": 3,
    "aimrce_linear_svm_frr": 4,
    "aimrce_shallow_tree_frr": 5,
    "hybrid_bfd_like_aimrce_frr": 6,
}

MECHANISM_LABELS = {
    "ospf_only": "OSPF only",
    "bfd_like_frr": "OSPF + BFD-like + FRR-like routes",
    "aimrce_rule_based_frr": "AI-MRCE rule-based + FRR-like routes",
    "aimrce_logistic_regression_frr": "AI-MRCE logistic-regression + FRR-like routes",
    "aimrce_linear_svm_frr": "AI-MRCE linear-SVM + FRR-like routes",
    "aimrce_shallow_tree_frr": "AI-MRCE shallow-tree + FRR-like routes",
    "hybrid_bfd_like_aimrce_frr": "Hybrid BFD-like + AI-MRCE + FRR-like routes",
}

PHASES = (
    "pre_degradation",
    "degradation_pre_activation",
    "activation_to_failure",
    "post_hard_failure",
)

PHASE_LABELS = {
    "pre_degradation": "pre-degradation",
    "degradation_pre_activation": "degradation before activation",
    "activation_to_failure": "activation-to-failure",
    "post_hard_failure": "post-hard-failure",
}

PHASE_FIELD_SUFFIXES = (
    "duration_s",
    "received_packets",
    "expected_packets_proxy",
    "delivery_ratio_proxy",
    "udp_delay_mean_s",
    "udp_delay_max_s",
    "udp_delay_variation_proxy_mean_abs_delta_s",
    "udp_delay_variation_proxy_max_abs_delta_s",
    "udp_throughput_mean_bps",
    "udp_throughput_last_bps",
    "udp_goodput_mean_bps",
    "queue_length_mean_pk",
    "queue_length_max_pk",
    "queue_length_last_pk",
    "queue_bit_length_mean_b",
    "queue_bit_length_max_b",
    "queue_bit_length_last_b",
    "queueing_time_mean_s",
    "queueing_time_max_s",
    "queueing_time_last_s",
    "controller_delay_mean_s",
    "controller_delay_max_s",
    "controller_packet_error_rate_mean",
    "controller_packet_error_rate_max",
    "service_available_rate",
)

BY_RUN_FIELDNAMES = [
    "scenario",
    "degradation_profile",
    "mechanism_family",
    "mechanism_label",
    "run",
    "runtime_model_type",
    "trigger_source",
    "activation_time_s",
    "hard_failure_time_s",
    "lead_time_s",
    "fallback_used",
    "repairRouteCount",
    "repair_route_install_time_s",
    "early_backup_usage_time_s",
    "time_on_backup_before_hard_failure_s",
    "avoided_post_failure_unobserved_vs_ospf",
    "post_activation_udp_delay_mean_s",
    "backup_path_cost_model_note",
    "activation_queue_length_pk",
    "activation_queue_bit_length_b",
    "activation_probe_delay_mean_s",
    "activation_probe_throughput_bps",
    "activation_risk_score",
    "activation_decision_threshold",
    "activation_positive_decision_streak",
    "post_failure_unobserved",
    "post_failure_reordered",
    "post_failure_out_of_order_events",
    "activation_to_failure_unobserved",
    "activation_to_failure_reordered",
    "out_of_order_events",
    "post_failure_unobserved_improvement_vs_ospf_same_run",
    "post_failure_unobserved_ratio_proxy",
    "post_failure_reordered_ratio_proxy",
    "activation_to_failure_unobserved_ratio_proxy",
    "activation_to_failure_reordered_ratio_proxy",
    "bfd_like_detection_time_s",
    "bfd_like_lead_time_before_failure_s",
    "bfd_like_missed_probe_count",
    "bfd_like_probe_loss_rate_observed",
    "bfd_like_modeled_loss_probability_at_detection",
    "bfd_like_trigger_reason",
    "degradation_start_time_s",
    "degradation_end_time_s",
    "degradation_target_delay_s",
    "degradation_target_packet_error_rate",
    "metric_quality_notes",
]

for phase in PHASES:
    BY_RUN_FIELDNAMES.extend(f"{phase}_{suffix}" for suffix in PHASE_FIELD_SUFFIXES)

SUMMARY_BASE_FIELDNAMES = [
    "scenario",
    "degradation_profile",
    "mechanism_family",
    "mechanism_label",
    "runs",
    "runtime_model_types",
    "trigger_sources",
    "fallback_count",
    "repairRouteCount_values",
    "repairRouteCount_consistent",
    "key_interpretation_note",
]

SUMMARY_NUMERIC_FIELDS = [
    "activation_time_s",
    "lead_time_s",
    "post_failure_unobserved",
    "post_failure_reordered",
    "activation_to_failure_unobserved",
    "activation_to_failure_reordered",
    "post_failure_unobserved_improvement_vs_ospf_same_run",
    "post_failure_unobserved_ratio_proxy",
    "activation_to_failure_unobserved_ratio_proxy",
    "bfd_like_detection_time_s",
    "bfd_like_lead_time_before_failure_s",
    "bfd_like_modeled_loss_probability_at_detection",
    "activation_queue_length_pk",
    "activation_queue_bit_length_b",
    "activation_probe_delay_mean_s",
    "activation_probe_throughput_bps",
    "activation_risk_score",
    "activation_decision_threshold",
    "post_hard_failure_delivery_ratio_proxy",
    "post_hard_failure_udp_delay_mean_s",
    "post_hard_failure_udp_delay_max_s",
    "post_hard_failure_udp_throughput_mean_bps",
    "post_hard_failure_queue_length_mean_pk",
    "post_hard_failure_queueing_time_mean_s",
    "post_hard_failure_controller_packet_error_rate_mean",
    "activation_to_failure_delivery_ratio_proxy",
    "activation_to_failure_udp_delay_mean_s",
    "activation_to_failure_udp_delay_max_s",
    "activation_to_failure_udp_throughput_mean_bps",
    "activation_to_failure_queue_length_mean_pk",
    "activation_to_failure_queueing_time_mean_s",
    "activation_to_failure_controller_packet_error_rate_mean",
    "early_backup_usage_time_s",
    "time_on_backup_before_hard_failure_s",
    "avoided_post_failure_unobserved_vs_ospf",
]

SUMMARY_FIELDNAMES = SUMMARY_BASE_FIELDNAMES[:]
for field in SUMMARY_NUMERIC_FIELDS:
    SUMMARY_FIELDNAMES.extend([f"{field}_mean", f"{field}_std"])

BACKUP_COST_BY_RUN_FIELDS = [
    "scenario",
    "degradation_profile",
    "mechanism_family",
    "run",
    "activation_time_s",
    "lead_time_s",
    "early_backup_usage_time_s",
    "avoided_post_failure_unobserved_vs_ospf",
    "activation_to_failure_unobserved",
    "activation_to_failure_reordered",
    "out_of_order_events",
    "post_activation_udp_delay_mean_s",
    "activation_to_failure_udp_delay_mean_s",
    "activation_to_failure_queueing_time_mean_s",
    "activation_to_failure_udp_throughput_mean_bps",
    "repairRouteCount",
    "repair_route_install_time_s",
    "backup_path_cost_model_note",
]

BACKUP_COST_SUMMARY_FIELDS = [
    "scenario",
    "degradation_profile",
    "mechanism_family",
    "runs",
    "early_backup_usage_time_s_mean",
    "avoided_post_failure_unobserved_vs_ospf_mean",
    "activation_to_failure_reordered_mean",
    "activation_to_failure_unobserved_mean",
    "post_activation_udp_delay_mean_s_mean",
    "activation_to_failure_queueing_time_mean_s_mean",
    "activation_to_failure_udp_throughput_mean_bps_mean",
    "benefit_cost_interpretation",
]

TRANSPORT_BY_RUN_FIELDS = [
    "scenario",
    "degradation_profile",
    "mechanism_family",
    "run",
    "activation_time_s",
    "lead_time_s",
    "early_backup_usage_time_s",
    "tcp_received_bytes_total",
    "tcp_goodput_mean_bps",
    "tcp_active_window_count",
    "tcp_service_available_rate",
    "tcp_materially_degraded_rate",
    "tcp_service_interruption_observed",
    "tcp_service_interruption_duration_s",
    "tcp_zero_goodput_window_count_after_reference",
    "tcp_max_zero_goodput_window_streak_after_reference",
    "tcp_useful_goodput_restored_after_failure",
    "tcp_endpoint_receive_event_count_after_reference",
    "tcp_first_endpoint_receive_delay_after_reference_s",
    "tcp_max_endpoint_receive_gap_after_reference_s",
    "tcp_metric_quality_notes",
]

TRANSPORT_SUMMARY_FIELDS = [
    "scenario",
    "degradation_profile",
    "mechanism_family",
    "runs",
    "tcp_received_bytes_total_mean",
    "tcp_goodput_mean_bps_mean",
    "tcp_service_available_rate_mean",
    "tcp_materially_degraded_rate_mean",
    "tcp_service_interruption_duration_s_mean",
    "tcp_zero_goodput_window_count_after_reference_mean",
    "tcp_max_endpoint_receive_gap_after_reference_s_mean",
    "transport_interpretation",
]

INET_METRICS_SUMMARY_FIELDS = [
    "scenario",
    "degradation_profile",
    "mechanism_family",
    "runs",
    "udp_flow_count",
    "udp_packets_sent_total",
    "udp_packets_received_total",
    "udp_packet_loss_count",
    "udp_packet_loss_percent",
    "udp_delay_mean_ms",
    "udp_delay_p50_ms",
    "udp_delay_p95_ms",
    "udp_delay_p99_ms",
    "udp_ipdv_mean_ms",
    "udp_ipdv_p95_ms",
    "udp_throughput_mean_kbps",
    "tcp_received_bytes_total",
    "tcp_goodput_mean_kbps",
    "tcp_endpoint_delay_mean_ms",
    "tcp_rtt_mean_ms",
    "tcp_cwnd_mean",
    "tcp_retransmission_count",
    "queue_drop_event_count",
    "queue_drop_bytes_sum",
    "primary_queueing_time_p95_ms",
    "backup_queueing_time_p95_ms",
    "primary_link_utilization_mean_percent",
    "backup_link_utilization_mean_percent",
    "metric_quality_notes",
]

INET_METRICS_BY_RUN_FIELDS = [
    "scenario",
    "degradation_profile",
    "mechanism_family",
    "run",
    "config_name",
    *INET_METRICS_SUMMARY_FIELDS[4:],
]

RESULTS_ROOT = PROJECT_ROOT / "results" / "regionalbackbone"
UDP_APP_INDICES = tuple(range(7))
TCP_CLIENT_APP_INDEX = 7
PRIMARY_QUEUE_MODULES = {
    "RegionalBackbone.coreNW.eth[1].queue",
    "RegionalBackbone.coreNE.eth[0].queue",
}
BACKUP_QUEUE_MODULES = {
    "RegionalBackbone.accessA.eth[2].queue",
    "RegionalBackbone.west2.eth[1].queue",
    "RegionalBackbone.coreSW.eth[1].queue",
    "RegionalBackbone.coreSE.eth[3].queue",
    "RegionalBackbone.east2.eth[1].queue",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a behavior-neutral UDP/QoS network-impact report from existing AI-MRCE outputs."
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help=f"Scenario to summarize. Default: {DEFAULT_SCENARIO}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=NETWORK_IMPACT_DIR,
        help="Directory for generated network-impact outputs.",
    )
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def atomic_temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.tmp")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = atomic_temp_path(path)
    try:
        temp_path.write_text(text, encoding="utf-8", newline="\n")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = atomic_temp_path(path)
    try:
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def elapsed_text(start_time: float) -> str:
    return f"{time.perf_counter() - start_time:.2f}s"


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required input is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: object) -> int | None:
    numeric = parse_float(value)
    if numeric is None:
        return None
    return int(numeric)


def numeric_or_blank(value: float | int | None) -> object:
    return "" if value is None else value


def mean_or_none(values: list[float]) -> float | None:
    return fmean(values) if values else None


def max_or_none(values: list[float]) -> float | None:
    return max(values) if values else None


def sum_or_none(values: list[float]) -> float | None:
    return sum(values) if values else None


def percentile_or_none(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (percentile / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def ratio_or_none(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def numeric_values(rows: list[dict[str, str]], column: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = parse_float(row.get(column))
        if value is not None:
            values.append(value)
    return values


def scenario_results_dir(scenario: str) -> Path:
    if scenario == COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
        return RESULTS_ROOT / "ti_inst"
    if scenario == COST_AWARE_TRANSPORT_SCENARIO:
        return RESULTS_ROOT / "failure_detection_cost_aware_transport_impact"
    if scenario == COST_AWARE_BACKUP_SCENARIO:
        return RESULTS_ROOT / "failure_detection_cost_aware_backup"
    return RESULTS_ROOT / "failure_detection_degraded_link_model_family"


def result_file_candidates(scenario: str, config_name: str, run: int, suffix: str) -> list[Path]:
    result_dir = scenario_results_dir(scenario)
    candidates = [
        result_dir / f"{config_name}Cohort-{run}{suffix}",
        result_dir / f"{config_name}-{run}{suffix}",
    ]
    if config_name.endswith("Cohort"):
        candidates.insert(0, result_dir / f"{config_name}-{run}{suffix}")
    return candidates


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def parse_all_scalars(sca_path: Path) -> dict[tuple[str, str], float]:
    scalars: dict[tuple[str, str], float] = {}
    if not sca_path.exists():
        return scalars
    with sca_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line.startswith("scalar "):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            module, name, raw_value = parts[1], parts[2], parts[3]
            try:
                scalars[(module, name)] = float(raw_value)
            except ValueError:
                continue
    return scalars


def parse_histograms(sca_path: Path) -> dict[tuple[str, str], list[tuple[float, float]]]:
    histograms: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    if not sca_path.exists():
        return histograms

    current_key: tuple[str, str] | None = None
    with sca_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith("statistic "):
                parts = line.split()
                current_key = None
                if len(parts) >= 3 and parts[2].endswith(":histogram"):
                    current_key = (parts[1], parts[2].removesuffix(":histogram"))
                continue
            if line.startswith(("scalar ", "par ", "config ", "attr ")) and not line.startswith("attr "):
                current_key = None
            if current_key is None or not line.startswith("bin"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                bound = float(parts[1])
                count = float(parts[2])
            except ValueError:
                continue
            if count > 0 and not (bound == float("inf") or bound == float("-inf")):
                histograms[current_key].append((bound, count))
    return dict(histograms)


def should_keep_vector(module: str, name: str) -> bool:
    if module.startswith("RegionalBackbone.hostB.app[") and any(
        name == metric or name.startswith(f"{metric}:")
        for metric in ("endToEndDelay", "throughput", "rcvdPkSeqNo", "packetReceived")
    ):
        return True
    if module == f"RegionalBackbone.hostA.app[{TCP_CLIENT_APP_INDEX}]" and (
        name == "endToEndDelay"
        or name.startswith("endToEndDelay:")
        or name == "packetReceived"
        or name.startswith("packetReceived:")
    ):
        return True
    if module in PRIMARY_QUEUE_MODULES | BACKUP_QUEUE_MODULES and any(
        token in name
        for token in ("queueLength", "queueingTime", "incomingDataRate", "outgoingDataRate", "droppedPacketLengthsQueueOverflow")
    ):
        return True
    lower_name = name.lower()
    lower_module = module.lower()
    if ".tcp" in lower_module and any(token in lower_name for token in ("rtt", "srtt", "cwnd", "retrans", "numrto")):
        return True
    return False


def parse_selected_vectors(vec_path: Path) -> dict[tuple[str, str], list[tuple[float, float]]]:
    vectors: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    if not vec_path.exists():
        return vectors

    vector_id_to_key: dict[str, tuple[str, str]] = {}
    with vec_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("vector "):
                parts = line.split()
                if len(parts) >= 4:
                    vector_id, module, name = parts[1], parts[2], parts[3]
                    if should_keep_vector(module, name):
                        vector_id_to_key[vector_id] = (module, name)
                continue

            first = line.split(maxsplit=1)[0]
            key = vector_id_to_key.get(first)
            if key is None:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                timestamp = float(parts[2])
                value = float(parts[3])
            except ValueError:
                continue
            vectors[key].append((timestamp, value))
    return dict(vectors)


def vector_values(
    vectors: dict[tuple[str, str], list[tuple[float, float]]],
    module_predicate,
    name_predicate,
) -> list[float]:
    values: list[float] = []
    for (module, name), samples in vectors.items():
        if module_predicate(module) and name_predicate(name):
            values.extend(value for _, value in samples)
    return values


def vector_ipdv_ms(
    vectors: dict[tuple[str, str], list[tuple[float, float]]],
    module_predicate,
    name_predicate,
) -> list[float]:
    deltas: list[float] = []
    for (module, name), samples in vectors.items():
        if not (module_predicate(module) and name_predicate(name)):
            continue
        ordered = sorted(samples)
        for index in range(1, len(ordered)):
            deltas.append(abs(ordered[index][1] - ordered[index - 1][1]) * 1000.0)
    return deltas


def sum_scalar_suffix(scalars: dict[tuple[str, str], float], module: str, name_prefix: str) -> float | None:
    values = [
        value for (scalar_module, scalar_name), value in scalars.items()
        if scalar_module == module and (scalar_name == name_prefix or scalar_name.startswith(f"{name_prefix}:"))
    ]
    return sum_or_none(values)


def scalar_values(
    scalars: dict[tuple[str, str], float],
    module_predicate,
    name_predicate,
) -> list[float]:
    return [
        value
        for (module, name), value in scalars.items()
        if module_predicate(module) and name_predicate(name)
    ]


def weighted_scalar_mean(
    scalars: dict[tuple[str, str], float],
    module_names: list[str],
    value_suffix: str,
    weight_suffix: str,
) -> float | None:
    weighted_sum = 0.0
    weight_sum = 0.0
    fallback: list[float] = []
    for module in module_names:
        value = scalars.get((module, value_suffix))
        if value is None:
            continue
        fallback.append(value)
        weight = scalars.get((module, weight_suffix))
        if weight is not None and weight > 0:
            weighted_sum += value * weight
            weight_sum += weight
    if weight_sum > 0:
        return weighted_sum / weight_sum
    return mean_or_none(fallback)


def histogram_percentile(
    histograms: dict[tuple[str, str], list[tuple[float, float]]],
    module_names: list[str],
    metric_name: str,
    percentile: float,
) -> float | None:
    bins: dict[float, float] = defaultdict(float)
    for module in module_names:
        for bound, count in histograms.get((module, metric_name), []):
            bins[bound] += count
    if not bins:
        return None
    total = sum(bins.values())
    if total <= 0:
        return None
    threshold = total * percentile / 100.0
    cumulative = 0.0
    for bound, count in sorted(bins.items()):
        cumulative += count
        if cumulative >= threshold:
            return bound
    return max(bins)



def latest_value(rows: list[dict[str, str]], column: str) -> float | None:
    for row in reversed(rows):
        value = parse_float(row.get(column))
        if value is not None:
            return value
    return None


def weighted_mean(rows: list[dict[str, str]], value_column: str, weight_column: str) -> float | None:
    weighted_sum = 0.0
    weight_sum = 0.0
    fallback_values: list[float] = []
    for row in rows:
        value = parse_float(row.get(value_column))
        if value is None:
            continue
        fallback_values.append(value)
        weight = parse_float(row.get(weight_column))
        if weight is not None and weight > 0:
            weighted_sum += value * weight
            weight_sum += weight
    if weight_sum > 0:
        return weighted_sum / weight_sum
    return mean_or_none(fallback_values)


def sorted_rows_by_time(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: parse_float(row.get("window_start_s")) or 0.0)


def group_dataset_rows(dataset_rows: list[dict[str, str]]) -> dict[tuple[str, str, int], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, int], list[dict[str, str]]] = defaultdict(list)
    for row in dataset_rows:
        profile = row.get("degradation_profile", "")
        mechanism = row.get("protection_mode", "")
        run = parse_int(row.get("run_number"))
        if not mechanism or run is None:
            continue
        grouped[(profile, mechanism, run)].append(row)
    return {key: sorted_rows_by_time(rows) for key, rows in grouped.items()}


def detect_degradation_start(rows: list[dict[str, str]]) -> float | None:
    for row in rows:
        per_values = [
            parse_float(row.get("controller_packet_error_rate_mean")),
            parse_float(row.get("controller_packet_error_rate_max")),
            parse_float(row.get("controller_packet_error_rate_last")),
        ]
        if any(value is not None and value > 0.0 for value in per_values):
            return parse_float(row.get("window_start_s"))

    for row in rows:
        delay_values = [
            parse_float(row.get("controller_delay_mean_s")),
            parse_float(row.get("controller_delay_max_s")),
            parse_float(row.get("controller_delay_last_s")),
        ]
        if any(value is not None and value > 1e-6 for value in delay_values):
            return parse_float(row.get("window_start_s"))
    return None


def select_phase_rows(
    rows: list[dict[str, str]],
    phase: str,
    degradation_start: float | None,
    activation_time: float | None,
    hard_failure_time: float | None,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        window_start = parse_float(row.get("window_start_s"))
        if window_start is None:
            continue

        include = False
        if phase == "pre_degradation":
            include = degradation_start is not None and window_start < degradation_start
        elif phase == "degradation_pre_activation":
            if degradation_start is not None and hard_failure_time is not None:
                end_time = activation_time if activation_time is not None and activation_time > degradation_start else hard_failure_time
                include = degradation_start <= window_start < end_time
        elif phase == "activation_to_failure":
            include = (
                activation_time is not None
                and hard_failure_time is not None
                and activation_time < hard_failure_time
                and activation_time <= window_start < hard_failure_time
            )
        elif phase == "post_hard_failure":
            include = hard_failure_time is not None and window_start >= hard_failure_time

        if include:
            selected.append(row)
    return selected


def phase_duration(rows: list[dict[str, str]]) -> float | None:
    durations: list[float] = []
    for row in rows:
        start = parse_float(row.get("window_start_s"))
        end = parse_float(row.get("window_end_s"))
        if start is not None and end is not None and end > start:
            durations.append(end - start)
    return sum_or_none(durations)


def delay_variation_proxy(rows: list[dict[str, str]]) -> tuple[float | None, float | None]:
    values: list[tuple[float, float]] = []
    for row in rows:
        window_start = parse_float(row.get("window_start_s"))
        delay = parse_float(row.get("receiver_app0_e2e_delay_mean_s"))
        if window_start is not None and delay is not None:
            values.append((window_start, delay))
    values.sort()
    deltas = [abs(values[index][1] - values[index - 1][1]) for index in range(1, len(values))]
    return mean_or_none(deltas), max_or_none(deltas)


def summarize_phase(rows: list[dict[str, str]], expected_packet_rate_pps: float | None) -> dict[str, object]:
    duration = phase_duration(rows)
    received_packets = sum_or_none(numeric_values(rows, "receiver_app0_packet_count"))
    expected_packets = expected_packet_rate_pps * duration if expected_packet_rate_pps is not None and duration is not None else None
    delay_proxy_mean, delay_proxy_max = delay_variation_proxy(rows)

    return {
        "duration_s": numeric_or_blank(duration),
        "received_packets": numeric_or_blank(received_packets),
        "expected_packets_proxy": numeric_or_blank(expected_packets),
        "delivery_ratio_proxy": numeric_or_blank(ratio_or_none(received_packets, expected_packets)),
        "udp_delay_mean_s": numeric_or_blank(
            weighted_mean(rows, "receiver_app0_e2e_delay_mean_s", "receiver_app0_packet_count")
        ),
        "udp_delay_max_s": numeric_or_blank(max_or_none(numeric_values(rows, "receiver_app0_e2e_delay_max_s"))),
        "udp_delay_variation_proxy_mean_abs_delta_s": numeric_or_blank(delay_proxy_mean),
        "udp_delay_variation_proxy_max_abs_delta_s": numeric_or_blank(delay_proxy_max),
        "udp_throughput_mean_bps": numeric_or_blank(mean_or_none(numeric_values(rows, "receiver_app0_throughput_mean_bps"))),
        "udp_throughput_last_bps": numeric_or_blank(latest_value(rows, "receiver_app0_throughput_last_bps")),
        "udp_goodput_mean_bps": numeric_or_blank(mean_or_none(numeric_values(rows, "receiver_app0_goodput_mean_bps"))),
        "queue_length_mean_pk": numeric_or_blank(mean_or_none(numeric_values(rows, "bottleneck_queue_length_mean_pk"))),
        "queue_length_max_pk": numeric_or_blank(max_or_none(numeric_values(rows, "bottleneck_queue_length_max_pk"))),
        "queue_length_last_pk": numeric_or_blank(latest_value(rows, "bottleneck_queue_length_last_pk")),
        "queue_bit_length_mean_b": numeric_or_blank(mean_or_none(numeric_values(rows, "bottleneck_queue_bit_length_mean_b"))),
        "queue_bit_length_max_b": numeric_or_blank(max_or_none(numeric_values(rows, "bottleneck_queue_bit_length_max_b"))),
        "queue_bit_length_last_b": numeric_or_blank(latest_value(rows, "bottleneck_queue_bit_length_last_b")),
        "queueing_time_mean_s": numeric_or_blank(mean_or_none(numeric_values(rows, "bottleneck_queueing_time_mean_s"))),
        "queueing_time_max_s": numeric_or_blank(max_or_none(numeric_values(rows, "bottleneck_queueing_time_max_s"))),
        "queueing_time_last_s": numeric_or_blank(latest_value(rows, "bottleneck_queueing_time_last_s")),
        "controller_delay_mean_s": numeric_or_blank(mean_or_none(numeric_values(rows, "controller_delay_mean_s"))),
        "controller_delay_max_s": numeric_or_blank(max_or_none(numeric_values(rows, "controller_delay_max_s"))),
        "controller_packet_error_rate_mean": numeric_or_blank(
            mean_or_none(numeric_values(rows, "controller_packet_error_rate_mean"))
        ),
        "controller_packet_error_rate_max": numeric_or_blank(
            max_or_none(numeric_values(rows, "controller_packet_error_rate_max"))
        ),
        "service_available_rate": numeric_or_blank(mean_or_none(numeric_values(rows, "service_available_operational"))),
    }


def outcome_value(row: dict[str, str], column: str) -> float | None:
    return parse_float(row.get(column))


def build_metric_quality_notes(outcome_row: dict[str, str], dataset_rows: list[dict[str, str]]) -> str:
    tcp_note = (
        "tcp=endpoint_received_bytes_goodput_progress_proxy"
        if outcome_row.get("traffic_mix_model") or outcome_row.get("tcp_receiver_app_indices") or outcome_row.get("receiver_tcp_total_received_bytes")
        else "tcp=not_evaluated_udp_only_cohort"
    )
    notes = [
        "continuity=receiver_observed_diagnostic",
        "delivery_ratio=proxy_from_receiver_windows",
        "delay_variation=window_mean_delta_proxy_not_rfc5481_ipdv",
        tcp_note,
    ]
    if not dataset_rows:
        notes.append("dataset_windows_missing_phase_metrics_blank")
    if not outcome_row.get("protection_activation_time_s"):
        notes.append("no_protection_activation_activation_phase_blank")
    return "; ".join(notes)


def build_by_run_rows(
    scenario: str,
    outcome_rows: list[dict[str, str]],
    grouped_dataset: dict[tuple[str, str, int], list[dict[str, str]]],
) -> list[dict[str, object]]:
    by_run_rows: list[dict[str, object]] = []
    ospf_post_failure_by_run: dict[tuple[str, int], float] = {}

    for outcome in outcome_rows:
        if outcome.get("protection_mode") == "ospf_only":
            profile = outcome.get("degradation_profile", "")
            run = parse_int(outcome.get("run_number"))
            value = outcome_value(outcome, "packet_sequence_gap_total_unobserved_after_hard_failure")
            if run is not None and value is not None:
                ospf_post_failure_by_run[(profile, run)] = value

    for outcome in outcome_rows:
        profile = outcome.get("degradation_profile", "")
        mechanism = outcome.get("protection_mode", "")
        run = parse_int(outcome.get("run_number"))
        if not mechanism or run is None:
            continue

        dataset_rows = grouped_dataset.get((profile, mechanism, run), [])
        degradation_start = detect_degradation_start(dataset_rows)
        activation_time = outcome_value(outcome, "protection_activation_time_s")
        hard_failure_time = outcome_value(outcome, "hard_failure_time_s")
        expected_packet_rate_pps = outcome_value(outcome, "monitored_flow_expected_packet_rate_pps")

        row: dict[str, object] = {
            "scenario": scenario,
            "degradation_profile": profile,
            "mechanism_family": mechanism,
            "mechanism_label": MECHANISM_LABELS.get(mechanism, mechanism),
            "run": run,
            "runtime_model_type": outcome.get("runtime_model_type", ""),
            "trigger_source": outcome.get("protection_trigger_source", ""),
            "activation_time_s": numeric_or_blank(activation_time),
            "hard_failure_time_s": numeric_or_blank(hard_failure_time),
            "lead_time_s": numeric_or_blank(outcome_value(outcome, "protection_lead_time_before_failure_s")),
            "fallback_used": numeric_or_blank(outcome_value(outcome, "runtime_model_fallback_used")),
            "repairRouteCount": numeric_or_blank(outcome_value(outcome, "repair_route_count")),
            "repair_route_install_time_s": numeric_or_blank(outcome_value(outcome, "repair_route_install_time_s")),
            "activation_queue_length_pk": numeric_or_blank(outcome_value(outcome, "activation_queue_length_pk")),
            "activation_queue_bit_length_b": numeric_or_blank(outcome_value(outcome, "activation_queue_bit_length_b")),
            "activation_probe_delay_mean_s": numeric_or_blank(outcome_value(outcome, "activation_probe_delay_mean_s")),
            "activation_probe_throughput_bps": numeric_or_blank(outcome_value(outcome, "activation_probe_throughput_bps")),
            "activation_risk_score": numeric_or_blank(outcome_value(outcome, "activation_risk_score")),
            "activation_decision_threshold": numeric_or_blank(outcome_value(outcome, "activation_decision_threshold")),
            "activation_positive_decision_streak": numeric_or_blank(
                outcome_value(outcome, "activation_positive_decision_streak")
            ),
            "post_failure_unobserved": numeric_or_blank(
                outcome_value(outcome, "packet_sequence_gap_total_unobserved_after_hard_failure")
            ),
            "post_failure_reordered": numeric_or_blank(
                outcome_value(outcome, "packet_sequence_gap_total_reordered_after_hard_failure")
            ),
            "post_failure_out_of_order_events": numeric_or_blank(
                outcome_value(outcome, "packet_sequence_out_of_order_event_count_after_hard_failure")
            ),
            "activation_to_failure_unobserved": numeric_or_blank(
                outcome_value(outcome, "packet_sequence_gap_total_unobserved_between_activation_and_failure")
            ),
            "activation_to_failure_reordered": numeric_or_blank(
                outcome_value(outcome, "packet_sequence_gap_total_reordered_between_activation_and_failure")
            ),
            "out_of_order_events": numeric_or_blank(
                outcome_value(outcome, "packet_sequence_out_of_order_event_count_between_activation_and_failure")
            ),
            "bfd_like_detection_time_s": numeric_or_blank(outcome_value(outcome, "bfd_like_detection_time_s")),
            "bfd_like_lead_time_before_failure_s": numeric_or_blank(
                outcome_value(outcome, "bfd_like_lead_time_before_failure_s")
            ),
            "bfd_like_missed_probe_count": numeric_or_blank(outcome_value(outcome, "bfd_like_missed_probe_count")),
            "bfd_like_probe_loss_rate_observed": numeric_or_blank(
                outcome_value(outcome, "bfd_like_probe_loss_rate_observed")
            ),
            "bfd_like_modeled_loss_probability_at_detection": numeric_or_blank(
                outcome_value(outcome, "bfd_like_modeled_probe_loss_probability_at_detection")
            ),
            "bfd_like_trigger_reason": outcome.get("bfd_like_trigger_reason_text", ""),
            "degradation_start_time_s": outcome.get("degradation_start_time_s") or numeric_or_blank(degradation_start),
            "degradation_end_time_s": outcome.get("degradation_end_time_s", ""),
            "degradation_target_delay_s": outcome.get("degradation_target_delay_s", ""),
            "degradation_target_packet_error_rate": outcome.get("degradation_target_packet_error_rate", ""),
            "metric_quality_notes": build_metric_quality_notes(outcome, dataset_rows),
        }

        for phase in PHASES:
            phase_rows = select_phase_rows(dataset_rows, phase, degradation_start, activation_time, hard_failure_time)
            phase_summary = summarize_phase(phase_rows, expected_packet_rate_pps)
            for suffix, value in phase_summary.items():
                row[f"{phase}_{suffix}"] = value

        early_backup_usage = (
            max(0.0, hard_failure_time - activation_time)
            if activation_time is not None and hard_failure_time is not None and activation_time < hard_failure_time
            else None
        )
        row["early_backup_usage_time_s"] = numeric_or_blank(early_backup_usage)
        row["time_on_backup_before_hard_failure_s"] = numeric_or_blank(early_backup_usage)
        row["post_activation_udp_delay_mean_s"] = row.get("activation_to_failure_udp_delay_mean_s", "")
        if scenario in {COST_AWARE_BACKUP_SCENARIO, *TRANSPORT_SCENARIOS}:
            row["backup_path_cost_model_note"] = (
                "cost_aware_backup: primary is normal 100Mbps lower-cost path; "
                "southern repair corridor remains 100Mbps but adds about 5ms extra path delay; "
                "cost metrics are component diagnostics, not a weighted utility claim"
            )
        else:
            row["backup_path_cost_model_note"] = "legacy cohort: no persistent backup data-plane penalty is modeled"

        post_received = parse_float(row.get("post_hard_failure_received_packets"))
        post_unobserved = outcome_value(outcome, "packet_sequence_gap_total_unobserved_after_hard_failure")
        post_reordered = outcome_value(outcome, "packet_sequence_gap_total_reordered_after_hard_failure")
        activation_received = parse_float(row.get("activation_to_failure_received_packets"))
        activation_unobserved = outcome_value(outcome, "packet_sequence_gap_total_unobserved_between_activation_and_failure")
        activation_reordered = outcome_value(outcome, "packet_sequence_gap_total_reordered_between_activation_and_failure")

        row["post_failure_unobserved_ratio_proxy"] = numeric_or_blank(
            ratio_or_none(post_unobserved, (post_unobserved or 0.0) + (post_received or 0.0))
        )
        row["post_failure_reordered_ratio_proxy"] = numeric_or_blank(
            ratio_or_none(post_reordered, (post_reordered or 0.0) + (post_received or 0.0))
        )
        row["activation_to_failure_unobserved_ratio_proxy"] = numeric_or_blank(
            ratio_or_none(activation_unobserved, (activation_unobserved or 0.0) + (activation_received or 0.0))
        )
        row["activation_to_failure_reordered_ratio_proxy"] = numeric_or_blank(
            ratio_or_none(activation_reordered, (activation_reordered or 0.0) + (activation_received or 0.0))
        )

        ospf_baseline = ospf_post_failure_by_run.get((profile, run))
        row["post_failure_unobserved_improvement_vs_ospf_same_run"] = numeric_or_blank(
            None if ospf_baseline is None or post_unobserved is None else ospf_baseline - post_unobserved
        )
        row["avoided_post_failure_unobserved_vs_ospf"] = row["post_failure_unobserved_improvement_vs_ospf_same_run"]
        by_run_rows.append(row)

    by_run_rows.sort(key=lambda item: (str(item.get("degradation_profile", "")), MECHANISM_ORDER.get(str(item["mechanism_family"]), 999), int(item["run"])))
    return by_run_rows


def distinct_text(values: list[object]) -> str:
    observed = sorted({str(value) for value in values if str(value).strip()})
    return ";".join(observed)


def mean_std_cells(rows: list[dict[str, object]], field: str) -> tuple[object, object]:
    values = [parse_float(row.get(field)) for row in rows]
    numeric = [value for value in values if value is not None]
    if not numeric:
        return "", ""
    mean_value = fmean(numeric)
    std_value = stdev(numeric) if len(numeric) > 1 else 0.0
    return mean_value, std_value


def interpretation_note(mechanism: str, rows: list[dict[str, object]]) -> str:
    post_mean, _ = mean_std_cells(rows, "post_failure_unobserved")
    activation_cost_mean, _ = mean_std_cells(rows, "activation_to_failure_reordered")
    if mechanism == "ospf_only":
        return "No-protection baseline; post-hard-failure unobserved gaps remain the reference cost."
    if mechanism == "bfd_like_frr":
        return "Reactive BFD-like comparator; compare trigger timing and post-failure gaps against OSPF because late triggers may leave failure or transition cost visible."
    if mechanism == "hybrid_bfd_like_aimrce_frr":
        return "Hybrid safety-net; AI-MRCE is first trigger in this progressive degraded-link cohort."
    if str(post_mean) == "0.0" and parse_float(activation_cost_mean) is not None:
        return "AI-MRCE policy triggers proactively; post-failure unobserved gaps are zero but transition reordering remains visible."
    return "AI-MRCE model-family policy; interpret within the deterministic progressive degraded-link cohort."


def build_summary_rows(scenario: str, by_run_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in by_run_rows:
        grouped[(str(row.get("degradation_profile", "")), str(row["mechanism_family"]))].append(row)

    summary_rows: list[dict[str, object]] = []
    for (profile, mechanism), rows in sorted(grouped.items(), key=lambda item: (item[0][0], MECHANISM_ORDER.get(item[0][1], 999))):
        repair_values = sorted({str(row.get("repairRouteCount")) for row in rows if str(row.get("repairRouteCount")).strip()})
        fallback_values = [parse_float(row.get("fallback_used")) or 0.0 for row in rows]
        summary: dict[str, object] = {
            "scenario": scenario,
            "degradation_profile": profile,
            "mechanism_family": mechanism,
            "mechanism_label": MECHANISM_LABELS.get(mechanism, mechanism),
            "runs": len(rows),
            "runtime_model_types": distinct_text([row.get("runtime_model_type", "") for row in rows]),
            "trigger_sources": distinct_text([row.get("trigger_source", "") for row in rows]),
            "fallback_count": int(sum(fallback_values)),
            "repairRouteCount_values": ";".join(repair_values),
            "repairRouteCount_consistent": 1 if len(repair_values) <= 1 else 0,
            "key_interpretation_note": interpretation_note(mechanism, rows),
        }
        for field in SUMMARY_NUMERIC_FIELDS:
            mean_value, std_value = mean_std_cells(rows, field)
            summary[f"{field}_mean"] = mean_value
            summary[f"{field}_std"] = std_value
        summary_rows.append(summary)
    return summary_rows


def build_backup_cost_rows(scenario: str, by_run_rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    cost_rows = [
        {field: row.get(field, "") for field in BACKUP_COST_BY_RUN_FIELDS}
        for row in by_run_rows
    ]
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in cost_rows:
        grouped[(str(row.get("degradation_profile", "")), str(row.get("mechanism_family", "")))].append(row)

    summary: list[dict[str, object]] = []
    for (profile, mechanism), rows in sorted(grouped.items(), key=lambda item: (item[0][0], MECHANISM_ORDER.get(item[0][1], 999))):
        early_mean, _ = mean_std_cells(rows, "early_backup_usage_time_s")
        avoided_mean, _ = mean_std_cells(rows, "avoided_post_failure_unobserved_vs_ospf")
        reordered_mean, _ = mean_std_cells(rows, "activation_to_failure_reordered")
        unobserved_mean, _ = mean_std_cells(rows, "activation_to_failure_unobserved")
        delay_mean, _ = mean_std_cells(rows, "post_activation_udp_delay_mean_s")
        queueing_mean, _ = mean_std_cells(rows, "activation_to_failure_queueing_time_mean_s")
        throughput_mean, _ = mean_std_cells(rows, "activation_to_failure_udp_throughput_mean_bps")
        if mechanism == "ospf_only":
            interpretation = "No backup activation; this is the no-protection reference for avoided-gap benefit."
        elif parse_float(avoided_mean) is not None and parse_float(early_mean) is not None:
            interpretation = "Benefit/cost components available; inspect avoided gaps, early backup time, transition reordering, and UDP delay together."
        else:
            interpretation = "Cost components partially unavailable, usually because no pre-failure activation was observed."
        summary.append({
            "scenario": scenario,
            "degradation_profile": profile,
            "mechanism_family": mechanism,
            "runs": len(rows),
            "early_backup_usage_time_s_mean": early_mean,
            "avoided_post_failure_unobserved_vs_ospf_mean": avoided_mean,
            "activation_to_failure_reordered_mean": reordered_mean,
            "activation_to_failure_unobserved_mean": unobserved_mean,
            "post_activation_udp_delay_mean_s_mean": delay_mean,
            "activation_to_failure_queueing_time_mean_s_mean": queueing_mean,
            "activation_to_failure_udp_throughput_mean_bps_mean": throughput_mean,
            "benefit_cost_interpretation": interpretation,
        })
    return cost_rows, summary


def build_transport_rows(
    scenario: str,
    outcome_rows: list[dict[str, str]],
    grouped_dataset: dict[tuple[str, str, int], list[dict[str, str]]],
    by_run_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if scenario not in TRANSPORT_SCENARIOS:
        return [], []

    activation_lookup = {
        (str(row.get("degradation_profile", "")), str(row.get("mechanism_family", "")), parse_int(row.get("run")) or 0): row
        for row in by_run_rows
    }

    transport_rows: list[dict[str, object]] = []
    for outcome in outcome_rows:
        profile = outcome.get("degradation_profile", "")
        mechanism = outcome.get("protection_mode", "")
        run = parse_int(outcome.get("run_number"))
        if not mechanism or run is None:
            continue

        dataset_rows = grouped_dataset.get((profile, mechanism, run), [])
        bytes_total = sum_or_none(numeric_values(dataset_rows, "receiver_tcp_total_received_bytes"))
        goodput_values = numeric_values(dataset_rows, "receiver_tcp_goodput_mean_bps")
        active_windows = [
            row
            for row in dataset_rows
            if (parse_float(row.get("receiver_tcp_total_received_bytes")) or 0.0) > 0.0
            or (parse_float(row.get("receiver_tcp_goodput_mean_bps")) or 0.0) > 0.0
        ]
        activation_row = activation_lookup.get((profile, mechanism, run), {})

        row = {
            "scenario": scenario,
            "degradation_profile": profile,
            "mechanism_family": mechanism,
            "run": run,
            "activation_time_s": outcome.get("protection_activation_time_s", ""),
            "lead_time_s": outcome.get("protection_lead_time_before_failure_s", ""),
            "early_backup_usage_time_s": activation_row.get("early_backup_usage_time_s", ""),
            "tcp_received_bytes_total": numeric_or_blank(bytes_total),
            "tcp_goodput_mean_bps": numeric_or_blank(mean_or_none(goodput_values)),
            "tcp_active_window_count": len(active_windows),
            "tcp_service_available_rate": numeric_or_blank(mean_or_none(numeric_values(dataset_rows, "tcp_service_available_operational"))),
            "tcp_materially_degraded_rate": numeric_or_blank(mean_or_none(numeric_values(dataset_rows, "tcp_service_materially_degraded_operational"))),
            "tcp_service_interruption_observed": outcome.get("tcp_service_interruption_observed", ""),
            "tcp_service_interruption_duration_s": outcome.get("tcp_service_interruption_duration_s", ""),
            "tcp_zero_goodput_window_count_after_reference": outcome.get("tcp_zero_goodput_window_count_after_reference", ""),
            "tcp_max_zero_goodput_window_streak_after_reference": outcome.get("tcp_max_zero_goodput_window_streak_after_reference", ""),
            "tcp_useful_goodput_restored_after_failure": outcome.get("tcp_useful_goodput_restored_after_failure", ""),
            "tcp_endpoint_receive_event_count_after_reference": outcome.get("tcp_endpoint_receive_event_count_after_reference", ""),
            "tcp_first_endpoint_receive_delay_after_reference_s": outcome.get("tcp_first_endpoint_receive_delay_after_reference_s", ""),
            "tcp_max_endpoint_receive_gap_after_reference_s": outcome.get("tcp_max_endpoint_receive_gap_after_reference_s", ""),
            "tcp_metric_quality_notes": (
                "endpoint-observed received bytes/goodput/progress proxy; "
                "TCP retransmissions, RTT, cwnd, and exact flow-completion metrics are claimed only when explicitly exported"
            ),
        }
        transport_rows.append(row)

    transport_rows.sort(
        key=lambda item: (
            str(item.get("degradation_profile", "")),
            MECHANISM_ORDER.get(str(item.get("mechanism_family", "")), 999),
            int(item.get("run") or 0),
        )
    )

    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in transport_rows:
        grouped[(str(row.get("degradation_profile", "")), str(row.get("mechanism_family", "")))].append(row)

    summary_rows: list[dict[str, object]] = []
    numeric_fields = [
        "tcp_received_bytes_total",
        "tcp_goodput_mean_bps",
        "tcp_service_available_rate",
        "tcp_materially_degraded_rate",
        "tcp_service_interruption_duration_s",
        "tcp_zero_goodput_window_count_after_reference",
        "tcp_max_endpoint_receive_gap_after_reference_s",
    ]
    for (profile, mechanism), rows in sorted(grouped.items(), key=lambda item: (item[0][0], MECHANISM_ORDER.get(item[0][1], 999))):
        summary: dict[str, object] = {
            "scenario": scenario,
            "degradation_profile": profile,
            "mechanism_family": mechanism,
            "runs": len(rows),
        }
        for field in numeric_fields:
            mean_value, _ = mean_std_cells(rows, field)
            summary[f"{field}_mean"] = mean_value
        if mechanism == "ospf_only":
            interpretation = "No protection baseline for mixed UDP/TCP endpoint progress."
        elif mechanism == "bfd_like_frr":
            interpretation = "Reactive comparator; inspect TCP endpoint-goodput/progress against activation timing and UDP gaps."
        else:
            interpretation = "AI-MRCE policy; TCP values are endpoint progress proxies, not protocol-internal TCP recovery metrics."
        summary["transport_interpretation"] = interpretation
        summary_rows.append(summary)

    return transport_rows, summary_rows


def build_inet_metrics_rows(scenario: str, outcome_rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if scenario != COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
        return [], []

    by_run_rows: list[dict[str, object]] = []
    for outcome in outcome_rows:
        profile = outcome.get("degradation_profile", "")
        mechanism = outcome.get("protection_mode", "")
        config_name = outcome.get("config_name", "")
        run = parse_int(outcome.get("run_number"))
        if not mechanism or not config_name or run is None:
            continue

        sca_path = first_existing(result_file_candidates(scenario, config_name, run, ".sca"))
        vec_path = first_existing(result_file_candidates(scenario, config_name, run, ".vec"))
        scalars = parse_all_scalars(sca_path) if sca_path is not None else {}
        histograms = parse_histograms(sca_path) if sca_path is not None else {}
        vectors = parse_selected_vectors(vec_path) if vec_path is not None else {}

        udp_sent_total = 0.0
        udp_received_total = 0.0
        udp_flow_count = 0
        for app_index in UDP_APP_INDICES:
            sent = sum_scalar_suffix(scalars, f"RegionalBackbone.hostA.app[{app_index}]", "packetSent")
            received = sum_scalar_suffix(scalars, f"RegionalBackbone.hostB.app[{app_index}]", "packetReceived")
            if sent is None and received is None:
                continue
            udp_flow_count += 1
            udp_sent_total += sent or 0.0
            udp_received_total += received or 0.0

        udp_loss_count = max(0.0, udp_sent_total - udp_received_total) if udp_sent_total > 0 else None
        udp_loss_percent = (100.0 * udp_loss_count / udp_sent_total) if udp_loss_count is not None and udp_sent_total > 0 else None
        udp_modules = [f"RegionalBackbone.hostB.app[{app_index}]" for app_index in UDP_APP_INDICES]
        udp_delay_values_s = vector_values(
            vectors,
            lambda module: module.startswith("RegionalBackbone.hostB.app["),
            lambda name: name == "endToEndDelay" or name.startswith("endToEndDelay:"),
        )
        udp_delay_values_ms = [value * 1000.0 for value in udp_delay_values_s]
        udp_ipdv_values_ms = vector_ipdv_ms(
            vectors,
            lambda module: module.startswith("RegionalBackbone.hostB.app["),
            lambda name: name == "endToEndDelay" or name.startswith("endToEndDelay:"),
        )
        udp_throughput_values_kbps = [
            value / 1000.0
            for value in vector_values(
                vectors,
                lambda module: module.startswith("RegionalBackbone.hostB.app["),
                lambda name: name == "throughput" or name.startswith("throughput:"),
            )
            if value >= 0
        ]
        scalar_udp_delay_mean_ms = weighted_scalar_mean(
            scalars,
            udp_modules,
            "endToEndDelay:mean",
            "packetReceived:count",
        )
        scalar_udp_throughput_kbps = mean_or_none([
            value / 1000.0
            for value in scalar_values(
                scalars,
                lambda module: module in udp_modules,
                lambda name: name == "throughput:mean",
            )
        ])
        histogram_udp_p50_ms = (histogram_percentile(histograms, udp_modules, "endToEndDelay", 50.0) or 0.0) * 1000.0 if histogram_percentile(histograms, udp_modules, "endToEndDelay", 50.0) is not None else None
        histogram_udp_p95_ms = (histogram_percentile(histograms, udp_modules, "endToEndDelay", 95.0) or 0.0) * 1000.0 if histogram_percentile(histograms, udp_modules, "endToEndDelay", 95.0) is not None else None
        histogram_udp_p99_ms = (histogram_percentile(histograms, udp_modules, "endToEndDelay", 99.0) or 0.0) * 1000.0 if histogram_percentile(histograms, udp_modules, "endToEndDelay", 99.0) is not None else None

        tcp_received_bytes = sum_scalar_suffix(scalars, f"RegionalBackbone.hostA.app[{TCP_CLIENT_APP_INDEX}]", "packetReceived")
        tcp_packet_bytes = vector_values(
            vectors,
            lambda module: module == f"RegionalBackbone.hostA.app[{TCP_CLIENT_APP_INDEX}]",
            lambda name: name == "packetReceived" or name.startswith("packetReceived:"),
        )
        tcp_endpoint_delay_ms = [
            value * 1000.0
            for value in vector_values(
                vectors,
                lambda module: module == f"RegionalBackbone.hostA.app[{TCP_CLIENT_APP_INDEX}]",
                lambda name: name == "endToEndDelay" or name.startswith("endToEndDelay:"),
            )
        ]
        tcp_goodput_kbps = None
        if tcp_packet_bytes:
            tcp_goodput_kbps = ((sum(tcp_packet_bytes) * 8.0) / 150.0) / 1000.0
        elif tcp_received_bytes is not None:
            tcp_goodput_kbps = ((tcp_received_bytes * 8.0) / 150.0) / 1000.0

        tcp_rtt_values_ms = [
            value * 1000.0
            for value in vector_values(
                vectors,
                lambda module: ".tcp" in module.lower(),
                lambda name: "rtt" in name.lower() or "srtt" in name.lower(),
            )
        ]
        tcp_cwnd_values = vector_values(
            vectors,
            lambda module: ".tcp" in module.lower(),
            lambda name: "cwnd" in name.lower(),
        )
        tcp_retrans_values = vector_values(
            vectors,
            lambda module: ".tcp" in module.lower(),
            lambda name: "retrans" in name.lower() or "numrto" in name.lower(),
        )
        tcp_endpoint_module = f"RegionalBackbone.hostA.app[{TCP_CLIENT_APP_INDEX}]"
        scalar_tcp_endpoint_delay_ms = (scalars.get((tcp_endpoint_module, "endToEndDelay:mean")) or 0.0) * 1000.0 if (tcp_endpoint_module, "endToEndDelay:mean") in scalars else None
        scalar_tcp_rtt_values_ms = [
            value * 1000.0
            for value in scalar_values(
                scalars,
                lambda module: module.startswith("RegionalBackbone.hostA.tcp."),
                lambda name: name in {"rtt:mean", "srtt:mean"},
            )
        ]
        scalar_tcp_cwnd_values = scalar_values(
            scalars,
            lambda module: module.startswith("RegionalBackbone.hostA.tcp."),
            lambda name: name == "cwnd:mean",
        )
        scalar_tcp_retrans_values = scalar_values(
            scalars,
            lambda module: module.startswith("RegionalBackbone.hostA.tcp."),
            lambda name: "retransmission" in name or "numRTOs" in name,
        )

        primary_queueing_ms = [
            value * 1000.0
            for value in vector_values(
                vectors,
                lambda module: module in PRIMARY_QUEUE_MODULES,
                lambda name: name == "queueingTime" or name.startswith("queueingTime:"),
            )
        ]
        backup_queueing_ms = [
            value * 1000.0
            for value in vector_values(
                vectors,
                lambda module: module in BACKUP_QUEUE_MODULES,
                lambda name: name == "queueingTime" or name.startswith("queueingTime:"),
            )
        ]
        primary_rate_values = vector_values(
            vectors,
            lambda module: module in PRIMARY_QUEUE_MODULES,
            lambda name: "outgoingDataRate" in name,
        )
        backup_rate_values = vector_values(
            vectors,
            lambda module: module in BACKUP_QUEUE_MODULES,
            lambda name: "outgoingDataRate" in name,
        )
        queue_drop_values = vector_values(
            vectors,
            lambda module: module in PRIMARY_QUEUE_MODULES | BACKUP_QUEUE_MODULES,
            lambda name: "droppedPacketLengthsQueueOverflow" in name,
        )
        queue_drop_bytes = sum(queue_drop_values) if queue_drop_values else None
        queue_drop_events = len(queue_drop_values) if queue_drop_values else None
        scalar_drop_events = sum_or_none(scalar_values(
            scalars,
            lambda module: module in PRIMARY_QUEUE_MODULES | BACKUP_QUEUE_MODULES,
            lambda name: name == "droppedPacketsQueueOverflow:count",
        ))
        scalar_drop_bytes = sum_or_none(scalar_values(
            scalars,
            lambda module: module in PRIMARY_QUEUE_MODULES | BACKUP_QUEUE_MODULES,
            lambda name: name == "droppedPacketLengthsQueueOverflow:sum",
        ))
        primary_modules = sorted(PRIMARY_QUEUE_MODULES)
        backup_modules = sorted(BACKUP_QUEUE_MODULES)
        scalar_primary_queueing_p95 = histogram_percentile(histograms, primary_modules, "queueingTime", 95.0)
        scalar_backup_queueing_p95 = histogram_percentile(histograms, backup_modules, "queueingTime", 95.0)

        quality_notes = [
            "udp_loss=exact_app_scalar_sent_received_all_configured_udp_apps" if udp_flow_count else "udp_loss=unavailable_no_udp_scalars",
            "udp_delay_percentiles=histogram_approx_received_packets_only" if histogram_udp_p95_ms is not None else "udp_delay_percentiles=unavailable",
            "tcp_goodput=endpoint_received_bytes_proxy",
            "tcp_rtt=available" if (tcp_rtt_values_ms or scalar_tcp_rtt_values_ms) else "tcp_rtt=not_recorded_or_not_exported_by_current_modules",
            "tcp_cwnd=available" if (tcp_cwnd_values or scalar_tcp_cwnd_values) else "tcp_cwnd=not_recorded_or_not_exported_by_current_modules",
            "tcp_retransmissions=available" if (tcp_retrans_values or scalar_tcp_retrans_values) else "tcp_retransmissions=not_recorded_or_not_exported_by_current_modules",
            "queue_metrics=scalar_drop_counts_and_histogram_queueing_if_present" if (scalar_drop_events is not None or scalar_primary_queueing_p95 is not None or scalar_backup_queueing_p95 is not None) else "queue_metrics=unavailable",
        ]

        by_run_rows.append({
            "scenario": scenario,
            "degradation_profile": profile,
            "mechanism_family": mechanism,
            "run": run,
            "config_name": config_name,
            "udp_flow_count": udp_flow_count,
            "udp_packets_sent_total": numeric_or_blank(udp_sent_total if udp_flow_count else None),
            "udp_packets_received_total": numeric_or_blank(udp_received_total if udp_flow_count else None),
            "udp_packet_loss_count": numeric_or_blank(udp_loss_count),
            "udp_packet_loss_percent": numeric_or_blank(udp_loss_percent),
            "udp_delay_mean_ms": numeric_or_blank(mean_or_none(udp_delay_values_ms) or (scalar_udp_delay_mean_ms * 1000.0 if scalar_udp_delay_mean_ms is not None else None)),
            "udp_delay_p50_ms": numeric_or_blank(percentile_or_none(udp_delay_values_ms, 50.0) or histogram_udp_p50_ms),
            "udp_delay_p95_ms": numeric_or_blank(percentile_or_none(udp_delay_values_ms, 95.0) or histogram_udp_p95_ms),
            "udp_delay_p99_ms": numeric_or_blank(percentile_or_none(udp_delay_values_ms, 99.0) or histogram_udp_p99_ms),
            "udp_ipdv_mean_ms": numeric_or_blank(mean_or_none(udp_ipdv_values_ms)),
            "udp_ipdv_p95_ms": numeric_or_blank(percentile_or_none(udp_ipdv_values_ms, 95.0)),
            "udp_throughput_mean_kbps": numeric_or_blank(mean_or_none(udp_throughput_values_kbps) or scalar_udp_throughput_kbps),
            "tcp_received_bytes_total": numeric_or_blank(tcp_received_bytes),
            "tcp_goodput_mean_kbps": numeric_or_blank(tcp_goodput_kbps),
            "tcp_endpoint_delay_mean_ms": numeric_or_blank(mean_or_none(tcp_endpoint_delay_ms) or scalar_tcp_endpoint_delay_ms),
            "tcp_rtt_mean_ms": numeric_or_blank(mean_or_none(tcp_rtt_values_ms) or mean_or_none(scalar_tcp_rtt_values_ms)),
            "tcp_cwnd_mean": numeric_or_blank(mean_or_none(tcp_cwnd_values) or mean_or_none(scalar_tcp_cwnd_values)),
            "tcp_retransmission_count": numeric_or_blank(sum_or_none(tcp_retrans_values) or sum_or_none(scalar_tcp_retrans_values)),
            "queue_drop_event_count": numeric_or_blank(queue_drop_events if queue_drop_events is not None else scalar_drop_events),
            "queue_drop_bytes_sum": numeric_or_blank(queue_drop_bytes if queue_drop_bytes is not None else scalar_drop_bytes),
            "primary_queueing_time_p95_ms": numeric_or_blank(percentile_or_none(primary_queueing_ms, 95.0) or (scalar_primary_queueing_p95 * 1000.0 if scalar_primary_queueing_p95 is not None else None)),
            "backup_queueing_time_p95_ms": numeric_or_blank(percentile_or_none(backup_queueing_ms, 95.0) or (scalar_backup_queueing_p95 * 1000.0 if scalar_backup_queueing_p95 is not None else None)),
            "primary_link_utilization_mean_percent": numeric_or_blank(
                (mean_or_none(primary_rate_values) or 0.0) / 100_000_000.0 * 100.0 if primary_rate_values else None
            ),
            "backup_link_utilization_mean_percent": numeric_or_blank(
                (mean_or_none(backup_rate_values) or 0.0) / 100_000_000.0 * 100.0 if backup_rate_values else None
            ),
            "metric_quality_notes": "; ".join(quality_notes),
        })

    by_run_rows.sort(
        key=lambda item: (
            str(item.get("degradation_profile", "")),
            MECHANISM_ORDER.get(str(item.get("mechanism_family", "")), 999),
            int(item.get("run") or 0),
        )
    )

    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in by_run_rows:
        grouped[(str(row.get("degradation_profile", "")), str(row.get("mechanism_family", "")))].append(row)

    summary_rows: list[dict[str, object]] = []
    numeric_fields = [field for field in INET_METRICS_SUMMARY_FIELDS if field not in {"scenario", "degradation_profile", "mechanism_family", "runs", "metric_quality_notes"}]
    for (profile, mechanism), rows in sorted(grouped.items(), key=lambda item: (item[0][0], MECHANISM_ORDER.get(item[0][1], 999))):
        summary: dict[str, object] = {
            "scenario": scenario,
            "degradation_profile": profile,
            "mechanism_family": mechanism,
            "runs": len(rows),
            "metric_quality_notes": distinct_text([row.get("metric_quality_notes", "") for row in rows]),
        }
        for field in numeric_fields:
            mean_value, _ = mean_std_cells(rows, field)
            summary[field] = mean_value
        summary_rows.append(summary)

    return by_run_rows, summary_rows


def metric_classification_lines(scenario: str) -> list[str]:
    lines = [
        "- post_failure_unobserved, activation_to_failure_unobserved: receiver-observed continuity diagnostics.",
        "- post_failure_reordered, activation_to_failure_reordered, out_of_order_events: receiver-observed reordering diagnostics.",
        "- delivery_ratio_proxy and unobserved/reordered ratio fields: proxy metrics derived from receiver windows and continuity counters.",
        "- UDP delay/throughput/goodput fields: direct vector-derived diagnostics already summarized in the dataset at one-second windows.",
        "- delay_variation_proxy fields: proxy from adjacent one-second mean-delay deltas; not a full RFC 5481 IPDV calculation.",
        "- queue length, queue bit length, and queueing time: direct vector-derived diagnostics from the configured bottleneck queue.",
        "- applied delay and packet error rate: simulator impairment context from LinkDegradationController vectors.",
        "- BFD-like loss/miss/lead-time fields: project-local BFD-like detector diagnostics from controller scalars.",
        "- queue drop count: unavailable from current compact outputs; future instrumentation required.",
    ]
    if scenario in TRANSPORT_SCENARIOS:
        lines.append(
            "- TCP received bytes/goodput/progress: endpoint-observed proxy from INET TCP application packet-byte vectors; TCP stack RTT/retransmission/cwnd metrics are reported only when explicitly exported."
        )
    else:
        lines.append("- TCP goodput/retransmission/RTT/cwnd: unavailable because this cohort is UDP-only.")
    return lines


def render_report(
    scenario: str,
    dataset_path: Path,
    outcome_path: Path,
    by_run_path: Path,
    summary_path: Path,
    summary_rows: list[dict[str, object]],
    by_run_rows: list[dict[str, object]],
    elapsed: str,
    transport_by_run_path: Path | None = None,
    transport_summary_path: Path | None = None,
    transport_rows: list[dict[str, object]] | None = None,
) -> str:
    lines: list[str] = [
        "AI-MRCE Network-Impact Report",
        "==============================",
        "",
        f"Scenario: {scenario}",
        "Scope: analysis-only UDP/QoS diagnostics from existing generated artifacts.",
        f"Dataset input: {dataset_path}",
        f"Outcome input: {outcome_path}",
        f"By-run output: {by_run_path}",
        f"Summary output: {summary_path}",
        f"Generated rows: by_run={len(by_run_rows)}, mechanisms={len(summary_rows)}",
        f"Elapsed: {elapsed}",
        "",
        "Metric Classification",
        "---------------------",
        *metric_classification_lines(scenario),
        "",
        "Mechanism Summary",
        "-----------------",
    ]

    for row in summary_rows:
        profile_text = f" profile={row['degradation_profile']}," if str(row.get("degradation_profile", "")).strip() else ""
        lines.append(
            f"-{profile_text} {row['mechanism_label']} ({row['mechanism_family']}): "
            f"runs={row['runs']}, trigger_sources={row['trigger_sources'] or 'none'}, "
            f"activation_time_mean={row.get('activation_time_s_mean', '')}, "
            f"lead_time_mean={row.get('lead_time_s_mean', '')}, "
            f"post_failure_unobserved_mean={row.get('post_failure_unobserved_mean', '')}, "
            f"activation_to_failure_unobserved_mean={row.get('activation_to_failure_unobserved_mean', '')}, "
            f"activation_to_failure_reordered_mean={row.get('activation_to_failure_reordered_mean', '')}, "
            f"post_failure_delivery_ratio_proxy_mean={row.get('post_hard_failure_delivery_ratio_proxy_mean', '')}, "
            f"fallback_count={row['fallback_count']}, "
            f"repairRouteCount_values={row['repairRouteCount_values'] or 'none'}"
        )
        lines.append(f"  Interpretation: {row['key_interpretation_note']}")

    if scenario in TRANSPORT_SCENARIOS:
        lines.extend(
            [
                "",
                "Mixed UDP/TCP Transport Outputs",
                "-------------------------------",
                f"- Transport by-run output: {transport_by_run_path}",
                f"- Transport summary output: {transport_summary_path}",
                f"- Transport rows: {len(transport_rows or [])}",
                "- TCP metrics are endpoint-observed received-byte/goodput/progress proxies from INET application vectors.",
                "- TCP retransmissions, RTT, congestion window, and exact finite-flow completion time are reported only when explicitly available in exported INET metrics.",
            ]
        )

    lines.extend(
        [
            "",
            "Conservative Interpretation",
            "---------------------------",
            "- These are receiver-observed network-impact diagnostics, not new simulator behavior.",
            "- Delivery/loss-like ratios are proxies unless exact sent/received accounting is available for the phase.",
            "- Reordering is reported separately and must not be interpreted as direct packet loss.",
            "- The cohort is a deterministic progressive degraded-link/brownout stress profile, not universal failure evidence.",
            "- UDP metrics refer to the current monitored UDP/probe traffic and staged UDP load.",
            (
                "- TCP metrics in this mixed cohort are endpoint-observed progress proxies only; protocol-internal retransmission/RTT/cwnd behavior remains future instrumentation."
                if scenario in TRANSPORT_SCENARIOS
                else "- TCP is not evaluated in this cohort; TCP conclusions require the separate mixed UDP/TCP transport-impact cohort."
            ),
            "- Queue/drop metrics are limited by available INET signals; this report does not claim queue drops.",
            "- Backup-path cost fields report separate components: early backup usage time, avoided post-failure unobserved gaps, transition reordering, UDP delay, queueing, and throughput diagnostics.",
            "- Cost-aware backup and transport-impact cohorts model a mildly penalized southern backup corridor; legacy cohorts do not model a persistent backup data-plane penalty.",
            "- The report is analysis-only and does not modify AI-MRCE, BFD-like, FRR-like routes, runtime models, or outcomes.",
            "",
            "Unavailable / Future Instrumentation",
            "------------------------------------",
            "- Exact RFC 5481 IPDV requires packet-pair delay variation from raw samples or dedicated instrumentation.",
            "- Queue drop counts require explicit queue-drop signal/vector export.",
            (
                "- TCP retransmissions, RTT, congestion window, and exact flow-completion time require additional INET TCP signal/statistic export."
                if scenario in TRANSPORT_SCENARIOS
                else "- TCP goodput, retransmissions, RTT, congestion window, and flow-completion time require a separate TCP cohort."
            ),
            "- Control-plane CPU/runtime overhead is not measured by the current OMNeT++ outputs.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_outputs(scenario: str, output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return (
        output_dir / f"{scenario}_network_impact_by_run.csv",
        output_dir / f"{scenario}_network_impact_summary.csv",
        output_dir / f"{scenario}_network_impact_report.txt",
    )


def build_backup_cost_outputs(scenario: str, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return (
        output_dir / f"{scenario}_backup_path_cost_by_run.csv",
        output_dir / f"{scenario}_backup_path_cost_summary.csv",
    )


def build_transport_outputs(scenario: str, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return (
        output_dir / f"{scenario}_transport_by_run.csv",
        output_dir / f"{scenario}_transport_summary.csv",
    )


def build_inet_metric_outputs(scenario: str, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return (
        output_dir / f"{scenario}_inet_metrics_by_run.csv",
        output_dir / f"{scenario}_inet_metrics_summary.csv",
    )


def main() -> int:
    total_start = time.perf_counter()
    args = parse_args()
    scenario = args.scenario
    output_dir = resolve_project_path(args.output_dir)

    dataset_path = DATASET_DIR / f"{scenario}_dataset.csv"
    outcome_path = OUTCOMES_DIR / f"{scenario}_outcome_summary.csv"
    by_run_path, summary_path, report_path = build_outputs(scenario, output_dir)
    backup_cost_by_run_path, backup_cost_summary_path = build_backup_cost_outputs(scenario, output_dir)
    transport_by_run_path, transport_summary_path = build_transport_outputs(scenario, output_dir)
    inet_metrics_by_run_path, inet_metrics_summary_path = build_inet_metric_outputs(scenario, output_dir)

    print(f"[network_impact] Scenario: {scenario}")
    print(f"[network_impact] Dataset input: {dataset_path}")
    print(f"[network_impact] Outcome input: {outcome_path}")

    dataset_rows = load_csv(dataset_path)
    outcome_rows = load_csv(outcome_path)
    print(f"[network_impact] Loaded dataset rows: {len(dataset_rows)}")
    print(f"[network_impact] Loaded outcome rows: {len(outcome_rows)}")

    grouped_dataset = group_dataset_rows(dataset_rows)
    print(f"[network_impact] Dataset mechanism/run groups: {len(grouped_dataset)}")

    by_run_rows = build_by_run_rows(scenario, outcome_rows, grouped_dataset)
    summary_rows = build_summary_rows(scenario, by_run_rows)
    backup_cost_rows, backup_cost_summary_rows = build_backup_cost_rows(scenario, by_run_rows)
    transport_rows, transport_summary_rows = build_transport_rows(scenario, outcome_rows, grouped_dataset, by_run_rows)
    inet_metrics_by_run_rows, inet_metrics_summary_rows = build_inet_metrics_rows(scenario, outcome_rows)

    atomic_write_csv(by_run_path, by_run_rows, BY_RUN_FIELDNAMES)
    atomic_write_csv(summary_path, summary_rows, SUMMARY_FIELDNAMES)
    atomic_write_csv(backup_cost_by_run_path, backup_cost_rows, BACKUP_COST_BY_RUN_FIELDS)
    atomic_write_csv(backup_cost_summary_path, backup_cost_summary_rows, BACKUP_COST_SUMMARY_FIELDS)
    if scenario in TRANSPORT_SCENARIOS:
        atomic_write_csv(transport_by_run_path, transport_rows, TRANSPORT_BY_RUN_FIELDS)
        atomic_write_csv(transport_summary_path, transport_summary_rows, TRANSPORT_SUMMARY_FIELDS)
    if scenario == COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
        atomic_write_csv(inet_metrics_by_run_path, inet_metrics_by_run_rows, INET_METRICS_BY_RUN_FIELDS)
        atomic_write_csv(inet_metrics_summary_path, inet_metrics_summary_rows, INET_METRICS_SUMMARY_FIELDS)
    report_text = render_report(
        scenario=scenario,
        dataset_path=dataset_path,
        outcome_path=outcome_path,
        by_run_path=by_run_path,
        summary_path=summary_path,
        summary_rows=summary_rows,
        by_run_rows=by_run_rows,
        elapsed=elapsed_text(total_start),
        transport_by_run_path=transport_by_run_path if scenario in TRANSPORT_SCENARIOS else None,
        transport_summary_path=transport_summary_path if scenario in TRANSPORT_SCENARIOS else None,
        transport_rows=transport_rows,
    )
    atomic_write_text(report_path, report_text)

    print(f"[network_impact] Wrote by-run CSV: {by_run_path}")
    print(f"[network_impact] Wrote summary CSV: {summary_path}")
    print(f"[network_impact] Wrote backup-path cost by-run CSV: {backup_cost_by_run_path}")
    print(f"[network_impact] Wrote backup-path cost summary CSV: {backup_cost_summary_path}")
    if scenario in TRANSPORT_SCENARIOS:
        print(f"[network_impact] Wrote transport by-run CSV: {transport_by_run_path}")
        print(f"[network_impact] Wrote transport summary CSV: {transport_summary_path}")
    if scenario == COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
        print(f"[network_impact] Wrote INET metrics by-run CSV: {inet_metrics_by_run_path}")
        print(f"[network_impact] Wrote INET metrics summary CSV: {inet_metrics_summary_path}")
    print(f"[network_impact] Wrote report: {report_path}")
    if scenario in TRANSPORT_SCENARIOS:
        print("[network_impact] TCP endpoint received-byte/goodput/progress proxy metrics were generated.")
        if scenario == COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
            print("[network_impact] Targeted INET metric extraction was attempted for UDP delay percentiles, IPDV, queue/link metrics, and TCP stack signals.")
        print("[network_impact] TCP retransmissions, RTT, cwnd, and exact finite-flow completion are claimed only when explicitly available.")
    else:
        print("[network_impact] TCP metrics are unavailable because this cohort is UDP-only.")
    print(f"[network_impact] Total elapsed: {elapsed_text(total_start)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
