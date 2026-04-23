// Scheduled administrative interface withdrawal helper.
//
// This controller is part of the project-local experimental tooling. It does
// not implement any new routing protocol mechanism; instead it exercises the
// standard routing consequences of taking the protected interface down.

#include "InterfaceWithdrawController.h"
#include "inet/networklayer/common/NetworkInterface.h"

using namespace omnetpp;

namespace dissertationsim::controller {

Define_Module(InterfaceWithdrawController);

void InterfaceWithdrawController::initialize()
{
    simtime_t withdrawTime = par("withdrawTime");
    if (withdrawTime < 0)
        throw cRuntimeError("withdrawTime must be non-negative");

    withdrawTimer = new cMessage("withdrawTimer");
    scheduleAt(withdrawTime, withdrawTimer);

    WATCH(protectionActivated);
    WATCH(protectionActivationTime);
}

void InterfaceWithdrawController::handleMessage(cMessage *message)
{
    if (message != withdrawTimer)
        throw cRuntimeError("Unexpected message received by InterfaceWithdrawController");

    // Both directions of the preferred span are withdrawn so the later routing
    // behavior reflects ordinary interface-down handling on both endpoints.
    administrativelyWithdraw(par("firstInterfaceModule"));
    administrativelyWithdraw(par("secondInterfaceModule"));

    // These shared scalars are workflow measurement support only. They align
    // the deterministic proactive baseline with the AI-MRCE controller output
    // names so later outcome analysis can compare action timing without
    // changing routing semantics or implying identical decision logic.
    protectionActivated = true;
    protectionActivationTime = simTime();
}

void InterfaceWithdrawController::finish()
{
    // This remains project-local recovery-evaluation instrumentation. The
    // proactive baseline still uses standard administrative interface-down
    // behavior rather than any custom OSPF or INET extension.
    recordScalar("protectionActivated", protectionActivated);
    recordScalar("protectionActivationTime", protectionActivationTime >= SIMTIME_ZERO ? protectionActivationTime.dbl() : -1);

    cancelAndDelete(withdrawTimer);
    withdrawTimer = nullptr;
}

inet::NetworkInterface *InterfaceWithdrawController::resolveInterface(const char *modulePath) const
{
    auto module = getModuleByPath(modulePath);
    if (module == nullptr)
        throw cRuntimeError("Cannot find target interface module '%s'", modulePath);
    return check_and_cast<inet::NetworkInterface *>(module);
}

void InterfaceWithdrawController::administrativelyWithdraw(const char *modulePath)
{
    auto networkInterface = resolveInterface(modulePath);
    if (networkInterface->getState() == inet::NetworkInterface::DOWN)
        return;

    // This follows ordinary administrative interface-down semantics rather
    // than introducing any custom protocol message or local shortcut.
    EV_INFO << "Administratively withdrawing interface " << networkInterface->getInterfaceFullPath() << endl;
    cMethodCallContextSwitcher contextSwitcher(networkInterface);
    networkInterface->setState(inet::NetworkInterface::DOWN);
}

} // namespace dissertationsim::controller
