// Reusable helper for scheduled administrative withdrawal experiments.
// This is a conservative project-local control mechanism, not a protocol
// extension or a runtime AI-MRCE inference module.

package dissertationsim.controller;

simple InterfaceWithdrawController
{
    parameters:
        @class(dissertationsim::controller::InterfaceWithdrawController);
        string firstInterfaceModule;
        string secondInterfaceModule;
        // Absolute simulation time for the deterministic withdrawal action.
        double withdrawTime @unit(s);
        // Measurement-only note: finish() records shared protection scalars so
        // the deterministic proactive baseline can be compared with AI-MRCE in
        // offline outcome analysis. This is workflow instrumentation only.
        @display("i=block/cogwheel");
}
