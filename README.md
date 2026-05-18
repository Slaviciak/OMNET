# Dissertation Simulation: AI-MRCE Regional Backbone

This repository is a dissertation research prototype for AI-MRCE: an
AI-assisted, telemetry-driven proactive protection controller for IP routing
domains. The active simulator implementation uses OMNeT++ / INET with an OSPF
regional backbone topology.

The project is intentionally conservative. It does not modify INET internals or
OSPF internals, and it does not claim standards-compliant BFD, LFA, TI-LFA, or
FRR. The practical goal is narrower: evaluate whether observable
degradation/brownout telemetry can trigger project-local repair routes before a
hard failure and improve operational outcome metrics relative to reactive OSPF
behavior.

## Active Dissertation Core

The strongest current result block is:

`regionalbackbone_failure_detection_degraded_link_model_family`

It compares:

- OSPF only;
- OSPF + project-local BFD-like detector + FRR-like repair routes;
- AI-MRCE rule-based + FRR-like repair routes;
- AI-MRCE logistic regression + FRR-like repair routes;
- AI-MRCE linear SVM + FRR-like repair routes;
- AI-MRCE shallow tree + FRR-like repair routes;
- hybrid BFD-like + AI-MRCE + FRR-like repair routes.

The active implementation files are centered on:

- `simulations/regionalbackbone/`;
- `src/dissertationsim/controller/AiMrceController.*`;
- `src/dissertationsim/controller/LinkDegradationController.*`;
- `analysis/build_dataset.py`;
- `analysis/dataset_report.py`;
- `analysis/compare_outcomes.py`;
- `analysis/export_runtime_models.py`;
- `analysis/extract_aimrce_risk_trace.py`;
- `analysis/pipeline_integrity.py`;
- `analysis/package_current_experiment.py`;
- `analysis/clean_generated.py`;
- `analysis/run_analysis.ps1`;
- `analysis/run_experiments.ps1`.

Legacy standalone scenario trees were removed during the publication-readiness
cleanup. The repository now presents the regionalbackbone degraded-link
model-family workflow as the reproducible dissertation core. The regional
`omnetpp.ini` now uses a compact active hierarchy for the model-family cohort,
with `RegionalBackboneCongestionDegradation` retained only as the runtime-model
export/training support config.

## Main Reproduction Commands

Run from the project root:

```bat
cmd /c run_analysis.bat export-runtime-models --configs RegionalBackboneCongestionDegradation
cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --clean --yes --skip-runtime-export --skip-build
py -3 analysis\build_dataset.py --scenario regionalbackbone_failure_detection_degraded_link_model_family
py -3 analysis\dataset_report.py --scenario regionalbackbone_failure_detection_degraded_link_model_family
py -3 analysis\compare_outcomes.py --inputs analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family
py -3 analysis\extract_aimrce_risk_trace.py --scenario regionalbackbone_failure_detection_degraded_link_model_family --runs 0 --start 78 --end 86
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

For this dedicated publication cohort, omitting `--runs` runs the full
five-run set `0,1,2,3,4`. Use `--skip-build` only when the local project
binary is already current. Use `--skip-runtime-export` only when the runtime
CSV artifacts are intentionally being reused.

For development/regression work, `--runs 0` is the intended smoke mode. The
pipeline-integrity report should then return `OK_WITH_WARNINGS` because the
workspace is complete for run 0 but not yet publication-ready. For dissertation
or article tables, run the full five-run cohort and regenerate the dataset,
report, comparison, headline summary, and risk trace afterward.

## Important Outputs

Generated outputs are organized under `analysis/output/`:

- `datasets/`: dataset CSVs generated from OMNeT++ scalar/vector results;
- `reports/`: dataset sanity reports;
- `outcomes/`: outcome summaries, comparison CSVs, headline summaries, and
  human-readable comparison reports;
- `debug/`: missing-value summaries, per-config summaries, risk traces,
  event summaries, and pipeline-integrity reports;
- `audit/`: generated snapshots for implementation audits;
- `experiment_logs/`: wrapper execution logs;
- `training/`: offline ML training/evaluation artifacts.

Raw OMNeT++ results are generated under `results/`. Build outputs are generated
under `out/`.

These generated folders are ignored by `.gitignore` and should not be committed.
Runtime deployment CSV examples under `simulations/regionalbackbone/` are
intentionally source-controlled so the runtime configs remain auditable; refresh
them with the documented export command when training data or export code
changes.

Regional model-family `.vec` files can be hundreds of MB each. The dataset
builder prints per-file progress and elapsed timing so a long parse looks like
active work rather than a stalled command. Generated CSV/TXT writers use
same-directory temporary files and atomic replacement where practical to reduce
the risk of half-written artifacts after interrupted runs.

## Diagnostic Commands

Generate graph-ready AI-MRCE decision traces:

```bat
cmd /c run_analysis.bat model-risk-trace --scenario regionalbackbone_failure_detection_degraded_link_model_family --runs 0 --start 78 --end 86
```

Write a pipeline-integrity report:

```bat
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

Preview generated-output cleanup without deleting files:

```bat
cmd /c run_analysis.bat clean-generated
cmd /c run_analysis.bat clean-generated --include-results --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

Actual cleanup requires both `--clean` and `--yes`.

## Demonstration Logging

For controlled EV logging, use the degraded-link debug configs in
`simulations/regionalbackbone/omnetpp.ini`, for example:

```bat
cd simulations\regionalbackbone
..\..\out\gcc-release\src\dissertationsim.exe -u Cmdenv --cmdenv-express-mode=false --cmdenv-event-banners=false -f omnetpp.ini -c RegionalBackboneFailureDegradedLinkAiMrceLogRegDebug -r 0
```

The debug configs suppress unrelated Cmdenv INFO logs and re-enable INFO only
for `RegionalBackbone.aiMrceController`. Useful prefixes include
`[AI-MRCE:init]`, `[AI-MRCE:model]`, `[AI-MRCE:decision]`,
`[AI-MRCE:trigger]`, `[BFD-like:probe]`, `[BFD-like:trigger]`,
`[FRR-like:repair-route]`, and `[Scenario:hard-failure]`.

## Methodological Guardrails

Allowed interpretation:

- evidence is scenario-conditioned;
- AI-MRCE is proactive in the degraded-link profile;
- BFD-like detection is a reactive safety net;
- repair-route activation is a project-local FRR-like abstraction;
- post-failure unobserved gaps, activation-to-failure unobserved gaps, and
  reordering must be reported separately.

Do not claim:

- universal failure prediction;
- standards-compliant BFD or FRR;
- seamless make-before-break behavior;
- generalization to all topologies, traffic mixes, or failure classes;
- statistical significance beyond the current run count and design.

See `analysis/AIMRCE_METHODOLOGY.md` and `analysis/WORKFLOW.md` for the detailed
methodology and workflow.
