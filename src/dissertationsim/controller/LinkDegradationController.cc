// Controlled synthetic degradation proxy for dissertation experiments.
//
// This controller varies ordinary OMNeT++ channel delay and packet error rate
// over time so the platform can generate pre-failure telemetry. It models the
// impairment period only; the final hard failure remains a separate
// ScenarioManager disconnect in the scenario configuration. The profiles are
// intentionally deterministic and interpretable; they are not presented as
// real carrier impairment traces. The staged profile is specifically meant to
// approximate intermittent deterioration or gray-failure-style brownouts using
// observable delay variation and loss symptoms, while remaining reproducible.

#include "LinkDegradationController.h"

#include <cmath>
#include <string>

#include "omnetpp/cdataratechannel.h"
#include "inet/networklayer/common/NetworkInterface.h"

using namespace omnetpp;

namespace {

constexpr double PI = 3.14159265358979323846;
constexpr const char *PROFILE_MILD_LINEAR = "mildLinear";
constexpr const char *PROFILE_STRONG_LINEAR = "strongLinear";
constexpr const char *PROFILE_UNSTABLE_LINEAR = "unstableLinear";
constexpr const char *PROFILE_STAGED_REALISTIC = "stagedRealistic";
constexpr const char *SUPPORTED_PROFILES_DESCRIPTION = "mildLinear, strongLinear, unstableLinear, stagedRealistic";

constexpr double STAGED_EARLY_END = 0.30;
constexpr double STAGED_MIDDLE_END = 0.75;
constexpr double STAGED_EARLY_DELAY_PROGRESS_MAX = 0.12;
constexpr double STAGED_EARLY_PER_PROGRESS_MAX = 0.02;
constexpr double STAGED_MIDDLE_DELAY_PROGRESS_BASE = 0.12;
constexpr double STAGED_MIDDLE_DELAY_PROGRESS_RISE = 0.26;
constexpr double STAGED_MIDDLE_PER_PROGRESS_BASE = 0.02;
constexpr double STAGED_MIDDLE_PER_PROGRESS_RISE = 0.16;
constexpr double STAGED_MIDDLE_BROWNOUT_ENVELOPE_BASE = 0.25;
constexpr double STAGED_MIDDLE_BROWNOUT_ENVELOPE_RISE = 0.75;
constexpr double STAGED_MIDDLE_BROWNOUT_CYCLES = 2.5;
constexpr double STAGED_MIDDLE_BROWNOUT_SHARPNESS = 4.0;
constexpr double STAGED_MIDDLE_BROWNOUT_DELAY_GAIN = 0.18;
constexpr double STAGED_MIDDLE_BROWNOUT_PER_GAIN = 0.32;
constexpr double STAGED_LATE_BROWNOUT_ENVELOPE_BASE = 0.55;
constexpr double STAGED_LATE_BROWNOUT_ENVELOPE_RISE = 0.45;
constexpr double STAGED_LATE_BROWNOUT_CYCLES = 4.0;
constexpr double STAGED_LATE_BROWNOUT_PHASE_OFFSET = 0.15;
constexpr double STAGED_LATE_BROWNOUT_SHARPNESS = 2.5;
constexpr double STAGED_LATE_DELAY_PROGRESS_BASE = 0.38;
constexpr double STAGED_LATE_DELAY_PROGRESS_RISE = 0.62;
constexpr double STAGED_LATE_DELAY_EXPONENT = 1.25;
constexpr double STAGED_LATE_DELAY_BROWNOUT_GAIN = 0.20;
constexpr double STAGED_LATE_PER_PROGRESS_BASE = 0.18;
constexpr double STAGED_LATE_PER_PROGRESS_RISE = 0.82;
constexpr double STAGED_LATE_PER_EXPONENT = 1.35;
constexpr double STAGED_LATE_PER_BROWNOUT_GAIN = 0.25;
constexpr double UNSTABLE_LINEAR_OSCILLATION_AMPLITUDE = 0.08;
constexpr double UNSTABLE_LINEAR_OSCILLATION_PI_MULTIPLIER = 6.0;

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

double normalizeSegment(double progress, double start, double end)
{
    if (end <= start)
        return progress >= end ? 1.0 : 0.0;
    return clamp01((progress - start) / (end - start));
}

double smoothstep01(double value)
{
    value = clamp01(value);
    return value * value * (3.0 - 2.0 * value);
}

double positivePulse(double phase, double sharpness)
{
    auto sineValue = std::sin(2.0 * PI * phase);
    if (sineValue <= 0)
        return 0;
    return std::pow(sineValue, sharpness);
}

bool isSupportedProfile(const std::string& profile)
{
    return profile == PROFILE_MILD_LINEAR
        || profile == PROFILE_STRONG_LINEAR
        || profile == PROFILE_UNSTABLE_LINEAR
        || profile == PROFILE_STAGED_REALISTIC;
}

ProfileProgress stagedRealisticProgress(double progress)
{
    // This profile is a deterministic intermittent-deterioration proxy. It is
    // motivated by literature on delay variation as an observable symptom and
    // by work on gray or hardware-deterioration failures where links can spend
    // periods of time oscillating between mostly healthy and visibly degraded
    // operation before a later hard outage. It does not claim empirical
    // calibration to any specific operator dataset.
    //
    // The intended approximation is:
    // - early phase: mild sustained delay/loss drift
    // - middle phase: intermittent brownout episodes with elevated delay and loss
    // - late phase: denser and more severe brownouts before the scripted outage
    if (progress <= STAGED_EARLY_END) {
        auto phaseProgress = smoothstep01(normalizeSegment(progress, 0.0, STAGED_EARLY_END));
        return {
            STAGED_EARLY_DELAY_PROGRESS_MAX * phaseProgress,
            STAGED_EARLY_PER_PROGRESS_MAX * phaseProgress,
        };
    }

    if (progress <= STAGED_MIDDLE_END) {
        auto phaseProgress = normalizeSegment(progress, STAGED_EARLY_END, STAGED_MIDDLE_END);
        auto delayTrend = STAGED_MIDDLE_DELAY_PROGRESS_BASE + STAGED_MIDDLE_DELAY_PROGRESS_RISE * phaseProgress;
        auto perTrend = STAGED_MIDDLE_PER_PROGRESS_BASE + STAGED_MIDDLE_PER_PROGRESS_RISE * phaseProgress;
        auto brownoutEnvelope = STAGED_MIDDLE_BROWNOUT_ENVELOPE_BASE
            + STAGED_MIDDLE_BROWNOUT_ENVELOPE_RISE * phaseProgress;
        // Deterministic brownout windows create short worse-than-trend periods
        // without introducing randomness into the dataset generation path.
        auto brownoutPulse = positivePulse(
            STAGED_MIDDLE_BROWNOUT_CYCLES * phaseProgress,
            STAGED_MIDDLE_BROWNOUT_SHARPNESS
        );
        return {
            clamp01(delayTrend + STAGED_MIDDLE_BROWNOUT_DELAY_GAIN * brownoutEnvelope * brownoutPulse),
            clamp01(perTrend + STAGED_MIDDLE_BROWNOUT_PER_GAIN * brownoutEnvelope * brownoutPulse),
        };
    }

    auto phaseProgress = normalizeSegment(progress, STAGED_MIDDLE_END, 1.0);
    auto lateBrownoutEnvelope = STAGED_LATE_BROWNOUT_ENVELOPE_BASE
        + STAGED_LATE_BROWNOUT_ENVELOPE_RISE * phaseProgress;
    auto lateBrownoutPulse = positivePulse(
        STAGED_LATE_BROWNOUT_CYCLES * phaseProgress + STAGED_LATE_BROWNOUT_PHASE_OFFSET,
        STAGED_LATE_BROWNOUT_SHARPNESS
    );
    return {
        clamp01(
            STAGED_LATE_DELAY_PROGRESS_BASE
            + STAGED_LATE_DELAY_PROGRESS_RISE * std::pow(phaseProgress, STAGED_LATE_DELAY_EXPONENT)
            + STAGED_LATE_DELAY_BROWNOUT_GAIN * lateBrownoutEnvelope * lateBrownoutPulse
        ),
        clamp01(
            STAGED_LATE_PER_PROGRESS_BASE
            + STAGED_LATE_PER_PROGRESS_RISE * std::pow(phaseProgress, STAGED_LATE_PER_EXPONENT)
            + STAGED_LATE_PER_BROWNOUT_GAIN * lateBrownoutEnvelope * lateBrownoutPulse
        ),
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
    if (!isSupportedProfile(profile))
        throw cRuntimeError("Unsupported degradation profile '%s'. Supported profiles: %s", profile.c_str(), SUPPORTED_PROFILES_DESCRIPTION);

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
    if (profile == PROFILE_UNSTABLE_LINEAR) {
        // Small deterministic oscillations around the upward trend provide a
        // simple non-monotonic proxy without introducing randomness.
        auto oscillation = UNSTABLE_LINEAR_OSCILLATION_AMPLITUDE
            * std::sin(UNSTABLE_LINEAR_OSCILLATION_PI_MULTIPLIER * PI * progress);
        delayProgress = clamp01(progress + oscillation * progress);
        packetErrorRateProgress = delayProgress;
    }
    else if (profile == PROFILE_STAGED_REALISTIC) {
        auto stagedProgress = stagedRealisticProgress(progress);
        delayProgress = stagedProgress.delay;
        packetErrorRateProgress = stagedProgress.packetErrorRate;
    }

    // Interpolate from each direction's original simulator channel settings to
    // the configured target impairment. targetPacketErrorRate is the OMNeT++
    // cDatarateChannel packet error rate in [0, 1]; high values in the
    // regional degraded-link cohort represent severe stress/brownout, not a
    // calibrated operator trace.
    auto appliedDelay = channels[0].initialDelay + (targetDelay - channels[0].initialDelay) * delayProgress;
    auto appliedPacketErrorRate = channels[0].initialPacketErrorRate + (targetPacketErrorRate - channels[0].initialPacketErrorRate) * packetErrorRateProgress;

    for (auto& channelState : channels) {
        auto channelDelay = channelState.initialDelay + (targetDelay - channelState.initialDelay) * delayProgress;
        auto channelPacketErrorRate = channelState.initialPacketErrorRate + (targetPacketErrorRate - channelState.initialPacketErrorRate) * packetErrorRateProgress;
        applyToChannel(channelState, channelDelay, channelPacketErrorRate);
    }

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
