#!/usr/bin/env python3
"""Package compact current-experiment artifacts for review.

This helper copies only small, publication-facing analysis artifacts into a
single generated folder. It intentionally excludes raw OMNeT++ results such as
.vec, .vci, .sca, .elog, and build outputs.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = PROJECT_ROOT / "analysis"
OUTPUT_DIR = ANALYSIS_DIR / "output"

DEFAULT_SCENARIO = "regionalbackbone_failure_detection_degraded_link_model_family"

RAW_RESULT_SUFFIXES = {".vec", ".vci", ".sca", ".elog", ".anf", ".pcap", ".pcapng"}

SCENARIO_DISPLAY = {
    "regionalbackbone_failure_detection_degraded_link_model_family": (
        "Predictive Link-Failure Recovery",
        "predictive_link_failure_recovery",
        "Scenario A / concept validation",
    ),
    "regionalbackbone_failure_detection_cost_aware_backup": (
        "Cost-Aware Degraded-Backup Operation",
        "cost_aware_degraded_backup_operation",
        "Scenario B / opportunity-cost and policy differentiation",
    ),
    "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented": (
        "Congestion/Queue-Buildup Early Mitigation",
        "congestion_queue_buildup_early_mitigation",
        "Scenario C / network-impact and QoS mitigation",
    ),
    "regionalbackbone_failure_detection_cost_aware_transport_impact_randomized_onset": (
        "Queue Buildup Randomized-Onset Robustness",
        "queue_buildup_randomized_onset_robustness",
        "Supplementary Scenario C-R / randomized QoS-brownout onset robustness",
    ),
}

EXPECTED_MECHANISMS = [
    "ospf_only",
    "bfd_like_frr",
    "aimrce_rule_based_frr",
    "aimrce_logistic_regression_frr",
    "aimrce_linear_svm_frr",
    "aimrce_shallow_tree_frr",
]

LEGACY_TRACEABILITY_MECHANISMS = [
    "hybrid_bfd_like_aimrce_frr",
]


def experiment_batch_command(scenario: str) -> str:
    if scenario == "regionalbackbone_failure_detection_cost_aware_transport_impact_randomized_onset":
        return "regional-cost-aware-transport-impact-randomized-onset-batch"
    if scenario == "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented":
        return "regional-cost-aware-transport-impact-instrumented-batch"
    if scenario == "regionalbackbone_failure_detection_cost_aware_transport_impact":
        return "regional-cost-aware-transport-impact-batch"
    if scenario == "regionalbackbone_failure_detection_cost_aware_backup":
        return "regional-cost-aware-backup-batch"
    if scenario == "regionalbackbone_failure_detection_degradation_sensitivity":
        return "regional-degradation-sensitivity-batch"
    return "regional-failure-detection-degraded-link-model-family-batch"


def scenario_display_name(scenario: str) -> str:
    return SCENARIO_DISPLAY.get(scenario, (scenario, scenario, "legacy/traceability scenario"))[0]


def scenario_slug(scenario: str) -> str:
    return SCENARIO_DISPLAY.get(scenario, (scenario, scenario, "legacy/traceability scenario"))[1]


def scenario_role(scenario: str) -> str:
    return SCENARIO_DISPLAY.get(scenario, (scenario, scenario, "legacy/traceability scenario"))[2]


@dataclass(frozen=True)
class CopySpec:
    source: Path
    destination: Path
    description: str
    essential: bool = False


@dataclass
class CopiedFile:
    source: Path
    destination: Path
    description: str
    size_bytes: int
    modified_time: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a compact package folder for the active dissertation experiment."
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help=f"Scenario to package. Default: {DEFAULT_SCENARIO}",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_DIR / "current_experiment",
        help="Root directory for generated current-experiment packages.",
    )
    return parser.parse_args()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    try:
        temp_path.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_copy_file(source: Path, destination: Path) -> CopiedFile:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f"{destination.name}.tmp")
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    stat = destination.stat()
    return CopiedFile(
        source=source,
        destination=destination,
        description="",
        size_bytes=stat.st_size,
        modified_time=datetime.fromtimestamp(stat.st_mtime),
    )


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def build_copy_specs(scenario: str, package_dir: Path) -> list[CopySpec]:
    outcomes = project_path("analysis", "output", "outcomes")
    datasets = project_path("analysis", "output", "datasets")
    reports = project_path("analysis", "output", "reports")
    debug = project_path("analysis", "output", "debug")
    network_impact = project_path("analysis", "output", "network_impact")
    ml_audit = project_path("analysis", "output", "ml_audit")
    final_evaluation = project_path("analysis", "output", "final_evaluation")
    runtime = project_path("simulations", "regionalbackbone")

    specs = [
        CopySpec(
            outcomes / f"{scenario}_headline_summary.csv",
            package_dir / "summaries" / "headline_summary.csv",
            "Scenario headline summary table",
        ),
        CopySpec(
            outcomes / f"{scenario}_headline_summary.txt",
            package_dir / "summaries" / "headline_summary.txt",
            "Human-readable scenario headline summary",
        ),
        CopySpec(
            outcomes / f"{scenario}_outcome_summary.csv",
            package_dir / "summaries" / "outcome_summary.csv",
            "Run-level outcome summary",
            essential=True,
        ),
        CopySpec(
            outcomes / f"{scenario}_report.txt",
            package_dir / "summaries" / "comparison_report.txt",
            "Human-readable comparison report",
        ),
        CopySpec(
            reports / f"{scenario}_report.txt",
            package_dir / "summaries" / "dataset_report.txt",
            "Dataset sanity report",
        ),
        CopySpec(
            debug / f"pipeline_integrity_{scenario}.txt",
            package_dir / "integrity" / "pipeline_integrity_report.txt",
            "Pipeline integrity report",
        ),
        CopySpec(
            debug / f"aimrce_model_family_risk_trace_{scenario}.csv",
            package_dir / "traces" / "risk_trace_run0.csv",
            "Run-0 AI-MRCE risk trace",
        ),
        CopySpec(
            debug / f"aimrce_model_action_events_{scenario}.csv",
            package_dir / "traces" / "model_action_events_run0.csv",
            "Run-0 model-action event summary",
        ),
        CopySpec(
            network_impact / f"{scenario}_network_impact_summary.csv",
            package_dir / "network_impact" / "network_impact_summary.csv",
            "Mechanism-level UDP/QoS network-impact summary",
        ),
        CopySpec(
            network_impact / f"{scenario}_network_impact_by_run.csv",
            package_dir / "network_impact" / "network_impact_by_run.csv",
            "Run-level UDP/QoS network-impact diagnostics",
        ),
        CopySpec(
            network_impact / f"{scenario}_network_impact_report.txt",
            package_dir / "network_impact" / "network_impact_report.txt",
            "Human-readable network-impact report",
        ),
        CopySpec(
            datasets / f"{scenario}_extended_dataset.csv",
            package_dir / "extended_telemetry" / "extended_dataset.csv",
            "Optional telemetry-v2 extended dataset",
        ),
        CopySpec(
            reports / f"{scenario}_extended_dataset_report.txt",
            package_dir / "extended_telemetry" / "extended_dataset_report.txt",
            "Optional telemetry-v2 dataset report",
        ),
        CopySpec(
            reports / f"{scenario}_extended_feature_classification.txt",
            package_dir / "extended_telemetry" / "extended_feature_classification.txt",
            "Optional telemetry-v2 feature classification and leakage notes",
        ),
        CopySpec(
            ml_audit / f"{scenario}_extended_feature_quality_report.txt",
            package_dir / "ml_audit" / "extended_feature_quality_report.txt",
            "Optional offline telemetry-v2 feature-quality report",
        ),
        CopySpec(
            ml_audit / f"{scenario}_extended_feature_quality.csv",
            package_dir / "ml_audit" / "extended_feature_quality.csv",
            "Optional offline telemetry-v2 feature-quality table",
        ),
        CopySpec(
            ml_audit / f"{scenario}_offline_ml_benchmark_report.txt",
            package_dir / "ml_audit" / "offline_ml_benchmark_report.txt",
            "Optional offline ML benchmark report",
        ),
        CopySpec(
            ml_audit / f"{scenario}_offline_ml_benchmark.csv",
            package_dir / "ml_audit" / "offline_ml_benchmark.csv",
            "Optional offline ML benchmark table",
        ),
        CopySpec(
            ml_audit / f"{scenario}_offline_decision_timing.csv",
            package_dir / "ml_audit" / "offline_decision_timing.csv",
            "Optional offline decision-timing proxy table",
        ),
        CopySpec(
            ml_audit / f"{scenario}_feature_importance.csv",
            package_dir / "ml_audit" / "feature_importance.csv",
            "Optional offline feature-importance table",
        ),
        CopySpec(
            runtime / "aimrce_runtime_manifest.csv",
            package_dir / "runtime_models" / "aimrce_runtime_manifest.csv",
            "Runtime model manifest",
        ),
        CopySpec(
            runtime / "aimrce_runtime_logreg.csv",
            package_dir / "runtime_models" / "aimrce_runtime_logreg.csv",
            "Logistic-regression runtime artifact",
        ),
        CopySpec(
            runtime / "aimrce_runtime_linsvm.csv",
            package_dir / "runtime_models" / "aimrce_runtime_linsvm.csv",
            "Linear-SVM runtime artifact",
        ),
        CopySpec(
            runtime / "aimrce_runtime_shallow_tree.csv",
            package_dir / "runtime_models" / "aimrce_runtime_shallow_tree.csv",
            "Shallow-tree runtime artifact",
        ),
        CopySpec(
            final_evaluation / "final_evaluation_report.md",
            package_dir / "final_evaluation" / "final_evaluation_report.md",
            "Paper-facing final evaluation report",
        ),
        CopySpec(
            final_evaluation / "final_evaluation_report.txt",
            package_dir / "final_evaluation" / "final_evaluation_report.txt",
            "Plain-text paper-facing final evaluation report",
        ),
        CopySpec(
            final_evaluation / "tables" / "final_policy_set.csv",
            package_dir / "final_evaluation" / "tables" / "final_policy_set.csv",
            "Final included/excluded mechanism policy set",
        ),
        CopySpec(
            final_evaluation / "tables" / "paper_figure_selection.csv",
            package_dir / "final_evaluation" / "tables" / "paper_figure_selection.csv",
            "Final paper figure selection table",
        ),
        CopySpec(
            final_evaluation / "tables" / "mechanism_policy_classification.csv",
            package_dir / "final_evaluation" / "tables" / "mechanism_policy_classification.csv",
            "Mechanism/policy classification table",
        ),
        CopySpec(
            final_evaluation / "tables" / "ml_policy_timing_by_scenario.csv",
            package_dir / "final_evaluation" / "tables" / "ml_policy_timing_by_scenario.csv",
            "Paper-facing AI-MRCE runtime-policy timing table",
        ),
        CopySpec(
            final_evaluation / "tables" / "paper_runtime_feature_importance.csv",
            package_dir / "final_evaluation" / "tables" / "paper_runtime_feature_importance.csv",
            "Runtime-safe telemetry-driver table",
        ),
        CopySpec(
            final_evaluation / "tables" / "event_timeline_summary.csv",
            package_dir / "final_evaluation" / "tables" / "event_timeline_summary.csv",
            "Scenario event timeline summary table",
        ),
        CopySpec(
            final_evaluation / "tables" / "scenario_b_tradeoff.csv",
            package_dir / "final_evaluation" / "tables" / "scenario_b_tradeoff.csv",
            "Scenario B benefit/cost trade-off table",
        ),
        CopySpec(
            final_evaluation / "tables" / "scenario_b_tradeoff_metric_definition.csv",
            package_dir / "final_evaluation" / "tables" / "scenario_b_tradeoff_metric_definition.csv",
            "Scenario B trade-off metric definition table",
        ),
        CopySpec(
            final_evaluation / "tables" / "policy_activation_matrix.csv",
            package_dir / "final_evaluation" / "tables" / "policy_activation_matrix.csv",
            "Policy activation matrix table",
        ),
        CopySpec(
            final_evaluation / "tables" / "result_variability_summary.csv",
            package_dir / "final_evaluation" / "tables" / "result_variability_summary.csv",
            "Result variability summary table",
        ),
        CopySpec(
            final_evaluation / "main_figures" / "paper_event_timeline.png",
            package_dir / "final_evaluation" / "main_figures" / "paper_event_timeline.png",
            "Scenario event timeline figure",
        ),
        CopySpec(
            final_evaluation / "main_figures" / "paper_runtime_feature_importance.png",
            package_dir / "final_evaluation" / "main_figures" / "paper_runtime_feature_importance.png",
            "Runtime telemetry-driver figure",
        ),
        CopySpec(
            final_evaluation / "main_figures" / "paper_packet_loss.png",
            package_dir / "final_evaluation" / "main_figures" / "paper_packet_loss.png",
            "Packet-delivery impact figure",
        ),
        CopySpec(
            final_evaluation / "main_figures" / "paper_queue_buildup_udp_quality.png",
            package_dir / "final_evaluation" / "main_figures" / "paper_queue_buildup_udp_quality.png",
            "Queue-buildup UDP quality figure",
        ),
        CopySpec(
            final_evaluation / "main_figures" / "paper_lead_time.png",
            package_dir / "final_evaluation" / "main_figures" / "paper_lead_time.png",
            "Protection lead-time figure",
        ),
        CopySpec(
            final_evaluation / "main_figures" / "paper_scenario_b_tradeoff.png",
            package_dir / "final_evaluation" / "main_figures" / "paper_scenario_b_tradeoff.png",
            "Scenario B cost-aware trade-off figure",
        ),
    ]
    if scenario in {
        "regionalbackbone_failure_detection_cost_aware_transport_impact",
    }:
        # The legacy mixed transport-impact package is primarily a transport/QoS
        # traceability package. The final Scenario C package includes run-0
        # model traces when the diagnostic extractor has generated them.
        specs = [spec for spec in specs if spec.destination.parent.name != "traces"]
    if scenario in {
        "regionalbackbone_failure_detection_cost_aware_backup",
        "regionalbackbone_failure_detection_cost_aware_transport_impact",
        "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented",
        "regionalbackbone_failure_detection_cost_aware_transport_impact_randomized_onset",
    }:
        specs.extend(
            [
                CopySpec(
                    network_impact / f"{scenario}_backup_path_cost_by_run.csv",
                    package_dir / "network_impact" / "backup_path_cost_by_run.csv",
                    "Cost-aware backup-path cost components by run",
                ),
                CopySpec(
                    network_impact / f"{scenario}_backup_path_cost_summary.csv",
                    package_dir / "network_impact" / "backup_path_cost_summary.csv",
                    "Cost-aware backup-path cost components summary",
                ),
            ]
        )
    if scenario in {
        "regionalbackbone_failure_detection_degraded_link_model_family",
        "regionalbackbone_failure_detection_cost_aware_backup",
        "regionalbackbone_failure_detection_cost_aware_transport_impact",
        "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented",
        "regionalbackbone_failure_detection_cost_aware_transport_impact_randomized_onset",
    }:
        specs.extend(
            [
                CopySpec(
                    network_impact / f"{scenario}_transport_by_run.csv",
                    package_dir / "network_impact" / "transport_by_run.csv",
                    "Mixed UDP/TCP endpoint diagnostics by run",
                ),
                CopySpec(
                    network_impact / f"{scenario}_transport_summary.csv",
                    package_dir / "network_impact" / "transport_summary.csv",
                    "Mixed UDP/TCP endpoint diagnostics summary",
                ),
                CopySpec(
                    network_impact / f"{scenario}_inet_metrics_summary.csv",
                    package_dir / "network_impact" / "inet_metrics_summary.csv",
                    "Unified transport/network metric summary when available",
                ),
            ]
        )
    if scenario == "regionalbackbone_failure_detection_cost_aware_transport_impact_randomized_onset":
        specs.extend(
            [
                CopySpec(
                    final_evaluation / "tables" / "randomized_onset_scenario_summary.csv",
                    package_dir / "final_evaluation" / "tables" / "randomized_onset_scenario_summary.csv",
                    "Supplementary Scenario C-R run-level randomized-onset summary",
                ),
                CopySpec(
                    final_evaluation / "tables" / "randomized_onset_lead_time_summary.csv",
                    package_dir / "final_evaluation" / "tables" / "randomized_onset_lead_time_summary.csv",
                    "Supplementary Scenario C-R lead-time robustness summary",
                ),
                CopySpec(
                    final_evaluation / "tables" / "randomized_onset_event_shift_validation.csv",
                    package_dir / "final_evaluation" / "tables" / "randomized_onset_event_shift_validation.csv",
                    "Supplementary Scenario C-R event-shift validation table",
                ),
                CopySpec(
                    final_evaluation / "tables" / "randomized_onset_claim_boundary.csv",
                    package_dir / "final_evaluation" / "tables" / "randomized_onset_claim_boundary.csv",
                    "Supplementary Scenario C-R claim-boundary table",
                ),
                CopySpec(
                    final_evaluation / "supplementary_figures" / "paper_randomized_onset_activation_vs_qos_event.png",
                    package_dir / "final_evaluation" / "supplementary_figures" / "paper_randomized_onset_activation_vs_qos_event.png",
                    "Supplementary randomized-onset activation-vs-QoS-event figure",
                ),
                CopySpec(
                    final_evaluation / "supplementary_figures" / "paper_randomized_onset_lead_time.png",
                    package_dir / "final_evaluation" / "supplementary_figures" / "paper_randomized_onset_lead_time.png",
                    "Supplementary randomized-onset lead-time robustness figure",
                ),
                CopySpec(
                    final_evaluation / "supplementary_figures" / "paper_randomized_onset_qos_impact.png",
                    package_dir / "final_evaluation" / "supplementary_figures" / "paper_randomized_onset_qos_impact.png",
                    "Supplementary randomized-onset QoS-impact figure",
                ),
                CopySpec(
                    OUTPUT_DIR / "audit" / "randomized_onset_robustness_audit.txt",
                    package_dir / "audit" / "randomized_onset_robustness_audit.txt",
                    "Supplementary randomized-onset robustness audit",
                ),
            ]
        )
    return specs


def read_outcome_rows(outcome_summary_path: Path) -> list[dict[str, str]]:
    if not outcome_summary_path.exists():
        return []
    with outcome_summary_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def detect_workspace_mode(
    outcome_rows: list[dict[str, str]],
    scenario: str = DEFAULT_SCENARIO,
) -> tuple[str, list[str], dict[str, list[int]]]:
    warnings: list[str] = []
    runs_by_mechanism: dict[str, list[int]] = {}

    for row in outcome_rows:
        mechanism = row.get("protection_mode") or row.get("mechanism_family") or row.get("config_name") or "unknown"
        run_text = row.get("run_number", "")
        try:
            run_number = int(float(run_text))
        except ValueError:
            warnings.append(f"Could not parse run_number='{run_text}' for mechanism '{mechanism}'.")
            continue
        runs_by_mechanism.setdefault(mechanism, [])
        if run_number not in runs_by_mechanism[mechanism]:
            runs_by_mechanism[mechanism].append(run_number)

    for runs in runs_by_mechanism.values():
        runs.sort()

    observed_mechanisms = set(runs_by_mechanism)
    expected_mechanisms = set(EXPECTED_MECHANISMS)
    if expected_mechanisms and not expected_mechanisms.issubset(observed_mechanisms):
        missing = sorted(expected_mechanisms - observed_mechanisms)
        warnings.append(f"Outcome summary is missing expected mechanism(s): {', '.join(missing)}.")

    if expected_mechanisms.issubset(observed_mechanisms):
        if scenario == "regionalbackbone_failure_detection_cost_aware_transport_impact_randomized_onset":
            expected_full = [0]
            expected_run0 = [0]
            expected_runs = [runs_by_mechanism[mechanism] for mechanism in EXPECTED_MECHANISMS]
            if all(runs == expected_full for runs in expected_runs):
                return "complete randomized-onset sweep mode", warnings, runs_by_mechanism
        expected_full = [0, 1, 2, 3, 4]
        expected_run0 = [0]
        expected_runs = [runs_by_mechanism[mechanism] for mechanism in EXPECTED_MECHANISMS]
        if all(runs == expected_full for runs in expected_runs):
            return "full five-run publication mode", warnings, runs_by_mechanism
        if all(runs == expected_run0 for runs in expected_runs):
            warnings.append("Workspace appears to contain run-0 development outputs only.")
            return "run-0 development mode", warnings, runs_by_mechanism

    if outcome_rows:
        warnings.append("Workspace appears to contain partial or mixed run coverage.")
        return "partial/mixed output mode", warnings, runs_by_mechanism

    warnings.append("Outcome summary is missing, so workspace mode could not be determined.")
    return "unknown output mode", warnings, runs_by_mechanism


def read_pipeline_status(integrity_path: Path) -> tuple[str, list[str]]:
    if not integrity_path.exists():
        return "missing", ["Pipeline integrity report is missing."]

    text = integrity_path.read_text(encoding="utf-8", errors="replace")
    status = "unknown"
    for line in text.splitlines():
        if line.startswith("Overall status:"):
            status = line.split(":", 1)[1].strip()
            break

    warnings: list[str] = []
    if status == "OK_WITH_WARNINGS":
        warnings.append("Pipeline integrity currently reports OK_WITH_WARNINGS; inspect integrity/pipeline_integrity_report.txt.")
    elif status == "FAIL":
        warnings.append("Pipeline integrity currently reports FAIL; this package is not publication-ready.")
    elif status == "missing":
        warnings.append("Pipeline integrity status is missing.")
    return status, warnings


def format_timestamp(path: Path) -> str:
    if not path.exists():
        return "missing"
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def copy_artifacts(specs: list[CopySpec]) -> tuple[list[CopiedFile], list[str]]:
    copied: list[CopiedFile] = []
    warnings: list[str] = []

    for spec in specs:
        if spec.source.suffix.lower() in RAW_RESULT_SUFFIXES:
            warnings.append(f"Refused to copy raw result artifact: {spec.source}")
            continue
        if not spec.source.exists():
            severity = "essential" if spec.essential else "optional"
            warnings.append(f"Missing {severity} source for {spec.description}: {spec.source}")
            continue

        copied_file = atomic_copy_file(spec.source, spec.destination)
        copied_file.description = spec.description
        copied.append(copied_file)

    return copied, warnings


def build_methodology_summary(scenario: str, mode: str) -> str:
    display = scenario_display_name(scenario)
    role = scenario_role(scenario)
    return f"""# Methodology Summary

