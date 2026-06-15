# AI-MRCE Proactive Network Recovery Simulator

This repository is a dissertation research prototype for AI-MRCE: an
AI-assisted, telemetry-driven proactive protection controller for IP routing
domains. The active simulator implementation uses OMNeT++ / INET with an OSPF
regional backbone topology.

The internal OMNeT++ project/package identifier remains `dissertationsim` for
build and NED-package stability. The public scientific display name is
**AI-MRCE Proactive Network Recovery Simulator**.

The project is intentionally conservative. It does not modify INET internals or
OSPF internals, and it does not claim standards-compliant BFD, LFA, TI-LFA, or
FRR. The practical goal is narrower: evaluate whether observable
degradation/brownout telemetry can trigger project-local repair routes before a
hard failure and improve operational outcome metrics relative to reactive OSPF
behavior.

## Validated Scenario Roles

The current public-ready project is organized around three paper-facing
scenario roles, plus two supplementary traceability scenarios. The three
paper-facing roles now share a unified mixed UDP/TCP workload so the final
figures can compare a common packet-delivery, transport-progress, and
activation-timing metric contract:

1. `regionalbackbone_failure_detection_degraded_link_model_family`
   - **Predictive Link-Failure Recovery**: basic validation that AI-MRCE can
     activate FRR-like repair before a hard link failure under the unified
     mixed UDP/TCP workload.
2. `regionalbackbone_failure_detection_cost_aware_backup`
   - **Cost-Aware Degraded-Backup Operation**: predictive switching under a
     primary path that is normally better and a QoS-capable backup path with
     mild nonzero cost, using the same mixed UDP/TCP workload.
3. `regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented`
   - **Congestion/Queue-Buildup Early Mitigation**: mixed UDP/TCP traffic on a
     protected primary span with progressive queue buildup and QoS degradation,
     plus targeted INET scalar/histogram telemetry for publication-facing
     networking metrics.

Supplementary scenarios are retained for robustness and traceability:

- `regionalbackbone_failure_detection_degradation_sensitivity`
  - robustness across `mild_slow`, `moderate`, and `severe_fast` profiles.
- `regionalbackbone_failure_detection_cost_aware_transport_impact`
  - baseline mixed UDP/TCP transport-impact validation superseded by the
    congestion/queue-buildup scenario for main networking figures.

All five retained scenario families use the same seven mechanism families:

- `ospf_only`
- `bfd_like_frr`
- `aimrce_rule_based_frr`
- `aimrce_logistic_regression_frr`
- `aimrce_linear_svm_frr`
- `aimrce_shallow_tree_frr`
- `hybrid_bfd_like_aimrce_frr`

The active implementation files are centered on:

- `simulations/regionalbackbone/`
- `src/dissertationsim/controller/`
- `analysis/core/` for dataset, outcome, network-impact, final-evaluation,
  integrity, and packaging scripts;
- `analysis/ml/` for offline ML support and explicit runtime-model export;
- `analysis/diagnostics/` for root-cause, trace, and cleanup helpers;
- `run_analysis.bat` / `analysis/run_analysis.ps1`
- `run_experiments.bat` / `analysis/run_experiments.ps1`

## Main Reproduction Commands

Run from the project root. The final report is regenerated from existing
outputs and is the preferred review entry point:

```bat
cmd /c run_analysis.bat evaluate-results
```

Validate the three main scenario roles:

```bat
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
```

Regenerate compact packages for the main scenarios:

```bat
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_degraded_link_model_family
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_cost_aware_backup
cmd /c run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
```

To rerun a full cohort, use the matching experiment wrapper. Omitting `--runs`
runs the full five-run set `0,1,2,3,4`; use `--runs 0` for a smoke pass.
Independent OMNeT++ config/run jobs can be run concurrently with `--jobs N`.
When a cohort is run with `--clean --yes`, the wrapper removes target-scenario
raw result files, scenario-specific generated analysis outputs, old logs, old
packages, and stale final-evaluation figures before writing replacement files:

```bat
cmd /c run_experiments.bat regional-cost-aware-transport-impact-batch --clean --yes --skip-runtime-export --skip-build --jobs 2
```

For the congestion/queue-buildup Scenario C smoke pass:

```bat
cmd /c run_experiments.bat regional-cost-aware-transport-impact-instrumented-batch --runs 0 --clean --yes --skip-runtime-export --skip-build --jobs 1
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
```

Use `--skip-build` only when the local project binary is already current. Use
`--skip-runtime-export` only when the runtime CSV artifacts are intentionally
being reused.

`--jobs` parallelizes separate OMNeT++ processes only; it does not parallelize a
single simulation. Use conservative values such as `2` to `4` depending on CPU,
RAM, and disk I/O capacity, because large `.vec` files are written during each
run. Recheck output equivalence with `pipeline-integrity`.

The five runs are a reproducibility and coverage cohort for this controlled
workflow. They should not be interpreted as broad stochastic statistical
significance, because the active degraded-link/brownout profile and controller
timing are largely deterministic by design.

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
- `network_impact/`: analysis-only UDP/QoS network-impact summaries derived
  from existing dataset/outcome artifacts;
- `debug/`: missing-value summaries, per-config summaries, risk traces,
  event summaries, and pipeline-integrity reports;
- `audit/`: generated snapshots for implementation audits;
- `experiment_logs/`: wrapper execution logs;
- `training/`: offline ML training/evaluation artifacts.

Raw OMNeT++ results are generated under `results/`. Build outputs are generated
under `out/`. Both are ignored by Git. Keep raw results locally when you want
to regenerate datasets/reports without rerunning simulations; delete them only
after a confirmed replacement run or explicit archival decision.

These generated folders are ignored by `.gitignore` and should not be committed.
Runtime deployment CSV examples under `simulations/regionalbackbone/` are
intentionally source-controlled so the runtime configs remain auditable; refresh
them with the documented export command when training data or export code
changes.

Local Python environments such as `analysis/sklearn-env/` are recreatable from
`analysis/requirements.txt` and should not be committed.

The learned AI-MRCE runtime policies are compact simulator-derived policy
variants. They use four runtime features and simulator-derived labels; they are
not claimed to be production-grade predictors or evidence of general
deployment-time ML generalization.

Because the unified workload adds TCP to the Link-Failure and Degraded-Backup
scenario families, the runtime model CSV artifacts were refreshed from the same
compact four-feature telemetry vector. Scenario C's queue-buildup redesign uses
the same runtime feature order and does not change AI-MRCE thresholds; runtime
CSV artifacts should be refreshed only after a legitimate training/export
decision, not after presentation-only changes.

Runtime deployability boundary: the deployed AI-MRCE feature vector contains
only protected queue length plus receiver-side active-probe delay, throughput,
and packet-count summaries. These are plausible real-network telemetry signals
via active probing, endpoint counters, streaming telemetry/gNMI, SNMP where
available, or controller-collected probe logs. Evaluation metrics such as hard
failure time, lead time, recovery/disruption proxy, post-failure gaps,
reordering, TCP endpoint summaries, scripted impairment state, and scenario
phase labels are not runtime model inputs.

Optional telemetry-v2 dataset generation is integrated into the existing
dataset pipeline:

```bat
cmd /c run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degraded_link_model_family --feature-set extended
cmd /c run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degraded_link_model_family --feature-set extended
```

The baseline dataset remains the validated core. The extended dataset is
analysis-only at this stage, is written separately as
`analysis/output/datasets/*_extended_dataset.csv`, and adds candidate
`feat_*`, `phase_*`, `label_*`, `meta_*`, and `id_*` columns derived from real
recorded simulation/controller telemetry. It does not retrain models or change
runtime CSV artifacts. Future ML use requires leakage review against the
generated extended feature-classification report.

Regional model-family `.vec` files can be hundreds of MB each. The dataset
builder prints per-file progress and elapsed timing so a long parse looks like
active work rather than a stalled command. Generated CSV/TXT writers use
same-directory temporary files and atomic replacement where practical to reduce
the risk of half-written artifacts after interrupted runs.

