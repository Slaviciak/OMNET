// Implementation of a small AI-MRCE runtime prototype family.
//
// The controller is intentionally conservative. It reuses ordinary OMNeT++ /
// INET control points, consumes an explicit exported runtime model artifact
// when configured for logistic regression, and avoids any deep changes to
// OSPF internals. The goal is an experimentally useful and scientifically
// transparent runtime prototype family rather than a full routing product.

#include "AiMrceController.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "omnetpp/cconfiguration.h"
#include "inet/common/packet/Packet.h"
#include "inet/networklayer/common/NetworkInterface.h"
#include "inet/queueing/contract/IPacketCollection.h"

using namespace omnetpp;

namespace {

double clamp01(double value)
{
    if (value < 0)
        return 0;
    if (value > 1)
        return 1;
    return value;
}

std::string trim(const std::string& value)
{
    auto begin = value.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos)
        return "";
    auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(begin, end - begin + 1);
}

std::string toLower(const std::string& value)
{
    auto result = value;
    std::transform(result.begin(), result.end(), result.begin(), [](unsigned char ch) { return std::tolower(ch); });
    return result;
}

std::vector<std::string> splitCsvLine(const std::string& line)
{
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, ','))
        fields.push_back(trim(field));
    return fields;
}

double parseCsvDouble(const std::string& rawValue, const char *fieldName)
{
    try {
        return std::stod(rawValue);
    }
    catch (const std::exception&) {
        throw cRuntimeError("Cannot parse '%s' as a numeric value for field '%s'", rawValue.c_str(), fieldName);
    }
}

int parseCsvInt(const std::string& rawValue, const char *fieldName)
{
    try {
        return std::stoi(rawValue);
    }
    catch (const std::exception&) {
        throw cRuntimeError("Cannot parse '%s' as an integer value for field '%s'", rawValue.c_str(), fieldName);
    }
}

} // namespace

