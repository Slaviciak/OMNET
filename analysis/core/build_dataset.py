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
- Packet-continuity diagnostics use receiver-observed sequence numbers and
  receive timestamps. They are intended to reveal short packet-loss/reordering
  symptoms that may not produce a full one-second zero-progress window.
- The historical sequence-gap "missing" fields are forward-jump estimates,
  not direct packet-loss claims. They intentionally remain for compatibility,
  but route switches can reorder packets when a fast repair path overtakes
  older packets delayed in the congested primary queue. Reordering-aware
  unobserved/reordered fields are therefore exported alongside the original
  fields and should be used for loss-like versus reordering interpretations.
- Packet-continuity outputs are split by reference point. The historical
  after_reference fields follow the operational service-interruption reference
  (protection activation for protected runs, hard failure for reactive runs);
  separate after_hard_failure and between_activation_and_failure fields avoid
  hiding activation transition cost or overstating post-failure benefit.
- Queue-normalized activation-to-failure diagnostics are descriptive ratios
  only. They help relate repair-route reordering to the observed queue state at
  activation, but they are not control thresholds and do not change runtime
  behavior.
- Mixed UDP/TCP regional runs use standard INET TCP applications and summarize
  application packet-byte vectors as a conservative useful-goodput proxy.
  This deliberately avoids protocol-internal TCP instrumentation or claims
  about carrier-grade transport recovery.
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
from bisect import bisect_left, bisect_right
import csv
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean


WINDOW_SIZE_SECONDS = 1.0

REGIONAL_CONGESTION_CONVERGENCE_END_SECONDS = 20.0
REGIONAL_CONGESTION_BASELINE_END_SECONDS = 35.0
REGIONAL_CONGESTION_RISING_END_SECONDS = 80.0
REGIONAL_CONGESTION_CRITICAL_END_SECONDS = 125.0
REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS = 125.0

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "analysis" / "output"
DATASETS_DIR = OUTPUT_ROOT / "datasets"
REPORTS_DIR = OUTPUT_ROOT / "reports"
DEFAULT_SCENARIO = "regionalbackbone"
DEGRADED_LINK_MODEL_FAMILY_SCENARIO = "regionalbackbone_failure_detection_degraded_link_model_family"
DEGRADATION_SENSITIVITY_SCENARIO = "regionalbackbone_failure_detection_degradation_sensitivity"
COST_AWARE_BACKUP_SCENARIO = "regionalbackbone_failure_detection_cost_aware_backup"
COST_AWARE_TRANSPORT_SCENARIO = "regionalbackbone_failure_detection_cost_aware_transport_impact"
COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO = "regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented"
RANDOMIZED_ONSET_SCENARIO = "regionalbackbone_failure_detection_cost_aware_transport_impact_randomized_onset"
BOTTLE_NECK_QUEUE_MODULE_SUFFIX = ".r2.eth[1].queue"
REGIONAL_BOTTLENECK_QUEUE_MODULE_SUFFIX = ".coreNW.eth[1].queue"
HOSTA_APP_RE = re.compile(r".*\.hostA\.app\[(\d+)\]$")
HOSTB_APP_RE = re.compile(r".*\.hostB\.app\[(\d+)\]$")
TARGET_CONTROLLER_SCALAR_NAMES = {
    "protectionActivated",
    "protectionActivationTime",
    "protectionTriggerSourceCode",
    "protectionActionCode",
    "repairRoutesInstalled",
    "repairRouteCount",
    "repairRouteInstallTime",
    "enableAimrceDecision",
    "enableBfdLikeDetection",
    "aimrcePolicyCode",
    "runtimeModelArtifactRequired",
    "runtimeModelLoaded",
    "runtimeModelFeatureCount",
    "runtimeModelThreshold",
    "runtimeModelFallbackUsed",
    "runtimeModelFallbackReasonCode",
    "aimrceEvaluationInterval",
    "aimrceActivationConsecutiveCyclesConfigured",
    "bfdLikeDetectionActivated",
    "bfdLikeDetectionTime",
    "bfdLikeDetectMultiplier",
    "bfdLikeDetectionInterval",
    "bfdLikeExpectedDetectionTime",
    "bfdLikeMissedProbeCount",
    "bfdLikeMaxMissedProbeCount",
    "bfdLikeUseModeledProbeLoss",
    "bfdLikeProbeChecks",
    "bfdLikeProbeSuccesses",
    "bfdLikeProbeMisses",
    "bfdLikeProbeLossRateObserved",
    "bfdLikeModeledProbeLossProbabilityLast",
    "bfdLikeModeledProbeLossProbabilityMax",
    "bfdLikeModeledProbeLossProbabilityAtDetection",
    "bfdLikeTriggerReasonCode",
    "bfdLikeProtectedSpanUpAtDetection",
    "bfdLikeDetectionBeforeHardFailure",
    "bfdLikeLeadTimeBeforeFailure",
    "hardFailureToBfdDetectionTime",
    "hardFailureTime",
    "activationRiskScore",
    "activationDecisionThreshold",
    "activationPositiveDecisionStreak",
    "activationQueueLengthPk",
    "activationQueueBitLengthB",
    "activationProbeDelayMeanS",
    "activationProbeThroughputBps",
    "activationProbePacketCount",
}
REGIONALBACKBONE_FAMILY_SCENARIOS = {
    "regionalbackbone",
    DEGRADED_LINK_MODEL_FAMILY_SCENARIO,
    DEGRADATION_SENSITIVITY_SCENARIO,
    COST_AWARE_BACKUP_SCENARIO,
    COST_AWARE_TRANSPORT_SCENARIO,
    COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO,
    RANDOMIZED_ONSET_SCENARIO,
}

REGIONALBACKBONE_DATASET_CONFIGS = {
    "RegionalBackboneCongestionDegradation",
}
REGIONALBACKBONE_OPTIONAL_RUNTIME_CONFIGS: set[str] = set()
REGIONALBACKBONE_FAILURE_DETECTION_DEGRADED_LINK_MODEL_FAMILY_CONFIGS = {
    "RegionalBackboneFailureDegradedLinkOspfOnly",
    "RegionalBackboneFailureDegradedLinkBfdLikeFrr",
    "RegionalBackboneFailureDegradedLinkAiMrceRuleBased",
    "RegionalBackboneFailureDegradedLinkAiMrceLogReg",
    "RegionalBackboneFailureDegradedLinkAiMrceLinearSvm",
    "RegionalBackboneFailureDegradedLinkAiMrceShallowTree",
    "RegionalBackboneFailureDegradedLinkHybrid",
}
SENSITIVITY_PROFILE_PARAMETERS = {
    "mild_slow": {
        "title": "MildSlow",
        "label": "mild_slow",
        "start_time_s": 90.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.025,
        "target_packet_error_rate": 0.35,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
    },
    "moderate": {
        "title": "Moderate",
        "label": "moderate",
        "start_time_s": 100.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.035,
        "target_packet_error_rate": 0.65,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
    },
    "severe_fast": {
        "title": "SevereFast",
        "label": "severe_fast",
        "start_time_s": 112.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.045,
        "target_packet_error_rate": 0.95,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
    },
}
COST_AWARE_PROFILE_PARAMETERS = {
    "cost_aware_mild": {
        "title": "Mild",
        "label": "cost_aware_mild",
        "start_time_s": 65.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.060,
        "target_packet_error_rate": 0.55,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
    },
    "cost_aware_moderate": {
        "title": "Moderate",
        "label": "cost_aware_moderate",
        "start_time_s": 85.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.070,
        "target_packet_error_rate": 0.70,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
    },
    "cost_aware_fast_warning": {
        "title": "FastWarning",
        "label": "cost_aware_fast_warning",
        "start_time_s": 108.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.080,
        "target_packet_error_rate": 0.90,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
    },
}
TRANSPORT_IMPACT_PROFILE_PARAMETERS = {
    "transport_mild": {
        "title": "TransportMild",
        "label": "transport_mild",
        "start_time_s": 65.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.060,
        "target_packet_error_rate": 0.55,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
        "traffic_mix": "udp_monitoring_plus_repeated_tcp_request_reply",
    },
    "transport_moderate": {
        "title": "TransportModerate",
        "label": "transport_moderate",
        "start_time_s": 85.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.070,
        "target_packet_error_rate": 0.70,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
        "traffic_mix": "udp_monitoring_plus_repeated_tcp_request_reply",
    },
    "transport_fast_warning": {
        "title": "TransportFastWarning",
        "label": "transport_fast_warning",
        "start_time_s": 108.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.080,
        "target_packet_error_rate": 0.90,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
        "traffic_mix": "udp_monitoring_plus_repeated_tcp_request_reply",
    },
}
TRANSPORT_IMPACT_INSTRUMENTED_PROFILE_PARAMETERS = {
    "transport_mild": {
        "title": "TransportInstrumentedMild",
        "label": "transport_mild",
        "start_time_s": 65.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.060,
        "target_packet_error_rate": 0.55,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
        "traffic_mix": "udp_monitoring_plus_repeated_tcp_request_reply",
        "instrumentation_mode": "targeted_inet_transport_network_telemetry",
        "scenario_role": "congestion_queue_buildup_early_mitigation",
        "protected_primary_bottleneck_enabled": True,
    },
    "transport_moderate": {
        "title": "TransportInstrumentedModerate",
        "label": "transport_moderate",
        "start_time_s": 85.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.070,
        "target_packet_error_rate": 0.70,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
        "traffic_mix": "udp_monitoring_plus_repeated_tcp_request_reply",
        "instrumentation_mode": "targeted_inet_transport_network_telemetry",
        "scenario_role": "congestion_queue_buildup_early_mitigation",
        "protected_primary_bottleneck_enabled": True,
    },
    "transport_fast_warning": {
        "title": "TransportInstrumentedFastWarning",
        "label": "transport_fast_warning",
        "start_time_s": 108.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.080,
        "target_packet_error_rate": 0.90,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
        "traffic_mix": "udp_monitoring_plus_repeated_tcp_request_reply",
        "instrumentation_mode": "targeted_inet_transport_network_telemetry",
        "scenario_role": "congestion_queue_buildup_early_mitigation",
        "protected_primary_bottleneck_enabled": True,
    },
}
RANDOMIZED_ONSET_VALUES_SECONDS = (45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0)
RANDOMIZED_ONSET_PROFILE_PARAMETERS = {
    f"onset_{int(onset)}": {
        "title": f"RandomizedOnset{int(onset)}",
        "label": f"randomized_onset_{int(onset)}s",
        "start_time_s": onset + 30.0,
        "end_time_s": 124.0,
        "target_delay_s": 0.070,
        "target_packet_error_rate": 0.70,
        "hard_failure_time_s": REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
        "backup_path_penalty": "southern_backup_100mbps_plus_5ms",
        "traffic_mix": "udp_monitoring_plus_shifted_staged_udp_plus_repeated_tcp_request_reply",
        "instrumentation_mode": "targeted_inet_transport_network_telemetry",
        "scenario_role": "queue_buildup_randomized_onset_robustness",
        "protected_primary_bottleneck_enabled": True,
        "randomized_onset_time_s": onset,
        "onset_seed": int(onset),
        "qos_event_monitor_start_time_s": onset + 10.0,
    }
    for onset in RANDOMIZED_ONSET_VALUES_SECONDS
}
SENSITIVITY_MECHANISM_SPECS = {
    "OspfOnly": {
        "protection_mode": "ospf_only",
        "runtime_model_type": "",
        "runtime_model_path": "",
        "protection_expected": False,
    },
    "BfdLikeFrr": {
        "protection_mode": "bfd_like_frr",
        "runtime_model_type": "",
        "runtime_model_path": "",
        "protection_expected": False,
    },
    "AiMrceRuleBased": {
        "protection_mode": "aimrce_rule_based_frr",
        "runtime_model_type": "rule_based",
        "runtime_model_path": "",
        "protection_expected": True,
    },
    "AiMrceLogReg": {
        "protection_mode": "aimrce_logistic_regression_frr",
        "runtime_model_type": "logistic_regression",
        "runtime_model_path": "aimrce_runtime_logreg.csv",
        "protection_expected": True,
    },
    "AiMrceLinearSvm": {
        "protection_mode": "aimrce_linear_svm_frr",
        "runtime_model_type": "linear_svm",
        "runtime_model_path": "aimrce_runtime_linsvm.csv",
        "protection_expected": True,
    },
    "AiMrceShallowTree": {
        "protection_mode": "aimrce_shallow_tree_frr",
        "runtime_model_type": "shallow_tree",
        "runtime_model_path": "aimrce_runtime_shallow_tree.csv",
        "protection_expected": True,
    },
    "Hybrid": {
        "protection_mode": "hybrid_bfd_like_aimrce_frr",
        "runtime_model_type": "rule_based",
        "runtime_model_path": "",
        "protection_expected": True,
    },
}


def sensitivity_config_name(profile_key: str, mechanism_suffix: str) -> str:
    return f"RegionalBackboneSensitivity{SENSITIVITY_PROFILE_PARAMETERS[profile_key]['title']}{mechanism_suffix}"


def cost_aware_config_name(profile_key: str, mechanism_suffix: str) -> str:
    return f"RegionalBackboneCostAware{COST_AWARE_PROFILE_PARAMETERS[profile_key]['title']}{mechanism_suffix}"


def transport_impact_config_name(profile_key: str, mechanism_suffix: str) -> str:
    return f"RegionalBackboneCostAware{TRANSPORT_IMPACT_PROFILE_PARAMETERS[profile_key]['title']}{mechanism_suffix}"


def transport_impact_instrumented_config_name(profile_key: str, mechanism_suffix: str) -> str:
    return f"RegionalBackboneCostAware{TRANSPORT_IMPACT_INSTRUMENTED_PROFILE_PARAMETERS[profile_key]['title']}{mechanism_suffix}"


