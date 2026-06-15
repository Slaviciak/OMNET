# AI-MRCE Current Experiment Workflow

This workflow covers the current regional-backbone dissertation scenario set.
The paper-facing narrative uses three main roles. These three main roles now
share a unified mixed UDP/TCP workload and common metric contract:

- `regionalbackbone_failure_detection_degraded_link_model_family`
- `regionalbackbone_failure_detection_cost_aware_backup`
- `regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented`

Two additional scenarios remain available for supplementary traceability:

- `regionalbackbone_failure_detection_degradation_sensitivity`
- `regionalbackbone_failure_detection_cost_aware_transport_impact`

The final evaluation report is the preferred review entry point:

```bat
cmd /c run_analysis.bat evaluate-results
```

The standalone legacy small-topology scenario trees are not part of the public
workflow. Hidden legacy helper branches in the experiment wrapper are retained
only as compatibility/support code and are not advertised in `help`.

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
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degraded_link_model_family --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degraded_link_model_family --feature-set extended
cmd /c run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

Run-0 development mode should produce `OK_WITH_WARNINGS` from
`pipeline-integrity` because it is intentionally incomplete for publication.

## Full Publication Cohort

For dissertation/article outputs, omit `--runs` so the wrapper runs
`0,1,2,3,4` for all seven mechanisms:

```bat
cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --clean --yes --skip-runtime-export --skip-build
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat model-risk-trace --scenario regionalbackbone_failure_detection_degraded_link_model_family --runs 0 --start 78 --end 86
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

Publication mode should produce `OK` from `pipeline-integrity`, with 7 observed
mechanism families, 5 runs per mechanism, 35 outcome rows, runtime model
artifacts present, and no learned-model fallback.

To reduce wall-clock time on a capable machine, add `--jobs N` to parallelize
independent OMNeT++ config/run processes:

```bat
cmd /c run_experiments.bat regional-failure-detection-degraded-link-model-family-batch --clean --yes --skip-runtime-export --skip-build --jobs 2
```

`--jobs 1` is equivalent to the sequential workflow. `--jobs` does not
parallelize one simulation process and should be kept conservative, commonly
`2` to `4`, because concurrent `.vec` generation can be disk-I/O and RAM
intensive. Always run `pipeline-integrity` afterward.

Interpret the five runs as reproducibility and workflow coverage for this
controlled cohort. They are not broad stochastic significance evidence because
the active progressive degraded-link/brownout profile is largely deterministic.

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

The final unified mixed-workload rerun refreshed these CSV artifacts because
adding TCP to the Link-Failure and Degraded-Backup scenarios changed the
telemetry distribution. Scenario C's queue-buildup redesign keeps the same
runtime feature order and deployed four-feature vector; refresh runtime CSVs
only after a deliberate training/export decision.

The active simulation configs fail fast if a required learned runtime artifact
is missing or cannot be loaded. Rule-based AI-MRCE intentionally requires no
runtime CSV artifact.

## Risk Trace And Current Package

Generate graph-ready AI-MRCE model-action traces:

```bat
cmd /c run_analysis.bat model-risk-trace --scenario regionalbackbone_failure_detection_degraded_link_model_family --runs 0 --start 78 --end 86
```

Generate analysis-only UDP/QoS network-impact summaries from existing dataset
and outcome artifacts:

```bat
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

This command writes separate files under `analysis/output/network_impact/`.
It does not change simulator behavior, existing outcome columns, runtime model
artifacts, or AI-MRCE decisions. Delivery/loss-like ratios and delay-variation
fields are conservative proxies where exact packet accounting or RFC 5481 IPDV
is not available. TCP impact is reported as endpoint received-byte/goodput and
progress proxies in the unified mixed UDP/TCP main scenarios; TCP-stack RTT,
retransmission, cwnd, duplicate-ACK, and exact finite-flow-completion claims
are made only when explicitly exported.

## Optional Extended Telemetry Dataset

Generate telemetry-v2 candidate features through the existing dataset pipeline:

```bat
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degraded_link_model_family --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degraded_link_model_family --feature-set extended
```

This writes separate extended artifacts and leaves the validated baseline
dataset/outcome workflow unchanged. Extended columns use `id_*`, `meta_*`,
`phase_*`, `feat_*`, and `label_*` prefixes and are derived from recorded
OMNeT++/INET vectors, AI-MRCE controller vectors/scalars, degradation vectors,
queue vectors, and receiver application vectors already present in the current
outputs. They are candidate features for later ML study only; runtime model
export remains on the compact four-feature set until a separate retraining and
leakage-review pass is performed.

