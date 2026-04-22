// Project-local controller for controlled synthetic degradation proxies.
//
// The controller manipulates ordinary OMNeT++ channel delay and packet error
// rate on a protected span to generate interpretable pre-failure telemetry.
// These profiles are controlled synthetic proxies for experiments; they are
// not empirically calibrated field-failure traces.

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

/**
 * Applies deterministic channel-impairment profiles to a protected span.
 *
 * Experimentally, this controller provides a reusable way to stage synthetic
 * pre-failure behavior without changing routing protocol internals.
 */
class LinkDegradationController : public omnetpp::cSimpleModule
{
  protected:
    // Both directions of the protected span are impaired symmetrically in the
    // current scenarios, so the controller keeps the original channel state for
    // each endpoint-facing transmit channel.
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
    // Selects and applies one of the controlled synthetic degradation profiles.
    void applyProfile(omnetpp::simtime_t now);
    // Applies standard OMNeT++ channel parameters, not protocol-standard logic.
    void applyToChannel(ChannelState& channelState, omnetpp::simtime_t delay, double packetErrorRate);
    void recordAppliedValues(omnetpp::simtime_t delay, double packetErrorRate);
};

} // namespace dissertationsim::controller

#endif
