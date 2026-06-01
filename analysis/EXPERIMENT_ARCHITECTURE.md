# Experiment Architecture

This repository is centered on the regionalbackbone simulation source,
AI-MRCE/FRR-like/BFD-like controllers, runtime model artifacts, and the
analysis pipeline needed to reproduce, validate, trace, package, and evaluate
four current dissertation scenario families:

- `regionalbackbone_failure_detection_degraded_link_model_family`
- `regionalbackbone_failure_detection_degradation_sensitivity`
- `regionalbackbone_failure_detection_cost_aware_backup`
- `regionalbackbone_failure_detection_cost_aware_transport_impact`

The separate instrumentation extension
`regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented`
is an analysis-strengthening derivative of the fourth layer. It is not counted
as a new behavioral claim layer; it preserves the mixed UDP/TCP experiment
semantics while recording richer INET scalar/histogram telemetry.

The old standalone small-topology scenario trees are not part of the current
public workflow. Earlier wrapper compatibility branches are treated as support
code, not advertised publication commands.

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

The optional degradation-sensitivity cohort is separate from this publication
core:

`regionalbackbone_failure_detection_degradation_sensitivity`

It adds three degradation-profile variants, `mild_slow`, `moderate`, and
`severe_fast`, while keeping topology, traffic, AI-MRCE thresholds, BFD-like
logic, repair-route semantics, and runtime model artifacts unchanged. Its
purpose is robustness and telemetry-feasibility analysis, not a replacement for
the validated model-family result.

A second optional extension is the cost-aware backup-path cohort:

`regionalbackbone_failure_detection_cost_aware_backup`

It reuses the regional topology and the same seven mechanism families, but
sets `enableCostAwareBackupPenalty=true` so the southern static repair corridor
uses 100 Mbps links with a small added delay penalty on each repair-corridor
hop. The resulting backup path remains usable and QoS-capable, while early
repair-route activation has measurable opportunity cost. This cohort is the
place to discuss backup usage time, transition reordering, UDP delay/queueing
impact, and avoided receiver-observed post-failure gaps as separate
benefit/cost components.

A fourth realism layer is the mixed UDP/TCP transport-impact cohort:

`regionalbackbone_failure_detection_cost_aware_transport_impact`

It derives from the cost-aware backup-path design and adds a lightweight INET
TCP request-reply application pair alongside the existing UDP monitoring and
staged UDP traffic. This scenario is closest to a deployment-style mixed-traffic
validation layer, but its TCP fields are endpoint-observed received-byte,
goodput, and progress proxies only. It does not claim TCP RTT, retransmission,
congestion-window, or exact finite-flow completion measurements.

The instrumented transport-impact derivative keeps the same profiles,
mechanisms, traffic, thresholds, and repair-route behavior, but writes to the
short isolated raw result folder `results/regionalbackbone/ti_inst/`. Its
recording policy favors compact scalars and histograms over broad packet-level
vectors: exact aggregate UDP sent/received/loss counts across configured UDP
apps, received-packet UDP delay percentiles, TCP endpoint goodput/progress,
TCP RTT/cwnd scalar summaries when INET exports them, and queue drop/queueing
summaries where present. IPDV-like jitter, link-utilization vectors, TCP
duplicate ACKs, and TCP retransmission counts remain future instrumentation
items unless explicitly exported.

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

The learned runtime policies are compact simulator-derived policy variants
trained/exported for this scenario workflow. They are useful for comparing
runtime decision families in the controlled cohort, but they are not presented
as production-grade general predictors.

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
- `analysis/network_impact_report.py`
- `analysis/export_runtime_models.py`
- `analysis/pipeline_integrity.py`
- `analysis/package_current_experiment.py`
- `analysis/clean_generated.py`
- `analysis/activation_root_cause.py`
- `analysis/offline_ml_audit.py`
- `analysis/evaluate_results.py`
- `analysis/run_analysis.ps1`
- `analysis/run_experiments.ps1`

The pipeline reads OMNeT++ `.sca/.vec/.vci` outputs from the active results
folder, produces dataset/report/outcome/comparison artifacts, validates
mechanism/run coverage with pipeline integrity, extracts AI-MRCE risk traces,
generates a separate analysis-only UDP/QoS network-impact report, and builds a
compact current-experiment package for review.

Experiment execution remains wrapper-level and conservative. `run_experiments`
can optionally run independent config/run OMNeT++ processes concurrently with
`--jobs N`; build, runtime export, dataset generation, reports, comparison, and
packaging remain sequential to preserve deterministic artifacts. `--jobs 1`
matches the sequential workflow, and larger values should be chosen carefully
because concurrent `.vec` writes can saturate disk I/O and memory.