def randomized_onset_config_name(profile_key: str, mechanism_suffix: str) -> str:
    return f"RegionalBackboneCostAwareTransport{RANDOMIZED_ONSET_PROFILE_PARAMETERS[profile_key]['title']}{mechanism_suffix}"


REGIONALBACKBONE_DEGRADATION_SENSITIVITY_CONFIGS = {
    sensitivity_config_name(profile_key, mechanism_suffix)
    for profile_key in SENSITIVITY_PROFILE_PARAMETERS
    for mechanism_suffix in SENSITIVITY_MECHANISM_SPECS
}
COST_AWARE_BACKUP_CONFIGS = {
    cost_aware_config_name(profile_key, mechanism_suffix)
    for profile_key in COST_AWARE_PROFILE_PARAMETERS
    for mechanism_suffix in SENSITIVITY_MECHANISM_SPECS
}
COST_AWARE_TRANSPORT_CONFIGS = {
    transport_impact_config_name(profile_key, mechanism_suffix)
    for profile_key in TRANSPORT_IMPACT_PROFILE_PARAMETERS
    for mechanism_suffix in SENSITIVITY_MECHANISM_SPECS
}
COST_AWARE_TRANSPORT_INSTRUMENTED_CONFIGS = {
    transport_impact_instrumented_config_name(profile_key, mechanism_suffix)
    for profile_key in TRANSPORT_IMPACT_INSTRUMENTED_PROFILE_PARAMETERS
    for mechanism_suffix in SENSITIVITY_MECHANISM_SPECS
}
RANDOMIZED_ONSET_CONFIGS = {
    randomized_onset_config_name(profile_key, mechanism_suffix)
    for profile_key in RANDOMIZED_ONSET_PROFILE_PARAMETERS
    for mechanism_suffix in SENSITIVITY_MECHANISM_SPECS
    if mechanism_suffix != "Hybrid"
}
COST_AWARE_BACKUP_ALIASES = {
    f"{config_name}Cohort": config_name
    for config_name in COST_AWARE_BACKUP_CONFIGS
}
COST_AWARE_TRANSPORT_ALIASES = {
    f"{config_name}Cohort": config_name
    for config_name in COST_AWARE_TRANSPORT_CONFIGS
}
COST_AWARE_TRANSPORT_INSTRUMENTED_ALIASES = {
    f"{config_name}Cohort": config_name
    for config_name in COST_AWARE_TRANSPORT_INSTRUMENTED_CONFIGS
}
RANDOMIZED_ONSET_ALIASES = {
    f"{config_name}Cohort": config_name
    for config_name in RANDOMIZED_ONSET_CONFIGS
}
REGIONALBACKBONE_DEGRADATION_SENSITIVITY_ALIASES = {
    f"{config_name}Cohort": config_name
    for config_name in REGIONALBACKBONE_DEGRADATION_SENSITIVITY_CONFIGS
}
SENSITIVITY_CONFIG_INFO = {
    sensitivity_config_name(profile_key, mechanism_suffix): {
        **SENSITIVITY_PROFILE_PARAMETERS[profile_key],
        **mechanism_spec,
        "profile_key": profile_key,
        "mechanism_suffix": mechanism_suffix,
    }
    for profile_key in SENSITIVITY_PROFILE_PARAMETERS
    for mechanism_suffix, mechanism_spec in SENSITIVITY_MECHANISM_SPECS.items()
}
COST_AWARE_CONFIG_INFO = {
    cost_aware_config_name(profile_key, mechanism_suffix): {
        **COST_AWARE_PROFILE_PARAMETERS[profile_key],
        **mechanism_spec,
        "profile_key": profile_key,
        "mechanism_suffix": mechanism_suffix,
    }
    for profile_key in COST_AWARE_PROFILE_PARAMETERS
    for mechanism_suffix, mechanism_spec in SENSITIVITY_MECHANISM_SPECS.items()
}
COST_AWARE_TRANSPORT_CONFIG_INFO = {
    transport_impact_config_name(profile_key, mechanism_suffix): {
        **TRANSPORT_IMPACT_PROFILE_PARAMETERS[profile_key],
        **mechanism_spec,
        "profile_key": profile_key,
        "mechanism_suffix": mechanism_suffix,
    }
    for profile_key in TRANSPORT_IMPACT_PROFILE_PARAMETERS
    for mechanism_suffix, mechanism_spec in SENSITIVITY_MECHANISM_SPECS.items()
}
COST_AWARE_TRANSPORT_INSTRUMENTED_CONFIG_INFO = {
    transport_impact_instrumented_config_name(profile_key, mechanism_suffix): {
        **TRANSPORT_IMPACT_INSTRUMENTED_PROFILE_PARAMETERS[profile_key],
        **mechanism_spec,
        "profile_key": profile_key,
        "mechanism_suffix": mechanism_suffix,
    }
    for profile_key in TRANSPORT_IMPACT_INSTRUMENTED_PROFILE_PARAMETERS
    for mechanism_suffix, mechanism_spec in SENSITIVITY_MECHANISM_SPECS.items()
}
RANDOMIZED_ONSET_CONFIG_INFO = {
    randomized_onset_config_name(profile_key, mechanism_suffix): {
        **RANDOMIZED_ONSET_PROFILE_PARAMETERS[profile_key],
        **mechanism_spec,
        "profile_key": profile_key,
        "mechanism_suffix": mechanism_suffix,
    }
    for profile_key in RANDOMIZED_ONSET_PROFILE_PARAMETERS
    for mechanism_suffix, mechanism_spec in SENSITIVITY_MECHANISM_SPECS.items()
    if mechanism_suffix != "Hybrid"
}
REGIONALBACKBONE_CONGESTION_STYLE_CONFIGS = {
    "RegionalBackboneCongestionDegradation",
    *REGIONALBACKBONE_FAILURE_DETECTION_DEGRADED_LINK_MODEL_FAMILY_CONFIGS,
    *REGIONALBACKBONE_DEGRADATION_SENSITIVITY_CONFIGS,
    *COST_AWARE_BACKUP_CONFIGS,
    *COST_AWARE_TRANSPORT_CONFIGS,
    *COST_AWARE_TRANSPORT_INSTRUMENTED_CONFIGS,
    *RANDOMIZED_ONSET_CONFIGS,
}

SUPPORTED_FEATURE_SETS = ("baseline", "extended")
EXTENDED_TELEMETRY_VERSION = "telemetry_v2_analysis_only"

