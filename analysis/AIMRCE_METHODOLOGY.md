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

The five runs in the publication cohort provide reproducibility and workflow
coverage for this controlled model-family experiment. They should not be
interpreted as broad stochastic statistical significance, because the active
degraded-link/brownout profile and controller timing are largely deterministic.

## Degradation-Sensitivity Extension

The optional sensitivity cohort is:

`regionalbackbone_failure_detection_degradation_sensitivity`

It is a modular robustness extension, not a replacement for the validated core.
The cohort varies only the progressive degradation profile while preserving the
same topology, traffic, AI-MRCE decision thresholds, BFD-like detector settings,
FRR-like repair-route semantics, and deployed runtime model CSVs.

The first controlled profiles are:

- `mild_slow`: earlier/slower ramp to a milder terminal impairment;
- `moderate`: intermediate ramp and terminal impairment;
- `severe_fast`: later/faster ramp to the severe terminal impairment level.

The scientific purpose is to check whether activation timing, BFD-like
reactivity, UDP/QoS impact, and offline telemetry-v2 feature usefulness remain
stable under profile variability. The cohort should not be used to tune the
validated thresholds after seeing outcomes, and it does not establish universal
failure-prediction generalization.

## Cost-Aware Backup-Path Extension

The optional cost-aware cohort is:

`regionalbackbone_failure_detection_cost_aware_backup`

It addresses a realism limitation in the older degraded-link experiments: repair
route activation should not be treated as cost-free. The cohort keeps the same
mechanism families and deployed runtime model artifacts, but enables a mild
persistent data-plane penalty on the southern repair corridor. The normal
primary path remains lower-cost and preferred in normal operation. The backup
path remains QoS-capable at 100 Mbps and adds about 5 ms total extra path delay
across the five southern repair-corridor hops.

The first profiles are:

- `cost_aware_mild`: longer warning interval and longer possible early-backup
  exposure;
- `cost_aware_moderate`: balanced warning interval;
- `cost_aware_fast_warning`: short warning interval where reactive detection
  may become more competitive.

This extension is intended to report separate benefit/cost components:

- benefit: avoided receiver-observed post-hard-failure unobserved gaps;
- cost: early backup usage time before hard failure;
- cost: transition reordering after repair-route activation;
- cost: UDP delay/queueing impact after activation.

The current implementation does not claim a universal weighted utility score.
Any illustrative utility proxy should remain secondary to the separate
components above.

## Mixed UDP/TCP Transport-Impact Extension

The optional mixed-traffic cohort is:

`regionalbackbone_failure_detection_cost_aware_transport_impact`

It derives from the cost-aware backup-path design and adds a lightweight INET
`TcpBasicClientApp`/`TcpGenericServerApp` request-reply flow alongside the UDP
monitoring traffic used by AI-MRCE telemetry. This makes the transport-impact
layer closer to deployment-style mixed traffic without changing the deployed
AI-MRCE runtime policies.

TCP fields in this cohort are conservative endpoint-observed proxies:

- received bytes at the TCP application endpoint;
- one-second goodput/progress proxy derived from application packet-byte
  vectors;
- zero-progress/stall proxy windows after the protection or hard-failure
  reference point.

