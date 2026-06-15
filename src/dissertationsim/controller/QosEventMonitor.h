// Passive Scenario C QoS-event monitor.
//
// This module records a compact offline event reference for the congestion /
// queue-buildup scenario. It observes receiver-side probe delivery and the
// protected queue, then writes scalars for the first sustained QoS brownout
// crossing. It does not feed AI-MRCE, BFD-like detection, or repair routing.

#ifndef __DISSERTATIONSIM_QOSEVENTMONITOR_H
#define __DISSERTATIONSIM_QOSEVENTMONITOR_H

#include <omnetpp.h>

namespace inet {
namespace queueing {
class IPacketCollection;
}
} // namespace inet

namespace dissertationsim::controller {

class QosEventMonitor : public omnetpp::cSimpleModule, public omnetpp::cListener
{
  protected:
    struct IntervalTelemetry
    {
        int probePacketCount = 0;
        double probeReceivedBits = 0;
        double probeDelaySumSeconds = 0;
        int probeDelaySamples = 0;
    };

    omnetpp::cMessage *evaluationTimer = nullptr;
    omnetpp::simsignal_t packetReceivedSignal = -1;
    omnetpp::cModule *probeReceiverModule = nullptr;
    inet::queueing::IPacketCollection *protectedQueue = nullptr;

    IntervalTelemetry intervalTelemetry;
    double baselineDelaySum = 0;
    int baselineDelaySamples = 0;
    double baselineQueueLengthSum = 0;
    int baselineQueueLengthSamples = 0;
    double baselinePacketCountSum = 0;
    int baselinePacketCountSamples = 0;
    double baselineThroughputSumBps = 0;
    int baselineThroughputSamples = 0;

    bool thresholdsInitialized = false;
    double delayThresholdSeconds = -1;
    double packetCountFloor = -1;
    double throughputFloorBps = -1;
    double queueLengthThresholdPackets = -1;

    int consecutiveBrownoutWindows = 0;
    omnetpp::simtime_t brownoutStreakStart = -1;
    bool qosEventDetected = false;
    omnetpp::simtime_t qosEventTime = -1;
    int qosEventDetectionBasisCode = 0;

    omnetpp::cOutVector probeDelayMeanVector;
    omnetpp::cOutVector probePacketCountVector;
    omnetpp::cOutVector probeThroughputVector;
    omnetpp::cOutVector queueLengthVector;
    omnetpp::cOutVector brownoutWindowVector;
    omnetpp::cOutVector consecutiveBrownoutVector;

  protected:
    virtual void initialize() override;
    virtual void handleMessage(omnetpp::cMessage *message) override;
    virtual void receiveSignal(omnetpp::cComponent *source, omnetpp::simsignal_t signalID, omnetpp::cObject *object, omnetpp::cObject *details) override;
    virtual void finish() override;

    omnetpp::cModule *resolveModule(const char *modulePath, const char *purpose) const;
    inet::queueing::IPacketCollection *resolveQueue(const char *modulePath) const;
    void evaluateWindow();
    void initializeThresholdsIfNeeded();
    bool isBrownoutWindow(double delayMeanSeconds, bool hasDelay, int packetCount, double throughputBps, double queueLengthPackets, int& basisCode) const;
    void recordWindowVectors(double delayMeanSeconds, bool hasDelay, int packetCount, double throughputBps, double queueLengthPackets, bool brownout);
    void resetIntervalTelemetry();
};

} // namespace dissertationsim::controller

#endif