AI_MRCE_VECTOR_NAMES = {
    "observedQueueLengthPk",
    "observedQueueBitLengthB",
    "observedProbeDelayMeanS",
    "observedProbeThroughputBps",
    "observedProbePacketCount",
    "riskScore",
    "decisionPositive",
    "positiveDecisionStreak",
    "protectionActive",
    "repairRoutesInstalled",
    "protectionTriggerSourceCode",
    "bfdLikeMissedProbeCount",
    "bfdLikeDetectionActive",
    "bfdLikeProtectedSpanUp",
    "bfdLikeModeledProbeLossProbability",
    "bfdLikeProbeMissed",
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
    traffic_profile: str = "udp_only"
    tcp_app_indices: tuple[int, ...] = ()
    tcp_flow_start_time_s: float | None = None
    tcp_useful_goodput_floor_bps: float | None = None
    packet_continuity_critical_start_time_s: float | None = None
    runtime_model_type: str = ""
    runtime_model_path: str = ""


SCENARIO_PRESETS = {
    "regionalbackbone": {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "eval",
        "output_file": DATASETS_DIR / "regionalbackbone_dataset.csv",
        "supported_configs": REGIONALBACKBONE_DATASET_CONFIGS,
        "optional_runtime_configs": REGIONALBACKBONE_OPTIONAL_RUNTIME_CONFIGS,
        "config_aliases": {},
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            "RegionalBackboneCongestionDegradation": 150.0,
        },
    },
    "regionalbackbone_failure_detection_degraded_link_model_family": {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "failure_detection_degraded_link_model_family",
        "output_file": DATASETS_DIR / "regionalbackbone_failure_detection_degraded_link_model_family_dataset.csv",
        "supported_configs": REGIONALBACKBONE_FAILURE_DETECTION_DEGRADED_LINK_MODEL_FAMILY_CONFIGS,
        "config_aliases": {
            "RegionalBackboneFailureDegradedLinkOspfOnlyCohort": "RegionalBackboneFailureDegradedLinkOspfOnly",
            "RegionalBackboneFailureDegradedLinkBfdLikeFrrCohort": "RegionalBackboneFailureDegradedLinkBfdLikeFrr",
            "RegionalBackboneFailureDegradedLinkAiMrceRuleBasedCohort": "RegionalBackboneFailureDegradedLinkAiMrceRuleBased",
            "RegionalBackboneFailureDegradedLinkAiMrceLogRegCohort": "RegionalBackboneFailureDegradedLinkAiMrceLogReg",
            "RegionalBackboneFailureDegradedLinkAiMrceLinearSvmCohort": "RegionalBackboneFailureDegradedLinkAiMrceLinearSvm",
            "RegionalBackboneFailureDegradedLinkAiMrceShallowTreeCohort": "RegionalBackboneFailureDegradedLinkAiMrceShallowTree",
            "RegionalBackboneFailureDegradedLinkHybridCohort": "RegionalBackboneFailureDegradedLinkHybrid",
        },
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            "RegionalBackboneFailureDegradedLinkOspfOnly": 150.0,
            "RegionalBackboneFailureDegradedLinkBfdLikeFrr": 150.0,
            "RegionalBackboneFailureDegradedLinkAiMrceRuleBased": 150.0,
            "RegionalBackboneFailureDegradedLinkAiMrceLogReg": 150.0,
            "RegionalBackboneFailureDegradedLinkAiMrceLinearSvm": 150.0,
            "RegionalBackboneFailureDegradedLinkAiMrceShallowTree": 150.0,
            "RegionalBackboneFailureDegradedLinkHybrid": 150.0,
        },
    },
    DEGRADATION_SENSITIVITY_SCENARIO: {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "failure_detection_degradation_sensitivity",
        "output_file": DATASETS_DIR / f"{DEGRADATION_SENSITIVITY_SCENARIO}_dataset.csv",
        "supported_configs": REGIONALBACKBONE_DEGRADATION_SENSITIVITY_CONFIGS,
        "config_aliases": REGIONALBACKBONE_DEGRADATION_SENSITIVITY_ALIASES,
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            config_name: 150.0 for config_name in REGIONALBACKBONE_DEGRADATION_SENSITIVITY_CONFIGS
        },
    },
    COST_AWARE_BACKUP_SCENARIO: {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "failure_detection_cost_aware_backup",
        "output_file": DATASETS_DIR / f"{COST_AWARE_BACKUP_SCENARIO}_dataset.csv",
        "supported_configs": COST_AWARE_BACKUP_CONFIGS,
        "config_aliases": COST_AWARE_BACKUP_ALIASES,
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            config_name: 150.0 for config_name in COST_AWARE_BACKUP_CONFIGS
        },
    },
    COST_AWARE_TRANSPORT_SCENARIO: {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "failure_detection_cost_aware_transport_impact",
        "output_file": DATASETS_DIR / f"{COST_AWARE_TRANSPORT_SCENARIO}_dataset.csv",
        "supported_configs": COST_AWARE_TRANSPORT_CONFIGS,
        "config_aliases": COST_AWARE_TRANSPORT_ALIASES,
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            config_name: 150.0 for config_name in COST_AWARE_TRANSPORT_CONFIGS
        },
    },
    COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO: {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "ti_inst",
        "output_file": DATASETS_DIR / f"{COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO}_dataset.csv",
        "supported_configs": COST_AWARE_TRANSPORT_INSTRUMENTED_CONFIGS,
        "config_aliases": COST_AWARE_TRANSPORT_INSTRUMENTED_ALIASES,
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            config_name: 150.0 for config_name in COST_AWARE_TRANSPORT_INSTRUMENTED_CONFIGS
        },
    },
    RANDOMIZED_ONSET_SCENARIO: {
        "results_dir": PROJECT_ROOT / "results" / "regionalbackbone" / "ti_randomized_onset",
        "output_file": DATASETS_DIR / f"{RANDOMIZED_ONSET_SCENARIO}_dataset.csv",
        "supported_configs": RANDOMIZED_ONSET_CONFIGS,
        "config_aliases": RANDOMIZED_ONSET_ALIASES,
        "default_sim_time_limit": 150.0,
        "default_sim_time_limits_by_config": {
            config_name: 150.0 for config_name in RANDOMIZED_ONSET_CONFIGS
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
        help="Output CSV path. Defaults to analysis/output/datasets/<scenario>_dataset.csv.",
    )
    parser.add_argument(
        "--feature-set",
        choices=SUPPORTED_FEATURE_SETS,
        default="baseline",
        help=(
            "Dataset feature set to write. 'baseline' preserves the validated dataset schema. "
            "'extended' writes a separate *_extended_dataset.csv with appended telemetry-v2 "
            "candidate features and a feature-classification report."
        ),
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


def resolve_project_path(path: Path) -> Path:
    # Treat explicit CLI paths as project-root relative when they are not
    # absolute. This preserves documented root-based commands and avoids the
    # common Windows mistake where running from analysis\ turns
    # analysis\output\... into analysis\analysis\output\...
    return path if path.is_absolute() else PROJECT_ROOT / path


def atomic_temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.tmp")


def atomic_write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = atomic_temp_path(path)
    try:
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = atomic_temp_path(path)
    try:
        temp_path.write_text(text, encoding="utf-8", newline="\n")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def file_size_text(path: Path) -> str:
    if not path.exists():
        return "missing"
    size_bytes = path.stat().st_size
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GiB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MiB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KiB"
    return f"{size_bytes} B"


def elapsed_text(start_time: float) -> str:
    return f"{time.perf_counter() - start_time:.2f}s"


def latest_mtime(paths: list[Path]) -> float | None:
    mtimes = [path.stat().st_mtime for path in paths if path.exists()]
    return max(mtimes) if mtimes else None


def warn_if_existing_output_stale(output_file: Path, input_files: list[Path], regenerate_command: str) -> None:
    if not output_file.exists():
        return
    newest_input = latest_mtime(input_files)
    if newest_input is None or output_file.stat().st_mtime >= newest_input:
        return
    newest_inputs = [path for path in input_files if path.exists() and path.stat().st_mtime == newest_input]
    source_text = newest_inputs[0] if newest_inputs else "input result file"
    print(
        "Warning: existing output appears stale before regeneration: "
        f"{output_file} is older than {source_text}. Regenerate with: {regenerate_command}"
    )


def get_scenario_preset(scenario: str) -> dict[str, object]:
    preset = SCENARIO_PRESETS.get(scenario)
    if preset is None:
        supported = ", ".join(sorted(SCENARIO_PRESETS))
        raise SystemExit(f"Unsupported scenario '{scenario}'. Supported scenarios: {supported}")
    return preset


def feature_set_output_file(output_file: Path, feature_set: str, explicit_output: bool) -> Path:
    if feature_set == "baseline" or explicit_output:
        return output_file
    if output_file.name.endswith("_dataset.csv"):
        return output_file.with_name(output_file.name.replace("_dataset.csv", "_extended_dataset.csv"))
    return output_file.with_name(f"{output_file.stem}_extended{output_file.suffix}")


def extended_feature_classification_path(scenario: str) -> Path:
    return REPORTS_DIR / f"{scenario}_extended_feature_classification.txt"


def effective_supported_configs(preset: dict[str, object], include_runtime_protection_configs: bool) -> set[str]:
    supported_configs = set(preset["supported_configs"])
    if include_runtime_protection_configs:
        supported_configs.update(preset.get("optional_runtime_configs", set()))
    return supported_configs


def normalize_config_name(name: str, config_aliases: dict[str, str]) -> str:
    return config_aliases.get(name, name)


def label_for_regionalbackbone_window(config_name: str, window_start: float) -> str:
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
    if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
        return label_for_regionalbackbone_window(config_name, window_start)
    raise SystemExit(f"Unsupported scenario '{scenario}' for labeling")


def sensitivity_outcome_profile(config_name: str) -> OutcomeProfile | None:
    info = SENSITIVITY_CONFIG_INFO.get(config_name)
    if info is None:
        return None
    return OutcomeProfile(
        hard_failure_time_s=float(info["hard_failure_time_s"]),
        protection_mode=str(info["protection_mode"]),
        monitored_app_index=0,
        packet_size_bits=256.0 * 8.0,
        send_interval_s=0.01,
        flow_start_time_s=20.0,
        protection_expected=bool(info["protection_expected"]),
        traffic_profile=f"udp_probe_10ms_degradation_sensitivity_{info['profile_key']}",
        packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
        runtime_model_type=str(info["runtime_model_type"]),
        runtime_model_path=str(info["runtime_model_path"]),
    )


def cost_aware_outcome_profile(config_name: str) -> OutcomeProfile | None:
    info = COST_AWARE_CONFIG_INFO.get(config_name)
    if info is None:
        return None
    return OutcomeProfile(
        hard_failure_time_s=float(info["hard_failure_time_s"]),
        protection_mode=str(info["protection_mode"]),
        monitored_app_index=0,
        packet_size_bits=256.0 * 8.0,
        send_interval_s=0.01,
        flow_start_time_s=20.0,
        protection_expected=bool(info["protection_expected"]),
        traffic_profile=f"mixed_udp_tcp_cost_aware_backup_{info['profile_key']}",
        tcp_app_indices=(7,),
        tcp_flow_start_time_s=25.0,
        tcp_useful_goodput_floor_bps=500_000.0,
        packet_continuity_critical_start_time_s=float(info["start_time_s"]),
        runtime_model_type=str(info["runtime_model_type"]),
        runtime_model_path=str(info["runtime_model_path"]),
    )


def transport_impact_outcome_profile(config_name: str) -> OutcomeProfile | None:
    info = COST_AWARE_TRANSPORT_CONFIG_INFO.get(config_name)
    if info is None:
        info = COST_AWARE_TRANSPORT_INSTRUMENTED_CONFIG_INFO.get(config_name)
    if info is None:
        info = RANDOMIZED_ONSET_CONFIG_INFO.get(config_name)
    if info is None:
        return None
    return OutcomeProfile(
        hard_failure_time_s=float(info["hard_failure_time_s"]),
        protection_mode=str(info["protection_mode"]),
        monitored_app_index=0,
        packet_size_bits=256.0 * 8.0,
        send_interval_s=0.01,
        flow_start_time_s=20.0,
        protection_expected=bool(info["protection_expected"]),
        traffic_profile=f"mixed_udp_tcp_cost_aware_transport_{info['profile_key']}",
        tcp_app_indices=(7,),
        tcp_flow_start_time_s=25.0,
        tcp_useful_goodput_floor_bps=500_000.0,
        packet_continuity_critical_start_time_s=float(info["start_time_s"]),
        runtime_model_type=str(info["runtime_model_type"]),
        runtime_model_path=str(info["runtime_model_path"]),
    )


def degradation_metadata_fields(scenario: str, config_name: str) -> dict[str, object]:
    if scenario == DEGRADED_LINK_MODEL_FAMILY_SCENARIO:
        return {
            "scenario_role": "predictive_link_failure_recovery",
            "traffic_mix_model": "udp_monitoring_plus_repeated_tcp_request_reply",
            "tcp_app_indices": "7",
            "tcp_flow_start_time_s": 25.0,
            "tcp_metric_scope": "endpoint_received_bytes_goodput_progress_proxy",
            "protected_primary_bottleneck_enabled": "1",
            "primary_impairment_model": "controlled_brownout_plus_core_bottleneck",
        }
    if scenario == DEGRADATION_SENSITIVITY_SCENARIO:
        info = SENSITIVITY_CONFIG_INFO.get(config_name)
    elif scenario == COST_AWARE_BACKUP_SCENARIO:
        info = COST_AWARE_CONFIG_INFO.get(config_name)
    elif scenario == COST_AWARE_TRANSPORT_SCENARIO:
        info = COST_AWARE_TRANSPORT_CONFIG_INFO.get(config_name)
    elif scenario == COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
        info = COST_AWARE_TRANSPORT_INSTRUMENTED_CONFIG_INFO.get(config_name)
    elif scenario == RANDOMIZED_ONSET_SCENARIO:
        info = RANDOMIZED_ONSET_CONFIG_INFO.get(config_name)
    else:
        return {}
    if info is None:
        return {}
    fields = {
        "degradation_profile": info["label"],
        "degradation_profile_key": info["profile_key"],
        "degradation_start_time_s": info["start_time_s"],
        "degradation_end_time_s": info["end_time_s"],
        "degradation_target_delay_s": info["target_delay_s"],
        "degradation_target_packet_error_rate": info["target_packet_error_rate"],
        "degradation_hard_failure_time_s": info["hard_failure_time_s"],
    }
    if scenario in {COST_AWARE_BACKUP_SCENARIO, COST_AWARE_TRANSPORT_SCENARIO, COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO, RANDOMIZED_ONSET_SCENARIO}:
        fields.update({
            "backup_path_penalty_model": info.get("backup_path_penalty", ""),
            "backup_path_data_rate_bps": 100_000_000.0,
            "backup_path_extra_delay_s": 0.005,
            "primary_path_normal_data_rate_bps": 100_000_000.0,
            "primary_path_normal_extra_delay_s": 0.0,
        })
    if scenario in {COST_AWARE_TRANSPORT_SCENARIO, COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO, RANDOMIZED_ONSET_SCENARIO}:
        fields.update({
            "traffic_mix_model": info.get("traffic_mix", "udp_monitoring_plus_repeated_tcp_request_reply"),
            "tcp_app_indices": "7",
            "tcp_flow_start_time_s": 25.0,
            "tcp_metric_scope": "endpoint_received_bytes_goodput_progress_proxy",
        })
    elif scenario in {DEFAULT_SCENARIO, COST_AWARE_BACKUP_SCENARIO}:
        fields.update({
            "traffic_mix_model": "udp_monitoring_plus_repeated_tcp_request_reply",
            "tcp_app_indices": "7",
            "tcp_flow_start_time_s": 25.0,
            "tcp_metric_scope": "endpoint_received_bytes_goodput_progress_proxy",
        })
    if scenario == COST_AWARE_TRANSPORT_INSTRUMENTED_SCENARIO:
        fields["instrumentation_mode"] = info.get("instrumentation_mode", "targeted_inet_transport_network_telemetry")
        fields["scenario_role"] = info.get("scenario_role", "congestion_queue_buildup_early_mitigation")
        fields["protected_primary_bottleneck_enabled"] = bool_flag(
            bool(info.get("protected_primary_bottleneck_enabled", False))
        )
        fields["primary_impairment_model"] = "protected_core_bottleneck_queue_buildup"
    elif scenario == RANDOMIZED_ONSET_SCENARIO:
        fields["instrumentation_mode"] = info.get("instrumentation_mode", "targeted_inet_transport_network_telemetry")
        fields["scenario_role"] = info.get("scenario_role", "queue_buildup_randomized_onset_robustness")
        fields["protected_primary_bottleneck_enabled"] = bool_flag(
            bool(info.get("protected_primary_bottleneck_enabled", False))
        )
        fields["primary_impairment_model"] = "protected_core_bottleneck_shifted_queue_buildup"
        fields["randomized_onset_time_s"] = info.get("randomized_onset_time_s", "")
        fields["onset_seed"] = info.get("onset_seed", "")
        fields["qos_event_monitor_start_time_s"] = info.get("qos_event_monitor_start_time_s", "")
    elif scenario == COST_AWARE_BACKUP_SCENARIO:
        fields["scenario_role"] = "cost_aware_degraded_backup_operation"
        fields["protected_primary_bottleneck_enabled"] = "0"
        fields["primary_impairment_model"] = "progressive_degradation_without_core_bottleneck"
    elif scenario == DEFAULT_SCENARIO:
        fields["scenario_role"] = "predictive_link_failure_recovery"
        fields["protected_primary_bottleneck_enabled"] = "1"
        fields["primary_impairment_model"] = "controlled_brownout_plus_core_bottleneck"
    return fields


def get_outcome_profile(scenario: str, config_name: str) -> OutcomeProfile:
    if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
        sensitivity_profile = sensitivity_outcome_profile(config_name)
        if sensitivity_profile is not None:
            return sensitivity_profile
        cost_aware_profile = cost_aware_outcome_profile(config_name)
        if cost_aware_profile is not None:
            return cost_aware_profile
        transport_profile = transport_impact_outcome_profile(config_name)
        if transport_profile is not None:
            return transport_profile
        profiles = {
            "RegionalBackboneCongestionDegradation": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="reactive_only",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                traffic_profile="mixed_udp_tcp_staged_congestion_runtime_export",
                tcp_app_indices=(7,),
                tcp_flow_start_time_s=25.0,
                tcp_useful_goodput_floor_bps=500_000.0,
                packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
            ),
            "RegionalBackboneFailureDegradedLinkOspfOnly": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="ospf_only",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                traffic_profile="mixed_udp_tcp_staged_congestion_progressive_link_loss",
                tcp_app_indices=(7,),
                tcp_flow_start_time_s=25.0,
                tcp_useful_goodput_floor_bps=500_000.0,
                packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
            ),
            "RegionalBackboneFailureDegradedLinkBfdLikeFrr": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="bfd_like_frr",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                traffic_profile="mixed_udp_tcp_staged_congestion_progressive_link_loss",
                tcp_app_indices=(7,),
                tcp_flow_start_time_s=25.0,
                tcp_useful_goodput_floor_bps=500_000.0,
                packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
            ),
            "RegionalBackboneFailureDegradedLinkAiMrceRuleBased": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="aimrce_rule_based_frr",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
                traffic_profile="mixed_udp_tcp_staged_congestion_progressive_link_loss",
                tcp_app_indices=(7,),
                tcp_flow_start_time_s=25.0,
                tcp_useful_goodput_floor_bps=500_000.0,
                packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
                runtime_model_type="rule_based",
            ),
            "RegionalBackboneFailureDegradedLinkAiMrceLogReg": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="aimrce_logistic_regression_frr",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
                traffic_profile="mixed_udp_tcp_staged_congestion_progressive_link_loss",
                tcp_app_indices=(7,),
                tcp_flow_start_time_s=25.0,
                tcp_useful_goodput_floor_bps=500_000.0,
                packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
                runtime_model_type="logistic_regression",
                runtime_model_path="aimrce_runtime_logreg.csv",
            ),
            "RegionalBackboneFailureDegradedLinkAiMrceLinearSvm": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="aimrce_linear_svm_frr",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
                traffic_profile="mixed_udp_tcp_staged_congestion_progressive_link_loss",
                tcp_app_indices=(7,),
                tcp_flow_start_time_s=25.0,
                tcp_useful_goodput_floor_bps=500_000.0,
                packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
                runtime_model_type="linear_svm",
                runtime_model_path="aimrce_runtime_linsvm.csv",
            ),
            "RegionalBackboneFailureDegradedLinkAiMrceShallowTree": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="aimrce_shallow_tree_frr",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
                traffic_profile="mixed_udp_tcp_staged_congestion_progressive_link_loss",
                tcp_app_indices=(7,),
                tcp_flow_start_time_s=25.0,
                tcp_useful_goodput_floor_bps=500_000.0,
                packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
                runtime_model_type="shallow_tree",
                runtime_model_path="aimrce_runtime_shallow_tree.csv",
            ),
            "RegionalBackboneFailureDegradedLinkHybrid": OutcomeProfile(
                hard_failure_time_s=REGIONAL_CONGESTION_HARD_FAILURE_TIME_SECONDS,
                protection_mode="hybrid_bfd_like_aimrce_frr",
                monitored_app_index=0,
                packet_size_bits=256.0 * 8.0,
                send_interval_s=0.01,
                flow_start_time_s=20.0,
                protection_expected=True,
                traffic_profile="mixed_udp_tcp_staged_congestion_progressive_link_loss",
                tcp_app_indices=(7,),
                tcp_flow_start_time_s=25.0,
                tcp_useful_goodput_floor_bps=500_000.0,
                packet_continuity_critical_start_time_s=REGIONAL_CONGESTION_RISING_END_SECONDS,
                runtime_model_type="rule_based",
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


@dataclass(frozen=True)
class IndexedTimeSeries:
    # OMNeT++ vector samples are emitted in timestamp order per vector. The
    # previous implementation relied on the same ordering; indexing keeps those
    # semantics while avoiding repeated full-series scans for every window.
    times: list[float]
    values: list[float]

    @classmethod
    def from_series(cls, series: list[tuple[float, float]]) -> "IndexedTimeSeries":
        return cls(
            [timestamp for timestamp, _ in series],
            [value for _, value in series],
        )

    def __bool__(self) -> bool:
        return bool(self.times)

    def window_values(self, window_start: float, window_end: float) -> list[float]:
        start_index = bisect_left(self.times, window_start)
        end_index = bisect_left(self.times, window_end)
        return self.values[start_index:end_index]

    def window_items(self, window_start: float, window_end: float) -> list[tuple[float, float]]:
        start_index = bisect_left(self.times, window_start)
        end_index = bisect_left(self.times, window_end)
        return list(zip(self.times[start_index:end_index], self.values[start_index:end_index]))

    def last_value_before_or_at(self, time_point: float) -> float | None:
        index = bisect_right(self.times, time_point) - 1
        if index < 0:
            return None
        return self.values[index]

    def items_until(self, end_time_s: float | None = None) -> list[tuple[float, float]]:
        if end_time_s is None:
            return list(zip(self.times, self.values))
        end_index = bisect_right(self.times, end_time_s)
        return list(zip(self.times[:end_index], self.values[:end_index]))


SeriesLike = IndexedTimeSeries | list[tuple[float, float]]


def indexed_series(series: SeriesLike) -> IndexedTimeSeries:
    if isinstance(series, IndexedTimeSeries):
        return series
    return IndexedTimeSeries.from_series(series)


@dataclass(frozen=True)
class PacketContinuitySeries:
    samples: list[tuple[float, float]]
    times: list[float]

    @classmethod
    def from_series(cls, series: list[tuple[float, float]], flow_start_time_s: float) -> "PacketContinuitySeries":
        samples = sorted((timestamp, value) for timestamp, value in series if timestamp >= flow_start_time_s)
        return cls(samples, [timestamp for timestamp, _ in samples])

    def __bool__(self) -> bool:
        return bool(self.samples)

    def samples_until(self, end_time_s: float | None = None) -> list[tuple[float, float]]:
        if end_time_s is None:
            return self.samples
        end_index = bisect_right(self.times, end_time_s)
        return self.samples[:end_index]


def last_value_before_or_at(series: SeriesLike, time_point: float) -> float | None:
    return indexed_series(series).last_value_before_or_at(time_point)


def values_in_window(series: SeriesLike, window_start: float, window_end: float) -> list[float]:
    return indexed_series(series).window_values(window_start, window_end)


def sample_summary(
    series: SeriesLike,
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


def state_summary(series: SeriesLike, window_start: float, window_end: float) -> dict[str, float | str]:
    indexed = indexed_series(series)
    if not indexed:
        return {"mean": "", "max": "", "last": ""}

    window_duration = window_end - window_start
    if window_duration <= 0:
        return {"mean": "", "max": "", "last": ""}

    current_value = indexed.last_value_before_or_at(window_start)
    current_time = window_start
    integral = 0.0
    max_value = current_value
    had_state = current_value is not None

    for timestamp, value in indexed.window_items(window_start, window_end):
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


def sequence_summary(series: SeriesLike, window_start: float, window_end: float) -> dict[str, int | str]:
    indexed = indexed_series(series)
    if not indexed:
        return {"count": 0, "progress": 0, "last": ""}

    window_events = indexed.window_items(window_start, window_end)
    count = len(window_events)

    start_value = indexed.last_value_before_or_at(window_start)
    end_value = indexed.last_value_before_or_at(window_end)

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


def packet_bytes_summary(series: SeriesLike, window_start: float, window_end: float) -> dict[str, float | int | str]:
    indexed = indexed_series(series)
    if not indexed:
        return {"count": 0, "bytes": "", "goodput_bps": ""}

    values = [max(0.0, value) for value in indexed.window_values(window_start, window_end)]
    if not values:
        return {"count": 0, "bytes": 0.0, "goodput_bps": 0.0}

    duration = window_end - window_start
    if duration <= 0:
        return {"count": len(values), "bytes": sum(values), "goodput_bps": ""}

    total_bytes = sum(values)
    return {
        "count": len(values),
        "bytes": total_bytes,
        "goodput_bps": (total_bytes * 8.0) / duration,
    }


def init_run_data(scenario: str, feature_set: str = "baseline") -> dict:
    run_data = {
        "receiver_apps": {},
        "scalars": {},
    }
    if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
        run_data["controller"] = {
            "appliedDelay": [],
            "appliedPacketErrorRate": [],
        }
        if feature_set == "extended":
            run_data["ai_mrce"] = {name: [] for name in AI_MRCE_VECTOR_NAMES}
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
        "packetBytes": [],
    })