Run the offline feature-quality and ML feasibility audit after the extended
dataset exists:

```bat
cmd /c run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

The audit writes separate files under `analysis/output/ml_audit/`. It is
offline-only: it does not change AI-MRCE runtime behavior, thresholds, runtime
model CSVs, or validated outcome summaries. Treat any gains as feasibility
evidence for this controlled cohort, not production ML generalization.

## Degradation-Sensitivity Cohort

The optional sensitivity cohort is separate from the validated publication
core:

`regionalbackbone_failure_detection_degradation_sensitivity`

It reuses the same topology, traffic, AI-MRCE policies, BFD-like comparator,
repair-route actuator, and runtime model CSVs, while varying only the
progressive degradation profile:

- `mild_slow`;
- `moderate`;
- `severe_fast`.

Use it to test robustness and whether telemetry-v2 features become more useful
under profile variability. Do not use it to retune thresholds or imply universal
failure prediction.

Run-0 smoke workflow:

```bat
cmd /c run_experiments.bat regional-degradation-sensitivity-batch --runs 0 --clean --yes --skip-runtime-export --skip-build
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degradation_sensitivity
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degradation_sensitivity --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degradation_sensitivity
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degradation_sensitivity --feature-set extended
cmd /c run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_failure_detection_degradation_sensitivity_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_degradation_sensitivity
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_degradation_sensitivity
cmd /c run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_degradation_sensitivity
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degradation_sensitivity
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_degradation_sensitivity
```

For full sensitivity coverage, omit `--runs 0`; the full matrix is 3 profiles x
7 mechanisms x 5 runs.
The same `--jobs N` option is available for the sensitivity batch, for example:

```bat
cmd /c run_experiments.bat regional-degradation-sensitivity-batch --clean --yes --skip-runtime-export --skip-build --jobs 2
```

## Cost-Aware Backup-Path Cohort

The optional cost-aware cohort is separate from both the validated publication
core and the degradation-sensitivity robustness cohort:

`regionalbackbone_failure_detection_cost_aware_backup`

It keeps the same seven mechanisms and deployed runtime model CSV artifacts, but
enables a mild persistent backup-corridor penalty so early switching is no
longer modeled as free. The normal primary path remains the preferred lower-cost
path; the southern repair corridor remains QoS-capable at 100 Mbps and adds
about 5 ms total extra path delay.

Profiles:

- `cost_aware_mild`
- `cost_aware_moderate`
- `cost_aware_fast_warning`

Run-0 smoke workflow:

```bat
cmd /c run_experiments.bat regional-cost-aware-backup-batch --runs 0 --clean --yes --skip-runtime-export --skip-build
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_cost_aware_backup --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_cost_aware_backup --feature-set extended
cmd /c run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_failure_detection_cost_aware_backup_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat activation-root-cause --scenario regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_cost_aware_backup
```

For full coverage, omit `--runs 0`. The full cost-aware matrix is 3 profiles x
7 mechanisms x 5 runs = 105 outcome rows:

```bat
cmd /c run_experiments.bat regional-cost-aware-backup-batch --clean --yes --skip-runtime-export --skip-build --jobs 2
```

The backup-cost tables are written under `analysis/output/network_impact/` as
separate component summaries. Interpret them as benefit/cost diagnostics, not
as a weighted utility claim.

## Supplementary Mixed UDP/TCP Transport-Impact Cohort

The baseline transport-impact cohort is retained for traceability:

`regionalbackbone_failure_detection_cost_aware_transport_impact`

It derives from the cost-aware backup-path scenario, keeps the UDP monitoring
traffic used by AI-MRCE, and adds a lightweight INET
`TcpBasicClientApp`/`TcpGenericServerApp` request-reply flow. TCP analysis is
limited to endpoint-observed received bytes, goodput, and progress/stall
proxies. RTT, retransmissions, congestion window, and exact finite-flow
completion are not claimed.

Run-0 smoke workflow:

```bat
cmd /c run_experiments.bat regional-cost-aware-transport-impact-batch --runs 0 --clean --yes --skip-runtime-export --skip-build
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_cost_aware_transport_impact --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_cost_aware_transport_impact --feature-set extended
cmd /c run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_failure_detection_cost_aware_transport_impact_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_cost_aware_transport_impact
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
cmd /c run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
cmd /c run_analysis.bat evaluate-results
```

For full coverage, omit `--runs 0`. The full matrix is 3 profiles x
7 mechanisms x 5 runs = 105 outcome rows:

```bat
cmd /c run_experiments.bat regional-cost-aware-transport-impact-batch --clean --yes --skip-runtime-export --skip-build --jobs 2
```

Run-0 transport integrity is expected to report `OK_WITH_WARNINGS` until the
full five-run matrix is regenerated.

### Scenario C: Congestion/Queue-Buildup Early Mitigation

The queue-buildup mitigation scenario is:

`regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented`

It preserves the mixed UDP/TCP topology, mechanisms, profiles, thresholds, and
repair-route behavior, but enables the protected-span bottleneck so staged
traffic creates progressive queue buildup and QoS degradation before hard
failure. It also records targeted INET scalar/histogram telemetry for stronger
networking figures: exact aggregate UDP sent/received/loss accounting across
configured UDP apps, histogram-derived UDP delay percentiles, TCP endpoint
goodput/progress, TCP RTT/cwnd summaries where INET exports them, and compact
queue drop/queueing diagnostics. IPDV-like jitter, link utilization, and TCP
retransmissions remain unavailable unless the corresponding vectors/scalars are
deliberately enabled.

Run smoke and analysis first; do not start the full cohort until size and metric
availability are acceptable:

```bat
cmd /c run_experiments.bat regional-cost-aware-transport-impact-instrumented-batch --dry-run
cmd /c run_experiments.bat regional-cost-aware-transport-impact-instrumented-batch --runs 0 --clean --yes --skip-runtime-export --skip-build --jobs 1
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented --feature-set extended
cmd /c run_analysis.bat compare-outcomes --inputs analysis\output\outcomes\regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented_outcome_summary.csv --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
```

The expected run-0 status is `OK_WITH_WARNINGS`; full-cohort publication status
requires all five runs.

Create a compact sendable package from existing generated outputs:

```bat
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

