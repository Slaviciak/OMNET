# Dissertation Workflow

This document describes the consolidated OMNeT++ / INET workflow for the dissertation topic **Intelligent Fast Network Recovery**.

The project is now organized around one dissertation spine: validate a project-local AI-MRCE prototype that uses monitored telemetry and offline-trained, auditable runtime models to trigger an early protective reroute action in a regional IP/OSPF-like topology. Historical small-topology scenarios remain available for reference, but they are no longer default workflow targets.

For the scenario classification, see `analysis/EXPERIMENT_ARCHITECTURE.md`.

## Scientific Scope

- The simulation validates a conservative AI-assisted protection concept, not a production FRR implementation.
- INET and OSPF internals are treated as external behavior and are not modified by the project.
- AI-MRCE runtime candidates use observable telemetry, scenario-phase supervision, and simple deployment artifacts.
- Standards-compliant FRR and BFD mechanisms are discussed through literature and technical comparison. The simulator includes only a clearly named project-local FRR-like repair-route actuator and, in one separate cohort, a BFD-inspired protected-span detector abstraction.
- The regional OSPF baseline uses INET OSPFv2 defaults unless explicitly stated. In INET 4.5 this means hello interval 10s and router dead interval 40s, applied consistently through `ASConfig.xml`; these defaults are kept as a normal OSPF reference rather than tuned to favor or weaken any candidate.
- The project does not claim universal failure prediction. It studies selected degradation and congestion classes where observable pre-failure symptoms may exist.
- Outcome metrics are operational simulator-side definitions, not RFC-standard restoration measurements.

## Active Dissertation Core

### Main Topology

- `simulations/regionalbackbone`
- Main configs:
  - `RegionalBackboneBaseline`
  - `RegionalBackboneReactiveFailure`
  - `RegionalBackboneControlledDegradation`
  - `RegionalBackboneCongestionDegradation`
- Runtime AI-MRCE configs:
  - `RegionalBackboneAiMrceRuleBased`
  - `RegionalBackboneAiMrceLogReg`
  - `RegionalBackboneAiMrceLinearSvm`
  - `RegionalBackboneAiMrceShallowTree`
- Multi-run congestion protection cohort wrappers:
  - `RegionalBackboneCongestionDegradationCohort`
  - `RegionalBackboneAiMrceRuleBasedCohort`
  - `RegionalBackboneAiMrceLogRegCohort`
  - `RegionalBackboneAiMrceLinearSvmCohort`
  - `RegionalBackboneAiMrceShallowTreeCohort`
- Focused mixed UDP/TCP protection cohort wrappers:
  - `RegionalBackboneMixedTrafficCongestionDegradationCohort`
  - `RegionalBackboneAiMrceRuleBasedMixedTrafficCohort`
  - `RegionalBackboneAiMrceLogRegMixedTrafficCohort`
- Focused failure-detection comparison wrappers:
  - `RegionalBackboneFailureComparisonOspfOnlyCohort`
  - `RegionalBackboneFailureComparisonBfdLikeFrrCohort`
  - `RegionalBackboneFailureComparisonAiMrceFrrCohort`
  - `RegionalBackboneFailureComparisonHybridCohort`
- Higher-resolution monitored-traffic failure-detection wrappers:
  - `RegionalBackboneFailureComparisonOspfOnlyMsTrafficCohort`
  - `RegionalBackboneFailureComparisonBfdLikeFrrMsTrafficCohort`
  - `RegionalBackboneFailureComparisonAiMrceFrrMsTrafficCohort`
  - `RegionalBackboneFailureComparisonHybridMsTrafficCohort`
- Degraded-link failure-detection wrappers:
  - `RegionalBackboneFailureComparisonOspfOnlyDegradedLinkCohort`
  - `RegionalBackboneFailureComparisonBfdLikeFrrDegradedLinkCohort`
  - `RegionalBackboneFailureComparisonAiMrceFrrDegradedLinkCohort`
  - `RegionalBackboneFailureComparisonHybridDegradedLinkCohort`

### Active Controllers

- `src/dissertationsim/controller/LinkDegradationController.*`
  - Applies controlled, project-local channel impairment proxies.
  - The staged profile approximates intermittent brownout-style deterioration using delay variation and packet loss.
- `src/dissertationsim/controller/AiMrceController.*`
  - Runs the current AI-MRCE runtime prototype family.
  - Uses sustained positive decisions before activating a project-local FRR-like static repair-route abstraction in the regional dissertation configs.
  - Can optionally run a BFD-inspired protected-span detector in the separate failure-detection comparison cohort. In degraded-link variants, logical BFD-like probe checks can be exposed to the current channel packet-error-rate impairment. This is a reactive safety-net trigger abstraction, not full RFC BFD.
  - The older administrative-withdrawal action remains available as an explicit reference/debug mode, but it is no longer the intended active AI-MRCE protection abstraction.
