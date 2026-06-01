#!/usr/bin/env python3
"""
Offline ML feasibility audit for telemetry-v2 extended datasets.

This script is analysis-only. It does not retrain deployed AI-MRCE runtime
artifacts, export runtime CSVs, alter simulation behavior, or change validated
outcome definitions. It evaluates whether telemetry-v2 runtime-safe candidate
features are suitable for a future, separately validated model-retraining step.
"""

from __future__ import annotations

import argparse
import csv
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, pstdev


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
DATASETS_DIR = OUTPUT_ROOT / "datasets"
REPORTS_DIR = OUTPUT_ROOT / "reports"
OUTCOMES_DIR = OUTPUT_ROOT / "outcomes"
ML_AUDIT_DIR = OUTPUT_ROOT / "ml_audit"
AUDIT_DIR = OUTPUT_ROOT / "audit"
RUNTIME_DIR = PROJECT_ROOT / "simulations" / "regionalbackbone"

DEFAULT_SCENARIO = "regionalbackbone_failure_detection_degraded_link_model_family"

BASELINE_FEATURES = [
    "bottleneck_queue_length_last_pk",
    "receiver_app0_e2e_delay_mean_s",
    "receiver_app0_throughput_mean_bps",
    "receiver_app0_packet_count",
]

LABEL_COLUMN = "offline_should_protect_before_failure"
SUPPORTED_LABEL_SOURCE_VALUES = {"baseline", "rising_congestion", "critical_congestion"}
POSITIVE_LABEL_VALUE = "critical_congestion"
STREAK_REQUIRED = 3
CORRELATION_THRESHOLD = 0.995
NEAR_CONSTANT_DOMINANCE = 0.99


@dataclass(frozen=True)
class FeatureClassification:
    feature: str
    group: str
    classification: str
    provenance: str
    note: str


@dataclass
class FeatureStats:
    feature: str
    group: str
    classification: str
    provenance: str
    note: str
    rows: int
    missing: int
    missing_rate: float
    pre_activation_missing_rate: float
    unique_values: int
    near_constant: bool
    constant: bool
    min_value: str
    mean_value: str
    std_value: str
    max_value: str
    populated_config_runs: int
    selected_for_benchmark: bool
    exclusion_reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit telemetry-v2 extended features and run offline ML feasibility benchmarks."
    )
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--extended-dataset", type=Path)
    parser.add_argument("--baseline-dataset", type=Path)
    parser.add_argument("--classification", type=Path)
    parser.add_argument("--outcome-summary", type=Path)
    return parser.parse_args()


def scenario_paths(args: argparse.Namespace) -> dict[str, Path]:
    scenario = args.scenario
    return {
        "extended_dataset": args.extended_dataset
        or DATASETS_DIR / f"{scenario}_extended_dataset.csv",
        "baseline_dataset": args.baseline_dataset
        or DATASETS_DIR / f"{scenario}_dataset.csv",
        "classification": args.classification
        or REPORTS_DIR / f"{scenario}_extended_feature_classification.txt",
        "outcome_summary": args.outcome_summary
        or OUTCOMES_DIR / f"{scenario}_outcome_summary.csv",
    }


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        with tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Required input missing: {path}")
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def format_float(value: float | None, digits: int = 6) -> str:
    if value is None or math.isnan(value):
        return ""
    return f"{value:.{digits}f}"


def parse_feature_classification(path: Path) -> dict[str, FeatureClassification]:
    if not path.exists():
        raise SystemExit(f"Required feature classification missing: {path}")
    classifications: dict[str, FeatureClassification] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("- ") or ": group=" not in line:
            continue
        feature, rest = line[2:].split(": ", 1)
        parts: dict[str, str] = {}
        for segment in rest.split("; "):
            if "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            parts[key] = value
        classifications[feature] = FeatureClassification(
            feature=feature,
            group=parts.get("group", ""),
            classification=parts.get("classification", ""),
            provenance=parts.get("provenance", ""),
            note=parts.get("note", ""),
        )
    return classifications


