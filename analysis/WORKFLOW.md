# Dissertation Workflow

This document describes the current experiment workflow for the OMNeT++ / INET dissertation project.

For the scenario tiering and next topology plan, see `analysis/EXPERIMENT_ARCHITECTURE.md`.

## Scenario Tiers

### Core active data-generation scenarios
- `simulations/linkdegradation`
  - Purpose: controlled synthetic degradation proxy using deterministic delay and packet-error-rate ramps.
  - Main configs: `MildLinear`, `StrongLinear`, `UnstableLinear`, `StagedRealistic`
  - Debug config: `UnstableLinearDebug`
- `simulations/congestiondegradation`
  - Purpose: traffic-driven congestion approximation on a primary-path bottleneck with a later hard failure.
  - Main configs: `CongestionDegradation`, `CongestionDegradationMild`
  - Debug config: `CongestionDegradationDebug`
- `simulations/regionalbackbone`
  - Purpose: medium-scale OSPF backbone family for baseline routing, reactive failure, controlled synthetic degradation proxy experiments, traffic-driven congestion approximation, and the first AI-MRCE runtime prototype.
  - Main configs: `RegionalBackboneBaseline`, `RegionalBackboneReactiveFailure`, `RegionalBackboneControlledDegradation`, `RegionalBackboneCongestionDegradation`
  - Debug configs: `RegionalBackboneBaselineDebug`, `RegionalBackboneReactiveFailureDebug`, `RegionalBackboneControlledDegradationDebug`, `RegionalBackboneCongestionDegradationDebug`

### Auxiliary / transitional scenarios
- `simulations/dualpathbaseline`
  - Purpose: stable dual-path OSPF baseline with a preferred primary path and a higher-cost backup path.
  - Main configs: `Baseline`, `BaselineDebug`
  - Status: keep stable as a sanity reference; do not actively extend.
- `simulations/reactivefailure`
  - Purpose: primary-link hard failure at `20s`, followed by OSPF reconvergence.
  - Main configs: `ReactiveFailure`, `ReactiveFailureDebug`
  - Status: keep stable as the reactive rerouting reference.
- `simulations/proactiveswitch`
  - Purpose: administrative withdrawal of the primary path before the hard failure.
  - Main configs: `ProactiveSwitch`, `ProactiveSwitchDebug`
  - Status: keep stable as the first protective-reroute prototype.

### Archival / reference-only scenarios
- `simulations/simpletest`
  - Purpose: original INET OSPF reference material.
  - Main configs: `AlwaysUp`, `ShutdownAndRestart`, `CrashAndReboot`
  - Status: keep as reference-only; do not include in active batches or datasets.

### Reusable custom modules
- `src/dissertationsim/controller/InterfaceWithdrawController.*`
  - Used by `proactiveswitch` and other scheduled administrative-withdrawal experiments
- `src/dissertationsim/controller/LinkDegradationController.*`
  - Used by `linkdegradation` and `regionalbackbone` controlled synthetic degradation proxy configs
- `src/dissertationsim/controller/AiMrceController.*`
  - Used by the first AI-MRCE runtime prototype configs in `regionalbackbone`

## Current Research Workflow

### 1. Build the project
- Build the local dissertation project binary from the project root.
- Do not modify INET; it is treated as an external dependency.

### Python environment
- The standard local Python environment for this project is `analysis/sklearn-env`.
- Keep the existing analysis scripts where they are; the wrapper only standardizes how they are invoked.
- The recommended day-to-day entrypoint from the project root is:

```powershell
run_analysis.bat <command> [arguments...]
```

- The wrapper prefers `analysis/sklearn-env` and falls back to `py -3` only when that environment does not exist yet.
- Backward-compatible direct commands like `py -3 analysis\build_dataset.py ...` still work, but the wrapper is now the recommended default.
- Prepare the local analysis environment with:

```powershell
run_analysis.bat setup-env
run_analysis.bat install-ml-deps
```

### 2. Run simulation scenarios
- Use the config names from the scenario-local `omnetpp.ini` files.
- Results are written into the shared top-level `results/<scenario>/` layout.
- For dataset-generating batches, prepare the eval directory before running configs:

```powershell
run_analysis.bat prepare-batch --scenario <scenario> --clean
```

- The command above is a dry run. Add `--yes` only after checking the listed eval files:

```powershell
run_analysis.bat prepare-batch --scenario <scenario> --clean --yes
```

- The helper only cleans `results/<scenario>/eval/`; it does not touch `debug/`.

### 3. Generate a dataset
- Current dataset generation is standardized for `linkdegradation`, `congestiondegradation`, and `regionalbackbone`.
- Build the synthetic degradation dataset with:

```powershell
run_analysis.bat build-dataset --scenario linkdegradation
```

- Build the traffic-driven congestion dataset with:

```powershell
run_analysis.bat build-dataset --scenario congestiondegradation
```

