# Dissertation Workflow

This document describes the current experiment workflow for the OMNeT++ / INET dissertation project.

## Active Scenarios

### Core routing scenarios
- `simulations/dualpathbaseline`
  - Purpose: stable dual-path OSPF baseline with a preferred primary path and a higher-cost backup path.
  - Main configs: `Baseline`, `BaselineDebug`
- `simulations/reactivefailure`
  - Purpose: primary-link hard failure at `20s`, followed by OSPF reconvergence.
  - Main configs: `ReactiveFailure`, `ReactiveFailureDebug`
- `simulations/proactiveswitch`
  - Purpose: administrative withdrawal of the primary path before the hard failure.
  - Main configs: `ProactiveSwitch`, `ProactiveSwitchDebug`

### Data-generation scenarios
- `simulations/linkdegradation`
  - Purpose: synthetic pre-failure degradation using controlled delay and packet-error-rate ramps.
  - Main configs: `MildLinear`, `StrongLinear`, `UnstableLinear`
  - Debug config: `UnstableLinearDebug`
- `simulations/congestiondegradation`
  - Purpose: traffic-driven congestion on a primary-path bottleneck with a later hard failure.
  - Main configs: `CongestionDegradation`, `CongestionDegradationDebug`

### Reusable custom modules
- `src/dissertationsim/controller/InterfaceWithdrawController.*`
  - Used by `proactiveswitch`
- `src/dissertationsim/controller/LinkDegradationController.*`
  - Used by `linkdegradation`

## Current Research Workflow

### 1. Build the project
- Build the local dissertation project binary from the project root.
- Do not modify INET; it is treated as an external dependency.

### 2. Run simulation scenarios
- Use the config names from the scenario-local `omnetpp.ini` files.
- Results are written into the shared top-level `results/<scenario>/` layout.

### 3. Generate a dataset
- Current dataset generation is standardized for `linkdegradation` and `congestiondegradation`.
- Build the synthetic degradation dataset with:

```powershell
py -3 analysis\build_dataset.py --scenario linkdegradation
```

- Build the traffic-driven congestion dataset with:

```powershell
py -3 analysis\build_dataset.py --scenario congestiondegradation
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

### Additional traffic-driven data generation
- Congestion dataset generation:
  - `CongestionDegradation`

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

### Analysis outputs
- Datasets:
  - `analysis/output/<scenario>_dataset.csv`
- Reports:
  - `analysis/output/<scenario>_report.txt`
- Helper summaries:
  - `analysis/output/<scenario>_missing_values.csv`
  - `analysis/output/<scenario>_per_config_summary.csv`

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
- Confirm eventlog is disabled unless a debug run is intentional.
- Confirm the simulation timeline and failure time match the experiment notes.

After a run:
- Check that `.sca` and `.vec` files were written under the expected `results/<scenario>/eval/` folder.
- For rerouting scenarios, verify the path behavior around the failure or switch time.
- For degradation scenarios, verify the expected pre-failure telemetry appears in vectors.

Before dataset export:
- Confirm the required configs have been run.
- Confirm the current dataset builder supports the target scenario.
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

The baseline, reactivefailure, and proactiveswitch scenarios do not yet have dedicated dataset/report presets.