def runtime_safe_features(classifications: dict[str, FeatureClassification], columns: set[str]) -> list[str]:
    return [
        name
        for name, info in sorted(classifications.items())
        if info.classification == "runtime-safe candidate feature" and name in columns
    ]


def is_before_actual_activation(row: dict[str, str]) -> bool:
    start_time = parse_float(row.get("window_start_s"))
    activation_time = parse_float(row.get("protection_activation_time_s"))
    if start_time is None:
        return False
    if activation_time is None or activation_time < 0:
        return True
    return start_time < activation_time


def label_audit_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        label = row.get("label", "")
        if label not in SUPPORTED_LABEL_SOURCE_VALUES:
            continue
        if row.get("label_post_hard_failure") == "1":
            continue
        if not is_before_actual_activation(row):
            continue
        audited = dict(row)
        audited[LABEL_COLUMN] = "1" if label == POSITIVE_LABEL_VALUE else "0"
        selected.append(audited)
    return selected


def numeric_values(rows: list[dict[str, str]], feature: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = parse_float(row.get(feature))
        if value is not None:
            values.append(value)
    return values


def dominant_value_fraction(values: list[float]) -> float:
    if not values:
        return 0.0
    rounded = [round(value, 12) for value in values]
    counts = Counter(rounded)
    return max(counts.values()) / len(values)


def feature_stats(
    all_rows: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
    features: list[str],
    classifications: dict[str, FeatureClassification],
) -> tuple[list[FeatureStats], list[str], list[str]]:
    stats: list[FeatureStats] = []
    selected: list[str] = []
    excluded: list[str] = []
    config_run_keys = {
        (row.get("config_name", ""), row.get("run_number", ""))
        for row in all_rows
    }

    for feature in features:
        info = classifications[feature]
        all_values = numeric_values(all_rows, feature)
        audit_values = numeric_values(audit_rows, feature)
        missing = len(all_rows) - len(all_values)
        audit_missing = len(audit_rows) - len(audit_values)
        unique_values = len({round(value, 12) for value in all_values})
        constant = unique_values <= 1
        near_constant = dominant_value_fraction(all_values) >= NEAR_CONSTANT_DOMINANCE
        populated_groups = {
            (row.get("config_name", ""), row.get("run_number", ""))
            for row in all_rows
            if parse_float(row.get(feature)) is not None
        }

        exclusion_reason = ""
        if feature not in all_rows[0]:
            exclusion_reason = "missing from dataset"
        elif not audit_values:
            exclusion_reason = "all missing in pre-activation/pre-failure audit rows"
        elif constant:
            exclusion_reason = "constant"

        selected_for_benchmark = exclusion_reason == ""
        if selected_for_benchmark:
            selected.append(feature)
        else:
            excluded.append(feature)

        mean_value = fmean(all_values) if all_values else None
        std_value = pstdev(all_values) if len(all_values) > 1 else (0.0 if all_values else None)
        stats.append(
            FeatureStats(
                feature=feature,
                group=info.group,
                classification=info.classification,
                provenance=info.provenance,
                note=info.note,
                rows=len(all_rows),
                missing=missing,
                missing_rate=missing / len(all_rows) if all_rows else 1.0,
                pre_activation_missing_rate=audit_missing / len(audit_rows) if audit_rows else 1.0,
                unique_values=unique_values,
                near_constant=near_constant,
                constant=constant,
                min_value=format_float(min(all_values) if all_values else None),
                mean_value=format_float(mean_value),
                std_value=format_float(std_value),
                max_value=format_float(max(all_values) if all_values else None),
                populated_config_runs=len(populated_groups & config_run_keys),
                selected_for_benchmark=selected_for_benchmark,
                exclusion_reason=exclusion_reason,
            )
        )
    return stats, selected, excluded


def to_matrix(rows: list[dict[str, str]], features: list[str]):
    import numpy as np

    matrix = []
    for row in rows:
        matrix.append([
            math.nan if parse_float(row.get(feature)) is None else parse_float(row.get(feature))
            for feature in features
        ])
    return np.array(matrix, dtype=float)


def labels_array(rows: list[dict[str, str]]):
    import numpy as np

    return np.array([int(row[LABEL_COLUMN]) for row in rows], dtype=int)


def group_labels(rows: list[dict[str, str]]) -> list[str]:
    return [f"{row.get('config_name', '')}::run{row.get('run_number', '')}" for row in rows]


def build_models():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import LinearSVC
    from sklearn.tree import DecisionTreeClassifier

    return {
        "logistic_regression": LogisticRegression(max_iter=2000, class_weight="balanced", random_state=7),
        "linear_svm": LinearSVC(class_weight="balanced", random_state=7, max_iter=20000),
        "shallow_tree": DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=7),
        "random_forest": RandomForestClassifier(
            n_estimators=200,
            max_depth=5,
            class_weight="balanced",
            random_state=7,
        ),
    }