- Build the medium-scale regional backbone dataset with:

```powershell
run_analysis.bat build-dataset --scenario regionalbackbone
```

### 4. Generate a dataset sanity report
- Produce the synthetic degradation report with:

```powershell
run_analysis.bat dataset-report --scenario linkdegradation
```

- Produce the traffic-driven congestion report with:

```powershell
run_analysis.bat dataset-report --scenario congestiondegradation
```

- Produce the medium-scale regional backbone report with:

```powershell
run_analysis.bat dataset-report --scenario regionalbackbone
```

### 5. Offline risk-model training
- Offline training consumes `analysis/output/<scenario>_dataset.csv`; it should not read `.vec` files directly.
- The first trainer maps scenario-specific labels into the shared risk taxonomy: `safe`, `warning`, `protect`, `failed`.
- These labels are scenario-phase supervision labels derived from the experiment design; they are not measured ground-truth failure-onset annotations.
- Run the first offline risk-model pipeline with:

```powershell
run_analysis.bat train-risk-model --scenarios linkdegradation congestiondegradation regionalbackbone
```

- If one dataset has not been generated yet, either generate it first or use `--allow-missing` for a partial local check.
- The default training command now runs:
  - an optimistic random window split baseline
  - a grouped holdout split that keeps `config_name + run_number` groups intact
  - leave-one-config-out evaluation
  - small-topology to regional and regional to small transfer evaluations
- Treat grouped and transfer-style results as the main generalization evidence. Treat the random split only as a leakage-prone baseline reference.
- This is still offline analysis only; do not integrate it into OMNeT++ runtime behavior yet.

### 6. Export the first AI-MRCE runtime logistic model
- The first runtime AI-MRCE prototype is currently scoped to the `regionalbackbone` congestion branch.
- Export the runtime logistic model with:

```powershell
run_analysis.bat export-runtime-logreg --configs RegionalBackboneCongestionDegradation
```

- This writes `simulations/regionalbackbone/aimrce_runtime_logreg.csv`.
- The export helper trains on the selected rows using scenario-phase supervision and excludes `failed` rows so the runtime score targets the pre-failure `protect` phase rather than post-failure behavior.
- Use the separate evaluation outputs from `train-risk-model` for methodological claims. The runtime export is a deployment artifact, not an evaluation substitute.

### 7. Run the first AI-MRCE regional prototype
- Rule-based baseline:
  - `RegionalBackboneAiMrceRuleBased`
- Logistic-regression runtime model:
  - `RegionalBackboneAiMrceLogReg`
- Run those configs from `simulations/regionalbackbone/omnetpp.ini` using the same OMNeT++ launcher flow you already use for the other regional backbone configs.
- These configs monitor the preferred `coreNW <-> coreNE` corridor and, after sustained positive decisions, administratively withdraw the protected span before the scripted hard failure.
- The protective action is a conservative project-local control step that relies on ordinary administrative interface-down semantics rather than deep OSPF internal modification.
- This is the first runtime AI-MRCE prototype only. It does not yet alter OSPF internals or implement a richer protection-state machine.

## Required Config Runs

### Routing comparisons
- Baseline:
  - `Baseline`
- Reactive rerouting:
  - `ReactiveFailure`
- Proactive rerouting:
  - `ProactiveSwitch`

### Current dataset pipeline
- Synthetic degradation dataset generation:
  - `MildLinear`
  - `StrongLinear`
  - `UnstableLinear`
  - `StagedRealistic`

### Additional traffic-driven data generation
- Congestion dataset generation:
  - `CongestionDegradation`
  - `CongestionDegradationMild`

### Medium-scale regional backbone workflow
- Regional backbone dataset generation:
  - `RegionalBackboneBaseline`
  - `RegionalBackboneReactiveFailure`
  - `RegionalBackboneControlledDegradation`
  - `RegionalBackboneCongestionDegradation`

### Auxiliary validation runs
- Minimal baseline validation:
  - `Baseline`
- Minimal reactive rerouting validation:
  - `ReactiveFailure`
- Minimal proactive rerouting validation:
  - `ProactiveSwitch`

Debug configs should be used only when sequence-chart or event-level inspection is needed.

## Expected Output Locations

### Simulation outputs
- `results/dualpathbaseline/eval/`
- `results/dualpathbaseline/debug/`
- `results/reactivefailure/eval/`
- `results/reactivefailure/debug/`
- `results/proactiveswitch/eval/`
- `results/proactiveswitch/debug/`
- `results/linkdegradation/eval/`
- `results/linkdegradation/debug/`
- `results/congestiondegradation/eval/`
- `results/congestiondegradation/debug/`
- `results/regionalbackbone/eval/`
- `results/regionalbackbone/debug/`

### Analysis outputs
- Datasets:
  - `analysis/output/<scenario>_dataset.csv`
- Reports:
  - `analysis/output/<scenario>_report.txt`