Scenario: **{display}**

Internal id: `{scenario}`

Role: {role}

Current package mode: **{mode}**

AI-MRCE is a telemetry-driven proactive controller in the regional OMNeT++/INET
OSPF backbone. It evaluates current telemetry with rule-based and compact
runtime ML policies, then activates project-local FRR-like static repair routes
when risk remains positive for the configured decision streak.

The current package should be read narrowly: it documents one of the final
three deterministic mixed UDP/TCP paper-facing cohorts. The five-run
publication mode provides reproducibility and mechanism-family coverage for the
selected cohort, not broad stochastic statistical significance.

The active model-family cohort compares:

- `ospf_only`
- `bfd_like_frr`
- `aimrce_rule_based_frr`
- `aimrce_logistic_regression_frr`
- `aimrce_linear_svm_frr`
- `aimrce_shallow_tree_frr`

All mechanisms use the same regional topology, shared mixed UDP/TCP workload,
profile-conditioned impairment timing, and project-local repair-route
semantics within the selected scenario. AI-MRCE model-family rows differ only
by decision policy/runtime model.

The legacy `hybrid_bfd_like_aimrce_frr` mechanism may still appear in raw
traceability outputs from older complete cohorts, but it is excluded from the
final main figures, AI-MRCE family means, runtime-policy comparison, and default
main package mechanism set because it is a hybrid reactive-predictive
arbitration policy rather than a pure AI-MRCE/ML policy.

