#!/usr/bin/env python3
"""
Train offline risk-state classifiers from dissertation dataset CSV files.

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
- Runtime protection configs may appear in outcome-oriented regional datasets,
  but they remain outside this offline classifier scope because they are used
  for mechanism evaluation rather than for the current supervision problem.
- Scenario/config identifiers and window times are intentionally not used as
  model features, to avoid leakage from experiment design into the classifier.
- Missing numeric feature values are handled by median imputation inside each
  scikit-learn pipeline.
- Labels come from scenario-phase supervision, not measured real-world failure
  onset detection, so evaluation results should be interpreted accordingly.
- The random window split is retained as an optimistic baseline only. Grouped
  and transfer-style evaluations are the primary evidence for generalization.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "analysis" / "output"

SUPPORTED_SCENARIOS = ("linkdegradation", "congestiondegradation", "regionalbackbone")
DEFAULT_SCENARIOS = SUPPORTED_SCENARIOS
DECISION_LABELS = ["safe", "warning", "protect", "failed"]

SUPPORTED_EVALUATIONS = (
    "baseline_random",
    "grouped_run_holdout",
    "leave_one_config_out",
    "topology_transfer_small_to_regional",
    "topology_transfer_regional_to_small",
)
DEFAULT_EVALUATIONS = SUPPORTED_EVALUATIONS

EVALUATION_METADATA = {
    "baseline_random": {
        "title": "Baseline Random Window Split",
        "category": "optimistic_baseline",
        "description": "Random window-level split. Windows from the same run may appear in both train and test.",
    },
    "grouped_run_holdout": {
        "title": "Grouped Run Holdout",
        "category": "generalization_oriented",
        "description": "One grouped holdout split using config_name plus run_number as the grouping key.",
    },
    "leave_one_config_out": {
        "title": "Leave One Config Out",
        "category": "generalization_oriented",
        "description": "Each config is held out in turn to test cross-config generalization.",
    },
    "topology_transfer_small_to_regional": {
        "title": "Small To Regional Transfer",
        "category": "generalization_oriented",
        "description": "Train on small-topology datasets and test on the medium-topology regional backbone dataset.",
    },
    "topology_transfer_regional_to_small": {
        "title": "Regional To Small Transfer",
        "category": "generalization_oriented",
        "description": "Train on the medium-topology regional backbone dataset and test on the small-topology datasets.",
    },
}

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
# Offline feature pool for methodological evaluation. The runtime AI-MRCE
# prototype intentionally uses a smaller exported subset instead of this full
# mixed controller/receiver/queue feature list.

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

SMALL_TOPOLOGY_SCENARIOS = {"linkdegradation", "congestiondegradation"}


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
        "--evaluations",
        nargs="+",
        default=list(DEFAULT_EVALUATIONS),
        choices=SUPPORTED_EVALUATIONS,
        help="Evaluation schemes to run. Defaults to baseline plus grouped and transfer-style evaluations.",
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
        help="Fraction of rows reserved for testing in holdout evaluations.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed used for randomized evaluation splits and model initialization.",
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
        from sklearn.model_selection import GroupShuffleSplit, LeaveOneGroupOut, train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "scikit-learn"
        raise SystemExit(
            "Missing Python ML dependency: "
            f"{missing_name}. Install the analysis requirements in the project environment before training, "
            "for example: run_analysis.bat install-ml-deps"
        ) from exc

    return {
        "RandomForestClassifier": RandomForestClassifier,
        "SimpleImputer": SimpleImputer,
        "LogisticRegression": LogisticRegression,
        "classification_report": classification_report,
        "confusion_matrix": confusion_matrix,
        "f1_score": f1_score,
        "GroupShuffleSplit": GroupShuffleSplit,
        "LeaveOneGroupOut": LeaveOneGroupOut,
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
    """Map scenario-phase supervision labels into the shared risk taxonomy.

    The output labels are intentionally harmonized for offline comparison
    across scenarios. They should still be described as schedule-derived
    supervision, not measured real-world failure onset annotations.
    """
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
        if config_name.startswith("RegionalBackboneAiMrce"):
            # These runtime protection rows are useful for project-local outcome
            # evaluation, but keeping them out here preserves the existing
            # offline supervision problem and avoids mixing deployment-behavior
            # runs into the main classifier training table.
            return None, "excluded_runtime_protection_config"
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
    """Load and normalize rows from the selected scenario datasets.

    This is the main bridge from scenario-specific dataset exports into the
    unified offline evaluation table. It also records exclusion reasons so the
    later report makes the modeling scope explicit.
    """
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
            training_row["run_group"] = run_group_key(training_row)
            rows.append(training_row)

            metadata["kept_rows_by_scenario"][scenario] += 1
            metadata["kept_rows_by_config"][row.get("config_name", "")] += 1
            metadata["kept_rows_by_original_label"][row.get("label", "")] += 1
            metadata["kept_rows_by_risk_label"][risk_label] += 1

    metadata["all_columns"] = sorted(all_columns)
    return rows, metadata


def select_features(rows: list[dict[str, Any]], available_columns: list[str]) -> tuple[list[str], list[str]]:
    """Keep only available offline features with at least one usable value."""
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


def run_group_key(row: dict[str, Any]) -> str:
    return f"{row.get('config_name', '')}::run{row.get('run_number', '')}"


def config_run_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    runs_by_config: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        runs_by_config[row.get("config_name", "")].add(str(row.get("run_number", "")))
    return {config_name: len(runs) for config_name, runs in sorted(runs_by_config.items())}


def serialize_counter(counter: Counter) -> str:
    if not counter:
        return ""
    return "; ".join(f"{key}={value}" for key, value in sorted(counter.items(), key=lambda item: str(item[0])))


def distinct_values(rows: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(row.get(key, "")) for row in rows})


def build_models(sklearn: dict[str, Any], random_seed: int) -> dict[str, Any]:
    """Construct the offline baseline models used in this evaluation script.

    These estimators are part of the methodological analysis layer. They are
    not the same thing as the exported runtime deployment artifact used by the
    first AI-MRCE prototype.
    """
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


def make_fold(
    evaluation_scheme: str,
    fold_id: str,
    fold_description: str,
    train_indices: list[int],
    test_indices: list[int],
    *,
    baseline_only: bool,
    split_note: str = "",
) -> dict[str, Any]:
    return {
        "evaluation_scheme": evaluation_scheme,
        "fold_id": fold_id,
        "fold_description": fold_description,
        "baseline_only": baseline_only,
        "split_note": split_note,
        "train_indices": list(train_indices),
        "test_indices": list(test_indices),
    }


def plan_random_baseline(rows: list[dict[str, Any]], sklearn: dict[str, Any], test_size: float, random_seed: int) -> list[dict[str, Any]]:
    """Create the optimistic window-level baseline split.

    This split is retained for reference because it is easy to compare with
    earlier work, but it should not be presented as independent generalization
    evidence when windows from the same run can appear on both sides.
    """
    indices = list(range(len(rows)))
    labels = [row["risk_label"] for row in rows]
    stratified = can_stratify(labels, test_size)
    train_indices, test_indices = sklearn["train_test_split"](
        indices,
        test_size=test_size,
        random_state=random_seed,
        stratify=labels if stratified else None,
    )
    note = "stratified by risk label" if stratified else "not stratified"
    return [
        make_fold(
            "baseline_random",
            "baseline_split",
            "Random window-level baseline split",
            train_indices,
            test_indices,
            baseline_only=True,
            split_note=note,
        )
    ]


def plan_grouped_run_holdout(rows: list[dict[str, Any]], sklearn: dict[str, Any], test_size: float, random_seed: int) -> list[dict[str, Any]]:
    """Create one holdout split that keeps config/run groups intact."""
    groups = [row["run_group"] for row in rows]
    unique_groups = sorted(set(groups))
    if len(unique_groups) < 2:
        return []

    splitter = sklearn["GroupShuffleSplit"](n_splits=1, test_size=test_size, random_state=random_seed)
    indices = list(range(len(rows)))
    train_indices, test_indices = next(splitter.split(indices, groups=groups))
    return [
        make_fold(
            "grouped_run_holdout",
            "group_holdout",
            "Grouped holdout using config_name plus run_number",
            train_indices.tolist(),
            test_indices.tolist(),
            baseline_only=False,
        )
    ]


def plan_leave_one_config_out(rows: list[dict[str, Any]], sklearn: dict[str, Any]) -> list[dict[str, Any]]:
    """Hold out each config in turn for a stricter cross-config check."""
    groups = [row["config_name"] for row in rows]
    unique_configs = sorted(set(groups))
    if len(unique_configs) < 2:
        return []

    splitter = sklearn["LeaveOneGroupOut"]()
    indices = list(range(len(rows)))
    folds = []
    for train_indices, test_indices in splitter.split(indices, groups=groups):
        held_out_config = rows[test_indices[0]]["config_name"]
        folds.append(
            make_fold(
                "leave_one_config_out",
                f"holdout_{held_out_config}",
                f"Hold out config {held_out_config}",
                train_indices.tolist(),
                test_indices.tolist(),
                baseline_only=False,
            )
        )
    return folds


def plan_topology_transfer(rows: list[dict[str, Any]], evaluation_scheme: str) -> list[dict[str, Any]]:
    """Create topology-transfer folds between small and regional datasets.

    These folds are meant to test whether the offline classifier is learning a
    transferable risk signal rather than only memorizing one topology family.
    """
    if evaluation_scheme == "topology_transfer_small_to_regional":
        train_indices = [index for index, row in enumerate(rows) if row["source_scenario"] in SMALL_TOPOLOGY_SCENARIOS]
        test_indices = [index for index, row in enumerate(rows) if row["source_scenario"] == "regionalbackbone"]
        description = "Train on small-topology datasets, test on regional backbone"
        fold_id = "small_to_regional"
    else:
        train_indices = [index for index, row in enumerate(rows) if row["source_scenario"] == "regionalbackbone"]
        test_indices = [index for index, row in enumerate(rows) if row["source_scenario"] in SMALL_TOPOLOGY_SCENARIOS]
        description = "Train on regional backbone, test on small-topology datasets"
        fold_id = "regional_to_small"

    if not train_indices or not test_indices:
        return []

    return [
        make_fold(
            evaluation_scheme,
            fold_id,
            description,
            train_indices,
            test_indices,
            baseline_only=False,
        )
    ]


def plan_evaluation_folds(
    rows: list[dict[str, Any]],
    evaluations: list[str],
    sklearn: dict[str, Any],
    test_size: float,
    random_seed: int,
) -> list[dict[str, Any]]:
    folds: list[dict[str, Any]] = []
    for evaluation in evaluations:
        if evaluation == "baseline_random":
            folds.extend(plan_random_baseline(rows, sklearn, test_size, random_seed))
        elif evaluation == "grouped_run_holdout":
            folds.extend(plan_grouped_run_holdout(rows, sklearn, test_size, random_seed))
        elif evaluation == "leave_one_config_out":
            folds.extend(plan_leave_one_config_out(rows, sklearn))
        elif evaluation in {"topology_transfer_small_to_regional", "topology_transfer_regional_to_small"}:
            folds.extend(plan_topology_transfer(rows, evaluation))
        else:
            raise SystemExit(f"Unsupported evaluation scheme '{evaluation}'")
    return folds


def summarize_fold_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "row_count": len(rows),
        "config_count": len(distinct_values(rows, "config_name")),
        "run_group_count": len(distinct_values(rows, "run_group")),
        "risk_label_counts": Counter(row["risk_label"] for row in rows),
        "scenario_counts": Counter(row["source_scenario"] for row in rows),
    }


def evaluate_fold(
    fold: dict[str, Any],
    rows: list[dict[str, Any]],
    features: list[str],
    sklearn: dict[str, Any],
    random_seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fit offline models on one planned split and collect evaluation artifacts."""
    train_rows = [rows[index] for index in fold["train_indices"]]
    test_rows = [rows[index] for index in fold["test_indices"]]

    train_summary = summarize_fold_rows(train_rows)
    test_summary = summarize_fold_rows(test_rows)
    split_row = {
        "evaluation_scheme": fold["evaluation_scheme"],
        "evaluation_title": EVALUATION_METADATA[fold["evaluation_scheme"]]["title"],
        "evaluation_category": EVALUATION_METADATA[fold["evaluation_scheme"]]["category"],
        "fold_id": fold["fold_id"],
        "fold_description": fold["fold_description"],
        "baseline_only": fold["baseline_only"],
        "split_note": fold["split_note"],
        "status": "completed",
        "skip_reason": "",
        "train_rows": train_summary["row_count"],
        "test_rows": test_summary["row_count"],
        "train_configs": train_summary["config_count"],
        "test_configs": test_summary["config_count"],
        "train_run_groups": train_summary["run_group_count"],
        "test_run_groups": test_summary["run_group_count"],
        "train_label_counts": serialize_counter(train_summary["risk_label_counts"]),
        "test_label_counts": serialize_counter(test_summary["risk_label_counts"]),
        "train_scenarios": serialize_counter(train_summary["scenario_counts"]),
        "test_scenarios": serialize_counter(test_summary["scenario_counts"]),
    }

    if not train_rows or not test_rows:
        split_row["status"] = "skipped"
        split_row["skip_reason"] = "empty_train_or_test_split"
        return split_row, [], [], []

    train_labels = [row["risk_label"] for row in train_rows]
    test_labels = [row["risk_label"] for row in test_rows]
    if len(set(train_labels)) < 2:
        split_row["status"] = "skipped"
        split_row["skip_reason"] = "training_split_has_fewer_than_two_classes"
        return split_row, [], [], []

    x_train = feature_matrix(train_rows, features)
    x_test = feature_matrix(test_rows, features)
    observed_test_labels = [label for label in DECISION_LABELS if label in set(test_labels)]

    evaluation_summary_rows: list[dict[str, Any]] = []
    confusion_rows: list[dict[str, Any]] = []
    per_class_rows: list[dict[str, Any]] = []
    feature_importance_rows: list[dict[str, Any]] = []

    classification_report = sklearn["classification_report"]
    confusion_matrix = sklearn["confusion_matrix"]
    f1_score = sklearn["f1_score"]

    for model_name, model in build_models(sklearn, random_seed).items():
        model.fit(x_train, train_labels)
        predictions = model.predict(x_test)

        macro_f1_all_labels = f1_score(
            test_labels,
            predictions,
            labels=DECISION_LABELS,
            average="macro",
            zero_division=0,
        )
        macro_f1_observed_labels = (
            f1_score(
                test_labels,
                predictions,
                labels=observed_test_labels,
                average="macro",
                zero_division=0,
            )
            if observed_test_labels else ""
        )

        report = classification_report(
            test_labels,
            predictions,
            labels=DECISION_LABELS,
            output_dict=True,
            zero_division=0,
        )
        protect_metrics = report.get("protect", {})

        evaluation_summary_rows.append({
            "evaluation_scheme": fold["evaluation_scheme"],
            "evaluation_title": EVALUATION_METADATA[fold["evaluation_scheme"]]["title"],
            "evaluation_category": EVALUATION_METADATA[fold["evaluation_scheme"]]["category"],
            "fold_id": fold["fold_id"],
            "fold_description": fold["fold_description"],
            "baseline_only": fold["baseline_only"],
            "model": model_name,
            "train_rows": train_summary["row_count"],
            "test_rows": test_summary["row_count"],
            "train_run_groups": train_summary["run_group_count"],
            "test_run_groups": test_summary["run_group_count"],
            "train_label_counts": serialize_counter(train_summary["risk_label_counts"]),
            "test_label_counts": serialize_counter(test_summary["risk_label_counts"]),
            "macro_f1_all_labels": macro_f1_all_labels,
            "macro_f1_observed_test_labels": macro_f1_observed_labels,
            "protect_precision": protect_metrics.get("precision", 0.0),
            "protect_recall": protect_metrics.get("recall", 0.0),
            "protect_f1_score": protect_metrics.get("f1-score", 0.0),
        })

        for label in DECISION_LABELS:
            metrics = report.get(label, {})
            per_class_rows.append({
                "evaluation_scheme": fold["evaluation_scheme"],
                "evaluation_title": EVALUATION_METADATA[fold["evaluation_scheme"]]["title"],
                "evaluation_category": EVALUATION_METADATA[fold["evaluation_scheme"]]["category"],
                "fold_id": fold["fold_id"],
                "fold_description": fold["fold_description"],
                "baseline_only": fold["baseline_only"],
                "model": model_name,
                "class": label,
                "precision": metrics.get("precision", 0.0),
                "recall": metrics.get("recall", 0.0),
                "f1_score": metrics.get("f1-score", 0.0),
                "support": metrics.get("support", 0.0),
            })

        matrix = confusion_matrix(test_labels, predictions, labels=DECISION_LABELS)
        for actual_index, actual_label in enumerate(DECISION_LABELS):
            for predicted_index, predicted_label in enumerate(DECISION_LABELS):
                confusion_rows.append({
                    "evaluation_scheme": fold["evaluation_scheme"],
                    "evaluation_title": EVALUATION_METADATA[fold["evaluation_scheme"]]["title"],
                    "evaluation_category": EVALUATION_METADATA[fold["evaluation_scheme"]]["category"],
                    "fold_id": fold["fold_id"],
                    "fold_description": fold["fold_description"],
                    "baseline_only": fold["baseline_only"],
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
                    "evaluation_scheme": fold["evaluation_scheme"],
                    "evaluation_title": EVALUATION_METADATA[fold["evaluation_scheme"]]["title"],
                    "evaluation_category": EVALUATION_METADATA[fold["evaluation_scheme"]]["category"],
                    "fold_id": fold["fold_id"],
                    "fold_description": fold["fold_description"],
                    "baseline_only": fold["baseline_only"],
                    "model": model_name,
                    "feature": feature,
                    "importance": importance,
                })

    return split_row, evaluation_summary_rows, per_class_rows, confusion_rows + feature_importance_rows


