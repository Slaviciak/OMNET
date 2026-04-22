// Reusable controller for controlled synthetic degradation proxies.
// It manipulates channel delay and packet error rate on a protected span and
// is intentionally separate from protocol-standard routing behavior.

package dissertationsim.controller;

simple LinkDegradationController
{
    parameters:
        @class(dissertationsim::controller::LinkDegradationController);
        string firstInterfaceModule;
        string secondInterfaceModule;
        // Supported profiles are controlled synthetic proxies, not empirical
        // field-failure curves: mildLinear, strongLinear, unstableLinear,
        // stagedRealistic.
        string profile = default("mildLinear");
        double startTime @unit(s);
        double endTime @unit(s);
        double updateInterval @unit(s) = default(0.5s);
        double targetDelay @unit(s);
        double targetPacketErrorRate;
        @display("i=block/cogwheel");
}
