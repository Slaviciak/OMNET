# AI-MRCE Current Experiment Workflow

This workflow is intentionally narrow after the publication-readiness cleanup.
The supported dissertation core is the regional OSPF backbone degraded-link
model-family experiment:

`regionalbackbone_failure_detection_degraded_link_model_family`

The standalone legacy scenario trees were deleted. Historical regionalbackbone
experimental configs were removed from `simulations/regionalbackbone/omnetpp.ini`.
The retained regional configs are the active model-family hierarchy plus
`RegionalBackboneCongestionDegradation`, which supports runtime-model export
from the regional training artifact path.

## Active Mechanisms

- `ospf_only`
- `bfd_like_frr`
- `aimrce_rule_based_frr`
- `aimrce_logistic_regression_frr`
- `aimrce_linear_svm_frr`
- `aimrce_shallow_tree_frr`
- `hybrid_bfd_like_aimrce_frr`

## Development Smoke Run

Use run 0 when checking code or pipeline behavior without rebuilding the full
publication cohort:

```bat
cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --runs 0 --clean --yes --skip-runtime-export --skip-build
py -3 analysis\build_dataset.py --scenario regionalbackbone_failure_detection_degraded_link_model_family
py -3 analysis\dataset_report.py --scenario regionalbackbone_failure_detection_degraded_link_model_family
py -3 analysis\compare_outcomes.py --inputs analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

Run-0 development mode should produce `OK_WITH_WARNINGS` from
`pipeline-integrity` because it is intentionally incomplete for publication.

## Full Publication Cohort

For dissertation/article outputs, omit `--runs` so the wrapper runs
`0,1,2,3,4` for all seven mechanisms:

```bat
cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --clean --yes --skip-runtime-export --skip-build
py -3 analysis\build_dataset.py --scenario regionalbackbone_failure_detection_degraded_link_model_family
py -3 analysis\dataset_report.py --scenario regionalbackbone_failure_detection_degraded_link_model_family
py -3 analysis\compare_outcomes.py --inputs analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family
py -3 analysis\extract_aimrce_risk_trace.py --scenario regionalbackbone_failure_detection_degraded_link_model_family --runs 0 --start 78 --end 86
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

Publication mode should produce `OK` from `pipeline-integrity`, with 7 observed
mechanism families, 5 runs per mechanism, 35 outcome rows, runtime model
artifacts present, and no learned-model fallback.

## Runtime Model Artifacts

The runtime model CSV examples under `simulations/regionalbackbone/` are
intentionally source-controlled:

- `aimrce_runtime_manifest.csv`
- `aimrce_runtime_logreg.csv`
- `aimrce_runtime_linsvm.csv`
- `aimrce_runtime_shallow_tree.csv`

Regenerate them only when the training dataset or export code changes:

```bat
cmd /c run_analysis.bat export-runtime-models --configs RegionalBackboneCongestionDegradation
```

The active simulation configs fail fast if a required learned runtime artifact
is missing or cannot be loaded. Rule-based AI-MRCE intentionally requires no
runtime CSV artifact.

## Risk Trace And Current Package

Generate graph-ready AI-MRCE model-action traces:

```bat
cmd /c run_analysis.bat model-risk-trace --scenario regionalbackbone_failure_detection_degraded_link_model_family --runs 0 --start 78 --end 86
```

Create a compact sendable package from existing generated outputs:

```bat
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

The package is written under:

`analysis/output/current_experiment/regionalbackbone_failure_detection_degraded_link_model_family/`

It intentionally excludes raw `.vec`, `.vci`, `.sca`, `.elog`, and build
artifacts.

## Cleanup

Preview cleanup:

```bat
cmd /c run_analysis.bat clean-generated
```

Actual generated-output cleanup requires both `--clean` and `--yes`. Use
scenario-targeted result cleanup only when you intentionally want to remove raw
generated outputs:

```bat
cmd /c run_analysis.bat clean-generated --include-results --scenario regionalbackbone_failure_detection_degraded_link_model_family --clean --yes
```

Do not commit `analysis/output/`, `results/`, `out/`, eventlogs, packet
captures, or local virtual environments. Do commit source, configs, docs,
wrappers, and the runtime model CSV examples under `simulations/regionalbackbone/`.

## Methodological Guardrails

- AI-MRCE is a telemetry-driven proactive controller evaluated in a deterministic
  progressive degraded-link/brownout stress profile.
- BFD-like is project-local and BFD-inspired; it is not RFC BFD.
- FRR-like repair routes are project-local static `/32` repair-route
  abstractions; they are not standards-compliant LFA, TI-LFA, or FRR.
- Results are scenario-conditioned and do not establish universal failure
  prediction.
- Reordering and activation costs remain visible and must be reported.