## Publication Metric Guidance

For dissertation/article tables, report the mechanism family together with:

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

Keep these as diagnostics rather than headline claims:

- legacy `missing` / forward-jump fields;
- queue-normalized ratios;
- `zero_progress_windows` and `recovery_time` fields when they are always zero.

Receiver-observed unobserved packet gaps and reordered packets must remain
separate. Reordered packets are transition side effects, not direct packet-loss
proof.

Exact packet loss is available where the final evaluation can pair INET
`packetSent:count` and `packetReceived:count` scalars. The unified Link-Failure
and Degraded-Backup cohorts retain exact monitored UDP `app[0]` accounting and
also export mixed UDP/TCP endpoint diagnostics. The Queue-Buildup cohort adds
exact aggregate sent/received/loss accounting across configured UDP application
flows plus histogram-derived UDP delay percentiles. All UDP delay values are
conditioned on received packets and must be interpreted together with
loss/continuity metrics.

The optional network-impact report adds a separate UDP/QoS view from existing
outputs only:

```bat
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

It does not change AI-MRCE decisions, simulation behavior, dataset/outcome
schemas, or runtime model artifacts. Delivery/loss-like ratios and jitter-like
fields in that report are explicitly labeled as proxies unless exact accounting
is available. TCP impact is reported only as endpoint
received-byte/goodput/progress proxies; TCP RTT, retransmissions, congestion
window, duplicate ACKs, and exact flow-completion time are not claimed unless
the corresponding INET export is explicitly present.

The Queue-Buildup cohort can additionally report TCP stack RTT and
congestion-window scalar summaries when INET exports them. TCP retransmissions
remain unavailable unless the corresponding scalar is present; endpoint
goodput/progress remains the safest transport claim.

The final paper-facing figure set is intentionally compact and currently
contains exactly five core figures under
`analysis/output/final_evaluation/main_figures/`:

- `paper_packet_loss.png`;
- `paper_instrumented_udp_quality.png`;
- `paper_lead_time.png`;
- `paper_protection_family_summary.png`;
- `paper_runtime_feature_importance.png`.

Traceability tables and generated figure manifests remain available under
`analysis/output/final_evaluation/tables/`, but the manuscript narrative should
focus on this five-figure core set.

The shallow-tree policy has been audited in the cost-aware traces. No runtime
artifact loading or feature-mapping bug was found; the deployed tree stayed
negative because its learned split path depends on queue buildup that is absent
in those traces. Treat this as conservative/non-robust policy behavior under
that scenario, not missing data or a runtime failure.

The optional offline ML audit evaluates whether telemetry-v2 runtime-safe
candidate features are suitable for future retraining:

```bat
cmd /c run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

This audit writes separate files under `analysis/output/ml_audit/`. It does not
export runtime model CSVs, alter the deployed AI-MRCE policies, or provide
production-generalization evidence. Runtime export v2 requires a separate
future validation step.

## Degradation-Sensitivity Cohort

A separate modular robustness cohort is available as:

`regionalbackbone_failure_detection_degradation_sensitivity`

This cohort keeps the regional topology, traffic, AI-MRCE thresholds, BFD-like
detector, repair-route semantics, and runtime model artifacts unchanged. It
varies only the progressive degradation profile across:

- `mild_slow`;
- `moderate`;
- `severe_fast`.

The purpose is to test whether AI-MRCE/BFD-like behavior and telemetry-v2
offline ML feasibility remain stable when the brownout severity and ramp timing
vary. It is not a new universal-failure claim and does not replace the validated
model-family core.