The network-impact report reads existing dataset/outcome artifacts. It does
not change simulator behavior, AI-MRCE decisions, BFD-like behavior,
repair-route semantics, existing output schemas, or runtime model artifacts.
Exact UDP packet loss is available only for the monitored UDP `app[0]` flow when
INET `packetSent:count` and `packetReceived:count` scalars are present. Its
delivery/loss-like, delay-variation, and recovery-time fields are otherwise
explicitly conservative proxies where exact accounting, full IPDV calculation,
or direct routing convergence timing is unavailable. The first three cohorts
remain UDP-only; the transport-impact cohort adds TCP endpoint progress/goodput
proxies, not protocol-internal TCP measurements.

Telemetry-v2 candidate features are also generated through
`analysis/build_dataset.py --feature-set extended`, not through a parallel
builder. Extended datasets are separate optional artifacts under
`analysis/output/datasets/*_extended_dataset.csv`. They append candidate
`feat_*`, `phase_*`, `label_*`, `meta_*`, and `id_*` columns derived from real
recorded simulation telemetry and controller diagnostics. They are intended for
future feature validation and ML retraining, while the current runtime export
remains on the compact validated feature set.

## Runtime Telemetry Deployability

The currently deployed AI-MRCE runtime models use only four pre-failure
observable features:

- protected queue length in packets;
- receiver-side active-probe delay mean;
- receiver-side active-probe throughput;
- receiver-side active-probe packet count.

These are simulator measurements, but they map to plausible real telemetry
sources: active path probes, endpoint/application receive counters, SNMP or
streaming telemetry/gNMI queue statistics where available, and controller-side
probe collectors. A real deployment would need adapters, clock/measurement
calibration, and data-quality checks before using those signals in production.

Evaluation metrics and diagnostics are deliberately separated from runtime
inputs. Hard-failure time, lead time, recovery/disruption proxy, post-failure
unobserved gaps, activation-to-failure reordering, repair-route timing,
scenario phase labels, scripted impairment values, and TCP endpoint summaries
are used for evaluation or offline analysis only. They are not fed into the
deployed runtime policy. The telemetry-v2 offline ML audit is therefore a
candidate-feature feasibility study, not a runtime export path.

`analysis/offline_ml_audit.py` is the optional offline feasibility layer for
telemetry v2. It reads the extended dataset and feature-classification report,
selects only runtime-safe candidate inputs, evaluates grouped offline
classifiers, and writes reports under `analysis/output/ml_audit/`. It is not a
runtime export path and does not modify the deployed `aimrce_runtime_*.csv`
artifacts.

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

The optional sensitivity raw result folder is:

`results/regionalbackbone/failure_detection_degradation_sensitivity/`

The optional cost-aware backup raw result folder is:

`results/regionalbackbone/failure_detection_cost_aware_backup/`

The optional mixed UDP/TCP transport-impact raw result folder is:

`results/regionalbackbone/failure_detection_cost_aware_transport_impact/`

The instrumented mixed UDP/TCP raw result folder is:

`results/regionalbackbone/ti_inst/`

The compact review package is:

`analysis/output/current_experiment/regionalbackbone_failure_detection_degraded_link_model_family/`

## Claims And Non-Claims

Allowed claims are scenario-conditioned:

- AI-MRCE activates earlier than the project-local BFD-like comparator in the
  deterministic progressive degraded-link/brownout cohort.
- Hybrid protection is AI-MRCE-first in the current degraded-link profile.
- AI-MRCE removes post-hard-failure unobserved gaps in the validated cohort.
- Repair-route reordering remains visible and must be reported.
- Exact packet loss is reported only for monitored UDP `app[0]` where INET
  sent/received scalar accounting exists.
- Shallow-tree non-activation in cost-aware/transport traces is an audited
  conservative policy outcome, not a runtime loading or feature-mapping bug.

Recommended main-paper figure subset:

- `final_protection_family_packet_loss.png`;
- `final_protection_family_udp_delay.png`;
- `final_protection_family_recovery_time.png`;
- `final_protection_family_reordering.png`;
- `final_protection_family_lead_time.png`;
- `final_protection_family_tcp_goodput_proxy.png`;
- `final_protection_family_summary.png`;
- `ml_feature_importance_cost_aware.png`.

Treat per-scenario consistency figures, offline ML saturation plots, and
diagnostic policy tradeoff figures as supplementary unless the manuscript needs
one of them for a specific subsection.

Non-claims:

- no universal failure prediction;
- no RFC-compliant BFD implementation;
- no standards-compliant LFA, TI-LFA, or FRR implementation;
- no seamless make-before-break guarantee;
- no generalization beyond the current topology, traffic profile, degradation
  class, and run count;
- no broad stochastic statistical significance claim from the controlled
  five-run reproducibility/coverage cohort.