- `src/dissertationsim/controller/InterfaceWithdrawController.*`
  - Retained as a reusable deterministic administrative-withdrawal helper.

## Auxiliary And Archival Components

- `simulations/linkdegradation`
  - Auxiliary controlled synthetic data-generation branch.
  - Useful for sanity checks and optional cross-topology training evidence.
- `simulations/congestiondegradation`
  - Auxiliary traffic-driven data-generation branch.
  - Useful for sanity checks and optional cross-topology training evidence.
- `simulations/dualpathbaseline`
  - Archival minimal OSPF sanity reference.
- `simulations/reactivefailure`
  - Archival small-topology reactive reference.
- `simulations/proactiveswitch`
  - Archival small-topology deterministic proactive prototype.
- `simulations/simpletest`
  - External/reference INET material only, not part of dissertation batches.

These components should not be expanded as first-class dissertation result branches unless there is a specific methodological reason.

## Output Layout

Generated analysis artifacts are written under `analysis/output/`:

- `analysis/output/datasets/`
  - Dataset CSV files generated by `build-dataset`.
- `analysis/output/reports/`
  - Human-readable dataset and sanity reports.
- `analysis/output/outcomes/`
  - Run-level outcome summaries and practical comparison reports/CSVs.
- `analysis/output/training/`
  - Offline risk-model evaluation artifacts.
- `analysis/output/debug/`
  - Verbose helper CSVs such as missing-value and per-config summaries.
- `analysis/output/audit/`
  - Optional generated snapshots or audit artifacts.
- `analysis/output/experiment_logs/`
  - Batch execution logs from `run_experiments.bat`.

Generated outputs remain excluded from git.

## Python Environment

From the project root:

```powershell
run_analysis.bat setup-env
run_analysis.bat install-ml-deps
```

The wrapper prefers `analysis/sklearn-env` and falls back to `py -3` only when the local environment does not exist.

## Build

Build the local dissertation project binary from the project root through the experiment orchestrator, or directly from the OMNeT++ build environment. Rebuild whenever C++ source, NED definitions, or build metadata changes.

Do not modify INET or OSPF internals for the current dissertation prototype.

## Main Dataset Pipeline

Run the regional backbone dataset batch:

```powershell
run_experiments.bat dataset-batch --scenario regionalbackbone --clean --yes
```

Generate or refresh the regional dataset/report from existing results:

```powershell
run_analysis.bat build-dataset --scenario regionalbackbone
run_analysis.bat dataset-report --scenario regionalbackbone
```

For regional outcome analysis that includes runtime AI-MRCE rows from the standard eval directory:

```powershell
run_analysis.bat build-dataset --scenario regionalbackbone --include-runtime-protection-configs
run_analysis.bat dataset-report --scenario regionalbackbone
```

Auxiliary datasets can still be generated explicitly:

```powershell
run_analysis.bat build-dataset --scenario linkdegradation
run_analysis.bat dataset-report --scenario linkdegradation
run_analysis.bat build-dataset --scenario congestiondegradation
run_analysis.bat dataset-report --scenario congestiondegradation
```

Small standalone reactive/proactive datasets are archival support only and should not be used as default dissertation evidence.

## Offline Training

The default offline training path now uses the regional backbone dataset:

```powershell
run_analysis.bat train-risk-model
```

Training artifacts are written to `analysis/output/training/`.

Optional broader training using auxiliary small-topology datasets remains available:

```powershell
run_analysis.bat train-risk-model --scenarios linkdegradation congestiondegradation regionalbackbone --evaluations baseline_random grouped_run_holdout leave_one_config_out topology_transfer_small_to_regional topology_transfer_regional_to_small
```

Training remains offline methodological analysis. Runtime protection rows are still excluded from classifier training, even when they appear in outcome-oriented regional datasets.

## Runtime Model Export

Export the current runtime AI-MRCE model family:

```powershell
run_analysis.bat export-runtime-models --configs RegionalBackboneCongestionDegradation
```

This writes deployment artifacts under `simulations/regionalbackbone/`:

- `aimrce_runtime_logreg.csv`
- `aimrce_runtime_linsvm.csv`
- `aimrce_runtime_shallow_tree.csv`
- `aimrce_runtime_manifest.csv`

