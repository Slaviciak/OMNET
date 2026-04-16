#!/usr/bin/env python3
"""
Build a simple ML-ready CSV dataset from OMNeT++ vector results.

Assumptions:
- Input files are OMNeT++ .vec files under results/<scenario>/eval/ by default.
- Windows are fixed-size and non-overlapping.
- Labels are assigned from configurable time boundaries using the window start.
- Receiver-side metrics may be absent in some runs; missing values are left blank.
- Throughput vectors are rate samples, so they are summarized from actual
  nonnegative samples inside each window only.
- Older runs using legacy or debug config names may be normalized to the main
  config name for dataset consistency.
- The CLI uses scenario presets so later scenario-specific builders can follow
  the same style.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from statistics import fmean


WINDOW_SIZE_SECONDS = 1.0

DEGRADATION_START_SECONDS = 20.0
PRE_FAILURE_START_SECONDS = 40.0
HARD_FAILURE_TIME_SECONDS = 45.0

CONGESTION_CONVERGENCE_END_SECONDS = 20.0
CONGESTION_BASELINE_END_SECONDS = 50.0
CONGESTION_RISING_END_SECONDS = 125.0
CONGESTION_CRITICAL_END_SECONDS = 150.0

REGIONAL_REACTIVE_FAILURE_TIME_SECONDS = 40.0
REGIONAL_REACTIVE_DISRUPTION_END_SECONDS = 50.0

REGIONAL_DEGRADATION_START_SECONDS = 35.0
REGIONAL_DEGRADATION_END_SECONDS = 55.0
REGIONAL_HARD_FAILURE_TIME_SECONDS = 60.0

REGIONAL_CONGESTION_CONVERGENCE_END_SECONDS = 20.0
REGIONAL_CONGESTION_BASELINE_END_SECONDS = 35.0
REGIONAL_CONGESTION_RISING_END_SECONDS = 80.0
REGIONAL_CONGESTION_CRITICAL_END_SECONDS = 125.0

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = "linkdegradation"
BOTTLE_NECK_QUEUE_MODULE_SUFFIX = ".r2.eth[1].queue"
REGIONAL_BOTTLENECK_QUEUE_MODULE_SUFFIX = ".coreNW.eth[1].queue"

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
    "regionalbackbone": {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "eval",
        "output_file": PROJECT_ROOT / "analysis" / "output" / "regionalbackbone_dataset.csv",
        "supported_configs": {
            "RegionalBackboneBaseline",
            "RegionalBackboneReactiveFailure",
            "RegionalBackboneControlledDegradation",
            "RegionalBackboneCongestionDegradation",
        },
        "config_aliases": {},
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            "RegionalBackboneBaseline": 60.0,
            "RegionalBackboneReactiveFailure": 80.0,
            "RegionalBackboneControlledDegradation": 90.0,
            "RegionalBackboneCongestionDegradation": 150.0,
        },
    },
}

HOSTB_APP_RE = re.compile(r".*\.hostB\.app\[(\d+)\]$")


def parse_time_value(raw: str) -> float | None:
    raw = raw.strip()
    if raw.endswith("s"):
        raw = raw[:-1]
    try:
        return float(raw)
    except ValueError:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a windowed dataset from OMNeT++ vector results.")
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
    return parser.parse_args()


def get_scenario_preset(scenario: str) -> dict[str, object]:
    preset = SCENARIO_PRESETS.get(scenario)
    if preset is None:
        supported = ", ".join(sorted(SCENARIO_PRESETS))
        raise SystemExit(f"Unsupported scenario '{scenario}'. Supported scenarios: {supported}")
    return preset


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

    if config_name == "RegionalBackboneCongestionDegradation":
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
    if scenario == "regionalbackbone":
        return label_for_regionalbackbone_window(config_name, window_start)
    raise SystemExit(f"Unsupported scenario '{scenario}' for labeling")


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


def numeric_summary(series: list[tuple[float, float]], window_start: float, window_end: float) -> dict[str, float | str]:
    if not series:
        return {"mean": "", "max": "", "last": ""}

    samples = []
    start_value = last_value_before_or_at(series, window_start)
    end_value = last_value_before_or_at(series, window_end)
    in_window_values = values_in_window(series, window_start, window_end)

    if start_value is not None:
        samples.append(start_value)
    samples.extend(in_window_values)
    if end_value is not None and (not samples or end_value != samples[-1]):
        samples.append(end_value)

    if not samples:
        return {"mean": "", "max": "", "last": ""}

    return {
        "mean": fmean(samples),
        "max": max(samples),
        "last": end_value if end_value is not None else samples[-1],
    }


def throughput_summary(series: list[tuple[float, float]], window_start: float, window_end: float) -> dict[str, float | str]:
    if not series:
        return {"mean": "", "max": "", "last": ""}

    # Throughput is a sampled rate, not a state variable. Boundary carry-over can
    # misrepresent a window, and INET may emit a startup estimator artifact below
    # zero, which is not physically meaningful for throughput.
    samples = [value for timestamp, value in series if window_start <= timestamp < window_end and value >= 0]

    if not samples:
        return {"mean": "", "max": "", "last": ""}

    return {
        "mean": fmean(samples),
        "max": max(samples),
        "last": samples[-1],
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
    elif scenario == "regionalbackbone":
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


def register_vector_target(scenario: str, config_name: str, run_data: dict, module: str, name: str) -> tuple[str, int | str | None] | None:
    if scenario in {"linkdegradation", "regionalbackbone"} and module.endswith(".degradationController") and name in {"appliedDelay", "appliedPacketErrorRate"}:
        return ("controller", name)

    if scenario == "congestiondegradation" and module.endswith(BOTTLE_NECK_QUEUE_MODULE_SUFFIX) and name in {"queueLength", "queueBitLength", "queueingTime"}:
        return ("bottleneck_queue", name)

    if (
        scenario == "regionalbackbone"
        and config_name == "RegionalBackboneCongestionDegradation"
        and module.endswith(REGIONAL_BOTTLENECK_QUEUE_MODULE_SUFFIX)
        and name in {"queueLength", "queueBitLength", "queueingTime"}
    ):
        return ("bottleneck_queue", name)

    match = HOSTB_APP_RE.match(module)
    if match and name in {"throughput", "endToEndDelay", "rcvdPkSeqNo"}:
        return (name, int(match.group(1)))

    return None


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
    return run_data


def build_rows_for_run(run_data: dict, scenario: str) -> list[dict[str, object]]:
    metadata = run_data["metadata"]
    sim_time_limit = float(metadata["sim_time_limit"])
    num_windows = int(math.ceil(sim_time_limit / WINDOW_SIZE_SECONDS))
    receiver_apps = run_data["receiver_apps"]

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
        }

        if scenario in {"linkdegradation", "regionalbackbone"}:
            delay_summary = numeric_summary(run_data["controller"]["appliedDelay"], window_start, window_end)
            per_summary = numeric_summary(run_data["controller"]["appliedPacketErrorRate"], window_start, window_end)
            row.update({
                "controller_delay_mean_s": delay_summary["mean"],
                "controller_delay_max_s": delay_summary["max"],
                "controller_delay_last_s": delay_summary["last"],
                "controller_packet_error_rate_mean": per_summary["mean"],
                "controller_packet_error_rate_max": per_summary["max"],
                "controller_packet_error_rate_last": per_summary["last"],
            })

        if scenario in {"congestiondegradation", "regionalbackbone"}:
            queue_length_summary = numeric_summary(run_data["bottleneck_queue"]["queueLength"], window_start, window_end)
            queue_bit_length_summary = numeric_summary(run_data["bottleneck_queue"]["queueBitLength"], window_start, window_end)
            queueing_time_summary = numeric_summary(run_data["bottleneck_queue"]["queueingTime"], window_start, window_end)
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
        elif scenario != "linkdegradation":
            raise SystemExit(f"Unsupported scenario '{scenario}' for dataset row generation")

        total_packets = 0
        for app_index in sorted(receiver_apps.keys()):
            metrics = receiver_apps[app_index]
            seq = sequence_summary(metrics["rcvdPkSeqNo"], window_start, window_end)
            delay = numeric_summary(metrics["endToEndDelay"], window_start, window_end)
            throughput = throughput_summary(metrics["throughput"], window_start, window_end)

            total_packets += int(seq["count"])
            row[f"receiver_app{app_index}_packet_count"] = seq["count"]
            row[f"receiver_app{app_index}_seq_progress"] = seq["progress"]
            row[f"receiver_app{app_index}_last_seq"] = seq["last"]
            row[f"receiver_app{app_index}_e2e_delay_mean_s"] = delay["mean"]
            row[f"receiver_app{app_index}_e2e_delay_max_s"] = delay["max"]
            row[f"receiver_app{app_index}_throughput_mean_bps"] = throughput["mean"]
            row[f"receiver_app{app_index}_throughput_last_bps"] = throughput["last"]

        row["receiver_total_packet_count"] = total_packets
        rows.append(row)

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
    supported_configs = preset["supported_configs"]
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
