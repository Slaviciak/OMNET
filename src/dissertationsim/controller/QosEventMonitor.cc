// Passive Scenario C QoS-event monitor for offline evaluation.
//
// The event label produced here is an evaluation artifact. It is not exposed to
// AI-MRCE runtime decisioning and does not modify traffic, routing, or failure
// behavior.

#include "QosEventMonitor.h"

#include <algorithm>

#include "inet/common/packet/Packet.h"
#include "inet/queueing/contract/IPacketCollection.h"

using namespace omnetpp;

namespace dissertationsim::controller {

Define_Module(QosEventMonitor);

void QosEventMonitor::initialize()
{
    simtime_t baselineStartTime = par("baselineStartTime");
    simtime_t baselineEndTime = par("baselineEndTime");
    simtime_t eventStartTime = par("eventStartTime");
    simtime_t evaluationInterval = par("evaluationInterval");
    simtime_t stopTime = par("stopTime");
    simtime_t probeSendInterval = par("probeSendInterval");
    double probePacketLength = par("probePacketLength").doubleValue();
    int consecutiveWindows = par("consecutiveWindows");
    double packetCountFloorRatio = par("packetCountFloorRatio").doubleValue();
    double throughputFloorRatio = par("throughputFloorRatio").doubleValue();

    if (baselineStartTime < 0)
        throw cRuntimeError("baselineStartTime must be non-negative");
    if (baselineEndTime <= baselineStartTime)
        throw cRuntimeError("baselineEndTime must be later than baselineStartTime");
    if (eventStartTime < baselineEndTime)
        throw cRuntimeError("eventStartTime must not be earlier than baselineEndTime");
    if (evaluationInterval <= 0)
        throw cRuntimeError("evaluationInterval must be positive");
    if (stopTime <= eventStartTime)
        throw cRuntimeError("stopTime must be later than eventStartTime");
    if (probeSendInterval <= 0)
        throw cRuntimeError("probeSendInterval must be positive");
    if (probePacketLength <= 0)
        throw cRuntimeError("probePacketLength must be positive");
    if (consecutiveWindows <= 0)
        throw cRuntimeError("consecutiveWindows must be positive");
    if (packetCountFloorRatio <= 0 || packetCountFloorRatio > 1)
        throw cRuntimeError("packetCountFloorRatio must be in the range (0, 1]");
    if (throughputFloorRatio <= 0 || throughputFloorRatio > 1)
        throw cRuntimeError("throughputFloorRatio must be in the range (0, 1]");

    probeReceiverModule = resolveModule(par("probeReceiverModule"), "probe receiver module");
    protectedQueue = resolveQueue(par("protectedQueueModule"));
    packetReceivedSignal = registerSignal("packetReceived");
    probeReceiverModule->subscribe(packetReceivedSignal, this);

    probeDelayMeanVector.setName("qosProbeDelayMeanS");
    probePacketCountVector.setName("qosProbePacketCount");
    probeThroughputVector.setName("qosProbeThroughputBps");
    queueLengthVector.setName("qosQueueLengthPk");
    brownoutWindowVector.setName("qosBrownoutWindow");
    consecutiveBrownoutVector.setName("qosConsecutiveBrownoutWindows");

    evaluationTimer = new cMessage("qosEventMonitorEvaluationTimer");
    scheduleAt(baselineStartTime + evaluationInterval, evaluationTimer);
}

void QosEventMonitor::handleMessage(cMessage *message)
{
    if (message != evaluationTimer)
        throw cRuntimeError("Unexpected message received by QosEventMonitor");

    evaluateWindow();

    simtime_t evaluationInterval = par("evaluationInterval");
    simtime_t stopTime = par("stopTime");
    auto nextTime = simTime() + evaluationInterval;
    if (nextTime <= stopTime)
        scheduleAt(nextTime, evaluationTimer);
}

void QosEventMonitor::receiveSignal(cComponent *source, simsignal_t signalID, cObject *object, cObject *)
{
    if (signalID != packetReceivedSignal || source != probeReceiverModule)
        return;

    auto packet = dynamic_cast<inet::Packet *>(object);
    if (packet == nullptr)
        return;

    intervalTelemetry.probePacketCount++;
    intervalTelemetry.probeReceivedBits += packet->getBitLength();
    intervalTelemetry.probeDelaySumSeconds += (simTime() - packet->getCreationTime()).dbl();
    intervalTelemetry.probeDelaySamples++;
}

void QosEventMonitor::finish()
{
    if (evaluationTimer != nullptr) {
        cancelAndDelete(evaluationTimer);
        evaluationTimer = nullptr;
    }

    if (probeReceiverModule != nullptr)
        probeReceiverModule->unsubscribe(packetReceivedSignal, this);

    recordScalar("qosEventDetected", qosEventDetected ? 1 : 0);
    recordScalar("qosEventTime", qosEventDetected ? qosEventTime.dbl() : -1);
    recordScalar("qosEventConsecutiveWindowsRequired", par("consecutiveWindows").intValue());
    recordScalar("qosEventDelayThreshold", delayThresholdSeconds);
    recordScalar("qosEventPacketCountFloor", packetCountFloor);
    recordScalar("qosEventThroughputFloorBps", throughputFloorBps);
    recordScalar("qosEventQueueLengthThresholdPk", queueLengthThresholdPackets);
    recordScalar("qosEventDetectionBasisCode", qosEventDetectionBasisCode);
    recordScalar("qosEventBaselineStartTime", par("baselineStartTime").doubleValue());
    recordScalar("qosEventBaselineEndTime", par("baselineEndTime").doubleValue());
    recordScalar("qosEventStartTime", par("eventStartTime").doubleValue());
    recordScalar("qosEventEvaluationInterval", par("evaluationInterval").doubleValue());
}

cModule *QosEventMonitor::resolveModule(const char *modulePath, const char *purpose) const
{
    auto module = getModuleByPath(modulePath);
    if (module == nullptr)
        throw cRuntimeError("Cannot find %s '%s'", purpose, modulePath);
    return module;
}

inet::queueing::IPacketCollection *QosEventMonitor::resolveQueue(const char *modulePath) const
{
    auto module = getModuleByPath(modulePath);
    if (module == nullptr)
        throw cRuntimeError("Cannot find protected queue module '%s'", modulePath);
    auto queue = dynamic_cast<inet::queueing::IPacketCollection *>(module);
    if (queue == nullptr)
        throw cRuntimeError("Protected queue module '%s' does not implement inet::queueing::IPacketCollection", modulePath);
    return queue;
}

void QosEventMonitor::evaluateWindow()
{
    simtime_t now = simTime();
    simtime_t baselineStartTime = par("baselineStartTime");
    simtime_t baselineEndTime = par("baselineEndTime");
    simtime_t eventStartTime = par("eventStartTime");
    simtime_t evaluationInterval = par("evaluationInterval");

    bool hasDelay = intervalTelemetry.probeDelaySamples > 0;
    double delayMeanSeconds = hasDelay
        ? intervalTelemetry.probeDelaySumSeconds / intervalTelemetry.probeDelaySamples
        : -1;
    int packetCount = intervalTelemetry.probePacketCount;
    double throughputBps = evaluationInterval.dbl() > 0
        ? intervalTelemetry.probeReceivedBits / evaluationInterval.dbl()
        : 0;
    double queueLengthPackets = protectedQueue != nullptr ? protectedQueue->getNumPackets() : 0;

    if (now > baselineStartTime && now <= baselineEndTime) {
        if (hasDelay) {
            baselineDelaySum += delayMeanSeconds;
            baselineDelaySamples++;
        }
        baselineQueueLengthSum += queueLengthPackets;
        baselineQueueLengthSamples++;
        baselinePacketCountSum += packetCount;
        baselinePacketCountSamples++;
        baselineThroughputSumBps += throughputBps;
        baselineThroughputSamples++;
    }

    initializeThresholdsIfNeeded();

    int basisCode = 0;
    bool brownout = false;
    if (now >= eventStartTime)
        brownout = isBrownoutWindow(delayMeanSeconds, hasDelay, packetCount, throughputBps, queueLengthPackets, basisCode);

    if (!qosEventDetected && brownout) {
        if (consecutiveBrownoutWindows == 0)
            brownoutStreakStart = now - evaluationInterval;
        consecutiveBrownoutWindows++;
        if (consecutiveBrownoutWindows >= par("consecutiveWindows").intValue()) {
            qosEventDetected = true;
            qosEventTime = brownoutStreakStart;
            qosEventDetectionBasisCode = basisCode;
        }
    }
    else if (!brownout) {
        consecutiveBrownoutWindows = 0;
        brownoutStreakStart = -1;
    }

    recordWindowVectors(delayMeanSeconds, hasDelay, packetCount, throughputBps, queueLengthPackets, brownout);
    resetIntervalTelemetry();
}

void QosEventMonitor::initializeThresholdsIfNeeded()
{
    if (thresholdsInitialized)
        return;
    if (simTime() < par("baselineEndTime"))
        return;

    simtime_t evaluationInterval = par("evaluationInterval");
    simtime_t probeSendInterval = par("probeSendInterval");
    double probePacketLength = par("probePacketLength").doubleValue();
    double expectedProbeCount = evaluationInterval.dbl() / probeSendInterval.dbl();
    double expectedThroughputBps = (probePacketLength * 8.0 * expectedProbeCount) / evaluationInterval.dbl();

    double baselineDelayMean = baselineDelaySamples > 0 ? baselineDelaySum / baselineDelaySamples : -1;
    double baselineQueueMean = baselineQueueLengthSamples > 0 ? baselineQueueLengthSum / baselineQueueLengthSamples : 0;
    double baselinePacketCountMean = baselinePacketCountSamples > 0 ? baselinePacketCountSum / baselinePacketCountSamples : expectedProbeCount;
    double baselineThroughputMean = baselineThroughputSamples > 0 ? baselineThroughputSumBps / baselineThroughputSamples : expectedThroughputBps;

    delayThresholdSeconds = std::max(
        par("delayThresholdFloor").doubleValue(),
        baselineDelayMean >= 0 ? baselineDelayMean + par("delayThresholdMargin").doubleValue() : par("delayThresholdFloor").doubleValue()
    );
    packetCountFloor = std::max(1.0, baselinePacketCountMean * par("packetCountFloorRatio").doubleValue());
    throughputFloorBps = baselineThroughputMean * par("throughputFloorRatio").doubleValue();
    queueLengthThresholdPackets = std::max(
        par("queueLengthThresholdFloorPk").doubleValue(),
        baselineQueueMean + par("queueLengthThresholdMarginPk").doubleValue()
    );

    thresholdsInitialized = true;
}

bool QosEventMonitor::isBrownoutWindow(
    double delayMeanSeconds,
    bool hasDelay,
    int packetCount,
    double throughputBps,
    double queueLengthPackets,
    int& basisCode
) const
{
    bool delayBad = hasDelay && delayThresholdSeconds >= 0 && delayMeanSeconds >= delayThresholdSeconds;
    bool deliveryBad = packetCountFloor >= 0 && packetCount <= packetCountFloor;
    bool throughputBad = throughputFloorBps >= 0 && throughputBps <= throughputFloorBps;
    bool queueBad = queueLengthThresholdPackets >= 0 && queueLengthPackets >= queueLengthThresholdPackets;

    basisCode = 0;
    if (delayBad)
        basisCode |= 1;
    if (deliveryBad || throughputBad)
        basisCode |= 2;
    if (queueBad)
        basisCode |= 4;

    return (delayBad && (deliveryBad || throughputBad || queueBad))
        || (queueBad && (deliveryBad || throughputBad));
}

void QosEventMonitor::recordWindowVectors(
    double delayMeanSeconds,
    bool hasDelay,
    int packetCount,
    double throughputBps,
    double queueLengthPackets,
    bool brownout
)
{
    probeDelayMeanVector.record(hasDelay ? delayMeanSeconds : -1);
    probePacketCountVector.record(packetCount);
    probeThroughputVector.record(throughputBps);
    queueLengthVector.record(queueLengthPackets);
    brownoutWindowVector.record(brownout ? 1 : 0);
    consecutiveBrownoutVector.record(consecutiveBrownoutWindows);
}

void QosEventMonitor::resetIntervalTelemetry()
{
    intervalTelemetry = IntervalTelemetry();
}

} // namespace dissertationsim::controller
