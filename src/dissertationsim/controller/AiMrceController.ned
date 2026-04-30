// Project-local runtime prototype for AI-MRCE experiments.
// It evaluates compact telemetry and can trigger either the older conservative
// administrative-withdrawal reference action or a project-local FRR-like
// static repair-route abstraction for the monitored corridor.

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
        @display("i=block/cogwheel");
}