The learned runtime policies are compact simulator-derived policy variants based
on four runtime features. They are not production-grade general predictors.

Recommended publication table fields are mechanism family, runtime model type,
trigger source, activation time, lead time before hard failure,
post-hard-failure unobserved packet gaps, activation-to-failure unobserved
packet gaps, activation-to-failure reordered packets, activation queue length,
fallback used, and repairRouteCount.

Most useful files for review are in `summaries/`, `integrity/`, and `traces/`.
When generated, `network_impact/` adds an analysis-only UDP/QoS view derived
from existing dataset and outcome artifacts.
For final mixed UDP/TCP main scenarios, `network_impact/` also includes
endpoint-observed TCP received-byte/goodput/progress proxy tables where the
traffic is exported. Cost-aware and congestion/queue-buildup scenarios
additionally include separate backup-usage and backup-cost component tables.
TCP retransmission, RTT, cwnd, and exact flow-completion metrics are not
claimed unless the corresponding INET exports are explicitly present.
When generated, `extended_telemetry/` carries optional telemetry-v2 candidate
features and leakage-classification notes for future ML work.
When generated, `ml_audit/` carries offline-only feature-quality, benchmark,
decision-timing, and feature-importance diagnostics. These files are not
deployed runtime artifacts.
Raw OMNeT++ `.vec`, `.vci`, `.sca`, `.elog`, packet captures, and build outputs
are intentionally not included because they are large and reproducible.
"""


def build_limitations_text() -> str:
    return """# Limitations And Non-Claims

