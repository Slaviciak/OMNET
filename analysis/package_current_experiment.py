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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = PROJECT_ROOT / "analysis"
OUTPUT_DIR = ANALYSIS_DIR / "output"

DEFAULT_SCENARIO = "regionalbackbone_failure_detection_degraded_link_model_family"

RAW_RESULT_SUFFIXES = {".vec", ".vci", ".sca", ".elog", ".anf", ".pcap", ".pcapng"}

EXPECTED_MECHANISMS = [
    "ospf_only",
    "bfd_like_frr",
    "aimrce_rule_based_frr",
    "aimrce_logistic_regression_frr",
    "aimrce_linear_svm_frr",
    "aimrce_shallow_tree_frr",
    "hybrid_bfd_like_aimrce_frr",
]


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
    reports = project_path("analysis", "output", "reports")
    debug = project_path("analysis", "output", "debug")
    runtime = project_path("simulations", "regionalbackbone")

    return [
        CopySpec(
            outcomes / f"{scenario}_headline_summary.csv",
            package_dir / "summaries" / "headline_summary.csv",
            "Degraded-link headline summary table",
        ),
        CopySpec(
            outcomes / f"{scenario}_headline_summary.txt",
            package_dir / "summaries" / "headline_summary.txt",
            "Human-readable headline summary",
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
    ]


def read_outcome_rows(outcome_summary_path: Path) -> list[dict[str, str]]:
    if not outcome_summary_path.exists():
        return []
    with outcome_summary_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def detect_workspace_mode(outcome_rows: list[dict[str, str]]) -> tuple[str, list[str], dict[str, list[int]]]:
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
    return f"""# Methodology Summary

Scenario: `{scenario}`

Current package mode: **{mode}**

AI-MRCE is a telemetry-driven proactive controller in the regional OMNeT++/INET
OSPF backbone. It evaluates current telemetry with rule-based and compact
runtime ML policies, then activates project-local FRR-like static repair routes
when risk remains positive for the configured decision streak.

The active model-family cohort compares:

- `ospf_only`
- `bfd_like_frr`
- `aimrce_rule_based_frr`
- `aimrce_logistic_regression_frr`
- `aimrce_linear_svm_frr`
- `aimrce_shallow_tree_frr`
- `hybrid_bfd_like_aimrce_frr`

All mechanisms use the same regional topology, traffic, progressive
degraded-link/brownout profile, hard-failure time, and repair-route semantics.
AI-MRCE model-family rows differ only by decision policy/runtime model.

Most useful files for review are in `summaries/`, `integrity/`, and `traces/`.
Raw OMNeT++ `.vec`, `.vci`, `.sca`, `.elog`, packet captures, and build outputs
are intentionally not included because they are large and reproducible.
"""


def build_limitations_text() -> str:
    return """# Limitations And Non-Claims

- AI-MRCE is evaluated in a scenario-conditioned degraded-link/brownout profile.
- The current result is not a universal failure-prediction claim.
- BFD-like detection is project-local and BFD-inspired; it is not RFC-compliant BFD.
- FRR-like repair routes are project-local static `/32` routes; they are not standards-compliant LFA, TI-LFA, RSVP-TE FRR, or OSPF FRR.
- The severe packet-error-rate profile is a stress/brownout scenario, not a calibrated field trace.
- Reordering and activation-to-failure transition costs remain visible and must be reported.
- Packet sequence gaps are receiver-observed operational diagnostics, not direct proof of packet loss without the unobserved/reordered distinction.
- Do not generalize these results to all topologies, traffic mixes, failure classes, or production router implementations.
"""


def build_reproduce_bat(scenario: str) -> str:
    return f"""@echo off
setlocal
cd /d "%~dp0\\..\\..\\..\\..\\.."

cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --clean --yes --skip-runtime-export --skip-build
py -3 analysis\\build_dataset.py --scenario {scenario}
py -3 analysis\\dataset_report.py --scenario {scenario}
py -3 analysis\\compare_outcomes.py --inputs analysis\\output\\outcomes\\{scenario}_outcome_summary.csv --output-prefix analysis\\output\\outcomes\\{scenario}
py -3 analysis\\extract_aimrce_risk_trace.py --scenario {scenario} --runs 0 --start 78 --end 86
cmd /c run_analysis.bat pipeline-integrity --scenario {scenario}
cmd /c run_analysis.bat package-current-experiment --scenario {scenario}
"""


def build_useful_commands(scenario: str) -> str:
    return f"""Useful current-experiment commands
==================================

Package compact current outputs:
cmd /c run_analysis.bat package-current-experiment --scenario {scenario}

Run full five-run publication cohort:
cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --clean --yes --skip-runtime-export --skip-build

Run run-0 smoke/regression mode:
cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --runs 0 --clean --yes --skip-runtime-export --skip-build

Regenerate dataset/report/comparison from existing raw results:
py -3 analysis\\build_dataset.py --scenario {scenario}
py -3 analysis\\dataset_report.py --scenario {scenario}
py -3 analysis\\compare_outcomes.py --inputs analysis\\output\\outcomes\\{scenario}_outcome_summary.csv --output-prefix analysis\\output\\outcomes\\{scenario}

Regenerate graph-ready risk trace:
py -3 analysis\\extract_aimrce_risk_trace.py --scenario {scenario} --runs 0 --start 78 --end 86

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

    return f"""# Current Experiment Package

This folder is a compact generated package for the active dissertation
experiment. It copies small, useful outputs and context from the working tree so
they can be sent for review without searching through `analysis/output/`.

It is **not** a full archive and does **not** include raw OMNeT++ result files.

## Scenario

`{scenario}`

Workspace mode: **{mode}**

Pipeline integrity status: **{pipeline_status}**

## Mechanism Families

{os.linesep.join(mechanism_lines)}

## Most Useful Files To Send For Review

- `summaries/headline_summary.csv`
- `summaries/headline_summary.txt`
- `summaries/outcome_summary.csv`
- `summaries/comparison_report.txt`
- `integrity/pipeline_integrity_report.txt`
- `traces/risk_trace_run0.csv`
- `traces/model_action_events_run0.csv`
- `methodology/limitations_and_nonclaims.md`

## Not Included

The package intentionally excludes large or reproducible artifacts:

- raw `.vec`, `.vci`, `.sca`, `.elog`, `.anf`, `.pcap`, and `.pcapng` files;
- OMNeT++ build outputs;
- full `results/` folders;
- analysis virtual environments and caches.

## Copied Files

{os.linesep.join(copied_lines) if copied_lines else "- none"}

## Warnings / Missing Optional Files

{os.linesep.join(warning_lines)}

## Regeneration Commands

Run from the project root:

```bat
cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --clean --yes --skip-runtime-export --skip-build
py -3 analysis\\build_dataset.py --scenario {scenario}
py -3 analysis\\dataset_report.py --scenario {scenario}
py -3 analysis\\compare_outcomes.py --inputs analysis\\output\\outcomes\\{scenario}_outcome_summary.csv --output-prefix analysis\\output\\outcomes\\{scenario}
py -3 analysis\\extract_aimrce_risk_trace.py --scenario {scenario} --runs 0 --start 78 --end 86
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


def main() -> int:
    args = parse_args()
    scenario = args.scenario
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    package_dir = output_root / scenario
    package_dir.mkdir(parents=True, exist_ok=True)

    specs = build_copy_specs(scenario, package_dir)
    copied, warnings = copy_artifacts(specs)

    outcome_summary = OUTPUT_DIR / "outcomes" / f"{scenario}_outcome_summary.csv"
    outcome_rows = read_outcome_rows(outcome_summary)
    mode, mode_warnings, runs_by_mechanism = detect_workspace_mode(outcome_rows)
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
