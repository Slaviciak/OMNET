// Project-local runtime controller for a small AI-MRCE prototype family.
//
// This class implements custom dissertation logic that sits above standard INET
// OSPF behavior. It periodically samples a compact telemetry set from the
// regionalbackbone congestion scenario, computes a conservative rule-based or
// exported runtime-model decision score, and can trigger a conservative
// project-local protective reroute abstraction.
//
// Important scope note:
// - This is a runtime prototype, not a production routing stack.
// - It does not alter OSPF internals or advertise custom LSAs.
// - Its FRR-like mode installs explicit host-specific repair routes as an
//   abstraction of preinstalled local protection, not as a protocol-standard
//   Fast Reroute implementation.
// - It depends partly on simulator-default behavior, especially the monitored
//   interface queue implementation exposed by the current INET version.

#ifndef __DISSERTATIONSIM_AIMRCECONTROLLER_H
#define __DISSERTATIONSIM_AIMRCECONTROLLER_H

#include <string>
#include <vector>

#include <omnetpp.h>

namespace inet {
class IIpv4RoutingTable;
class Ipv4Address;
class NetworkInterface;
namespace queueing {
class IPacketCollection;
}
} // namespace inet

namespace dissertationsim::controller {

/**
 * Project-local runtime AI-MRCE prototype family for predictive protection
 * experiments.
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
        LINEAR_SVM,
        SHALLOW_TREE,
    };

    enum class ProtectionAction
    {
        ADMIN_WITHDRAWAL,
        LOCAL_REPAIR_STATIC_ROUTES,
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

    // Compact linear-model artifact used by the runtime prototype family.
    // Logistic regression and linear SVM share the same feature preprocessing
    // export path so the deployment logic stays simple and auditable.
    struct RuntimeLinearModel
    {
        std::string sourcePath;
        std::string positiveLabel = "protect";
        std::string scoreTransform;
        double intercept = 0;
        double threshold = 0.5;
        std::vector<RuntimeFeatureParameter> features;
    };

    // Tree runtime features reuse the same observable telemetry names but need
    // only the imputation values because scaling is not part of the tree path.
    struct RuntimeTreeFeatureParameter
    {
        std::string name;
        double imputeValue = 0;
    };

    // Small decision-tree deployment artifact. This remains a project-local
    // prototype and is intentionally limited to shallow transparent trees.
    struct RuntimeTreeNode
    {
        int nodeIndex = -1;
        int featureIndex = -1;
        double threshold = 0;
        int leftIndex = -1;
        int rightIndex = -1;
        double positiveScore = 0;
        bool isLeaf = false;
    };

    struct RuntimeTreeModel
    {
        std::string sourcePath;
        std::string positiveLabel = "protect";
        double threshold = 0.5;
        std::vector<RuntimeTreeFeatureParameter> features;
        std::vector<RuntimeTreeNode> nodes;
    };

    // One explicit static repair route to be installed when AI-MRCE activates.
    // Each item names a router, that router's outgoing interface, the peer
    // interface used as gateway, and the destination host interface. Keeping
    // this route list in scenario config makes the protection path auditable.
    struct LocalRepairRouteSpec
    {
        std::string routerModule;
        std::string outputInterfaceModule;
        std::string gatewayInterfaceModule;
        std::string destinationInterfaceModule;
    };

    omnetpp::cMessage *evaluationTimer = nullptr;
    omnetpp::simsignal_t packetReceivedSignal = SIMSIGNAL_NULL;
    inet::queueing::IPacketCollection *protectedQueue = nullptr;
    omnetpp::cModule *probeReceiverModule = nullptr;
    DecisionMode decisionMode = DecisionMode::RULE_BASED;
    ProtectionAction protectionAction = ProtectionAction::ADMIN_WITHDRAWAL;
    RuntimeLinearModel linearModel;
    RuntimeTreeModel treeModel;
    std::vector<LocalRepairRouteSpec> localRepairRouteSpecs;
    IntervalTelemetry intervalTelemetry;
    bool protectionActive = false;
    bool repairRoutesInstalled = false;
    int repairRouteCount = 0;
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
    omnetpp::cOutVector repairRoutesInstalledVector;

  protected:
    virtual void initialize() override;
    virtual void handleMessage(omnetpp::cMessage *message) override;
    virtual void finish() override;
    virtual void receiveSignal(omnetpp::cComponent *source, omnetpp::simsignal_t signalID, omnetpp::cObject *object, omnetpp::cObject *details) override;

    DecisionMode parseDecisionMode(const char *value) const;
    ProtectionAction parseProtectionAction(const char *value) const;
    std::vector<LocalRepairRouteSpec> parseLocalRepairRouteSpecs(const std::string& rawValue) const;
    inet::NetworkInterface *resolveInterface(const char *modulePath) const;
    inet::IIpv4RoutingTable *resolveIpv4RoutingTable(const char *modulePath) const;
    inet::Ipv4Address resolveInterfaceIpv4Address(const char *modulePath) const;
    inet::queueing::IPacketCollection *resolveQueue(const char *modulePath) const;
    omnetpp::cModule *resolveModule(const char *modulePath, const char *purpose) const;
    std::string resolveParameterFilePath(const char *parameterName) const;
    // Loads the exported deployment artifact, not an evaluation report.
    void loadRuntimeLinearModel();
    void loadRuntimeTreeModel();
    // Samples the current queue state and the most recent probe interval.
    FeatureSnapshot collectFeatureSnapshot() const;
    // Interpretable baseline score used as the non-ML runtime reference.
    double computeRuleBasedRisk(const FeatureSnapshot& snapshot) const;
    // Runtime inference paths using exported deployment artifacts only.
    double computeLinearModelRisk(const FeatureSnapshot& snapshot) const;
    double computeShallowTreeRisk(const FeatureSnapshot& snapshot) const;
    double lookupFeatureValue(const FeatureSnapshot& snapshot, const std::string& featureName, bool& available) const;
    // Periodic controller cycle that applies debouncing before protection.
    void evaluateCycle();
    // Protective action is selected by configuration. The dissertation-core
    // regional branch uses a project-local FRR-like local-repair abstraction;
    // administrative withdrawal remains available as a conservative reference.
    void activateProtection();
    void administrativelyWithdraw(const char *modulePath);
    void activateLocalRepairStaticRoutes();
    bool installLocalRepairRoute(const LocalRepairRouteSpec& spec);
    void resetIntervalTelemetry();
    void recordVectors(const FeatureSnapshot& snapshot, double riskScore, bool decisionPositive);
};

} // namespace dissertationsim::controller

#endif