- AI-MRCE is evaluated in a scenario-conditioned degraded-link/brownout profile.
- The current result is not a universal failure-prediction claim.
- The five runs provide reproducibility/coverage for this controlled cohort,
  not broad stochastic statistical significance.
- Learned AI-MRCE runtime policies are compact simulator-derived variants based
  on four runtime features; they are not production-grade predictors.
- BFD-like detection is project-local and BFD-inspired; it is not RFC-compliant BFD.
- FRR-like repair routes are project-local static `/32` routes; they are not standards-compliant LFA, TI-LFA, RSVP-TE FRR, or OSPF FRR.
- OSPF-only is a no-protection INET OSPF baseline, not a tuned fast-recovery baseline.
- The severe packet-error-rate profile is a stress/brownout scenario, not a calibrated field trace.
- Reordering and activation-to-failure transition costs remain visible and must be reported.
- Packet sequence gaps are receiver-observed operational diagnostics, not direct proof of packet loss without the unobserved/reordered distinction.
- Legacy `missing` fields are forward-jump compatibility diagnostics, not direct packet-loss claims.
- Network-impact delivery/loss-like ratios are proxies unless exact sent/received accounting is available for the selected phase.
- Network-impact delay-variation fields are window-mean delta proxies, not full RFC 5481 IPDV.
- TCP impact is evaluated only as endpoint progress/goodput proxies in the
  unified mixed UDP/TCP cohorts; it is not a TCP-stack recovery analysis.
