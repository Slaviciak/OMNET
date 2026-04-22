// Controlled synthetic degradation proxy for dissertation experiments.
//
// This controller varies ordinary OMNeT++ channel delay and packet error rate
// over time so the platform can generate pre-failure telemetry. The profiles
// are intentionally deterministic and interpretable; they are not presented as
// real carrier impairment traces.

#include "LinkDegradationController.h"

#include <cmath>

#include "omnetpp/cdataratechannel.h"
#include "inet/networklayer/common/NetworkInterface.h"

using namespace omnetpp;

namespace {

constexpr double PI = 3.14159265358979323846;

struct ProfileProgress
{
    double delay = 0;
    double packetErrorRate = 0;
};

double clamp01(double value)
{
    if (value < 0)
        return 0;
    if (value > 1)
        return 1;
    return value;
}

ProfileProgress stagedRealisticProgress(double progress)
{
    // This profile is a hand-designed controlled synthetic degradation proxy.
    // It aims to produce a gradual early phase, a noisier mid phase, and a
    // sharper late phase without claiming empirical field calibration.
    if (progress <= 1.0 / 3.0) {
        auto phaseProgress = progress * 3.0;
        return {
            0.20 * std::pow(phaseProgress, 1.2),
            0.02 * phaseProgress,
        };
    }

    if (progress <= 2.0 / 3.0) {
        auto phaseProgress = (progress - 1.0 / 3.0) * 3.0;
        auto delayTrend = 0.20 + 0.40 * phaseProgress;
        // Deterministic delay variation: small bounded oscillations around the trend.
        auto delayVariation = 0.04 * std::sin(4.0 * PI * phaseProgress);
        return {
            clamp01(delayTrend + delayVariation),
            0.02 + 0.18 * phaseProgress,
        };
    }

    auto phaseProgress = (progress - 2.0 / 3.0) * 3.0;
    return {
        0.60 + 0.40 * std::pow(phaseProgress, 1.7),
        0.20 + 0.80 * std::pow(phaseProgress, 1.8),
    };
}

} // namespace