def register_vector_target(
    scenario: str,
    config_name: str,
    run_data: dict,
    module: str,
    name: str,
    feature_set: str = "baseline",
) -> tuple[str, int | str | None] | None:
    if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS and module.endswith(".degradationController") and name in {"appliedDelay", "appliedPacketErrorRate"}:
        return ("controller", name)

    if (
        feature_set == "extended"
        and scenario in REGIONALBACKBONE_FAMILY_SCENARIOS
        and module.endswith(".aiMrceController")
        and name in AI_MRCE_VECTOR_NAMES
    ):
        return ("ai_mrce", name)

    if (
        scenario in REGIONALBACKBONE_FAMILY_SCENARIOS
        and config_name in REGIONALBACKBONE_CONGESTION_STYLE_CONFIGS
        and module.endswith(REGIONAL_BOTTLENECK_QUEUE_MODULE_SUFFIX)
        and name in {"queueLength", "queueBitLength", "queueingTime"}
    ):
        return ("bottleneck_queue", name)

    match = HOSTB_APP_RE.match(module)
    if match:
        app_index = int(match.group(1))
        if name in {"throughput", "endToEndDelay", "rcvdPkSeqNo"}:
            return (name, app_index)
        if name == "packetReceived" or name.startswith("packetReceived:"):
            # INET TCP applications expose received payload through
            # packetReceived byte vectors when enabled. We summarize those
            # endpoint-observable bytes as a project-local useful-goodput proxy.
            return ("packetBytes", app_index)

    match = HOSTA_APP_RE.match(module)
    if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS and match:
        app_index = int(match.group(1))
        if app_index == 7 and (name == "packetReceived" or name.startswith("packetReceived:")):
            # The unified mixed-traffic workload uses TcpBasicClientApp on hostA and
            # TcpGenericServerApp on hostB; client-side reply bytes are the TCP
            # endpoint progress/goodput proxy.
            return ("packetBytes", app_index)

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
    feature_set: str,
) -> dict | None:
    metadata = {
        "configname": None,
        "runnumber": None,
        "sim_time_limit": None,
    }
    run_data = init_run_data(scenario, feature_set)
    vector_targets: dict[int, tuple[str, int | str | None]] = {}
    targeted_vector_count = 0
    targeted_sample_count = 0
    vec_parse_start = time.perf_counter()

    with vec_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("attr configname "):
                metadata["configname"] = line.split(" ", 2)[2]
                normalized_name = normalize_config_name(metadata["configname"] or "", config_aliases)
                if normalized_name not in supported_configs:
                    return None
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
                target = register_vector_target(scenario, configname, run_data, module, name, feature_set)
                if target is not None:
                    vector_targets[vector_id] = target
                    targeted_vector_count += 1
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
            targeted_sample_count += 1

            target_type, target_key = target
            if target_type == "controller":
                run_data["controller"][target_key].append((timestamp, value))
            elif target_type == "ai_mrce":
                run_data["ai_mrce"][target_key].append((timestamp, value))
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
    scalar_start = time.perf_counter()
    run_data["scalars"] = parse_scalar_file(vec_path.with_suffix(".sca"))
    run_data["diagnostics"] = {
        "vec_parse_time_s": time.perf_counter() - vec_parse_start,
        "scalar_parse_time_s": time.perf_counter() - scalar_start,
        "targeted_vector_count": targeted_vector_count,
        "targeted_sample_count": targeted_sample_count,
    }
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


def optional_nonnegative_numeric(value: float | int | None) -> float | int | str:
    if value is None:
        return ""
    if float(value) < 0:
        return ""
    return value


def bool_flag(value: bool | None) -> int | str:
    if value is None:
        return ""
    return 1 if value else 0