namespace dissertationsim::controller {

Define_Module(AiMrceController);

void AiMrceController::initialize()
{
    simtime_t startTime = par("startTime");
    simtime_t evaluationInterval = par("evaluationInterval");
    auto activationCycles = par("activationConsecutiveCycles").intValue();
    simtime_t probeSendInterval = par("probeSendInterval");
    double probePacketLength = par("probePacketLength").doubleValue();
    double queueLengthThreshold = par("queueLengthThresholdPk").doubleValue();
    simtime_t delayThreshold = par("delayThreshold");
    auto throughputFloorRatio = par("throughputFloorRatio").doubleValue();
    auto packetCountFloorRatio = par("packetCountFloorRatio").doubleValue();
    auto ruleRiskThreshold = par("ruleRiskThreshold").doubleValue();

    if (startTime < 0)
        throw cRuntimeError("startTime must be non-negative");
    if (evaluationInterval <= 0)
        throw cRuntimeError("evaluationInterval must be positive");
    if (activationCycles <= 0)
        throw cRuntimeError("activationConsecutiveCycles must be positive");
    if (probeSendInterval <= 0)
        throw cRuntimeError("probeSendInterval must be positive");
    if (probePacketLength <= 0)
        throw cRuntimeError("probePacketLength must be positive");
    if (queueLengthThreshold <= 0)
        throw cRuntimeError("queueLengthThresholdPk must be positive");
    if (delayThreshold <= 0)
        throw cRuntimeError("delayThreshold must be positive");
    if (throughputFloorRatio <= 0 || throughputFloorRatio > 1)
        throw cRuntimeError("throughputFloorRatio must be in the range (0, 1]");
    if (packetCountFloorRatio <= 0 || packetCountFloorRatio > 1)
        throw cRuntimeError("packetCountFloorRatio must be in the range (0, 1]");
    if (ruleRiskThreshold < 0 || ruleRiskThreshold > 1)
        throw cRuntimeError("ruleRiskThreshold must be in the range [0, 1]");

    decisionMode = parseDecisionMode(par("decisionMode"));
    protectedQueue = resolveQueue(par("protectedQueueModule"));
    probeReceiverModule = resolveModule(par("probeReceiverModule"), "probe receiver module");
    packetReceivedSignal = registerSignal("packetReceived");
    probeReceiverModule->subscribe(packetReceivedSignal, this);

    if (decisionMode == DecisionMode::LOGISTIC_REGRESSION || decisionMode == DecisionMode::LINEAR_SVM)
        loadRuntimeLinearModel();
    else if (decisionMode == DecisionMode::SHALLOW_TREE)
        loadRuntimeTreeModel();

    queueLengthVector.setName("observedQueueLengthPk");
    queueBitLengthVector.setName("observedQueueBitLengthB");
    probeDelayMeanVector.setName("observedProbeDelayMeanS");
    probeThroughputVector.setName("observedProbeThroughputBps");
    probePacketCountVector.setName("observedProbePacketCount");
    riskScoreVector.setName("riskScore");
    decisionPositiveVector.setName("decisionPositive");
    positiveDecisionStreakVector.setName("positiveDecisionStreak");
    protectionActiveVector.setName("protectionActive");

    WATCH(protectionActive);
    WATCH(positiveDecisionStreak);
    WATCH(protectionActivationTime);
    WATCH(lastRiskScore);
    WATCH(lastDecisionPositive);

    protectionActiveVector.record(0);

    // The first evaluation is scheduled one interval after startTime so each
    // controller cycle summarizes a full observation window.
    evaluationTimer = new cMessage("aiMrceEvaluationTimer");
    scheduleAt(startTime + evaluationInterval, evaluationTimer);
}

void AiMrceController::handleMessage(cMessage *message)
{
    if (message != evaluationTimer)
        throw cRuntimeError("Unexpected message received by AiMrceController");

    evaluateCycle();
    scheduleAt(simTime() + par("evaluationInterval"), evaluationTimer);
}

void AiMrceController::finish()
{
    cancelAndDelete(evaluationTimer);
    evaluationTimer = nullptr;

    recordScalar("protectionActivated", protectionActive);
    recordScalar("protectionActivationTime", protectionActivationTime >= SIMTIME_ZERO ? protectionActivationTime.dbl() : -1);
    recordScalar("lastRiskScore", lastRiskScore);
    recordScalar("lastDecisionPositive", lastDecisionPositive);
}

void AiMrceController::receiveSignal(cComponent *source, simsignal_t signalID, cObject *object, cObject *details)
{
    if (signalID != packetReceivedSignal || source != probeReceiverModule)
        return;

    auto packet = dynamic_cast<inet::Packet *>(object);
    if (packet == nullptr)
        return;

    // Probe-flow telemetry is intentionally collected at the receiver because
    // it captures observable loss/delay symptoms without coupling the runtime
    // prototype to protocol internals.
    intervalTelemetry.probePacketCount++;
    intervalTelemetry.probeReceivedBits += packet->getBitLength();
    intervalTelemetry.probeDelaySumSeconds += (simTime() - packet->getCreationTime()).dbl();
    intervalTelemetry.probeDelaySamples++;
}

AiMrceController::DecisionMode AiMrceController::parseDecisionMode(const char *value) const
{
    auto mode = toLower(value);
    if (mode == "rulebased")
        return DecisionMode::RULE_BASED;
    if (mode == "logisticregression")
        return DecisionMode::LOGISTIC_REGRESSION;
    if (mode == "linearsvm")
        return DecisionMode::LINEAR_SVM;
    if (mode == "shallowtree")
        return DecisionMode::SHALLOW_TREE;
    throw cRuntimeError("Unsupported decisionMode '%s'", value);
}

inet::NetworkInterface *AiMrceController::resolveInterface(const char *modulePath) const
{
    auto module = getModuleByPath(modulePath);
    if (module == nullptr)
        throw cRuntimeError("Cannot find target interface module '%s'", modulePath);
    return check_and_cast<inet::NetworkInterface *>(module);
}

inet::queueing::IPacketCollection *AiMrceController::resolveQueue(const char *modulePath) const
{
    auto module = getModuleByPath(modulePath);
    if (module == nullptr)
        throw cRuntimeError("Cannot find protected queue module '%s'", modulePath);
    auto queue = dynamic_cast<inet::queueing::IPacketCollection *>(module);
    if (queue == nullptr)
        throw cRuntimeError("Protected queue module '%s' does not implement inet::queueing::IPacketCollection", modulePath);
    return queue;
}

cModule *AiMrceController::resolveModule(const char *modulePath, const char *purpose) const
{
    auto module = getModuleByPath(modulePath);
    if (module == nullptr)
        throw cRuntimeError("Cannot find %s '%s'", purpose, modulePath);
    return module;
}

std::string AiMrceController::resolveParameterFilePath(const char *parameterName) const
{
    auto configuredPath = par(parameterName).stdstringValue();
    if (configuredPath.empty())
        return configuredPath;

    const auto& parameterEntry = getEnvir()->getConfigEx()->getParameterEntry(getFullPath().c_str(), parameterName, true);
    return cConfiguration::adjustPath(configuredPath.c_str(), parameterEntry.getBaseDirectory(), nullptr);
}

void AiMrceController::loadRuntimeLinearModel()
{
    auto configuredPath = par("runtimeModelFile").stdstringValue();
    if (configuredPath.empty())
        throw cRuntimeError("runtimeModelFile must be configured for learned AI-MRCE decision modes");

    linearModel = RuntimeLinearModel();
    linearModel.sourcePath = resolveParameterFilePath("runtimeModelFile");

    std::ifstream input(linearModel.sourcePath.c_str());
    if (!input.is_open())
        throw cRuntimeError("Cannot open runtime linear model file '%s' (resolved from '%s')", linearModel.sourcePath.c_str(), configuredPath.c_str());

    std::string line;
    auto lineNumber = 0;
    while (std::getline(input, line)) {
        lineNumber++;
        auto trimmedLine = trim(line);
        if (trimmedLine.empty() || trimmedLine[0] == '#')
            continue;

        auto fields = splitCsvLine(trimmedLine);
        if (fields.size() < 3)
            throw cRuntimeError("Malformed runtime model line %d in '%s'", lineNumber, linearModel.sourcePath.c_str());
        fields.resize(7);
        if (fields[0] == "row_type")
            continue;

        if (fields[0] == "meta") {
            if (fields[1] == "positive_label")
                linearModel.positiveLabel = fields[2];
            else if (fields[1] == "threshold")
                linearModel.threshold = parseCsvDouble(fields[2], "threshold");
            else if (fields[1] == "intercept")
                linearModel.intercept = parseCsvDouble(fields[2], "intercept");
            else if (fields[1] == "score_semantics")
                linearModel.scoreTransform = fields[2];
            continue;
        }

        if (fields[0] == "feature") {
            // The runtime artifact carries everything needed for deterministic
            // C++ scoring: feature names, normalization parameters, and the
            // fitted coefficient for each supported runtime feature.
            RuntimeFeatureParameter feature;
            feature.name = fields[1];
            feature.coefficient = parseCsvDouble(fields[3], "coefficient");
            feature.mean = parseCsvDouble(fields[4], "mean");
            feature.scale = parseCsvDouble(fields[5], "scale");
            feature.imputeValue = parseCsvDouble(fields[6], "impute_value");
            linearModel.features.push_back(feature);
            continue;
        }

        throw cRuntimeError("Unsupported runtime model row type '%s' at line %d", fields[0].c_str(), lineNumber);
    }

    if (linearModel.features.empty())
        throw cRuntimeError("Runtime linear model '%s' does not define any features", linearModel.sourcePath.c_str());

    if (linearModel.scoreTransform.empty()) {
        if (decisionMode == DecisionMode::LOGISTIC_REGRESSION)
            linearModel.scoreTransform = "logistic_probability";
        else
            linearModel.scoreTransform = "sigmoid_of_margin";
    }
}

void AiMrceController::loadRuntimeTreeModel()
{
    auto configuredPath = par("runtimeModelFile").stdstringValue();
    if (configuredPath.empty())
        throw cRuntimeError("runtimeModelFile must be configured when decisionMode=shallowTree");

    treeModel = RuntimeTreeModel();
    treeModel.sourcePath = resolveParameterFilePath("runtimeModelFile");

    std::ifstream input(treeModel.sourcePath.c_str());
    if (!input.is_open())
        throw cRuntimeError("Cannot open runtime tree model file '%s' (resolved from '%s')", treeModel.sourcePath.c_str(), configuredPath.c_str());

    std::string line;
    auto lineNumber = 0;
    while (std::getline(input, line)) {
        lineNumber++;
        auto trimmedLine = trim(line);
        if (trimmedLine.empty() || trimmedLine[0] == '#')
            continue;

        auto fields = splitCsvLine(trimmedLine);
        if (fields.size() < 3)
            throw cRuntimeError("Malformed runtime tree line %d in '%s'", lineNumber, treeModel.sourcePath.c_str());
        fields.resize(11);
        if (fields[0] == "row_type")
            continue;

        if (fields[0] == "meta") {
            if (fields[1] == "positive_label")
                treeModel.positiveLabel = fields[2];
            else if (fields[1] == "threshold")
                treeModel.threshold = parseCsvDouble(fields[2], "threshold");
            continue;
        }

        if (fields[0] == "feature") {
            RuntimeTreeFeatureParameter feature;
            auto featureIndex = parseCsvInt(fields[4], "feature_index");
            if (featureIndex != static_cast<int>(treeModel.features.size()))
                throw cRuntimeError("Runtime tree feature indices must be sequential starting at 0 in '%s'", treeModel.sourcePath.c_str());
            feature.name = fields[1];
            feature.imputeValue = parseCsvDouble(fields[8], "impute_value");
            treeModel.features.push_back(feature);
            continue;
        }

        if (fields[0] == "node") {
            RuntimeTreeNode node;
            node.nodeIndex = parseCsvInt(fields[3], "node_index");
            if (node.nodeIndex != static_cast<int>(treeModel.nodes.size()))
                throw cRuntimeError("Runtime tree node indices must be sequential starting at 0 in '%s'", treeModel.sourcePath.c_str());
            node.featureIndex = parseCsvInt(fields[4], "feature_index");
            node.leftIndex = parseCsvInt(fields[6], "left_index");
            node.rightIndex = parseCsvInt(fields[7], "right_index");
            node.positiveScore = parseCsvDouble(fields[9], "positive_score");
            node.isLeaf = parseCsvInt(fields[10], "is_leaf") != 0;
            if (!node.isLeaf)
                node.threshold = parseCsvDouble(fields[5], "threshold");
            treeModel.nodes.push_back(node);
            continue;
        }

        throw cRuntimeError("Unsupported runtime tree row type '%s' at line %d", fields[0].c_str(), lineNumber);
    }

    if (treeModel.features.empty())
        throw cRuntimeError("Runtime tree model '%s' does not define any features", treeModel.sourcePath.c_str());
    if (treeModel.nodes.empty())
        throw cRuntimeError("Runtime tree model '%s' does not define any nodes", treeModel.sourcePath.c_str());
}

AiMrceController::FeatureSnapshot AiMrceController::collectFeatureSnapshot() const
{
    FeatureSnapshot snapshot;
    auto evaluationIntervalSeconds = par("evaluationInterval").doubleValue();

    // Queue occupancy is read directly from the current queue object. This is
    // useful telemetry for the experiment, but it still depends on the default
    // INET queue implementation configured in the scenario.
    snapshot.queueLengthPackets = protectedQueue->getNumPackets();
    snapshot.queueBitLength = protectedQueue->getTotalLength().get();
    snapshot.probePacketCount = intervalTelemetry.probePacketCount;
    snapshot.probeThroughputBps = evaluationIntervalSeconds > 0 ? intervalTelemetry.probeReceivedBits / evaluationIntervalSeconds : 0;
    snapshot.hasProbeDelay = intervalTelemetry.probeDelaySamples > 0;
    if (snapshot.hasProbeDelay)
        snapshot.probeDelayMeanSeconds = intervalTelemetry.probeDelaySumSeconds / intervalTelemetry.probeDelaySamples;
    return snapshot;
}

double AiMrceController::computeRuleBasedRisk(const FeatureSnapshot& snapshot) const
{
    auto evaluationIntervalSeconds = par("evaluationInterval").doubleValue();
    auto probeSendIntervalSeconds = par("probeSendInterval").doubleValue();
    auto probePacketLengthBytes = par("probePacketLength").doubleValue();
    auto expectedProbePacketCount = evaluationIntervalSeconds / probeSendIntervalSeconds;
    auto expectedProbeThroughputBps = (probePacketLengthBytes * 8.0) / probeSendIntervalSeconds;
    auto throughputFloorRatio = par("throughputFloorRatio").doubleValue();
    auto packetCountFloorRatio = par("packetCountFloorRatio").doubleValue();

    auto queueRisk = clamp01(snapshot.queueLengthPackets / par("queueLengthThresholdPk").doubleValue());

    // If the probe flow produced no received packets in the interval, the
    // controller treats delay as maximally risky. In this first prototype that
    // acts as a conservative starvation proxy rather than as a claim about
    // true unobserved packet delay.
    auto delayRisk = 1.0;
    if (snapshot.hasProbeDelay)
        delayRisk = clamp01(snapshot.probeDelayMeanSeconds / par("delayThreshold").doubleValue());

    auto throughputFloor = expectedProbeThroughputBps * throughputFloorRatio;
    auto throughputDenominator = std::max(1.0, expectedProbeThroughputBps - throughputFloor);
    auto throughputRisk = clamp01((expectedProbeThroughputBps - snapshot.probeThroughputBps) / throughputDenominator);

    auto packetCountFloor = expectedProbePacketCount * packetCountFloorRatio;
    auto packetCountDenominator = std::max(1.0, expectedProbePacketCount - packetCountFloor);
    auto packetCountRisk = clamp01((expectedProbePacketCount - snapshot.probePacketCount) / packetCountDenominator);

    return 0.40 * queueRisk + 0.40 * delayRisk + 0.10 * throughputRisk + 0.10 * packetCountRisk;
}

double AiMrceController::computeLinearModelRisk(const FeatureSnapshot& snapshot) const
{
    // Runtime inference uses the exported coefficients and preprocessing
    // parameters only. This keeps the deployment path deterministic and
    // separated from the richer offline sklearn evaluation environment.
    auto linearScore = linearModel.intercept;
    for (const auto& feature : linearModel.features) {
        auto available = true;
        auto value = lookupFeatureValue(snapshot, feature.name, available);
        if (!available)
            value = feature.imputeValue;
        auto scale = feature.scale == 0 ? 1.0 : feature.scale;
        auto normalized = (value - feature.mean) / scale;
        linearScore += feature.coefficient * normalized;
    }

    if (linearModel.scoreTransform == "sigmoid_of_margin" || linearModel.scoreTransform == "logistic_probability")
        return 1.0 / (1.0 + std::exp(-linearScore));

    return linearScore;
}

double AiMrceController::computeShallowTreeRisk(const FeatureSnapshot& snapshot) const
{
    // The tree path is kept intentionally small and explicit so later paper
    // writing can describe the deployment logic without invoking a black-box
    // runtime stack. Leaf scores are operational positive-class fractions
    // under scenario-conditioned supervision, not universal probabilities.
    auto currentNodeIndex = 0;
    auto safetyCounter = 0;
    while (safetyCounter < static_cast<int>(treeModel.nodes.size())) {
        const auto& node = treeModel.nodes[currentNodeIndex];
        if (node.isLeaf)
            return clamp01(node.positiveScore);

        if (node.featureIndex < 0 || node.featureIndex >= static_cast<int>(treeModel.features.size()))
            throw cRuntimeError("Runtime tree node %d references invalid feature index %d", node.nodeIndex, node.featureIndex);

        const auto& feature = treeModel.features[node.featureIndex];
        auto available = true;
        auto value = lookupFeatureValue(snapshot, feature.name, available);
        if (!available)
            value = feature.imputeValue;

        currentNodeIndex = value <= node.threshold ? node.leftIndex : node.rightIndex;
        if (currentNodeIndex < 0 || currentNodeIndex >= static_cast<int>(treeModel.nodes.size()))
            throw cRuntimeError("Runtime tree traversal reached invalid node index %d", currentNodeIndex);
        safetyCounter++;
    }

    throw cRuntimeError("Runtime tree traversal exceeded the expected node depth");
}

double AiMrceController::lookupFeatureValue(const FeatureSnapshot& snapshot, const std::string& featureName, bool& available) const
{
    available = true;

    if (featureName == "bottleneck_queue_length_last_pk")
        return snapshot.queueLengthPackets;
    if (featureName == "receiver_app0_e2e_delay_mean_s") {
        available = snapshot.hasProbeDelay;
        return snapshot.probeDelayMeanSeconds;
    }
    if (featureName == "receiver_app0_throughput_mean_bps")
        return snapshot.probeThroughputBps;
    if (featureName == "receiver_app0_packet_count")
        return snapshot.probePacketCount;

    throw cRuntimeError("Runtime model requested unsupported feature '%s'", featureName.c_str());
}

void AiMrceController::evaluateCycle()
{
    auto snapshot = collectFeatureSnapshot();

    double riskScore = 0;
    double decisionThreshold = 0;
    switch (decisionMode) {
        case DecisionMode::RULE_BASED:
            riskScore = computeRuleBasedRisk(snapshot);
            decisionThreshold = par("ruleRiskThreshold").doubleValue();
            break;
        case DecisionMode::LOGISTIC_REGRESSION:
        case DecisionMode::LINEAR_SVM:
            riskScore = computeLinearModelRisk(snapshot);
            decisionThreshold = linearModel.threshold;
            break;
        case DecisionMode::SHALLOW_TREE:
            riskScore = computeShallowTreeRisk(snapshot);
            decisionThreshold = treeModel.threshold;
            break;
    }
    auto decisionPositive = riskScore >= decisionThreshold;

    // Consecutive positive cycles provide simple hysteresis for the first
    // prototype so one noisy interval does not trigger protective action.
    if (decisionPositive)
        positiveDecisionStreak++;
    else
        positiveDecisionStreak = 0;

    if (!protectionActive && positiveDecisionStreak >= par("activationConsecutiveCycles").intValue())
        activateProtection();

    lastRiskScore = riskScore;
    lastDecisionPositive = decisionPositive;
    recordVectors(snapshot, riskScore, decisionPositive);
    resetIntervalTelemetry();
}

void AiMrceController::activateProtection()
{
    if (protectionActive)
        return;

    protectionActive = true;
    protectionActivationTime = simTime();

    // The first protective action is deliberately conservative: ordinary
    // administrative interface withdrawal on the preferred corridor. This is a
    // project-local control mechanism, not a deep routing protocol extension.
    EV_INFO << "AI-MRCE activating protection on the monitored corridor at " << protectionActivationTime << endl;
    administrativelyWithdraw(par("firstInterfaceModule"));
    administrativelyWithdraw(par("secondInterfaceModule"));
}

void AiMrceController::administrativelyWithdraw(const char *modulePath)
{
    auto networkInterface = resolveInterface(modulePath);
    if (networkInterface->getState() == inet::NetworkInterface::DOWN)
        return;

    // This follows ordinary administrative interface-down semantics that OSPF
    // can react to in the simulation, rather than introducing custom LSAs.
    EV_INFO << "AI-MRCE administratively withdrawing interface " << networkInterface->getInterfaceFullPath() << endl;
    cMethodCallContextSwitcher contextSwitcher(networkInterface);
    networkInterface->setState(inet::NetworkInterface::DOWN);
}

void AiMrceController::resetIntervalTelemetry()
{
    intervalTelemetry = IntervalTelemetry();
}

void AiMrceController::recordVectors(const FeatureSnapshot& snapshot, double riskScore, bool decisionPositive)
{
    // Record both inputs and decisions so later analysis can separate observed
    // network symptoms from the custom runtime AI-MRCE logic. The riskScore
    // vector stores the family-specific bounded decision score; for example,
    // logistic regression yields a probability-like score, the linear-SVM path
    // stores a sigmoid-transformed margin, and the tree path stores a leaf
    // positive-score estimate. These are project-local controller metrics.
    queueLengthVector.record(snapshot.queueLengthPackets);
    queueBitLengthVector.record(snapshot.queueBitLength);
    probeDelayMeanVector.record(snapshot.hasProbeDelay ? snapshot.probeDelayMeanSeconds : -1);
    probeThroughputVector.record(snapshot.probeThroughputBps);
    probePacketCountVector.record(snapshot.probePacketCount);
    riskScoreVector.record(riskScore);
    decisionPositiveVector.record(decisionPositive ? 1 : 0);
    positiveDecisionStreakVector.record(positiveDecisionStreak);
    protectionActiveVector.record(protectionActive ? 1 : 0);
}

} // namespace dissertationsim::controller
