// Project-local runtime prototype for AI-MRCE experiments.
// It evaluates compact telemetry and can trigger either the older conservative
// administrative-withdrawal reference action or a project-local FRR-like
// static repair-route abstraction for the monitored corridor. Comparison
// configs may also enable a BFD-inspired protected-span / missed-probe detector
// as a reactive safety net; this is not a full RFC BFD implementation.

package dissertationsim.controller;

simple AiMrceController
{
    parameters:
        @class(dissertationsim::controller::AiMrceController);
        // Queue path for the protected corridor. The observed queue behavior
        // depends on the queue implementation present in the current scenario.
        string protectedQueueModule;
        // Probe receiver application whose packetReceived signal is used for
        // runtime delay, throughput, and packet-count observations.
        string probeReceiverModule;
        // Supported: adminWithdrawal, localRepairStaticRoutes.
        // localRepairStaticRoutes is a project-local abstraction of activating
        // a preinstalled protection path. It installs explicit manual /32 IPv4
        // routes and is not a protocol-standard FRR implementation.
        string protectionAction = default("adminWithdrawal");
        // Semicolon-separated static repair route specs used when
        // protectionAction=localRepairStaticRoutes. Each item has:
        // routerModule,outputInterfaceModule,gatewayInterfaceModule,destinationInterfaceModule
        // Example: ^.accessA,^.accessA.eth[2],^.west2.eth[0],^.hostB.eth[0]
        string localRepairRouteSpecs = default("");
        int localRepairRouteMetric = default(1);
        // Administrative-withdrawal reference action uses ordinary interface-
        // down semantics on the preferred span, not a custom OSPF extension.
        string firstInterfaceModule;
        string secondInterfaceModule;
        // Supported: ruleBased, logisticRegression, linearSvm, shallowTree.
        string decisionMode = default("ruleBased");
        // AI-MRCE decisioning is enabled by default to preserve existing
        // runtime configs. BFD-like detection is opt-in for the separate
        // failure-detection comparison cohort.
        bool enableAimrceDecision = default(true);
        bool enableBfdLikeDetection = default(false);
        // Project-local BFD-inspired detector parameters. The detector observes
        // protected-span interface/carrier state and also counts probe-reception
        // intervals with fewer than bfdLikeExpectedProbeCount packets. An
        // opt-in modeled-probe-loss mode can additionally expose logical
        // BFD-like checks to the current OMNeT++ channel packet error rate on
        // the protected span. It triggers the same repair-route actuator after
        // bfdLikeDetectMultiplier consecutive unhealthy intervals. This models
        // a fast reactive safety net conservatively; it does not model
        // negotiated BFD sessions, discriminator state, or OSPF/BFD signaling.
        double bfdLikeStartTime @unit(s) = default(20s);
        double bfdLikeDetectionInterval @unit(s) = default(1s);
        int bfdLikeDetectMultiplier = default(3);
        int bfdLikeExpectedProbeCount = default(1);
        // Disabled by default to preserve existing congestion-only cohorts.
        // Degraded-link comparison configs enable it so BFD-like checks can
        // react to progressive packet-loss impairment before carrier-down.
        bool bfdLikeUseModeledProbeLoss = default(false);
        // Optional metadata recorded as a scalar for analysis diagnostics.
        double hardFailureTime @unit(s) = default(-1s);
        // Used only in learned-model modes. This file is an exported runtime
        // deployment artifact, not the main methodological evaluation output.
        string runtimeModelFile = default("");
        double startTime @unit(s) = default(20s);
        double evaluationInterval @unit(s) = default(1s);
        int activationConsecutiveCycles = default(3);
        double probeSendInterval @unit(s) = default(10ms);
        double probePacketLength @unit(B) = default(256B);
        double queueLengthThresholdPk = default(40);
        double delayThreshold @unit(s) = default(20ms);
        double throughputFloorRatio = default(0.85);
        double packetCountFloorRatio = default(0.85);
        double ruleRiskThreshold = default(0.6);
        // Controlled EV logging for manual Qtenv/Cmdenv demonstration.
        bool verboseTelemetryLogging = default(false);
        double telemetryLogInterval @unit(s) = default(5s);
        bool verboseDecisionLogging = default(false);
        bool verboseRepairRouteLogging = default(false);
        bool verboseBfdLikeLogging = default(false);
        @display("i=block/cogwheel");
}
