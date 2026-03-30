package dissertationsim.controller;

simple LinkDegradationController
{
    parameters:
        @class(dissertationsim::controller::LinkDegradationController);
        string firstInterfaceModule;
        string secondInterfaceModule;
        string profile = default("mildLinear");
        double startTime @unit(s);
        double endTime @unit(s);
        double updateInterval @unit(s) = default(0.5s);
        double targetDelay @unit(s);
        double targetPacketErrorRate;
        @display("i=block/cogwheel");
}
