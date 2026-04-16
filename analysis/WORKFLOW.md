# Dissertation Workflow

This document describes the current experiment workflow for the OMNeT++ / INET dissertation project.

For the scenario tiering and next topology plan, see `analysis/EXPERIMENT_ARCHITECTURE.md`.

## Scenario Tiers

### Core active data-generation scenarios
- `simulations/linkdegradation`
  - Purpose: synthetic pre-failure degradation using controlled delay and packet-error-rate ramps.
  - Main configs: `MildLinear`, `StrongLinear`, `UnstableLinear`, `StagedRealistic`
  - Debug config: `UnstableLinearDebug`
- `simulations/congestiondegradation`
  - Purpose: traffic-driven congestion on a primary-path bottleneck with a later hard failure.
  - Main configs: `CongestionDegradation`, `CongestionDegradationMild`
  - Debug config: `CongestionDegradationDebug`
- `simulations/regionalbackbone`
  - Purpose: medium-scale OSPF backbone family for baseline routing, reactive failure, controlled pre-failure degradation, and congestion-driven degradation.
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
  - Used by `proactiveswitch`
- `src/dissertationsim/controller/LinkDegradationController.*`
  - Used by `linkdegradation` and `regionalbackbone`

## Current Research Workflow

### 1. Build the project
- Build the local dissertation project binary from the project root.
- Do not modify INET; it is treated as an external dependency.

### 2. Run simulation scenarios
- Use the config names from the scenario-local `omnetpp.ini` files.
- Results are written into the shared top-level `results/<scenario>/` layout.
- For dataset-generating batches, prepare the eval directory before running configs:

```powershell
py -3 analysis\prepare_batch.py --scenario <scenario> --clean
```

- The command above is a dry run. Add `--yes` only after checking the listed eval files:

```powershell
py -3 analysis\prepare_batch.py --scenario <scenario> --clean --yes
```

- The helper only cleans `results/<scenario>/eval/`; it does not touch `debug/`.

### 3. Generate a dataset
- Current dataset generation is standardized for `linkdegradation`, `congestiondegradation`, and `regionalbackbone`.
- Build the synthetic degradation dataset with:

```powershell
py -3 analysis\build_dataset.py --scenario linkdegradation
```

- Build the traffic-driven congestion dataset with:

```powershell
py -3 analysis\build_dataset.py --scenario congestiondegradation
```

- Build the medium-scale regional backbone dataset with:

```powershell
py -3 analysis\build_dataset.py --scenario regionalbackbone
```

### 4. Generate a dataset sanity report
- Produce the synthetic degradation report with:

```powershell
py -3 analysis\dataset_report.py --scenario linkdegradation
```

- Produce the traffic-driven congestion report with:

```powershell
py -3 analysis\dataset_report.py --scenario congestiondegradation
```

- Produce the medium-scale regional backbone report with:

```powershell
py -3 analysis\dataset_report.py --scenario regionalbackbone
```

### 5. Later model training
- Training is intentionally out of scope for the current step.
- The next layer should consume `analysis/output/<scenario>_dataset.csv` rather than reading `.vec` files directly.

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

## Batch Workflow

Use a batch when you want a clean dataset from a known set of configs.

### Prepare a batch
- Decide the scenario and configs before running anything.
- Clean only the matching eval directory when starting a fresh dataset batch.
- Do not clean `debug/`; debug outputs are for inspection and should stay separate from eval.
- Use the helper to show the intended configs and current eval files:

```powershell
py -3 analysis\prepare_batch.py --scenario congestiondegradation
```

- Dry-run cleanup:

```powershell
py -3 analysis\prepare_batch.py --scenario congestiondegradation --clean
```

- Actual cleanup:

```powershell
py -3 analysis\prepare_batch.py --scenario congestiondegradation --clean --yes
```

- Regional backbone batch preparation uses the same helper:

```powershell
py -3 analysis\prepare_batch.py --scenario regionalbackbone
py -3 analysis\prepare_batch.py --scenario regionalbackbone --clean
py -3 analysis\prepare_batch.py --scenario regionalbackbone --clean --yes
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
- `analysis/WORKFLOW.md`
- build/project metadata that is part of the shared workflow

Should not usually be committed:
- `out/`
- `results/`
- `analysis/output/`
- generated binaries and local QtEnv state

## Current Scope Limit

The standardized dataset/report pipeline is currently implemented for:
- `linkdegradation`
- `congestiondegradation`
- `regionalbackbone`

The older small-topology baseline, reactivefailure, and proactiveswitch scenarios remain reference/validation branches and do not have dedicated dataset/report presets.
