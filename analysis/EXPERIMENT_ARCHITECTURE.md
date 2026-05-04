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
- offline training/export,
- run-level recovery/protection outcome comparison.
- receiver-observed packet-continuity diagnostics that complement coarse
  one-second availability windows when rerouting effects are short.
- activation-time controller diagnostics that make the repair-route trigger
  auditable without changing routing or AI-MRCE decision semantics.

The simulator does not attempt to implement every FRR mechanism from the literature. FRR and BFD remain literature and technical-comparison baselines unless they are explicitly represented by a project-local scenario branch.

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

This is the scenario family that should appear in main dissertation result tables.

The mixed UDP/TCP branch is intentionally smaller than the full runtime family. It compares the reactive congestion baseline against the existing rule-based and logistic-regression AI-MRCE candidates while adding standard INET TCP application traffic whose larger request direction follows the monitored hostA -> hostB corridor. TCP useful-goodput remains an application-endpoint proxy, not a TCP-internal restoration counter. The logistic-regression mixed run intentionally reuses the UDP-dominant regional runtime export, so missed protection there should be interpreted as deployment-compatibility evidence rather than tuned away. This keeps the transport-impact evidence focused without creating many weak variants.

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
- Treat this as an auditable local-protection abstraction, not as a standards-compliant IP FRR/LFA/TI-LFA implementation.
- Do not modify INET or OSPF internals in the current prototype.
- Do not claim that all failures are predictable.
- Do not claim carrier-calibrated restoration from the current operational metrics.
- Treat packet sequence gaps and endpoint receive gaps as descriptive
  application-delivery evidence, not as RFC-standard recovery timers.
- Keep packet-continuity reference points explicit. The operational
  after-reference view may include AI-MRCE activation transition cost, while
  the after-hard-failure view is the cleaner post-failure protection comparison.
- Treat small-topology branches as optional support, not as the dissertation core.

## Current Default Workflow

Default dissertation commands should favor:

- `run_experiments.bat dataset-batch --scenario regionalbackbone`
- `run_analysis.bat train-risk-model`
- `run_analysis.bat export-runtime-models --configs RegionalBackboneCongestionDegradation`
- `run_experiments.bat regional-congestion-protection-batch`
- `run_experiments.bat regional-mixed-traffic-protection-batch`
- `run_analysis.bat compare-outcomes`

Use auxiliary or archival scenarios only when they answer a specific methodological question.
