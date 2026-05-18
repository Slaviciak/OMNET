// Implementation of a small AI-MRCE runtime prototype family.
//
// The controller is intentionally conservative. It reuses ordinary OMNeT++ /
// INET control points, consumes explicit exported runtime model artifacts for
// learned AI-MRCE variants, and avoids any deep changes to OSPF internals. The
// optional BFD-like path is a local protected-span health / missed-probe
// safety-net detector that drives the same repair-route actuator; it is not an
// RFC-compliant BFD implementation.

#include "AiMrceController.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "omnetpp/cdataratechannel.h"
#include "omnetpp/cconfiguration.h"
#include "inet/common/packet/Packet.h"
#include "inet/networklayer/common/L3AddressResolver.h"
#include "inet/networklayer/common/NetworkInterface.h"
#include "inet/networklayer/contract/IRoute.h"
#include "inet/networklayer/contract/ipv4/Ipv4Address.h"
#include "inet/networklayer/ipv4/IIpv4RoutingTable.h"
#include "inet/networklayer/ipv4/Ipv4InterfaceData.h"
#include "inet/networklayer/ipv4/Ipv4Route.h"
#include "inet/queueing/contract/IPacketCollection.h"

using namespace omnetpp;

namespace {

constexpr const char *DECISION_MODE_RULE_BASED = "ruleBased";
constexpr const char *DECISION_MODE_LOGISTIC_REGRESSION = "logisticRegression";
constexpr const char *DECISION_MODE_LINEAR_SVM = "linearSvm";
constexpr const char *DECISION_MODE_SHALLOW_TREE = "shallowTree";
constexpr const char *DECISION_MODE_RULE_BASED_NORMALIZED = "rulebased";
constexpr const char *DECISION_MODE_LOGISTIC_REGRESSION_NORMALIZED = "logisticregression";
constexpr const char *DECISION_MODE_LINEAR_SVM_NORMALIZED = "linearsvm";
constexpr const char *DECISION_MODE_SHALLOW_TREE_NORMALIZED = "shallowtree";
constexpr const char *SUPPORTED_DECISION_MODES = "ruleBased, logisticRegression, linearSvm, shallowTree";

constexpr const char *PROTECTION_ACTION_ADMIN_WITHDRAWAL = "adminWithdrawal";
constexpr const char *PROTECTION_ACTION_LOCAL_REPAIR_STATIC_ROUTES = "localRepairStaticRoutes";
constexpr const char *PROTECTION_ACTION_ADMIN_WITHDRAWAL_NORMALIZED = "adminwithdrawal";
constexpr const char *PROTECTION_ACTION_LOCAL_REPAIR_STATIC_ROUTES_NORMALIZED = "localrepairstaticroutes";
constexpr const char *SUPPORTED_PROTECTION_ACTIONS = "adminWithdrawal, localRepairStaticRoutes";

constexpr const char *TRIGGER_SOURCE_NONE = "none";
constexpr const char *TRIGGER_SOURCE_AIMRCE = "aimrce";
constexpr const char *TRIGGER_SOURCE_BFD_LIKE = "bfd_like";
constexpr const char *TRIGGER_SOURCE_HYBRID_AIMRCE_FIRST = "hybrid_aimrce_first";
constexpr const char *TRIGGER_SOURCE_HYBRID_BFD_LIKE_FIRST = "hybrid_bfd_like_first";

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

std::vector<std::string> splitSemicolonList(const std::string& value)
{
    std::vector<std::string> items;
    std::stringstream stream(value);
    std::string item;
    while (std::getline(stream, item, ';')) {
        auto trimmedItem = trim(item);
        if (!trimmedItem.empty())
            items.push_back(trimmedItem);
    }
    return items;
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

template <typename FeatureParameter>
std::string joinFeatureNames(const std::vector<FeatureParameter>& features)
{
    std::stringstream featureNames;
    for (size_t i = 0; i < features.size(); i++) {
        if (i > 0)
            featureNames << ";";
        featureNames << features[i].name;
    }
    return featureNames.str();
}

} // namespace

namespace dissertationsim::controller {

Define_Module(AiMrceController);

void AiMrceController::initialize()
{
    enableAimrceDecision = par("enableAimrceDecision").boolValue();
    enableBfdLikeDetection = par("enableBfdLikeDetection").boolValue();
    simtime_t startTime = par("startTime");
    simtime_t evaluationInterval = par("evaluationInterval");
    auto activationCycles = par("activationConsecutiveCycles").intValue();
    simtime_t bfdLikeStartTime = par("bfdLikeStartTime");
    simtime_t bfdLikeDetectionInterval = par("bfdLikeDetectionInterval");
    auto bfdLikeDetectMultiplier = par("bfdLikeDetectMultiplier").intValue();
    auto bfdLikeExpectedProbeCount = par("bfdLikeExpectedProbeCount").intValue();
    hardFailureTime = par("hardFailureTime");
    simtime_t probeSendInterval = par("probeSendInterval");
    double probePacketLength = par("probePacketLength").doubleValue();
    double queueLengthThreshold = par("queueLengthThresholdPk").doubleValue();
    simtime_t delayThreshold = par("delayThreshold");
    simtime_t telemetryLogInterval = par("telemetryLogInterval");
    simtime_t decisionLogInterval = par("decisionLogInterval");
    auto throughputFloorRatio = par("throughputFloorRatio").doubleValue();
    auto packetCountFloorRatio = par("packetCountFloorRatio").doubleValue();
    auto ruleRiskThreshold = par("ruleRiskThreshold").doubleValue();

    validateControllerParameters(
        startTime,
        evaluationInterval,
        activationCycles,
        bfdLikeStartTime,
        bfdLikeDetectionInterval,
        bfdLikeDetectMultiplier,
        bfdLikeExpectedProbeCount,
        probeSendInterval,
        probePacketLength,
        queueLengthThreshold,
        delayThreshold,
        telemetryLogInterval,
        decisionLogInterval,
        throughputFloorRatio,
        packetCountFloorRatio,
        ruleRiskThreshold
    );

    initializeProtectionConfiguration();
    initializeTelemetryReferences();
    initializeRuntimePolicy();

    logInitializationSummary(evaluationInterval, activationCycles, bfdLikeDetectionInterval, bfdLikeDetectMultiplier);

    initializeVectorNames();
    initializeWatches();
    recordInitialVectorState();
    scheduleControllerTimers(startTime, evaluationInterval, bfdLikeStartTime, bfdLikeDetectionInterval);
}

void AiMrceController::validateControllerParameters(
    simtime_t startTime,
    simtime_t evaluationInterval,
    int activationCycles,
    simtime_t bfdLikeStartTime,
    simtime_t bfdLikeDetectionInterval,
    int bfdLikeDetectMultiplier,
    int bfdLikeExpectedProbeCount,
    simtime_t probeSendInterval,
    double probePacketLength,
    double queueLengthThreshold,
    simtime_t delayThreshold,
    simtime_t telemetryLogInterval,
    simtime_t decisionLogInterval,
    double throughputFloorRatio,
    double packetCountFloorRatio,
    double ruleRiskThreshold
) const
{
    if (!enableAimrceDecision && !enableBfdLikeDetection)
        throw cRuntimeError("At least one controller trigger must be enabled: enableAimrceDecision or enableBfdLikeDetection");
    if (startTime < 0)
        throw cRuntimeError("startTime must be non-negative");
    if (evaluationInterval <= 0)
        throw cRuntimeError("evaluationInterval must be positive");
    if (activationCycles <= 0)
        throw cRuntimeError("activationConsecutiveCycles must be positive");
    if (bfdLikeStartTime < 0)
        throw cRuntimeError("bfdLikeStartTime must be non-negative");
    if (bfdLikeDetectionInterval <= 0)
        throw cRuntimeError("bfdLikeDetectionInterval must be positive");
    if (bfdLikeDetectMultiplier <= 0)
        throw cRuntimeError("bfdLikeDetectMultiplier must be positive");
    if (bfdLikeExpectedProbeCount < 0)
        throw cRuntimeError("bfdLikeExpectedProbeCount must be non-negative");
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
    if (telemetryLogInterval <= 0)
        throw cRuntimeError("telemetryLogInterval must be positive");
    if (decisionLogInterval <= 0)
        throw cRuntimeError("decisionLogInterval must be positive");
}

void AiMrceController::initializeProtectionConfiguration()
{
    decisionMode = parseDecisionMode(par("decisionMode"));
    protectionAction = parseProtectionAction(par("protectionAction"));
    localRepairRouteSpecs = parseLocalRepairRouteSpecs(par("localRepairRouteSpecs").stdstringValue());
    if (protectionAction == ProtectionAction::LOCAL_REPAIR_STATIC_ROUTES && localRepairRouteSpecs.empty())
        throw cRuntimeError("localRepairRouteSpecs must define at least one route when protectionAction=localRepairStaticRoutes");
}

void AiMrceController::initializeTelemetryReferences()
{
    protectedQueue = resolveQueue(par("protectedQueueModule"));
    probeReceiverModule = resolveModule(par("probeReceiverModule"), "probe receiver module");
    packetReceivedSignal = registerSignal("packetReceived");
    probeReceiverModule->subscribe(packetReceivedSignal, this);
}

void AiMrceController::initializeRuntimePolicy()
{
    if (!enableAimrceDecision)
        return;

    if (decisionMode == DecisionMode::LOGISTIC_REGRESSION || decisionMode == DecisionMode::LINEAR_SVM) {
        loadRuntimeLinearModel();
        return;
    }
    if (decisionMode == DecisionMode::SHALLOW_TREE) {
        loadRuntimeTreeModel();
        return;
    }

    // Rule-based AI-MRCE has no deployment artifact to load. Recording this
    // explicitly helps later reports distinguish an intentional transparent
    // baseline policy from a learned-model loading failure.
    runtimeModelLoaded = false;
    runtimeModelFeatureCount = 0;
    runtimeModelThreshold = par("ruleRiskThreshold").doubleValue();
    if (par("verboseModelLoadingLogging").boolValue()) {
        EV_INFO << "[AI-MRCE:model] t=" << simTime().dbl()
                << "s model=ruleBased artifactRequired=0 loaded=0 fallback=0 "
                << "threshold=" << runtimeModelThreshold << endl;
    }
}

void AiMrceController::initializeVectorNames()
{
    queueLengthVector.setName("observedQueueLengthPk");
    queueBitLengthVector.setName("observedQueueBitLengthB");
    probeDelayMeanVector.setName("observedProbeDelayMeanS");
    probeThroughputVector.setName("observedProbeThroughputBps");
    probePacketCountVector.setName("observedProbePacketCount");
    riskScoreVector.setName("riskScore");
    decisionPositiveVector.setName("decisionPositive");
    positiveDecisionStreakVector.setName("positiveDecisionStreak");
    protectionActiveVector.setName("protectionActive");
    repairRoutesInstalledVector.setName("repairRoutesInstalled");
    protectionTriggerSourceCodeVector.setName("protectionTriggerSourceCode");
    bfdLikeMissedProbeCountVector.setName("bfdLikeMissedProbeCount");
    bfdLikeDetectionActiveVector.setName("bfdLikeDetectionActive");
    bfdLikeProtectedSpanUpVector.setName("bfdLikeProtectedSpanUp");
    bfdLikeModeledProbeLossProbabilityVector.setName("bfdLikeModeledProbeLossProbability");
    bfdLikeProbeMissedVector.setName("bfdLikeProbeMissed");
}

void AiMrceController::initializeWatches()
{
    WATCH(protectionActive);
    WATCH(enableAimrceDecision);
    WATCH(enableBfdLikeDetection);
    WATCH(protectionTriggerSourceCode);
    WATCH(repairRoutesInstalled);
    WATCH(repairRouteCount);
    WATCH(positiveDecisionStreak);
    WATCH(bfdLikeConsecutiveMissedProbeIntervals);
    WATCH(bfdLikeDetectionActivated);
    WATCH(bfdLikeProtectedSpanUpAtDetection);
    WATCH(bfdLikeDetectionTime);
    WATCH(protectionActivationTime);
    WATCH(repairRouteInstallTime);
    WATCH(lastRiskScore);
    WATCH(lastDecisionPositive);
    WATCH(activationRiskScore);
    WATCH(activationDecisionThreshold);
    WATCH(activationPositiveDecisionStreak);
}

void AiMrceController::recordInitialVectorState()
{
    protectionActiveVector.record(0);
    repairRoutesInstalledVector.record(0);
    protectionTriggerSourceCodeVector.record(0);
    bfdLikeMissedProbeCountVector.record(0);
    bfdLikeDetectionActiveVector.record(0);
    bfdLikeProtectedSpanUpVector.record(isBfdLikeProtectedSpanHealthy() ? 1 : 0);
    bfdLikeModeledProbeLossProbabilityVector.record(0);
    bfdLikeProbeMissedVector.record(0);
}

void AiMrceController::scheduleControllerTimers(simtime_t startTime, simtime_t evaluationInterval, simtime_t bfdLikeStartTime, simtime_t bfdLikeDetectionInterval)
{
    if (enableAimrceDecision) {
        // The first evaluation is scheduled one interval after startTime so
        // each controller cycle summarizes a full observation window.
        evaluationTimer = new cMessage("aiMrceEvaluationTimer");
        scheduleAt(startTime + evaluationInterval, evaluationTimer);
    }

    if (enableBfdLikeDetection) {
        // The BFD-like detector is intentionally separate from AI-MRCE scoring.
        // It observes protected-span interface/carrier state and keeps a
        // missed-probe fallback, then triggers the same local repair route
        // actuator as a reactive safety net.
        bfdLikeTimer = new cMessage("bfdLikeDetectionTimer");
        scheduleAt(bfdLikeStartTime + bfdLikeDetectionInterval, bfdLikeTimer);
    }

    if (hardFailureTime >= SIMTIME_ZERO && par("verboseTriggerLogging").boolValue()) {
        // Logging-only reference marker for demo/debug runs. This self-message
        // does not alter failure, routing, repair, or decision semantics.
        hardFailureLogTimer = new cMessage("aiMrceHardFailureReferenceLogTimer");
        scheduleAt(hardFailureTime, hardFailureLogTimer);
    }
}

void AiMrceController::handleMessage(cMessage *message)
{
    if (message == evaluationTimer) {
        evaluateCycle();
        scheduleAt(simTime() + par("evaluationInterval"), evaluationTimer);
        return;
    }

    if (message == bfdLikeTimer) {
        evaluateBfdLikeCycle();
        scheduleAt(simTime() + par("bfdLikeDetectionInterval"), bfdLikeTimer);
        return;
    }

    if (message == hardFailureLogTimer) {
        logHardFailureReference();
        return;
    }

    throw cRuntimeError("Unexpected message received by AiMrceController");
}

void AiMrceController::finish()
{
    cancelControllerTimers();
    recordProtectionScalars();
    recordRuntimeModelScalars();
    recordBfdLikeScalars();
    recordScalar("hardFailureTime", hardFailureTime >= SIMTIME_ZERO ? hardFailureTime.dbl() : -1);
    recordActivationScalars();
    recordScalar("lastRiskScore", lastRiskScore);
    recordScalar("lastDecisionPositive", lastDecisionPositive);
}

void AiMrceController::cancelControllerTimers()
{
    if (evaluationTimer != nullptr) {
        cancelAndDelete(evaluationTimer);
        evaluationTimer = nullptr;
    }
    if (bfdLikeTimer != nullptr) {
        cancelAndDelete(bfdLikeTimer);
        bfdLikeTimer = nullptr;
    }
    if (hardFailureLogTimer != nullptr) {
        cancelAndDelete(hardFailureLogTimer);
        hardFailureLogTimer = nullptr;
    }
}

void AiMrceController::recordProtectionScalars()
{
    recordScalar("protectionActivated", protectionActive);
    recordScalar("protectionActivationTime", protectionActivationTime >= SIMTIME_ZERO ? protectionActivationTime.dbl() : -1);
    recordScalar("protectionTriggerSourceCode", protectionTriggerSourceCode);
    recordScalar("protectionActionCode", protectionAction == ProtectionAction::LOCAL_REPAIR_STATIC_ROUTES ? 1 : 0);
    recordScalar("repairRoutesInstalled", repairRoutesInstalled);
    recordScalar("repairRouteCount", repairRouteCount);
    recordScalar("repairRouteInstallTime", repairRouteInstallTime >= SIMTIME_ZERO ? repairRouteInstallTime.dbl() : -1);
    recordScalar("enableAimrceDecision", enableAimrceDecision);
    recordScalar("enableBfdLikeDetection", enableBfdLikeDetection);
}

void AiMrceController::recordRuntimeModelScalars()
{
    recordScalar("aimrcePolicyCode", enableAimrceDecision ? decisionModeCodeForDiagnostics() : 0);
    recordScalar(
        "runtimeModelArtifactRequired",
        enableAimrceDecision && decisionMode != DecisionMode::RULE_BASED ? 1 : 0
    );
    recordScalar("runtimeModelLoaded", runtimeModelLoaded);
    recordScalar("runtimeModelFeatureCount", runtimeModelFeatureCount);
    recordScalar("runtimeModelThreshold", runtimeModelThreshold);
    recordScalar("runtimeModelFallbackUsed", 0);
    recordScalar("runtimeModelFallbackReasonCode", runtimeModelFallbackReasonCode);
    recordScalar("aimrceEvaluationInterval", par("evaluationInterval").doubleValue());
    recordScalar("aimrceActivationConsecutiveCyclesConfigured", par("activationConsecutiveCycles").intValue());
}

void AiMrceController::recordBfdLikeScalars()
{
    recordScalar("bfdLikeDetectionActivated", bfdLikeDetectionActivated);
    if (enableBfdLikeDetection) {
        // BFD-like timing scalars are recorded only for configurations that
        // actually enable this project-local reactive detector. Keeping them
        // absent elsewhere avoids treating default NED parameters as active
        // mechanism settings in cross-mechanism reports.
        recordScalar("bfdLikeDetectionTime", bfdLikeDetectionTime >= SIMTIME_ZERO ? bfdLikeDetectionTime.dbl() : -1);
        recordScalar("bfdLikeDetectMultiplier", par("bfdLikeDetectMultiplier").intValue());
        recordScalar("bfdLikeDetectionInterval", par("bfdLikeDetectionInterval").doubleValue());
        recordScalar("bfdLikeExpectedDetectionTime", par("bfdLikeDetectionInterval").doubleValue() * par("bfdLikeDetectMultiplier").intValue());
        recordScalar("bfdLikeMissedProbeCount", bfdLikeMissedProbeCountAtDetection);
        recordScalar("bfdLikeMaxMissedProbeCount", bfdLikeMaxConsecutiveMissedProbeIntervals);
        recordScalar("bfdLikeUseModeledProbeLoss", par("bfdLikeUseModeledProbeLoss").boolValue());
        recordScalar("bfdLikeProbeChecks", bfdLikeProbeChecks);
        recordScalar("bfdLikeProbeSuccesses", bfdLikeProbeSuccesses);
        recordScalar("bfdLikeProbeMisses", bfdLikeProbeMisses);
        recordScalar("bfdLikeProbeLossRateObserved", bfdLikeProbeChecks > 0 ? static_cast<double>(bfdLikeProbeMisses) / bfdLikeProbeChecks : -1);
        recordScalar("bfdLikeModeledProbeLossProbabilityLast", bfdLikeModeledProbeLossProbabilityLast);
        recordScalar("bfdLikeModeledProbeLossProbabilityMax", bfdLikeModeledProbeLossProbabilityMax);
        recordScalar("bfdLikeModeledProbeLossProbabilityAtDetection", bfdLikeModeledProbeLossProbabilityAtDetection);
        recordScalar("bfdLikeTriggerReasonCode", bfdLikeTriggerReasonCode);
        recordScalar(
            "bfdLikeProtectedSpanUpAtDetection",
            bfdLikeDetectionActivated ? (bfdLikeProtectedSpanUpAtDetection ? 1 : 0) : -1
        );
        auto detectionBeforeHardFailure = bfdLikeDetectionActivated
            && bfdLikeDetectionTime >= SIMTIME_ZERO
            && hardFailureTime >= SIMTIME_ZERO
            && bfdLikeDetectionTime < hardFailureTime;
        recordScalar("bfdLikeDetectionBeforeHardFailure", detectionBeforeHardFailure);
        recordScalar(
            "bfdLikeLeadTimeBeforeFailure",
            detectionBeforeHardFailure ? (hardFailureTime - bfdLikeDetectionTime).dbl() : -1
        );
        recordScalar(
            "hardFailureToBfdDetectionTime",
            bfdLikeDetectionActivated && hardFailureTime >= SIMTIME_ZERO
                ? (bfdLikeDetectionTime - hardFailureTime).dbl()
                : -1
        );
    }
}

void AiMrceController::recordActivationScalars()
{
    recordScalar("activationRiskScore", activationRiskScore);
    recordScalar("activationDecisionThreshold", activationDecisionThreshold);
    recordScalar("activationPositiveDecisionStreak", activationPositiveDecisionStreak);
    recordScalar("activationQueueLengthPk", activationQueueLengthPackets);
    recordScalar("activationQueueBitLengthB", activationQueueBitLength);
    recordScalar("activationProbeDelayMeanS", activationProbeDelayMeanSeconds);
    recordScalar("activationProbeThroughputBps", activationProbeThroughputBps);
    recordScalar("activationProbePacketCount", activationProbePacketCount);
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
    bfdLikeProbePacketCount++;
}

AiMrceController::DecisionMode AiMrceController::parseDecisionMode(const char *value) const
{
    auto mode = toLower(value);
    if (mode == DECISION_MODE_RULE_BASED_NORMALIZED)
        return DecisionMode::RULE_BASED;
    if (mode == DECISION_MODE_LOGISTIC_REGRESSION_NORMALIZED)
        return DecisionMode::LOGISTIC_REGRESSION;
    if (mode == DECISION_MODE_LINEAR_SVM_NORMALIZED)
        return DecisionMode::LINEAR_SVM;
    if (mode == DECISION_MODE_SHALLOW_TREE_NORMALIZED)
        return DecisionMode::SHALLOW_TREE;
    throw cRuntimeError("Unsupported decisionMode '%s'. Supported values: %s", value, SUPPORTED_DECISION_MODES);
}

AiMrceController::ProtectionAction AiMrceController::parseProtectionAction(const char *value) const
{
    auto mode = toLower(value);
    if (mode == PROTECTION_ACTION_ADMIN_WITHDRAWAL_NORMALIZED)
        return ProtectionAction::ADMIN_WITHDRAWAL;
    if (mode == PROTECTION_ACTION_LOCAL_REPAIR_STATIC_ROUTES_NORMALIZED)
        return ProtectionAction::LOCAL_REPAIR_STATIC_ROUTES;
    throw cRuntimeError("Unsupported protectionAction '%s'. Supported values: %s", value, SUPPORTED_PROTECTION_ACTIONS);
}

int AiMrceController::decisionModeCodeForDiagnostics() const
{
    switch (decisionMode) {
        case DecisionMode::RULE_BASED:
            return 1;
        case DecisionMode::LOGISTIC_REGRESSION:
            return 2;
        case DecisionMode::LINEAR_SVM:
            return 3;
        case DecisionMode::SHALLOW_TREE:
            return 4;
    }
    return -1;
}

const char *AiMrceController::decisionModeNameForDiagnostics() const
{
    switch (decisionMode) {
        case DecisionMode::RULE_BASED:
            return DECISION_MODE_RULE_BASED;
        case DecisionMode::LOGISTIC_REGRESSION:
            return DECISION_MODE_LOGISTIC_REGRESSION;
        case DecisionMode::LINEAR_SVM:
            return DECISION_MODE_LINEAR_SVM;
        case DecisionMode::SHALLOW_TREE:
            return DECISION_MODE_SHALLOW_TREE;
    }
    return "unknown";
}

const char *AiMrceController::protectionActionNameForDiagnostics() const
{
    switch (protectionAction) {
        case ProtectionAction::ADMIN_WITHDRAWAL:
            return PROTECTION_ACTION_ADMIN_WITHDRAWAL;
        case ProtectionAction::LOCAL_REPAIR_STATIC_ROUTES:
            return PROTECTION_ACTION_LOCAL_REPAIR_STATIC_ROUTES;
    }
    return "unknown";
}

int AiMrceController::triggerSourceCodeForActivation(ProtectionTriggerSource source) const
{
    // Codes are deliberately stable because analysis scripts map them to
    // publication-friendly trigger-source labels. Hybrid codes distinguish the
    // first trigger without claiming protocol-level arbitration semantics.
    if (source == ProtectionTriggerSource::AIMRCE)
        return enableBfdLikeDetection ? 3 : 1;
    if (source == ProtectionTriggerSource::BFD_LIKE)
        return enableAimrceDecision ? 4 : 2;
    return 0;
}

const char *AiMrceController::triggerSourceNameForActivation(ProtectionTriggerSource source) const
{
    auto code = triggerSourceCodeForActivation(source);
    switch (code) {
        case 1: return TRIGGER_SOURCE_AIMRCE;
        case 2: return TRIGGER_SOURCE_BFD_LIKE;
        case 3: return TRIGGER_SOURCE_HYBRID_AIMRCE_FIRST;
        case 4: return TRIGGER_SOURCE_HYBRID_BFD_LIKE_FIRST;
        default: return TRIGGER_SOURCE_NONE;
    }
}

std::vector<AiMrceController::LocalRepairRouteSpec> AiMrceController::parseLocalRepairRouteSpecs(const std::string& rawValue) const
{
    std::vector<LocalRepairRouteSpec> routeSpecs;
    for (const auto& rawItem : splitSemicolonList(rawValue)) {
        auto fields = splitCsvLine(rawItem);
        if (fields.size() != 4)
            throw cRuntimeError("Each localRepairRouteSpecs item must have 4 comma-separated fields: routerModule,outputInterfaceModule,gatewayInterfaceModule,destinationInterfaceModule");

        LocalRepairRouteSpec spec;
        spec.routerModule = fields[0];
        spec.outputInterfaceModule = fields[1];
        spec.gatewayInterfaceModule = fields[2];
        spec.destinationInterfaceModule = fields[3];
        routeSpecs.push_back(spec);
    }
    return routeSpecs;
}

inet::NetworkInterface *AiMrceController::resolveInterface(const char *modulePath) const
{
    auto module = getModuleByPath(modulePath);
    if (module == nullptr)
        throw cRuntimeError("Cannot find target interface module '%s'", modulePath);
    return check_and_cast<inet::NetworkInterface *>(module);
}

inet::IIpv4RoutingTable *AiMrceController::resolveIpv4RoutingTable(const char *modulePath) const
{
    auto module = resolveModule(modulePath, "repair-router module");
    return inet::L3AddressResolver().getIpv4RoutingTableOf(module);
}

inet::Ipv4Address AiMrceController::resolveInterfaceIpv4Address(const char *modulePath) const
{
    auto networkInterface = resolveInterface(modulePath);
    auto ipv4Data = networkInterface->findProtocolData<inet::Ipv4InterfaceData>();
    if (ipv4Data == nullptr)
        throw cRuntimeError("Interface '%s' has no IPv4 protocol data", modulePath);

    auto address = ipv4Data->getIPAddress();
    if (address.isUnspecified())
        throw cRuntimeError("Interface '%s' has an unspecified IPv4 address", modulePath);
    return address;
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

    if (par("verboseModelLoadingLogging").boolValue()) {
        EV_INFO << "[AI-MRCE:model] t=" << simTime().dbl()
                << "s loading model=" << decisionModeNameForDiagnostics()
                << " path=" << linearModel.sourcePath << endl;
    }

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
    runtimeModelLoaded = true;
    runtimeModelFeatureCount = static_cast<int>(linearModel.features.size());
    runtimeModelThreshold = linearModel.threshold;
    if (par("verboseModelLoadingLogging").boolValue()) {
        EV_INFO << "[AI-MRCE:model] t=" << simTime().dbl()
                << "s model=" << decisionModeNameForDiagnostics()
                << " loaded=1 fallback=0 featureCount=" << runtimeModelFeatureCount
                << " threshold=" << runtimeModelThreshold
                << " scoreSemantics=" << linearModel.scoreTransform
                << " features=" << joinFeatureNames(linearModel.features) << endl;
    }
}

void AiMrceController::loadRuntimeTreeModel()
{
    auto configuredPath = par("runtimeModelFile").stdstringValue();
    if (configuredPath.empty())
        throw cRuntimeError("runtimeModelFile must be configured when decisionMode=shallowTree");

    treeModel = RuntimeTreeModel();
    treeModel.sourcePath = resolveParameterFilePath("runtimeModelFile");

    if (par("verboseModelLoadingLogging").boolValue()) {
        EV_INFO << "[AI-MRCE:model] t=" << simTime().dbl()
                << "s loading model=" << decisionModeNameForDiagnostics()
                << " path=" << treeModel.sourcePath << endl;
    }

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
    runtimeModelLoaded = true;
    runtimeModelFeatureCount = static_cast<int>(treeModel.features.size());
    runtimeModelThreshold = treeModel.threshold;
    if (par("verboseModelLoadingLogging").boolValue()) {
        EV_INFO << "[AI-MRCE:model] t=" << simTime().dbl()
                << "s model=" << decisionModeNameForDiagnostics()
                << " loaded=1 fallback=0 featureCount=" << runtimeModelFeatureCount
                << " threshold=" << runtimeModelThreshold
                << " nodes=" << treeModel.nodes.size()
                << " features=" << joinFeatureNames(treeModel.features) << endl;
    }
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

AiMrceController::PolicyScore AiMrceController::scoreCurrentPolicy(const FeatureSnapshot& snapshot) const
{
    PolicyScore score;
    switch (decisionMode) {
        case DecisionMode::RULE_BASED:
            score.riskScore = computeRuleBasedRisk(snapshot);
            score.decisionThreshold = par("ruleRiskThreshold").doubleValue();
            return score;
        case DecisionMode::LOGISTIC_REGRESSION:
        case DecisionMode::LINEAR_SVM:
            score.riskScore = computeLinearModelRisk(snapshot);
            score.decisionThreshold = linearModel.threshold;
            return score;
        case DecisionMode::SHALLOW_TREE:
            score.riskScore = computeShallowTreeRisk(snapshot);
            score.decisionThreshold = treeModel.threshold;
            return score;
    }
    throw cRuntimeError("Unsupported AI-MRCE decision mode code %d while scoring current policy", decisionModeCodeForDiagnostics());
}

void AiMrceController::evaluateCycle()
{
    auto snapshot = collectFeatureSnapshot();
    maybeLogTelemetry(snapshot, "AI-MRCE evaluation");

    auto policyScore = scoreCurrentPolicy(snapshot);
    auto riskScore = policyScore.riskScore;
    auto decisionThreshold = policyScore.decisionThreshold;
    auto decisionPositive = riskScore >= decisionThreshold;

    // Consecutive positive cycles provide simple hysteresis for the first
    // prototype so one noisy interval does not trigger protective action.
    if (decisionPositive)
        positiveDecisionStreak++;
    else
        positiveDecisionStreak = 0;

    auto activationCycle = !protectionActive && positiveDecisionStreak >= par("activationConsecutiveCycles").intValue();
    maybeLogDecision(snapshot, riskScore, decisionThreshold, decisionPositive, activationCycle);

    if (activationCycle) {
        captureActivationDiagnostics(snapshot, riskScore, decisionThreshold);
        activateProtection(ProtectionTriggerSource::AIMRCE);
    }

    lastRiskScore = riskScore;
    lastDecisionPositive = decisionPositive;
    recordVectors(snapshot, riskScore, decisionPositive);
    resetIntervalTelemetry();
}

void AiMrceController::evaluateBfdLikeCycle()
{
    auto expectedProbeCount = par("bfdLikeExpectedProbeCount").intValue();
    auto detectMultiplier = par("bfdLikeDetectMultiplier").intValue();
    auto observedProbeCount = bfdLikeProbePacketCount;
    auto protectedSpanHealthy = isBfdLikeProtectedSpanHealthy();
    auto probeIntervalMissed = observedProbeCount < expectedProbeCount;
    auto modeledLossProbability = currentBfdLikeModeledProbeLossProbability();
    auto modeledProbeMissed = protectedSpanHealthy
        && par("bfdLikeUseModeledProbeLoss").boolValue()
        && nextDeterministicModeledProbeMiss(modeledLossProbability);
    auto intervalUnhealthy = probeIntervalMissed || !protectedSpanHealthy || modeledProbeMissed;

    bfdLikeProbeChecks++;
    if (intervalUnhealthy)
        bfdLikeProbeMisses++;
    else
        bfdLikeProbeSuccesses++;

    if (intervalUnhealthy)
        bfdLikeConsecutiveMissedProbeIntervals++;
    else
        bfdLikeConsecutiveMissedProbeIntervals = 0;

    bfdLikeMaxConsecutiveMissedProbeIntervals = std::max(
        bfdLikeMaxConsecutiveMissedProbeIntervals,
        bfdLikeConsecutiveMissedProbeIntervals
    );

    auto bfdLikeTriggerCycle = !protectionActive && bfdLikeConsecutiveMissedProbeIntervals >= detectMultiplier;
    maybeLogBfdLikeProbe(
        modeledLossProbability,
        modeledProbeMissed,
        protectedSpanHealthy,
        observedProbeCount,
        expectedProbeCount,
        intervalUnhealthy,
        bfdLikeTriggerCycle
    );

    if (bfdLikeTriggerCycle) {
        auto snapshot = collectFeatureSnapshot();
        maybeLogTelemetry(snapshot, "BFD-like detection");

        double riskScore = -1;
        double decisionThreshold = -1;
        if (enableAimrceDecision) {
            auto policyScore = scoreCurrentPolicy(snapshot);
            riskScore = policyScore.riskScore;
            decisionThreshold = policyScore.decisionThreshold;
            lastRiskScore = riskScore;
            lastDecisionPositive = riskScore >= decisionThreshold;
        }

        bfdLikeDetectionActivated = true;
        bfdLikeDetectionTime = simTime();
        bfdLikeMissedProbeCountAtDetection = bfdLikeConsecutiveMissedProbeIntervals;
        bfdLikeProtectedSpanUpAtDetection = protectedSpanHealthy;
        bfdLikeModeledProbeLossProbabilityAtDetection = modeledLossProbability;
        // 1 = receiver probe-reception interval below expectation,
        // 2 = protected span interface/carrier observed down,
        // 3 = deterministic modeled BFD-like probe miss from current channel
        // packet-error-rate impairment. This is intentionally local
        // simulation-side state, not negotiated BFD session state.
        if (!protectedSpanHealthy)
            bfdLikeTriggerReasonCode = 2;
        else if (modeledProbeMissed)
            bfdLikeTriggerReasonCode = 3;
        else
            bfdLikeTriggerReasonCode = 1;

        captureActivationDiagnostics(snapshot, riskScore, decisionThreshold);
        activateProtection(ProtectionTriggerSource::BFD_LIKE);
    }

    bfdLikeMissedProbeCountVector.record(bfdLikeConsecutiveMissedProbeIntervals);
    bfdLikeDetectionActiveVector.record(bfdLikeDetectionActivated ? 1 : 0);
    bfdLikeProtectedSpanUpVector.record(protectedSpanHealthy ? 1 : 0);
    bfdLikeModeledProbeLossProbabilityVector.record(modeledLossProbability);
    bfdLikeProbeMissedVector.record(intervalUnhealthy ? 1 : 0);
    protectionTriggerSourceCodeVector.record(protectionTriggerSourceCode);

    bfdLikeProbePacketCount = 0;
    if (!enableAimrceDecision)
        resetIntervalTelemetry();
}

bool AiMrceController::isBfdLikeProtectedSpanHealthy() const
{
    // The project-local BFD-like detector approximates a fast local failure
    // indication for the protected span. INET's NetworkInterface::isUp()
    // combines administrative state with carrier state, so ScenarioManager
    // disconnect events can be observed without touching OSPF internals.
    auto firstInterface = resolveInterface(par("firstInterfaceModule"));
    auto secondInterface = resolveInterface(par("secondInterfaceModule"));
    return firstInterface->isUp() && secondInterface->isUp();
}

double AiMrceController::currentBfdLikeModeledProbeLossProbability() const
{
    if (!par("bfdLikeUseModeledProbeLoss").boolValue())
        return 0;

    // This opt-in path lets degraded-link comparison configs expose logical
    // BFD-like checks to the same project-local channel packet-error-rate
    // impairment used for data traffic. It reads only current simulator state;
    // it does not look at hardFailureTime and is not a future-failure oracle.
    auto firstDirectionLoss = packetErrorRateForInterface(par("firstInterfaceModule"));
    auto secondDirectionLoss = packetErrorRateForInterface(par("secondInterfaceModule"));
    auto lossProbability = clamp01(std::max(firstDirectionLoss, secondDirectionLoss));
    return lossProbability;
}

double AiMrceController::packetErrorRateForInterface(const char *modulePath) const
{
    auto networkInterface = resolveInterface(modulePath);
    auto channel = dynamic_cast<cDatarateChannel *>(networkInterface->getTxTransmissionChannel());
    if (channel == nullptr)
        return 0;
    return channel->getPacketErrorRate();
}

bool AiMrceController::nextDeterministicModeledProbeMiss(double lossProbability)
{
    lossProbability = clamp01(lossProbability);
    bfdLikeModeledProbeLossProbabilityLast = lossProbability;
    bfdLikeModeledProbeLossProbabilityMax = std::max(bfdLikeModeledProbeLossProbabilityMax, lossProbability);

    if (lossProbability <= 0)
        return false;
    if (lossProbability >= 1)
        return true;

    // Deterministic accumulator: a packet-error-rate of p produces about p of
    // logical checks as misses over time without adding uncontrolled random
    // variation. Consecutive misses still require sufficiently severe current
    // degradation, matching the detect-multiplier idea conservatively.
    bfdLikeModeledProbeLossAccumulator += lossProbability;
    if (bfdLikeModeledProbeLossAccumulator >= 1.0) {
        bfdLikeModeledProbeLossAccumulator -= 1.0;
        return true;
    }
    return false;
}

void AiMrceController::captureActivationDiagnostics(const FeatureSnapshot& snapshot, double riskScore, double decisionThreshold)
{
    // These scalars are diagnostic only. They document the telemetry and
    // decision state at the exact cycle that triggers the project-local repair
    // action, without changing the activation semantics or route installation.
    activationRiskScore = riskScore;
    activationDecisionThreshold = decisionThreshold;
    activationPositiveDecisionStreak = positiveDecisionStreak;
    activationQueueLengthPackets = snapshot.queueLengthPackets;
    activationQueueBitLength = snapshot.queueBitLength;
    activationProbeDelayMeanSeconds = snapshot.hasProbeDelay ? snapshot.probeDelayMeanSeconds : -1;
    activationProbeThroughputBps = snapshot.probeThroughputBps;
    activationProbePacketCount = snapshot.probePacketCount;
}

void AiMrceController::activateProtection(ProtectionTriggerSource triggerSource)
{
    if (protectionActive)
        return;

    protectionActive = true;
    protectionActivationTime = simTime();
    protectionTriggerSource = triggerSource;
    protectionTriggerSourceCode = triggerSourceCodeForActivation(triggerSource);

    if (par("verboseTriggerLogging").boolValue()) {
        auto leadTime = hardFailureTime >= SIMTIME_ZERO ? (hardFailureTime - simTime()).dbl() : -1;
        if (triggerSource == ProtectionTriggerSource::AIMRCE) {
            EV_INFO << "[AI-MRCE:trigger] t=" << simTime().dbl()
                    << "s source=" << triggerSourceNameForActivation(triggerSource)
                    << " model=" << decisionModeNameForDiagnostics()
                    << " score=" << activationRiskScore
                    << " threshold=" << activationDecisionThreshold
                    << " streak=" << activationPositiveDecisionStreak
                    << "/" << par("activationConsecutiveCycles").intValue()
                    << " leadTimeBeforeFailure=" << leadTime
                    << "s queue=" << activationQueueLengthPackets
                    << "pk probeDelay=" << activationProbeDelayMeanSeconds
                    << "s" << endl;
        }
        else if (triggerSource == ProtectionTriggerSource::BFD_LIKE) {
            EV_INFO << "[BFD-like:trigger] t=" << simTime().dbl()
                    << "s source=" << triggerSourceNameForActivation(triggerSource)
                    << " reasonCode=" << bfdLikeTriggerReasonCode
                    << " modeledLoss=" << bfdLikeModeledProbeLossProbabilityAtDetection
                    << " missed=" << bfdLikeMissedProbeCountAtDetection
                    << "/" << par("bfdLikeDetectMultiplier").intValue()
                    << " leadTimeBeforeFailure=" << leadTime
                    << "s protectionAlreadyActivated=0" << endl;
        }
        else {
            EV_INFO << "[Protection:trigger] t=" << simTime().dbl()
                    << "s source=" << triggerSourceNameForActivation(triggerSource)
                    << " leadTimeBeforeFailure=" << leadTime << "s" << endl;
        }
    }
    switch (protectionAction) {
        case ProtectionAction::ADMIN_WITHDRAWAL:
            // Retained for reference and debugging: ordinary administrative
            // interface-down semantics that OSPF can react to in the simulation.
            administrativelyWithdraw(par("firstInterfaceModule"));
            administrativelyWithdraw(par("secondInterfaceModule"));
            break;
        case ProtectionAction::LOCAL_REPAIR_STATIC_ROUTES:
            activateLocalRepairStaticRoutes();
            break;
    }
}

void AiMrceController::administrativelyWithdraw(const char *modulePath)
{
    auto networkInterface = resolveInterface(modulePath);
    if (networkInterface->getState() == inet::NetworkInterface::DOWN)
        return;

    // This follows ordinary administrative interface-down semantics that OSPF
    // can react to in the simulation, rather than introducing custom LSAs.
    if (par("verboseRepairRouteLogging").boolValue()) {
        EV_INFO << "[FRR-like:admin-withdrawal] t=" << simTime().dbl()
                << "s withdrawing interface " << networkInterface->getInterfaceFullPath() << endl;
    }
    cMethodCallContextSwitcher contextSwitcher(networkInterface);
    networkInterface->setState(inet::NetworkInterface::DOWN);
}

void AiMrceController::activateLocalRepairStaticRoutes()
{
    repairRouteCount = 0;

    // This dissertation-core action represents an AI-MRCE warning that tells
    // affected routers to activate a prearranged local protection path. It is
    // intentionally implemented as explicit host-specific manual IPv4 routes:
    // scientifically auditable, project-local, and not a claim of standards-
    // compliant IP/LFA/TI-LFA behavior.
    if (par("verboseRepairRouteLogging").boolValue()) {
        EV_INFO << "[FRR-like:repair-route] t=" << simTime().dbl()
                << "s source=" << triggerSourceNameForActivation(protectionTriggerSource)
                << " installing static /32 repair routes"
                << " countConfigured=" << localRepairRouteSpecs.size()
                << " corridor=configured-southern-backup"
                << " alreadyInstalled=" << (repairRoutesInstalled ? 1 : 0)
                << endl;
    }
    for (const auto& spec : localRepairRouteSpecs) {
        if (installLocalRepairRoute(spec))
            repairRouteCount++;
    }

    repairRoutesInstalled = repairRouteCount > 0;
    if (!repairRoutesInstalled)
        throw cRuntimeError("AI-MRCE local repair action did not install any repair routes");

    repairRouteInstallTime = simTime();

    if (par("verboseRepairRouteLogging").boolValue()) {
        EV_INFO << "[FRR-like:repair-route] t=" << repairRouteInstallTime.dbl()
                << "s installed=" << (repairRoutesInstalled ? 1 : 0)
                << " routeCount=" << repairRouteCount << endl;
    }
}

bool AiMrceController::installLocalRepairRoute(const LocalRepairRouteSpec& spec)
{
    auto routingTable = resolveIpv4RoutingTable(spec.routerModule.c_str());
    auto outputInterface = resolveInterface(spec.outputInterfaceModule.c_str());
    auto gatewayAddress = resolveInterfaceIpv4Address(spec.gatewayInterfaceModule.c_str());
    auto destinationAddress = resolveInterfaceIpv4Address(spec.destinationInterfaceModule.c_str());

    auto route = new inet::Ipv4Route();
    route->setSourceType(inet::IRoute::MANUAL);
    route->setSource(this);
    route->setDestination(destinationAddress);
    route->setNetmask(inet::Ipv4Address::ALLONES_ADDRESS);
    route->setGateway(gatewayAddress);
    route->setInterface(outputInterface);
    route->setAdminDist(inet::IRoute::dStatic);
    route->setMetric(par("localRepairRouteMetric").intValue());

    auto routingTableComponent = dynamic_cast<cComponent *>(routingTable);
    if (routingTableComponent == nullptr)
        throw cRuntimeError("Routing table for '%s' is not an OMNeT++ component", spec.routerModule.c_str());

    // addRoute() notifies the standard INET IPv4 routing table. The route is a
    // host-specific manual entry, so it is intended to override the broader
    // OSPF route without modifying OSPF internals or link-state behavior.
    if (par("verboseRepairRouteLogging").boolValue()) {
        EV_INFO << "[FRR-like:repair-route] t=" << simTime().dbl()
                << "s router=" << spec.routerModule
                << " destination=" << destinationAddress
                << "/32 via " << gatewayAddress
                << " out " << outputInterface->getInterfaceFullPath() << endl;
    }
    cMethodCallContextSwitcher contextSwitcher(routingTableComponent);
    routingTable->addRoute(route);
    return true;
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
    repairRoutesInstalledVector.record(repairRoutesInstalled ? 1 : 0);
    protectionTriggerSourceCodeVector.record(protectionTriggerSourceCode);
    if (enableBfdLikeDetection) {
        bfdLikeMissedProbeCountVector.record(bfdLikeConsecutiveMissedProbeIntervals);
        bfdLikeDetectionActiveVector.record(bfdLikeDetectionActivated ? 1 : 0);
        bfdLikeProtectedSpanUpVector.record(isBfdLikeProtectedSpanHealthy() ? 1 : 0);
    }
}

void AiMrceController::maybeLogDecision(const FeatureSnapshot& snapshot, double riskScore, double decisionThreshold, bool decisionPositive, bool activationCycle)
{
    if (!par("verboseDecisionLogging").boolValue())
        return;

    auto logOnlyPositive = par("logOnlyPositiveDecisions").boolValue();
    simtime_t decisionLogInterval = par("decisionLogInterval");
    auto cadenceReached = lastDecisionLogTime < SIMTIME_ZERO || simTime() - lastDecisionLogTime >= decisionLogInterval;
    auto shouldLog = activationCycle || (logOnlyPositive ? decisionPositive : cadenceReached);
    if (!shouldLog)
        return;

    lastDecisionLogTime = simTime();
    EV_INFO << "[AI-MRCE:decision] t=" << simTime().dbl()
            << "s model=" << decisionModeNameForDiagnostics()
            << " score=" << riskScore
            << " threshold=" << decisionThreshold
            << " positive=" << (decisionPositive ? 1 : 0)
            << " streak=" << positiveDecisionStreak
            << "/" << par("activationConsecutiveCycles").intValue()
            << " queue=" << snapshot.queueLengthPackets
            << "pk queueBits=" << snapshot.queueBitLength
            << " probeDelay=" << (snapshot.hasProbeDelay ? snapshot.probeDelayMeanSeconds : -1)
            << "s probeThroughputBps=" << snapshot.probeThroughputBps
            << " probePackets=" << snapshot.probePacketCount
            << " protection=" << (protectionActive ? 1 : 0)
            << (activationCycle ? " activationCycle=1" : "")
            << endl;
}

void AiMrceController::maybeLogBfdLikeProbe(double modeledLossProbability, bool modeledProbeMissed, bool protectedSpanHealthy, int observedProbeCount, int expectedProbeCount, bool intervalUnhealthy, bool triggerCycle)
{
    if (!par("verboseBfdLikeLogging").boolValue())
        return;

    simtime_t logInterval = par("decisionLogInterval");
    auto cadenceReached = lastBfdLikeLogTime < SIMTIME_ZERO || simTime() - lastBfdLikeLogTime >= logInterval;
    auto firstMissInStreak = intervalUnhealthy && bfdLikeConsecutiveMissedProbeIntervals == 1;
    auto shouldLog = triggerCycle || cadenceReached || firstMissInStreak;
    if (!shouldLog)
        return;

    lastBfdLikeLogTime = simTime();
    EV_INFO << "[BFD-like:probe] t=" << simTime().dbl()
            << "s modeledLoss=" << modeledLossProbability
            << " miss=" << (intervalUnhealthy ? 1 : 0)
            << " modeledMiss=" << (modeledProbeMissed ? 1 : 0)
            << " observedProbes=" << observedProbeCount
            << " expectedMinimum=" << expectedProbeCount
            << " missed=" << bfdLikeConsecutiveMissedProbeIntervals
            << "/" << par("bfdLikeDetectMultiplier").intValue()
            << " protectedSpanUp=" << (protectedSpanHealthy ? 1 : 0)
            << " protectionAlreadyActivated=" << (protectionActive ? 1 : 0)
            << endl;
}

void AiMrceController::logInitializationSummary(simtime_t evaluationInterval, int activationCycles, simtime_t bfdLikeDetectionInterval, int bfdLikeDetectMultiplier) const
{
    if (!par("verboseInitializationLogging").boolValue())
        return;

    auto decisionThreshold = runtimeModelThreshold >= 0 ? runtimeModelThreshold : par("ruleRiskThreshold").doubleValue();
    EV_INFO << "[AI-MRCE:init] t=" << simTime().dbl()
            << "s module=" << getFullPath()
            << " aimrce=" << (enableAimrceDecision ? 1 : 0)
            << " bfdLike=" << (enableBfdLikeDetection ? 1 : 0)
            << " policy=" << (enableAimrceDecision ? decisionModeNameForDiagnostics() : "disabled")
            << " runtimeModelPath=" << par("runtimeModelFile").stdstringValue()
            << " threshold=" << decisionThreshold
            << " decisionInterval=" << evaluationInterval.dbl()
            << "s streakRequired=" << activationCycles
            << " repairAction=" << protectionActionNameForDiagnostics();
    if (enableBfdLikeDetection) {
        EV_INFO << " bfdInterval=" << bfdLikeDetectionInterval.dbl()
                << "s bfdMultiplier=" << bfdLikeDetectMultiplier
                << " bfdExpectedDetection=" << (bfdLikeDetectionInterval.dbl() * bfdLikeDetectMultiplier)
                << "s";
    }
    EV_INFO << " hardFailureTime=" << (hardFailureTime >= SIMTIME_ZERO ? hardFailureTime.dbl() : -1)
            << "s" << endl;
}

void AiMrceController::logHardFailureReference() const
{
    if (!par("verboseTriggerLogging").boolValue())
        return;

    EV_INFO << "[Scenario:hard-failure] t=" << simTime().dbl()
            << "s protectionActivated=" << (protectionActive ? 1 : 0)
            << " source=" << triggerSourceNameForActivation(protectionTriggerSource)
            << " activationTime="
            << (protectionActivationTime >= SIMTIME_ZERO ? protectionActivationTime.dbl() : -1)
            << "s" << endl;
}

void AiMrceController::maybeLogTelemetry(const FeatureSnapshot& snapshot, const char *context)
{
    if (!par("verboseTelemetryLogging").boolValue())
        return;

    simtime_t telemetryLogInterval = par("telemetryLogInterval");
    if (lastTelemetryLogTime >= SIMTIME_ZERO && simTime() - lastTelemetryLogTime < telemetryLogInterval)
        return;

    lastTelemetryLogTime = simTime();
    EV_INFO << "[AI-MRCE:telemetry] t=" << simTime().dbl()
            << "s context=" << context
            << " queuePk=" << snapshot.queueLengthPackets
            << " queueBits=" << snapshot.queueBitLength
            << " probePackets=" << snapshot.probePacketCount
            << " probeThroughputBps=" << snapshot.probeThroughputBps
            << " probeDelayMeanS=" << (snapshot.hasProbeDelay ? snapshot.probeDelayMeanSeconds : -1)
            << endl;
}

} // namespace dissertationsim::controller
