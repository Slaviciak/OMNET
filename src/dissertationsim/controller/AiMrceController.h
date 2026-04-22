// Project-local runtime controller for the first AI-MRCE prototype.
//
// This class implements custom dissertation logic that sits above standard INET
// OSPF behavior. It periodically samples a compact telemetry set from the
// regionalbackbone congestion scenario, computes either a rule-based risk score
// or an exported logistic-regression score, and can trigger a conservative
// protective action through administrative interface withdrawal.
//
// Important scope note:
// - This is a runtime prototype, not a production routing stack.
// - It does not alter OSPF internals or advertise custom LSAs.
// - It depends partly on simulator-default behavior, especially the monitored
//   interface queue implementation exposed by the current INET version.

#ifndef __DISSERTATIONSIM_AIMRCECONTROLLER_H
#define __DISSERTATIONSIM_AIMRCECONTROLLER_H

#include <string>
#include <vector>

#include <omnetpp.h>

namespace inet {
class NetworkInterface;
namespace queueing {
class IPacketCollection;
}
} // namespace inet

namespace dissertationsim::controller {

/**
 * First runtime AI-MRCE prototype for predictive protection experiments.
 *
 * Experimentally, the controller represents a compact decision point watching
 * a single protected corridor. It intentionally uses only telemetry that is
 * observable in the current platform without deep protocol modification:
 * queue occupancy plus probe-flow reception statistics.
 */
class AiMrceController : public omnetpp::cSimpleModule, public omnetpp::cListener
{
  protected:
    enum class DecisionMode
    {
        RULE_BASED,
        LOGISTIC_REGRESSION,
    };

    // Probe-flow telemetry accumulated between controller evaluations.
    // The first prototype uses receiver-side observations instead of protocol-
    // internal OSPF state so the runtime logic stays auditable and portable.
    struct IntervalTelemetry
    {
        int probePacketCount = 0;
        double probeReceivedBits = 0;
        double probeDelaySumSeconds = 0;
        int probeDelaySamples = 0;
    };

    // Compact feature vector evaluated once per controller cycle. Queue state
    // comes from the current simulator queue implementation; probe metrics come
    // from the designated receiver application.
    struct FeatureSnapshot
    {
        double queueLengthPackets = 0;
        double queueBitLength = 0;
        double probePacketCount = 0;
        double probeThroughputBps = 0;
        double probeDelayMeanSeconds = -1;
        bool hasProbeDelay = false;
    };

    // Runtime deployment parameters exported from offline training. This keeps
    // sklearn out of OMNeT++ while preserving explicit feature provenance.
    struct RuntimeFeatureParameter
    {
        std::string name;
        double coefficient = 0;
        double mean = 0;
        double scale = 1;
        double imputeValue = 0;
    };

    // Minimal binary logistic-regression artifact used by the runtime
    // prototype. The main methodological evaluation remains offline.
    struct RuntimeLogisticModel
    {
        std::string sourcePath;
        std::string positiveLabel = "protect";
        double intercept = 0;
        double threshold = 0.5;
        std::vector<RuntimeFeatureParameter> features;
    };

    omnetpp::cMessage *evaluationTimer = nullptr;
    omnetpp::simsignal_t packetReceivedSignal = SIMSIGNAL_NULL;
    inet::queueing::IPacketCollection *protectedQueue = nullptr;
    omnetpp::cModule *probeReceiverModule = nullptr;
    DecisionMode decisionMode = DecisionMode::RULE_BASED;
    RuntimeLogisticModel logisticModel;
    IntervalTelemetry intervalTelemetry;
    bool protectionActive = false;
    int positiveDecisionStreak = 0;
    omnetpp::simtime_t protectionActivationTime = omnetpp::simtime_t(-1);
    double lastRiskScore = 0;
    bool lastDecisionPositive = false;

    // These vectors expose both raw runtime observations and controller state
    // transitions so later analysis can separate telemetry behavior from the
    // custom AI-MRCE decision logic itself.
    omnetpp::cOutVector queueLengthVector;
    omnetpp::cOutVector queueBitLengthVector;
    omnetpp::cOutVector probeDelayMeanVector;
    omnetpp::cOutVector probeThroughputVector;
    omnetpp::cOutVector probePacketCountVector;
    omnetpp::cOutVector riskScoreVector;
    omnetpp::cOutVector decisionPositiveVector;
    omnetpp::cOutVector positiveDecisionStreakVector;
    omnetpp::cOutVector protectionActiveVector;

  protected:
    virtual void initialize() override;
    virtual void handleMessage(omnetpp::cMessage *message) override;
    virtual void finish() override;
    virtual void receiveSignal(omnetpp::cComponent *source, omnetpp::simsignal_t signalID, omnetpp::cObject *object, omnetpp::cObject *details) override;

    DecisionMode parseDecisionMode(const char *value) const;
    inet::NetworkInterface *resolveInterface(const char *modulePath) const;
    inet::queueing::IPacketCollection *resolveQueue(const char *modulePath) const;
    omnetpp::cModule *resolveModule(const char *modulePath, const char *purpose) const;
    std::string resolveParameterFilePath(const char *parameterName) const;
    // Loads the exported deployment artifact, not an evaluation report.
    void loadRuntimeLogisticModel();
    // Samples the current queue state and the most recent probe interval.
    FeatureSnapshot collectFeatureSnapshot() const;
    // Interpretable baseline score used as the non-ML runtime reference.
    double computeRuleBasedRisk(const FeatureSnapshot& snapshot) const;
    // Runtime inference path using exported coefficients only.
    double computeLogisticRisk(const FeatureSnapshot& snapshot) const;
    double lookupFeatureValue(const FeatureSnapshot& snapshot, const RuntimeFeatureParameter& feature, bool& available) const;
    // Periodic controller cycle that applies debouncing before protection.
    void evaluateCycle();
    // First-step protective action: ordinary administrative withdrawal of the
    // preferred span rather than any custom OSPF extension.
    void activateProtection();
    void administrativelyWithdraw(const char *modulePath);
    void resetIntervalTelemetry();
    void recordVectors(const FeatureSnapshot& snapshot, double riskScore, bool decisionPositive);
};

} // namespace dissertationsim::controller

#endif