- Generated package paths may include absolute local Windows source paths for provenance; reproduce from your own clone path for public review.
- Do not generalize these results to all topologies, traffic mixes, failure classes, or production router implementations.
"""


def build_reproduce_bat(scenario: str) -> str:
    batch_command = experiment_batch_command(scenario)
    return f"""@echo off
setlocal
cd /d "%~dp0\\..\\..\\..\\..\\.."

cmd /c run_experiments.bat {batch_command} --clean --yes --skip-runtime-export --skip-build
cmd /c run_analysis.bat build-dataset --scenario {scenario}
cmd /c run_analysis.bat build-dataset --scenario {scenario} --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario {scenario}
cmd /c run_analysis.bat dataset-report --scenario {scenario} --feature-set extended
cmd /c run_analysis.bat compare-outcomes --inputs analysis\\output\\outcomes\\{scenario}_outcome_summary.csv --output-prefix analysis\\output\\outcomes\\{scenario}
cmd /c run_analysis.bat model-risk-trace --scenario {scenario} --runs 0 --start 78 --end 86
cmd /c run_analysis.bat network-impact --scenario {scenario}
cmd /c run_analysis.bat pipeline-integrity --scenario {scenario}
cmd /c run_analysis.bat package-current-experiment --scenario {scenario}
"""


def build_useful_commands(scenario: str) -> str:
    batch_command = experiment_batch_command(scenario)
    return f"""Useful current-experiment commands