The older logistic-only wrapper is retained for compatibility:

```powershell
run_analysis.bat export-runtime-logreg --configs RegionalBackboneCongestionDegradation
```

Exported models are deployment artifacts, not substitutes for offline evaluation.

## Runtime AI-MRCE Cohort

Run the main multi-run regional congestion protection cohort:

```powershell
run_experiments.bat regional-congestion-protection-batch --clean --yes
```

For a smaller smoke test:

```powershell
run_experiments.bat regional-congestion-protection-batch --runs 0 1 --clean --yes --skip-build
```

This command runs the reactive congestion baseline and all current AI-MRCE runtime candidates, then builds:

- `analysis/output/datasets/regionalbackbone_congestion_protection_multirun_dataset.csv`
- `analysis/output/reports/regionalbackbone_congestion_protection_multirun_report.txt`
- `analysis/output/outcomes/regionalbackbone_congestion_protection_multirun_outcome_summary.csv`
- `analysis/output/outcomes/regionalbackbone_congestion_protection_multirun_comparison_report.txt`

The cohort comparison is descriptive. It reports run counts, pre-failure activation, lead time, interruption occurrence/duration, recovery time, packet-continuity gaps, and throughput restoration under the project's operational definitions.

The packet-continuity fields are intentionally separate from the coarse one-second service-interruption fields. They use receiver-observed UDP sequence-number jumps and receive-timestamp gaps to expose short delivery disruptions that can be real service impact even when every one-second window still contains enough packets to be marked available. Use `packet_sequence_gap_total_unobserved_after_hard_failure` as the headline loss-like post-failure comparison, and use `packet_sequence_gap_total_reordered_between_activation_and_failure` plus out-of-order event counts for the pre-failure repair-route switch side effect. The optional `activation_to_failure_*_per_activation_queue_packet` ratios are descriptive diagnostics that relate transition effects to the observed queue at activation; they are not controller thresholds.

## Failure-Detection Comparison Cohort

Run the focused regional OSPF/BFD-like/AI-MRCE/hybrid comparison cohort:

```powershell
run_experiments.bat regional-failure-detection-comparison-batch --clean --yes
```

For a smoke test:

```powershell
run_experiments.bat regional-failure-detection-comparison-batch --runs 0 --skip-build --skip-runtime-export
```

This command runs four trigger families over the same regional congestion/failure branch and writes separate artifacts:

- `analysis/output/datasets/regionalbackbone_failure_detection_comparison_dataset.csv`
- `analysis/output/reports/regionalbackbone_failure_detection_comparison_report.txt`
- `analysis/output/outcomes/regionalbackbone_failure_detection_comparison_outcome_summary.csv`
- `analysis/output/outcomes/regionalbackbone_failure_detection_comparison_report.txt`

Mechanism buckets are explicit: `ospf_only`, `bfd_like_frr`, `aimrce_frr`, and `hybrid_bfd_like_aimrce_frr`. The BFD-like detector observes the protected-span interface/carrier state and keeps configurable missed probe-reception intervals as a fallback diagnostic; after a detect-multiplier-style condition it activates the same project-local repair routes. The active evaluation profile uses `bfdLikeDetectionInterval = 300ms` and `bfdLikeDetectMultiplier = 3`, so the configured expected detection time is about 0.9s after the protected span is observed unhealthy. The default congestion-only branch does not expose BFD-like checks to a separate pre-failure packet-error-rate impairment, so it may still resemble OSPF-only until the protected span is down. The hybrid config records whether AI-MRCE or the BFD-like detector triggered first. Do not describe this branch as standards-compliant BFD, LFA, TI-LFA, or integrated OSPF/BFD behavior.

For manual demonstration, use `RegionalBackboneFailureComparisonHybridDebug` in Qtenv or Cmdenv. It enables eventlog recording plus controlled AI-MRCE telemetry, decision, repair-route, and BFD-like detector EV logs; evaluation configs keep these logs disabled to avoid noisy batch output.

### Higher-Resolution Failure-Detection Traffic

The default failure-detection comparison already uses a `256B` monitored UDP probe every `10ms`, plus staged `1200B` UDP load every `4ms` on the bulk flows. That is adequate for many packet-continuity diagnostics, but a 0.9s BFD-like detection profile can be easier to interpret with a finer monitored-packet cadence. The separate ms-traffic cohort therefore changes only the monitored probe to `2ms` while keeping the same topology, staged bulk traffic, hard failure time, BFD-like timing, AI-MRCE decisions, and repair-route actuator.

Run it with:

```powershell
run_experiments.bat regional-failure-detection-ms-traffic-batch --clean --yes
```

