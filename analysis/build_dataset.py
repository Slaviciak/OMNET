#!/usr/bin/env python3
"""
Build an ML-ready and outcome-aware CSV dataset from OMNeT++ result files.

Assumptions:
- Input files are OMNeT++ .vec files under results/<scenario>/eval/ by default.
- Matching .sca files are used only for project-local controller outcome
  measurement support such as protection activation timing.
- Windows are fixed-size and non-overlapping.
- Labels remain scenario-phase supervision labels assigned from configurable
  time boundaries using the window start.
- Recovery and protection outcome fields are a separate project-local
  measurement layer derived from observable receiver-side telemetry plus known
  scripted event times. They are not protocol-standard fields and they are not
  replacements for the supervision labels.
- Receiver-side metrics may be absent in some runs; missing values are left
  blank where possible.
- State-like vectors and event/sample-like vectors are summarized separately so
  queue and controller metrics are not averaged like per-packet delay samples.
- Throughput vectors are rate samples, so they are summarized from actual
  nonnegative samples inside each window only.
- Older runs using legacy or debug config names may be normalized to the main
  config name for dataset consistency.
- The CLI uses scenario presets so later scenario-specific builders can follow
  the same style without changing the workflow.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean


WINDOW_SIZE_SECONDS = 1.0

SMALL_REACTIVE_FAILURE_TIME_SECONDS = 20.0
SMALL_PROACTIVE_PROTECTION_TIME_SECONDS = 18.0
SMALL_PROACTIVE_HARD_FAILURE_TIME_SECONDS = 20.0

DEGRADATION_START_SECONDS = 20.0
PRE_FAILURE_START_SECONDS = 40.0
HARD_FAILURE_TIME_SECONDS = 45.0

CONGESTION_CONVERGENCE_END_SECONDS = 20.0
CONGESTION_BASELINE_END_SECONDS = 50.0
CONGESTION_RISING_END_SECONDS = 125.0
CONGESTION_CRITICAL_END_SECONDS = 150.0
CONGESTION_HARD_FAILURE_TIME_SECONDS = 150.0

REGIONAL_REACTIVE_FAILURE_TIME_SECONDS = 40.0
REGIONAL_REACTIVE_DISRUPTION_END_SECONDS = 50.0

REGIONAL_DEGRADATION_START_SECONDS = 35.0
REGIONAL_DEGRADATION_END_SECONDS = 55.0
REGIONAL_HARD_FAILURE_TIME_SECONDS = 60.0

REGIONAL_CONGESTION_CONVERGENCE_END_SECONDS = 20.0
REGIONAL_CONGESTION_BASELINE_END_SECONDS = 35.0
REGIONAL_CONGESTION_RISING_END_SECONDS = 80.0
REGIONAL_CONGESTION_CRITICAL_END_SECONDS = 125.0
REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS = 125.0

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = "linkdegradation"
BOTTLE_NECK_QUEUE_MODULE_SUFFIX = ".r2.eth[1].queue"
REGIONAL_BOTTLENECK_QUEUE_MODULE_SUFFIX = ".coreNW.eth[1].queue"
HOSTB_APP_RE = re.compile(r".*\.hostB\.app\[(\d+)\]$")
TARGET_CONTROLLER_SCALAR_NAMES = {"protectionActivated", "protectionActivationTime"}
REGIONALBACKBONE_FAMILY_SCENARIOS = {"regionalbackbone", "regionalbackbone_congestion_protection"}

REGIONALBACKBONE_DATASET_CONFIGS = {
    "RegionalBackboneBaseline",
    "RegionalBackboneReactiveFailure",
    "RegionalBackboneControlledDegradation",
    "RegionalBackboneCongestionDegradation",
}
REGIONALBACKBONE_OPTIONAL_RUNTIME_CONFIGS = {
    "RegionalBackboneAiMrceRuleBased",
    "RegionalBackboneAiMrceLogReg",
    "RegionalBackboneAiMrceLinearSvm",
    "RegionalBackboneAiMrceShallowTree",
}
REGIONALBACKBONE_CONGESTION_STYLE_CONFIGS = {
    "RegionalBackboneCongestionDegradation",
    "RegionalBackboneAiMrceRuleBased",
    "RegionalBackboneAiMrceLogReg",
    "RegionalBackboneAiMrceLinearSvm",
    "RegionalBackboneAiMrceShallowTree",
}


@dataclass(frozen=True)
class OutcomeProfile:
    hard_failure_time_s: float | None
    protection_mode: str
    monitored_app_index: int
    packet_size_bits: float
    send_interval_s: float
    flow_start_time_s: float
    protection_expected: bool = False
    scheduled_protection_time_s: float | None = None


SCENARIO_PRESETS = {
    "linkdegradation": {
        "results_dir": PROJECT_ROOT / "results" / "linkdegradation" / "eval",
        "output_file": PROJECT_ROOT / "analysis" / "output" / "linkdegradation_dataset.csv",
        "supported_configs": {"MildLinear", "StrongLinear", "UnstableLinear", "StagedRealistic"},
        "config_aliases": {
            "LinkDegradation": "MildLinear",
        },
        "default_sim_time_limit": 60.0,
    },
    "congestiondegradation": {
        "results_dir": PROJECT_ROOT / "results" / "congestiondegradation" / "eval",
        "output_file": PROJECT_ROOT / "analysis" / "output" / "congestiondegradation_dataset.csv",
        "supported_configs": {"CongestionDegradation", "CongestionDegradationMild"},
        "config_aliases": {},
        "default_sim_time_limit": 180.0,
    },
    "reactivefailure": {
        "results_dir": PROJECT_ROOT / "results" / "reactivefailure" / "eval",
        "output_file": PROJECT_ROOT / "analysis" / "output" / "reactivefailure_dataset.csv",
        "supported_configs": {"ReactiveFailure"},
        "config_aliases": {},
        "default_sim_time_limit": 60.0,
    },
    "proactiveswitch": {
        "results_dir": PROJECT_ROOT / "results" / "proactiveswitch" / "eval",
        "output_file": PROJECT_ROOT / "analysis" / "output" / "proactiveswitch_dataset.csv",
        "supported_configs": {"ProactiveSwitch"},
        "config_aliases": {},
        "default_sim_time_limit": 60.0,
    },
    "regionalbackbone": {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "eval",
        "output_file": PROJECT_ROOT / "analysis" / "output" / "regionalbackbone_dataset.csv",
        "supported_configs": REGIONALBACKBONE_DATASET_CONFIGS,
        "optional_runtime_configs": REGIONALBACKBONE_OPTIONAL_RUNTIME_CONFIGS,
        "config_aliases": {},
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            "RegionalBackboneBaseline": 60.0,
            "RegionalBackboneReactiveFailure": 80.0,
            "RegionalBackboneControlledDegradation": 90.0,
            "RegionalBackboneCongestionDegradation": 150.0,
            "RegionalBackboneAiMrceRuleBased": 150.0,
            "RegionalBackboneAiMrceLogReg": 150.0,
            "RegionalBackboneAiMrceLinearSvm": 150.0,
            "RegionalBackboneAiMrceShallowTree": 150.0,
        },
    },
    "regionalbackbone_congestion_protection": {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "congestion_protection_cohort",
        "output_file": PROJECT_ROOT / "analysis" / "output" / "regionalbackbone_congestion_protection_multirun_dataset.csv",
        "supported_configs": {
            "RegionalBackboneCongestionDegradation",
            "RegionalBackboneAiMrceRuleBased",
            "RegionalBackboneAiMrceLogReg",
            "RegionalBackboneAiMrceLinearSvm",
            "RegionalBackboneAiMrceShallowTree",
        },
        "config_aliases": {
            "RegionalBackboneCongestionDegradationCohort": "RegionalBackboneCongestionDegradation",
            "RegionalBackboneAiMrceRuleBasedCohort": "RegionalBackboneAiMrceRuleBased",
            "RegionalBackboneAiMrceLogRegCohort": "RegionalBackboneAiMrceLogReg",
            "RegionalBackboneAiMrceLinearSvmCohort": "RegionalBackboneAiMrceLinearSvm",
            "RegionalBackboneAiMrceShallowTreeCohort": "RegionalBackboneAiMrceShallowTree",
        },
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            "RegionalBackboneCongestionDegradation": 150.0,
            "RegionalBackboneAiMrceRuleBased": 150.0,
            "RegionalBackboneAiMrceLogReg": 150.0,
            "RegionalBackboneAiMrceLinearSvm": 150.0,
            "RegionalBackboneAiMrceShallowTree": 150.0,
        },
    },
}


def parse_time_value(raw: str) -> float | None:
    raw = raw.strip()
    if raw.endswith("s"):
        raw = raw[:-1]
    try:
        return float(raw)
    except ValueError:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a windowed dataset from OMNeT++ result files.")
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help=f"Scenario preset to use for defaults. Currently supported: {', '.join(sorted(SCENARIO_PRESETS))}.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Directory containing .vec files. Defaults to the preset results directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV path. Defaults to analysis/output/<scenario>_dataset.csv.",
    )
    parser.add_argument(
        "--include-runtime-protection-configs",
        action="store_true",
        help=(
            "For regionalbackbone only, also include the optional AI-MRCE runtime "
            "prototype configs in the dataset. This is intended for outcome "
            "evaluation and is kept opt-in so the existing main dataset batch "
            "semantics do not change silently."
        ),
    )
    return parser.parse_args()


def get_scenario_preset(scenario: str) -> dict[str, object]:
    preset = SCENARIO_PRESETS.get(scenario)
    if preset is None:
        supported = ", ".join(sorted(SCENARIO_PRESETS))
        raise SystemExit(f"Unsupported scenario '{scenario}'. Supported scenarios: {supported}")
    return preset


def effective_supported_configs(preset: dict[str, object], include_runtime_protection_configs: bool) -> set[str]:
    supported_configs = set(preset["supported_configs"])
    if include_runtime_protection_configs:
        supported_configs.update(preset.get("optional_runtime_configs", set()))
    return supported_configs


def normalize_config_name(name: str, config_aliases: dict[str, str]) -> str:
    return config_aliases.get(name, name)


def label_for_linkdegradation_window(window_start: float) -> str:
    if window_start < DEGRADATION_START_SECONDS:
        return "normal"
    if window_start < PRE_FAILURE_START_SECONDS:
        return "degraded"
    if window_start < HARD_FAILURE_TIME_SECONDS:
        return "pre_failure"
    return "failed"


def label_for_congestiondegradation_window(window_start: float) -> str:
    if window_start < CONGESTION_CONVERGENCE_END_SECONDS:
        return "convergence"
    if window_start < CONGESTION_BASELINE_END_SECONDS:
        return "baseline"
    if window_start < CONGESTION_RISING_END_SECONDS:
        return "rising_congestion"
    if window_start < CONGESTION_CRITICAL_END_SECONDS:
        return "critical_congestion"
    return "failed"


def label_for_reactivefailure_window(window_start: float) -> str:
    if window_start < SMALL_REACTIVE_FAILURE_TIME_SECONDS:
        return "normal"
    if window_start < SMALL_REACTIVE_FAILURE_TIME_SECONDS + 10.0:
        return "reactive_disruption"
    return "post_reroute"


def label_for_proactiveswitch_window(window_start: float) -> str:
    if window_start < SMALL_PROACTIVE_PROTECTION_TIME_SECONDS:
        return "normal"
    if window_start < SMALL_PROACTIVE_HARD_FAILURE_TIME_SECONDS:
        return "protected_pre_failure"
    return "post_failure_protected"


def label_for_regionalbackbone_window(config_name: str, window_start: float) -> str:
    if config_name == "RegionalBackboneBaseline":
        return "normal"

    if config_name == "RegionalBackboneReactiveFailure":
        if window_start < REGIONAL_REACTIVE_FAILURE_TIME_SECONDS:
            return "normal"
        if window_start < REGIONAL_REACTIVE_DISRUPTION_END_SECONDS:
            return "reactive_disruption"
        return "post_reroute"

    if config_name == "RegionalBackboneControlledDegradation":
        if window_start < REGIONAL_DEGRADATION_START_SECONDS:
            return "normal"
        if window_start < REGIONAL_DEGRADATION_END_SECONDS:
            return "degraded"
        if window_start < REGIONAL_HARD_FAILURE_TIME_SECONDS:
            return "pre_failure"
        return "failed"

    if config_name in REGIONALBACKBONE_CONGESTION_STYLE_CONFIGS:
        # The runtime AI-MRCE configs reuse the congestion-branch supervision
        # timeline intentionally. These labels remain scenario-phase schedule
        # labels, not measured protection-outcome ground truth.
        if window_start < REGIONAL_CONGESTION_CONVERGENCE_END_SECONDS:
            return "convergence"
        if window_start < REGIONAL_CONGESTION_BASELINE_END_SECONDS:
            return "baseline"
        if window_start < REGIONAL_CONGESTION_RISING_END_SECONDS:
            return "rising_congestion"
        if window_start < REGIONAL_CONGESTION_CRITICAL_END_SECONDS:
            return "critical_congestion"
        return "failed"

    raise SystemExit(f"Unsupported regionalbackbone config '{config_name}' for labeling")


def label_for_window(scenario: str, config_name: str, window_start: float) -> str:
    if scenario == "linkdegradation":
        return label_for_linkdegradation_window(window_start)
    if scenario == "congestiondegradation":
        return label_for_congestiondegradation_window(window_start)
    if scenario == "reactivefailure":
        return label_for_reactivefailure_window(window_start)
    if scenario == "proactiveswitch":
        return label_for_proactiveswitch_window(window_start)
    if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
        return label_for_regionalbackbone_window(config_name, window_start)
    raise SystemExit(f"Unsupported scenario '{scenario}' for labeling")


def get_outcome_profile(scenario: str, config_name: str) -> OutcomeProfile:
    if scenario == "linkdegradation":
        return OutcomeProfile(
            hard_failure_time_s=HARD_FAILURE_TIME_SECONDS,
            protection_mode="reactive_only",
            monitored_app_index=0,
            packet_size_bits=512.0 * 8.0,
            send_interval_s=1.0,
            flow_start_time_s=10.0,
        )

    if scenario == "congestiondegradation":
        return OutcomeProfile(
            hard_failure_time_s=CONGESTION_HARD_FAILURE_TIME_SECONDS,
            protection_mode="reactive_only",
            monitored_app_index=0,
            packet_size_bits=256.0 * 8.0,
            send_interval_s=0.01,
            flow_start_time_s=20.0,
        )

    if scenario == "reactivefailure":
        return OutcomeProfile(
            hard_failure_time_s=SMALL_REACTIVE_FAILURE_TIME_SECONDS,
            protection_mode="reactive_only",
            monitored_app_index=0,
            packet_size_bits=512.0 * 8.0,
            send_interval_s=1.0,
            flow_start_time_s=10.0,
        )

    if scenario == "proactiveswitch":
        return OutcomeProfile(
            hard_failure_time_s=SMALL_PROACTIVE_HARD_FAILURE_TIME_SECONDS,
            protection_mode="deterministic_admin_protection",
            monitored_app_index=0,
            packet_size_bits=512.0 * 8.0,
            send_interval_s=1.0,
            flow_start_time_s=10.0,
            protection_expected=True,
            scheduled_protection_time_s=SMALL_PROACTIVE_PROTECTION_TIME_SECONDS,
        )

    if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
        profiles = {
            "RegionalBackboneBaseline": OutcomeProfile(
                hard_failure_time_s=None,
                protection_mode="no_protection_baseline",
                monitored_app_index=0,
                packet_size_bits=512.0 * 8.0,
                send_interval_s=1.0,
                flow_start_time_s=20.0,
            ),
            "RegionalBackboneReactiveFailure": OutcomeProfile(
                hard_failure_time_s=REGIONAL_REACTIVE_FAILURE_TIME_SECONDS,
                protection_mode="reactive_only",
                monitored_app_index=0,
                packet_size_bits=512.0 * 8.0,
                send_interval_s=1.0,
                flow_start_time_s=20.0,
            ),
            "RegionalBackboneControlledDegradation": OutcomeProfile(
                hard_failure_time_s=REGIONAL_HARD_FAILURE_TIME_SECONDS,
                protection_mode="reactive_only",
                monitored_app_index=0,
                packet_size_bits=512.0 * 8.0,
                send_interval_s=1.0,
                flow_start_time_s=20.0,
            ),
            "RegionalBackboneCongestionDegradation": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="reactive_only",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
            ),
            "RegionalBackboneAiMrceRuleBased": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="aimrce_rule_based",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
            ),
            "RegionalBackboneAiMrceLogReg": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="aimrce_logistic_regression",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
            ),
            "RegionalBackboneAiMrceLinearSvm": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="aimrce_linear_svm",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
            ),
            "RegionalBackboneAiMrceShallowTree": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="aimrce_shallow_tree",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
            ),
        }
        profile = profiles.get(config_name)
        if profile is None:
            raise SystemExit(f"Unsupported regionalbackbone config '{config_name}' for outcome profiling")
        return profile

    raise SystemExit(f"Unsupported scenario '{scenario}' for outcome profiling")


def default_sim_time_limit_for_config(
    default_sim_time_limit: float,
    config_name: str,
    default_sim_time_limits_by_config: dict[str, float] | None,
) -> float:
    if default_sim_time_limits_by_config is None:
        return default_sim_time_limit
    return default_sim_time_limits_by_config.get(config_name, default_sim_time_limit)


def last_value_before_or_at(series: list[tuple[float, float]], time_point: float) -> float | None:
    last_value = None
    for timestamp, value in series:
        if timestamp <= time_point:
            last_value = value
        else:
            break
    return last_value


def values_in_window(series: list[tuple[float, float]], window_start: float, window_end: float) -> list[float]:
    return [value for timestamp, value in series if window_start <= timestamp < window_end]


def sample_summary(
    series: list[tuple[float, float]],
    window_start: float,
    window_end: float,
    *,
    nonnegative_only: bool = False,
) -> dict[str, float | str]:
    if not series:
        return {"mean": "", "max": "", "last": ""}

    samples = values_in_window(series, window_start, window_end)
    if nonnegative_only:
        samples = [value for value in samples if value >= 0]
    if not samples:
        return {"mean": "", "max": "", "last": ""}

    return {
        "mean": fmean(samples),
        "max": max(samples),
        "last": samples[-1],
    }


def state_summary(series: list[tuple[float, float]], window_start: float, window_end: float) -> dict[str, float | str]:
    if not series:
        return {"mean": "", "max": "", "last": ""}

    window_duration = window_end - window_start
    if window_duration <= 0:
        return {"mean": "", "max": "", "last": ""}

    current_value = last_value_before_or_at(series, window_start)
    current_time = window_start
    integral = 0.0
    max_value = current_value
    had_state = current_value is not None

    for timestamp, value in series:
        if timestamp < window_start:
            continue
        if timestamp >= window_end:
            break

        if current_value is not None and timestamp > current_time:
            integral += current_value * (timestamp - current_time)

        current_value = value
        current_time = timestamp
        had_state = True
        if max_value is None or value > max_value:
            max_value = value

    if current_value is not None and current_time < window_end:
        integral += current_value * (window_end - current_time)

    if not had_state or max_value is None:
        return {"mean": "", "max": "", "last": ""}

    return {
        "mean": integral / window_duration,
        "max": max_value,
        "last": current_value if current_value is not None else "",
    }


def sequence_summary(series: list[tuple[float, float]], window_start: float, window_end: float) -> dict[str, int | str]:
    if not series:
        return {"count": 0, "progress": 0, "last": ""}

    window_events = [(timestamp, value) for timestamp, value in series if window_start <= timestamp < window_end]
    count = len(window_events)

    start_value = last_value_before_or_at(series, window_start)
    end_value = last_value_before_or_at(series, window_end)

    if start_value is not None and end_value is not None:
        progress = max(0, int(round(end_value - start_value)))
    elif count > 0:
        progress = max(0, int(round(window_events[-1][1] - window_events[0][1] + 1)))
    else:
        progress = 0

    return {
        "count": count,
        "progress": progress,
        "last": int(round(end_value)) if end_value is not None else "",
    }


def init_run_data(scenario: str) -> dict:
    run_data = {
        "receiver_apps": {},
        "scalars": {},
    }
    if scenario == "linkdegradation":
        run_data["controller"] = {
            "appliedDelay": [],
            "appliedPacketErrorRate": [],
        }
    elif scenario == "congestiondegradation":
        run_data["bottleneck_queue"] = {
            "queueLength": [],
            "queueBitLength": [],
            "queueingTime": [],
        }
    elif scenario in {"reactivefailure", "proactiveswitch"}:
        pass
    elif scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
        run_data["controller"] = {
            "appliedDelay": [],
            "appliedPacketErrorRate": [],
        }
        run_data["bottleneck_queue"] = {
            "queueLength": [],
            "queueBitLength": [],
            "queueingTime": [],
        }
    else:
        raise SystemExit(f"Unsupported scenario '{scenario}' for dataset extraction")
    return run_data


def ensure_receiver_app(run_data: dict, app_index: int) -> dict:
    return run_data["receiver_apps"].setdefault(app_index, {
        "throughput": [],
        "endToEndDelay": [],
        "rcvdPkSeqNo": [],
    })


def register_vector_target(
    scenario: str,
    config_name: str,
    run_data: dict,
    module: str,
    name: str,
) -> tuple[str, int | str | None] | None:
    if scenario in {"linkdegradation", *REGIONALBACKBONE_FAMILY_SCENARIOS} and module.endswith(".degradationController") and name in {"appliedDelay", "appliedPacketErrorRate"}:
        return ("controller", name)

    if scenario == "congestiondegradation" and module.endswith(BOTTLE_NECK_QUEUE_MODULE_SUFFIX) and name in {"queueLength", "queueBitLength", "queueingTime"}:
        return ("bottleneck_queue", name)

    if (
        scenario in REGIONALBACKBONE_FAMILY_SCENARIOS
        and config_name in REGIONALBACKBONE_CONGESTION_STYLE_CONFIGS
        and module.endswith(REGIONAL_BOTTLENECK_QUEUE_MODULE_SUFFIX)
        and name in {"queueLength", "queueBitLength", "queueingTime"}
    ):
        return ("bottleneck_queue", name)

    match = HOSTB_APP_RE.match(module)
    if match and name in {"throughput", "endToEndDelay", "rcvdPkSeqNo"}:
        return (name, int(match.group(1)))

    return None


def parse_scalar_file(sca_path: Path) -> dict[str, float]:
    scalars: dict[str, float] = {}
    if not sca_path.exists():
        return scalars

    with sca_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line.startswith("scalar "):
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            module_name = parts[1]
            scalar_name = parts[2]
            raw_value = parts[3]

            if scalar_name not in TARGET_CONTROLLER_SCALAR_NAMES:
                continue

            try:
                scalar_value = float(raw_value)
            except ValueError:
                continue

            if scalar_name not in scalars:
                scalars[scalar_name] = scalar_value
                continue

            if module_name.endswith(".aiMrceController") or module_name.endswith(".withdrawController"):
                scalars[scalar_name] = scalar_value

    return scalars


def parse_vec_file(
    vec_path: Path,
    scenario: str,
    supported_configs: set[str],
    config_aliases: dict[str, str],
    default_sim_time_limit: float,
    default_sim_time_limits_by_config: dict[str, float] | None,
) -> dict | None:
    metadata = {
        "configname": None,
        "runnumber": None,
        "sim_time_limit": None,
    }
    run_data = init_run_data(scenario)
    vector_targets: dict[int, tuple[str, int | str | None]] = {}

    with vec_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("attr configname "):
                metadata["configname"] = line.split(" ", 2)[2]
                continue

            if line.startswith("attr runnumber "):
                try:
                    metadata["runnumber"] = int(line.split(" ", 2)[2])
                except ValueError:
                    metadata["runnumber"] = None
                continue

            if line.startswith("config sim-time-limit "):
                if metadata["sim_time_limit"] is None:
                    metadata["sim_time_limit"] = parse_time_value(line.split(" ", 2)[2])
                continue

            if line.startswith("vector "):
                parts = line.split()
                if len(parts) < 4:
                    continue
                vector_id = int(parts[1])
                module = parts[2]
                name = parts[3]
                if name.endswith(":vector"):
                    name = name[:-7]
                configname = normalize_config_name(metadata["configname"] or "", config_aliases)
                target = register_vector_target(scenario, configname, run_data, module, name)
                if target is not None:
                    vector_targets[vector_id] = target
                continue

            if not line[0].isdigit():
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            vector_id = int(parts[0])
            target = vector_targets.get(vector_id)
            if target is None:
                continue

            timestamp = float(parts[2])
            value = float(parts[-1])

            target_type, target_key = target
            if target_type == "controller":
                run_data["controller"][target_key].append((timestamp, value))
            elif target_type == "bottleneck_queue":
                run_data["bottleneck_queue"][target_key].append((timestamp, value))
            else:
                app_metrics = ensure_receiver_app(run_data, int(target_key))
                app_metrics[target_type].append((timestamp, value))

    configname = normalize_config_name(metadata["configname"] or "", config_aliases)
    if configname not in supported_configs:
        return None

    if metadata["runnumber"] is None:
        match = re.search(r"-(\d+)$", vec_path.stem)
        metadata["runnumber"] = int(match.group(1)) if match else 0

    metadata["configname"] = configname
    metadata["sim_time_limit"] = (
        metadata["sim_time_limit"]
        if metadata["sim_time_limit"] is not None
        else default_sim_time_limit_for_config(default_sim_time_limit, configname, default_sim_time_limits_by_config)
    )
    run_data["metadata"] = metadata
    run_data["scalars"] = parse_scalar_file(vec_path.with_suffix(".sca"))
    return run_data


def parse_numeric_cell(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int_cell(value: object) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def optional_numeric(value: float | int | None) -> float | int | str:
    if value is None:
        return ""
    return value


def bool_flag(value: bool | None) -> int | str:
    if value is None:
        return ""
    return 1 if value else 0


def availability_thresholds(profile: OutcomeProfile) -> tuple[float, int, float]:
    expected_packets_per_window = WINDOW_SIZE_SECONDS / profile.send_interval_s
    packet_progress_floor = max(1, int(math.ceil(expected_packets_per_window * 0.5)))
    expected_throughput_bps = profile.packet_size_bits / profile.send_interval_s
    throughput_floor_bps = expected_throughput_bps * 0.5
    return expected_packets_per_window, packet_progress_floor, throughput_floor_bps


def operational_service_available(
    seq_progress: int | None,
    throughput_mean_bps: float | None,
    packet_progress_floor: int,
    throughput_floor_bps: float,
) -> bool:
    # This is a project-local operational definition for service availability.
    # It relies only on receiver-observable packet continuity and throughput,
    # not on protocol-internal oracle knowledge or RFC-standard thresholds.
    if seq_progress is not None and seq_progress >= packet_progress_floor:
        return True
    if throughput_mean_bps is not None and throughput_mean_bps >= throughput_floor_bps:
        return True
    return False


def resolve_protection_activation(profile: OutcomeProfile, scalar_values: dict[str, float]) -> tuple[bool, float | None, str]:
    activation_flag = scalar_values.get("protectionActivated")
    activation_time = scalar_values.get("protectionActivationTime")

    if activation_flag is not None and activation_flag > 0.5 and activation_time is not None and activation_time >= 0:
        return True, activation_time, "controller_scalar"

    if activation_flag is not None and activation_flag > 0.5 and profile.scheduled_protection_time_s is not None:
        return True, profile.scheduled_protection_time_s, "scheduled_baseline_fallback"

    if activation_flag is None and activation_time is None and profile.scheduled_protection_time_s is not None:
        # This fallback preserves backward compatibility for deterministic
        # proactive baseline runs generated before shared controller scalars
        # were recorded. It uses only the known local control schedule.
        return True, profile.scheduled_protection_time_s, "scheduled_baseline_fallback"

    if profile.protection_expected:
        return False, None, "not_activated"
    return False, None, "not_applicable"


def zero_progress_gap_metrics(rows: list[dict[str, object]], monitored_app_index: int, reference_time_s: float | None) -> tuple[int | None, int | None]:
    if reference_time_s is None:
        return None, None

    zero_progress_count = 0
    max_streak = 0
    current_streak = 0
    column_name = f"receiver_app{monitored_app_index}_seq_progress"

    for row in rows:
        window_start_s = float(row["window_start_s"])
        if window_start_s < reference_time_s:
            continue

        seq_progress = parse_int_cell(row.get(column_name))
        if seq_progress is not None and seq_progress <= 0:
            zero_progress_count += 1
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    return zero_progress_count, max_streak


def annotate_run_outcome_metrics(rows: list[dict[str, object]], run_data: dict, scenario: str) -> None:
    if not rows:
        return

    metadata = run_data["metadata"]
    profile = get_outcome_profile(scenario, metadata["configname"])
    _, packet_progress_floor, throughput_floor_bps = availability_thresholds(profile)

    protection_activated, protection_activation_time_s, protection_activation_source = resolve_protection_activation(
        profile,
        run_data["scalars"],
    )
    hard_failure_time_s = profile.hard_failure_time_s
    protection_activated_before_failure = (
        protection_activated
        and protection_activation_time_s is not None
        and hard_failure_time_s is not None
        and protection_activation_time_s < hard_failure_time_s
    )
    protection_lead_time_before_failure_s = (
        hard_failure_time_s - protection_activation_time_s
        if protection_activated_before_failure and hard_failure_time_s is not None and protection_activation_time_s is not None
        else None
    )

    if protection_activated_before_failure:
        reference_event = "protection_activation"
        reference_time_s = protection_activation_time_s
    elif hard_failure_time_s is not None:
        reference_event = "hard_failure"
        reference_time_s = hard_failure_time_s
    elif protection_activated and protection_activation_time_s is not None:
        reference_event = "protection_activation_no_failure"
        reference_time_s = protection_activation_time_s
    else:
        reference_event = "none"
        reference_time_s = None

    service_interruption_start_time_s = None
    service_interruption_end_time_s = None

    if reference_time_s is not None:
        interruption_started = False
        for row in rows:
            window_start_s = float(row["window_start_s"])
            service_available = parse_int_cell(row.get("service_available_operational"))
            if window_start_s < reference_time_s:
                continue

            if not interruption_started and service_available == 0:
                service_interruption_start_time_s = window_start_s
                interruption_started = True
                continue

            if interruption_started and service_available == 1 and window_start_s > service_interruption_start_time_s:
                service_interruption_end_time_s = window_start_s
                break

    service_interruption_duration_s = None
    if service_interruption_start_time_s is not None and service_interruption_end_time_s is not None:
        service_interruption_duration_s = service_interruption_end_time_s - service_interruption_start_time_s

    recovery_observed: bool | None = None
    recovery_time_after_failure_s = None
    throughput_restored_after_failure: bool | None = None
    if hard_failure_time_s is not None:
        recovery_observed = False
        throughput_restored_after_failure = False
        monitored_throughput_column = f"receiver_app{profile.monitored_app_index}_throughput_mean_bps"

        for row in rows:
            window_start_s = float(row["window_start_s"])
            if window_start_s < hard_failure_time_s:
                continue

            if parse_int_cell(row.get("service_available_operational")) == 1 and recovery_observed is False:
                recovery_observed = True
                recovery_time_after_failure_s = window_start_s - hard_failure_time_s

            throughput_mean_bps = parse_numeric_cell(row.get(monitored_throughput_column))
            if throughput_mean_bps is not None and throughput_mean_bps >= throughput_floor_bps:
                throughput_restored_after_failure = True

    zero_progress_window_count_after_reference, max_zero_progress_window_streak_after_reference = zero_progress_gap_metrics(
        rows,
        profile.monitored_app_index,
        reference_time_s,
    )

    unnecessary_protection = protection_activated and hard_failure_time_s is None
    missed_protection = (
        profile.protection_expected
        and hard_failure_time_s is not None
        and not protection_activated_before_failure
    )

    run_outcome_fields = {
        "protection_activated": bool_flag(protection_activated),
        "protection_activation_time_s": optional_numeric(protection_activation_time_s),
        "protection_activation_source": protection_activation_source,
        "hard_failure_time_s": optional_numeric(hard_failure_time_s),
        "protection_activated_before_failure": bool_flag(protection_activated_before_failure) if hard_failure_time_s is not None else "",
        "protection_lead_time_before_failure_s": optional_numeric(protection_lead_time_before_failure_s),
        "service_interruption_reference_event": reference_event,
        "service_interruption_reference_time_s": optional_numeric(reference_time_s),
        "service_interruption_observed": bool_flag(service_interruption_start_time_s is not None) if reference_time_s is not None else "",
        "service_interruption_start_time_s": optional_numeric(service_interruption_start_time_s),
        "service_interruption_end_time_s": optional_numeric(service_interruption_end_time_s),
        "service_interruption_duration_s": optional_numeric(service_interruption_duration_s),
        "recovery_observed": bool_flag(recovery_observed),
        "recovery_time_after_failure_s": optional_numeric(recovery_time_after_failure_s),
        "zero_progress_window_count_after_reference": optional_numeric(zero_progress_window_count_after_reference),
        "max_zero_progress_window_streak_after_reference": optional_numeric(max_zero_progress_window_streak_after_reference),
        "throughput_restored_after_failure": bool_flag(throughput_restored_after_failure),
        "unnecessary_protection": bool_flag(unnecessary_protection),
        "missed_protection": bool_flag(missed_protection),
    }

    for row in rows:
        row.update(run_outcome_fields)


def build_rows_for_run(run_data: dict, scenario: str) -> list[dict[str, object]]:
    metadata = run_data["metadata"]
    outcome_profile = get_outcome_profile(scenario, metadata["configname"])
    sim_time_limit = float(metadata["sim_time_limit"])
    num_windows = int(math.ceil(sim_time_limit / WINDOW_SIZE_SECONDS))
    receiver_apps = run_data["receiver_apps"]
    expected_packets_per_window, packet_progress_floor, throughput_floor_bps = availability_thresholds(outcome_profile)
    expected_throughput_bps = outcome_profile.packet_size_bits / outcome_profile.send_interval_s

    rows = []
    for window_index in range(num_windows):
        window_start = window_index * WINDOW_SIZE_SECONDS
        window_end = min(sim_time_limit, window_start + WINDOW_SIZE_SECONDS)

        row = {
            "config_name": metadata["configname"],
            "run_number": metadata["runnumber"],
            "window_start_s": window_start,
            "window_end_s": window_end,
            "label": label_for_window(scenario, metadata["configname"], window_start),
            "protection_mode": outcome_profile.protection_mode,
            "monitored_flow_app_index": outcome_profile.monitored_app_index,
            "monitored_flow_expected_packets_per_window": expected_packets_per_window,
            "monitored_flow_expected_throughput_bps": expected_throughput_bps,
            "service_availability_packet_progress_floor": packet_progress_floor,
            "service_availability_throughput_floor_bps": throughput_floor_bps,
        }

        if scenario in {"linkdegradation", *REGIONALBACKBONE_FAMILY_SCENARIOS}:
            delay_summary = state_summary(run_data["controller"]["appliedDelay"], window_start, window_end)
            per_summary = state_summary(run_data["controller"]["appliedPacketErrorRate"], window_start, window_end)
            row.update({
                "controller_delay_mean_s": delay_summary["mean"],
                "controller_delay_max_s": delay_summary["max"],
                "controller_delay_last_s": delay_summary["last"],
                "controller_packet_error_rate_mean": per_summary["mean"],
                "controller_packet_error_rate_max": per_summary["max"],
                "controller_packet_error_rate_last": per_summary["last"],
            })

        if scenario in {"congestiondegradation", *REGIONALBACKBONE_FAMILY_SCENARIOS}:
            queue_length_summary = state_summary(run_data["bottleneck_queue"]["queueLength"], window_start, window_end)
            queue_bit_length_summary = state_summary(run_data["bottleneck_queue"]["queueBitLength"], window_start, window_end)
            queueing_time_summary = state_summary(run_data["bottleneck_queue"]["queueingTime"], window_start, window_end)
            row.update({
                "bottleneck_queue_length_mean_pk": queue_length_summary["mean"],
                "bottleneck_queue_length_max_pk": queue_length_summary["max"],
                "bottleneck_queue_length_last_pk": queue_length_summary["last"],
                "bottleneck_queue_bit_length_mean_b": queue_bit_length_summary["mean"],
                "bottleneck_queue_bit_length_max_b": queue_bit_length_summary["max"],
                "bottleneck_queue_bit_length_last_b": queue_bit_length_summary["last"],
                "bottleneck_queueing_time_mean_s": queueing_time_summary["mean"],
                "bottleneck_queueing_time_max_s": queueing_time_summary["max"],
                "bottleneck_queueing_time_last_s": queueing_time_summary["last"],
            })
        elif scenario not in {"linkdegradation", "reactivefailure", "proactiveswitch"}:
            raise SystemExit(f"Unsupported scenario '{scenario}' for dataset row generation")

        total_packets = 0
        for app_index in sorted(receiver_apps.keys()):
            metrics = receiver_apps[app_index]
            seq = sequence_summary(metrics["rcvdPkSeqNo"], window_start, window_end)
            delay = sample_summary(metrics["endToEndDelay"], window_start, window_end)
            throughput = sample_summary(metrics["throughput"], window_start, window_end, nonnegative_only=True)

            total_packets += int(seq["count"])
            row[f"receiver_app{app_index}_packet_count"] = seq["count"]
            row[f"receiver_app{app_index}_seq_progress"] = seq["progress"]
            row[f"receiver_app{app_index}_last_seq"] = seq["last"]
            row[f"receiver_app{app_index}_e2e_delay_mean_s"] = delay["mean"]
            row[f"receiver_app{app_index}_e2e_delay_max_s"] = delay["max"]
            row[f"receiver_app{app_index}_throughput_mean_bps"] = throughput["mean"]
            row[f"receiver_app{app_index}_throughput_last_bps"] = throughput["last"]

        row["receiver_total_packet_count"] = total_packets

        monitored_seq_progress = parse_int_cell(row.get(f"receiver_app{outcome_profile.monitored_app_index}_seq_progress"))
        monitored_throughput_bps = parse_numeric_cell(row.get(f"receiver_app{outcome_profile.monitored_app_index}_throughput_mean_bps"))
        if window_start < outcome_profile.flow_start_time_s:
            # Before the monitored flow starts, service availability is not yet
            # applicable. Leaving these fields blank avoids conflating "no
            # traffic scheduled" with "observable service degradation."
            row["service_available_operational"] = ""
            row["service_materially_degraded_operational"] = ""
        else:
            service_available = operational_service_available(
                monitored_seq_progress,
                monitored_throughput_bps,
                packet_progress_floor,
                throughput_floor_bps,
            )
            row["service_available_operational"] = bool_flag(service_available)
            row["service_materially_degraded_operational"] = bool_flag(not service_available)

        rows.append(row)

    annotate_run_outcome_metrics(rows, run_data, scenario)
    return rows


def collect_rows(
    results_dir: Path,
    scenario: str,
    supported_configs: set[str],
    config_aliases: dict[str, str],
    default_sim_time_limit: float,
    default_sim_time_limits_by_config: dict[str, float] | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for vec_path in sorted(results_dir.glob("*.vec")):
        run_data = parse_vec_file(
            vec_path,
            scenario,
            supported_configs,
            config_aliases,
            default_sim_time_limit,
            default_sim_time_limits_by_config,
        )
        if run_data is None:
            continue
        rows.extend(build_rows_for_run(run_data, scenario))
    return rows


def write_dataset(rows: list[dict[str, object]], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with output_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    preset = get_scenario_preset(args.scenario)

    results_dir = args.input if args.input is not None else preset["results_dir"]
    output_file = args.output if args.output is not None else preset["output_file"]
    supported_configs = effective_supported_configs(preset, args.include_runtime_protection_configs)
    config_aliases = preset["config_aliases"]
    default_sim_time_limit = preset["default_sim_time_limit"]
    default_sim_time_limits_by_config = preset.get("default_sim_time_limits_by_config")

    if not results_dir.exists():
        raise SystemExit(f"Results directory not found: {results_dir}")

    rows = collect_rows(
        results_dir,
        args.scenario,
        supported_configs,
        config_aliases,
        default_sim_time_limit,
        default_sim_time_limits_by_config,
    )
    if not rows:
        raise SystemExit(f"No supported {args.scenario} .vec files were found in {results_dir}.")

    write_dataset(rows, output_file)
    print(f"Wrote {len(rows)} dataset rows to {output_file}")


if __name__ == "__main__":
    main()