- Helper summaries:
  - `analysis/output/<scenario>_missing_values.csv`
  - `analysis/output/<scenario>_per_config_summary.csv`
- Offline model artifacts:
  - `analysis/output/risk_model_report.txt`
  - `analysis/output/risk_model_class_distribution.csv`
  - `analysis/output/risk_model_split_summary.csv`
  - `analysis/output/risk_model_evaluation_summary.csv`
  - `analysis/output/risk_model_confusion_matrix.csv`
  - `analysis/output/risk_model_feature_importance.csv`
  - `analysis/output/risk_model_per_class_metrics.csv`
- Runtime model artifact:
  - `simulations/regionalbackbone/aimrce_runtime_logreg.csv`

## Batch Workflow

Use a batch when you want a clean dataset from a known set of configs.

### Prepare a batch
- Decide the scenario and configs before running anything.
- Clean only the matching eval directory when starting a fresh dataset batch.
- Do not clean `debug/`; debug outputs are for inspection and should stay separate from eval.
- Use the helper to show the intended configs and current eval files:

```powershell
run_analysis.bat prepare-batch --scenario congestiondegradation
```

- Dry-run cleanup:

```powershell
run_analysis.bat prepare-batch --scenario congestiondegradation --clean
```

- Actual cleanup:

```powershell
run_analysis.bat prepare-batch --scenario congestiondegradation --clean --yes
```

- Regional backbone batch preparation uses the same helper:

```powershell
run_analysis.bat prepare-batch --scenario regionalbackbone
run_analysis.bat prepare-batch --scenario regionalbackbone --clean
run_analysis.bat prepare-batch --scenario regionalbackbone --clean --yes
```

### Run the batch
- Run only the listed eval configs for the selected scenario.
- Do not run debug configs into `eval/`.
- Rebuild the C++ project only when source files, NED module definitions, or build metadata changed.
- No rebuild is normally needed for `omnetpp.ini`, README, or analysis-only changes.

### Export and report
- Build the dataset only after all required eval configs have completed.
- Then generate the report from the freshly built dataset.
- Inspect row counts per config and run number before using the dataset for modeling.
- The wrapper keeps the working directory at the project root so the existing script paths continue to behave exactly as before.

### Offline training
- Run offline training only after the relevant datasets and reports have been regenerated and sanity-checked.
- Exclude generated model reports and CSV artifacts from git; they live under `analysis/output/`.
- Treat the first model as a baseline for later inference design, not as online routing logic.
- Use the grouped and transfer evaluation outputs when discussing methodological strength. Do not rely on the random split alone for generalization claims.
- Install or refresh the ML dependency set with `run_analysis.bat install-ml-deps`.

## Naming Convention

Use scenario-based names for generated analysis artifacts:
- dataset: `analysis/output/<scenario>_dataset.csv`
- report: `analysis/output/<scenario>_report.txt`
- missing summary: `analysis/output/<scenario>_missing_values.csv`
- per-config summary: `analysis/output/<scenario>_per_config_summary.csv`

Examples:
- `analysis/output/linkdegradation_dataset.csv`
- `analysis/output/linkdegradation_report.txt`

## Experiment Checklist

Before a run:
- Confirm the intended scenario and config name.
- Confirm the result directory matches the scenario.
- For a fresh dataset batch, clean `results/<scenario>/eval/` before running configs.
- Confirm eventlog is disabled unless a debug run is intentional.
- Confirm the simulation timeline and failure time match the experiment notes.

After a run:
- Check that `.sca` and `.vec` files were written under the expected `results/<scenario>/eval/` folder.
- For rerouting scenarios, verify the path behavior around the failure or switch time.
- For degradation scenarios, verify the expected pre-failure telemetry appears in vectors.

Before dataset export:
- Confirm the required configs have been run.
- Confirm the current dataset builder supports the target scenario.
- Confirm `eval/` does not contain stale `.vec` files from older runs.
- Keep raw results intact until the dataset and report are verified.

Before committing:
- Review only source/config/documentation changes.
- Do not commit generated outputs from `out/`, `results/`, or `analysis/output/`.

## Git Guidance

Should usually be committed:
- `src/`
- `simulations/`
- `analysis/*.py`
- `analysis/*.ps1`
- `analysis/requirements.txt`
- `analysis/WORKFLOW.md`
- `run_analysis.bat`
- build/project metadata that is part of the shared workflow

Should not usually be committed:
- `out/`
- `results/`
- `analysis/output/`
- `analysis/sklearn-env/`
- generated binaries and local QtEnv state

## Current Scope Limit

The standardized dataset/report pipeline is currently implemented for:
- `linkdegradation`
- `congestiondegradation`
- `regionalbackbone`

The offline risk-model training pipeline is implemented in:
- `analysis/train_risk_model.py`

The older small-topology baseline, reactivefailure, and proactiveswitch scenarios remain reference/validation branches and do not have dedicated dataset/report presets.
