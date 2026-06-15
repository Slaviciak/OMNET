// Passive offline QoS-event monitor for Scenario C.
//
// The module observes runtime-safe telemetry sources and records compact
// evaluation scalars. It does not change controller decisions or routing.

package dissertationsim.controller;

simple QosEventMonitor
{
    parameters:
        @class(dissertationsim::controller::QosEventMonitor);
        string probeReceiverModule;
        string protectedQueueModule;
        double baselineStartTime @unit(s) = default(20s);
        double baselineEndTime @unit(s) = default(45s);
        double eventStartTime @unit(s) = default(55s);
        double evaluationInterval @unit(s) = default(1s);
        double stopTime @unit(s) = default(130s);
        double probeSendInterval @unit(s) = default(10ms);
        double probePacketLength @unit(B) = default(256B);
        int consecutiveWindows = default(3);
        double delayThresholdFloor @unit(s) = default(20ms);
        double delayThresholdMargin @unit(s) = default(5ms);
        double queueLengthThresholdFloorPk = default(5);
        double queueLengthThresholdMarginPk = default(5);
        double packetCountFloorRatio = default(0.85);
        double throughputFloorRatio = default(0.85);
        @display("i=block/timer");
}