==================================

Package compact current outputs:
cmd /c run_analysis.bat package-current-experiment --scenario {scenario}

Run full five-run publication cohort:
cmd /c run_experiments.bat {batch_command} --clean --yes --skip-runtime-export --skip-build

Run run-0 smoke/regression mode:
cmd /c run_experiments.bat {batch_command} --runs 0 --clean --yes --skip-runtime-export --skip-build

Regenerate dataset/report/comparison from existing raw results:
cmd /c run_analysis.bat build-dataset --scenario {scenario}
cmd /c run_analysis.bat build-dataset --scenario {scenario} --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario {scenario}
cmd /c run_analysis.bat dataset-report --scenario {scenario} --feature-set extended
cmd /c run_analysis.bat compare-outcomes --inputs analysis\\output\\outcomes\\{scenario}_outcome_summary.csv --output-prefix analysis\\output\\outcomes\\{scenario}

Regenerate graph-ready risk trace:
cmd /c run_analysis.bat model-risk-trace --scenario {scenario} --runs 0 --start 78 --end 86

Generate analysis-only UDP/QoS network-impact report:
cmd /c run_analysis.bat network-impact --scenario {scenario}

Check integrity:
cmd /c run_analysis.bat pipeline-integrity --scenario {scenario}

Preview generated-output cleanup:
cmd /c run_analysis.bat clean-generated
"""


def build_audit_notes() -> str:
    audit_dir = OUTPUT_DIR / "audit"
    relevant = [
        audit_dir / "final_publication_readiness_audit.txt",
        audit_dir / "python_pipeline_performance_step3c_applied.txt",
        audit_dir / "python_pipeline_reliability_step3b_applied.txt",
    ]
    chunks: list[str] = ["Latest Relevant Audit Notes", "===========================", ""]
    for path in relevant:
        if not path.exists():
            chunks.append(f"Missing optional audit note: {path}")
            chunks.append("")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.append(f"--- {path.relative_to(PROJECT_ROOT)} ---")
        chunks.append(text.strip())
        chunks.append("")
    return "\n".join(chunks).strip() + "\n"


def build_readme(
    scenario: str,
    package_dir: Path,
    mode: str,
    pipeline_status: str,
    copied: list[CopiedFile],
    warnings: list[str],
    runs_by_mechanism: dict[str, list[int]],
) -> str:
    display = scenario_display_name(scenario)
    role = scenario_role(scenario)
    copied_lines = []
    for item in copied:
        copied_lines.append(
            f"- `{item.destination.relative_to(package_dir)}` from "
            f"`{item.source.relative_to(PROJECT_ROOT)}` "
            f"(modified {format_timestamp(item.source)}, {item.size_bytes} bytes): {item.description}"
        )

    warning_lines = [f"- {warning}" for warning in warnings] or ["- none"]
    mechanism_lines = []
    for mechanism in EXPECTED_MECHANISMS:
        runs = runs_by_mechanism.get(mechanism, [])
        mechanism_lines.append(f"- `{mechanism}`: runs {','.join(map(str, runs)) if runs else 'not observed'}")
    legacy_lines = []
    for mechanism in LEGACY_TRACEABILITY_MECHANISMS:
        runs = runs_by_mechanism.get(mechanism, [])
        if runs:
            legacy_lines.append(
                f"- `{mechanism}`: runs {','.join(map(str, runs))}; traceability/future-only, excluded from final main analysis"
            )

    return f"""# Current Experiment Package