Run a run-0 smoke cohort:

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
```

For a full sensitivity cohort, omit `--runs 0`. The full sensitivity matrix is
3 degradation profiles x 7 mechanisms x 5 runs = 105 outcome rows.
Use `--jobs N` here as well when the machine has enough spare CPU/RAM/disk I/O,
for example:

```bat
cmd /c run_experiments.bat regional-degradation-sensitivity-batch --clean --yes --skip-runtime-export --skip-build --jobs 2
```

## Cost-Aware Backup-Path Cohort

A separate compact realism extension is available as:

`regionalbackbone_failure_detection_cost_aware_backup`

This cohort keeps the same seven mechanism families and deployed runtime model
artifacts, but enables a mild persistent data-plane penalty on the southern
repair corridor. The normal primary path remains the lower-cost preferred path.
The backup corridor stays QoS-capable at 100 Mbps and adds about 5 ms total
extra path delay across the five southern repair-corridor hops. The purpose is
to make early repair-route activation non-free and to report benefit/cost
components separately: avoided receiver-observed post-failure gaps, early
backup usage time, transition reordering, and UDP delay/queueing impact.

The first implementation supports three profiles:

- `cost_aware_mild`;
- `cost_aware_moderate`;
- `cost_aware_fast_warning`.

Run a run-0 smoke cohort:

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

For the full cost-aware cohort, omit `--runs 0`; the full matrix is
3 cost-aware profiles x 7 mechanisms x 5 runs = 105 outcome rows. `--jobs N`
is supported, for example:

```bat
cmd /c run_experiments.bat regional-cost-aware-backup-batch --clean --yes --skip-runtime-export --skip-build --jobs 2
```

The cost-aware cohort is now part of the unified mixed UDP/TCP final
experiment. It does not add Deep Learning, runtime model v2 export, or
standards-compliant FRR/BFD behavior, and its TCP results remain endpoint
progress/goodput proxies.
Do not treat the illustrative run-0 smoke output as a publication cohort until
the full five-run matrix is regenerated and `pipeline-integrity` returns `OK`.

## Supplementary Mixed UDP/TCP Transport-Impact Cohort

The retained baseline transport-impact extension is:

`regionalbackbone_failure_detection_cost_aware_transport_impact`

It derives from the cost-aware backup-path design, preserves the UDP monitoring
flow used by AI-MRCE telemetry, and adds a lightweight INET
`TcpBasicClientApp`/`TcpGenericServerApp` request-reply flow over the same
primary/backup routing environment. It is retained for traceability; the final
main networking role is now Scenario C, Congestion/Queue-Buildup Early
Mitigation. TCP results are endpoint-observed
received-byte, goodput, and progress proxies only. The scenario does not claim
TCP RTT, retransmission, congestion-window, or exact finite-flow completion
metrics.

Run a run-0 smoke cohort:

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

For the full transport-impact cohort, omit `--runs 0`; the full matrix is
3 transport profiles x 7 mechanisms x 5 runs = 105 outcome rows. Use `--jobs N`
carefully because transport vectors are larger than earlier compact analysis
artifacts.

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
cmd /c run_analysis.bat clean-final-evaluation --dry-run
cmd /c run_analysis.bat clean-generated --dry-run
cmd /c run_analysis.bat clean-generated --include-results --scenario regionalbackbone_failure_detection_degraded_link_model_family
```

`clean-final-evaluation` only targets generated final-evaluation image files.
Actual broader cleanup requires both `--clean` and `--yes`.

## Public GitHub Portability

Commands are documented relative to the project root. Generated audit and
current-experiment package files may contain absolute local Windows paths
because they record source provenance from the machine that created them.
Public users should regenerate outputs from their own clone path with the
documented OMNeT++/INET and Windows shell workflow.

`analysis/output/README.md` documents the generated-output policy. Generated
outputs remain ignored by default; source, configs, documentation, wrappers,
and runtime model CSV examples remain the intended GitHub-tracked content.

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

- evidence is scenario-conditioned to this deterministic progressive
  degraded-link/brownout cohort;
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
- broad stochastic statistical significance beyond the controlled five-run
  reproducibility/coverage cohort.

See `analysis/AIMRCE_METHODOLOGY.md` and `analysis/WORKFLOW.md` for the detailed
methodology and workflow.