def evaluate_all_folds(
    folds: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    features: list[str],
    sklearn: dict[str, Any],
    random_seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    split_rows: list[dict[str, Any]] = []
    evaluation_summary_rows: list[dict[str, Any]] = []
    per_class_rows: list[dict[str, Any]] = []
    confusion_rows: list[dict[str, Any]] = []
    feature_importance_rows: list[dict[str, Any]] = []

    for fold in folds:
        split_row, fold_summary_rows, fold_per_class_rows, combined_rows = evaluate_fold(
            fold=fold,
            rows=rows,
            features=features,
            sklearn=sklearn,
            random_seed=random_seed,
        )
        split_rows.append(split_row)
        evaluation_summary_rows.extend(fold_summary_rows)
        per_class_rows.extend(fold_per_class_rows)

        for row in combined_rows:
            if "actual" in row:
                confusion_rows.append(row)
            else:
                feature_importance_rows.append(row)

    return split_rows, evaluation_summary_rows, per_class_rows, confusion_rows, feature_importance_rows


def scheme_summary_rows(evaluation_summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in evaluation_summary_rows:
        grouped[(row["evaluation_scheme"], row["model"])].append(row)

    summary_rows: list[dict[str, Any]] = []
    for (evaluation_scheme, model_name), rows in sorted(grouped.items()):
        all_label_values = [float(row["macro_f1_all_labels"]) for row in rows]
        observed_values = [
            float(row["macro_f1_observed_test_labels"])
            for row in rows
            if row["macro_f1_observed_test_labels"] != ""
        ]
        protect_values = [float(row["protect_f1_score"]) for row in rows]
        summary_rows.append({
            "evaluation_scheme": evaluation_scheme,
            "evaluation_title": EVALUATION_METADATA[evaluation_scheme]["title"],
            "evaluation_category": EVALUATION_METADATA[evaluation_scheme]["category"],
            "model": model_name,
            "completed_folds": len(rows),
            "macro_f1_all_labels_mean": fmean(all_label_values),
            "macro_f1_all_labels_min": min(all_label_values),
            "macro_f1_all_labels_max": max(all_label_values),
            "macro_f1_observed_test_labels_mean": fmean(observed_values) if observed_values else "",
            "macro_f1_observed_test_labels_min": min(observed_values) if observed_values else "",
            "macro_f1_observed_test_labels_max": max(observed_values) if observed_values else "",
            "protect_f1_mean": fmean(protect_values),
            "protect_f1_min": min(protect_values),
            "protect_f1_max": max(protect_values),
        })
    return summary_rows


def render_scheme_report_lines(
    evaluation: str,
    split_rows: list[dict[str, Any]],
    evaluation_summary_rows: list[dict[str, Any]],
) -> list[str]:
    lines = [
        EVALUATION_METADATA[evaluation]["title"],
        "-" * len(EVALUATION_METADATA[evaluation]["title"]),
        f"category: {EVALUATION_METADATA[evaluation]['category']}",
        f"description: {EVALUATION_METADATA[evaluation]['description']}",
    ]

    scheme_split_rows = [row for row in split_rows if row["evaluation_scheme"] == evaluation]
    completed_summaries = [row for row in evaluation_summary_rows if row["evaluation_scheme"] == evaluation]
    completed_splits = [row for row in scheme_split_rows if row["status"] == "completed"]
    skipped_splits = [row for row in scheme_split_rows if row["status"] != "completed"]

    lines.append(f"planned folds: {len(scheme_split_rows)}")
    lines.append(f"completed folds: {len(completed_splits)}")
    if skipped_splits:
        lines.append("skipped folds:")
        for row in skipped_splits:
            lines.append(f"  {row['fold_id']}: {row['skip_reason']}")

    if not completed_summaries:
        lines.append("no completed model evaluations")
        lines.append("")
        return lines

    summary_rows = scheme_summary_rows(completed_summaries)
    for summary_row in summary_rows:
        lines.append(
            f"{summary_row['model']}: "
            f"macro_f1_all_labels_mean={summary_row['macro_f1_all_labels_mean']}, "
            f"macro_f1_observed_test_labels_mean={summary_row['macro_f1_observed_test_labels_mean']}, "
            f"protect_f1_mean={summary_row['protect_f1_mean']}, "
            f"completed_folds={summary_row['completed_folds']}"
        )

    lines.append("completed fold summaries:")
    for row in completed_splits:
        lines.append(
            f"  {row['fold_id']}: "
            f"train_rows={row['train_rows']}, "
            f"test_rows={row['test_rows']}, "
            f"train_run_groups={row['train_run_groups']}, "
            f"test_run_groups={row['test_run_groups']}, "
            f"test_labels={row['test_label_counts']}"
        )

    lines.append("")
    return lines


def write_report(
    path: Path,
    metadata: dict[str, Any],
    features: list[str],
    dropped_features: list[str],
    run_counts_by_config: dict[str, int],
    evaluations: list[str],
    split_rows: list[dict[str, Any]],
    evaluation_summary_rows: list[dict[str, Any]],
    output_paths: dict[str, Path],
) -> None:
    """Write the human-readable offline training report.

    The report is designed to make evaluation framing explicit so optimistic
    baseline splits are not confused with the stronger grouped or transfer
    evaluations.
    """
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
    lines.append(f"  unique runs by config: {run_counts_by_config}")
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
    lines.append("Evaluation Framing")
    lines.append("  labels are scenario-phase supervision, not measured real-world failure onset detection")
    lines.append("  baseline_random is optimistic and retained only as a leakage-prone reference point")
    lines.append("  grouped and transfer-style evaluations are the primary generalization-oriented evidence")
    single_run_configs = [config_name for config_name, count in run_counts_by_config.items() if count < 2]
    if single_run_configs:
        lines.append("  configs with fewer than 2 unique runs:")
        for config_name in single_run_configs:
            lines.append(f"    {config_name}")
    lines.append("")
    lines.append("Evaluation Schemes")
    for evaluation in evaluations:
        lines.extend(render_scheme_report_lines(evaluation, split_rows, evaluation_summary_rows))
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

    run_counts_by_config = config_run_counts(rows)
    sklearn = require_sklearn()
    # Fold planning is where the script separates the optimistic baseline from
    # the generalization-oriented evaluation modes.
    folds = plan_evaluation_folds(
        rows=rows,
        evaluations=args.evaluations,
        sklearn=sklearn,
        test_size=args.test_size,
        random_seed=args.random_seed,
    )
    if not folds:
        raise SystemExit("No evaluation folds could be planned for the selected configuration.")

    split_rows, evaluation_summary_rows, per_class_rows, confusion_rows, feature_importance_rows = evaluate_all_folds(
        folds=folds,
        rows=rows,
        features=features,
        sklearn=sklearn,
        random_seed=args.random_seed,
    )

    output_prefix = args.output_prefix
    output_paths = {
        "report": output_prefix.with_name(f"{output_prefix.name}_report.txt"),
        "class distribution": output_prefix.with_name(f"{output_prefix.name}_class_distribution.csv"),
        "split summary": output_prefix.with_name(f"{output_prefix.name}_split_summary.csv"),
        "evaluation summary": output_prefix.with_name(f"{output_prefix.name}_evaluation_summary.csv"),
        "confusion matrix": output_prefix.with_name(f"{output_prefix.name}_confusion_matrix.csv"),
        "feature importance": output_prefix.with_name(f"{output_prefix.name}_feature_importance.csv"),
        "per-class metrics": output_prefix.with_name(f"{output_prefix.name}_per_class_metrics.csv"),
    }

    write_csv(output_paths["class distribution"], counter_rows(metadata["kept_rows_by_risk_label"], "risk_label"))
    write_csv(output_paths["split summary"], split_rows)
    write_csv(output_paths["evaluation summary"], evaluation_summary_rows)
    write_csv(output_paths["confusion matrix"], confusion_rows)
    write_csv(output_paths["feature importance"], feature_importance_rows)
    write_csv(output_paths["per-class metrics"], per_class_rows)
    write_report(
        path=output_paths["report"],
        metadata=metadata,
        features=features,
        dropped_features=dropped_features,
        run_counts_by_config=run_counts_by_config,
        evaluations=args.evaluations,
        split_rows=split_rows,
        evaluation_summary_rows=evaluation_summary_rows,
        output_paths=output_paths,
    )

    print(f"Wrote training report to {output_paths['report']}")
    print(f"Wrote class distribution to {output_paths['class distribution']}")
    print(f"Wrote split summary to {output_paths['split summary']}")
    print(f"Wrote evaluation summary to {output_paths['evaluation summary']}")
    print(f"Wrote confusion matrix to {output_paths['confusion matrix']}")
    print(f"Wrote feature importance to {output_paths['feature importance']}")
    print(f"Wrote per-class metrics to {output_paths['per-class metrics']}")


if __name__ == "__main__":
    main()