def make_pipeline(model, scale: bool):
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    steps: list[tuple[str, object]] = [("imputer", SimpleImputer(strategy="median"))]
    if scale:
        steps.append(("scaler", StandardScaler()))
    steps.append(("model", model))
    return Pipeline(steps)


def score_model(pipeline, x_matrix):
    import numpy as np

    model = pipeline.named_steps["model"]
    if hasattr(model, "predict_proba"):
        scores = pipeline.predict_proba(x_matrix)[:, 1]
        threshold = 0.5
        positives = scores >= threshold
        return scores, positives, threshold, "predict_proba>=0.5"
    scores = pipeline.decision_function(x_matrix)
    if len(np.asarray(scores).shape) > 1:
        scores = scores[:, -1]
    threshold = 0.0
    positives = scores >= threshold
    return scores, positives, threshold, "decision_function>=0"


def benchmark_feature_set(
    rows: list[dict[str, str]],
    feature_set_name: str,
    features: list[str],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    import numpy as np
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
    from sklearn.model_selection import GroupKFold

    if not features:
        return [], {"error": "no selected features"}

    x_matrix = to_matrix(rows, features)
    y = labels_array(rows)
    groups = group_labels(rows)
    unique_groups = sorted(set(groups))
    n_splits = min(5, len(unique_groups))
    if n_splits < 2 or len(set(y)) < 2:
        return [], {"error": "not enough groups or classes for grouped evaluation"}

    models = build_models()
    fold_rows: list[dict[str, object]] = []
    group_kfold = GroupKFold(n_splits=n_splits)

    for model_name, model in models.items():
        scale = model_name in {"logistic_regression", "linear_svm"}
        for fold_index, (train_idx, test_idx) in enumerate(group_kfold.split(x_matrix, y, groups), start=1):
            pipeline = make_pipeline(model, scale=scale)
            pipeline.fit(x_matrix[train_idx], y[train_idx])
            y_pred = pipeline.predict(x_matrix[test_idx])
            scores, _, _, score_rule = score_model(pipeline, x_matrix[test_idx])
            tn, fp, fn, tp = confusion_matrix(y[test_idx], y_pred, labels=[0, 1]).ravel()
            try:
                auc_value = roc_auc_score(y[test_idx], scores) if len(set(y[test_idx])) == 2 else None
            except ValueError:
                auc_value = None
            fold_rows.append(
                {
                    "scenario": DEFAULT_SCENARIO,
                    "feature_set": feature_set_name,
                    "model": model_name,
                    "evaluation": "group_kfold_config_run",
                    "fold": fold_index,
                    "rows_train": len(train_idx),
                    "rows_test": len(test_idx),
                    "features": len(features),
                    "groups_total": len(unique_groups),
                    "positive_class_rate_train": float(np.mean(y[train_idx])),
                    "positive_class_rate_test": float(np.mean(y[test_idx])),
                    "accuracy": accuracy_score(y[test_idx], y_pred),
                    "precision": precision_score(y[test_idx], y_pred, zero_division=0),
                    "recall": recall_score(y[test_idx], y_pred, zero_division=0),
                    "f1": f1_score(y[test_idx], y_pred, zero_division=0),
                    "roc_auc": "" if auc_value is None else auc_value,
                    "tn": int(tn),
                    "fp": int(fp),
                    "fn": int(fn),
                    "tp": int(tp),
                    "score_rule": score_rule,
                }
            )

    return fold_rows, {
        "rows": len(rows),
        "features": len(features),
        "groups": len(unique_groups),
        "positive_class_rate": float(np.mean(y)),
    }


def summarize_benchmark(fold_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in fold_rows:
        grouped[(str(row["feature_set"]), str(row["model"]))].append(row)

    summaries: list[dict[str, object]] = []
    for (feature_set, model), rows in sorted(grouped.items()):
        summary: dict[str, object] = {
            "scenario": DEFAULT_SCENARIO,
            "feature_set": feature_set,
            "model": model,
            "evaluation": "group_kfold_config_run_mean",
            "folds": len(rows),
            "features": rows[0]["features"],
            "rows_test_total": sum(int(row["rows_test"]) for row in rows),
            "tn": sum(int(row["tn"]) for row in rows),
            "fp": sum(int(row["fp"]) for row in rows),
            "fn": sum(int(row["fn"]) for row in rows),
            "tp": sum(int(row["tp"]) for row in rows),
        }
        for metric in ["accuracy", "precision", "recall", "f1", "positive_class_rate_test"]:
            values = [float(row[metric]) for row in rows]
            summary[f"{metric}_mean"] = fmean(values)
            summary[f"{metric}_std"] = pstdev(values) if len(values) > 1 else 0.0
        auc_values = [float(row["roc_auc"]) for row in rows if row["roc_auc"] != ""]
        summary["roc_auc_mean"] = fmean(auc_values) if auc_values else ""
        summary["roc_auc_std"] = pstdev(auc_values) if len(auc_values) > 1 else (0.0 if auc_values else "")
        summaries.append(summary)
    return summaries


def train_full_pipeline(rows: list[dict[str, str]], features: list[str], model_name: str):
    models = build_models()
    model = models[model_name]
    pipeline = make_pipeline(model, scale=model_name in {"logistic_regression", "linear_svm"})
    pipeline.fit(to_matrix(rows, features), labels_array(rows))
    return pipeline


def decision_timing_rows(
    all_rows: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
    feature_sets: dict[str, list[str]],
) -> list[dict[str, object]]:
    timing_rows: list[dict[str, object]] = []
    by_run: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in all_rows:
        if row.get("label") == "convergence" or row.get("label_post_hard_failure") == "1":
            continue
        by_run[(row.get("config_name", ""), row.get("run_number", ""))].append(row)

    for feature_set_name, features in feature_sets.items():
        if not features:
            continue
        for model_name in build_models():
            pipeline = train_full_pipeline(audit_rows, features, model_name)
            for (config_name, run_number), rows in sorted(by_run.items()):
                rows = sorted(rows, key=lambda item: parse_float(item.get("window_end_s")) or -1)
                actual_activation = parse_float(rows[0].get("protection_activation_time_s")) if rows else None
                hard_failure = parse_float(rows[0].get("hard_failure_time_s")) if rows else None
                observed_rows: list[dict[str, str]] = []
                censored = False
                for row in rows:
                    window_end = parse_float(row.get("window_end_s"))
                    if window_end is None:
                        continue
                    if hard_failure is not None and window_end > hard_failure:
                        continue
                    if actual_activation is not None and actual_activation >= 0 and window_end > actual_activation:
                        censored = True
                        break
                    observed_rows.append(row)
                if not observed_rows:
                    continue

                x_matrix = to_matrix(observed_rows, features)
                scores, positives, threshold, score_rule = score_model(pipeline, x_matrix)
                streak = 0
                first_positive_time: float | None = None
                offline_activation_time: float | None = None
                for row, score, positive in zip(observed_rows, scores, positives):
                    decision_time = parse_float(row.get("window_end_s"))
                    if positive:
                        if first_positive_time is None:
                            first_positive_time = decision_time
                        streak += 1
                    else:
                        streak = 0
                    if streak >= STREAK_REQUIRED:
                        offline_activation_time = decision_time
                        break

                timing_rows.append(
                    {
                        "scenario": DEFAULT_SCENARIO,
                        "degradation_profile": rows[0].get("degradation_profile", "") if rows else "",
                        "feature_set": feature_set_name,
                        "model": model_name,
                        "config_name": config_name,
                        "run_number": run_number,
                        "first_positive_time_s": "" if first_positive_time is None else first_positive_time,
                        "offline_activation_time_s": "" if offline_activation_time is None else offline_activation_time,
                        "offline_lead_time_s": (
                            "" if offline_activation_time is None or hard_failure is None else hard_failure - offline_activation_time
                        ),
                        "actual_activation_time_s": "" if actual_activation is None or actual_activation < 0 else actual_activation,
                        "actual_lead_time_s": (
                            "" if actual_activation is None or actual_activation < 0 or hard_failure is None else hard_failure - actual_activation
                        ),
                        "hard_failure_time_s": "" if hard_failure is None else hard_failure,
                        "censored_by_observed_activation": 1 if censored else 0,
                        "observed_windows_scored": len(observed_rows),
                        "streak_required": STREAK_REQUIRED,
                        "threshold": threshold,
                        "score_rule": score_rule,
                        "last_score_before_censor": scores[-1],
                    }
                )
    return timing_rows


def feature_importance_rows(
    audit_rows: list[dict[str, str]],
    feature_sets: dict[str, list[str]],
    classifications: dict[str, FeatureClassification],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for feature_set_name, features in feature_sets.items():
        if not features:
            continue
        for model_name in build_models():
            pipeline = train_full_pipeline(audit_rows, features, model_name)
            model = pipeline.named_steps["model"]
            values = None
            importance_type = ""
            if hasattr(model, "coef_"):
                values = model.coef_[0]
                importance_type = "coefficient"
            elif hasattr(model, "feature_importances_"):
                values = model.feature_importances_
                importance_type = "feature_importance"
            if values is None:
                continue
            for feature, value in sorted(zip(features, values), key=lambda item: abs(float(item[1])), reverse=True):
                info = classifications.get(
                    feature,
                    FeatureClassification(feature, "baseline_runtime", "runtime-safe candidate feature", "current runtime feature", ""),
                )
                rows.append(
                    {
                        "scenario": DEFAULT_SCENARIO,
                        "feature_set": feature_set_name,
                        "model": model_name,
                        "feature": feature,
                        "importance_type": importance_type,
                        "value": float(value),
                        "abs_value": abs(float(value)),
                        "classification": info.classification,
                        "group": info.group,
                        "provenance": info.provenance,
                        "note": info.note,
                    }
                )
    return rows


def high_correlation_pairs(rows: list[dict[str, str]], features: list[str]) -> list[tuple[str, str, float]]:
    import numpy as np
    from sklearn.impute import SimpleImputer

    if len(features) < 2 or not rows:
        return []
    matrix = to_matrix(rows, features)
    imputed = SimpleImputer(strategy="median").fit_transform(matrix)
    stds = np.std(imputed, axis=0)
    active_indices = [index for index, std in enumerate(stds) if std > 1e-12]
    pairs: list[tuple[str, str, float]] = []
    for left_pos, left_index in enumerate(active_indices):
        for right_index in active_indices[left_pos + 1:]:
            corr = float(np.corrcoef(imputed[:, left_index], imputed[:, right_index])[0, 1])
            if not math.isnan(corr) and abs(corr) >= CORRELATION_THRESHOLD:
                pairs.append((features[left_index], features[right_index], corr))
    return sorted(pairs, key=lambda item: abs(item[2]), reverse=True)


def write_feature_quality_csv(path: Path, stats: list[FeatureStats]) -> None:
    rows = [
        {
            "feature": item.feature,
            "group": item.group,
            "classification": item.classification,
            "provenance": item.provenance,
            "note": item.note,
            "rows": item.rows,
            "missing": item.missing,
            "missing_rate": item.missing_rate,
            "pre_activation_missing_rate": item.pre_activation_missing_rate,
            "unique_values": item.unique_values,
            "near_constant": int(item.near_constant),
            "constant": int(item.constant),
            "min": item.min_value,
            "mean": item.mean_value,
            "std": item.std_value,
            "max": item.max_value,
            "populated_config_runs": item.populated_config_runs,
            "selected_for_benchmark": int(item.selected_for_benchmark),
            "exclusion_reason": item.exclusion_reason,
        }
        for item in stats
    ]
    atomic_write_csv(
        path,
        rows,
        [
            "feature",
            "group",
            "classification",
            "provenance",
            "note",
            "rows",
            "missing",
            "missing_rate",
            "pre_activation_missing_rate",
            "unique_values",
            "near_constant",
            "constant",
            "min",
            "mean",
            "std",
            "max",
            "populated_config_runs",
            "selected_for_benchmark",
            "exclusion_reason",
        ],
    )


def benchmark_report_text(
    scenario: str,
    paths: dict[str, Path],
    all_rows: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
    runtime_features: list[str],
    selected_extended: list[str],
    excluded_extended: list[str],
    correlation_pairs: list[tuple[str, str, float]],
    benchmark_summary: list[dict[str, object]],
    timing_rows: list[dict[str, object]],
    importance_rows: list[dict[str, object]],
) -> str:
    label_counts = Counter(row.get("label", "") for row in all_rows)
    profile_counts = Counter(row.get("degradation_profile", "") or "none" for row in all_rows)
    audit_label_counts = Counter(row[LABEL_COLUMN] for row in audit_rows)
    lines = [
        f"Offline ML Feasibility Audit: {scenario}",
        "=" * (len(scenario) + 31),
        "",
        "Scope:",
        "- Offline analysis only; no deployed AI-MRCE runtime artifacts were modified.",
        "- The selected target is a simulator-derived, scenario-conditioned feasibility label.",
        "- GroupKFold uses config/run groups to avoid adjacent time windows from the same run appearing in both train and test.",
        "",
        "Inputs:",
    ]
    for name, path in paths.items():
        lines.append(f"- {name}: {path}")
    lines.extend(
        [
            "",
            "Candidate label decision:",
            f"- label name: {LABEL_COLUMN}",
            "- positive class: current row label is critical_congestion",
            "- negative class: current row label is baseline or rising_congestion",
            "- excluded rows: convergence, failed/post-hard-failure, and rows after observed protection activation",
            "- interpretation: pre-failure protect/no-protect feasibility label for this deterministic degraded-link cohort",
            "- leakage note: time_to_hard_failure and hardFailureTime are not model inputs; the label remains simulator-derived and scenario-conditioned.",
            "",
            f"Dataset rows: {len(all_rows)}",
            f"ML audit rows after filtering: {len(audit_rows)}",
            f"Original label counts: {dict(sorted(label_counts.items()))}",
            f"Rows by degradation profile: {dict(sorted(profile_counts.items()))}",
            f"Audit target counts: {dict(sorted(audit_label_counts.items()))}",
            f"Runtime-safe candidate features from classification: {len(runtime_features)}",
            f"Selected extended features for benchmark: {len(selected_extended)}",
            f"Excluded runtime-safe candidates: {len(excluded_extended)}",
            "",
            "High-correlation feature pairs (absolute Pearson >= 0.995, top 20):",
        ]
    )
    if not correlation_pairs:
        lines.append("- none")
    else:
        for left, right, corr in correlation_pairs[:20]:
            lines.append(f"- {left} <-> {right}: corr={corr:.6f}")

    lines.extend(["", "Benchmark summary:"])
    if not benchmark_summary:
        lines.append("- benchmark did not run")
    else:
        for row in benchmark_summary:
            lines.append(
                "- "
                f"{row['feature_set']} / {row['model']}: "
                f"F1={row['f1_mean']:.4f}, precision={row['precision_mean']:.4f}, "
                f"recall={row['recall_mean']:.4f}, accuracy={row['accuracy_mean']:.4f}, "
                f"ROC-AUC={row['roc_auc_mean'] if row['roc_auc_mean'] != '' else 'n/a'}, "
                f"features={row['features']}"
            )

    lines.extend(["", "Offline decision-timing proxy:"])
    if not timing_rows:
        lines.append("- not generated")
    else:
        grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
        for row in timing_rows:
            activation = parse_float(row.get("offline_activation_time_s"))
            if activation is not None:
                grouped[(str(row["feature_set"]), str(row["model"]))].append(activation)
        for key, values in sorted(grouped.items()):
            feature_set, model = key
            lines.append(
                f"- {feature_set} / {model}: activations={len(values)}, "
                f"mean={fmean(values):.3f}s, std={pstdev(values) if len(values) > 1 else 0.0:.3f}s"
            )

    lines.extend(["", "Top feature-importance signals by model (top 20 absolute values):"])
    for row in importance_rows[:20]:
        lines.append(
            "- "
            f"{row['feature_set']} / {row['model']} / {row['feature']}: "
            f"{row['importance_type']}={float(row['value']):.6f}, "
            f"classification={row['classification']}"
        )

    lines.extend(
        [
            "",
            "Preliminary interpretation:",
            "- Extended telemetry is suitable for offline feasibility analysis, but it remains scenario-conditioned.",
            "- Any apparent metric improvement may reflect the deterministic degraded-link cohort and should not be treated as production generalization.",
            "- Runtime export v2 is not recommended until the selected feature subset is reviewed, labels are finalized, and a separate deployment-artifact validation pass is run.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    start = time.perf_counter()
    args = parse_args()
    scenario = args.scenario
    global DEFAULT_SCENARIO
    DEFAULT_SCENARIO = scenario

    paths = scenario_paths(args)
    print(f"[offline_ml_audit] Scenario: {scenario}")
    for name, path in paths.items():
        print(f"[offline_ml_audit] {name}: {path}")

    all_rows = read_csv_rows(paths["extended_dataset"])
    _baseline_rows = read_csv_rows(paths["baseline_dataset"])
    _outcome_rows = read_csv_rows(paths["outcome_summary"])
    classifications = parse_feature_classification(paths["classification"])
    columns = set(all_rows[0].keys()) if all_rows else set()

    runtime_features = runtime_safe_features(classifications, columns)
    audit_rows = label_audit_rows(all_rows)
    if not audit_rows:
        raise SystemExit("No safe pre-failure audit rows were available; offline ML benchmark stopped.")

    stats, selected_extended, excluded_extended = feature_stats(
        all_rows,
        audit_rows,
        runtime_features,
        classifications,
    )
    baseline_selected = [feature for feature in BASELINE_FEATURES if feature in columns]

    feature_sets = {
        "baseline_four_feature": baseline_selected,
        "extended_runtime_safe": selected_extended,
    }

    all_fold_rows: list[dict[str, object]] = []
    benchmark_summaries: list[dict[str, object]] = []
    for feature_set_name, features in feature_sets.items():
        fold_rows, summary = benchmark_feature_set(audit_rows, feature_set_name, features)
        if summary.get("error"):
            print(f"[offline_ml_audit] Benchmark skipped for {feature_set_name}: {summary['error']}")
            continue
        all_fold_rows.extend(fold_rows)
    benchmark_summaries = summarize_benchmark(all_fold_rows)

    timing_rows = decision_timing_rows(all_rows, audit_rows, feature_sets)
    importance_rows = feature_importance_rows(audit_rows, feature_sets, classifications)
    importance_rows.sort(key=lambda row: (row["feature_set"], row["model"], -float(row["abs_value"])))
    correlation_pairs = high_correlation_pairs(audit_rows, selected_extended)

    quality_csv = ML_AUDIT_DIR / f"{scenario}_extended_feature_quality.csv"
    quality_report = ML_AUDIT_DIR / f"{scenario}_extended_feature_quality_report.txt"
    benchmark_csv = ML_AUDIT_DIR / f"{scenario}_offline_ml_benchmark.csv"
    benchmark_report = ML_AUDIT_DIR / f"{scenario}_offline_ml_benchmark_report.txt"
    timing_csv = ML_AUDIT_DIR / f"{scenario}_offline_decision_timing.csv"
    importance_csv = ML_AUDIT_DIR / f"{scenario}_feature_importance.csv"
    audit_path = AUDIT_DIR / "offline_ml_extended_features_audit_applied.txt"

    write_feature_quality_csv(quality_csv, stats)

    quality_lines = [
        f"Extended Feature Quality Report: {scenario}",
        "=" * (len(scenario) + 33),
        "",
        f"runtime_safe_candidate_features: {len(runtime_features)}",
        f"selected_for_benchmark: {len(selected_extended)}",
        f"excluded_runtime_safe_candidates: {len(excluded_extended)}",
        f"audit_rows_pre_activation_pre_failure: {len(audit_rows)}",
        "",
        "Excluded runtime-safe candidates:",
    ]
    if not excluded_extended:
        quality_lines.append("- none")
    else:
        for item in stats:
            if item.feature in excluded_extended:
                quality_lines.append(f"- {item.feature}: {item.exclusion_reason}")
    quality_lines.extend(["", "Near-constant runtime-safe candidates:"])
    near_constant = [item for item in stats if item.near_constant]
    if not near_constant:
        quality_lines.append("- none")
    else:
        for item in near_constant:
            quality_lines.append(f"- {item.feature}: unique={item.unique_values}, missing_rate={item.missing_rate:.4f}")
    quality_lines.extend(["", "High-correlation pairs are summarized in the benchmark report."])
    atomic_write_text(quality_report, "\n".join(quality_lines) + "\n")

    atomic_write_csv(
        benchmark_csv,
        benchmark_summaries,
        list(benchmark_summaries[0].keys()) if benchmark_summaries else ["scenario", "feature_set", "model"],
    )
    atomic_write_csv(
        timing_csv,
        timing_rows,
        list(timing_rows[0].keys()) if timing_rows else ["scenario", "feature_set", "model"],
    )
    atomic_write_csv(
        importance_csv,
        importance_rows,
        list(importance_rows[0].keys()) if importance_rows else ["scenario", "feature_set", "model", "feature"],
    )

    report_text = benchmark_report_text(
        scenario,
        paths,
        all_rows,
        audit_rows,
        runtime_features,
        selected_extended,
        excluded_extended,
        correlation_pairs,
        benchmark_summaries,
        timing_rows,
        importance_rows,
    )
    atomic_write_text(benchmark_report, report_text + "\n")
    atomic_write_text(
        audit_path,
        report_text
        + "\nGenerated outputs:\n"
        + f"- {quality_csv}\n"
        + f"- {quality_report}\n"
        + f"- {benchmark_csv}\n"
        + f"- {benchmark_report}\n"
        + f"- {timing_csv}\n"
        + f"- {importance_csv}\n"
        + "\nValidation note: generated by offline_ml_audit.py; no runtime artifacts were modified.\n",
    )

    print(f"[offline_ml_audit] Runtime-safe candidate features: {len(runtime_features)}")
    print(f"[offline_ml_audit] Selected extended features: {len(selected_extended)}")
    print(f"[offline_ml_audit] ML audit rows: {len(audit_rows)}")
    print(f"[offline_ml_audit] Wrote feature quality CSV: {quality_csv}")
    print(f"[offline_ml_audit] Wrote benchmark CSV: {benchmark_csv}")
    print(f"[offline_ml_audit] Wrote decision timing CSV: {timing_csv}")
    print(f"[offline_ml_audit] Wrote feature importance CSV: {importance_csv}")
    print(f"[offline_ml_audit] Wrote audit note: {audit_path}")
    print(f"[offline_ml_audit] Total elapsed: {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
