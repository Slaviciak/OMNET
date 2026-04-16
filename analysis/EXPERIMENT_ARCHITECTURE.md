# Experiment Architecture

This note defines the current active experiment architecture and the proposed next topology step.

The goal is to keep the project defensible as a research workflow, not just as a set of runnable simulations.

## Current Scenario Classification

### Core active scenarios
- `simulations/linkdegradation`
  - Role: controlled synthetic data-generation branch.
  - Purpose: produce interpretable pre-failure telemetry from deterministic delay and packet-error-rate profiles.
  - Current configs: `MildLinear`, `StrongLinear`, `UnstableLinear`, `StagedRealistic`.
  - Status: actively maintained for dataset/report generation.
- `simulations/congestiondegradation`
  - Role: traffic-driven data-generation branch.
  - Purpose: produce pre-failure telemetry from offered-load pressure and bottleneck queue buildup.
  - Current configs: `CongestionDegradation`, `CongestionDegradationMild`.
  - Status: actively maintained for dataset/report generation.

### Auxiliary / transitional scenarios
- `simulations/dualpathbaseline`
  - Role: minimal OSPF sanity baseline.
  - Purpose: verify the preferred primary path and backup path on the smallest topology.
  - Status: keep stable; do not actively extend unless needed for validation.
- `simulations/reactivefailure`
  - Role: minimal reactive rerouting reference.
  - Purpose: verify OSPF reconvergence after hard failure in the small topology.
  - Status: keep stable; use as a comparison reference, not as the main data-generation branch.
- `simulations/proactiveswitch`
  - Role: first protective-reroute prototype.
  - Purpose: demonstrate administrative withdrawal before hard failure using a small local controller.
  - Status: keep stable; avoid expanding the controller until the medium topology research question is fixed.

### Archival / reference-only scenarios
- `simulations/simpletest`
  - Role: original INET OSPF reference material.
  - Purpose: useful for checking INET OSPF behavior and configuration style.
  - Status: keep as reference-only; do not include in active batches, datasets, or dissertation result tables unless explicitly needed.

## Active Research Core

The active dissertation workflow should currently focus on two complementary data-generation branches:

- `linkdegradation`: controlled channel-quality degradation.
- `congestiondegradation`: traffic-driven congestion degradation.

These branches are complementary:

- `linkdegradation` isolates delay and packet-error-rate progression directly on the primary link.
- `congestiondegradation` produces emergent symptoms through traffic pressure, queueing, and delivery effects.

The small routing scenarios remain valuable, but they should support interpretation rather than continue growing independently.

## Medium-Scale Topology Recommendation

### Proposed name
- `regionalbackbone`

This should be designed first and implemented only after reviewing the OSPF costs and experiment hypotheses.

### Target scale
- About 12 routers.
- Two endpoint hosts for the main monitored flow.
- Optional background traffic hosts can be added later only if needed.

### Proposed router roles
- Access routers:
  - `accessA`
  - `accessB`
- West provider-edge / aggregation routers:
  - `west1`
  - `west2`
- East provider-edge / aggregation routers:
  - `east1`
  - `east2`
- Backbone core routers:
  - `coreNW`
  - `coreNE`
  - `coreSW`
  - `coreSE`
  - `coreC1`
  - `coreC2`

### Proposed structure

The topology should resemble a small regional provider backbone with two main corridors and cross-core alternatives:

```text
hostA
  |
accessA
  |\
  | \
west1 west2
  |     |
coreNW coreSW
  | \   | \
  |  \  |  \
coreNE coreSE
  |     |
east1 east2
  \     |
   \    |
   accessB
      |
    hostB
```

Additional backbone cross-links should make the network meaningfully different from the toy dual-path case:

- `coreNW <-> coreNE`: preferred northern corridor.
- `coreSW <-> coreSE`: southern alternative corridor.
- `coreNW <-> coreSW`: west-side vertical interconnect.
- `coreNE <-> coreSE`: east-side vertical interconnect.
- `coreNW <-> coreC1 <-> coreSE`: diagonal alternative.
- `coreSW <-> coreC2 <-> coreNE`: diagonal alternative.

### OSPF cost intent

The first version should use deterministic OSPF costs with a clear preferred path:

- Preferred path: `hostA -> accessA -> west1 -> coreNW -> coreNE -> east1 -> accessB -> hostB`.
- Secondary alternatives:
  - southern corridor via `west2 -> coreSW -> coreSE -> east2`.
  - diagonal alternatives through `coreC1` and `coreC2`.
- Avoid equal-cost multipath at first unless it is intentionally studied.

This makes rerouting behavior easier to interpret because one can identify the primary path, the next-best path, and longer fallback paths.

### Experiment roles

The medium topology should support four experiment families:

- Baseline routing:
  - confirm the preferred path and stable OSPF state.
- Reactive failure:
  - fail a preferred backbone span and observe whether traffic moves to a plausible alternate corridor.
- Controlled degradation:
  - apply staged delay/PER degradation to a preferred backbone span before hard failure.
- Congestion-driven degradation:
  - create offered-load pressure on one preferred backbone span and observe queueing before reroute/failure.

### Candidate monitored links

Good first monitored links:

- `coreNW <-> coreNE`
  - best first choice because it is a central preferred-corridor span.
- `west1 <-> coreNW`
  - useful later for ingress-side degradation.
- `coreNE <-> east1`
  - useful later for egress-side degradation.

Start with `coreNW <-> coreNE` because it is easy to explain and has multiple plausible alternatives.

## Implementation Recommendation

Do not implement `regionalbackbone` in this step.

The safest next step is documentation-only because:

- the current small-topology data branches are still being stabilized;
- OSPF cost choices in a medium topology are research-methodology decisions, not just code details;
- adding NED and ASConfig files too early risks locking in arbitrary path behavior;
- the current dataset builders are scenario-specific and should not be expanded before the topology's labels and metrics are defined.

The next implementation step should be a small scenario skeleton only after this design is accepted:

- `simulations/regionalbackbone/RegionalBackbone.ned`
- `simulations/regionalbackbone/ASConfig.xml`
- `simulations/regionalbackbone/omnetpp.ini`
- `simulations/regionalbackbone/README`

No new C++ controller should be added for the first medium-topology skeleton.

## Hygiene Rules

- Keep `linkdegradation` and `congestiondegradation` as active data branches.
- Keep `dualpathbaseline`, `reactivefailure`, and `proactiveswitch` stable as validation/prototype references.
- Keep `simpletest` as reference-only.
- Do not add new dataset presets for a medium topology until the scenario has a stable metric and label design.
- Do not commit generated outputs from `results/`, `out/`, or `analysis/output/`.