For a smoke test:

```powershell
run_experiments.bat regional-failure-detection-ms-traffic-batch --runs 0 --skip-build --skip-runtime-export
```

Generated artifacts are kept separate:

- `analysis/output/datasets/regionalbackbone_failure_detection_comparison_ms_traffic_dataset.csv`
- `analysis/output/reports/regionalbackbone_failure_detection_comparison_ms_traffic_report.txt`
- `analysis/output/outcomes/regionalbackbone_failure_detection_comparison_ms_traffic_outcome_summary.csv`
- `analysis/output/outcomes/regionalbackbone_failure_detection_comparison_ms_traffic_report.txt`

This is a measurement-resolution sensitivity cohort, not a new mechanism. It should be used to check whether fast reactive repair becomes more visible under millisecond-level active traffic. It must not be used to hide AI-MRCE reordering or to claim standards-compliant BFD/FRR behavior.

### Degraded-Link BFD-Like Failure Detection

The degraded-link comparison adds deterministic progressive packet-loss brownout on the protected `coreNW`-`coreNE` span before the same hard failure at `125s`. It keeps the same trigger families and repair-route actuator, but enables `bfdLikeUseModeledProbeLoss` for BFD-like and hybrid configs so logical BFD-like checks are exposed to the current channel packet error rate. This is intended to make the reactive BFD-like safety net scientifically credible in scenarios where the link is visibly losing packets before carrier-down; it is not a prediction mechanism and not RFC BFD.

Run it with:

```powershell
run_experiments.bat regional-failure-detection-degraded-link-batch --clean --yes
```

For a smoke test:

```powershell
run_experiments.bat regional-failure-detection-degraded-link-batch --runs 0 --skip-build --skip-runtime-export
```

Generated artifacts are kept separate:

- `analysis/output/datasets/regionalbackbone_failure_detection_degraded_link_dataset.csv`
- `analysis/output/reports/regionalbackbone_failure_detection_degraded_link_report.txt`
- `analysis/output/outcomes/regionalbackbone_failure_detection_degraded_link_outcome_summary.csv`
- `analysis/output/outcomes/regionalbackbone_failure_detection_degraded_link_report.txt`

## Mixed UDP/TCP Protection Cohort

Run the focused regional mixed-traffic cohort:

```powershell
run_experiments.bat regional-mixed-traffic-protection-batch --clean --yes
```

For a small smoke test:

```powershell
run_experiments.bat regional-mixed-traffic-protection-batch --runs 0 --skip-build --skip-runtime-export
```

This branch keeps the existing UDP probe and staged UDP pressure but adds standard INET `TcpBasicClientApp` / `TcpGenericServerApp` request-response sessions. The larger TCP request direction follows hostA -> hostB so it exercises the same protected forward corridor monitored by AI-MRCE; smaller replies keep the bidirectional TCP session measurable without moving the main congestion signal onto the unmonitored reverse queue. It is intentionally limited to the reactive congestion baseline, rule-based AI-MRCE, and logistic-regression AI-MRCE to avoid a combinatorial expansion of weak configs.

The generated mixed-cohort artifacts are:

- `analysis/output/datasets/regionalbackbone_mixed_traffic_protection_multirun_dataset.csv`
- `analysis/output/reports/regionalbackbone_mixed_traffic_protection_multirun_report.txt`
- `analysis/output/outcomes/regionalbackbone_mixed_traffic_protection_multirun_outcome_summary.csv`
- `analysis/output/outcomes/regionalbackbone_mixed_traffic_protection_multirun_comparison_report.txt`

TCP-specific outcome fields are application-endpoint useful-goodput proxies derived from application packet-byte vectors. They are suitable for descriptive transport-impact comparison inside this project, but they are not protocol-internal TCP retransmission or recovery counters.

Mixed-cohort reports also include endpoint receive-gap diagnostics derived from TCP application packet-byte timestamps. These are useful-goodput continuity proxies only; they should not be reported as TCP-stack recovery or retransmission measurements.

The logistic-regression mixed config currently reuses the UDP-dominant regional runtime export (`aimrce_runtime_logreg.csv`). Treat this as a conservative deployment-compatibility check: if it misses protection under mixed UDP/TCP traffic, report that as an out-of-distribution result rather than lowering thresholds or changing labels.

## Practical Outcome Comparison

Default regional outcome comparison:

```powershell
run_analysis.bat compare-outcomes --allow-missing
```

Focused multi-run cohort comparison:

```powershell
run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_congestion_protection_multirun_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_congestion_protection_multirun_comparison
```