The package is written under:

`analysis/output/current_experiment/regionalbackbone_failure_detection_degraded_link_model_family/`

It intentionally excludes raw `.vec`, `.vci`, `.sca`, `.elog`, and build
artifacts.

Package files and audit notes may record absolute local Windows source paths for
provenance. Those paths are not portable requirements; public users should
regenerate the package from their own project-root clone.

## Cleanup

Preview cleanup:

```bat
cmd /c run_analysis.bat clean-final-evaluation --dry-run
cmd /c run_analysis.bat clean-generated --dry-run
```

`clean-final-evaluation` targets only generated figure files under
`analysis/output/final_evaluation/` and leaves tables, reports, packages,
datasets, outcomes, raw results, source files, and runtime model CSVs alone.

Actual broader generated-output cleanup requires both `--clean` and `--yes`.
Use scenario-targeted result cleanup only when you intentionally want to remove
raw generated outputs:

```bat
cmd /c run_analysis.bat clean-generated --include-results --scenario regionalbackbone_failure_detection_degraded_link_model_family --clean --yes
```

Experiment wrappers also perform target-scenario cleanup when rerun with
`--clean --yes`. For full-cohort runs, the wrapper removes the selected
scenario's old `.sca`, `.vec`, `.vci`, `.elog`, scenario-specific datasets,
outcomes, network-impact summaries, old packages, old scenario logs, and stale
final-evaluation figures before launching replacement simulations. Bounded
`--configs ... --skip-analysis` smoke runs clean only the selected config/run
raw outputs.

Do not commit generated contents under `analysis/output/`, `results/`, `out/`,
eventlogs, packet captures, or local virtual environments. The exception is
`analysis/output/README.md`, which documents the generated-output policy. Do
commit source, configs, docs, wrappers, and the runtime model CSV examples
under `simulations/regionalbackbone/`.

## Publication Table Guidance

Recommended headline table fields:

- mechanism family;
- runtime model type;
- trigger source;
- activation time;
- lead time before hard failure;
- post-hard-failure unobserved packet gaps;
- activation-to-failure unobserved packet gaps;
- activation-to-failure reordered packets;
- activation queue length;
- fallback used;
- `repairRouteCount`.

Diagnostic-only fields include legacy `missing` / forward-jump fields,
queue-normalized ratios, and zero-progress/recovery-time fields when they remain
zero across the cohort.

## Methodological Guardrails

- AI-MRCE is a telemetry-driven proactive controller evaluated in a deterministic
  progressive degraded-link/brownout stress profile.
- BFD-like is project-local and BFD-inspired; it is not RFC BFD.
- FRR-like repair routes are project-local static `/32` repair-route
  abstractions; they are not standards-compliant LFA, TI-LFA, or FRR.
- Results are scenario-conditioned and do not establish universal failure
  prediction.
- Reordering and activation costs remain visible and must be reported.
