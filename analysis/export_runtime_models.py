#!/usr/bin/env python3
"""
Export a small family of runtime AI-MRCE deployment artifacts.

Assumptions:
- This helper prepares compact project-local deployment artifacts for the
  regionalbackbone runtime prototype family only.
- It trains binary runtime candidates for the scenario-phase "protect" state
  and excludes "failed" rows so the exported scores target pre-failure
  protective action rather than post-failure behavior.
- The exported files are deployment artifacts, not substitutes for the richer
  methodological evaluation performed by analysis/train_risk_model.py.
- Runtime features remain intentionally compact and observable at runtime:
  queue occupancy plus probe-flow delay, throughput, and packet continuity.
- The additional learned candidates are chosen for interpretability and simple
  auditable export rather than novelty or black-box complexity.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path
from typing import Any

from train_risk_model import (
    DATASETS_DIR,
    SUPPORTED_SCENARIOS,
    collect_training_rows,
    parse_float,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "simulations" / "regionalbackbone"
DEFAULT_MANIFEST_OUTPUT = DEFAULT_OUTPUT_DIR / "aimrce_runtime_manifest.csv"
DEFAULT_SCENARIOS = ["regionalbackbone"]
DEFAULT_CONFIGS = ["RegionalBackboneCongestionDegradation"]
MODEL_FAMILIES = ("logistic_regression", "linear_svm", "shallow_tree")
DEFAULT_OUTPUT_FILENAMES = {
    "logistic_regression": "aimrce_runtime_logreg.csv",
    "linear_svm": "aimrce_runtime_linsvm.csv",
    "shallow_tree": "aimrce_runtime_shallow_tree.csv",
}
RUNTIME_FEATURES = [
    "bottleneck_queue_length_last_pk",
    "receiver_app0_e2e_delay_mean_s",
    "receiver_app0_throughput_mean_bps",
    "receiver_app0_packet_count",
]
# Intentionally compact runtime feature subset for the current AI-MRCE runtime
# family. These inputs are chosen for interpretability and for availability
# inside the existing OMNeT++ runtime controller without hidden oracle signals.
SUPPORTED_RISK_LABELS = {"safe", "warning", "protect"}
MODEL_DECISION_MODES = {
    "logistic_regression": "logisticRegression",
    "linear_svm": "linearSvm",
    "shallow_tree": "shallowTree",
}


def require_runtime_sklearn() -> dict[str, Any]:
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import LinearSVC
        from sklearn.tree import DecisionTreeClassifier
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "scikit-learn"
        raise SystemExit(
            "Missing Python ML dependency: "
            f"{missing_name}. Install the analysis requirements in the project environment before exporting runtime models, "
            "for example: run_analysis.bat install-ml-deps"
        ) from exc

    return {
        "SimpleImputer": SimpleImputer,
        "LogisticRegression": LogisticRegression,
        "Pipeline": Pipeline,
        "StandardScaler": StandardScaler,
        "LinearSVC": LinearSVC,
        "DecisionTreeClassifier": DecisionTreeClassifier,
    }


def parse_args(
    argv: list[str] | None = None,
    default_model_families: list[str] | None = None,
    default_manifest_output: Path | None = DEFAULT_MANIFEST_OUTPUT,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export runtime AI-MRCE deployment artifacts.")
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
        help="Config names to include in the runtime-model fit. Defaults to RegionalBackboneCongestionDegradation.",
    )
    parser.add_argument(
        "--model-families",
        nargs="+",
        default=list(default_model_families or MODEL_FAMILIES),
        choices=MODEL_FAMILIES,
        help=(
            "Runtime candidate families to export. Defaults to all supported "
            "families unless a compatibility wrapper requests a narrower subset."
        ),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DATASETS_DIR,
        help="Directory containing <scenario>_dataset.csv files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the runtime artifact files will be written.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Explicit output file path. This is supported only when exporting a "
            "single model family, which preserves backward compatibility for the "
            "older logistic-only wrapper."
        ),
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=default_manifest_output,
        help="Optional CSV path for a runtime-export manifest. Set by default for multi-model exports.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.60,
        help="Decision threshold for probability-like runtime scores.",
    )
    parser.add_argument(
        "--tree-max-depth",
        type=int,
        default=3,
        help="Maximum depth for the shallow tree runtime candidate.",
    )
    parser.add_argument(
        "--tree-min-samples-leaf",
        type=int,
        default=10,
        help="Minimum leaf size for the shallow tree runtime candidate.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed used for model initialization.",
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
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.threshold <= 0 or args.threshold >= 1:
        raise SystemExit("--threshold must be between 0 and 1.")
    if args.tree_max_depth <= 0:
        raise SystemExit("--tree-max-depth must be positive.")
    if args.tree_min_samples_leaf <= 0:
        raise SystemExit("--tree-min-samples-leaf must be positive.")
    if args.output is not None and len(args.model_families) != 1:
        raise SystemExit("--output can only be used when exactly one --model-families value is selected.")


def filter_runtime_rows(rows: list[dict[str, object]], configs: list[str]) -> list[dict[str, object]]:
    """Keep only rows that are valid for runtime deployment export."""
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


def runtime_metadata_rows(
    *,
    scenarios: list[str],
    configs: list[str],
    rows: list[dict[str, object]],
    label_counts: Counter,
    input_files: dict[str, str],
    extra_rows: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    metadata_rows = [
        ("selected_scenarios", " ".join(scenarios)),
        ("selected_configs", " ".join(configs)),
        ("training_rows", str(len(rows))),
        ("feature_names", " ".join(RUNTIME_FEATURES)),
        ("risk_label_counts", "; ".join(f"{key}={value}" for key, value in sorted(label_counts.items()))),
        ("source_files", "; ".join(f"{scenario}={path}" for scenario, path in sorted(input_files.items()))),
    ]
    if extra_rows:
        metadata_rows.extend(extra_rows)
    return metadata_rows


def resolve_output_path(args: argparse.Namespace, model_family: str) -> Path:
    if args.output is not None:
        return args.output
    return args.output_dir / DEFAULT_OUTPUT_FILENAMES[model_family]


def write_linear_model(
    output_path: Path,
    *,
    format_name: str,
    decision_mode: str,
    positive_label: str,
    threshold: float,
    intercept: float,
    coefficients: list[float],
    means: list[float],
    scales: list[float],
    imputes: list[float],
    metadata_rows: list[tuple[str, str]],
) -> None:
    """Write an explicit linear-model artifact consumed by the runtime controller."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_type", "name", "value", "coefficient", "mean", "scale", "impute_value"])
        writer.writerow(["meta", "format", format_name, "", "", "", ""])
        writer.writerow(["meta", "decision_mode", decision_mode, "", "", "", ""])
        writer.writerow(["meta", "positive_label", positive_label, "", "", "", ""])
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