Focused mixed UDP/TCP cohort comparison:

```powershell
run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_mixed_traffic_protection_multirun_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_mixed_traffic_protection_multirun_comparison
```

Focused failure-detection comparison:

```powershell
run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_failure_detection_comparison_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_comparison
```

Focused 2 ms monitored-traffic failure-detection comparison:

```powershell
run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_failure_detection_comparison_ms_traffic_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_comparison_ms_traffic
```

Do not mix unlike cohorts unless the report explicitly separates them.

## Batch Orchestrator

Useful commands:

```powershell
run_experiments.bat help
run_experiments.bat dataset-batch --scenario regionalbackbone --dry-run
run_experiments.bat dataset-batch --scenario regionalbackbone --clean --yes
run_experiments.bat training-batch --stronger-evaluations-only
run_experiments.bat aimrce-batch --skip-runtime-export --dry-run
run_experiments.bat regional-congestion-protection-batch --dry-run
run_experiments.bat regional-mixed-traffic-protection-batch --runs 0 --skip-build --skip-runtime-export --dry-run
run_experiments.bat regional-failure-detection-ms-traffic-batch --runs 0 --skip-build --skip-runtime-export --dry-run
run_experiments.bat full-pipeline --clean --yes --include-aimrce
```

`--clean` still requires `--yes` for actual deletion. Use `--dry-run` to inspect planned cleanup safely.

## Methodological Notes

- Controlled degradation is synthetic and project-local. It approximates selected observable symptoms such as delay variation and packet loss, not exact carrier traces.
- Congestion degradation is traffic-driven and uses simulator-default queue behavior; it is not a calibrated hardware queue study.
- AI-MRCE runtime candidates use compact observable telemetry and sustained positive decisions before acting.
- The active regional AI-MRCE protective action installs explicit host-specific manual IPv4 repair routes along the configured southern backup corridor. This represents activation of a prearranged local protection path and avoids changing INET or OSPF internals.
- The repair-route action is a project-local FRR-like abstraction, not an implementation of standards-compliant IP FRR, LFA/TI-LFA, BFD, or custom OSPF extensions.
- Current controller scalars include activation-time diagnostic telemetry (`activationRiskScore`, threshold, streak, queue state, probe delay/throughput/count) and `repairRouteInstallTime`. These are audit signals only; they do not change the decision or routing semantics.
- Outcome improvements are scenario-conditioned. They should be described descriptively unless enough independent runs are available for stronger statistical analysis.
- A run may show no one-second service interruption while still showing unobserved packet gaps, receiver-observed reordering, or endpoint receive gaps. Report these as packet-continuity or useful-goodput continuity impacts, not as RFC-standard restoration timers.
- Packet-continuity reporting now separates operational `after_reference` gaps from `after_hard_failure`, `after_protection_activation`, `between_activation_and_failure`, and `after_critical_start` views. Use `after_hard_failure` for the cleanest post-failure protection comparison, and use the activation-to-failure fields to report any pre-failure switch penalty honestly.
- The legacy `packet_sequence_gap_total_missing_*` fields are forward-jump continuity estimates retained for compatibility, not direct packet-loss claims. After a repair-route switch, newer packets on the faster repair path can overtake older packets delayed in the congested primary queue; use the `packet_sequence_gap_total_unobserved_*` and `packet_sequence_gap_total_reordered_*` fields to distinguish likely unobserved/lost packets from out-of-order delivery.
- Queue-normalized activation-to-failure diagnostics relate reordered/unobserved counts to `activationQueueLengthPk`. They support mechanism diagnosis only and must not be reported as proof of a universal queue threshold or seamless FRR behavior.
- The mixed UDP/TCP branch is a practical transport-impact extension using standard INET applications. TCP useful-goodput is measured from application endpoint byte vectors, not TCP-internal retransmission or congestion-control counters. It improves realism over UDP-only evidence, but it is still a controlled simulator scenario rather than an Internet traffic trace.
- Analysis scripts resolve explicit relative CLI paths from the project root. Prefer running commands from the project root for readability, but paths such as `analysis\output\...` are no longer dependent on the caller's current directory.

## Before Committing

Review source, config, and documentation changes only. Do not commit generated artifacts from:

- `out/`
- `results/`
- `analysis/output/`
- `analysis/sklearn-env/`

Runtime deployment CSVs under `simulations/regionalbackbone/` are intentionally source-controlled example artifacts. Regenerate them with `run_analysis.bat export-runtime-models --configs RegionalBackboneCongestionDegradation` when the training dataset or runtime export code changes.