This folder is a compact generated package for the active dissertation
experiment. It copies small, useful outputs and context from the working tree so
they can be sent for review without searching through `analysis/output/`.

It is **not** a full archive and does **not** include raw OMNeT++ result files.

## Scenario

**{display}**

Internal id: `{scenario}`

Role: {role}

Workspace mode: **{mode}**

Pipeline integrity status: **{pipeline_status}**

If this package reports full five-run publication mode, those runs should be
read as reproducibility and mechanism-family coverage for the selected
deterministic mixed UDP/TCP cohort, not as broad stochastic statistical
significance.

## Mechanism Families

Final main mechanism set:

{os.linesep.join(mechanism_lines)}

Legacy/future traceability mechanisms:

{os.linesep.join(legacy_lines) if legacy_lines else "- none observed in this package"}

## Most Useful Files To Send For Review

- `summaries/headline_summary.csv`
- `summaries/headline_summary.txt`
- `summaries/outcome_summary.csv`
- `summaries/comparison_report.txt`
- `integrity/pipeline_integrity_report.txt`
- `traces/risk_trace_run0.csv`
- `traces/model_action_events_run0.csv`
- `network_impact/network_impact_report.txt` when generated
- `extended_telemetry/extended_feature_classification.txt` when generated
- `ml_audit/offline_ml_benchmark_report.txt` when generated
- `methodology/limitations_and_nonclaims.md`

## Not Included

The package intentionally excludes large or reproducible artifacts:

- raw `.vec`, `.vci`, `.sca`, `.elog`, `.anf`, `.pcap`, and `.pcapng` files;
- OMNeT++ build outputs;
- full `results/` folders;
- analysis virtual environments and caches.

Copied file metadata may contain absolute local Windows source paths or
timestamps for provenance. Those paths are not requirements for public users;
regenerate the package from the project root in your own clone.

## Copied Files

{os.linesep.join(copied_lines) if copied_lines else "- none"}

## Warnings / Missing Optional Files

{os.linesep.join(warning_lines)}

## Regeneration Commands

Run from the project root:

