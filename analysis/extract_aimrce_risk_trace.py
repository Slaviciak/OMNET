"""Extract AI-MRCE runtime decision traces from OMNeT++ vector files.

This is a diagnostic helper for the regional degraded-link model-family cohort.
It does not change simulator behavior or outcome definitions. The exported CSV
is intended to answer a narrow methodological question: did different AI-MRCE
runtime policies produce identical scores, or did distinct scores cross the
same threshold in the same controller decision cycle?
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
DEBUG_OUTPUT_DIR = OUTPUT_ROOT / "debug"
OUTCOME_OUTPUT_DIR = OUTPUT_ROOT / "outcomes"

SCENARIO_RESULTS = {
    "regionalbackbone_failure_detection_degraded_link_model_family": (
        PROJECT_ROOT / "results" / "regionalbackbone" / "failure_detection_degraded_link_model_family"
    ),
    "regionalbackbone_failure_detection_degradation_sensitivity": (
        PROJECT_ROOT / "results" / "regionalbackbone" / "failure_detection_degradation_sensitivity"
    ),
    "regionalbackbone_failure_detection_cost_aware_backup": (
        PROJECT_ROOT / "results" / "regionalbackbone" / "failure_detection_cost_aware_backup"
    ),
    "regionalbackbone_failure_detection_cost_aware_transport_impact": (
        PROJECT_ROOT / "results" / "regionalbackbone" / "failure_detection_cost_aware_transport_impact"
    ),
}

SCENARIO_OUTCOME_SUMMARIES = {
    "regionalbackbone_failure_detection_degraded_link_model_family": (
        OUTCOME_OUTPUT_DIR / "regionalbackbone_failure_detection_degraded_link_model_family_outcome_summary.csv"
    ),
    "regionalbackbone_failure_detection_degradation_sensitivity": (
        OUTCOME_OUTPUT_DIR / "regionalbackbone_failure_detection_degradation_sensitivity_outcome_summary.csv"
    ),
    "regionalbackbone_failure_detection_cost_aware_backup": (
        OUTCOME_OUTPUT_DIR / "regionalbackbone_failure_detection_cost_aware_backup_outcome_summary.csv"
    ),
    "regionalbackbone_failure_detection_cost_aware_transport_impact": (
        OUTCOME_OUTPUT_DIR / "regionalbackbone_failure_detection_cost_aware_transport_impact_outcome_summary.csv"
    ),
}

CONFIG_RUNTIME_MODEL_TYPES = {
    "RegionalBackboneFailureDegradedLinkAiMrceRuleBased": "rule_based",
    "RegionalBackboneFailureDegradedLinkAiMrceRuleBasedCohort": "rule_based",
    "RegionalBackboneFailureDegradedLinkAiMrceLogReg": "logistic_regression",
    "RegionalBackboneFailureDegradedLinkAiMrceLogRegCohort": "logistic_regression",
    "RegionalBackboneFailureDegradedLinkAiMrceLinearSvm": "linear_svm",
    "RegionalBackboneFailureDegradedLinkAiMrceLinearSvmCohort": "linear_svm",
    "RegionalBackboneFailureDegradedLinkAiMrceShallowTree": "shallow_tree",
    "RegionalBackboneFailureDegradedLinkAiMrceShallowTreeCohort": "shallow_tree",
    "RegionalBackboneFailureDegradedLinkHybrid": "rule_based",
    "RegionalBackboneFailureDegradedLinkHybridCohort": "rule_based",
}

for _profile in ("MildSlow", "Moderate", "SevereFast"):
    CONFIG_RUNTIME_MODEL_TYPES.update(
        {
            f"RegionalBackboneSensitivity{_profile}AiMrceRuleBased": "rule_based",
            f"RegionalBackboneSensitivity{_profile}AiMrceRuleBasedCohort": "rule_based",
            f"RegionalBackboneSensitivity{_profile}AiMrceLogReg": "logistic_regression",
            f"RegionalBackboneSensitivity{_profile}AiMrceLogRegCohort": "logistic_regression",
            f"RegionalBackboneSensitivity{_profile}AiMrceLinearSvm": "linear_svm",
            f"RegionalBackboneSensitivity{_profile}AiMrceLinearSvmCohort": "linear_svm",
            f"RegionalBackboneSensitivity{_profile}AiMrceShallowTree": "shallow_tree",
            f"RegionalBackboneSensitivity{_profile}AiMrceShallowTreeCohort": "shallow_tree",
            f"RegionalBackboneSensitivity{_profile}Hybrid": "rule_based",
            f"RegionalBackboneSensitivity{_profile}HybridCohort": "rule_based",
        }
    )
del _profile

for _profile in ("Mild", "Moderate", "FastWarning"):
    CONFIG_RUNTIME_MODEL_TYPES.update(
        {
            f"RegionalBackboneCostAware{_profile}AiMrceRuleBased": "rule_based",
            f"RegionalBackboneCostAware{_profile}AiMrceRuleBasedCohort": "rule_based",
            f"RegionalBackboneCostAware{_profile}AiMrceLogReg": "logistic_regression",
            f"RegionalBackboneCostAware{_profile}AiMrceLogRegCohort": "logistic_regression",
            f"RegionalBackboneCostAware{_profile}AiMrceLinearSvm": "linear_svm",
            f"RegionalBackboneCostAware{_profile}AiMrceLinearSvmCohort": "linear_svm",
            f"RegionalBackboneCostAware{_profile}AiMrceShallowTree": "shallow_tree",
            f"RegionalBackboneCostAware{_profile}AiMrceShallowTreeCohort": "shallow_tree",
            f"RegionalBackboneCostAware{_profile}Hybrid": "rule_based",
            f"RegionalBackboneCostAware{_profile}HybridCohort": "rule_based",
        }
    )
del _profile

for _profile in ("TransportMild", "TransportModerate", "TransportFastWarning"):
    CONFIG_RUNTIME_MODEL_TYPES.update(
        {
            f"RegionalBackboneCostAware{_profile}AiMrceRuleBased": "rule_based",
            f"RegionalBackboneCostAware{_profile}AiMrceRuleBasedCohort": "rule_based",
            f"RegionalBackboneCostAware{_profile}AiMrceLogReg": "logistic_regression",
            f"RegionalBackboneCostAware{_profile}AiMrceLogRegCohort": "logistic_regression",
            f"RegionalBackboneCostAware{_profile}AiMrceLinearSvm": "linear_svm",
            f"RegionalBackboneCostAware{_profile}AiMrceLinearSvmCohort": "linear_svm",
            f"RegionalBackboneCostAware{_profile}AiMrceShallowTree": "shallow_tree",
            f"RegionalBackboneCostAware{_profile}AiMrceShallowTreeCohort": "shallow_tree",
            f"RegionalBackboneCostAware{_profile}Hybrid": "rule_based",
            f"RegionalBackboneCostAware{_profile}HybridCohort": "rule_based",
        }
    )
del _profile

VECTOR_NAME_MAP = {
    "riskScore": "risk_score",
    "decisionPositive": "positive_decision",
    "positiveDecisionStreak": "positive_decision_streak",
    "observedQueueLengthPk": "queue_length",
    "observedQueueBitLengthB": "queue_bit_length",
    "observedProbeDelayMeanS": "probe_delay",
    "observedProbeThroughputBps": "throughput_or_packet_proxy",
    "observedProbePacketCount": "probe_packet_count",
    "protectionActive": "protection_activated",
    "repairRoutesInstalled": "repair_routes_installed",
    "protectionTriggerSourceCode": "trigger_source_code",
    "bfdLikeMissedProbeCount": "bfd_like_missed_probe_count",
    "bfdLikeDetectionActive": "bfd_like_detection_active",
    "bfdLikeModeledProbeLossProbability": "bfd_like_modeled_loss",
    "bfdLikeProbeMissed": "bfd_like_probe_missed",
}

SCALAR_NAME_MAP = {
    "protectionActivationTime": "protection_activation_time_s",
    "protectionTriggerSourceCode": "protection_trigger_source_code_final",
    "repairRoutesInstalled": "repair_routes_installed_final",
    "repairRouteInstallTime": "repair_route_install_time_s",
    "hardFailureTime": "hard_failure_time_s",
    "activationDecisionThreshold": "activation_threshold",
    "activationRiskScore": "activation_risk_score",
    "runtimeModelThreshold": "runtime_model_threshold",
    "runtimeModelLoaded": "runtime_model_loaded",
    "runtimeModelFallbackUsed": "runtime_model_fallback_used",
    "runtimeModelFeatureCount": "runtime_model_feature_count",
    "aimrceActivationConsecutiveCyclesConfigured": "activation_cycles_configured",
    "aimrceEvaluationInterval": "evaluation_interval_s",
    "bfdLikeDetectionTime": "bfd_like_detection_time_s",
    "bfdLikeModeledProbeLossProbabilityAtDetection": "bfd_like_modeled_loss_at_detection",
}


def atomic_temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.tmp")


def atomic_write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = atomic_temp_path(path)
    try:
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
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
    source_text = newest_inputs[0] if newest_inputs else "trace source"
    print(
        "Warning: existing trace artifact appears stale before regeneration: "
        f"{output_path} is older than {source_text}. Regenerate with the current model-risk-trace command."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract AI-MRCE risk-score trajectories from decision-cycle vectors."
    )
    parser.add_argument(
        "--scenario",
        default="regionalbackbone_failure_detection_degraded_link_model_family",
        choices=sorted(SCENARIO_RESULTS),
        help="Scenario preset to inspect.",
    )
    parser.add_argument("--runs", nargs="+", type=int, default=[0], help="Run numbers to include.")
    parser.add_argument("--start", type=float, default=78.0, help="Trace window start time in seconds.")
    parser.add_argument("--end", type=float, default=86.0, help="Trace window end time in seconds.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV path. Defaults to analysis/output/debug/aimrce_model_family_risk_trace_<scenario>.csv.",
    )
    parser.add_argument(
        "--events-output",
        type=Path,
        help="Optional compact event-summary CSV path. Defaults to analysis/output/debug/aimrce_model_action_events_<scenario>.csv.",
    )
    return parser.parse_args()


def trigger_source_from_code(raw_code: object) -> str:
    try:
        code = int(round(float(raw_code)))
    except (TypeError, ValueError):
        return ""
    return {
        0: "none",
        1: "aimrce",
        2: "bfd_like",
        3: "hybrid_aimrce_first",
        4: "hybrid_bfd_like_first",
    }.get(code, f"unknown_code_{code}")


def policy_name_from_runtime_model(runtime_model_type: str) -> str:
    return {
        "rule_based": "aimrce_rule_based",
        "logistic_regression": "aimrce_logistic_regression",
        "linear_svm": "aimrce_linear_svm",
        "shallow_tree": "aimrce_shallow_tree",
    }.get(runtime_model_type, runtime_model_type)


def parse_scalar_file(path: Path) -> dict[str, str]:
    scalars = {output_name: "" for output_name in SCALAR_NAME_MAP.values()}
    if not path.exists():
        return scalars

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line.startswith("scalar "):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            output_name = SCALAR_NAME_MAP.get(parts[2])
            if output_name and scalars.get(output_name, "") == "":
                scalars[output_name] = parts[3]
    return scalars


def metadata_from_vec(path: Path) -> tuple[str, int | None]:
    config_name = ""
    run_number: int | None = None
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith("attr configname "):
                config_name = line.split(" ", 2)[2]
            elif line.startswith("attr runnumber "):
                try:
                    run_number = int(line.split(" ", 2)[2])
                except ValueError:
                    run_number = None
            if config_name and run_number is not None:
                break

    if run_number is None:
        match = re.search(r"-(\d+)$", path.stem)
        run_number = int(match.group(1)) if match else 0
    return config_name, run_number


def extract_trace_rows(path: Path, start_s: float, end_s: float) -> list[dict[str, object]]:
    config_name, run_number = metadata_from_vec(path)
    runtime_model_type = CONFIG_RUNTIME_MODEL_TYPES.get(config_name, "")
    if not runtime_model_type:
        return []

    scalars = parse_scalar_file(path.with_suffix(".sca"))
    threshold = scalars.get("runtime_model_threshold") or scalars.get("activation_threshold", "")
    vector_names_by_id: dict[int, str] = {}
    samples_by_time: dict[float, dict[str, object]] = {}

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("vector "):
                parts = line.split()
                if len(parts) < 4:
                    continue
                module_name = parts[2]
                vector_name = parts[3]
                if vector_name.endswith(":vector"):
                    vector_name = vector_name[:-7]
                output_name = VECTOR_NAME_MAP.get(vector_name)
                if module_name.endswith(".aiMrceController") and output_name:
                    vector_names_by_id[int(parts[1])] = output_name
                continue
            if not line[0].isdigit():
                continue

            parts = line.split()
            if len(parts) < 4:
                continue
            vector_name = vector_names_by_id.get(int(parts[0]))
            if vector_name is None:
                continue
            timestamp = float(parts[2])
            if timestamp < start_s or timestamp > end_s:
                continue
            value = float(parts[-1])
            row = samples_by_time.setdefault(
                timestamp,
                {
                    "config_name": config_name,
                    "run_number": run_number,
                    "time_s": timestamp,
                    "runtime_model_type": runtime_model_type,
                    "aimrce_policy_name": policy_name_from_runtime_model(runtime_model_type),
                },
            )
            row[vector_name] = value

    rows: list[dict[str, object]] = []
    for timestamp in sorted(samples_by_time):
        row = samples_by_time[timestamp]
        for field_name in VECTOR_NAME_MAP.values():
            row.setdefault(field_name, "")
        row["threshold"] = threshold
        trigger_code = row.get("trigger_source_code", "") or scalars.get("protection_trigger_source_code_final", "")
        row["trigger_source"] = trigger_source_from_code(trigger_code)
        for scalar_name, scalar_value in scalars.items():
            row[scalar_name] = scalar_value
        rows.append(row)
    return rows


def load_outcome_rows(scenario: str) -> dict[tuple[str, int], dict[str, str]]:
    path = SCENARIO_OUTCOME_SUMMARIES.get(scenario)
    if path is None or not path.exists():
        return {}

    rows_by_key: dict[tuple[str, int], dict[str, str]] = {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            config_name = row.get("config_name", "")
            try:
                run_number = int(row.get("run_number", "0"))
            except ValueError:
                continue
            rows_by_key[(config_name, run_number)] = row
            # OMNeT++ vector files for repeated batches carry the cohort wrapper
            # config name, while outcome summaries intentionally normalize back
            # to the underlying scenario config. Add the wrapper alias so the
            # graph-ready event summary can join trigger timing to outcome
            # metrics without changing either source artifact.
            if config_name and not config_name.endswith("Cohort"):
                rows_by_key[(f"{config_name}Cohort", run_number)] = row
    return rows_by_key


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "config_name",
        "run_number",
        "time_s",
        "runtime_model_type",
        "aimrce_policy_name",
        "risk_score",
        "threshold",
        "positive_decision",
        "positive_decision_streak",
        "queue_length",
        "queue_bit_length",
        "probe_delay",
        "throughput_or_packet_proxy",
        "probe_packet_count",
        "protection_activated",
        "protection_activation_time_s",
        "repair_routes_installed",
        "repair_route_install_time_s",
        "hard_failure_time_s",
        "trigger_source",
        "trigger_source_code",
        "bfd_like_detection_time_s",
        "bfd_like_modeled_loss",
        "bfd_like_modeled_loss_at_detection",
        "bfd_like_missed_probe_count",
        "bfd_like_detection_active",
        "bfd_like_probe_missed",
        "activation_threshold",
        "activation_risk_score",
        "runtime_model_threshold",
        "runtime_model_loaded",
        "runtime_model_fallback_used",
        "runtime_model_feature_count",
        "activation_cycles_configured",
        "evaluation_interval_s",
    ]
    atomic_write_csv(path, rows, fieldnames)


def write_event_csv(path: Path, rows: list[dict[str, object]], outcome_rows: dict[tuple[str, int], dict[str, str]]) -> None:
    fieldnames = [
        "config_name",
        "run_number",
        "mechanism",
        "runtime_model_type",
        "first_positive_decision_time_s",
        "activation_time_s",
        "repair_route_install_time_s",
        "bfd_detection_time_s",
        "hard_failure_time_s",
        "lead_time_before_failure_s",
        "post_failure_unobserved",
        "activation_to_failure_unobserved",
        "activation_to_failure_reordered",
    ]

    grouped: dict[tuple[str, int], list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((str(row["config_name"]), int(row["run_number"])), []).append(row)

    event_rows: list[dict[str, object]] = []
    for key, group_rows in sorted(grouped.items()):
        config_name, run_number = key
        first = group_rows[0]
        first_positive_times = [
            float(row["time_s"])
            for row in group_rows
            if str(row.get("positive_decision", "")) not in {"", "0", "0.0"}
        ]
        outcome = outcome_rows.get(key, {})
        activation_time = first.get("protection_activation_time_s", "")
        hard_failure_time = first.get("hard_failure_time_s", "")
        lead_time = ""
        try:
            activation_float = float(activation_time)
            hard_failure_float = float(hard_failure_time)
            if activation_float >= 0 and hard_failure_float >= 0:
                lead_time = hard_failure_float - activation_float
        except (TypeError, ValueError):
            lead_time = ""

        event_rows.append(
            {
                "config_name": config_name,
                "run_number": run_number,
                "mechanism": outcome.get("protection_mode", ""),
                "runtime_model_type": first.get("runtime_model_type", ""),
                "first_positive_decision_time_s": first_positive_times[0] if first_positive_times else "",
                "activation_time_s": activation_time,
                "repair_route_install_time_s": first.get("repair_route_install_time_s", ""),
                "bfd_detection_time_s": first.get("bfd_like_detection_time_s", ""),
                "hard_failure_time_s": hard_failure_time,
                "lead_time_before_failure_s": lead_time,
                "post_failure_unobserved": outcome.get("packet_sequence_gap_total_unobserved_after_hard_failure", ""),
                "activation_to_failure_unobserved": outcome.get(
                    "packet_sequence_gap_total_unobserved_between_activation_and_failure", ""
                ),
                "activation_to_failure_reordered": outcome.get(
                    "packet_sequence_gap_total_reordered_between_activation_and_failure", ""
                ),
            }
        )

    atomic_write_csv(path, event_rows, fieldnames)


def main() -> None:
    total_start = time.perf_counter()
    args = parse_args()
    if args.end < args.start:
        raise SystemExit("--end must be greater than or equal to --start.")

    results_dir = SCENARIO_RESULTS[args.scenario]
    if not results_dir.exists():
        raise SystemExit(f"Results directory not found: {results_dir}")

    print(f"[model-risk-trace] Scenario: {args.scenario}")
    print(f"[model-risk-trace] Results directory: {results_dir}")
    print(f"[model-risk-trace] Runs: {', '.join(map(str, args.runs))}")
    print(f"[model-risk-trace] Window: {args.start}s to {args.end}s")

    rows: list[dict[str, object]] = []
    selected_runs = set(args.runs)
    selected_vec_paths: list[Path] = []
    for vec_path in sorted(results_dir.glob("*.vec")):
        _, run_number = metadata_from_vec(vec_path)
        if run_number in selected_runs:
            selected_vec_paths.append(vec_path)
            file_start = time.perf_counter()
            print(f"[model-risk-trace] Extracting {vec_path}")
            rows.extend(extract_trace_rows(vec_path, args.start, args.end))
            print(f"[model-risk-trace] Finished {vec_path.name} in {elapsed_text(file_start)}")

    output_path = args.output or DEBUG_OUTPUT_DIR / f"aimrce_model_family_risk_trace_{args.scenario}.csv"
    events_output_path = args.events_output or DEBUG_OUTPUT_DIR / f"aimrce_model_action_events_{args.scenario}.csv"
    outcome_rows = load_outcome_rows(args.scenario)
    source_paths = [
        path
        for vec_path in selected_vec_paths
        for path in (vec_path, vec_path.with_suffix(".sca"), vec_path.with_suffix(".vci"))
    ]
    outcome_path = SCENARIO_OUTCOME_SUMMARIES.get(args.scenario)
    if outcome_path is not None:
        source_paths.append(outcome_path)
    regenerate_command = (
        f"py -3 analysis\\extract_aimrce_risk_trace.py --scenario {args.scenario} "
        f"--runs {' '.join(map(str, args.runs))} --start {args.start:g} --end {args.end:g}"
    )
    warn_if_existing_output_stale(output_path, source_paths, regenerate_command)
    warn_if_existing_output_stale(events_output_path, source_paths, regenerate_command)
    write_csv(output_path, rows)
    write_event_csv(events_output_path, rows, outcome_rows)
    print(f"Wrote {len(rows)} AI-MRCE risk-trace rows to {output_path}")
    print(f"Wrote AI-MRCE model-action event summary to {events_output_path}")
    print(f"[model-risk-trace] Total elapsed: {elapsed_text(total_start)}")


if __name__ == "__main__":
    main()