def write_tree_model(
    output_path: Path,
    *,
    threshold: float,
    positive_label: str,
    impute_values: list[float],
    nodes: list[dict[str, object]],
    metadata_rows: list[tuple[str, str]],
) -> None:
    """Write an explicit shallow-tree artifact consumed by the runtime controller."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "row_type",
            "name",
            "value",
            "node_index",
            "feature_index",
            "threshold",
            "left_index",
            "right_index",
            "impute_value",
            "positive_score",
            "is_leaf",
        ])
        writer.writerow(["meta", "format", "aimrce_shallow_tree_v1", "", "", "", "", "", "", "", ""])
        writer.writerow(["meta", "decision_mode", "shallow_tree_binary", "", "", "", "", "", "", "", ""])
        writer.writerow(["meta", "positive_label", positive_label, "", "", "", "", "", "", "", ""])
        writer.writerow(["meta", "threshold", f"{threshold:.12g}", "", "", "", "", "", "", "", ""])
        for name, value in metadata_rows:
            writer.writerow(["meta", name, value, "", "", "", "", "", "", "", ""])
        for feature_index, (feature_name, impute_value) in enumerate(zip(RUNTIME_FEATURES, impute_values)):
            writer.writerow([
                "feature",
                feature_name,
                "",
                "",
                feature_index,
                "",
                "",
                "",
                f"{impute_value:.12g}",
                "",
                "",
            ])
        for node in nodes:
            writer.writerow([
                "node",
                node["feature_name"],
                "",
                node["node_index"],
                node["feature_index"],
                node["threshold"],
                node["left_index"],
                node["right_index"],
                "",
                node["positive_score"],
                1 if node["is_leaf"] else 0,
            ])


def write_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_logistic_regression(
    args: argparse.Namespace,
    sklearn: dict[str, Any],
    runtime_rows: list[dict[str, object]],
    label_counts: Counter,
    metadata: dict[str, Any],
) -> dict[str, object]:
    pipeline = sklearn["Pipeline"]([
        ("imputer", sklearn["SimpleImputer"](strategy="median")),
        ("scaler", sklearn["StandardScaler"]()),
        ("classifier", sklearn["LogisticRegression"](
            max_iter=1000,
            class_weight="balanced",
            random_state=args.random_seed,
        )),
    ])
    x = feature_matrix(runtime_rows)
    y = [1 if row["risk_label"] == "protect" else 0 for row in runtime_rows]
    pipeline.fit(x, y)

    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    classifier = pipeline.named_steps["classifier"]

    output_path = resolve_output_path(args, "logistic_regression")
    metadata_rows = runtime_metadata_rows(
        scenarios=args.scenarios,
        configs=args.configs,
        rows=runtime_rows,
        label_counts=label_counts,
        input_files=metadata["input_files"],
        extra_rows=[
            ("score_semantics", "logistic_probability"),
            ("note", "Binary logistic-regression runtime deployment artifact trained for protect vs safe/warning using scenario-phase supervision."),
        ],
    )
    write_linear_model(
        output_path=output_path,
        format_name="aimrce_logreg_v1",
        decision_mode="logistic_regression_binary",
        positive_label="protect",
        threshold=args.threshold,
        intercept=float(classifier.intercept_[0]),
        coefficients=[float(value) for value in classifier.coef_[0]],
        means=[float(value) for value in scaler.mean_],
        scales=[float(value) for value in scaler.scale_],
        imputes=[float(value) for value in imputer.statistics_],
        metadata_rows=metadata_rows,
    )

    return {
        "model_family": "logistic_regression",
        "decision_mode": MODEL_DECISION_MODES["logistic_regression"],
        "output_path": str(output_path),
        "threshold": args.threshold,
        "training_rows": len(runtime_rows),
        "features": " ".join(RUNTIME_FEATURES),
        "selected_configs": " ".join(args.configs),
        "selected_scenarios": " ".join(args.scenarios),
        "note": "Logistic-regression runtime deployment artifact.",
    }


def export_linear_svm(
    args: argparse.Namespace,
    sklearn: dict[str, Any],
    runtime_rows: list[dict[str, object]],
    label_counts: Counter,
    metadata: dict[str, Any],
) -> dict[str, object]:
    pipeline = sklearn["Pipeline"]([
        ("imputer", sklearn["SimpleImputer"](strategy="median")),
        ("scaler", sklearn["StandardScaler"]()),
        ("classifier", sklearn["LinearSVC"](
            class_weight="balanced",
            random_state=args.random_seed,
            max_iter=5000,
        )),
    ])
    x = feature_matrix(runtime_rows)
    y = [1 if row["risk_label"] == "protect" else 0 for row in runtime_rows]
    pipeline.fit(x, y)

    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    classifier = pipeline.named_steps["classifier"]

    output_path = resolve_output_path(args, "linear_svm")
    metadata_rows = runtime_metadata_rows(
        scenarios=args.scenarios,
        configs=args.configs,
        rows=runtime_rows,
        label_counts=label_counts,
        input_files=metadata["input_files"],
        extra_rows=[
            ("score_semantics", "sigmoid_of_margin"),
            ("note", "Linear-SVM runtime deployment artifact using a bounded sigmoid transform of the raw margin for runtime thresholding. The score is monotonic but not a calibrated probability."),
        ],
    )
    write_linear_model(
        output_path=output_path,
        format_name="aimrce_linsvm_v1",
        decision_mode="linear_svm_binary",
        positive_label="protect",
        threshold=args.threshold,
        intercept=float(classifier.intercept_[0]),
        coefficients=[float(value) for value in classifier.coef_[0]],
        means=[float(value) for value in scaler.mean_],
        scales=[float(value) for value in scaler.scale_],
        imputes=[float(value) for value in imputer.statistics_],
        metadata_rows=metadata_rows,
    )

    return {
        "model_family": "linear_svm",
        "decision_mode": MODEL_DECISION_MODES["linear_svm"],
        "output_path": str(output_path),
        "threshold": args.threshold,
        "training_rows": len(runtime_rows),
        "features": " ".join(RUNTIME_FEATURES),
        "selected_configs": " ".join(args.configs),
        "selected_scenarios": " ".join(args.scenarios),
        "note": "Linear-SVM runtime deployment artifact with bounded sigmoid-of-margin score.",
    }


def export_shallow_tree(
    args: argparse.Namespace,
    sklearn: dict[str, Any],
    runtime_rows: list[dict[str, object]],
    label_counts: Counter,
    metadata: dict[str, Any],
) -> dict[str, object]:
    pipeline = sklearn["Pipeline"]([
        ("imputer", sklearn["SimpleImputer"](strategy="median")),
        ("classifier", sklearn["DecisionTreeClassifier"](
            max_depth=args.tree_max_depth,
            min_samples_leaf=args.tree_min_samples_leaf,
            class_weight="balanced",
            random_state=args.random_seed,
        )),
    ])
    x = feature_matrix(runtime_rows)
    y = [1 if row["risk_label"] == "protect" else 0 for row in runtime_rows]
    pipeline.fit(x, y)

    imputer = pipeline.named_steps["imputer"]
    classifier = pipeline.named_steps["classifier"]
    positive_class_index = list(classifier.classes_).index(1)
    tree = classifier.tree_

    exported_nodes: list[dict[str, object]] = []
    for node_index in range(tree.node_count):
        feature_index = int(tree.feature[node_index])
        is_leaf = feature_index < 0
        total_count = float(tree.value[node_index][0].sum())
        positive_score = (
            float(tree.value[node_index][0][positive_class_index]) / total_count
            if total_count > 0 else 0.0
        )
        exported_nodes.append({
            "feature_name": "" if is_leaf else RUNTIME_FEATURES[feature_index],
            "node_index": node_index,
            "feature_index": -1 if is_leaf else feature_index,
            "threshold": "" if is_leaf else f"{float(tree.threshold[node_index]):.12g}",
            "left_index": -1 if is_leaf else int(tree.children_left[node_index]),
            "right_index": -1 if is_leaf else int(tree.children_right[node_index]),
            "positive_score": f"{positive_score:.12g}",
            "is_leaf": is_leaf,
        })

    output_path = resolve_output_path(args, "shallow_tree")
    metadata_rows = runtime_metadata_rows(
        scenarios=args.scenarios,
        configs=args.configs,
        rows=runtime_rows,
        label_counts=label_counts,
        input_files=metadata["input_files"],
        extra_rows=[
            ("score_semantics", "positive_leaf_fraction"),
            ("tree_max_depth", str(args.tree_max_depth)),
            ("tree_min_samples_leaf", str(args.tree_min_samples_leaf)),
            ("note", "Shallow decision-tree runtime deployment artifact. Leaf scores are empirical positive-class fractions under scenario-conditioned supervision."),
        ],
    )
    write_tree_model(
        output_path=output_path,
        threshold=args.threshold,
        positive_label="protect",
        impute_values=[float(value) for value in imputer.statistics_],
        nodes=exported_nodes,
        metadata_rows=metadata_rows,
    )

    return {
        "model_family": "shallow_tree",
        "decision_mode": MODEL_DECISION_MODES["shallow_tree"],
        "output_path": str(output_path),
        "threshold": args.threshold,
        "training_rows": len(runtime_rows),
        "features": " ".join(RUNTIME_FEATURES),
        "selected_configs": " ".join(args.configs),
        "selected_scenarios": " ".join(args.scenarios),
        "note": f"Shallow-tree runtime deployment artifact (max_depth={args.tree_max_depth}, min_samples_leaf={args.tree_min_samples_leaf}).",
    }


def main(
    argv: list[str] | None = None,
    *,
    default_model_families: list[str] | None = None,
    default_manifest_output: Path | None = DEFAULT_MANIFEST_OUTPUT,
) -> None:
    args = parse_args(
        argv=argv,
        default_model_families=default_model_families,
        default_manifest_output=default_manifest_output,
    )
    validate_args(args)

    rows, metadata = collect_training_rows(
        scenarios=args.scenarios,
        input_dir=args.input_dir,
        allow_missing=args.allow_missing,
        include_regional_reactive=args.include_regional_reactive,
    )
    runtime_rows = filter_runtime_rows(rows, args.configs)
    require_runtime_features(runtime_rows)

    label_counts = Counter(row["risk_label"] for row in runtime_rows)
    class_counts = Counter(1 if row["risk_label"] == "protect" else 0 for row in runtime_rows)
    if len(class_counts) < 2:
        raise SystemExit("Runtime export needs both positive and negative samples after filtering.")

    sklearn = require_runtime_sklearn()
    manifest_rows: list[dict[str, object]] = []

    for model_family in args.model_families:
        if model_family == "logistic_regression":
            manifest_rows.append(export_logistic_regression(args, sklearn, runtime_rows, label_counts, metadata))
        elif model_family == "linear_svm":
            manifest_rows.append(export_linear_svm(args, sklearn, runtime_rows, label_counts, metadata))
        elif model_family == "shallow_tree":
            manifest_rows.append(export_shallow_tree(args, sklearn, runtime_rows, label_counts, metadata))
        else:
            raise SystemExit(f"Unsupported model family '{model_family}'")

    if args.manifest_output is not None:
        write_manifest(args.manifest_output, manifest_rows)
        print(f"Wrote runtime export manifest to {args.manifest_output}")

    print(f"Rows used: {len(runtime_rows)}")
    print(f"Risk label counts: {dict(label_counts)}")
    print(f"Features: {', '.join(RUNTIME_FEATURES)}")
    for row in manifest_rows:
        print(f"Wrote {row['model_family']} runtime model to {row['output_path']}")


if __name__ == "__main__":
    main()