The cohort does not claim TCP RTT, retransmissions, congestion window, or exact
flow-completion time. Those require additional TCP-specific instrumentation or a
separate finite-flow scenario.

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
  idea. [RFC 5880](https://www.rfc-editor.org/rfc/rfc5880.html) defines BFD as
  a protocol for detecting faults in the bidirectional path between forwarding
  engines and uses interval/multiplier concepts, but this project does not
  implement BFD session state, discriminators, echo mode, authentication, or
  OSPF/BFD signaling.
- IP fast-reroute literature such as
  [RFC 5714](https://www.rfc-editor.org/rfc/rfc5714.html) motivates locally
  determined repair paths for conventional IP forwarding. The project models
  only a narrow static `/32` repair-route abstraction for the selected service
  endpoints, not standards-compliant LFA/TI-LFA behavior.
- OSPF context follows the INET routing model and OSPFv2 framing from
  [RFC 2328](https://www.rfc-editor.org/rfc/rfc2328.html). The OSPF-only
  baseline is a no-protection baseline using INET OSPF behavior; it is not
  claimed to be tuned or optimized for fast failure recovery.
- Queue buildup, delay growth, and loss under congestion are consistent with
  the queueing concerns described in IETF AQM guidance such as
  [RFC 7567](https://www.rfc-editor.org/rfc/rfc7567.html). The queue telemetry
  in this project is still a simulator-default backlog approximation rather
  than a calibrated hardware-buffer model.
- Packet delay variation is treated as an observable IP-path symptom in the
  same broad measurement sense as IETF IPPM delay-variation terminology in
  [RFC 5481](https://www.rfc-editor.org/rfc/rfc5481.html). The current
  controller uses mean probe delay and queue state, while explicit jitter or
  delay-variation features remain future work.
- Gray-failure work such as
  [Huang et al., HotOS 2017](https://www.microsoft.com/en-us/research/publication/gray-failure-achilles-heel-cloud-scale-systems/)
  and ISP gray-failure work such as
  [FANcY, SIGCOMM 2022](https://doi.org/10.1145/3544216.3544242) motivate the
  existence of partial failures where some traffic sees loss or performance
  degradation before a clean fail-stop event, including differential
  observability between detectors and affected applications. The staged
  packet-error-rate and delay profile is a deterministic approximation of that
  class.
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

## Runtime Telemetry Deployability

The deployed AI-MRCE runtime feature vector is intended to be plausible for a
future real-network controller. Each deployed feature is observable before the
scripted hard failure:

- `bottleneck_queue_length_last_pk`: protected-span queue occupancy. A real
  system would need router queue telemetry, for example streaming telemetry,
  gNMI, SNMP counters where available, or vendor queue instrumentation.
- `receiver_app0_e2e_delay_mean_s`: receiver-side active-probe delay. A real
  system could approximate this with synthetic UDP probes, TWAMP-like probing,
  application endpoint telemetry, or controller-collected path probes.
- `receiver_app0_throughput_mean_bps`: received active-probe throughput. A real
  system could derive this from probe receiver counters, flow telemetry, or
  endpoint/application logs.
- `receiver_app0_packet_count`: received active-probe packet count in the
  current decision window. A real system could derive this from probe sequence
  counters or endpoint receive logs.

The runtime feature vector does not include hard-failure time, time to failure,
post-failure gaps, recovery time, activation outcome, trigger source, scripted
impairment state, or future labels. Those fields are valid for supervision,
debugging, or evaluation only. They must not be used as live model inputs.

The richer telemetry-v2 columns should be read as feature-candidate research
infrastructure. Delay and throughput trends, queue growth, continuity proxies,
and endpoint TCP progress may be realistic candidates, but each would need a
real collection adapter and leakage review before runtime deployment. Configured
impairment vectors from `LinkDegradationController`, scenario phase labels,
time-to-hard-failure fields, post-event outcome fields, and controller-state
diagnostics are not deployment-ready runtime features.

The telemetry-v2 dataset mode starts that evaluation without changing runtime
behavior. `analysis/build_dataset.py --feature-set extended` appends optional
candidate columns derived from existing recorded simulation telemetry:
delay/throughput deltas, queue growth, continuity proxies, configured
impairment context, BFD-like diagnostic state, and AI-MRCE controller-state
diagnostics. The generated feature-classification report labels each field as a
runtime-safe candidate, offline diagnostic, label/target, metadata, or
leakage-risk field.

This extended dataset is analysis-only. The current runtime controller and
runtime model export still use the compact four-feature set above until a
separate retraining, leakage-review, and regression-validation step is
performed.

The learned policies are compact runtime policy variants trained from
simulator-derived labels and this four-feature set. They are useful for
comparing deployment-time decision families in the controlled cohort, but they
are not production-grade general predictors and should not be claimed to
generalize beyond the scenario and training/export workflow without additional
data, features, and validation.

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

The deployed shallow-tree policy is deliberately reported as a conservative
runtime decision policy in the cost-aware and mixed-transport scenarios. The
activation audit found no runtime-artifact loading failure and no feature-name
mapping bug. Its non-activation occurs because the deployed tree's split path
relies on queue buildup that is absent in the traced cost-aware windows. This is
a model robustness limitation, not evidence that the controller failed to load
or execute the tree artifact.

## Repair-Route Actuation

The protection action installs explicit static `/32` repair routes over the
configured southern backup corridor. The same project-local repair-route
actuator is used by AI-MRCE-only, BFD-like-only, and hybrid mechanisms.

This is a local FRR-like abstraction. It is not standards-compliant LFA,
TI-LFA, RSVP-TE FRR, or an OSPF protocol modification. It is intentionally
narrow: the routes protect the selected host-to-host service endpoints rather
than rewriting the whole routing domain.

The active repair-route set contains ten static `/32` route specifications.
Five steer protected `hostA` to `hostB` traffic over the southern backup
corridor, and five steer the reverse `hostB` to `hostA` direction. This
bidirectional host-pair protection is used consistently by BFD-like, AI-MRCE,
and hybrid mechanisms.

| Direction | Installing router sequence |
| --- | --- |
| `hostA -> hostB` | `accessA`, `west2`, `coreSW`, `coreSE`, `east2` |
| `hostB -> hostA` | `accessB`, `east2`, `coreSE`, `coreSW`, `west2` |

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
- cost-aware backup usage and early-backup exposure when the cost-aware cohort
  is selected;
- service interruption and recovery-window proxies;
- BFD-like detection timing and modeled loss at detection.

Legacy `packet_sequence_gap_total_missing_*` fields are retained for backward
compatibility as forward-jump continuity estimates. They must not be described
as direct packet loss without checking the corresponding `unobserved` and
`reordered` metrics.

For publication tables, the recommended headline fields are:

- mechanism family;
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

- legacy `missing` / forward-jump compatibility fields;
- queue-normalized transition ratios;
- `zero_progress_windows` and `recovery_time` fields when they are always zero.

The separate network-impact report under `analysis/output/network_impact/`
extends this view without changing the validated experiment. It derives
UDP/QoS diagnostics from the existing dataset and outcome summaries, including
phase-level delay, throughput/goodput, queue state, applied impairment context,
receiver-observed continuity, and reordering summaries.

Those additional fields are intentionally conservative:

- post-failure and activation-to-failure unobserved gaps remain
  receiver-observed continuity diagnostics;
- exact UDP packet loss is reported only for the monitored UDP `app[0]` flow
  when INET `packetSent:count` and `packetReceived:count` scalar accounting is
  available;
- delivery/loss-like ratios remain proxies unless exact sent/received
  accounting exists for the selected flow and phase;
- delay-variation fields are window-mean delta proxies, not full RFC 5481 IPDV;
- TCP received-byte/goodput/progress fields in the mixed transport-impact
  cohort are endpoint-observed proxies only; TCP retransmissions, RTT,
  congestion window, duplicate ACKs, and exact flow-completion time are not
  claimed;
- recovery-time fields are receiver-observed recovery/disruption proxies, not
  routing-protocol convergence timers;
- queue drop counts are not claimed unless a future scenario explicitly records
  queue-drop signals.

The instrumented transport-impact derivative is the first intentionally richer
INET telemetry pass. It can report exact aggregate UDP sent/received/loss
counts across all configured UDP application flows, histogram-derived UDP delay
percentiles over received packets, TCP endpoint goodput/progress, TCP RTT and
congestion-window scalar summaries where INET exports them, and compact queue
drop/queueing summaries. These additions improve network-result figures but do
not change the deployed AI-MRCE decision logic, runtime model artifacts,
thresholds, BFD-like logic, or FRR-like repair-route behavior.

## Diagnostic Artifacts

The model-family pipeline can generate:

- risk/action traces under `analysis/output/debug/`;
- model-action event summaries under `analysis/output/debug/`;
- headline summaries under `analysis/output/outcomes/`;
- network-impact summaries under `analysis/output/network_impact/`;
- offline telemetry-v2 ML feasibility reports under `analysis/output/ml_audit/`;
- a pipeline-integrity report under `analysis/output/debug/`.

These files are generated artifacts and should not be committed.

The offline ML audit is a feature-quality and feasibility check only. It uses
the telemetry-v2 feature classification to exclude metadata, label/target,
post-failure, trigger-source, impairment-context, and controller-state leakage
fields from candidate model inputs. It does not retrain or deploy runtime
AI-MRCE artifacts. Any runtime export v2 must be handled as a separate future
validation step.

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
- broad stochastic statistical significance beyond the controlled five-run
  reproducibility/coverage cohort.
