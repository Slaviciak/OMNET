// Reusable controller for controlled synthetic degradation proxies.
// It manipulates current OMNeT++ channel delay and packet error rate on a
// protected span and is intentionally separate from protocol-standard routing
// behavior. Final hard failure is configured separately in ScenarioManager.

package dissertationsim.controller;

simple LinkDegradationController
{
    parameters:
        @class(dissertationsim::controller::LinkDegradationController);
        string firstInterfaceModule;
        string secondInterfaceModule;
        // Supported profiles are controlled synthetic proxies, not empirical
        // field-failure curves: mildLinear, strongLinear, unstableLinear,
        // stagedRealistic. The stagedRealistic profile is intentionally a
        // deterministic intermittent-deterioration proxy rather than a claim
        // that operators can observe a perfectly smooth pre-failure ramp.
        string profile = default("mildLinear");
        // Start/end of the pre-failure impairment window. The controller does
        // not disconnect the link at endTime; hard failure remains a separate
        // scenario event.
        double startTime @unit(s);
        double endTime @unit(s);
        // Frequency for recomputing the deterministic current impairment.
        double updateInterval @unit(s) = default(0.5s);
        // Target one-way channel delay at the end of the degradation window.
        double targetDelay @unit(s);
        // Target OMNeT++ channel packet error rate at the end of the
        // degradation window. Valid range is [0, 1].
        double targetPacketErrorRate;
        @display("i=block/cogwheel");
}
