# AI-MRCE Methodology Notes

This document summarizes the project-local methodology used by the active
regional backbone experiments. It is intended for dissertation writing, article
preparation, and public-code review. It describes what is implemented and, just
as importantly, what is not claimed.

## Scope

AI-MRCE is modeled as a telemetry-driven controller above an IP routing domain.
The current simulator domain uses INET OSPF in the regional backbone topology.
AI-MRCE observes simulator-side telemetry, evaluates degradation/failure risk
with a rule-based or exported ML runtime policy, and activates project-local
FRR-like repair routes before the scripted hard failure when the risk decision
is sustained.

AI-MRCE is not implemented as a replacement for OSPF. It is also not a
standards-compliant implementation of BFD, LFA, TI-LFA, RSVP-TE FRR, or an
OSPF extension. The implementation is an auditable local-protection abstraction
for comparing trigger timing and receiver-side service outcomes under controlled
degraded-link scenarios.

## Active Dissertation Core

The primary reproducible result block is:

`regionalbackbone_failure_detection_degraded_link_model_family`

It compares:

- `ospf_only`
- `bfd_like_frr`
- `aimrce_rule_based_frr`
- `aimrce_logistic_regression_frr`
- `aimrce_linear_svm_frr`
- `aimrce_shallow_tree_frr`
- `hybrid_bfd_like_aimrce_frr`

The cohort uses the same regional topology, traffic profile, progressive
degraded-link profile, hard-failure time, and repair-route actuator for all
mechanisms. The AI-MRCE model-family variants differ only in the runtime
decision policy.

## Degraded-Link Model

The active degraded-link scenario represents a progressive brownout/failure
class on the protected `coreNW` to `coreNE` span. It is a controlled simulator
approximation of network behavior where packet loss, delay/queue pressure, or
observable degradation increases before a hard outage.

In the current main degraded-link model-family cohort, pre-failure impairment
is applied by `LinkDegradationController` to the protected span before the
separate `ScenarioManager` hard disconnect. The configured high terminal packet
error rate is a severe stress/brownout setting used to make BFD-like
current-impairment detection observable; it is not an operator-calibrated trace
and should not be reported as a typical production-link PER.

The model is intentionally scenario-conditioned. It does not imply that every
network failure has pre-failure symptoms or that AI-MRCE can predict arbitrary
hard failures. Sudden failures with no observable precursor remain outside the
strongest current claim.

## Realism Grounding

The active degradation model is grounded as a conservative simulator-side
approximation, not as an operator-calibrated impairment trace.

- BFD-style detection is represented only by the missed-probe / detect-multiplier
  idea. RFC 5880 defines BFD detection time around negotiated transmit intervals
  and detect multipliers, but this project does not implement BFD session state,
  discriminators, echo mode, authentication, or OSPF/BFD signaling.
- IP fast-reroute literature such as RFC 5714 motivates the general idea of
  locally available repair paths for conventional IP forwarding. The project
  models only a narrow static `/32` repair-route abstraction for the selected
  service endpoints, not standards-compliant LFA/TI-LFA behavior.
- Queue buildup, delay growth, and loss under congestion are consistent with
  the queueing concerns described in IETF AQM guidance. The queue telemetry in
  this project is still a simulator-default backlog approximation rather than a
  calibrated hardware-buffer model.
- Packet delay variation is treated as an observable IP-path symptom in the
  same broad measurement sense as IETF IPPM delay-variation terminology. The
  current controller uses mean probe delay and queue state, while explicit
  jitter or delay-variation features remain future work.
- Gray-failure and ISP gray-failure work motivates the existence of partial
  failures where some traffic sees loss or performance degradation before a
  clean fail-stop event. The staged packet-error-rate and delay profile is a
  deterministic approximation of that class.
- Production link-failure prediction work highlights the value of temporal
  relations and lower-layer indicators such as optical power, errored seconds,
  or unavailable seconds. Those richer indicators are not yet modeled here; the
  current runtime feature set is intentionally compact for a first auditable
  prototype.

Therefore, the current result should be read as evidence for one progressive
degraded-link / brownout class with observable pre-failure symptoms. It should
not be generalized to arbitrary sudden failures, all link technologies, or
all router/node failure modes.

## Runtime Telemetry

The controller and analysis pipeline expose operational telemetry such as:

- bottleneck queue length and bit length;
- receiver-side delay for the monitored probe flow;
- throughput and packet-count proxies for the monitored flow;
- BFD-like logical probe diagnostics in BFD-like and hybrid configs;
- AI-MRCE risk score, threshold, and positive-decision streak;
- protection trigger source and activation time;
- repair-route installation time and route count.

These are simulator-side observables and scripted-event metadata. They are not
protocol-standard restoration measurements.

