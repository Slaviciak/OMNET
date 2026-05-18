#!/usr/bin/env python3
"""
Dry-run-first cleanup helper for generated dissertation artifacts.

This script only targets generated project-local outputs. It never deletes
source files, simulator configs, runtime deployment CSV examples, or INET/OSPF
files. Actual deletion requires both --clean and --yes.
"""

from __future__ import annotations

import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
RESULTS_ROOT = PROJECT_ROOT / "results"

ANALYSIS_OUTPUT_DIRS = (
    ANALYSIS_OUTPUT_ROOT / "datasets",
    ANALYSIS_OUTPUT_ROOT / "reports",
    ANALYSIS_OUTPUT_ROOT / "outcomes",
    ANALYSIS_OUTPUT_ROOT / "debug",
    ANALYSIS_OUTPUT_ROOT / "audit",
    ANALYSIS_OUTPUT_ROOT / "experiment_logs",
    ANALYSIS_OUTPUT_ROOT / "training",
)

SCENARIO_RESULT_DIRS = {
    "regionalbackbone": RESULTS_ROOT / "regionalbackbone" / "eval",
    "regionalbackbone_congestion_protection": RESULTS_ROOT / "regionalbackbone" / "congestion_protection_cohort",
    "regionalbackbone_mixed_traffic_protection": RESULTS_ROOT / "regionalbackbone" / "mixed_traffic_protection_cohort",
    "regionalbackbone_failure_detection_comparison": RESULTS_ROOT / "regionalbackbone" / "failure_detection_comparison",
    "regionalbackbone_failure_detection_comparison_ms_traffic": RESULTS_ROOT
    / "regionalbackbone"
    / "failure_detection_comparison_ms_traffic",
    "regionalbackbone_failure_detection_degraded_link": RESULTS_ROOT / "regionalbackbone" / "failure_detection_degraded_link",
    "regionalbackbone_failure_detection_degraded_link_model_family": RESULTS_ROOT
    / "regionalbackbone"
    / "failure_detection_degraded_link_model_family",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or clean generated analysis/result artifacts without touching source files."
    )
    parser.add_argument(
        "--include-results",
        action="store_true",
        help="Also target the known generated results directory for --scenario.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_RESULT_DIRS),
        help="Known scenario result directory to include when --include-results is set.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Request deletion. Without --yes this remains a dry run.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete targeted files when used together with --clean.",
    )
    return parser.parse_args()


def resolve_inside(path: Path, allowed_roots: tuple[Path, ...]) -> Path:
    resolved = path.resolve()
    for root in allowed_roots:
        root_resolved = root.resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return resolved
    allowed = ", ".join(str(root.resolve()) for root in allowed_roots)
    raise SystemExit(f"Refusing to operate outside generated roots: {resolved}; allowed roots: {allowed}")


def iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def collect_targets(args: argparse.Namespace) -> list[Path]:
    roots: list[Path] = []
    for path in ANALYSIS_OUTPUT_DIRS:
        roots.append(resolve_inside(path, (ANALYSIS_OUTPUT_ROOT,)))

    if args.include_results:
        if not args.scenario:
            raise SystemExit("--include-results requires --scenario so cleanup stays explicit.")
        roots.append(resolve_inside(SCENARIO_RESULT_DIRS[args.scenario], (RESULTS_ROOT,)))

    targets: list[Path] = []
    for root in roots:
        targets.extend(iter_files(root))
    return sorted(set(targets))


def targeted_roots(args: argparse.Namespace) -> list[Path]:
    roots = [resolve_inside(path, (ANALYSIS_OUTPUT_ROOT,)) for path in ANALYSIS_OUTPUT_DIRS]
    if args.include_results and args.scenario:
        roots.append(resolve_inside(SCENARIO_RESULT_DIRS[args.scenario], (RESULTS_ROOT,)))
    return roots


def main() -> None:
    args = parse_args()
    targets = collect_targets(args)
    total_bytes = sum(path.stat().st_size for path in targets if path.exists())
    actually_delete = args.clean and args.yes

    mode = "DELETE" if actually_delete else "DRY RUN"
    print(f"Mode: {mode}")
    print("Scope: generated artifacts only. Source, config, docs, INET/OSPF internals, and runtime model CSV examples are not targeted.")
    print("Target roots:")
    for root in targeted_roots(args):
        print(f"  {root}")
    print(f"Generated files targeted: {len(targets)}")
    print(f"Approximate bytes targeted: {total_bytes}")
    if args.include_results:
        print(f"Included results scenario: {args.scenario}")
    print("Deletion requires both --clean and --yes; otherwise this command is a preview.")
    print("")

    for path in targets:
        print(path)

    if args.clean and not args.yes:
        print("")
        print("No files deleted. Re-run with --clean --yes to delete the listed generated files.")
        return

    if not actually_delete:
        print("")
        print("No files deleted. This helper is dry-run by default.")
        return

    for path in targets:
        path.unlink()
    print("")
    print(f"Deleted {len(targets)} generated file(s). Empty directories were left in place intentionally.")


if __name__ == "__main__":
    main()
