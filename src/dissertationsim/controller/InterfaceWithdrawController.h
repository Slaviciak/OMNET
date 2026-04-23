// Project-local helper for deterministic protective-reroute baselines.
//
// This controller performs a scheduled administrative withdrawal of two
// interfaces. It is intentionally simple and aligns with ordinary operational
// interface-down semantics in routing experiments rather than any custom OSPF
// protocol extension.

#ifndef __DISSERTATIONSIM_INTERFACEWITHDRAWCONTROLLER_H
#define __DISSERTATIONSIM_INTERFACEWITHDRAWCONTROLLER_H

#include <omnetpp.h>

namespace inet {
class NetworkInterface;
}

namespace dissertationsim::controller {

/**
 * Small reusable helper for scheduled interface withdrawal experiments.
 *
 * It is used for deterministic baselines such as proactive switch experiments,
 * where the action time is known in advance and no runtime inference is
 * involved.
 */
class InterfaceWithdrawController : public omnetpp::cSimpleModule
{
  protected:
    omnetpp::cMessage *withdrawTimer = nullptr;
    bool protectionActivated = false;
    omnetpp::simtime_t protectionActivationTime = omnetpp::simtime_t(-1);

  protected:
    virtual void initialize() override;
    virtual void handleMessage(omnetpp::cMessage *message) override;
    virtual void finish() override;

    inet::NetworkInterface *resolveInterface(const char *modulePath) const;
    // Uses administrative interface shutdown rather than deep protocol changes.
    void administrativelyWithdraw(const char *modulePath);
};

} // namespace dissertationsim::controller

#endif
