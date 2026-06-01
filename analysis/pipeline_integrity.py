#!/usr/bin/env python3
"""
Conservative pipeline-integrity report for the active AI-MRCE model-family cohort.

The report cross-checks generated raw results and analysis artifacts. It does
not change simulation, dataset, training, or comparison semantics.
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = PROJECT_ROOT / "results"
OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
OUTCOMES_DIR = OUTPUT_ROOT / "outcomes"
DEBUG_DIR = OUTPUT_ROOT / "debug"
RUNTIME_ARTIFACT_DIR = PROJECT_ROOT / "simulations" / "regionalbackbone"

CORE_SCENARIO = "regionalbackbone_failure_detection_degraded_link_model_family"
SENSITIVITY_SCENARIO = "regionalbackbone_failure_detection_degradation_sensitivity"
COST_AWARE_BACKUP_SCENARIO = "regionalbackbone_failure_detection_cost_aware_backup"
COST_AWARE_TRANSPORT_SCENARIO = "regionalbackbone_failure_detection_cost_aware_transport_impact"
COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO = "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented"
SCENARIO = CORE_SCENARIO
RESULTS_DIR = RESULTS_ROOT / "regionalbackbone" / "failure_detection_degraded_link_model_family"

EXPECTED_CONFIGS = {
    "RegionalBackboneFailureDegradedLinkOspfOnly": {
        "mechanism": "ospf_only",
        "runtime_model_type": "",
        "cohort_config": "RegionalBackboneFailureDegradedLinkOspfOnlyCohort",
    },
    "RegionalBackboneFailureDegradedLinkBfdLikeFrr": {
        "mechanism": "bfd_like_frr",
        "runtime_model_type": "",
        "cohort_config": "RegionalBackboneFailureDegradedLinkBfdLikeFrrCohort",
    },
    "RegionalBackboneFailureDegradedLinkAiMrceRuleBased": {
        "mechanism": "aimrce_rule_based_frr",
        "runtime_model_type": "rule_based",
        "cohort_config": "RegionalBackboneFailureDegradedLinkAiMrceRuleBasedCohort",
    },
    "RegionalBackboneFailureDegradedLinkAiMrceLogReg": {
        "mechanism": "aimrce_logistic_regression_frr",
        "runtime_model_type": "logistic_regression",
        "cohort_config": "RegionalBackboneFailureDegradedLinkAiMrceLogRegCohort",
    },
    "RegionalBackboneFailureDegradedLinkAiMrceLinearSvm": {
        "mechanism": "aimrce_linear_svm_frr",
        "runtime_model_type": "linear_svm",
        "cohort_config": "RegionalBackboneFailureDegradedLinkAiMrceLinearSvmCohort",
    },
    "RegionalBackboneFailureDegradedLinkAiMrceShallowTree": {
        "mechanism": "aimrce_shallow_tree_frr",
        "runtime_model_type": "shallow_tree",
        "cohort_config": "RegionalBackboneFailureDegradedLinkAiMrceShallowTreeCohort",
    },
    "RegionalBackboneFailureDegradedLinkHybrid": {
        "mechanism": "hybrid_bfd_like_aimrce_frr",
        "runtime_model_type": "rule_based",
        "cohort_config": "RegionalBackboneFailureDegradedLinkHybridCohort",
    },
}

EXPECTED_MECHANISMS = {value["mechanism"] for value in EXPECTED_CONFIGS.values()}
CORE_EXPECTED_CONFIGS = EXPECTED_CONFIGS.copy()
SENSITIVITY_PROFILE_TITLES = ("MildSlow", "Moderate", "SevereFast")
COST_AWARE_PROFILE_TITLES = ("Mild", "Moderate", "FastWarning")
TRANSPORT_PROFILE_TITLES = ("TransportMild", "TransportModerate", "TransportFastWarning")
TRANSPORT_INSTRUMENTED_PROFILE_TITLES = (
    "TransportInstrumentedMild",
    "TransportInstrumentedModerate",
    "TransportInstrumentedFastWarning",
)
SENSITIVITY_MECHANISMS = {
    "OspfOnly": ("ospf_only", ""),
    "BfdLikeFrr": ("bfd_like_frr", ""),
    "AiMrceRuleBased": ("aimrce_rule_based_frr", "rule_based"),
    "AiMrceLogReg": ("aimrce_logistic_regression_frr", "logistic_regression"),
    "AiMrceLinearSvm": ("aimrce_linear_svm_frr", "linear_svm"),
    "AiMrceShallowTree": ("aimrce_shallow_tree_frr", "shallow_tree"),
    "Hybrid": ("hybrid_bfd_like_aimrce_frr", "rule_based"),
}


def build_sensitivity_expected_configs() -> dict[str, dict[str, str]]:
    configs: dict[str, dict[str, str]] = {}
    for profile_title in SENSITIVITY_PROFILE_TITLES:
        for mechanism_suffix, (mechanism, runtime_model_type) in SENSITIVITY_MECHANISMS.items():
            config_name = f"RegionalBackboneSensitivity{profile_title}{mechanism_suffix}"
            configs[config_name] = {
                "mechanism": mechanism,
                "runtime_model_type": runtime_model_type,
                "cohort_config": f"{config_name}Cohort",
            }
    return configs


def build_cost_aware_expected_configs() -> dict[str, dict[str, str]]:
    configs: dict[str, dict[str, str]] = {}
    for profile_title in COST_AWARE_PROFILE_TITLES:
        for mechanism_suffix, (mechanism, runtime_model_type) in SENSITIVITY_MECHANISMS.items():
            config_name = f"RegionalBackboneCostAware{profile_title}{mechanism_suffix}"
            configs[config_name] = {
                "mechanism": mechanism,
                "runtime_model_type": runtime_model_type,
                "cohort_config": f"{config_name}Cohort",
            }
    return configs


def build_transport_expected_configs() -> dict[str, dict[str, str]]:
    configs: dict[str, dict[str, str]] = {}
    for profile_title in TRANSPORT_PROFILE_TITLES:
        for mechanism_suffix, (mechanism, runtime_model_type) in SENSITIVITY_MECHANISMS.items():
            config_name = f"RegionalBackboneCostAware{profile_title}{mechanism_suffix}"
            configs[config_name] = {
                "mechanism": mechanism,
                "runtime_model_type": runtime_model_type,
                "cohort_config": f"{config_name}Cohort",
            }
    return configs


def build_transport_instrumented_expected_configs() -> dict[str, dict[str, str]]:
    configs: dict[str, dict[str, str]] = {}
    for profile_title in TRANSPORT_INSTRUMENTED_PROFILE_TITLES:
        for mechanism_suffix, (mechanism, runtime_model_type) in SENSITIVITY_MECHANISMS.items():
            config_name = f"RegionalBackboneCostAware{profile_title}{mechanism_suffix}"
            configs[config_name] = {
                "mechanism": mechanism,
                "runtime_model_type": runtime_model_type,
                "cohort_config": f"{config_name}Cohort",
            }
    return configs


def expected_configs_for_scenario(scenario: str) -> dict[str, dict[str, str]]:
    if scenario == CORE_SCENARIO:
        return CORE_EXPECTED_CONFIGS.copy()
    if scenario == SENSITIVITY_SCENARIO:
        return build_sensitivity_expected_configs()
    if scenario == COST_AWARE_BACKUP_SCENARIO:
        return build_cost_aware_expected_configs()
    if scenario == COST_AWARE_TRANSPORT_SCENARIO:
        return build_transport_expected_configs()
    if scenario == COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
        return build_transport_instrumented_expected_configs()
    raise SystemExit(f"Unsupported scenario '{scenario}'.")


def results_dir_for_scenario(scenario: str) -> Path:
    if scenario == SENSITIVITY_SCENARIO:
        result_leaf = "failure_detection_degradation_sensitivity"
    elif scenario == COST_AWARE_BACKUP_SCENARIO:
        result_leaf = "failure_detection_cost_aware_backup"
    elif scenario == COST_AWARE_TRANSPORT_SCENARIO:
        result_leaf = "failure_detection_cost_aware_transport_impact"
    elif scenario == COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
        result_leaf = "ti_inst"
    else:
        result_leaf = "failure_detection_degraded_link_model_family"
    return RESULTS_ROOT / "regionalbackbone" / result_leaf


def artifacts_for_scenario(scenario: str) -> dict[str, Path]:
    return {
        "dataset": OUTPUT_ROOT / "datasets" / f"{scenario}_dataset.csv",
        "dataset_report": OUTPUT_ROOT / "reports" / f"{scenario}_report.txt",
        "outcome_summary": OUTCOMES_DIR / f"{scenario}_outcome_summary.csv",
        "comparison_runs": OUTCOMES_DIR / f"{scenario}_runs.csv",
        "comparison_summary": OUTCOMES_DIR / f"{scenario}_summary.csv",
        "comparison_report": OUTCOMES_DIR / f"{scenario}_report.txt",
        "headline_summary_csv": OUTCOMES_DIR / f"{scenario}_headline_summary.csv",
        "headline_summary_txt": OUTCOMES_DIR / f"{scenario}_headline_summary.txt",
        "risk_trace": DEBUG_DIR / f"aimrce_model_family_risk_trace_{scenario}.csv",
        "event_summary": DEBUG_DIR / f"aimrce_model_action_events_{scenario}.csv",
    }

ARTIFACTS = {
    "dataset": OUTPUT_ROOT / "datasets" / f"{SCENARIO}_dataset.csv",
    "dataset_report": OUTPUT_ROOT / "reports" / f"{SCENARIO}_report.txt",
    "outcome_summary": OUTCOMES_DIR / f"{SCENARIO}_outcome_summary.csv",
    "comparison_runs": OUTCOMES_DIR / f"{SCENARIO}_runs.csv",
    "comparison_summary": OUTCOMES_DIR / f"{SCENARIO}_summary.csv",
    "comparison_report": OUTCOMES_DIR / f"{SCENARIO}_report.txt",
    "headline_summary_csv": OUTCOMES_DIR / f"{SCENARIO}_headline_summary.csv",
    "headline_summary_txt": OUTCOMES_DIR / f"{SCENARIO}_headline_summary.txt",
    "risk_trace": DEBUG_DIR / f"aimrce_model_family_risk_trace_{SCENARIO}.csv",
    "event_summary": DEBUG_DIR / f"aimrce_model_action_events_{SCENARIO}.csv",
}

RUNTIME_ARTIFACTS = {
    "runtime_logreg": RUNTIME_ARTIFACT_DIR / "aimrce_runtime_logreg.csv",
    "runtime_linsvm": RUNTIME_ARTIFACT_DIR / "aimrce_runtime_linsvm.csv",
    "runtime_shallow_tree": RUNTIME_ARTIFACT_DIR / "aimrce_runtime_shallow_tree.csv",
    "runtime_manifest": RUNTIME_ARTIFACT_DIR / "aimrce_runtime_manifest.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a pipeline-integrity report for supported AI-MRCE cohorts.")
    parser.add_argument(
        "--scenario",
        default=SCENARIO,
        choices=[
            CORE_SCENARIO,
            SENSITIVITY_SCENARIO,
            COST_AWARE_BACKUP_SCENARIO,
            COST_AWARE_TRANSPORT_SCENARIO,
            COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO,
        ],
        help="Scenario preset to inspect.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report path. Defaults under analysis/output/debug/.",
    )
    return parser.parse_args()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def artifact_line(name: str, path: Path) -> str:
    if not path.exists():
        return f"[MISSING] {name}: {path}"
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    return f"[OK] {name}: {path} ({stat.st_size} bytes, modified={modified})"


def newest_existing(paths: list[Path]) -> tuple[float | None, Path | None]:
    existing_paths = [path for path in paths if path.exists()]
    if not existing_paths:
        return None, None
    newest = max(existing_paths, key=lambda path: path.stat().st_mtime)
    return newest.stat().st_mtime, newest


def stale_warning(generated: Path, sources: list[Path], regenerate_command: str) -> str | None:
    if not generated.exists():
        return None
    newest_mtime, newest_source = newest_existing(sources)
    if newest_mtime is None or newest_source is None:
        return None
    if generated.stat().st_mtime >= newest_mtime:
        return None
    return (
        f"{generated} appears stale: it is older than {newest_source}. "
        f"Regenerate with: {regenerate_command}"
    )


def count_result_triplets() -> dict[str, dict[int, set[str]]]:
    triplets: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    if not RESULTS_DIR.exists():
        return triplets

    for path in RESULTS_DIR.glob("*.*"):
        if path.suffix.lower() not in {".sca", ".vec", ".vci"}:
            continue
        stem = path.stem
        if "-" not in stem:
            continue
        config_name, run_text = stem.rsplit("-", 1)
        try:
            run_number = int(run_text)
        except ValueError:
            continue
        triplets[config_name][run_number].add(path.suffix.lower())
    return triplets


def main() -> None:
    args = parse_args()
    global SCENARIO, RESULTS_DIR, EXPECTED_CONFIGS, EXPECTED_MECHANISMS, ARTIFACTS
    SCENARIO = args.scenario
    RESULTS_DIR = results_dir_for_scenario(SCENARIO)
    EXPECTED_CONFIGS = expected_configs_for_scenario(SCENARIO)
    EXPECTED_MECHANISMS = {value["mechanism"] for value in EXPECTED_CONFIGS.values()}
    ARTIFACTS = artifacts_for_scenario(SCENARIO)
    output_path = args.output or (DEBUG_DIR / f"pipeline_integrity_{SCENARIO}.txt")
    lines: list[str] = [
        f"Pipeline integrity report: {args.scenario}",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Scope:",
        "- This report checks generated artifacts for the requested AI-MRCE degraded-link cohort.",
        "- It is diagnostic only and does not modify simulation or analysis semantics.",
        "",
        "Artifacts:",
    ]

    for name, path in ARTIFACTS.items():
        lines.append(artifact_line(name, path))
    lines.extend(["", "Runtime deployment artifacts:"])
    for name, path in RUNTIME_ARTIFACTS.items():
        lines.append(artifact_line(name, path))

    errors: list[str] = []
    warnings: list[str] = []
    if not ARTIFACTS["outcome_summary"].exists():
        errors.append(f"Outcome summary is missing: {ARTIFACTS['outcome_summary']}")

    outcome_rows = read_csv_rows(ARTIFACTS["outcome_summary"])
    comparison_rows = read_csv_rows(ARTIFACTS["comparison_summary"])
    headline_rows = read_csv_rows(ARTIFACTS["headline_summary_csv"])
    event_rows = read_csv_rows(ARTIFACTS["event_summary"])

    lines.extend(["", "Outcome summary rows:"])
    lines.append(f"Observed rows: {len(outcome_rows)}")
    outcome_by_config: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_config_runs: set[tuple[str, str]] = set()
    for row in outcome_rows:
        config_name = row.get("config_name", "")
        run_number = row.get("run_number", "")
        key = (config_name, run_number)
        if key in seen_config_runs:
            errors.append(f"Duplicate outcome row for config={config_name} run={run_number}.")
        seen_config_runs.add(key)
        if config_name not in EXPECTED_CONFIGS:
            warnings.append(f"Unexpected outcome config observed: {config_name or '<blank>'}.")
        outcome_by_config[config_name].append(row)

    for config_name, expected in EXPECTED_CONFIGS.items():
        rows = outcome_by_config.get(config_name, [])
        run_numbers = sorted({row.get("run_number", "") for row in rows})
        mechanisms = sorted({row.get("protection_mode", "") for row in rows})
        runtime_models = sorted({row.get("runtime_model_type", "") for row in rows if row.get("runtime_model_type", "")})
        loaded_values = sorted({row.get("runtime_model_loaded", "") for row in rows if row.get("runtime_model_loaded", "")})
        fallback_values = sorted({row.get("runtime_model_fallback_used", "") for row in rows if row.get("runtime_model_fallback_used", "")})
        lines.append(
            f"- {config_name}: rows={len(rows)}, runs={','.join(run_numbers) or 'none'}, "
            f"mechanism={';'.join(mechanisms) or 'none'}, runtime={';'.join(runtime_models) or 'n/a'}, "
            f"loaded={';'.join(loaded_values) or 'n/a'}, fallback={';'.join(fallback_values) or 'n/a'}"
        )
        if not rows:
            errors.append(f"Missing outcome rows for {config_name}.")
            continue
        if any(row.get("protection_mode", "") != expected["mechanism"] for row in rows):
            errors.append(f"Mechanism mismatch for {config_name}; expected {expected['mechanism']}.")
        expected_runtime = expected["runtime_model_type"]
        if expected_runtime and any(row.get("runtime_model_type", "") != expected_runtime for row in rows):
            errors.append(f"Runtime model mismatch for {config_name}; expected {expected_runtime}.")
        if any(row.get("runtime_model_fallback_used", "") not in {"", "0"} for row in rows):
            errors.append(f"Runtime model fallback was used in {config_name}; learned-model loading should be fail-fast.")
        if len(run_numbers) < 5:
            warnings.append(f"{config_name} has {len(run_numbers)} observed run(s); full dissertation cohort expects 5.")

    observed_mechanisms = {
        row.get("mechanism_family", "") or row.get("mechanism_family_normalized", "")
        for row in comparison_rows
        if row.get("mechanism_family", "") or row.get("mechanism_family_normalized", "")
    }
    if not observed_mechanisms:
        observed_mechanisms = {row.get("mechanism_family", "") for row in headline_rows if row.get("mechanism_family", "")}
    missing_mechanisms = sorted(EXPECTED_MECHANISMS - observed_mechanisms)
    if missing_mechanisms:
        warnings.append(f"Comparison/headline mechanism coverage could not confirm: {', '.join(missing_mechanisms)}")

    lines.extend(["", "Raw result triplets:"])
    triplets = count_result_triplets()
    required_suffixes = {".sca", ".vec", ".vci"}
    raw_run_sets: dict[str, set[int]] = {}
    for config_name, expected in EXPECTED_CONFIGS.items():
        cohort_name = expected["cohort_config"]
        runs = triplets.get(cohort_name, {})
        observed_runs = sorted(runs)
        raw_run_sets[cohort_name] = set(observed_runs)
        lines.append(f"- {cohort_name}: runs={','.join(map(str, observed_runs)) or 'none'}")
        for run_number, suffixes in sorted(runs.items()):
            missing = required_suffixes - suffixes
            if missing:
                warnings.append(f"{cohort_name} run {run_number} is missing result files: {', '.join(sorted(missing))}")
        if len(observed_runs) < 5:
            warnings.append(f"{cohort_name} has {len(observed_runs)} raw result run(s); full cohort expects 5.")

    outcome_run_sets = {
        config_name: {row.get("run_number", "") for row in rows}
        for config_name, rows in outcome_by_config.items()
        if config_name in EXPECTED_CONFIGS
    }
    full_outcome = (
        len(outcome_run_sets) == len(EXPECTED_CONFIGS)
        and all(run_set == {"0", "1", "2", "3", "4"} for run_set in outcome_run_sets.values())
    )
    run0_only = (
        len(outcome_run_sets) == len(EXPECTED_CONFIGS)
        and all(run_set == {"0"} for run_set in outcome_run_sets.values())
    )
    raw_full = (
        len(raw_run_sets) == len(EXPECTED_CONFIGS)
        and all(run_set == {0, 1, 2, 3, 4} for run_set in raw_run_sets.values())
    )
    raw_run0_only = (
        len(raw_run_sets) == len(EXPECTED_CONFIGS)
        and all(run_set == {0} for run_set in raw_run_sets.values())
    )
    lines.extend(["", "Workspace mode:"])
    if full_outcome and raw_full:
        lines.append("- FULL_PUBLICATION_COHORT: all expected mechanisms have runs 0,1,2,3,4.")
    elif run0_only and raw_run0_only:
        lines.append("- RUN0_DEVELOPMENT_MODE: all expected mechanisms have run 0 only.")
        warnings.append("Workspace is in run-0 development mode; full dissertation publication cohort expects runs 0,1,2,3,4.")
    else:
        lines.append("- PARTIAL_OR_MIXED_OUTPUTS: observed run coverage is neither full five-run nor clean run-0-only.")
        warnings.append("Workspace has partial or mixed run coverage; regenerate the intended cohort before publication use.")

    raw_sources = sorted(
        path
        for path in RESULTS_DIR.glob("*.*")
        if path.suffix.lower() in {".sca", ".vec", ".vci"}
    )
    freshness_checks = [
        (
            "dataset_vs_raw_results",
            ARTIFACTS["dataset"],
            raw_sources,
            f"py -3 analysis\\build_dataset.py --scenario {SCENARIO}",
        ),
        (
            "dataset_report_vs_dataset",
            ARTIFACTS["dataset_report"],
            [ARTIFACTS["dataset"]],
            f"py -3 analysis\\dataset_report.py --scenario {SCENARIO}",
        ),
        (
            "outcome_summary_vs_dataset",
            ARTIFACTS["outcome_summary"],
            [ARTIFACTS["dataset"]],
            f"py -3 analysis\\dataset_report.py --scenario {SCENARIO}",
        ),
        (
            "comparison_vs_outcome_summary",
            ARTIFACTS["comparison_report"],
            [ARTIFACTS["outcome_summary"]],
            "py -3 analysis\\compare_outcomes.py --inputs "
            f"analysis\\output\\outcomes\\{SCENARIO}_outcome_summary.csv "
            f"--output-prefix analysis\\output\\outcomes\\{SCENARIO}",
        ),
        (
            "headline_vs_outcome_summary",
            ARTIFACTS["headline_summary_csv"],
            [ARTIFACTS["outcome_summary"]],
            "py -3 analysis\\compare_outcomes.py --inputs "
            f"analysis\\output\\outcomes\\{SCENARIO}_outcome_summary.csv "
            f"--output-prefix analysis\\output\\outcomes\\{SCENARIO}",
        ),
        (
            "risk_trace_vs_raw_and_outcome",
            ARTIFACTS["risk_trace"],
            raw_sources + [ARTIFACTS["outcome_summary"]],
            f"py -3 analysis\\extract_aimrce_risk_trace.py --scenario {SCENARIO} --runs 0 --start 78 --end 86",
        ),
        (
            "event_summary_vs_raw_and_outcome",
            ARTIFACTS["event_summary"],
            raw_sources + [ARTIFACTS["outcome_summary"]],
            f"py -3 analysis\\extract_aimrce_risk_trace.py --scenario {SCENARIO} --runs 0 --start 78 --end 86",
        ),
    ]
    lines.extend(["", "Freshness checks:"])
    for name, generated, sources, command in freshness_checks:
        warning = stale_warning(generated, sources, command)
        if warning:
            warnings.append(warning)
            lines.append(f"- [WARN] {name}: {warning}")
        else:
            lines.append(f"- [OK] {name}")

    nested_output = PROJECT_ROOT / "analysis" / "analysis" / "output"
    lines.extend(["", "Path sanity checks:"])
    if nested_output.exists():
        warnings.append(f"Unexpected nested analysis output directory exists: {nested_output}")
        lines.append(f"- [WARN] unexpected nested output directory exists: {nested_output}")
    else:
        lines.append(f"- [OK] no accidental nested analysis output directory at {nested_output}")

    lines.extend(["", "Trace/event summary:"])
    event_mechanisms = Counter(row.get("mechanism", "") for row in event_rows)
    lines.append(f"Event summary rows: {len(event_rows)}")
    for mechanism, count in sorted(event_mechanisms.items()):
        lines.append(f"- {mechanism or 'blank'}: {count}")

    lines.extend(["", "Warnings:"])
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("- none")

    lines.extend(["", "Errors:"])
    lines.extend(f"- {error}" for error in errors) if errors else lines.append("- none")

    status = "FAIL" if errors else "OK_WITH_WARNINGS" if warnings else "OK"
    lines.extend(["", f"Overall status: {status}"])

    atomic_write_text(output_path, "\n".join(lines) + "\n")
    print(f"Wrote pipeline integrity report to {output_path}")
    print(f"Overall status: {status}")

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
