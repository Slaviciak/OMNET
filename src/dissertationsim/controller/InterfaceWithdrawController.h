#ifndef __DISSERTATIONSIM_INTERFACEWITHDRAWCONTROLLER_H
#define __DISSERTATIONSIM_INTERFACEWITHDRAWCONTROLLER_H

#include <omnetpp.h>

namespace inet {
class NetworkInterface;
}

namespace dissertationsim::controller {

class InterfaceWithdrawController : public omnetpp::cSimpleModule
{
  protected:
    omnetpp::cMessage *withdrawTimer = nullptr;

  protected:
    virtual void initialize() override;
    virtual void handleMessage(omnetpp::cMessage *message) override;
    virtual void finish() override;

    inet::NetworkInterface *resolveInterface(const char *modulePath) const;
    void administrativelyWithdraw(const char *modulePath);
};

} // namespace dissertationsim::controller

#endif
