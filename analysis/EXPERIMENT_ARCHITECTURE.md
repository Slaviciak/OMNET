# Experiment Architecture

This note records the consolidated experiment architecture after aligning the repository with the dissertation framing document for **Intelligent Fast Network Recovery**.

The project should be read as one dissertation prototype, not as a growing collection of unrelated OMNeT++ examples.

## Research Center

The active research question is whether a project-local AI-MRCE element can use monitored network indicators and offline-trained, auditable models to trigger a protective reroute action before selected hard outages, then improve practical recovery/protection outcomes relative to reactive behavior.

The simulator contribution is therefore:

- a regional IP/OSPF-like topology,
- controlled degradation and congestion branches with observable symptoms,
- runtime AI-MRCE decision candidates,
- conservative project-local FRR-like repair-route protection action,
- a separate BFD-inspired protected-span safety-net comparison branch,
- offline training/export,
- run-level recovery/protection outcome comparison.
- receiver-observed packet-continuity diagnostics that complement coarse
  one-second availability windows when rerouting effects are short.
- activation-time controller diagnostics that make the repair-route trigger
  auditable without changing routing or AI-MRCE decision semantics.
- reordering-aware sequence diagnostics so a repair path overtaking queued
  primary-path packets is not misreported as pure packet loss.

The simulator does not attempt to implement every FRR mechanism from the literature. Standards-compliant FRR and BFD remain literature and technical-comparison baselines. The failure-detection comparison branch uses a project-local BFD-like detector abstraction only. Regional OSPF uses INET OSPFv2 defaults consistently across the topology unless a config states otherwise; no OSPF timer is tuned to create an artificial baseline.

## Core Active Scenario

### `simulations/regionalbackbone`

Role: main dissertation topology.

Purpose:

- validate baseline OSPF-like behavior,
- compare reactive behavior after hard failure,
- model selected pre-failure degradation/congestion classes,
- evaluate AI-MRCE runtime candidates under one consistent topology,
- support multi-run practical outcome comparison.

Core configs:

- `RegionalBackboneBaseline`
- `RegionalBackboneReactiveFailure`
- `RegionalBackboneControlledDegradation`
- `RegionalBackboneCongestionDegradation`

Runtime AI-MRCE configs:

- `RegionalBackboneAiMrceRuleBased`
- `RegionalBackboneAiMrceLogReg`
- `RegionalBackboneAiMrceLinearSvm`
- `RegionalBackboneAiMrceShallowTree`

Focused mixed UDP/TCP configs:

- `RegionalBackboneMixedTrafficCongestionDegradation`
- `RegionalBackboneAiMrceRuleBasedMixedTraffic`
- `RegionalBackboneAiMrceLogRegMixedTraffic`

Dedicated multi-run cohort wrappers:

- `RegionalBackboneCongestionDegradationCohort`
- `RegionalBackboneAiMrceRuleBasedCohort`
- `RegionalBackboneAiMrceLogRegCohort`
- `RegionalBackboneAiMrceLinearSvmCohort`
- `RegionalBackboneAiMrceShallowTreeCohort`
- `RegionalBackboneMixedTrafficCongestionDegradationCohort`
- `RegionalBackboneAiMrceRuleBasedMixedTrafficCohort`
- `RegionalBackboneAiMrceLogRegMixedTrafficCohort`
- `RegionalBackboneFailureComparisonOspfOnlyCohort`
- `RegionalBackboneFailureComparisonBfdLikeFrrCohort`
- `RegionalBackboneFailureComparisonAiMrceFrrCohort`
- `RegionalBackboneFailureComparisonHybridCohort`
- `RegionalBackboneFailureComparisonOspfOnlyMsTrafficCohort`
- `RegionalBackboneFailureComparisonBfdLikeFrrMsTrafficCohort`
- `RegionalBackboneFailureComparisonAiMrceFrrMsTrafficCohort`
- `RegionalBackboneFailureComparisonHybridMsTrafficCohort`
- `RegionalBackboneFailureComparisonOspfOnlyDegradedLinkCohort`
- `RegionalBackboneFailureComparisonBfdLikeFrrDegradedLinkCohort`
- `RegionalBackboneFailureComparisonAiMrceFrrDegradedLinkCohort`
- `RegionalBackboneFailureComparisonHybridDegradedLinkCohort`

This is the scenario family that should appear in main dissertation result tables.

The mixed UDP/TCP branch is intentionally smaller than the full runtime family. It compares the reactive congestion baseline against the existing rule-based and logistic-regression AI-MRCE candidates while adding standard INET TCP application traffic whose larger request direction follows the monitored hostA -> hostB corridor. TCP useful-goodput remains an application-endpoint proxy, not a TCP-internal restoration counter. The logistic-regression mixed run intentionally reuses the UDP-dominant regional runtime export, so missed protection there should be interpreted as deployment-compatibility evidence rather than tuned away. This keeps the transport-impact evidence focused without creating many weak variants.

The failure-detection comparison branch is intentionally separate from the main AI-MRCE model-family cohort. It compares OSPF-only behavior, a BFD-like protected-span detector plus the same repair-route actuator, AI-MRCE plus the same actuator, and a hybrid where the first trigger wins. The BFD-like detector is a project-local reactive abstraction using protected-span interface/carrier state plus configurable probe-miss intervals and a detect multiplier; it must not be reported as full BFD session behavior or OSPF/BFD integration. The active BFD-like timing profile is moderate-fast rather than deliberately weak: 300ms intervals with multiplier 3, expected detection about 0.9s after the protected span is observed unhealthy.