def ratio_or_none(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    denominator_value = float(denominator)
    if denominator_value <= 0:
        return None
    return float(numerator) / denominator_value


def delta_or_none(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous is None:
        return None
    return float(current) - float(previous)


def rate_or_none(delta: float | int | None, duration_s: float | int | None) -> float | None:
    if delta is None or duration_s is None or float(duration_s) <= 0:
        return None
    return float(delta) / float(duration_s)


def is_impairment_active(row: dict[str, object]) -> bool:
    per_values = [
        parse_numeric_cell(row.get("controller_packet_error_rate_mean")),
        parse_numeric_cell(row.get("controller_packet_error_rate_max")),
        parse_numeric_cell(row.get("controller_packet_error_rate_last")),
    ]
    if any(value is not None and value > 0.0 for value in per_values):
        return True

    delay_values = [
        parse_numeric_cell(row.get("controller_delay_mean_s")),
        parse_numeric_cell(row.get("controller_delay_max_s")),
        parse_numeric_cell(row.get("controller_delay_last_s")),
    ]
    # The configured non-degraded channel delay is around 1e-7s, so a small
    # tolerance avoids marking baseline windows as degraded.
    return any(value is not None and value > 1e-6 for value in delay_values)


def extended_phase_context(row: dict[str, object]) -> str:
    window_start = parse_numeric_cell(row.get("window_start_s"))
    hard_failure_time = parse_numeric_cell(row.get("hard_failure_time_s"))
    activation_time = parse_numeric_cell(row.get("protection_activation_time_s"))
    if window_start is None:
        return ""
    if hard_failure_time is not None and window_start >= hard_failure_time:
        return "post_hard_failure"
    if (
        activation_time is not None
        and hard_failure_time is not None
        and activation_time < hard_failure_time
        and window_start >= activation_time
    ):
        return "activation_to_failure"
    if is_impairment_active(row):
        return "degradation_pre_activation"
    return "pre_degradation"


def extended_impairment_state(row: dict[str, object]) -> str:
    if not is_impairment_active(row):
        return "none"
    per_mean = parse_numeric_cell(row.get("controller_packet_error_rate_mean")) or 0.0
    if per_mean >= 0.5:
        return "severe_brownout"
    if per_mean >= 0.05:
        return "moderate_impairment"
    return "mild_impairment"


def protection_trigger_source_from_code(code: float | int | None, protection_mode: str, activated: bool) -> str:
    if code is not None:
        code_int = int(round(float(code)))
        return {
            0: "none",
            1: "aimrce",
            2: "bfd_like",
            3: "hybrid_aimrce_first",
            4: "hybrid_bfd_like_first",
        }.get(code_int, f"unknown_code_{code_int}")

    if not activated:
        return "none"
    if protection_mode == "bfd_like_frr":
        return "bfd_like"
    if protection_mode == "hybrid_bfd_like_aimrce_frr":
        return "hybrid_unknown_first"
    if protection_mode.startswith("aimrce"):
        return "aimrce"
    return "unknown"


def bfd_like_trigger_reason_from_code(code: float | int | None) -> str:
    if code is None:
        return ""
    code_int = int(round(float(code)))
    return {
        0: "none",
        1: "receiver_probe_interval_below_expected",
        2: "protected_span_interface_down",
        3: "modeled_probe_loss_from_channel_per",
    }.get(code_int, f"unknown_code_{code_int}")


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


def service_gap_metrics(
    rows: list[dict[str, object]],
    availability_column: str,
    reference_time_s: float | None,
) -> tuple[float | None, float | None, float | None, int | None, int | None]:
    if reference_time_s is None:
        return None, None, None, None, None

    interruption_start_time_s = None
    interruption_end_time_s = None
    zero_window_count = 0
    max_zero_streak = 0
    current_zero_streak = 0
    interruption_started = False

    for row in rows:
        window_start_s = float(row["window_start_s"])
        if window_start_s < reference_time_s:
            continue

        service_available = parse_int_cell(row.get(availability_column))
        if service_available == 0:
            zero_window_count += 1
            current_zero_streak += 1
            max_zero_streak = max(max_zero_streak, current_zero_streak)
            if not interruption_started:
                interruption_start_time_s = window_start_s
                interruption_started = True
            continue

        current_zero_streak = 0
        if interruption_started and service_available == 1 and window_start_s > interruption_start_time_s:
            interruption_end_time_s = window_start_s
            break

    interruption_duration_s = None
    if interruption_start_time_s is not None and interruption_end_time_s is not None:
        interruption_duration_s = interruption_end_time_s - interruption_start_time_s

    return (
        interruption_start_time_s,
        interruption_end_time_s,
        interruption_duration_s,
        zero_window_count,
        max_zero_streak,
    )


def packet_continuity_metrics(
    series: list[tuple[float, float]] | PacketContinuitySeries,
    reference_time_s: float | None,
    expected_send_interval_s: float,
    flow_start_time_s: float,
    end_time_s: float | None = None,
) -> dict[str, float | int | bool | None]:
    # Receiver sequence numbers expose short packet-continuity disruptions that
    # can be hidden by the coarser one-second availability windows. The
    # interarrival threshold is deliberately transparent: three nominal probe
    # send intervals, not a protocol restoration target or literature claim.
    if reference_time_s is None or not series:
        return {
            "packet_sequence_gap_observed_after_reference": None,
            "packet_sequence_gap_count_after_reference": None,
            "packet_sequence_gap_total_missing_after_reference": None,
            "packet_sequence_gap_total_unobserved_after_reference": None,
            "packet_sequence_gap_total_reordered_after_reference": None,
            "max_packet_sequence_gap_after_reference": None,
            "max_packet_interarrival_gap_after_reference_s": None,
            "packet_interarrival_nominal_gap_threshold_s": None,
            "packet_interarrival_gap_exceedance_count_after_reference": None,
            "packet_interarrival_gap_exceeded_nominal_threshold": None,
            "packet_sequence_out_of_order_event_count_after_reference": None,
            "packet_sequence_out_of_order_packet_count_after_reference": None,
            "first_packet_after_reference_delay_s": None,
        }

    threshold_s = 3.0 * expected_send_interval_s
    if end_time_s is not None and end_time_s <= reference_time_s:
        return {
            "packet_sequence_gap_observed_after_reference": False,
            "packet_sequence_gap_count_after_reference": 0,
            "packet_sequence_gap_total_missing_after_reference": 0,
            "packet_sequence_gap_total_unobserved_after_reference": 0,
            "packet_sequence_gap_total_reordered_after_reference": 0,
            "max_packet_sequence_gap_after_reference": 0,
            "max_packet_interarrival_gap_after_reference_s": 0.0,
            "packet_interarrival_nominal_gap_threshold_s": threshold_s,
            "packet_interarrival_gap_exceedance_count_after_reference": 0,
            "packet_interarrival_gap_exceeded_nominal_threshold": False,
            "packet_sequence_out_of_order_event_count_after_reference": 0,
            "packet_sequence_out_of_order_packet_count_after_reference": 0,
            "first_packet_after_reference_delay_s": None,
        }

    continuity_series = (
        series
        if isinstance(series, PacketContinuitySeries)
        else PacketContinuitySeries.from_series(series, flow_start_time_s)
    )
    samples = continuity_series.samples_until(end_time_s)
    if len(samples) < 2:
        first_after = next((timestamp for timestamp, _ in samples if timestamp >= reference_time_s), None)
        return {
            "packet_sequence_gap_observed_after_reference": False,
            "packet_sequence_gap_count_after_reference": 0,
            "packet_sequence_gap_total_missing_after_reference": 0,
            "packet_sequence_gap_total_unobserved_after_reference": 0,
            "packet_sequence_gap_total_reordered_after_reference": 0,
            "max_packet_sequence_gap_after_reference": 0,
            "max_packet_interarrival_gap_after_reference_s": 0.0,
            "packet_interarrival_nominal_gap_threshold_s": threshold_s,
            "packet_interarrival_gap_exceedance_count_after_reference": 0,
            "packet_interarrival_gap_exceeded_nominal_threshold": False,
            "packet_sequence_out_of_order_event_count_after_reference": 0,
            "packet_sequence_out_of_order_packet_count_after_reference": 0,
            "first_packet_after_reference_delay_s": (
                first_after - reference_time_s if first_after is not None else None
            ),
        }

    sequence_gap_count = 0
    total_missing_packets = 0
    total_unobserved_packets = 0
    total_reordered_gap_packets = 0
    max_sequence_gap = 0
    max_interarrival_gap_s = 0.0
    interarrival_exceedance_count = 0
    out_of_order_event_count = 0
    out_of_order_packet_count = 0
    max_seen_sequence = int(round(samples[0][1]))
    observed_sequences = {int(round(value)) for _, value in samples}

    previous_timestamp, previous_value = samples[0]
    for timestamp, value in samples[1:]:
        overlaps_reference_interval = previous_timestamp < reference_time_s <= timestamp
        if timestamp < reference_time_s and not overlaps_reference_interval:
            max_seen_sequence = max(max_seen_sequence, int(round(value)))
            previous_timestamp, previous_value = timestamp, value
            continue

        interarrival_gap_s = timestamp - previous_timestamp
        max_interarrival_gap_s = max(max_interarrival_gap_s, interarrival_gap_s)
        if interarrival_gap_s > threshold_s:
            interarrival_exceedance_count += 1

        sequence_jump = max(0, int(round(value - previous_value)))
        if sequence_jump > 1:
            sequence_gap_count += 1
            skipped_sequences = range(int(round(previous_value)) + 1, int(round(value)))
            skipped_count = sequence_jump - 1
            observed_skipped_count = sum(1 for sequence in skipped_sequences if sequence in observed_sequences)
            unobserved_skipped_count = skipped_count - observed_skipped_count
            total_missing_packets += skipped_count
            total_reordered_gap_packets += observed_skipped_count
            total_unobserved_packets += unobserved_skipped_count
            max_sequence_gap = max(max_sequence_gap, sequence_jump - 1)

        current_sequence = int(round(value))
        if current_sequence < max_seen_sequence:
            out_of_order_event_count += 1
            out_of_order_packet_count += 1
        max_seen_sequence = max(max_seen_sequence, current_sequence)

        previous_timestamp, previous_value = timestamp, value

    first_packet_after_reference = next((timestamp for timestamp, _ in samples if timestamp >= reference_time_s), None)

    return {
        "packet_sequence_gap_observed_after_reference": sequence_gap_count > 0,
        "packet_sequence_gap_count_after_reference": sequence_gap_count,
        "packet_sequence_gap_total_missing_after_reference": total_missing_packets,
        "packet_sequence_gap_total_unobserved_after_reference": total_unobserved_packets,
        "packet_sequence_gap_total_reordered_after_reference": total_reordered_gap_packets,
        "max_packet_sequence_gap_after_reference": max_sequence_gap,
        "max_packet_interarrival_gap_after_reference_s": max_interarrival_gap_s,
        "packet_interarrival_nominal_gap_threshold_s": threshold_s,
        "packet_interarrival_gap_exceedance_count_after_reference": interarrival_exceedance_count,
        "packet_interarrival_gap_exceeded_nominal_threshold": interarrival_exceedance_count > 0,
        "packet_sequence_out_of_order_event_count_after_reference": out_of_order_event_count,
        "packet_sequence_out_of_order_packet_count_after_reference": out_of_order_packet_count,
        "first_packet_after_reference_delay_s": (
            first_packet_after_reference - reference_time_s
            if first_packet_after_reference is not None
            else None
        ),
    }


def add_packet_continuity_outcome_fields(
    output_fields: dict[str, object],
    suffix: str,
    metrics: dict[str, float | int | bool | None],
) -> None:
    output_fields[f"packet_sequence_gap_observed_{suffix}"] = bool_flag(metrics["packet_sequence_gap_observed_after_reference"])
    output_fields[f"packet_sequence_gap_count_{suffix}"] = optional_numeric(metrics["packet_sequence_gap_count_after_reference"])
    output_fields[f"packet_sequence_gap_total_missing_{suffix}"] = optional_numeric(metrics["packet_sequence_gap_total_missing_after_reference"])
    output_fields[f"packet_sequence_gap_total_unobserved_{suffix}"] = optional_numeric(metrics["packet_sequence_gap_total_unobserved_after_reference"])
    output_fields[f"packet_sequence_gap_total_reordered_{suffix}"] = optional_numeric(metrics["packet_sequence_gap_total_reordered_after_reference"])
    output_fields[f"max_packet_sequence_gap_{suffix}"] = optional_numeric(metrics["max_packet_sequence_gap_after_reference"])
    output_fields[f"max_packet_interarrival_gap_{suffix}_s"] = optional_numeric(metrics["max_packet_interarrival_gap_after_reference_s"])
    output_fields[f"packet_interarrival_gap_exceedance_count_{suffix}"] = optional_numeric(metrics["packet_interarrival_gap_exceedance_count_after_reference"])
    output_fields[f"packet_interarrival_gap_exceeded_nominal_threshold_{suffix}"] = bool_flag(metrics["packet_interarrival_gap_exceeded_nominal_threshold"])
    output_fields[f"packet_sequence_out_of_order_event_count_{suffix}"] = optional_numeric(metrics["packet_sequence_out_of_order_event_count_after_reference"])
    output_fields[f"packet_sequence_out_of_order_packet_count_{suffix}"] = optional_numeric(metrics["packet_sequence_out_of_order_packet_count_after_reference"])
    output_fields[f"first_packet_{suffix}_delay_s"] = optional_numeric(metrics["first_packet_after_reference_delay_s"])


def endpoint_receive_gap_metrics(
    receiver_apps: dict[int, dict[str, list[tuple[float, float]]]],
    app_indices: tuple[int, ...],
    reference_time_s: float | None,
    flow_start_time_s: float | None,
) -> dict[str, float | int | None]:
    # Mixed TCP evaluation remains endpoint-observable only. This helper uses
    # application packet-byte timestamps as a useful-goodput continuity proxy;
    # it does not inspect TCP retransmission, congestion-window, or RTO internals.
    if reference_time_s is None or not app_indices:
        return {
            "tcp_endpoint_receive_event_count_after_reference": None,
            "tcp_first_endpoint_receive_delay_after_reference_s": None,
            "tcp_max_endpoint_receive_gap_after_reference_s": None,
        }

    start_time_s = flow_start_time_s if flow_start_time_s is not None else 0.0
    samples: list[tuple[float, float]] = []
    for app_index in app_indices:
        samples.extend(receiver_apps.get(app_index, {}).get("packetBytes", []))

    samples = sorted((timestamp, value) for timestamp, value in samples if timestamp >= start_time_s)
    if not samples:
        return {
            "tcp_endpoint_receive_event_count_after_reference": 0,
            "tcp_first_endpoint_receive_delay_after_reference_s": None,
            "tcp_max_endpoint_receive_gap_after_reference_s": None,
        }

    receive_event_count_after_reference = sum(1 for timestamp, _ in samples if timestamp >= reference_time_s)
    first_after = next((timestamp for timestamp, _ in samples if timestamp >= reference_time_s), None)
    max_gap_s = 0.0

    previous_timestamp, _ = samples[0]
    for timestamp, value in samples[1:]:
        overlaps_reference_interval = previous_timestamp < reference_time_s <= timestamp
        if timestamp >= reference_time_s or overlaps_reference_interval:
            max_gap_s = max(max_gap_s, timestamp - previous_timestamp)
        previous_timestamp = timestamp

    return {
        "tcp_endpoint_receive_event_count_after_reference": receive_event_count_after_reference,
        "tcp_first_endpoint_receive_delay_after_reference_s": (
            first_after - reference_time_s if first_after is not None else None
        ),
        "tcp_max_endpoint_receive_gap_after_reference_s": max_gap_s,
    }


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
    protection_action_code = run_data["scalars"].get("protectionActionCode")
    protection_trigger_source_code = run_data["scalars"].get("protectionTriggerSourceCode")
    repair_routes_installed = run_data["scalars"].get("repairRoutesInstalled")
    repair_route_count = run_data["scalars"].get("repairRouteCount")
    repair_route_install_time_s = run_data["scalars"].get("repairRouteInstallTime")
    enable_aimrce_decision = run_data["scalars"].get("enableAimrceDecision")
    enable_bfd_like_detection = run_data["scalars"].get("enableBfdLikeDetection")
    aimrce_policy_code = run_data["scalars"].get("aimrcePolicyCode")
    runtime_model_artifact_required = run_data["scalars"].get("runtimeModelArtifactRequired")
    runtime_model_loaded = run_data["scalars"].get("runtimeModelLoaded")
    runtime_model_feature_count = run_data["scalars"].get("runtimeModelFeatureCount")
    runtime_model_threshold = run_data["scalars"].get("runtimeModelThreshold")
    runtime_model_fallback_used = run_data["scalars"].get("runtimeModelFallbackUsed")
    runtime_model_fallback_reason_code = run_data["scalars"].get("runtimeModelFallbackReasonCode")
    aimrce_evaluation_interval_s = run_data["scalars"].get("aimrceEvaluationInterval")
    aimrce_activation_consecutive_cycles_configured = run_data["scalars"].get("aimrceActivationConsecutiveCyclesConfigured")
    bfd_like_detection_activated = run_data["scalars"].get("bfdLikeDetectionActivated")
    bfd_like_detection_time_s = run_data["scalars"].get("bfdLikeDetectionTime")
    bfd_like_detect_multiplier = run_data["scalars"].get("bfdLikeDetectMultiplier")
    bfd_like_detection_interval_s = run_data["scalars"].get("bfdLikeDetectionInterval")
    bfd_like_expected_detection_time_s = run_data["scalars"].get("bfdLikeExpectedDetectionTime")
    bfd_like_missed_probe_count = run_data["scalars"].get("bfdLikeMissedProbeCount")
    bfd_like_max_missed_probe_count = run_data["scalars"].get("bfdLikeMaxMissedProbeCount")
    bfd_like_use_modeled_probe_loss = run_data["scalars"].get("bfdLikeUseModeledProbeLoss")
    bfd_like_probe_checks = run_data["scalars"].get("bfdLikeProbeChecks")
    bfd_like_probe_successes = run_data["scalars"].get("bfdLikeProbeSuccesses")
    bfd_like_probe_misses = run_data["scalars"].get("bfdLikeProbeMisses")
    bfd_like_probe_loss_rate_observed = run_data["scalars"].get("bfdLikeProbeLossRateObserved")
    bfd_like_modeled_probe_loss_probability_last = run_data["scalars"].get("bfdLikeModeledProbeLossProbabilityLast")
    bfd_like_modeled_probe_loss_probability_max = run_data["scalars"].get("bfdLikeModeledProbeLossProbabilityMax")
    bfd_like_modeled_probe_loss_probability_at_detection = run_data["scalars"].get("bfdLikeModeledProbeLossProbabilityAtDetection")
    bfd_like_trigger_reason_code = run_data["scalars"].get("bfdLikeTriggerReasonCode")
    bfd_like_protected_span_up_at_detection = run_data["scalars"].get("bfdLikeProtectedSpanUpAtDetection")
    bfd_like_detection_before_hard_failure = run_data["scalars"].get("bfdLikeDetectionBeforeHardFailure")
    bfd_like_lead_time_before_failure_s = run_data["scalars"].get("bfdLikeLeadTimeBeforeFailure")
    hard_failure_to_bfd_detection_time_s = run_data["scalars"].get("hardFailureToBfdDetectionTime")
    hard_failure_time_scalar_s = run_data["scalars"].get("hardFailureTime")
    activation_risk_score = run_data["scalars"].get("activationRiskScore")
    activation_decision_threshold = run_data["scalars"].get("activationDecisionThreshold")
    activation_positive_decision_streak = run_data["scalars"].get("activationPositiveDecisionStreak")
    activation_queue_length_pk = run_data["scalars"].get("activationQueueLengthPk")
    activation_queue_bit_length_b = run_data["scalars"].get("activationQueueBitLengthB")
    activation_probe_delay_mean_s = run_data["scalars"].get("activationProbeDelayMeanS")
    activation_probe_throughput_bps = run_data["scalars"].get("activationProbeThroughputBps")
    activation_probe_packet_count = run_data["scalars"].get("activationProbePacketCount")
    protection_trigger_source = protection_trigger_source_from_code(
        protection_trigger_source_code,
        profile.protection_mode,
        protection_activated,
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
    bfd_like_detection_time_nonnegative_s = (
        float(bfd_like_detection_time_s)
        if bfd_like_detection_time_s is not None and float(bfd_like_detection_time_s) >= 0
        else None
    )
    bfd_like_detection_before_failure = (
        bfd_like_detection_time_nonnegative_s is not None
        and hard_failure_time_s is not None
        and bfd_like_detection_time_nonnegative_s < hard_failure_time_s
    )
    bfd_like_lead_time_computed_s = (
        hard_failure_time_s - bfd_like_detection_time_nonnegative_s
        if bfd_like_detection_before_failure and hard_failure_time_s is not None
        else None
    )
    hard_failure_to_bfd_detection_computed_s = (
        bfd_like_detection_time_nonnegative_s - hard_failure_time_s
        if bfd_like_detection_time_nonnegative_s is not None and hard_failure_time_s is not None
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

    tcp_reference_time_s = None
    if profile.tcp_app_indices and reference_time_s is not None:
        tcp_reference_time_s = reference_time_s
        if profile.tcp_flow_start_time_s is not None:
            tcp_reference_time_s = max(reference_time_s, profile.tcp_flow_start_time_s)

    (
        tcp_service_interruption_start_time_s,
        tcp_service_interruption_end_time_s,
        tcp_service_interruption_duration_s,
        tcp_zero_goodput_window_count_after_reference,
        tcp_max_zero_goodput_window_streak_after_reference,
    ) = service_gap_metrics(
        rows,
        "tcp_service_available_operational",
        tcp_reference_time_s,
    )

    tcp_useful_goodput_restored_after_failure: bool | None = None
    if profile.tcp_app_indices and hard_failure_time_s is not None:
        tcp_useful_goodput_restored_after_failure = False
        for row in rows:
            window_start_s = float(row["window_start_s"])
            if window_start_s < hard_failure_time_s:
                continue
            if parse_int_cell(row.get("tcp_service_available_operational")) == 1:
                tcp_useful_goodput_restored_after_failure = True
                break

    zero_progress_window_count_after_reference, max_zero_progress_window_streak_after_reference = zero_progress_gap_metrics(
        rows,
        profile.monitored_app_index,
        reference_time_s,
    )
    monitored_sequence_series = run_data["receiver_apps"].get(profile.monitored_app_index, {}).get("rcvdPkSeqNo", [])
    monitored_continuity_series = PacketContinuitySeries.from_series(
        monitored_sequence_series,
        profile.flow_start_time_s,
    )
    packet_continuity = packet_continuity_metrics(
        monitored_continuity_series,
        reference_time_s,
        profile.send_interval_s,
        profile.flow_start_time_s,
    )
    packet_continuity_after_hard_failure = packet_continuity_metrics(
        monitored_continuity_series,
        hard_failure_time_s,
        profile.send_interval_s,
        profile.flow_start_time_s,
    )
    packet_continuity_after_protection_activation = packet_continuity_metrics(
        monitored_continuity_series,
        protection_activation_time_s if protection_activated else None,
        profile.send_interval_s,
        profile.flow_start_time_s,
    )
    packet_continuity_between_activation_and_failure = packet_continuity_metrics(
        monitored_continuity_series,
        protection_activation_time_s if protection_activated_before_failure else None,
        profile.send_interval_s,
        profile.flow_start_time_s,
        end_time_s=hard_failure_time_s,
    )
    packet_continuity_after_critical_start = packet_continuity_metrics(
        monitored_continuity_series,
        profile.packet_continuity_critical_start_time_s,
        profile.send_interval_s,
        profile.flow_start_time_s,
    )
    tcp_endpoint_receive_gaps = endpoint_receive_gap_metrics(
        run_data["receiver_apps"],
        profile.tcp_app_indices,
        tcp_reference_time_s,
        profile.tcp_flow_start_time_s,
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
        "protection_trigger_source": protection_trigger_source,
        "protection_trigger_source_code": optional_numeric(protection_trigger_source_code),
        "protection_action_code": optional_numeric(protection_action_code),
        "repair_routes_installed": bool_flag(repair_routes_installed > 0.5) if repair_routes_installed is not None else "",
        "repair_route_count": optional_numeric(repair_route_count),
        "repair_route_install_time_s": optional_numeric(repair_route_install_time_s),
        "enable_aimrce_decision": bool_flag(enable_aimrce_decision > 0.5) if enable_aimrce_decision is not None else "",
        "enable_bfd_like_detection": bool_flag(enable_bfd_like_detection > 0.5) if enable_bfd_like_detection is not None else "",
        "aimrce_policy_name": profile.runtime_model_type,
        "aimrce_policy_code": optional_numeric(aimrce_policy_code),
        "runtime_model_artifact_required": bool_flag(runtime_model_artifact_required > 0.5) if runtime_model_artifact_required is not None else "",
        "runtime_model_loaded": bool_flag(runtime_model_loaded > 0.5) if runtime_model_loaded is not None else "",
        "runtime_model_feature_count": optional_numeric(runtime_model_feature_count),
        "runtime_model_threshold": optional_numeric(runtime_model_threshold),
        "runtime_model_fallback_used": bool_flag(runtime_model_fallback_used > 0.5) if runtime_model_fallback_used is not None else "",
        "runtime_model_fallback_reason_code": optional_numeric(runtime_model_fallback_reason_code),
        "aimrce_evaluation_interval_s": optional_numeric(aimrce_evaluation_interval_s),
        "aimrce_activation_consecutive_cycles_configured": optional_numeric(aimrce_activation_consecutive_cycles_configured),
        "bfd_like_detection_activated": bool_flag(bfd_like_detection_activated > 0.5) if bfd_like_detection_activated is not None else "",
        "bfd_like_detection_time_s": optional_nonnegative_numeric(bfd_like_detection_time_s),
        "bfd_like_detect_multiplier": optional_numeric(bfd_like_detect_multiplier),
        "bfd_like_detection_interval_s": optional_numeric(bfd_like_detection_interval_s),
        "bfd_like_expected_detection_time_s": optional_numeric(bfd_like_expected_detection_time_s),
        "bfd_like_missed_probe_count": optional_numeric(bfd_like_missed_probe_count),
        "bfd_like_max_missed_probe_count": optional_numeric(bfd_like_max_missed_probe_count),
        "bfd_like_use_modeled_probe_loss": bool_flag(bfd_like_use_modeled_probe_loss > 0.5) if bfd_like_use_modeled_probe_loss is not None else "",
        "bfd_like_probe_checks": optional_numeric(bfd_like_probe_checks),
        "bfd_like_probe_successes": optional_numeric(bfd_like_probe_successes),
        "bfd_like_probe_misses": optional_numeric(bfd_like_probe_misses),
        "bfd_like_probe_loss_rate_observed": optional_nonnegative_numeric(bfd_like_probe_loss_rate_observed),
        "bfd_like_modeled_probe_loss_probability_last": optional_nonnegative_numeric(bfd_like_modeled_probe_loss_probability_last),
        "bfd_like_modeled_probe_loss_probability_max": optional_nonnegative_numeric(bfd_like_modeled_probe_loss_probability_max),
        "bfd_like_modeled_probe_loss_probability_at_detection": optional_nonnegative_numeric(bfd_like_modeled_probe_loss_probability_at_detection),
        "bfd_like_trigger_reason_code": optional_numeric(bfd_like_trigger_reason_code),
        "bfd_like_trigger_reason_text": bfd_like_trigger_reason_from_code(bfd_like_trigger_reason_code),
        "bfd_like_protected_span_up_at_detection": (
            bool_flag(bfd_like_protected_span_up_at_detection > 0.5)
            if bfd_like_protected_span_up_at_detection is not None
            and bfd_like_protected_span_up_at_detection >= 0
            else ""
        ),
        "bfd_like_detection_before_hard_failure": (
            bool_flag(bfd_like_detection_before_failure)
            if bfd_like_detection_time_nonnegative_s is not None and hard_failure_time_s is not None
            else ""
        ),
        "bfd_like_lead_time_before_failure_s": optional_nonnegative_numeric(
            bfd_like_lead_time_before_failure_s
            if bfd_like_lead_time_before_failure_s is not None and float(bfd_like_lead_time_before_failure_s) >= 0
            else bfd_like_lead_time_computed_s
        ),
        "hard_failure_to_bfd_detection_time_s": optional_numeric(hard_failure_to_bfd_detection_computed_s),
        "hard_failure_time_configured_s": optional_numeric(hard_failure_time_scalar_s),
        "activation_risk_score": optional_numeric(activation_risk_score),
        "activation_decision_threshold": optional_numeric(activation_decision_threshold),
        "activation_positive_decision_streak": optional_numeric(activation_positive_decision_streak),
        "activation_queue_length_pk": optional_numeric(activation_queue_length_pk),
        "activation_queue_bit_length_b": optional_numeric(activation_queue_bit_length_b),
        "activation_probe_delay_mean_s": optional_numeric(activation_probe_delay_mean_s),
        "activation_probe_throughput_bps": optional_numeric(activation_probe_throughput_bps),
        "activation_probe_packet_count": optional_numeric(activation_probe_packet_count),
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
        "packet_sequence_gap_observed_after_reference": bool_flag(packet_continuity["packet_sequence_gap_observed_after_reference"]),
        "packet_sequence_gap_count_after_reference": optional_numeric(packet_continuity["packet_sequence_gap_count_after_reference"]),
        "packet_sequence_gap_total_missing_after_reference": optional_numeric(packet_continuity["packet_sequence_gap_total_missing_after_reference"]),
        "packet_sequence_gap_total_unobserved_after_reference": optional_numeric(packet_continuity["packet_sequence_gap_total_unobserved_after_reference"]),
        "packet_sequence_gap_total_reordered_after_reference": optional_numeric(packet_continuity["packet_sequence_gap_total_reordered_after_reference"]),
        "max_packet_sequence_gap_after_reference": optional_numeric(packet_continuity["max_packet_sequence_gap_after_reference"]),
        "max_packet_interarrival_gap_after_reference_s": optional_numeric(packet_continuity["max_packet_interarrival_gap_after_reference_s"]),
        "packet_interarrival_nominal_gap_threshold_s": optional_numeric(packet_continuity["packet_interarrival_nominal_gap_threshold_s"]),
        "packet_interarrival_gap_exceedance_count_after_reference": optional_numeric(packet_continuity["packet_interarrival_gap_exceedance_count_after_reference"]),
        "packet_interarrival_gap_exceeded_nominal_threshold": bool_flag(packet_continuity["packet_interarrival_gap_exceeded_nominal_threshold"]),
        "packet_sequence_out_of_order_event_count_after_reference": optional_numeric(packet_continuity["packet_sequence_out_of_order_event_count_after_reference"]),
        "packet_sequence_out_of_order_packet_count_after_reference": optional_numeric(packet_continuity["packet_sequence_out_of_order_packet_count_after_reference"]),
        "first_packet_after_reference_delay_s": optional_numeric(packet_continuity["first_packet_after_reference_delay_s"]),
        "tcp_service_interruption_observed": (
            bool_flag(tcp_service_interruption_start_time_s is not None)
            if profile.tcp_app_indices and tcp_reference_time_s is not None
            else ""
        ),
        "tcp_service_interruption_start_time_s": optional_numeric(tcp_service_interruption_start_time_s),
        "tcp_service_interruption_end_time_s": optional_numeric(tcp_service_interruption_end_time_s),
        "tcp_service_interruption_duration_s": optional_numeric(tcp_service_interruption_duration_s),
        "tcp_zero_goodput_window_count_after_reference": optional_numeric(tcp_zero_goodput_window_count_after_reference),
        "tcp_max_zero_goodput_window_streak_after_reference": optional_numeric(tcp_max_zero_goodput_window_streak_after_reference),
        "tcp_useful_goodput_restored_after_failure": bool_flag(tcp_useful_goodput_restored_after_failure),
        "tcp_endpoint_receive_event_count_after_reference": optional_numeric(tcp_endpoint_receive_gaps["tcp_endpoint_receive_event_count_after_reference"]),
        "tcp_first_endpoint_receive_delay_after_reference_s": optional_numeric(tcp_endpoint_receive_gaps["tcp_first_endpoint_receive_delay_after_reference_s"]),
        "tcp_max_endpoint_receive_gap_after_reference_s": optional_numeric(tcp_endpoint_receive_gaps["tcp_max_endpoint_receive_gap_after_reference_s"]),
        "unnecessary_protection": bool_flag(unnecessary_protection),
        "missed_protection": bool_flag(missed_protection),
    }
    add_packet_continuity_outcome_fields(run_outcome_fields, "after_hard_failure", packet_continuity_after_hard_failure)
    add_packet_continuity_outcome_fields(run_outcome_fields, "after_protection_activation", packet_continuity_after_protection_activation)
    add_packet_continuity_outcome_fields(
        run_outcome_fields,
        "between_activation_and_failure",
        packet_continuity_between_activation_and_failure,
    )
    add_packet_continuity_outcome_fields(run_outcome_fields, "after_critical_start", packet_continuity_after_critical_start)

    # Reporting diagnostics only: these ratios relate the observed transition
    # side effect to the queue state captured at activation. They intentionally
    # do not feed back into runtime decisions or thresholds.
    activation_queue_packets = (
        float(activation_queue_length_pk)
        if activation_queue_length_pk is not None and float(activation_queue_length_pk) > 0
        else None
    )
    run_outcome_fields["activation_to_failure_unobserved_per_activation_queue_packet"] = optional_numeric(
        ratio_or_none(
            packet_continuity_between_activation_and_failure["packet_sequence_gap_total_unobserved_after_reference"],
            activation_queue_packets,
        )
    )
    run_outcome_fields["activation_to_failure_reordered_per_activation_queue_packet"] = optional_numeric(
        ratio_or_none(
            packet_continuity_between_activation_and_failure["packet_sequence_gap_total_reordered_after_reference"],
            activation_queue_packets,
        )
    )

    for row in rows:
        row.update(run_outcome_fields)


def build_rows_for_run(run_data: dict, scenario: str, feature_set: str = "baseline") -> list[dict[str, object]]:
    metadata = run_data["metadata"]
    outcome_profile = get_outcome_profile(scenario, metadata["configname"])
    sim_time_limit = float(metadata["sim_time_limit"])
    num_windows = int(math.ceil(sim_time_limit / WINDOW_SIZE_SECONDS))
    receiver_apps = run_data["receiver_apps"]
    expected_packets_per_window, packet_progress_floor, throughput_floor_bps = availability_thresholds(outcome_profile)
    expected_throughput_bps = outcome_profile.packet_size_bits / outcome_profile.send_interval_s
    controller_series = {
        name: indexed_series(values)
        for name, values in run_data.get("controller", {}).items()
    }
    bottleneck_queue_series = {
        name: indexed_series(values)
        for name, values in run_data.get("bottleneck_queue", {}).items()
    }
    ai_mrce_series = {
        name: indexed_series(values)
        for name, values in run_data.get("ai_mrce", {}).items()
    }
    receiver_app_series = {
        app_index: {
            name: indexed_series(values)
            for name, values in metrics.items()
        }
        for app_index, metrics in receiver_apps.items()
    }

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
            "traffic_profile": outcome_profile.traffic_profile,
            "runtime_model_type": outcome_profile.runtime_model_type,
            "runtime_model_path": outcome_profile.runtime_model_path,
            "monitored_flow_app_index": outcome_profile.monitored_app_index,
            "monitored_flow_packet_size_bytes": outcome_profile.packet_size_bits / 8.0,
            "monitored_flow_send_interval_s": outcome_profile.send_interval_s,
            "monitored_flow_expected_packet_rate_pps": 1.0 / outcome_profile.send_interval_s,
            "monitored_flow_expected_packets_per_window": expected_packets_per_window,
            "monitored_flow_expected_throughput_bps": expected_throughput_bps,
            "service_availability_packet_progress_floor": packet_progress_floor,
            "service_availability_throughput_floor_bps": throughput_floor_bps,
            "tcp_receiver_app_indices": ";".join(str(app_index) for app_index in outcome_profile.tcp_app_indices),
            "tcp_useful_goodput_floor_bps": optional_numeric(outcome_profile.tcp_useful_goodput_floor_bps),
        }
        row.update(degradation_metadata_fields(scenario, metadata["configname"]))

        if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
            delay_summary = state_summary(controller_series["appliedDelay"], window_start, window_end)
            per_summary = state_summary(controller_series["appliedPacketErrorRate"], window_start, window_end)
            row.update({
                "controller_delay_mean_s": delay_summary["mean"],
                "controller_delay_max_s": delay_summary["max"],
                "controller_delay_last_s": delay_summary["last"],
                "controller_packet_error_rate_mean": per_summary["mean"],
                "controller_packet_error_rate_max": per_summary["max"],
                "controller_packet_error_rate_last": per_summary["last"],
            })

        if scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
            queue_length_summary = state_summary(bottleneck_queue_series["queueLength"], window_start, window_end)
            queue_bit_length_summary = state_summary(bottleneck_queue_series["queueBitLength"], window_start, window_end)
            queueing_time_summary = state_summary(bottleneck_queue_series["queueingTime"], window_start, window_end)
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

        if feature_set == "extended" and scenario in REGIONALBACKBONE_FAMILY_SCENARIOS:
            def ai_state(name: str) -> dict[str, float | str]:
                return state_summary(ai_mrce_series.get(name, []), window_start, window_end)

            observed_probe_delay = ai_state("observedProbeDelayMeanS")["last"]
            row.update({
                "feat_aimrce_observed_queue_length_last_pk": ai_state("observedQueueLengthPk")["last"],
                "feat_aimrce_observed_queue_bit_length_last_b": ai_state("observedQueueBitLengthB")["last"],
                "feat_aimrce_observed_probe_delay_mean_s": optional_nonnegative_numeric(parse_numeric_cell(observed_probe_delay)),
                "feat_aimrce_observed_probe_throughput_bps": ai_state("observedProbeThroughputBps")["last"],
                "feat_aimrce_observed_probe_packet_count": ai_state("observedProbePacketCount")["last"],
                "feat_aimrce_risk_score_last": ai_state("riskScore")["last"],
                "feat_aimrce_decision_positive_last": ai_state("decisionPositive")["last"],
                "feat_aimrce_positive_decision_streak_last": ai_state("positiveDecisionStreak")["last"],
                "feat_aimrce_protection_active_last": ai_state("protectionActive")["last"],
                "feat_aimrce_repair_routes_installed_last": ai_state("repairRoutesInstalled")["last"],
                "feat_aimrce_trigger_source_code_last": ai_state("protectionTriggerSourceCode")["last"],
                "feat_bfd_missed_probe_count_last": ai_state("bfdLikeMissedProbeCount")["last"],
                "feat_bfd_detection_active_last": ai_state("bfdLikeDetectionActive")["last"],
                "feat_bfd_protected_span_up_last": ai_state("bfdLikeProtectedSpanUp")["last"],
                "feat_bfd_modeled_loss_probability_mean": ai_state("bfdLikeModeledProbeLossProbability")["mean"],
                "feat_bfd_modeled_loss_probability_max": ai_state("bfdLikeModeledProbeLossProbability")["max"],
                "feat_bfd_modeled_loss_probability_last": ai_state("bfdLikeModeledProbeLossProbability")["last"],
                "feat_bfd_probe_missed_last": ai_state("bfdLikeProbeMissed")["last"],
            })

        total_packets = 0
        tcp_total_received_bytes = 0.0
        tcp_total_goodput_bps = 0.0
        tcp_active_app_count = 0
        for app_index in sorted(receiver_apps.keys()):
            metrics = receiver_app_series[app_index]
            seq = sequence_summary(metrics["rcvdPkSeqNo"], window_start, window_end)
            delay = sample_summary(metrics["endToEndDelay"], window_start, window_end)
            throughput = sample_summary(metrics["throughput"], window_start, window_end, nonnegative_only=True)
            packet_bytes = packet_bytes_summary(metrics["packetBytes"], window_start, window_end)
            packet_count = int(seq["count"]) if int(seq["count"]) > 0 else int(packet_bytes["count"])

            total_packets += packet_count
            row[f"receiver_app{app_index}_packet_count"] = packet_count
            row[f"receiver_app{app_index}_seq_progress"] = seq["progress"]
            row[f"receiver_app{app_index}_last_seq"] = seq["last"]
            row[f"receiver_app{app_index}_e2e_delay_mean_s"] = delay["mean"]
            row[f"receiver_app{app_index}_e2e_delay_max_s"] = delay["max"]
            row[f"receiver_app{app_index}_throughput_mean_bps"] = throughput["mean"]
            row[f"receiver_app{app_index}_throughput_last_bps"] = throughput["last"]
            row[f"receiver_app{app_index}_received_bytes"] = packet_bytes["bytes"]
            row[f"receiver_app{app_index}_goodput_mean_bps"] = packet_bytes["goodput_bps"]

            if app_index in outcome_profile.tcp_app_indices:
                received_bytes = parse_numeric_cell(packet_bytes["bytes"]) or 0.0
                goodput_bps = parse_numeric_cell(packet_bytes["goodput_bps"]) or 0.0
                tcp_total_received_bytes += received_bytes
                tcp_total_goodput_bps += goodput_bps
                if received_bytes > 0.0 or goodput_bps > 0.0:
                    tcp_active_app_count += 1

        row["receiver_total_packet_count"] = total_packets
        if outcome_profile.tcp_app_indices:
            row["receiver_tcp_total_received_bytes"] = tcp_total_received_bytes
            row["receiver_tcp_goodput_mean_bps"] = tcp_total_goodput_bps
            row["receiver_tcp_active_app_count"] = tcp_active_app_count
        else:
            row["receiver_tcp_total_received_bytes"] = ""
            row["receiver_tcp_goodput_mean_bps"] = ""
            row["receiver_tcp_active_app_count"] = ""

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

        if not outcome_profile.tcp_app_indices or outcome_profile.tcp_useful_goodput_floor_bps is None:
            row["tcp_service_available_operational"] = ""
            row["tcp_service_materially_degraded_operational"] = ""
        elif outcome_profile.tcp_flow_start_time_s is not None and window_start < outcome_profile.tcp_flow_start_time_s:
            row["tcp_service_available_operational"] = ""
            row["tcp_service_materially_degraded_operational"] = ""
        else:
            # TCP visibility is intentionally application-endpoint only: this
            # is a useful-goodput proxy for dissertation evaluation, not a
            # TCP-stack retransmission or congestion-control measurement.
            tcp_goodput_bps = parse_numeric_cell(row.get("receiver_tcp_goodput_mean_bps"))
            tcp_service_available = (
                tcp_goodput_bps is not None
                and tcp_goodput_bps >= outcome_profile.tcp_useful_goodput_floor_bps
            )
            row["tcp_service_available_operational"] = bool_flag(tcp_service_available)
            row["tcp_service_materially_degraded_operational"] = bool_flag(not tcp_service_available)

        rows.append(row)

    annotate_run_outcome_metrics(rows, run_data, scenario)
    return rows


def add_extended_telemetry_features(rows: list[dict[str, object]], scenario: str) -> None:
    grouped: dict[tuple[str, int], list[dict[str, object]]] = {}
    for row in rows:
        config_name = str(row.get("config_name", ""))
        run_number = parse_int_cell(row.get("run_number"))
        if not config_name or run_number is None:
            continue
        grouped.setdefault((config_name, run_number), []).append(row)

    for (config_name, run_number), run_rows in grouped.items():
        run_rows.sort(key=lambda item: parse_numeric_cell(item.get("window_start_s")) or 0.0)
        previous: dict[str, object] | None = None
        for row in run_rows:
            window_start = parse_numeric_cell(row.get("window_start_s"))
            previous_window_start = parse_numeric_cell(previous.get("window_start_s")) if previous else None
            time_delta = (
                window_start - previous_window_start
                if window_start is not None and previous_window_start is not None
                else None
            )

            delay_mean = parse_numeric_cell(row.get("receiver_app0_e2e_delay_mean_s"))
            previous_delay_mean = parse_numeric_cell(previous.get("receiver_app0_e2e_delay_mean_s")) if previous else None
            delay_delta = delta_or_none(delay_mean, previous_delay_mean)

            throughput_mean = parse_numeric_cell(row.get("receiver_app0_throughput_mean_bps"))
            previous_throughput_mean = parse_numeric_cell(previous.get("receiver_app0_throughput_mean_bps")) if previous else None
            throughput_delta = delta_or_none(throughput_mean, previous_throughput_mean)
            expected_throughput = parse_numeric_cell(row.get("monitored_flow_expected_throughput_bps"))

            queue_length = parse_numeric_cell(row.get("bottleneck_queue_length_mean_pk"))
            previous_queue_length = parse_numeric_cell(previous.get("bottleneck_queue_length_mean_pk")) if previous else None
            queue_delta = delta_or_none(queue_length, previous_queue_length)

            queueing_time = parse_numeric_cell(row.get("bottleneck_queueing_time_mean_s"))
            previous_queueing_time = parse_numeric_cell(previous.get("bottleneck_queueing_time_mean_s")) if previous else None
            queueing_time_delta = delta_or_none(queueing_time, previous_queueing_time)

            packet_count = parse_numeric_cell(row.get("receiver_app0_packet_count"))
            seq_progress = parse_numeric_cell(row.get("receiver_app0_seq_progress"))
            expected_packets = parse_numeric_cell(row.get("monitored_flow_expected_packets_per_window"))
            window_unobserved_proxy = (
                max(0.0, expected_packets - packet_count)
                if expected_packets is not None and packet_count is not None
                else None
            )
            hard_failure_time = parse_numeric_cell(row.get("hard_failure_time_s"))

            row.update({
                "id_scenario": scenario,
                "id_config_name": config_name,
                "id_run_number": run_number,
                "id_window_start_s": optional_numeric(window_start),
                "id_window_end_s": row.get("window_end_s", ""),
                "meta_feature_set": "extended",
                "meta_telemetry_version": EXTENDED_TELEMETRY_VERSION,
                "meta_source_provenance": "existing_omnetpp_vectors_and_controller_scalars",
                "meta_mechanism_family": row.get("protection_mode", ""),
                "meta_runtime_model_type": row.get("runtime_model_type", ""),
                "phase_context": extended_phase_context(row),
                "phase_impairment_state": extended_impairment_state(row),
                "label_time_to_hard_failure_s": optional_numeric(
                    hard_failure_time - window_start if hard_failure_time is not None and window_start is not None else None
                ),
                "label_post_hard_failure": bool_flag(
                    hard_failure_time is not None and window_start is not None and window_start >= hard_failure_time
                ),
                "label_within_activation_to_failure": bool_flag(extended_phase_context(row) == "activation_to_failure"),
                "label_protection_active_at_window": row.get("feat_aimrce_protection_active_last", ""),
                "label_post_failure_unobserved": row.get("packet_sequence_gap_total_unobserved_after_hard_failure", ""),
                "label_activation_to_failure_unobserved": row.get(
                    "packet_sequence_gap_total_unobserved_between_activation_and_failure", ""
                ),
                "label_activation_to_failure_reordered": row.get(
                    "packet_sequence_gap_total_reordered_between_activation_and_failure", ""
                ),
                "feat_delay_mean_s": optional_numeric(delay_mean),
                "feat_delay_max_s": row.get("receiver_app0_e2e_delay_max_s", ""),
                "feat_delay_delta_from_previous_window_s": optional_numeric(delay_delta),
                "feat_delay_abs_delta_from_previous_window_s": optional_numeric(
                    abs(delay_delta) if delay_delta is not None else None
                ),
                "feat_delay_short_slope_s_per_s": optional_numeric(rate_or_none(delay_delta, time_delta)),
                "feat_throughput_mean_bps": optional_numeric(throughput_mean),
                "feat_throughput_last_bps": row.get("receiver_app0_throughput_last_bps", ""),
                "feat_throughput_delta_from_previous_window_bps": optional_numeric(throughput_delta),
                "feat_throughput_ratio_to_expected": optional_numeric(ratio_or_none(throughput_mean, expected_throughput)),
                "feat_throughput_drop_ratio_from_expected": optional_numeric(
                    ratio_or_none(
                        max(0.0, expected_throughput - throughput_mean)
                        if expected_throughput is not None and throughput_mean is not None
                        else None,
                        expected_throughput,
                    )
                ),
                "feat_goodput_mean_bps": row.get("receiver_app0_goodput_mean_bps", ""),
                "feat_received_bytes": row.get("receiver_app0_received_bytes", ""),
                "feat_queue_length_mean_pk": optional_numeric(queue_length),
                "feat_queue_length_max_pk": row.get("bottleneck_queue_length_max_pk", ""),
                "feat_queue_length_last_pk": row.get("bottleneck_queue_length_last_pk", ""),
                "feat_queue_length_delta_from_previous_window_pk": optional_numeric(queue_delta),
                "feat_queue_length_growth_rate_pk_per_s": optional_numeric(rate_or_none(queue_delta, time_delta)),
                "feat_queue_bit_length_mean_b": row.get("bottleneck_queue_bit_length_mean_b", ""),
                "feat_queue_bit_length_max_b": row.get("bottleneck_queue_bit_length_max_b", ""),
                "feat_queue_bit_length_last_b": row.get("bottleneck_queue_bit_length_last_b", ""),
                "feat_queueing_time_mean_s": optional_numeric(queueing_time),
                "feat_queueing_time_max_s": row.get("bottleneck_queueing_time_max_s", ""),
                "feat_queueing_time_last_s": row.get("bottleneck_queueing_time_last_s", ""),
                "feat_queueing_time_delta_from_previous_window_s": optional_numeric(queueing_time_delta),
                "feat_queueing_time_slope_s_per_s": optional_numeric(rate_or_none(queueing_time_delta, time_delta)),
                "feat_continuity_packet_count": optional_numeric(packet_count),
                "feat_continuity_seq_progress": optional_numeric(seq_progress),
                "feat_continuity_expected_packets": optional_numeric(expected_packets),
                "feat_continuity_packet_count_ratio_proxy": optional_numeric(ratio_or_none(packet_count, expected_packets)),
                "feat_continuity_seq_progress_ratio_proxy": optional_numeric(ratio_or_none(seq_progress, expected_packets)),
                "feat_continuity_window_unobserved_proxy": optional_numeric(window_unobserved_proxy),
                "feat_continuity_window_unobserved_ratio_proxy": optional_numeric(
                    ratio_or_none(window_unobserved_proxy, expected_packets)
                ),
                "feat_impairment_delay_mean_s": row.get("controller_delay_mean_s", ""),
                "feat_impairment_delay_max_s": row.get("controller_delay_max_s", ""),
                "feat_impairment_delay_last_s": row.get("controller_delay_last_s", ""),
                "feat_impairment_packet_error_rate_mean": row.get("controller_packet_error_rate_mean", ""),
                "feat_impairment_packet_error_rate_max": row.get("controller_packet_error_rate_max", ""),
                "feat_impairment_packet_error_rate_last": row.get("controller_packet_error_rate_last", ""),
            })
            previous = row


def classify_extended_column(column: str) -> tuple[str, str, str, str]:
    if column.startswith("id_"):
        return ("identifier", "metadata", "dataset identity", "not a runtime feature")
    if column.startswith("meta_"):
        return ("metadata", "metadata", "dataset/model context", "not a runtime feature")
    if column.startswith("degradation_"):
        return ("degradation_profile_context", "metadata", "scenario/config profile metadata", "not a runtime feature")
    if column.startswith("label_"):
        return ("label_target", "label/target", "derived from scripted timing or run outcome", "leakage-risk field")
    if column.startswith("phase_"):
        return ("phase_context", "offline diagnostic", "derived from impairment/activation/failure timing", "leakage-risk field")
    if column.startswith("feat_delay_"):
        return ("delay", "runtime-safe candidate feature", "hostB.app[0] endToEndDelay vector", "current/previous telemetry only")
    if column.startswith("feat_throughput_") or column.startswith("feat_goodput_") or column == "feat_received_bytes":
        return ("throughput_goodput", "runtime-safe candidate feature", "hostB.app[0] throughput/packetReceived vectors", "current/previous telemetry only")
    if column.startswith("feat_queue_") or column.startswith("feat_queueing_"):
        return ("queue", "runtime-safe candidate feature", "coreNW.eth[1].queue vectors", "current/previous telemetry only")
    if column.startswith("feat_continuity_"):
        return ("continuity", "runtime-safe candidate feature", "hostB.app[0] rcvdPkSeqNo vector plus configured send rate", "receiver-observed proxy")
    if column.startswith("feat_impairment_"):
        return ("impairment", "offline diagnostic feature", "LinkDegradationController appliedDelay/appliedPacketErrorRate vectors", "simulator impairment context; not deployment telemetry")
    if column.startswith("feat_bfd_"):
        return ("bfd_like", "offline diagnostic feature", "AiMrceController BFD-like diagnostic vectors", "detector-state diagnostic")
    if column.startswith("feat_aimrce_"):
        return ("aimrce_controller", "offline diagnostic feature", "AiMrceController telemetry/decision vectors", "policy-state diagnostic, not raw input telemetry")
    return ("unknown", "offline diagnostic feature", "unclassified generated field", "review before ML use")


def extended_columns(rows: list[dict[str, object]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column.startswith(("id_", "meta_", "degradation_", "phase_", "feat_", "label_")) and column not in columns:
                columns.append(column)
    return columns


def write_extended_feature_classification(rows: list[dict[str, object]], path: Path, scenario: str) -> None:
    columns = extended_columns(rows)
    classification_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    lines = [
        "Telemetry v2 Extended Feature Classification",
        "============================================",
        "",
        f"scenario: {scenario}",
        f"extended_columns: {len(columns)}",
        "",
        "Leakage-prevention rules:",
        "- hardFailureTime-derived values are label/target context, not runtime inputs.",
        "- time-to-hard-failure fields are labels/targets and must not be used as runtime features.",
        "- post-failure and activation outcome fields are labels/diagnostics, not pre-activation inputs.",
        "- trigger source, mechanism family, config, run, and window identifiers are metadata.",
        "- configured impairment fields are simulator diagnostics unless a real deployment equivalent is defined.",
        "- AI-MRCE and BFD-like decision-state fields are diagnostics unless a future model explicitly targets controller-state stacking.",
        "",
        "Columns:",
    ]
    for column in columns:
        group, classification, provenance, note = classify_extended_column(column)
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
        group_counts[group] = group_counts.get(group, 0) + 1
        lines.append(
            f"- {column}: group={group}; classification={classification}; "
            f"provenance={provenance}; note={note}"
        )

    lines.extend(["", "Classification counts:"])
    for classification, count in sorted(classification_counts.items()):
        lines.append(f"- {classification}: {count}")
    lines.extend(["", "Feature group counts:"])
    for group, count in sorted(group_counts.items()):
        lines.append(f"- {group}: {count}")
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def collect_rows(
    results_dir: Path,
    scenario: str,
    supported_configs: set[str],
    config_aliases: dict[str, str],
    default_sim_time_limit: float,
    default_sim_time_limits_by_config: dict[str, float] | None,
    feature_set: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    vec_paths = sorted(results_dir.glob("*.vec"))
    if not vec_paths:
        return rows

    total_start = time.perf_counter()
    print(f"[build_dataset] Found {len(vec_paths)} .vec file(s) in {results_dir}")
    for index, vec_path in enumerate(vec_paths, start=1):
        sca_path = vec_path.with_suffix(".sca")
        run_start = time.perf_counter()
        print(
            f"[build_dataset] ({index}/{len(vec_paths)}) parsing vec={vec_path} "
            f"size={file_size_text(vec_path)} sca={sca_path if sca_path.exists() else 'missing'}"
        )
        run_data = parse_vec_file(
            vec_path,
            scenario,
            supported_configs,
            config_aliases,
            default_sim_time_limit,
            default_sim_time_limits_by_config,
            feature_set,
        )
        if run_data is None:
            print(f"[build_dataset] ({index}/{len(vec_paths)}) skipped unsupported config in {vec_path.name}")
            continue
        parse_elapsed = elapsed_text(run_start)
        diagnostics = run_data.get("diagnostics", {})
        row_start = time.perf_counter()
        run_rows = build_rows_for_run(run_data, scenario, feature_set)
        rows.extend(run_rows)
        print(
            f"[build_dataset] ({index}/{len(vec_paths)}) config={run_data['metadata']['configname']} "
            f"run={run_data['metadata']['runnumber']} rows={len(run_rows)} "
            f"vectors={diagnostics.get('targeted_vector_count', 'n/a')} "
            f"samples={diagnostics.get('targeted_sample_count', 'n/a')} "
            f"parse={parse_elapsed} scalar={diagnostics.get('scalar_parse_time_s', 0.0):.2f}s "
            f"row_build={elapsed_text(row_start)} total={elapsed_text(run_start)}"
        )
    print(f"[build_dataset] Collected {len(rows)} row(s) in {elapsed_text(total_start)}")
    return rows


def write_dataset(rows: list[dict[str, object]], output_file: Path) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    atomic_write_csv(output_file, rows, fieldnames)


def main() -> None:
    args = parse_args()
    preset = get_scenario_preset(args.scenario)

    results_dir = resolve_project_path(args.input) if args.input is not None else preset["results_dir"]
    output_file = resolve_project_path(args.output) if args.output is not None else preset["output_file"]
    output_file = feature_set_output_file(output_file, args.feature_set, explicit_output=args.output is not None)
    supported_configs = effective_supported_configs(preset, args.include_runtime_protection_configs)
    config_aliases = preset["config_aliases"]
    default_sim_time_limit = preset["default_sim_time_limit"]
    default_sim_time_limits_by_config = preset.get("default_sim_time_limits_by_config")

    if not results_dir.exists():
        raise SystemExit(f"Results directory not found: {results_dir}")

    vec_paths = sorted(results_dir.glob("*.vec"))
    discovered_runs = sorted(
        {
            int(match.group(1))
            for path in vec_paths
            for match in [re.search(r"-(\d+)$", path.stem)]
            if match
        }
    )
    discovered_configs = sorted({path.stem.rsplit("-", 1)[0] for path in vec_paths if "-" in path.stem})
    print(f"[build_dataset] Scenario: {args.scenario}")
    print(f"[build_dataset] Results directory: {results_dir}")
    print(f"[build_dataset] Output dataset: {output_file}")
    print(f"[build_dataset] Discovered configs: {len(discovered_configs)}")
    print(f"[build_dataset] Discovered runs from filenames: {', '.join(map(str, discovered_runs)) or 'none'}")
    warn_if_existing_output_stale(
        output_file,
        [path for vec_path in vec_paths for path in (vec_path, vec_path.with_suffix(".sca"), vec_path.with_suffix(".vci"))],
        f"py -3 analysis\\build_dataset.py --scenario {args.scenario} --feature-set {args.feature_set}",
    )

    total_start = time.perf_counter()
    rows = collect_rows(
        results_dir,
        args.scenario,
        supported_configs,
        config_aliases,
        default_sim_time_limit,
        default_sim_time_limits_by_config,
        args.feature_set,
    )
    if not rows:
        raise SystemExit(f"No supported {args.scenario} .vec files were found in {results_dir}.")

    if args.feature_set == "extended":
        add_extended_telemetry_features(rows, args.scenario)
        classification_path = extended_feature_classification_path(args.scenario)
        write_extended_feature_classification(rows, classification_path, args.scenario)
        print(f"[build_dataset] Wrote extended feature classification to {classification_path}")

    write_dataset(rows, output_file)
    print(f"[build_dataset] Wrote {len(rows)} dataset rows to {output_file}")
    print(f"[build_dataset] Total elapsed: {elapsed_text(total_start)}")


if __name__ == "__main__":
    main()
