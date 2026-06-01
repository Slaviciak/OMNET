# Analysis Tooling

This directory contains the Python and PowerShell analysis pipeline for the
regionalbackbone AI-MRCE dissertation scenarios. The scripts are reporting,
dataset, validation, packaging, or diagnostic tools; they do not change
simulation behavior unless explicitly used by an experiment wrapper to run
OMNeT++.

## Main Commands

Run commands from the project root through `run_analysis.bat`:

```bat
cmd /c run_analysis.bat help
cmd /c run_analysis.bat evaluate-results
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
```

Use `run_experiments.bat` for OMNeT++ cohort execution. Use `--runs 0` for a
smoke pass and omit `--runs` only when intentionally running the full five-run
cohort.

## Active Scripts

- `build_dataset.py`: builds baseline and optional extended telemetry datasets
  from existing OMNeT++ outputs.
- `dataset_report.py`: summarizes generated datasets, feature groups,
  missingness, and extended telemetry classification.
- `compare_outcomes.py`: builds outcome comparison, headline, and summary
  tables for scenario outputs.
- `network_impact_report.py`: creates UDP/QoS, backup-cost, and mixed
  transport endpoint proxy summaries from existing outputs. For the
  instrumented transport-impact scenario, it also extracts targeted INET
  scalar/histogram metrics such as aggregate UDP sent/received/loss counts,
  UDP delay percentiles, TCP endpoint goodput, TCP RTT/cwnd summaries where
  exported, and queue drop/queueing summaries where present.
- `offline_ml_audit.py`: performs offline feature-quality and ML feasibility
  audits without exporting runtime models.
- `activation_root_cause.py`: explains AI-MRCE activation timing from traces
  and deployed runtime artifacts.
- `evaluate_results.py`: builds the final publication-oriented evaluation
  report, final tables, clean current figures, and figure manifest.
- `pipeline_integrity.py`: validates expected scenario row counts, mechanism
  coverage, runtime artifact status, and package readiness.
- `package_current_experiment.py`: copies compact scenario artifacts into
  `analysis/output/current_experiment/<scenario>/`.
- `clean_generated.py`: dry-run-first generated-output cleanup helper.
- `train_risk_model.py`: support script for training research models; not used
  to silently change deployed runtime artifacts.
- `export_runtime_models.py`: support script for exporting explicit runtime
  CSV model artifacts.
- `extract_aimrce_risk_trace.py`: focused trace extractor for AI-MRCE
  risk/action timelines.

## Output Policy

Generated artifacts go under `analysis/output/`, which is ignored by Git by
default. Keep source/config/runtime model CSV files under version control; keep
large raw results and generated reports out of normal commits unless a review
requires a compact package or final report snapshot.

## Scientific Wording

- `bfd_like_frr` is a project-local BFD-like comparator, not RFC-compliant BFD.
- FRR-like repair routes are static project-local abstractions, not
  standards-compliant LFA/TI-LFA/RSVP-TE/OSPF FRR.
- Exact UDP packet loss is reported only for monitored UDP app[0] when
  sent/received scalar accounting is available.
- The instrumented transport-impact scenario reports exact aggregate UDP
  sent/received/loss across all configured UDP app flows when those scalars are
  present; delay percentiles are histogram approximations over received packets.
- TCP metrics are endpoint received-byte/goodput/progress proxies only.
- Recovery time is a receiver-observed recovery/disruption proxy.