The 2 ms monitored-traffic failure-detection branch is a measurement-resolution sensitivity cohort, not a new mechanism. The default failure-detection cohort already uses a 10 ms monitored UDP probe; the ms-traffic branch lowers only that monitored probe interval to 2 ms while preserving the same staged bulk load, hard-failure timing, BFD-like timing, AI-MRCE decision semantics, and repair-route actuator. Its purpose is to make sub-second fast-recovery effects more observable in receiver-side packet-continuity metrics without pretending to implement standards-compliant BFD or seamless FRR.

The degraded-link failure-detection branch is a BFD-like correctness sensitivity cohort. It keeps the same trigger families and repair-route actuator, but adds deterministic progressive packet-error-rate impairment on the protected span before the same hard failure. BFD-like and hybrid variants enable modeled logical probe loss derived from current channel packet error rate, so this branch can test whether the reactive safety net fires before hard failure when the link is already visibly losing packets. This is still not full BFD and not predictive logic; it is an auditable degraded-link detector abstraction.

## Auxiliary Data Scenarios

### `simulations/linkdegradation`

Role: auxiliary controlled synthetic data branch.

Purpose:

- isolate delay, delay variation, and packet-error-rate symptoms,
- provide optional sanity checks and cross-topology training evidence,
- retain the staged intermittent brownout-style profile as a clearly synthetic approximation.

This branch is useful but secondary. It should not be presented as the main validation topology.

### `simulations/congestiondegradation`

Role: auxiliary traffic-driven congestion branch.

Purpose:

- isolate queue buildup and delivery impact in the small topology,
- provide optional sanity checks and cross-topology training evidence,
- validate that congestion symptoms can be generated through traffic pressure instead of direct channel impairment.

This branch is useful but secondary.

## Archival Reference Scenarios

### `simulations/dualpathbaseline`

Role: archival minimal OSPF sanity reference.

Use only when a tiny topology is needed to check basic routing behavior.

### `simulations/reactivefailure`

Role: archival small-topology reactive failure reference.

Regional backbone reactive branches now provide the dissertation-grade comparison context.

### `simulations/proactiveswitch`

Role: archival small-topology deterministic proactive switch prototype.

The active dissertation path now compares runtime AI-MRCE candidates in the regional congestion protection cohort.

### `simulations/simpletest`

Role: external/reference INET material.

Do not include in active batches, datasets, or dissertation result tables.

## Active Analysis Artifacts

The main analysis outputs are:

- datasets under `analysis/output/datasets/`,
- reports under `analysis/output/reports/`,
- outcome summaries and comparisons under `analysis/output/outcomes/`,
- offline ML evaluation outputs under `analysis/output/training/`,
- verbose helper/debug CSVs under `analysis/output/debug/`,
- batch logs under `analysis/output/experiment_logs/`.

## Methodological Guardrails

- Keep scenario-phase labels separate from operational outcome metrics.
- Keep runtime deployment artifacts separate from offline methodological evaluation.
- Keep AI-MRCE action semantics conservative: sustained positive decision followed by project-local activation of explicit host-specific repair routes on the configured backup corridor.
- Keep BFD-like semantics conservative: protected-span interface/carrier observation plus missed probe-reception intervals followed by the same project-local repair-route activation as a reactive safety net. In degraded-link variants, modeled logical probe loss is derived from current channel packet-error-rate impairment, not future failure time.
- Treat this as an auditable local-protection abstraction, not as a standards-compliant IP FRR/LFA/TI-LFA implementation.
- Treat the BFD-like branch as an experiment trigger abstraction, not standards-compliant BFD.
- Do not modify INET or OSPF internals in the current prototype.
- Do not claim that all failures are predictable.
- Do not claim carrier-calibrated restoration from the current operational metrics.
- Treat packet sequence gaps and endpoint receive gaps as descriptive
  application-delivery evidence, not as RFC-standard recovery timers.
- Keep packet-continuity reference points explicit. The operational
  after-reference view may include AI-MRCE activation transition cost, while
  the after-hard-failure view is the cleaner post-failure protection comparison.
- Treat `packet_sequence_gap_total_unobserved_after_hard_failure` as the
  headline loss-like post-failure continuity metric. Treat
  `packet_sequence_gap_total_reordered_between_activation_and_failure` and
  out-of-order event counts as pre-failure repair-route switch side-effect
  metrics. Legacy `packet_sequence_gap_total_missing_*` fields are forward
  sequence-jump estimates retained for compatibility, not direct loss claims.
- Queue-normalized activation-to-failure diagnostics relate the switch
  side-effect counts to `activationQueueLengthPk`. They are descriptive
  mechanism-audit values only and should not be interpreted as learned
  thresholds, standards-compliant FRR behavior, or make-before-break proof.
- Treat small-topology branches as optional support, not as the dissertation core.

## Current Default Workflow

Default dissertation commands should favor:

- `run_experiments.bat dataset-batch --scenario regionalbackbone`
- `run_analysis.bat train-risk-model`
- `run_analysis.bat export-runtime-models --configs RegionalBackboneCongestionDegradation`
- `run_experiments.bat regional-congestion-protection-batch`
- `run_experiments.bat regional-mixed-traffic-protection-batch`
- `run_experiments.bat regional-failure-detection-comparison-batch`
- `run_experiments.bat regional-failure-detection-degraded-link-batch`
- `run_analysis.bat compare-outcomes`

Use auxiliary or archival scenarios only when they answer a specific methodological question.
