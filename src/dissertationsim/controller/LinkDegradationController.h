#ifndef __DISSERTATIONSIM_LINKDEGRADATIONCONTROLLER_H
#define __DISSERTATIONSIM_LINKDEGRADATIONCONTROLLER_H

#include <omnetpp.h>

namespace omnetpp {
class cDatarateChannel;
}

namespace inet {
class NetworkInterface;
}

namespace dissertationsim::controller {

class LinkDegradationController : public omnetpp::cSimpleModule
{
  protected:
    struct ChannelState
    {
        omnetpp::cDatarateChannel *channel = nullptr;
        omnetpp::simtime_t initialDelay = SIMTIME_ZERO;
        double initialPacketErrorRate = 0;
    };

    omnetpp::cMessage *updateTimer = nullptr;
    ChannelState channels[2];
    omnetpp::cOutVector appliedDelayVector;
    omnetpp::cOutVector appliedPacketErrorRateVector;

  protected:
    virtual void initialize() override;
    virtual void handleMessage(omnetpp::cMessage *message) override;
    virtual void finish() override;

    inet::NetworkInterface *resolveInterface(const char *modulePath) const;
    ChannelState resolveTransmitChannel(const char *modulePath) const;
    void applyProfile(omnetpp::simtime_t now);
    void applyToChannel(ChannelState& channelState, omnetpp::simtime_t delay, double packetErrorRate);
    void recordAppliedValues(omnetpp::simtime_t delay, double packetErrorRate);
};

} // namespace dissertationsim::controller

#endif
