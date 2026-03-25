package dissertationsim.controller;

simple InterfaceWithdrawController
{
    parameters:
        @class(dissertationsim::controller::InterfaceWithdrawController);
        string firstInterfaceModule;
        string secondInterfaceModule;
        double withdrawTime @unit(s);
        @display("i=block/cogwheel");
}
