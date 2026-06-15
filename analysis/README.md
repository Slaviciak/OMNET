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
cmd /c run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
cmd /c run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
```

Use `run_experiments.bat` for OMNeT++ cohort execution. Use `--runs 0` for a
smoke pass and omit `--runs` only when intentionally running the full five-run
cohort.

## Script Groups

### Core Reproducibility Pipeline

- `core/build_dataset.py`: builds baseline and optional extended telemetry datasets
  from existing OMNeT++ outputs.
- `core/dataset_report.py`: summarizes generated datasets, feature groups,
  missingness, and extended telemetry classification.
- `core/compare_outcomes.py`: builds outcome comparison, headline, and summary
  tables for scenario outputs.
- `core/network_impact_report.py`: creates UDP/QoS, backup-cost, mixed transport
  endpoint proxy, and targeted INET telemetry summaries from existing outputs.
- `core/evaluate_results.py`: builds the final publication-oriented evaluation
  report, final tables, clean current figures, and figure manifest.
- `core/pipeline_integrity.py`: validates expected scenario row counts, mechanism
  coverage, runtime artifact status, and package readiness.
- `core/package_current_experiment.py`: copies compact scenario artifacts into
  `analysis/output/current_experiment/<scenario>/`.

### ML Support

- `ml/train_risk_model.py`: offline research-model training support; it does not
  silently change deployed runtime artifacts.
- `ml/export_runtime_models.py`: exports explicit runtime CSV model artifacts
  when the training/export workflow is intentionally refreshed.
- `ml/offline_ml_audit.py`: performs telemetry-v2 feature-quality and ML
  feasibility audits without exporting runtime models.

### Diagnostics And Cleanup

- `diagnostics/activation_root_cause.py`: explains AI-MRCE activation timing from traces
  and deployed runtime artifacts.
- `diagnostics/extract_aimrce_risk_trace.py`: focused trace extractor for AI-MRCE
  risk/action timelines.
- `diagnostics/clean_generated.py`: dry-run-first generated-output cleanup helper.

The cleanup audit in `analysis/output/audit/` records why every remaining
script is kept. User-facing commands should go through `run_analysis.bat`
rather than direct script paths, so this internal grouping stays reviewer
readable without changing normal reproduction commands.

## Output Policy

Generated artifacts go under `analysis/output/`, which is ignored by Git by
default. Keep source/config/runtime model CSV files under version control; keep
large raw results and generated reports out of normal commits unless a review
requires a compact package or final report snapshot.

## Scientific Wording

- `bfd_like_frr` is a project-local BFD-like comparator, not RFC-compliant BFD.
- FRR-like repair routes are static project-local abstractions, not
  standards-compliant LFA/TI-LFA/RSVP-TE/OSPF FRR.
- Exact UDP packet loss is reported where sent/received scalar accounting is
  available: monitored UDP app[0] for Scenario A/B cohorts, and aggregate
  configured UDP app flows for Scenario C, Congestion/Queue-Buildup Early
  Mitigation.
- UDP delay percentiles are histogram approximations over received packets.
- TCP metrics in unified mixed UDP/TCP cohorts are endpoint
  received-byte/goodput/progress proxies only.
- Recovery time is a receiver-observed recovery/disruption proxy.
