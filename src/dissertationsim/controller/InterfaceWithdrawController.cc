#include "InterfaceWithdrawController.h"
#include "inet/networklayer/common/NetworkInterface.h"

using namespace omnetpp;

namespace dissertationsim::controller {

Define_Module(InterfaceWithdrawController);

void InterfaceWithdrawController::initialize()
{
    withdrawTimer = new cMessage("withdrawTimer");
    scheduleAt(par("withdrawTime"), withdrawTimer);
}

void InterfaceWithdrawController::handleMessage(cMessage *message)
{
    if (message != withdrawTimer)
        throw cRuntimeError("Unexpected message received by InterfaceWithdrawController");

    administrativelyWithdraw(par("firstInterfaceModule"));
    administrativelyWithdraw(par("secondInterfaceModule"));
}

void InterfaceWithdrawController::finish()
{
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
    EV_INFO << "Administratively withdrawing interface " << networkInterface->getInterfaceFullPath() << endl;
    cMethodCallContextSwitcher contextSwitcher(networkInterface);
    networkInterface->setState(inet::NetworkInterface::DOWN);
}

} // namespace dissertationsim::controller