namespace dissertationsim::controller {

Define_Module(LinkDegradationController);

void LinkDegradationController::initialize()
{
    simtime_t startTime = par("startTime");
    simtime_t endTime = par("endTime");
    simtime_t updateInterval = par("updateInterval");
    simtime_t targetDelay = par("targetDelay");
    auto profile = par("profile").stdstringValue();
    auto targetPacketErrorRate = par("targetPacketErrorRate").doubleValue();

    if (startTime < 0)
        throw cRuntimeError("startTime must be non-negative");
    if (endTime < startTime)
        throw cRuntimeError("endTime must not be earlier than startTime");
    if (updateInterval <= 0)
        throw cRuntimeError("updateInterval must be positive");
    if (targetDelay < 0)
        throw cRuntimeError("targetDelay must be non-negative");
    if (targetPacketErrorRate < 0 || targetPacketErrorRate > 1)
        throw cRuntimeError("targetPacketErrorRate must be between 0 and 1");
    if (profile != "mildLinear" && profile != "strongLinear" && profile != "unstableLinear" && profile != "stagedRealistic")
        throw cRuntimeError("Unsupported degradation profile '%s'", profile.c_str());

    channels[0] = resolveTransmitChannel(par("firstInterfaceModule"));
    channels[1] = resolveTransmitChannel(par("secondInterfaceModule"));

    appliedDelayVector.setName("appliedDelay");
    appliedPacketErrorRateVector.setName("appliedPacketErrorRate");

    // Record the initial unmodified state so later analysis can see the full
    // trajectory from baseline through the synthetic degradation proxy.
    recordAppliedValues(channels[0].initialDelay, channels[0].initialPacketErrorRate);

    updateTimer = new cMessage("degradationUpdateTimer");
    scheduleAt(startTime, updateTimer);
}

void LinkDegradationController::handleMessage(cMessage *message)
{
    if (message != updateTimer)
        throw cRuntimeError("Unexpected message received by LinkDegradationController");

    simtime_t now = simTime();
    simtime_t endTime = par("endTime");
    simtime_t updateInterval = par("updateInterval");

    applyProfile(now);

    if (now < endTime) {
        auto nextUpdate = now + updateInterval;
        if (nextUpdate > endTime)
            nextUpdate = endTime;
        scheduleAt(nextUpdate, updateTimer);
    }
}

void LinkDegradationController::finish()
{
    cancelAndDelete(updateTimer);
    updateTimer = nullptr;
}

inet::NetworkInterface *LinkDegradationController::resolveInterface(const char *modulePath) const
{
    auto module = getModuleByPath(modulePath);
    if (module == nullptr)
        throw cRuntimeError("Cannot find target interface module '%s'", modulePath);
    return check_and_cast<inet::NetworkInterface *>(module);
}

LinkDegradationController::ChannelState LinkDegradationController::resolveTransmitChannel(const char *modulePath) const
{
    auto networkInterface = resolveInterface(modulePath);
    auto channel = dynamic_cast<cDatarateChannel *>(networkInterface->getTxTransmissionChannel());
    if (channel == nullptr)
        throw cRuntimeError("Target interface '%s' does not have a cDatarateChannel transmit channel", modulePath);

    ChannelState channelState;
    channelState.channel = channel;
    channelState.initialDelay = channel->getDelay();
    channelState.initialPacketErrorRate = channel->getPacketErrorRate();
    return channelState;
}

void LinkDegradationController::applyProfile(simtime_t now)
{
    simtime_t startTime = par("startTime");
    simtime_t endTime = par("endTime");
    simtime_t targetDelay = par("targetDelay");
    auto profile = par("profile").stdstringValue();
    auto targetPacketErrorRate = par("targetPacketErrorRate").doubleValue();

    double progress;
    if (endTime == startTime)
        progress = 1.0;
    else {
        progress = clamp01((now - startTime).dbl() / (endTime - startTime).dbl());
    }

    double delayProgress = progress;
    double packetErrorRateProgress = progress;
    if (profile == "unstableLinear") {
        // Small deterministic oscillations around the upward trend provide a
        // simple non-monotonic proxy without introducing randomness.
        auto oscillation = 0.08 * std::sin(6.0 * PI * progress);
        delayProgress = clamp01(progress + oscillation * progress);
        packetErrorRateProgress = delayProgress;
    }
    else if (profile == "stagedRealistic") {
        auto stagedProgress = stagedRealisticProgress(progress);
        delayProgress = stagedProgress.delay;
        packetErrorRateProgress = stagedProgress.packetErrorRate;
    }

    auto appliedDelay = channels[0].initialDelay + (targetDelay - channels[0].initialDelay) * delayProgress;
    auto appliedPacketErrorRate = channels[0].initialPacketErrorRate + (targetPacketErrorRate - channels[0].initialPacketErrorRate) * packetErrorRateProgress;

    for (auto& channelState : channels)
        applyToChannel(channelState, channelState.initialDelay + (targetDelay - channelState.initialDelay) * delayProgress, channelState.initialPacketErrorRate + (targetPacketErrorRate - channelState.initialPacketErrorRate) * packetErrorRateProgress);

    recordAppliedValues(appliedDelay, appliedPacketErrorRate);
}

void LinkDegradationController::applyToChannel(ChannelState& channelState, simtime_t delay, double packetErrorRate)
{
    // This operates on the simulator channel object itself. The effect is a
    // project-local impairment mechanism, not any standardized protocol signal.
    EV_INFO << "Applying degradation to channel " << channelState.channel->getFullPath()
            << " delay=" << delay << " per=" << packetErrorRate << endl;
    cMethodCallContextSwitcher contextSwitcher(channelState.channel);
    channelState.channel->setDelay(delay.dbl());
    channelState.channel->setPacketErrorRate(packetErrorRate);
}

void LinkDegradationController::recordAppliedValues(simtime_t delay, double packetErrorRate)
{
    // Current scenarios apply symmetric settings to both directions, so the
    // recorded values are representative span-level control settings.
    appliedDelayVector.record(delay.dbl());
    appliedPacketErrorRateVector.record(packetErrorRate);
}

} // namespace dissertationsim::controller