```bat
cmd /c run_experiments.bat {experiment_batch_command(scenario)} --clean --yes --skip-runtime-export --skip-build
cmd /c run_analysis.bat build-dataset --scenario {scenario}
cmd /c run_analysis.bat build-dataset --scenario {scenario} --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario {scenario}
cmd /c run_analysis.bat dataset-report --scenario {scenario} --feature-set extended
cmd /c run_analysis.bat compare-outcomes --inputs analysis\\output\\outcomes\\{scenario}_outcome_summary.csv --output-prefix analysis\\output\\outcomes\\{scenario}
cmd /c run_analysis.bat model-risk-trace --scenario {scenario} --runs 0 --start 78 --end 86
cmd /c run_analysis.bat network-impact --scenario {scenario}
cmd /c run_analysis.bat pipeline-integrity --scenario {scenario}
cmd /c run_analysis.bat package-current-experiment --scenario {scenario}
```

If the local binary or runtime deployment artifacts are stale, rebuild/export
them before using `--skip-build` or `--skip-runtime-export`.

## Limitations

See `methodology/limitations_and_nonclaims.md`.
"""


def build_manifest(
    scenario: str,
    package_dir: Path,
    mode: str,
    pipeline_status: str,
    copied: list[CopiedFile],
    warnings: list[str],
) -> str:
    lines = [
        "Current Experiment Package Manifest",
        "===================================",
        f"created_at={datetime.now().isoformat(timespec='seconds')}",
        f"scenario_display_name={scenario_display_name(scenario)}",
        f"scenario_role={scenario_role(scenario)}",
        f"scenario={scenario}",
        f"package_dir={package_dir}",
        f"workspace_mode={mode}",
        f"pipeline_integrity_status={pipeline_status}",
        f"full_cohort_appears_present={'yes' if mode == 'full five-run publication mode' else 'no'}",
        "",
        "Copied files:",
    ]
    if copied:
        for item in copied:
            lines.append(
                f"- {item.destination.relative_to(package_dir)} <= {item.source} "
                f"({item.size_bytes} bytes, source_modified={format_timestamp(item.source)})"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Warnings / missing optional files:")
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def write_generated_context_files(
    scenario: str,
    package_dir: Path,
    mode: str,
    pipeline_status: str,
    copied: list[CopiedFile],
    warnings: list[str],
    runs_by_mechanism: dict[str, list[int]],
) -> None:
    atomic_write_text(
        package_dir / "methodology" / "methodology_summary.md",
        build_methodology_summary(scenario, mode),
    )
    atomic_write_text(
        package_dir / "methodology" / "limitations_and_nonclaims.md",
        build_limitations_text(),
    )
    atomic_write_text(
        package_dir / "commands" / "reproduce_current_experiment.bat",
        build_reproduce_bat(scenario),
    )
    atomic_write_text(
        package_dir / "commands" / "useful_analysis_commands.txt",
        build_useful_commands(scenario),
    )
    atomic_write_text(
        package_dir / "audit" / "latest_relevant_audit_notes.txt",
        build_audit_notes(),
    )
    atomic_write_text(
        package_dir / "README_CURRENT_EXPERIMENT.md",
        build_readme(
            scenario,
            package_dir,
            mode,
            pipeline_status,
            copied,
            warnings,
            runs_by_mechanism,
        ),
    )
    atomic_write_text(
        package_dir / "package_manifest.txt",
        build_manifest(scenario, package_dir, mode, pipeline_status, copied, warnings),
    )


def assert_no_raw_results_copied(package_dir: Path) -> list[str]:
    warnings: list[str] = []
    for path in package_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in RAW_RESULT_SUFFIXES:
            warnings.append(f"Raw result artifact is present in package and should be removed: {path}")
    return warnings


def clean_generated_package_dir(package_dir: Path, output_root: Path) -> None:
    package_resolved = package_dir.resolve()
    output_resolved = output_root.resolve()
    if output_resolved not in package_resolved.parents:
        raise SystemExit(f"Refusing to clean package outside output root: {package_dir}")
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)


def main() -> int:
    args = parse_args()
    scenario = args.scenario
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    package_dir = output_root / scenario_slug(scenario)
    clean_generated_package_dir(package_dir, output_root)

    specs = build_copy_specs(scenario, package_dir)
    copied, warnings = copy_artifacts(specs)

    outcome_summary = OUTPUT_DIR / "outcomes" / f"{scenario}_outcome_summary.csv"
    outcome_rows = read_outcome_rows(outcome_summary)
    mode, mode_warnings, runs_by_mechanism = detect_workspace_mode(outcome_rows, scenario)
    warnings.extend(mode_warnings)

    integrity_path = OUTPUT_DIR / "debug" / f"pipeline_integrity_{scenario}.txt"
    pipeline_status, integrity_warnings = read_pipeline_status(integrity_path)
    warnings.extend(integrity_warnings)

    raw_warnings = assert_no_raw_results_copied(package_dir)
    warnings.extend(raw_warnings)

    write_generated_context_files(
        scenario,
        package_dir,
        mode,
        pipeline_status,
        copied,
        warnings,
        runs_by_mechanism,
    )

    print(f"Packaged current experiment: {scenario}")
    print(f"Package folder: {package_dir}")
    print(f"Copied compact source artifact(s): {len(copied)}")
    if warnings:
        print(f"Warnings: {len(warnings)}")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("Warnings: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
