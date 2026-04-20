#!/usr/bin/env python3
"""
Train first offline risk-state classifiers from dissertation dataset CSV files.

Assumptions:
- This is an offline analysis script only; it does not modify simulations,
  controllers, INET, or OMNeT++ configuration.
- Input datasets are produced by analysis/build_dataset.py and live under
  analysis/output/<scenario>_dataset.csv by default.
- Original scenario labels are mapped into a unified risk taxonomy:
  safe, warning, protect, failed.
- Convergence rows and unsupported labels are excluded by default.
- Regional reactive-failure rows are excluded by default because the first
  model is for pre-failure risk estimation, not post-hoc rerouting behavior.
- Scenario/config identifiers and window times are intentionally not used as
  model features, to avoid leakage from experiment design into the classifier.
- Missing numeric feature values are handled by median imputation inside each
  scikit-learn pipeline.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "analysis" / "output"

SUPPORTED_SCENARIOS = ("linkdegradation", "congestiondegradation", "regionalbackbone")
DEFAULT_SCENARIOS = SUPPORTED_SCENARIOS
DECISION_LABELS = ["safe", "warning", "protect", "failed"]

FEATURE_COLUMNS = [
    "controller_delay_mean_s",
    "controller_delay_max_s",
    "controller_packet_error_rate_mean",
    "controller_packet_error_rate_max",
    "receiver_app0_e2e_delay_mean_s",
    "receiver_app0_throughput_mean_bps",
    "receiver_total_packet_count",
    "bottleneck_queue_length_mean_pk",
    "bottleneck_queue_bit_length_mean_b",
    "bottleneck_queueing_time_mean_s",
]

LINKDEGRADATION_LABEL_MAP = {
    "normal": "safe",
    "degraded": "warning",
    "pre_failure": "protect",
    "failed": "failed",
}

CONGESTIONDEGRADATION_LABEL_MAP = {
    "baseline": "safe",
    "rising_congestion": "warning",
    "critical_congestion": "protect",
    "failed": "failed",
}

REGIONAL_CONTROLLED_LABEL_MAP = {
    "normal": "safe",
    "degraded": "warning",
    "pre_failure": "protect",
    "failed": "failed",
}

REGIONAL_CONGESTION_LABEL_MAP = {
    "baseline": "safe",
    "rising_congestion": "warning",
    "critical_congestion": "protect",
    "failed": "failed",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train offline risk-state classifiers from dataset CSV files.")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=list(DEFAULT_SCENARIOS),
        choices=SUPPORTED_SCENARIOS,
        help="Scenario datasets to include. Defaults to all supported scenarios.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory containing <scenario>_dataset.csv files.",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=OUTPUT_DIR / "risk_model",
        help="Output prefix for report and CSV artifacts.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.30,
        help="Fraction of rows reserved for testing.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed used for train/test split and model initialization.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip selected scenario datasets that are not present instead of failing.",
    )
    parser.add_argument(
        "--include-regional-reactive",
        action="store_true",
        help="Include RegionalBackboneReactiveFailure rows if a future experiment needs them.",
    )
    return parser.parse_args()


def require_sklearn() -> dict[str, Any]:
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import classification_report, confusion_matrix, f1_score
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "scikit-learn"
        raise SystemExit(
            "Missing Python ML dependency: "
            f"{missing_name}. Install scikit-learn in this Python environment before training, "
            "for example: py -3 -m pip install scikit-learn"
        ) from exc

    return {
        "RandomForestClassifier": RandomForestClassifier,
        "SimpleImputer": SimpleImputer,
        "LogisticRegression": LogisticRegression,
        "classification_report": classification_report,
        "confusion_matrix": confusion_matrix,
        "f1_score": f1_score,
        "train_test_split": train_test_split,
        "Pipeline": Pipeline,
        "StandardScaler": StandardScaler,
    }


def dataset_path(input_dir: Path, scenario: str) -> Path:
    return input_dir / f"{scenario}_dataset.csv"


def load_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def parse_float(value: str | None) -> float:
    if value is None or value == "":
        return math.nan
    try:
        return float(value)
    except ValueError:
        return math.nan


def remap_label(scenario: str, row: dict[str, str], include_regional_reactive: bool) -> tuple[str | None, str | None]:
    label = row.get("label", "")
    config_name = row.get("config_name", "")

    if scenario == "linkdegradation":
        mapped = LINKDEGRADATION_LABEL_MAP.get(label)
        return mapped, None if mapped else f"unsupported_label:{label}"

    if scenario == "congestiondegradation":
        mapped = CONGESTIONDEGRADATION_LABEL_MAP.get(label)
        return mapped, None if mapped else f"excluded_or_unsupported_label:{label}"

    if scenario == "regionalbackbone":
        if config_name == "RegionalBackboneReactiveFailure" and not include_regional_reactive:
            return None, "excluded_regional_reactive_failure"
        if config_name == "RegionalBackboneBaseline":
            mapped = "safe" if label == "normal" else None
            return mapped, None if mapped else f"unsupported_regional_baseline_label:{label}"
        if config_name == "RegionalBackboneControlledDegradation":
            mapped = REGIONAL_CONTROLLED_LABEL_MAP.get(label)
            return mapped, None if mapped else f"unsupported_regional_controlled_label:{label}"
        if config_name == "RegionalBackboneCongestionDegradation":
            mapped = REGIONAL_CONGESTION_LABEL_MAP.get(label)
            return mapped, None if mapped else f"excluded_or_unsupported_regional_congestion_label:{label}"
        return None, f"unsupported_regional_config:{config_name}"

    return None, f"unsupported_scenario:{scenario}"


def collect_training_rows(
    scenarios: list[str],
    input_dir: Path,
    allow_missing: bool,
    include_regional_reactive: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    all_columns: set[str] = set()
    metadata: dict[str, Any] = {
        "input_files": {},
        "loaded_rows_by_scenario": Counter(),
        "kept_rows_by_scenario": Counter(),
        "kept_rows_by_config": Counter(),
        "kept_rows_by_original_label": Counter(),
        "kept_rows_by_risk_label": Counter(),
        "excluded_rows": Counter(),
        "missing_files": [],
    }

    for scenario in scenarios:
        path = dataset_path(input_dir, scenario)
        if not path.exists():
            if allow_missing:
                metadata["missing_files"].append(str(path))
                continue
            raise SystemExit(f"Dataset not found for scenario '{scenario}': {path}")

        columns, scenario_rows = load_csv_rows(path)
        all_columns.update(columns)
        metadata["input_files"][scenario] = str(path)
        metadata["loaded_rows_by_scenario"][scenario] += len(scenario_rows)

        for row in scenario_rows:
            risk_label, excluded_reason = remap_label(scenario, row, include_regional_reactive)
            if risk_label is None:
                metadata["excluded_rows"][excluded_reason or "excluded"] += 1
                continue

            training_row = dict(row)
            training_row["source_scenario"] = scenario
            training_row["risk_label"] = risk_label
            rows.append(training_row)

            metadata["kept_rows_by_scenario"][scenario] += 1
            metadata["kept_rows_by_config"][row.get("config_name", "")] += 1
            metadata["kept_rows_by_original_label"][row.get("label", "")] += 1
            metadata["kept_rows_by_risk_label"][risk_label] += 1

    metadata["all_columns"] = sorted(all_columns)
    return rows, metadata


def select_features(rows: list[dict[str, Any]], available_columns: list[str]) -> tuple[list[str], list[str]]:
    present_features = [feature for feature in FEATURE_COLUMNS if feature in available_columns]
    usable_features = []
    dropped_all_missing = []

    for feature in present_features:
        values = [parse_float(row.get(feature)) for row in rows]
        if all(math.isnan(value) for value in values):
            dropped_all_missing.append(feature)
        else:
            usable_features.append(feature)

    return usable_features, dropped_all_missing


def feature_matrix(rows: list[dict[str, Any]], features: list[str]) -> list[list[float]]:
    return [[parse_float(row.get(feature)) for feature in features] for row in rows]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def counter_rows(counter: Counter, key_name: str, value_name: str = "count") -> list[dict[str, Any]]:
    return [{key_name: key, value_name: value} for key, value in sorted(counter.items(), key=lambda item: str(item[0]))]


def can_stratify(labels: list[str], test_size: float) -> bool:
    counts = Counter(labels)
    if len(counts) < 2:
        return False
    if min(counts.values()) < 2:
        return False
    test_count = math.ceil(len(labels) * test_size)
    train_count = len(labels) - test_count
    return test_count >= len(counts) and train_count >= len(counts)


def build_models(sklearn: dict[str, Any], random_seed: int) -> dict[str, Any]:
    pipeline = sklearn["Pipeline"]
    simple_imputer = sklearn["SimpleImputer"]
    standard_scaler = sklearn["StandardScaler"]
    logistic_regression = sklearn["LogisticRegression"]
    random_forest = sklearn["RandomForestClassifier"]

    return {
        "Logistic Regression": pipeline([
            ("imputer", simple_imputer(strategy="median")),
            ("scaler", standard_scaler()),
            ("classifier", logistic_regression(max_iter=1000, class_weight="balanced", random_state=random_seed)),
        ]),
        "Random Forest": pipeline([
            ("imputer", simple_imputer(strategy="median")),
            ("classifier", random_forest(
                n_estimators=200,
                random_state=random_seed,
                class_weight="balanced",
                min_samples_leaf=2,
            )),
        ]),
    }


def evaluate_models(
    models: dict[str, Any],
    sklearn: dict[str, Any],
    features: list[str],
    x_train: list[list[float]],
    x_test: list[list[float]],
    y_train: list[str],
    y_test: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    report_rows: list[dict[str, Any]] = []
    confusion_rows: list[dict[str, Any]] = []
    feature_importance_rows: list[dict[str, Any]] = []
    report_lines: list[str] = []

    classification_report = sklearn["classification_report"]
    confusion_matrix = sklearn["confusion_matrix"]
    f1_score = sklearn["f1_score"]

    for model_name, model in models.items():
        model.fit(x_train, y_train)
        predictions = model.predict(x_test)
        macro_f1 = f1_score(y_test, predictions, labels=DECISION_LABELS, average="macro", zero_division=0)
        report = classification_report(
            y_test,
            predictions,
            labels=DECISION_LABELS,
            output_dict=True,
            zero_division=0,
        )

        report_lines.append(f"{model_name}")
        report_lines.append("-" * len(model_name))
        report_lines.append(f"macro_f1: {macro_f1}")
        for label in DECISION_LABELS:
            metrics = report.get(label, {})
            report_rows.append({
                "model": model_name,
                "class": label,
                "precision": metrics.get("precision", 0.0),
                "recall": metrics.get("recall", 0.0),
                "f1_score": metrics.get("f1-score", 0.0),
                "support": metrics.get("support", 0.0),
            })
            report_lines.append(
                f"{label}: "
                f"precision={metrics.get('precision', 0.0)}, "
                f"recall={metrics.get('recall', 0.0)}, "
                f"f1={metrics.get('f1-score', 0.0)}, "
                f"support={metrics.get('support', 0.0)}"
            )

        protect_metrics = report.get("protect", {})
        report_lines.append(
            "protect_focus: "
            f"precision={protect_metrics.get('precision', 0.0)}, "
            f"recall={protect_metrics.get('recall', 0.0)}, "
            f"f1={protect_metrics.get('f1-score', 0.0)}"
        )
        report_lines.append("")

        matrix = confusion_matrix(y_test, predictions, labels=DECISION_LABELS)
        for actual_index, actual_label in enumerate(DECISION_LABELS):
            for predicted_index, predicted_label in enumerate(DECISION_LABELS):
                confusion_rows.append({
                    "model": model_name,
                    "actual": actual_label,
                    "predicted": predicted_label,
                    "count": int(matrix[actual_index][predicted_index]),
                })

        classifier = model.named_steps.get("classifier")
        importances = getattr(classifier, "feature_importances_", None)
        if importances is not None:
            for feature, importance in sorted(zip(features, importances), key=lambda item: item[1], reverse=True):
                feature_importance_rows.append({
                    "model": model_name,
                    "feature": feature,
                    "importance": importance,
                })

    return report_rows, confusion_rows, report_lines + [""], feature_importance_rows


def write_report(
    path: Path,
    metadata: dict[str, Any],
    features: list[str],
    dropped_features: list[str],
    train_count: int,
    test_count: int,
    stratified: bool,
    model_report_lines: list[str],
    output_paths: dict[str, Path],
) -> None:
    lines: list[str] = []
    title = "Offline Risk Model Training Report"
    lines.append(title)
    lines.append("=" * len(title))
    lines.append("")
    lines.append("Input Datasets")
    for scenario, input_path in sorted(metadata["input_files"].items()):
        lines.append(f"  {scenario}: {input_path}")
    if metadata["missing_files"]:
        lines.append("  missing files skipped:")
        for missing_path in metadata["missing_files"]:
            lines.append(f"    {missing_path}")
    lines.append("")
    lines.append("Rows")
    lines.append(f"  loaded by scenario: {dict(metadata['loaded_rows_by_scenario'])}")
    lines.append(f"  kept by scenario: {dict(metadata['kept_rows_by_scenario'])}")
    lines.append(f"  kept by config: {dict(metadata['kept_rows_by_config'])}")
    lines.append(f"  kept by original label: {dict(metadata['kept_rows_by_original_label'])}")
    lines.append(f"  kept by risk label: {dict(metadata['kept_rows_by_risk_label'])}")
    lines.append(f"  excluded rows: {dict(metadata['excluded_rows'])}")
    lines.append("")
    lines.append("Feature Selection")
    lines.append("  identifiers excluded from training: config_name, run_number, window_start_s, window_end_s, source_scenario")
    lines.append(f"  features used ({len(features)}):")
    for feature in features:
        lines.append(f"    {feature}")
    if dropped_features:
        lines.append("  dropped all-missing features:")
        for feature in dropped_features:
            lines.append(f"    {feature}")
    lines.append("")
    lines.append("Split")
    lines.append(f"  train rows: {train_count}")
    lines.append(f"  test rows: {test_count}")
    lines.append(f"  stratified: {stratified}")
    lines.append("")
    lines.append("Model Evaluation")
    lines.extend(model_report_lines)
    lines.append("Generated Files")
    for name, output_path in output_paths.items():
        lines.append(f"  {name}: {output_path}")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if args.test_size <= 0 or args.test_size >= 1:
        raise SystemExit("--test-size must be between 0 and 1.")

    rows, metadata = collect_training_rows(
        scenarios=args.scenarios,
        input_dir=args.input_dir,
        allow_missing=args.allow_missing,
        include_regional_reactive=args.include_regional_reactive,
    )
    if not rows:
        raise SystemExit("No training rows remained after label remapping and filtering.")

    features, dropped_features = select_features(rows, metadata["all_columns"])
    if not features:
        raise SystemExit("No usable feature columns were found in the selected datasets.")

    x = feature_matrix(rows, features)
    y = [row["risk_label"] for row in rows]

    sklearn = require_sklearn()
    stratified = can_stratify(y, args.test_size)
    x_train, x_test, y_train, y_test = sklearn["train_test_split"](
        x,
        y,
        test_size=args.test_size,
        random_state=args.random_seed,
        stratify=y if stratified else None,
    )

    models = build_models(sklearn, args.random_seed)
    per_class_rows, confusion_rows, model_report_lines, feature_importance_rows = evaluate_models(
        models=models,
        sklearn=sklearn,
        features=features,
        x_train=x_train,
        x_test=x_test,
        y_train=y_train,
        y_test=y_test,
    )

    output_prefix = args.output_prefix
    output_paths = {
        "report": output_prefix.with_name(f"{output_prefix.name}_report.txt"),
        "class distribution": output_prefix.with_name(f"{output_prefix.name}_class_distribution.csv"),
        "confusion matrix": output_prefix.with_name(f"{output_prefix.name}_confusion_matrix.csv"),
        "feature importance": output_prefix.with_name(f"{output_prefix.name}_feature_importance.csv"),
        "per-class metrics": output_prefix.with_name(f"{output_prefix.name}_per_class_metrics.csv"),
    }

    write_csv(output_paths["class distribution"], counter_rows(metadata["kept_rows_by_risk_label"], "risk_label"))
    write_csv(output_paths["confusion matrix"], confusion_rows)
    write_csv(output_paths["feature importance"], feature_importance_rows)
    write_csv(output_paths["per-class metrics"], per_class_rows)
    write_report(
        path=output_paths["report"],
        metadata=metadata,
        features=features,
        dropped_features=dropped_features,
        train_count=len(y_train),
        test_count=len(y_test),
        stratified=stratified,
        model_report_lines=model_report_lines,
        output_paths=output_paths,
    )

    print(f"Wrote training report to {output_paths['report']}")
    print(f"Wrote class distribution to {output_paths['class distribution']}")
    print(f"Wrote confusion matrix to {output_paths['confusion matrix']}")
    print(f"Wrote feature importance to {output_paths['feature importance']}")
    print(f"Wrote per-class metrics to {output_paths['per-class metrics']}")


if __name__ == "__main__":
    main()
