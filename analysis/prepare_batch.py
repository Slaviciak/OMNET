#!/usr/bin/env python3
"""
Prepare a clean evaluation batch for a supported data-generation scenario.

Assumptions:
- This helper only manages local dissertation project outputs.
- It never touches INET, debug outputs, source files, or analysis outputs.
- It only targets results/<scenario>/eval/ for the selected scenario.
- Cleanup is dry-run by default; files are deleted only with --clean --yes.
- The actual OMNeT++ simulation runs are still launched manually from the IDE
  or command line using the listed config names.
"""

from __future__ import annotations

import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCENARIO_PRESETS = {
    "linkdegradation": {
        "description": "Synthetic link degradation data-generation batch",
        "eval_dir": PROJECT_ROOT / "results" / "linkdegradation" / "eval",
        "debug_dir": PROJECT_ROOT / "results" / "linkdegradation" / "debug",
        "configs": ["MildLinear", "StrongLinear", "UnstableLinear", "StagedRealistic"],
        "dataset_command": "run_analysis.bat build-dataset --scenario linkdegradation",
        "report_command": "run_analysis.bat dataset-report --scenario linkdegradation",
    },
    "congestiondegradation": {
        "description": "Traffic-driven congestion data-generation batch",
        "eval_dir": PROJECT_ROOT / "results" / "congestiondegradation" / "eval",
        "debug_dir": PROJECT_ROOT / "results" / "congestiondegradation" / "debug",
        "configs": ["CongestionDegradation", "CongestionDegradationMild"],
        "dataset_command": "run_analysis.bat build-dataset --scenario congestiondegradation",
        "report_command": "run_analysis.bat dataset-report --scenario congestiondegradation",
    },
    "regionalbackbone": {
        "description": "Medium-scale regional backbone baseline, reactive failure, controlled degradation, and congestion batch",
        "eval_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "eval",
        "debug_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "debug",
        "configs": [
            "RegionalBackboneBaseline",
            "RegionalBackboneReactiveFailure",
            "RegionalBackboneControlledDegradation",
            "RegionalBackboneCongestionDegradation",
        ],
        "dataset_command": "run_analysis.bat build-dataset --scenario regionalbackbone",
        "report_command": "run_analysis.bat dataset-report --scenario regionalbackbone",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a clean scenario eval batch.")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=sorted(SCENARIO_PRESETS),
        help="Scenario batch preset to prepare.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean files from the scenario eval directory. Without --yes this is a dry run.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete eval files when used together with --clean.",
    )
    return parser.parse_args()


def ensure_inside_project(path: Path) -> Path:
    resolved = path.resolve()
    project_root = PROJECT_ROOT.resolve()
    if project_root != resolved and project_root not in resolved.parents:
        raise SystemExit(f"Refusing to operate outside the project: {resolved}")
    return resolved


def list_eval_files(eval_dir: Path) -> list[Path]:
    if not eval_dir.exists():
        return []
    return sorted(path for path in eval_dir.iterdir() if path.is_file())


def list_eval_dirs(eval_dir: Path) -> list[Path]:
    if not eval_dir.exists():
        return []
    return sorted(path for path in eval_dir.iterdir() if path.is_dir())


def print_batch_summary(scenario: str, preset: dict[str, object], eval_files: list[Path], eval_dirs: list[Path]) -> None:
    print(f"Scenario: {scenario}")
    print(f"Purpose: {preset['description']}")
    print(f"Eval directory: {preset['eval_dir']}")
    print(f"Debug directory: {preset['debug_dir']} (not modified)")
    print("")
    print("Run these configs for a complete eval batch:")
    for config in preset["configs"]:
        print(f"  - {config}")
    print("")
    print(f"Current eval files: {len(eval_files)}")
    for path in eval_files:
        print(f"  - {path.name}")
    if eval_dirs:
        print("")
        print("Eval subdirectories were found and will not be removed by this helper:")
        for path in eval_dirs:
            print(f"  - {path.name}")
    print("")
    print("After running the configs, build outputs with:")
    print(f"  {preset['dataset_command']}")
    print(f"  {preset['report_command']}")


def clean_eval_files(eval_files: list[Path], actually_delete: bool) -> None:
    if not eval_files:
        print("No eval files to clean.")
        return

    if not actually_delete:
        print("Dry run only. Re-run with --clean --yes to delete these eval files.")
        return

    for path in eval_files:
        path.unlink()
    print(f"Deleted {len(eval_files)} eval file(s).")


def main() -> None:
    args = parse_args()
    preset = SCENARIO_PRESETS[args.scenario]

    eval_dir = ensure_inside_project(preset["eval_dir"])
    ensure_inside_project(preset["debug_dir"])
    eval_dir.mkdir(parents=True, exist_ok=True)

    eval_files = list_eval_files(eval_dir)
    eval_dirs = list_eval_dirs(eval_dir)
    print_batch_summary(args.scenario, preset, eval_files, eval_dirs)

    if args.clean:
        print("")
        clean_eval_files(eval_files, args.yes)


if __name__ == "__main__":
    main()