## Runtime Feature Set

The exported runtime ML policies currently use a compact four-feature set:

- `bottleneck_queue_length_last_pk`;
- `receiver_app0_e2e_delay_mean_s`;
- `receiver_app0_throughput_mean_bps`;
- `receiver_app0_packet_count`.

This feature set is deliberately auditable and observable. It is also limited:
it does not yet include explicit delay trends, jitter/variation, queue growth
rate, estimated packet-error rate, rolling-window deltas, or BFD-like probe-miss
rate. Future model-family work should evaluate those features in a separate
methodology step rather than retuning current thresholds after seeing outcomes.

## Router and Node Degradation Scope

The active result models degradation on a protected link/span plus traffic-driven
queue pressure. It does not currently model router CPU saturation, memory
pressure, forwarding ASIC faults, control-plane overload, interface CRC/error
counters, thermal faults, or line-card failure modes.

Router/node degradation would require a separate scenario design with explicit
observable symptoms, for example forwarding delay, queue drops, interface error
counters, control-plane delay, or node-local resource pressure. Adding that now
would broaden the scientific scope and could blur the current link/brownout
claim, so it should remain future work unless introduced as a clearly separated
cohort with its own baselines and validation.

## Decision and Activation

AI-MRCE computes a `riskScore` once per decision cycle. If the score is above
the configured threshold for `activationConsecutiveCycles`, the controller
activates protection.

The current validated model-family behavior is consistent with the one-second
decision cycle and sustained-positive requirement: several models activate in
the same second even though their risk scores differ, while logistic regression
activates one cycle later in the observed run-0 diagnostics.

## Repair-Route Actuation

The protection action installs explicit static `/32` repair routes over the
configured southern backup corridor. The same project-local repair-route
actuator is used by AI-MRCE-only, BFD-like-only, and hybrid mechanisms.

This is a local FRR-like abstraction. It is not standards-compliant LFA,
TI-LFA, RSVP-TE FRR, or an OSPF protocol modification. It is intentionally
narrow: the routes protect the selected host-to-host service endpoints rather
than rewriting the whole routing domain.

The current implementation is not seamless make-before-break. Activation can
cause receiver-observed packet reordering because newer packets on the faster
repair path may overtake older packets delayed in the congested primary path.
That transition side effect must remain visible in reports.

## BFD-Like Comparator

The BFD-like branch is a project-local fast reactive detector. It uses a
detection-interval and detect-multiplier style configuration and, in degraded
link variants, logical probe checks exposed to the current modeled packet-loss
state. It is intended to represent a fast reactive safety-net baseline, not a
full RFC BFD session implementation.

The degraded-link result shows why this distinction matters: BFD-like can
activate before the hard outage when modeled probe loss becomes severe, but it
is still reactive and late relative to AI-MRCE in the progressive brownout
profile.

## Outcome Metrics

The main outcome metrics are receiver-side and operational:

- `protection_activated_before_failure`;
- `protection_lead_time_before_failure_s`;
- `activation_queue_length_pk`;
- `activation_risk_score`;
- `packet_sequence_gap_total_unobserved_after_hard_failure`;
- `packet_sequence_gap_total_unobserved_between_activation_and_failure`;
- `packet_sequence_gap_total_reordered_between_activation_and_failure`;
- service interruption and recovery-window proxies;
- BFD-like detection timing and modeled loss at detection.

Legacy `packet_sequence_gap_total_missing_*` fields are retained for backward
compatibility as forward-jump continuity estimates. They must not be described
as direct packet loss without checking the corresponding `unobserved` and
`reordered` metrics.

## Diagnostic Artifacts

The model-family pipeline can generate:

- risk/action traces under `analysis/output/debug/`;
- model-action event summaries under `analysis/output/debug/`;
- headline summaries under `analysis/output/outcomes/`;
- a pipeline-integrity report under `analysis/output/debug/`.

These files are generated artifacts and should not be committed.

## Supported Claims

The current degraded-link model-family result can support conservative claims
such as:

- under this progressive degraded-link/brownout profile, AI-MRCE variants
  activated earlier than the BFD-like reactive detector;
- AI-MRCE variants eliminated post-hard-failure unobserved packet gaps in the
  observed cohort;
- the BFD-like detector served as a late reactive safety net when modeled probe
  loss became severe;
- the hybrid triggered AI-MRCE first in this profile;
- repair-route activation still introduced packet reordering, so the mechanism
  is not seamless.

## Unsupported Claims

Do not claim:

- universal network-failure prediction;
- standards-compliant BFD, LFA, TI-LFA, RSVP-TE FRR, or OSPF extension behavior;
- seamless make-before-break protection;
- generalization to all traffic mixes, topologies, or failure classes;
- statistical significance beyond the current run count and scenario design.
