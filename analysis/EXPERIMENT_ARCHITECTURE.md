# Experiment Architecture

This repository is now centered on one publication-ready dissertation core:

`regionalbackbone_failure_detection_degraded_link_model_family`

The old standalone small-topology scenario trees were removed during cleanup.
The remaining architecture is deliberately narrower: regionalbackbone
simulation source, AI-MRCE/FRR-like/BFD-like controllers, runtime model
artifacts, and the analysis pipeline needed to reproduce, validate, trace, and
package the active experiment.

## Simulation Layer

Active scenario directory:

- `simulations/regionalbackbone/`

Important files:

- `RegionalBackbone.ned`: regional OSPF backbone topology.
- `omnetpp.ini`: active model-family configs plus retained base configs used by
  inheritance and runtime export.
- `aimrce_runtime_manifest.csv`: runtime model artifact manifest.
- `aimrce_runtime_logreg.csv`: logistic-regression runtime model.
- `aimrce_runtime_linsvm.csv`: linear-SVM runtime model.
- `aimrce_runtime_shallow_tree.csv`: shallow-tree runtime model.

The active model-family configs compare:

- OSPF only;
- BFD-like + FRR-like repair routes;
- AI-MRCE rule-based + FRR-like repair routes;
- AI-MRCE logistic regression + FRR-like repair routes;
- AI-MRCE linear SVM + FRR-like repair routes;
- AI-MRCE shallow tree + FRR-like repair routes;
- hybrid BFD-like + AI-MRCE + FRR-like repair routes.

Historical regionalbackbone experimental configs were removed from the active
`omnetpp.ini` hierarchy. The only retained non-model-family config is
`RegionalBackboneCongestionDegradation`, which supports runtime-model export and
is not presented as a separate publication claim.

## Controller Layer

Active custom controllers:

- `src/dissertationsim/controller/AiMrceController.*`
- `src/dissertationsim/controller/LinkDegradationController.*`
- `src/dissertationsim/controller/InterfaceWithdrawController.*`

`AiMrceController` is the core dissertation mechanism. It collects telemetry,
constructs runtime features, evaluates rule-based or learned risk policies,
applies threshold/streak logic, arbitrates AI-MRCE and BFD-like triggers in
hybrid mode, installs project-local static `/32` repair routes, and records
diagnostics.

`LinkDegradationController` provides deterministic pre-failure impairment for
the degraded-link/brownout profile. Hard failure remains separate and is handled
by the scenario script/config timing, not by using future failure knowledge in
the AI-MRCE decision.

`InterfaceWithdrawController` is retained as auxiliary/reference source. It is
not the active AI-MRCE dissertation mechanism.

## Analysis Layer

Active pipeline scripts:

- `analysis/build_dataset.py`
- `analysis/dataset_report.py`
- `analysis/compare_outcomes.py`
- `analysis/extract_aimrce_risk_trace.py`
- `analysis/export_runtime_models.py`
- `analysis/pipeline_integrity.py`
- `analysis/package_current_experiment.py`
- `analysis/clean_generated.py`
- `analysis/run_analysis.ps1`
- `analysis/run_experiments.ps1`

The pipeline reads OMNeT++ `.sca/.vec/.vci` outputs from the active results
folder, produces dataset/report/outcome/comparison artifacts, validates
mechanism/run coverage with pipeline integrity, extracts AI-MRCE risk traces,
and builds a compact current-experiment package for review.

Support-only Python tooling:

- `analysis/train_risk_model.py` remains as offline ML methodology support. It
  is not part of the default active publication regeneration path and is not
  exposed by the cleaned `run_analysis.bat help` surface.

## Generated Outputs

Generated outputs are ignored and should not be committed:

- `results/`
- `out/`
- `analysis/output/`
- eventlogs and packet captures
- local Python virtual environments and caches

The current active raw result folder is:

`results/regionalbackbone/failure_detection_degraded_link_model_family/`

The compact review package is:

`analysis/output/current_experiment/regionalbackbone_failure_detection_degraded_link_model_family/`

## Claims And Non-Claims

Allowed claims are scenario-conditioned:

- AI-MRCE activates earlier than the project-local BFD-like comparator in the
  deterministic progressive degraded-link profile.
- Hybrid protection is AI-MRCE-first in the current degraded-link profile.
- AI-MRCE removes post-hard-failure unobserved gaps in the validated cohort.
- Repair-route reordering remains visible and must be reported.

Non-claims:

- no universal failure prediction;
- no RFC-compliant BFD implementation;
- no standards-compliant LFA, TI-LFA, or FRR implementation;
- no seamless make-before-break guarantee;
- no generalization beyond the current topology, traffic profile, degradation
  class, and run count.
