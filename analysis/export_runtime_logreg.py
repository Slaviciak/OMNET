#!/usr/bin/env python3
"""
Export a small runtime logistic-regression model for the first AI-MRCE prototype.

Assumptions:
- This helper is for the first regionalbackbone AI-MRCE runtime prototype.
- It trains a binary logistic model for the scenario-phase "protect" state and
  excludes "failed" rows so the exported score targets pre-failure protection
  rather than post-failure behavior.
- The exported artifact is a simple CSV with explicit feature names, imputation
  values, standardization parameters, coefficients, intercept, and threshold.
- This script is for runtime model preparation only; use
  analysis/train_risk_model.py for methodological evaluation.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path

from train_risk_model import (
    OUTPUT_DIR,
    SUPPORTED_SCENARIOS,
    collect_training_rows,
    parse_float,
    require_sklearn,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "simulations" / "regionalbackbone" / "aimrce_runtime_logreg.csv"
DEFAULT_SCENARIOS = ["regionalbackbone"]
DEFAULT_CONFIGS = ["RegionalBackboneCongestionDegradation"]
RUNTIME_FEATURES = [
    "bottleneck_queue_length_last_pk",
    "receiver_app0_e2e_delay_mean_s",
    "receiver_app0_throughput_mean_bps",
    "receiver_app0_packet_count",
]
# Intentionally compact runtime feature subset for the first AI-MRCE prototype.
# These are deployment-oriented inputs chosen for interpretability and for
# availability inside the current OMNeT++ runtime controller.
SUPPORTED_RISK_LABELS = {"safe", "warning", "protect"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a runtime logistic-regression model for AI-MRCE.")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=list(DEFAULT_SCENARIOS),
        choices=SUPPORTED_SCENARIOS,
        help="Scenario datasets to load. Defaults to regionalbackbone only.",
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        default=list(DEFAULT_CONFIGS),
        help="Config names to include in the runtime model fit. Defaults to RegionalBackboneCongestionDegradation.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory containing <scenario>_dataset.csv files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output CSV path for the runtime model artifact.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.60,
        help="Decision threshold to embed in the exported runtime model.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed for logistic-regression initialization.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip selected scenario datasets that are not present instead of failing.",
    )
    parser.add_argument(
        "--include-regional-reactive",
        action="store_true",
        help="Pass through to the shared dataset loader if future experiments need it.",
    )
    return parser.parse_args()


def filter_runtime_rows(rows: list[dict[str, object]], configs: list[str]) -> list[dict[str, object]]:
    """Keep only rows that are valid for the first runtime deployment artifact."""
    selected_configs = set(configs)
    filtered_rows = []
    for row in rows:
        if row.get("config_name") not in selected_configs:
            continue
        if row.get("risk_label") not in SUPPORTED_RISK_LABELS:
            continue
        filtered_rows.append(row)
    return filtered_rows


def require_runtime_features(rows: list[dict[str, object]]) -> None:
    """Fail early if the selected dataset rows cannot support runtime export."""
    if not rows:
        raise SystemExit("No rows remained for runtime export after config and label filtering.")

    missing_features = []
    for feature in RUNTIME_FEATURES:
        values = [parse_float(row.get(feature)) for row in rows]
        if all(math.isnan(value) for value in values):
            missing_features.append(feature)
    if missing_features:
        raise SystemExit(
            "The selected rows do not provide usable values for the required runtime features: "
            + ", ".join(missing_features)
        )


def feature_matrix(rows: list[dict[str, object]]) -> list[list[float]]:
    return [[parse_float(row.get(feature)) for feature in RUNTIME_FEATURES] for row in rows]


def write_runtime_model(
    output_path: Path,
    threshold: float,
    intercept: float,
    coefficients: list[float],
    means: list[float],
    scales: list[float],
    imputes: list[float],
    metadata_rows: list[tuple[str, str]],
) -> None:
    """Write the explicit CSV artifact consumed by the C++ runtime prototype."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_type", "name", "value", "coefficient", "mean", "scale", "impute_value"])
        writer.writerow(["meta", "format", "aimrce_logreg_v1", "", "", "", ""])
        writer.writerow(["meta", "decision_mode", "logistic_regression_binary", "", "", "", ""])
        writer.writerow(["meta", "positive_label", "protect", "", "", "", ""])
        writer.writerow(["meta", "threshold", f"{threshold:.12g}", "", "", "", ""])
        writer.writerow(["meta", "intercept", f"{intercept:.12g}", "", "", "", ""])
        for name, value in metadata_rows:
            writer.writerow(["meta", name, value, "", "", "", ""])
        for feature, coefficient, mean, scale, impute_value in zip(RUNTIME_FEATURES, coefficients, means, scales, imputes):
            writer.writerow([
                "feature",
                feature,
                "",
                f"{coefficient:.12g}",
                f"{mean:.12g}",
                f"{scale:.12g}",
                f"{impute_value:.12g}",
            ])


def main() -> None:
    args = parse_args()
    if args.threshold <= 0 or args.threshold >= 1:
        raise SystemExit("--threshold must be between 0 and 1.")

    rows, metadata = collect_training_rows(
        scenarios=args.scenarios,
        input_dir=args.input_dir,
        allow_missing=args.allow_missing,
        include_regional_reactive=args.include_regional_reactive,
    )
    runtime_rows = filter_runtime_rows(rows, args.configs)
    require_runtime_features(runtime_rows)

    x = feature_matrix(runtime_rows)
    y = [1 if row["risk_label"] == "protect" else 0 for row in runtime_rows]
    label_counts = Counter(row["risk_label"] for row in runtime_rows)
    class_counts = Counter(y)
    if len(class_counts) < 2:
        raise SystemExit("Runtime export needs both positive and negative samples after filtering.")

    sklearn = require_sklearn()
    # This fit exists only to produce a compact deployment artifact. The main
    # methodological evidence remains in train_risk_model.py and its stronger
    # generalization-oriented evaluation modes.
    pipeline = sklearn["Pipeline"]([
        ("imputer", sklearn["SimpleImputer"](strategy="median")),
        ("scaler", sklearn["StandardScaler"]()),
        ("classifier", sklearn["LogisticRegression"](
            max_iter=1000,
            class_weight="balanced",
            random_state=args.random_seed,
        )),
    ])
    pipeline.fit(x, y)

    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    classifier = pipeline.named_steps["classifier"]

    metadata_rows = [
        ("selected_scenarios", " ".join(args.scenarios)),
        ("selected_configs", " ".join(args.configs)),
        ("training_rows", str(len(runtime_rows))),
        ("risk_label_counts", "; ".join(f"{key}={value}" for key, value in sorted(label_counts.items()))),
        ("source_files", "; ".join(f"{scenario}={path}" for scenario, path in sorted(metadata["input_files"].items()))),
        ("note", "Binary runtime deployment artifact trained for protect vs safe/warning using scenario-phase supervision."),
    ]

    write_runtime_model(
        output_path=args.output,
        threshold=args.threshold,
        intercept=float(classifier.intercept_[0]),
        coefficients=[float(value) for value in classifier.coef_[0]],
        means=[float(value) for value in scaler.mean_],
        scales=[float(value) for value in scaler.scale_],
        imputes=[float(value) for value in imputer.statistics_],
        metadata_rows=metadata_rows,
    )

    print(f"Wrote runtime logistic model to {args.output}")
    print(f"Rows used: {len(runtime_rows)}")
    print(f"Risk label counts: {dict(label_counts)}")
    print(f"Features: {', '.join(RUNTIME_FEATURES)}")


if __name__ == "__main__":
    main()
