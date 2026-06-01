# Dissertation Simulation Controllers

This folder contains project-local OMNeT++ simple modules used by the
regionalbackbone AI-MRCE experiments.

## Controllers

- `AiMrceController.*`: observes runtime telemetry, computes rule-based or
  deployed CSV-model risk decisions, applies the configured consecutive-positive
  streak rule, and installs project-local repair routes when protection is
  triggered.
- `LinkDegradationController.*`: applies the configured degraded-link/brownout
  impairment profile and hard-failure behavior used by the scenario cohorts.
- `InterfaceWithdrawController.*`: support controller for interface/failure
  handling in retained regionalbackbone configs.

## Runtime Model Artifacts

The deployed runtime model CSVs live under
`simulations/regionalbackbone/aimrce_runtime_*.csv`. They are intentionally
source-controlled examples and are not changed by reporting scripts. Offline ML
audits do not automatically export runtime v2 models.

## Wording Guardrails

- `bfd_like_frr` is project-local BFD-like behavior, not RFC-compliant BFD.
- FRR-like repair routes are static project-local abstractions, not
  standards-compliant LFA/TI-LFA/RSVP-TE/OSPF FRR.
- AI-MRCE policies are simulator decision policies for the tested scenarios,
  not universal production failure predictors.
- Controller changes can alter scientific behavior; reporting/documentation
  tasks should not edit these files unless a real behavior bug is explicitly
  confirmed.
