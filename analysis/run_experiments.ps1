[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs = @()
)

$ErrorActionPreference = "Stop"

# Project-local experiment orchestrator for conservative batch execution.
#
# This script wraps standard OMNeT++ / INET command-line execution in Cmdenv
# express mode and the project's existing analysis entrypoints. It does not
# modify INET, OSPF internals, dataset labels, or AI-MRCE decision semantics.
# Its purpose is reproducible execution, logging, and validation of generated
# artifacts only.

$analysisDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $analysisDir "..")).Path
$simulationsDir = Join-Path $projectRoot "simulations"
$srcDir = Join-Path $projectRoot "src"
$runAnalysisScript = Join-Path $analysisDir "run_analysis.ps1"
$outputRoot = Join-Path $analysisDir "output"
$datasetsDir = Join-Path $outputRoot "datasets"
$reportsDir = Join-Path $outputRoot "reports"
$trainingDir = Join-Path $outputRoot "training"
$outcomesDir = Join-Path $outputRoot "outcomes"
$debugOutputDir = Join-Path $outputRoot "debug"
$logsRoot = Join-Path $outputRoot "experiment_logs"
$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$script:ExplorerExe = Join-Path $env:SystemRoot "explorer.exe"
if (-not (Test-Path $script:ExplorerExe)) {
    $script:ExplorerExe = "explorer.exe"
}

$script:ScenarioPresets = [ordered]@{
    "linkdegradation" = [pscustomobject]@{
        Name = "linkdegradation"
        Description = "Controlled synthetic degradation proxy dataset batch"
        ScenarioDir = Join-Path $simulationsDir "linkdegradation"
        EvalDir = Join-Path $projectRoot "results\linkdegradation\eval"
        DatasetPath = Join-Path $datasetsDir "linkdegradation_dataset.csv"
        ReportPath = Join-Path $reportsDir "linkdegradation_report.txt"
        MissingCsvPath = Join-Path $debugOutputDir "linkdegradation_missing_values.csv"
        PerConfigCsvPath = Join-Path $debugOutputDir "linkdegradation_per_config_summary.csv"
        OutcomeSummaryPath = Join-Path $outcomesDir "linkdegradation_outcome_summary.csv"
        EvalConfigs = @("MildLinear", "StrongLinear", "UnstableLinear", "StagedRealistic")
        AiMrceConfigs = @()
    }
    "congestiondegradation" = [pscustomobject]@{
        Name = "congestiondegradation"
        Description = "Traffic-driven congestion approximation dataset batch"
        ScenarioDir = Join-Path $simulationsDir "congestiondegradation"
        EvalDir = Join-Path $projectRoot "results\congestiondegradation\eval"
        DatasetPath = Join-Path $datasetsDir "congestiondegradation_dataset.csv"
        ReportPath = Join-Path $reportsDir "congestiondegradation_report.txt"
        MissingCsvPath = Join-Path $debugOutputDir "congestiondegradation_missing_values.csv"
        PerConfigCsvPath = Join-Path $debugOutputDir "congestiondegradation_per_config_summary.csv"
        OutcomeSummaryPath = Join-Path $outcomesDir "congestiondegradation_outcome_summary.csv"
        EvalConfigs = @("CongestionDegradation", "CongestionDegradationMild")
        AiMrceConfigs = @()
    }
    "regionalbackbone" = [pscustomobject]@{
        Name = "regionalbackbone"
        Description = "Regional backbone dataset batch with baseline, reactive failure, controlled synthetic degradation proxy, and traffic-driven congestion approximation"
        ScenarioDir = Join-Path $simulationsDir "regionalbackbone"
        EvalDir = Join-Path $projectRoot "results\regionalbackbone\eval"
        DatasetPath = Join-Path $datasetsDir "regionalbackbone_dataset.csv"
        ReportPath = Join-Path $reportsDir "regionalbackbone_report.txt"
        MissingCsvPath = Join-Path $debugOutputDir "regionalbackbone_missing_values.csv"
        PerConfigCsvPath = Join-Path $debugOutputDir "regionalbackbone_per_config_summary.csv"
        OutcomeSummaryPath = Join-Path $outcomesDir "regionalbackbone_outcome_summary.csv"
        EvalConfigs = @(
            "RegionalBackboneBaseline",
            "RegionalBackboneReactiveFailure",
            "RegionalBackboneControlledDegradation",
            "RegionalBackboneCongestionDegradation"
        )
        AiMrceConfigs = @(
            "RegionalBackboneAiMrceRuleBased",
            "RegionalBackboneAiMrceLogReg",
            "RegionalBackboneAiMrceLinearSvm",
            "RegionalBackboneAiMrceShallowTree"
        )
    }
}

$script:RegionalBackboneCongestionProtectionCohortPreset = [pscustomobject]@{
    Name = "regionalbackbone_congestion_protection"
    Description = "Regional backbone congestion protection cohort with repeated reactive-baseline and AI-MRCE runtime comparison runs"
    ScenarioDir = Join-Path $simulationsDir "regionalbackbone"
    EvalDir = Join-Path $projectRoot "results\regionalbackbone\congestion_protection_cohort"
    DatasetPath = Join-Path $datasetsDir "regionalbackbone_congestion_protection_multirun_dataset.csv"
    ReportPath = Join-Path $reportsDir "regionalbackbone_congestion_protection_multirun_report.txt"
    MissingCsvPath = Join-Path $debugOutputDir "regionalbackbone_congestion_protection_multirun_missing_values.csv"
    PerConfigCsvPath = Join-Path $debugOutputDir "regionalbackbone_congestion_protection_multirun_per_config_summary.csv"
    OutcomeSummaryPath = Join-Path $outcomesDir "regionalbackbone_congestion_protection_multirun_outcome_summary.csv"
    ComparisonOutputPrefix = Join-Path $outcomesDir "regionalbackbone_congestion_protection_multirun_comparison"
    ComparisonRunsPath = Join-Path $outcomesDir "regionalbackbone_congestion_protection_multirun_comparison_runs.csv"
    ComparisonSummaryPath = Join-Path $outcomesDir "regionalbackbone_congestion_protection_multirun_comparison_summary.csv"
    ComparisonReportPath = Join-Path $outcomesDir "regionalbackbone_congestion_protection_multirun_comparison_report.txt"
    EvalConfigs = @(
        "RegionalBackboneCongestionDegradationCohort",
        "RegionalBackboneAiMrceRuleBasedCohort",
        "RegionalBackboneAiMrceLogRegCohort",
        "RegionalBackboneAiMrceLinearSvmCohort",
        "RegionalBackboneAiMrceShallowTreeCohort"
    )
    DefaultRunNumbers = @(0, 1, 2, 3, 4)
}

$script:RegionalBackboneMixedTrafficProtectionCohortPreset = [pscustomobject]@{
    Name = "regionalbackbone_mixed_traffic_protection"
    Description = "Regional backbone mixed UDP/TCP protection cohort with repeated reactive-baseline and focused AI-MRCE comparison runs"
    ScenarioDir = Join-Path $simulationsDir "regionalbackbone"
    EvalDir = Join-Path $projectRoot "results\regionalbackbone\mixed_traffic_protection_cohort"
    DatasetPath = Join-Path $datasetsDir "regionalbackbone_mixed_traffic_protection_multirun_dataset.csv"
    ReportPath = Join-Path $reportsDir "regionalbackbone_mixed_traffic_protection_multirun_report.txt"
    MissingCsvPath = Join-Path $debugOutputDir "regionalbackbone_mixed_traffic_protection_multirun_missing_values.csv"
    PerConfigCsvPath = Join-Path $debugOutputDir "regionalbackbone_mixed_traffic_protection_multirun_per_config_summary.csv"
    OutcomeSummaryPath = Join-Path $outcomesDir "regionalbackbone_mixed_traffic_protection_multirun_outcome_summary.csv"
    ComparisonOutputPrefix = Join-Path $outcomesDir "regionalbackbone_mixed_traffic_protection_multirun_comparison"
    ComparisonRunsPath = Join-Path $outcomesDir "regionalbackbone_mixed_traffic_protection_multirun_comparison_runs.csv"
    ComparisonSummaryPath = Join-Path $outcomesDir "regionalbackbone_mixed_traffic_protection_multirun_comparison_summary.csv"
    ComparisonReportPath = Join-Path $outcomesDir "regionalbackbone_mixed_traffic_protection_multirun_comparison_report.txt"
    EvalConfigs = @(
        "RegionalBackboneMixedTrafficCongestionDegradationCohort",
        "RegionalBackboneAiMrceRuleBasedMixedTrafficCohort",
        "RegionalBackboneAiMrceLogRegMixedTrafficCohort"
    )
    DefaultRunNumbers = @(0, 1, 2, 3, 4)
}

$script:ActiveDatasetScenarios = @("regionalbackbone")
$script:StrongerEvaluationModes = @(
    "grouped_run_holdout",
    "leave_one_config_out"
)
$script:ToolEnvironmentInitialized = $false
$script:OmnetppRoot = $null
$script:InetRoot = $null
$script:NedPath = $null
$script:MakeExe = $null
$script:OppConfigfilepathScript = $null
$script:BuildConfigResolutionDescription = $null
$script:IgnoredOmnetppConfigOverride = $null
$script:SimulationExecutable = $null
$script:TrainingArtifactNames = @(
    "risk_model_report.txt",
    "risk_model_class_distribution.csv",
    "risk_model_split_summary.csv",
    "risk_model_evaluation_summary.csv",
    "risk_model_per_class_metrics.csv",
    "risk_model_feature_importance.csv",
    "risk_model_confusion_matrix.csv"
)
$script:RegionalBackboneRuntimeArtifactPaths = @(
    (Join-Path $simulationsDir "regionalbackbone\aimrce_runtime_logreg.csv"),
    (Join-Path $simulationsDir "regionalbackbone\aimrce_runtime_linsvm.csv"),
    (Join-Path $simulationsDir "regionalbackbone\aimrce_runtime_shallow_tree.csv"),
    (Join-Path $simulationsDir "regionalbackbone\aimrce_runtime_manifest.csv")
)

function Show-Usage {
    @"
Usage:
  run_experiments.bat <command> [options...]
  powershell -ExecutionPolicy Bypass -File analysis\run_experiments.ps1 <command> [options...]

Commands:
  help             Show this help text.
  dataset-batch    Run one supported scenario's eval configs sequentially, validate outputs, and optionally build the dataset and report.
  training-batch   Verify datasets, optionally rebuild missing dataset artifacts from existing raw results, then run offline training.
  aimrce-batch     Optionally export the runtime deployment artifacts, then run the regional AI-MRCE runtime configs.
  regional-congestion-protection-batch
                   Run the dedicated multi-run regional congestion protection cohort, rebuild its dataset/report, and generate its focused comparison artifacts.
  regional-mixed-traffic-protection-batch
                   Run the dedicated mixed UDP/TCP regional protection cohort, rebuild its dataset/report, and generate its focused comparison artifacts.
  full-pipeline    Run selected dataset batches, optional analysis, optional training, and optional AI-MRCE runtime configs.

Common options:
  --scenario <name...>              Scenario selection. For dataset-batch exactly one supported scenario is required. Defaults favor the regionalbackbone dissertation core.
  --configs <config...>             Optional subset of non-debug configs for dataset-batch or aimrce-batch.
  --runs <runNumber...>             Explicit OMNeT++ run numbers. Current configs normally expose run 0 unless repeat or iteration variables are added later.
  --clean                           Clean generated eval artifacts before running.
  --yes                             Required together with --clean for actual deletion.
  --skip-build                      Skip the local project rebuild before simulation-running commands.
  --skip-analysis                   Skip dataset build and dataset report after dataset-batch steps.
  --skip-training                   Skip offline training inside full-pipeline.
  --skip-runtime-export             Reuse the existing AI-MRCE runtime deployment artifacts instead of exporting them first.
  --rebuild-missing-datasets        For training-batch, rebuild missing dataset CSV/report artifacts from existing raw results.
  --stronger-evaluations-only       Run only generalization-oriented evaluation modes during training.
  --include-aimrce                  For full-pipeline, also export the runtime deployment artifacts and run the regional AI-MRCE runtime configs.
  --open-output-folder              Open the relevant generated-artifact folders in Windows Explorer after successful completion.
  --dry-run                         Print the planned actions and write dry-run logs without executing commands.
  --continue-on-error               Continue running later configs after a failed simulation command, but keep the overall batch marked failed.
  --help                            Show this help text.

Examples:
  run_experiments.bat help
  run_experiments.bat dataset-batch --scenario regionalbackbone --clean --yes
  run_experiments.bat dataset-batch --scenario regionalbackbone --dry-run
  run_experiments.bat training-batch --stronger-evaluations-only
  run_experiments.bat aimrce-batch --skip-runtime-export --dry-run
  run_experiments.bat regional-congestion-protection-batch --dry-run
  run_experiments.bat regional-congestion-protection-batch --runs 0 1 --clean --yes --skip-build
  run_experiments.bat regional-mixed-traffic-protection-batch --runs 0 --skip-build --skip-runtime-export
  run_experiments.bat dataset-batch --scenario linkdegradation --open-output-folder
  run_experiments.bat full-pipeline --clean --yes --include-aimrce

Generated logs:
  analysis\output\experiment_logs\<timestamp>-<command>\...

Default analysis artifacts:
  analysis\output\datasets\       dataset CSV files
  analysis\output\reports\        human-readable reports
  analysis\output\outcomes\       recovery/protection summaries and comparisons
  analysis\output\training\       offline ML evaluation artifacts
  analysis\output\debug\          verbose helper CSVs

Notes:
  - Simulation runs use standard OMNeT++ Cmdenv express mode from the command line.
  - This script adds project-local automation around existing scenarios and analysis tooling only.
  - It prepares generated artifacts and methodological outputs; it is not runtime decision logic itself.
  - The optional folder opening is Windows-only workflow usability help; it is not part of the experiment methodology.
  - When --configs selects only a subset of dataset configs, keep --skip-analysis enabled so the workflow does not silently produce a partial dataset export.
  - regional-congestion-protection-batch and regional-mixed-traffic-protection-batch default to runs 0,1,2,3,4 when --runs is omitted.
"@ | Write-Host
}

function Parse-CommandArguments {
    param(
        [string[]]$Arguments
    )

    $parsed = [ordered]@{
        Scenarios = @()
        Configs = @()
        Runs = @()
        RunsSpecified = $false
        Clean = $false
        Yes = $false
        SkipBuild = $false
        SkipAnalysis = $false
        SkipTraining = $false
        SkipRuntimeExport = $false
        RebuildMissingDatasets = $false
        StrongerEvaluationsOnly = $false
        IncludeAimrce = $false
        OpenOutputFolder = $false
        DryRun = $false
        ContinueOnError = $false
        Help = $false
    }

    $i = 0
    while ($i -lt $Arguments.Count) {
        $arg = $Arguments[$i]
        switch ($arg) {
            "--scenario" {
                $i++
                if ($i -ge $Arguments.Count -or $Arguments[$i].StartsWith("--")) {
                    throw "--scenario requires at least one value."
                }
                while ($i -lt $Arguments.Count -and -not $Arguments[$i].StartsWith("--")) {
                    $parsed.Scenarios += $Arguments[$i]
                    $i++
                }
                continue
            }
            "--configs" {
                $i++
                if ($i -ge $Arguments.Count -or $Arguments[$i].StartsWith("--")) {
                    throw "--configs requires at least one value."
                }
                while ($i -lt $Arguments.Count -and -not $Arguments[$i].StartsWith("--")) {
                    $parsed.Configs += $Arguments[$i]
                    $i++
                }
                continue
            }
            "--runs" {
                $i++
                $parsed.RunsSpecified = $true
                if ($i -ge $Arguments.Count -or $Arguments[$i].StartsWith("--")) {
                    throw "--runs requires at least one integer value."
                }
                while ($i -lt $Arguments.Count -and -not $Arguments[$i].StartsWith("--")) {
                    $runNumber = 0
                    if (-not [int]::TryParse($Arguments[$i], [ref]$runNumber)) {
                        throw "Run number '$($Arguments[$i])' is not a valid integer."
                    }
                    $parsed.Runs += $runNumber
                    $i++
                }
                continue
            }
            "--clean" { $parsed.Clean = $true; $i++; continue }
            "--yes" { $parsed.Yes = $true; $i++; continue }
            "--skip-build" { $parsed.SkipBuild = $true; $i++; continue }
            "--skip-analysis" { $parsed.SkipAnalysis = $true; $i++; continue }
            "--skip-training" { $parsed.SkipTraining = $true; $i++; continue }
            "--skip-runtime-export" { $parsed.SkipRuntimeExport = $true; $i++; continue }
            "--rebuild-missing-datasets" { $parsed.RebuildMissingDatasets = $true; $i++; continue }
            "--stronger-evaluations-only" { $parsed.StrongerEvaluationsOnly = $true; $i++; continue }
            "--include-aimrce" { $parsed.IncludeAimrce = $true; $i++; continue }
            "--open-output-folder" { $parsed.OpenOutputFolder = $true; $i++; continue }
            "--dry-run" { $parsed.DryRun = $true; $i++; continue }
            "--continue-on-error" { $parsed.ContinueOnError = $true; $i++; continue }
            "--help" { $parsed.Help = $true; $i++; continue }
            default {
                throw "Unsupported argument '$arg'. Run 'run_experiments.bat help' to see supported options."
            }
        }
    }

    if ($parsed.Runs.Count -eq 0) {
        $parsed.Runs = @(0)
    }

    $parsed.Scenarios = @($parsed.Scenarios | Select-Object -Unique)
    $parsed.Configs = @($parsed.Configs | Select-Object -Unique)
    $parsed.Runs = @($parsed.Runs | Select-Object -Unique)

    return [pscustomobject]$parsed
}

function Resolve-DatasetScenarios {
    param(
        [string[]]$RequestedScenarios
    )

    if (-not $RequestedScenarios -or $RequestedScenarios.Count -eq 0) {
        return @($script:ActiveDatasetScenarios)
    }

    foreach ($scenario in $RequestedScenarios) {
        if (-not $script:ScenarioPresets.Contains($scenario)) {
            throw "Unsupported scenario '$scenario'. Supported dataset-batch scenarios: $($script:ScenarioPresets.Keys -join ', ')"
        }
    }

    return @($RequestedScenarios)
}

function Resolve-SingleDatasetScenario {
    param(
        [string[]]$RequestedScenarios
    )

    $scenarioNames = @(Resolve-DatasetScenarios -RequestedScenarios $RequestedScenarios)
    if ($scenarioNames.Count -ne 1) {
        throw "dataset-batch requires exactly one --scenario value."
    }
    return $scenarioNames[0]
}

function Resolve-ConfigSelection {
    param(
        [string[]]$AllowedConfigs,
        [string[]]$RequestedConfigs
    )

    if (-not $RequestedConfigs -or $RequestedConfigs.Count -eq 0) {
        return @($AllowedConfigs)
    }

    $selected = @()
    foreach ($config in $RequestedConfigs) {
        if ($AllowedConfigs -notcontains $config) {
            throw "Unsupported config '$config'. Allowed configs: $($AllowedConfigs -join ', ')"
        }
        $selected += $config
    }

    return @($selected)
}

function Test-IsFullConfigSelection {
    param(
        [string[]]$AllowedConfigs,
        [string[]]$SelectedConfigs
    )

    if ($AllowedConfigs.Count -ne $SelectedConfigs.Count) {
        return $false
    }

    foreach ($config in $AllowedConfigs) {
        if ($SelectedConfigs -notcontains $config) {
            return $false
        }
    }

    return $true
}

function Resolve-RegionalCongestionProtectionRunNumbers {
    param(
        $Options
    )

    $allowedRunNumbers = @($script:RegionalBackboneCongestionProtectionCohortPreset.DefaultRunNumbers)
    if (-not $Options.RunsSpecified) {
        return $allowedRunNumbers
    }

    $selectedRunNumbers = @($Options.Runs | Select-Object -Unique)
    foreach ($runNumber in $selectedRunNumbers) {
        if ($allowedRunNumbers -notcontains $runNumber) {
            throw "regional-congestion-protection-batch supports only run numbers $($allowedRunNumbers -join ', ') because the dedicated cohort wrappers expose five repeated runs."
        }
    }

    return $selectedRunNumbers
}

function Resolve-RegionalMixedTrafficProtectionRunNumbers {
    param(
        $Options
    )

    $allowedRunNumbers = @($script:RegionalBackboneMixedTrafficProtectionCohortPreset.DefaultRunNumbers)
    if (-not $Options.RunsSpecified) {
        return $allowedRunNumbers
    }

    $selectedRunNumbers = @($Options.Runs | Select-Object -Unique)
    foreach ($runNumber in $selectedRunNumbers) {
        if ($allowedRunNumbers -notcontains $runNumber) {
            throw "regional-mixed-traffic-protection-batch supports only run numbers $($allowedRunNumbers -join ', ') because the dedicated mixed UDP/TCP cohort wrappers expose five repeated runs."
        }
    }

    return $selectedRunNumbers
}

function Get-OmnetppRoot {
    $candidate = $projectRoot
    while ($true) {
        if ((Test-Path (Join-Path $candidate "Makefile.inc")) -and (Test-Path (Join-Path $candidate "bin"))) {
            return (Resolve-Path $candidate).Path
        }

        $parent = Split-Path $candidate -Parent
        if (-not $parent -or $parent -eq $candidate) {
            break
        }
        $candidate = $parent
    }

    throw "Could not locate the OMNeT++ root from '$projectRoot'. Expected a parent directory containing Makefile.inc and bin."
}

function Get-InetRoot {
    $makefilePath = Join-Path $srcDir "Makefile"
    if (Test-Path $makefilePath) {
        $inetLine = Select-String -Path $makefilePath -Pattern '^INET4_5_PROJ=(.+)$' | Select-Object -First 1
        if ($null -ne $inetLine) {
            $relativePath = $inetLine.Matches[0].Groups[1].Value.Trim()
            $candidate = Join-Path $srcDir $relativePath
            if (Test-Path $candidate) {
                return (Resolve-Path $candidate).Path
            }
        }
    }

    $fallback = Join-Path (Split-Path $projectRoot -Parent) "inet4.5"
    if (Test-Path $fallback) {
        return (Resolve-Path $fallback).Path
    }

    throw "Could not locate the local INET project root."
}

function Resolve-SimulationExecutable {
    param(
        [switch]$AllowMissing
    )

    $preferred = Join-Path $projectRoot "out\gcc-release\src\dissertationsim.exe"
    if (Test-Path $preferred) {
        return (Resolve-Path $preferred).Path
    }

    $candidates = Get-ChildItem (Join-Path $projectRoot "out") -Recurse -Filter "dissertationsim*.exe" -ErrorAction SilentlyContinue |
        Sort-Object @{ Expression = { if ($_.Name -like "*_dbg.exe") { 1 } else { 0 } } }, @{ Expression = "LastWriteTime"; Descending = $true }
    if ($candidates -and $candidates.Count -gt 0) {
        return $candidates[0].FullName
    }

    if ($AllowMissing) {
        return $preferred
    }

    throw "No dissertation simulation executable was found under '$($projectRoot)\out'. Build the project first. --skip-build is only safe when a previously built dissertationsim executable already exists."
}

function Initialize-ToolEnvironment {
    if ($script:ToolEnvironmentInitialized) {
        return
    }

    $script:OmnetppRoot = Get-OmnetppRoot
    $script:InetRoot = Get-InetRoot
    $script:MakeExe = Join-Path $script:OmnetppRoot "tools\win32.x86_64\usr\bin\make.exe"
    $script:OppConfigfilepathScript = Join-Path $script:OmnetppRoot "bin\opp_configfilepath"
    $omnetppUsrBin = Join-Path $script:OmnetppRoot "tools\win32.x86_64\usr\bin"
    $omnetppClangBin = Join-Path $script:OmnetppRoot "tools\win32.x86_64\clang64\bin"
    $omnetppBin = Join-Path $script:OmnetppRoot "bin"
    $inetSrcDir = Join-Path $script:InetRoot "src"

    foreach ($pathToCheck in @($script:MakeExe, $script:OppConfigfilepathScript, $omnetppUsrBin, $omnetppClangBin, $omnetppBin, $inetSrcDir)) {
        if (-not (Test-Path $pathToCheck)) {
            throw "Required OMNeT++ or INET path was not found: $pathToCheck"
        }
    }

    $configFile = Join-Path $script:OmnetppRoot "Makefile.inc"
    if (-not (Test-Path $configFile)) {
        throw "Required OMNeT++ configuration file was not found: $configFile"
    }

    $pathEntries = @($omnetppUsrBin, $omnetppClangBin, $omnetppBin, $inetSrcDir)
    $existingEntries = @()
    if ($env:Path) {
        $existingEntries = $env:Path.Split(";") | Where-Object { $_ }
    }
    $env:Path = (($pathEntries + $existingEntries) | Where-Object { $_ } | Select-Object -Unique) -join ";"

    # Standard OMNeT++ runtime behavior: the simulator needs a NED search path.
    # This workflow keeps that explicit and project-local for auditability.
    $script:NedPath = @(
        $simulationsDir,
        (Join-Path $projectRoot "src"),
        $inetSrcDir
    ) -join ";"

    # Keep OMNETPP_CONFIGFILE unset for this project-local build workflow.
    # The generated src/Makefile already knows how to resolve the local
    # installation's Makefile.inc through opp_configfilepath when the OMNeT++
    # bin directory and sh.exe are available on PATH. This avoids cross-shell
    # path-format issues with inherited Windows-style environment overrides.
    $script:IgnoredOmnetppConfigOverride = $null
    if (-not [string]::IsNullOrWhiteSpace($env:OMNETPP_CONFIGFILE)) {
        $script:IgnoredOmnetppConfigOverride = $env:OMNETPP_CONFIGFILE
        Remove-Item Env:OMNETPP_CONFIGFILE -ErrorAction SilentlyContinue
    }

    $script:BuildConfigResolutionDescription = "Build bootstrap will rely on src/Makefile -> opp_configfilepath -> Makefile.inc."
    if ($script:IgnoredOmnetppConfigOverride) {
        $script:BuildConfigResolutionDescription += " Ignored inherited OMNETPP_CONFIGFILE override: '$($script:IgnoredOmnetppConfigOverride)'."
    }

    $script:SimulationExecutable = Resolve-SimulationExecutable -AllowMissing
    $script:ToolEnvironmentInitialized = $true
}

function Get-BuildBootstrapDiagnostic {
    $installationConfigPath = Join-Path $script:OmnetppRoot "Makefile.inc"
    $existingExecutable = Resolve-SimulationExecutable -AllowMissing
    $lines = @(
        "OMNeT++ root: $($script:OmnetppRoot)",
        "OMNeT++ Makefile.inc: $installationConfigPath",
        "opp_configfilepath script: $($script:OppConfigfilepathScript)",
        "make executable: $($script:MakeExe)",
        "Build config resolution: $($script:BuildConfigResolutionDescription)"
    )

    if ($script:IgnoredOmnetppConfigOverride) {
        $lines += "Ignored OMNETPP_CONFIGFILE override: $($script:IgnoredOmnetppConfigOverride)"
    }

    if (Test-Path $existingExecutable) {
        $lines += "Existing project executable detected: $existingExecutable"
        $lines += "If you do not need a rebuild, rerun with --skip-build."
    }
    else {
        $lines += "No existing project executable was detected under the local out/ tree."
    }

    return ($lines -join " ")
}

function Quote-DisplayArgument {
    param(
        [string]$Value
    )

    if ($Value -match '[\s";]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

function Format-CommandLine {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    return ((@((Quote-DisplayArgument $FilePath)) + ($Arguments | ForEach-Object { Quote-DisplayArgument $_ })) -join " ")
}

function New-BatchContext {
    param(
        [string]$BatchCommand,
        [string[]]$ScenarioNames
    )

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $folderName = $timestamp + "-" + $BatchCommand
    if ($ScenarioNames -and $ScenarioNames.Count -gt 0) {
        $folderName += "-" + (($ScenarioNames -join "-").Replace(" ", "_"))
    }

    $logDir = Join-Path $logsRoot $folderName
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null

    return [pscustomobject]@{
        Command = $BatchCommand
        StartedAt = Get-Date
        TimestampLabel = $timestamp
        LogDir = $logDir
        StepResults = New-Object 'System.Collections.Generic.List[object]'
        Artifacts = New-Object 'System.Collections.Generic.List[object]'
        Warnings = New-Object 'System.Collections.Generic.List[string]'
        PendingFolderOpens = New-Object 'System.Collections.Generic.List[object]'
    }
}

function Get-StepLogPath {
    param(
        $Context,
        [string]$BaseName
    )

    return Join-Path $Context.LogDir ("{0}-{1}" -f $Context.TimestampLabel, $BaseName)
}

function Add-StepResult {
    param(
        $Context,
        [string]$Step,
        [string]$Status,
        [string]$Details
    )

    $entry = [pscustomobject]@{
        Step = $Step
        Status = $Status
        Details = $Details
    }
    [void]$Context.StepResults.Add($entry)
}

# Workflow usability helpers below only surface generated files and optionally
# open folders for the local Windows user. They do not change experiment
# methodology, OMNeT++ / INET behavior, or the current AI-MRCE runtime logic.
function Add-ContextWarning {
    param(
        $Context,
        [string]$Message
    )

    if (-not [string]::IsNullOrWhiteSpace($Message)) {
        [void]$Context.Warnings.Add($Message)
    }
}

function Format-ArtifactSize {
    param(
        [long]$Bytes
    )

    return ("{0:N0} bytes" -f $Bytes)
}

function Get-ArtifactMetadata {
    param(
        [string]$Path,
        [string]$Category,
        [string]$SourceStep
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    $item = Get-Item -LiteralPath $Path
    return [pscustomobject]@{
        Category = $Category
        SourceStep = $SourceStep
        Path = $item.FullName
        Length = [long]$item.Length
        LastWriteTime = $item.LastWriteTime
    }
}

function Get-ArtifactDetailLines {
    param(
        $Artifact,
        [string]$Indent = "  "
    )

    return @(
        ("{0}- {1}" -f $Indent, $Artifact.Category),
        ("{0}  Path: {1}" -f $Indent, $Artifact.Path),
        ("{0}  Size: {1}" -f $Indent, (Format-ArtifactSize -Bytes $Artifact.Length)),
        ("{0}  Last write time: {1}" -f $Indent, $Artifact.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss"))
    )
}

function Publish-StepArtifacts {
    param(
        $Context,
        [string]$LogPath,
        [string]$Heading,
        [object[]]$Artifacts,
        [switch]$DryRun
    )

    $lines = @("", $Heading)
    Write-Host ""
    Write-Host $Heading

    if ($DryRun) {
        $note = "  Dry run only; no files were created or updated."
        Write-Host $note
        $lines += $note
        Add-Content -Path $LogPath -Value $lines -Encoding UTF8
        return
    }

    if (-not $Artifacts -or $Artifacts.Count -eq 0) {
        $note = "  No artifact files were found for this step."
        Write-Host $note
        $lines += $note
        Add-Content -Path $LogPath -Value $lines -Encoding UTF8
        return
    }

    foreach ($artifact in $Artifacts) {
        [void]$Context.Artifacts.Add($artifact)
        $detailLines = Get-ArtifactDetailLines -Artifact $artifact
        foreach ($detailLine in $detailLines) {
            Write-Host $detailLine
        }
        $lines += $detailLines
    }

    Add-Content -Path $LogPath -Value $lines -Encoding UTF8
}

function Get-ArtifactSummaryLines {
    param(
        $Context
    )

    $lines = @("", "Created/updated artifacts:")
    if ($Context.Artifacts.Count -eq 0) {
        $lines += "None recorded."
        return $lines
    }

    foreach ($artifact in $Context.Artifacts) {
        $lines += "- [{0}] {1}" -f $artifact.SourceStep, $artifact.Category
        $lines += "  Path: {0}" -f $artifact.Path
        $lines += "  Size: {0}" -f (Format-ArtifactSize -Bytes $artifact.Length)
        $lines += "  Last write time: {0}" -f $artifact.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
    }

    return $lines
}

function Get-WarningSummaryLines {
    param(
        $Context
    )

    if ($Context.Warnings.Count -eq 0) {
        return @()
    }

    $lines = @("", "Warnings:")
    foreach ($warningMessage in $Context.Warnings) {
        $lines += "- $warningMessage"
    }
    return $lines
}

function Request-OutputFolderOpen {
    param(
        $Context,
        $Options,
        [string]$FolderPath,
        [string]$Reason
    )

    if (-not $Options.OpenOutputFolder -or $Options.DryRun) {
        return
    }

    if (-not (Test-Path $FolderPath)) {
        $message = "Requested output folder for $Reason does not exist: $FolderPath"
        Write-Warning $message
        Add-ContextWarning -Context $Context -Message $message
        return
    }

    $resolvedPath = (Resolve-Path $FolderPath).Path
    if ($Context.Command -eq "full-pipeline") {
        foreach ($entry in $Context.PendingFolderOpens) {
            if ($entry.Path -eq $resolvedPath) {
                return
            }
        }

        [void]$Context.PendingFolderOpens.Add([pscustomobject]@{
            Path = $resolvedPath
            Reason = $Reason
        })
        return
    }

    Open-OutputFolder -Context $Context -FolderPath $resolvedPath -Reason $Reason
}

function Open-OutputFolder {
    param(
        $Context,
        [string]$FolderPath,
        [string]$Reason
    )

    try {
        Start-Process -FilePath $script:ExplorerExe -ArgumentList @($FolderPath) -ErrorAction Stop | Out-Null
        Write-Host "Opened output folder in Windows Explorer ($Reason): $FolderPath"
    }
    catch {
        $message = "Could not open output folder in Windows Explorer ($Reason): $FolderPath. $($_.Exception.Message)"
        Write-Warning $message
        Add-ContextWarning -Context $Context -Message $message
    }
}

function Open-PendingOutputFolders {
    param(
        $Context,
        $Options
    )

    if (-not $Options.OpenOutputFolder -or $Options.DryRun) {
        return
    }

    foreach ($entry in $Context.PendingFolderOpens) {
        Open-OutputFolder -Context $Context -FolderPath $entry.Path -Reason $entry.Reason
    }
}

function Write-BatchSummary {
    param(
        $Context,
        [string]$OverallStatus
    )

    $summaryPath = Get-StepLogPath -Context $Context -BaseName "summary.txt"
    $finishedAt = Get-Date
    $duration = New-TimeSpan -Start $Context.StartedAt -End $finishedAt
    $lines = @(
        "Command: $($Context.Command)",
        "Started: $($Context.StartedAt.ToString('s'))",
        "Finished: $($finishedAt.ToString('s'))",
        "Duration: $($duration.ToString())",
        "Overall status: $OverallStatus",
        "Log directory: $($Context.LogDir)",
        ""
    )

    foreach ($step in $Context.StepResults) {
        $lines += "[{0}] {1} - {2}" -f $step.Status, $step.Step, $step.Details
    }

    $lines += Get-ArtifactSummaryLines -Context $Context
    $lines += Get-WarningSummaryLines -Context $Context

    Set-Content -Path $summaryPath -Value $lines -Encoding UTF8

    Write-Host ""
    Write-Host "Batch summary: $summaryPath"
    foreach ($line in $lines) {
        Write-Host $line
    }
}

function Invoke-ExternalCommand {
    param(
        $Context,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$LogName,
        [string]$Description,
        [switch]$DryRun
    )

    $logPath = Get-StepLogPath -Context $Context -BaseName $LogName
    $commandLine = Format-CommandLine -FilePath $FilePath -Arguments $Arguments

    Write-Host ""
    Write-Host "Step: $Description"
    Write-Host "  Working directory: $WorkingDirectory"
    Write-Host "  Command: $commandLine"
    Write-Host "  Log: $logPath"

    if ($DryRun) {
        Set-Content -Path $logPath -Value @(
            "DRY RUN",
            "Description: $Description",
            "Working directory: $WorkingDirectory",
            "Command: $commandLine"
        ) -Encoding UTF8

        return [pscustomobject]@{
            ExitCode = 0
            LogPath = $logPath
            CommandLine = $commandLine
            DryRun = $true
        }
    }

    $stdoutPath = Join-Path $Context.LogDir ([System.IO.Path]::GetRandomFileName())
    $stderrPath = Join-Path $Context.LogDir ([System.IO.Path]::GetRandomFileName())
    $exitCode = 0

    try {
        Push-Location $WorkingDirectory
        try {
            & $FilePath @Arguments 1> $stdoutPath 2> $stderrPath
            $exitCode = $LASTEXITCODE
            if ($null -eq $exitCode) {
                $exitCode = 0
            }
        }
        finally {
            Pop-Location
        }
    }
    catch {
        throw "Failed to start command for '$Description': $($_.Exception.Message)"
    }

    $stdout = ""
    $stderr = ""
    if (Test-Path $stdoutPath) {
        $stdout = Get-Content -Path $stdoutPath -Raw
    }
    if (Test-Path $stderrPath) {
        $stderr = Get-Content -Path $stderrPath -Raw
    }

    $combinedLines = @(
        "Description: $Description",
        "Working directory: $WorkingDirectory",
        "Command: $commandLine",
        "Exit code: $exitCode",
        "",
        "--- stdout ---",
        $stdout,
        "",
        "--- stderr ---",
        $stderr
    )
    Set-Content -Path $logPath -Value $combinedLines -Encoding UTF8

    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue

    if ($exitCode -ne 0) {
        throw "Command failed for '$Description' with exit code $exitCode. See log: $logPath"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        LogPath = $logPath
        CommandLine = $commandLine
        DryRun = $false
    }
}

function Invoke-RunAnalysisCommand {
    param(
        $Context,
        [string]$Subcommand,
        [string[]]$SubcommandArgs,
        [string]$LogName,
        [string]$Description,
        [switch]$DryRun
    )

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $runAnalysisScript,
        $Subcommand
    ) + $SubcommandArgs

    return Invoke-ExternalCommand `
        -Context $Context `
        -FilePath $powerShellExe `
        -Arguments $arguments `
        -WorkingDirectory $projectRoot `
        -LogName $LogName `
        -Description $Description `
        -DryRun:$DryRun
}

function Build-Project {
    param(
        $Context,
        [switch]$DryRun
    )

    Initialize-ToolEnvironment

    Write-Host ""
    Write-Host "Build bootstrap"
    Write-Host "  OMNeT++ root: $($script:OmnetppRoot)"
    Write-Host "  make executable: $($script:MakeExe)"
    Write-Host "  Config resolution: $($script:BuildConfigResolutionDescription)"

    try {
        Invoke-ExternalCommand `
            -Context $Context `
            -FilePath $script:MakeExe `
            -Arguments @() `
            -WorkingDirectory $srcDir `
            -LogName "build.log" `
            -Description "Build the local dissertation project binary" `
            -DryRun:$DryRun | Out-Null
    }
    catch {
        $diagnostic = Get-BuildBootstrapDiagnostic
        throw "Build bootstrap failed. $diagnostic Original error: $($_.Exception.Message)"
    }

    if (-not $DryRun) {
        $script:SimulationExecutable = Resolve-SimulationExecutable
    }

    $buildDetails = if ($DryRun) { "Dry run only; project build not executed." } else { "Project build completed." }
    Add-StepResult -Context $Context -Step "build" -Status "OK" -Details $buildDetails
}

function Get-CleanTargets {
    param(
        $Preset,
        [string[]]$ConfigNames,
        [int[]]$RunNumbers,
        [switch]$SubsetOnly
    )

    if (-not (Test-Path $Preset.EvalDir)) {
        return @()
    }

    if (-not $SubsetOnly) {
        return @(Get-ChildItem -Path $Preset.EvalDir -File | Sort-Object Name)
    }

    $targets = New-Object 'System.Collections.Generic.List[object]'
    foreach ($configName in $ConfigNames) {
        foreach ($runNumber in $RunNumbers) {
            foreach ($extension in @("sca", "vec", "vci")) {
                $artifactPath = Join-Path $Preset.EvalDir ("{0}-{1}.{2}" -f $configName, $runNumber, $extension)
                if (Test-Path $artifactPath) {
                    [void]$targets.Add((Get-Item -LiteralPath $artifactPath))
                }
            }
        }
    }

    return @($targets | Sort-Object Name -Unique)
}

function Remove-EvalOutputs {
    param(
        $Context,
        $Preset,
        [string[]]$ConfigNames,
        [int[]]$RunNumbers,
        [switch]$SubsetOnly,
        [switch]$DryRun
    )

    $scopeDescription = if ($SubsetOnly) { "targeted config outputs" } else { "entire eval directory contents" }
    $targets = Get-CleanTargets -Preset $Preset -ConfigNames $ConfigNames -RunNumbers $RunNumbers -SubsetOnly:$SubsetOnly
    $logPath = Get-StepLogPath -Context $Context -BaseName ("clean-{0}.log" -f $Preset.Name)

    if (-not (Test-Path $Preset.EvalDir)) {
        Write-Host ""
        Write-Host "No eval directory exists for scenario '$($Preset.Name)': $($Preset.EvalDir)"
        Set-Content -Path $logPath -Value @(
            "No cleanup performed.",
            "Eval directory did not exist: $($Preset.EvalDir)"
        ) -Encoding UTF8
        Add-StepResult -Context $Context -Step ("clean-{0}" -f $Preset.Name) -Status "OK" -Details "Eval directory did not exist."
        return
    }

    Write-Host ""
    Write-Host "Cleaning eval outputs for scenario '$($Preset.Name)'"
    Write-Host "  Scope: $scopeDescription"
    Write-Host "  Eval directory: $($Preset.EvalDir)"
    Write-Host "  Files targeted: $($targets.Count)"
    foreach ($target in $targets) {
        Write-Host "    $($target.Name)"
    }

    if ($DryRun) {
        $dryRunLines = @(
            "DRY RUN",
            "Scope: $scopeDescription",
            "Eval directory: $($Preset.EvalDir)",
            "Files targeted: $($targets.Count)"
        )
        $dryRunLines += ($targets | ForEach-Object { $_.FullName })
        Set-Content -Path $logPath -Value $dryRunLines -Encoding UTF8
        Add-StepResult -Context $Context -Step ("clean-{0}" -f $Preset.Name) -Status "OK" -Details "Dry run only; no files deleted."
        return
    }

    foreach ($target in $targets) {
        Remove-Item -LiteralPath $target.FullName -Force
    }

    Set-Content -Path $logPath -Value @(
        "Removed $($targets.Count) file(s).",
        "Scope: $scopeDescription",
        "Eval directory: $($Preset.EvalDir)"
    ) -Encoding UTF8
    Add-StepResult -Context $Context -Step ("clean-{0}" -f $Preset.Name) -Status "OK" -Details "Deleted $($targets.Count) file(s) from eval."
}

function Get-ArtifactSnapshot {
    param(
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return [pscustomobject]@{
            Exists = $false
            Length = -1
            LastWriteTimeUtc = [datetime]::MinValue
        }
    }

    $item = Get-Item -LiteralPath $Path
    return [pscustomobject]@{
        Exists = $true
        Length = $item.Length
        LastWriteTimeUtc = $item.LastWriteTimeUtc
    }
}

function Test-ArtifactWasUpdated {
    param(
        [string]$Path,
        $BeforeSnapshot,
        [datetime]$StartedAtUtc
    )

    if (-not (Test-Path $Path)) {
        return $false
    }

    $item = Get-Item -LiteralPath $Path
    if (-not $BeforeSnapshot.Exists) {
        return $true
    }

    if ($item.LastWriteTimeUtc -gt $BeforeSnapshot.LastWriteTimeUtc) {
        return $true
    }

    if ($item.LastWriteTimeUtc -ge $StartedAtUtc.AddSeconds(-1)) {
        return $true
    }

    return $false
}

function Invoke-SimulationConfig {
    param(
        $Context,
        $Preset,
        [string]$ConfigName,
        [int]$RunNumber,
        [switch]$DryRun
    )

    Initialize-ToolEnvironment
    if (-not (Test-Path $script:SimulationExecutable)) {
        $script:SimulationExecutable = Resolve-SimulationExecutable
    }

    New-Item -ItemType Directory -Path $Preset.EvalDir -Force | Out-Null

    $scaPath = Join-Path $Preset.EvalDir ("{0}-{1}.sca" -f $ConfigName, $RunNumber)
    $vecPath = Join-Path $Preset.EvalDir ("{0}-{1}.vec" -f $ConfigName, $RunNumber)
    $vciPath = Join-Path $Preset.EvalDir ("{0}-{1}.vci" -f $ConfigName, $RunNumber)
    $scaBefore = Get-ArtifactSnapshot -Path $scaPath
    $vecBefore = Get-ArtifactSnapshot -Path $vecPath
    $startedAtUtc = [datetime]::UtcNow
    $stepName = ("simulate-{0}-{1}-run{2}" -f $Preset.Name, $ConfigName, $RunNumber)

    $arguments = @(
        "-u", "Cmdenv",
        "--cmdenv-express-mode=true",
        "-f", "omnetpp.ini",
        "-c", $ConfigName,
        "-r", $RunNumber.ToString(),
        "-n", $script:NedPath
    )

    $commandResult = Invoke-ExternalCommand `
        -Context $Context `
        -FilePath $script:SimulationExecutable `
        -Arguments $arguments `
        -WorkingDirectory $Preset.ScenarioDir `
        -LogName ("{0}.log" -f $stepName) `
        -Description ("Run scenario {0}, config {1}, run {2} in standard OMNeT++ Cmdenv express mode" -f $Preset.Name, $ConfigName, $RunNumber) `
        -DryRun:$DryRun

    if ($DryRun) {
        Add-StepResult -Context $Context -Step $stepName -Status "OK" -Details "Dry run only; simulation not executed."
        return
    }

    if (-not (Test-ArtifactWasUpdated -Path $scaPath -BeforeSnapshot $scaBefore -StartedAtUtc $startedAtUtc)) {
        throw "Expected scalar output was not created or updated for config '$ConfigName' run '$RunNumber': $scaPath"
    }
    if (-not (Test-ArtifactWasUpdated -Path $vecPath -BeforeSnapshot $vecBefore -StartedAtUtc $startedAtUtc)) {
        throw "Expected vector output was not created or updated for config '$ConfigName' run '$RunNumber': $vecPath"
    }

    $artifacts = @(
        (Get-ArtifactMetadata -Path $scaPath -Category "Simulation scalar (.sca)" -SourceStep $stepName),
        (Get-ArtifactMetadata -Path $vecPath -Category "Simulation vector (.vec)" -SourceStep $stepName)
    )
    $vciArtifact = Get-ArtifactMetadata -Path $vciPath -Category "Simulation vector index (.vci)" -SourceStep $stepName
    if ($null -ne $vciArtifact) {
        $artifacts += $vciArtifact
    }

    Publish-StepArtifacts `
        -Context $Context `
        -LogPath $commandResult.LogPath `
        -Heading "Created or updated simulation artifacts" `
        -Artifacts $artifacts

    Add-StepResult -Context $Context -Step $stepName -Status "OK" -Details "Validated scalar and vector outputs."
}

function Invoke-DatasetBatchCore {
    param(
        $Context,
        $Preset,
        [string[]]$ConfigNames,
        [int[]]$RunNumbers,
        $Options
    )

    Write-Host ""
    Write-Host "Scenario batch: $($Preset.Name)"
    Write-Host "  Purpose: $($Preset.Description)"
    Write-Host "  Configs: $($ConfigNames -join ', ')"
    Write-Host "  Runs: $($RunNumbers -join ', ')"
    Write-Host "  Eval directory: $($Preset.EvalDir)"

    if (-not $Options.SkipAnalysis -and -not (Test-IsFullConfigSelection -AllowedConfigs $Preset.EvalConfigs -SelectedConfigs $ConfigNames)) {
        throw "Dataset build/report is blocked when --configs selects only a subset of '$($Preset.Name)'. Use --skip-analysis for manual subset execution or run the full eval config set."
    }

    if ($Options.Clean) {
        Remove-EvalOutputs -Context $Context -Preset $Preset -ConfigNames $ConfigNames -RunNumbers $RunNumbers -DryRun:$Options.DryRun
    }

    $hadSimulationFailure = $false
    foreach ($configName in $ConfigNames) {
        foreach ($runNumber in $RunNumbers) {
            try {
                Invoke-SimulationConfig -Context $Context -Preset $Preset -ConfigName $configName -RunNumber $runNumber -DryRun:$Options.DryRun
            }
            catch {
                $hadSimulationFailure = $true
                Add-StepResult -Context $Context -Step ("simulate-{0}-{1}-run{2}" -f $Preset.Name, $configName, $runNumber) -Status "FAILED" -Details $_.Exception.Message
                if (-not $Options.ContinueOnError) {
                    throw
                }
                Write-Warning $_.Exception.Message
            }
        }
    }

    if ($hadSimulationFailure) {
        Add-StepResult -Context $Context -Step ("analysis-{0}" -f $Preset.Name) -Status "SKIPPED" -Details "Skipped dataset build/report because at least one simulation run failed."
        return $false
    }

    Request-OutputFolderOpen `
        -Context $Context `
        -Options $Options `
        -FolderPath $Preset.EvalDir `
        -Reason ("{0} eval outputs" -f $Preset.Name)

    if ($Options.SkipAnalysis) {
        Add-StepResult -Context $Context -Step ("analysis-{0}" -f $Preset.Name) -Status "OK" -Details "Skipped dataset build/report by request."
        return $true
    }

    $datasetStepName = ("build-dataset-{0}" -f $Preset.Name)
    $datasetCommandResult = Invoke-RunAnalysisCommand `
        -Context $Context `
        -Subcommand "build-dataset" `
        -SubcommandArgs @("--scenario", $Preset.Name) `
        -LogName ("{0}.log" -f $datasetStepName) `
        -Description ("Build dataset for scenario {0}" -f $Preset.Name) `
        -DryRun:$Options.DryRun

    if (-not $Options.DryRun -and -not (Test-Path $Preset.DatasetPath)) {
        throw "Dataset build completed without creating the expected dataset file: $($Preset.DatasetPath)"
    }
    if (-not $Options.DryRun) {
        $datasetArtifacts = @(
            (Get-ArtifactMetadata -Path $Preset.DatasetPath -Category "Dataset CSV" -SourceStep $datasetStepName)
        )
        Publish-StepArtifacts `
            -Context $Context `
            -LogPath $datasetCommandResult.LogPath `
            -Heading "Created or updated dataset artifacts" `
            -Artifacts $datasetArtifacts
    }
    $datasetDetails = if ($Options.DryRun) { "Dry run only; dataset build not executed." } else { "Dataset build completed." }
    Add-StepResult -Context $Context -Step $datasetStepName -Status "OK" -Details $datasetDetails

    $reportStepName = ("dataset-report-{0}" -f $Preset.Name)
    $reportCommandResult = Invoke-RunAnalysisCommand `
        -Context $Context `
        -Subcommand "dataset-report" `
        -SubcommandArgs @("--scenario", $Preset.Name) `
        -LogName ("{0}.log" -f $reportStepName) `
        -Description ("Build dataset report for scenario {0}" -f $Preset.Name) `
        -DryRun:$Options.DryRun

    if (-not $Options.DryRun -and -not (Test-Path $Preset.ReportPath)) {
        throw "Dataset report completed without creating the expected report file: $($Preset.ReportPath)"
    }
    if (-not $Options.DryRun) {
        $reportArtifacts = @(
            (Get-ArtifactMetadata -Path $Preset.ReportPath -Category "Dataset report (.txt)" -SourceStep $reportStepName)
        )
        foreach ($optionalArtifact in @(
            @{ Property = "MissingCsvPath"; Category = "Dataset missing-value summary (.csv)" },
            @{ Property = "PerConfigCsvPath"; Category = "Dataset per-config summary (.csv)" },
            @{ Property = "OutcomeSummaryPath"; Category = "Dataset outcome summary (.csv)" }
        )) {
            if ($Preset.PSObject.Properties.Name -contains $optionalArtifact.Property) {
                $artifactPath = $Preset.($optionalArtifact.Property)
                $artifact = Get-ArtifactMetadata -Path $artifactPath -Category $optionalArtifact.Category -SourceStep $reportStepName
                if ($null -ne $artifact) {
                    $reportArtifacts += $artifact
                }
            }
        }
        Publish-StepArtifacts `
            -Context $Context `
            -LogPath $reportCommandResult.LogPath `
            -Heading "Created or updated dataset report artifacts" `
            -Artifacts $reportArtifacts
    }
    $reportDetails = if ($Options.DryRun) { "Dry run only; dataset report not executed." } else { "Dataset report completed." }
    Add-StepResult -Context $Context -Step $reportStepName -Status "OK" -Details $reportDetails

    Request-OutputFolderOpen `
        -Context $Context `
        -Options $Options `
        -FolderPath $reportsDir `
        -Reason "dataset reports and analysis artifacts"

    return $true
}

function Ensure-DatasetArtifacts {
    param(
        $Context,
        [string[]]$ScenarioNames,
        $Options
    )

    foreach ($scenarioName in $ScenarioNames) {
        $preset = $script:ScenarioPresets[$scenarioName]
        if (Test-Path $preset.DatasetPath) {
            Add-StepResult -Context $Context -Step ("dataset-check-{0}" -f $scenarioName) -Status "OK" -Details "Dataset exists: $($preset.DatasetPath)"
            continue
        }

        if (-not $Options.RebuildMissingDatasets) {
            throw "Required dataset is missing for scenario '$scenarioName': $($preset.DatasetPath). Re-run with --rebuild-missing-datasets to rebuild dataset artifacts from existing raw results."
        }

        $datasetStepName = ("rebuild-dataset-{0}" -f $scenarioName)
        $datasetCommandResult = Invoke-RunAnalysisCommand `
            -Context $Context `
            -Subcommand "build-dataset" `
            -SubcommandArgs @("--scenario", $scenarioName) `
            -LogName ("{0}.log" -f $datasetStepName) `
            -Description ("Rebuild missing dataset for scenario {0}" -f $scenarioName) `
            -DryRun:$Options.DryRun

        $reportStepName = ("rebuild-dataset-report-{0}" -f $scenarioName)
        $reportCommandResult = Invoke-RunAnalysisCommand `
            -Context $Context `
            -Subcommand "dataset-report" `
            -SubcommandArgs @("--scenario", $scenarioName) `
            -LogName ("{0}.log" -f $reportStepName) `
            -Description ("Rebuild missing dataset report for scenario {0}" -f $scenarioName) `
            -DryRun:$Options.DryRun

        if (-not $Options.DryRun -and -not (Test-Path $preset.DatasetPath)) {
            throw "Missing dataset rebuild did not create the expected file: $($preset.DatasetPath)"
        }
        if (-not $Options.DryRun -and -not (Test-Path $preset.ReportPath)) {
            throw "Missing dataset report rebuild did not create the expected file: $($preset.ReportPath)"
        }

        if (-not $Options.DryRun) {
            $rebuiltDatasetArtifacts = @(
                (Get-ArtifactMetadata -Path $preset.DatasetPath -Category "Dataset CSV" -SourceStep $datasetStepName)
            )
            Publish-StepArtifacts `
                -Context $Context `
                -LogPath $datasetCommandResult.LogPath `
                -Heading "Created or updated dataset artifacts" `
                -Artifacts $rebuiltDatasetArtifacts

            $rebuiltReportArtifacts = @(
                (Get-ArtifactMetadata -Path $preset.ReportPath -Category "Dataset report (.txt)" -SourceStep $reportStepName)
            )
            Publish-StepArtifacts `
                -Context $Context `
                -LogPath $reportCommandResult.LogPath `
                -Heading "Created or updated dataset report artifacts" `
                -Artifacts $rebuiltReportArtifacts
        }

        $rebuildDetails = if ($Options.DryRun) { "Dry run only; dataset/report rebuild not executed." } else { "Dataset and report rebuild completed." }
        Add-StepResult -Context $Context -Step $datasetStepName -Status "OK" -Details $rebuildDetails
    }
}

function Invoke-TrainingBatchCore {
    param(
        $Context,
        [string[]]$ScenarioNames,
        $Options
    )

    Ensure-DatasetArtifacts -Context $Context -ScenarioNames $ScenarioNames -Options $Options

    $trainingArgs = @("--scenarios") + $ScenarioNames
    if ($Options.StrongerEvaluationsOnly) {
        # These modes are the generalization-oriented methodological checks.
        # The optimistic random split remains available through the analysis
        # script, but this flag intentionally excludes it.
        $trainingArgs += @("--evaluations") + $script:StrongerEvaluationModes
    }

    $trainingStepName = "train-risk-model"
    $trainingCommandResult = Invoke-RunAnalysisCommand `
        -Context $Context `
        -Subcommand "train-risk-model" `
        -SubcommandArgs $trainingArgs `
        -LogName "train-risk-model.log" `
        -Description "Run offline risk-model training and evaluation" `
        -DryRun:$Options.DryRun

    if (-not $Options.DryRun) {
        $trainingArtifacts = @()
        foreach ($artifactName in $script:TrainingArtifactNames) {
        $artifactPath = Join-Path $trainingDir $artifactName
            $artifact = Get-ArtifactMetadata -Path $artifactPath -Category ("Training artifact ({0})" -f $artifactName) -SourceStep $trainingStepName
            if ($null -ne $artifact) {
                $trainingArtifacts += $artifact
            }
        }

        Publish-StepArtifacts `
            -Context $Context `
            -LogPath $trainingCommandResult.LogPath `
            -Heading "Created or updated training artifacts" `
            -Artifacts $trainingArtifacts
    }

    $trainingDetails = if ($Options.DryRun) { "Dry run only; offline training not executed." } else { "Offline training completed." }
    Add-StepResult -Context $Context -Step $trainingStepName -Status "OK" -Details $trainingDetails

    Request-OutputFolderOpen `
        -Context $Context `
        -Options $Options `
        -FolderPath $trainingDir `
        -Reason "training analysis artifacts"
}

function Invoke-AiMrceBatchCore {
    param(
        $Context,
        $Options
    )

    $preset = $script:ScenarioPresets["regionalbackbone"]
    $configNames = Resolve-ConfigSelection -AllowedConfigs $preset.AiMrceConfigs -RequestedConfigs $Options.Configs
    $runtimeExportPerformed = $false

    Write-Host ""
    Write-Host "AI-MRCE runtime batch"
    Write-Host "  Configs: $($configNames -join ', ')"
    Write-Host "  Runs: $($Options.Runs -join ', ')"
    Write-Host "  Eval directory: $($preset.EvalDir)"

    if ($Options.Clean) {
        # AI-MRCE configs share the regionalbackbone eval directory with the
        # dataset branch, so this cleanup intentionally removes only targeted
        # AI-MRCE outputs rather than the whole scenario directory.
        Remove-EvalOutputs -Context $Context -Preset $preset -ConfigNames $configNames -RunNumbers $Options.Runs -SubsetOnly -DryRun:$Options.DryRun
    }

    if (-not $Options.SkipRuntimeExport) {
        if (-not $Options.DryRun -and -not (Test-Path $preset.DatasetPath)) {
            throw "AI-MRCE runtime export requires the existing regionalbackbone dataset: $($preset.DatasetPath). Generate it first or rerun with --skip-runtime-export to reuse the current runtime artifacts."
        }

        $runtimeExportStepName = "export-runtime-models"
        $runtimeExportCommandResult = Invoke-RunAnalysisCommand `
            -Context $Context `
            -Subcommand "export-runtime-models" `
            -SubcommandArgs @("--configs", "RegionalBackboneCongestionDegradation") `
            -LogName "export-runtime-models.log" `
            -Description "Export the AI-MRCE runtime deployment artifacts" `
            -DryRun:$Options.DryRun

        if (-not $Options.DryRun) {
            $runtimeArtifacts = @()
            foreach ($artifactPath in $script:RegionalBackboneRuntimeArtifactPaths) {
                $artifact = Get-ArtifactMetadata -Path $artifactPath -Category "Runtime deployment artifact (.csv)" -SourceStep $runtimeExportStepName
                if ($null -ne $artifact) {
                    $runtimeArtifacts += $artifact
                }
            }
            Publish-StepArtifacts `
                -Context $Context `
                -LogPath $runtimeExportCommandResult.LogPath `
                -Heading "Created or updated runtime export artifacts" `
                -Artifacts $runtimeArtifacts
        }

        $runtimeExportPerformed = $true
        $runtimeExportDetails = if ($Options.DryRun) { "Dry run only; runtime deployment artifact export not executed." } else { "Runtime deployment artifact export completed." }
        Add-StepResult -Context $Context -Step "export-runtime-models" -Status "OK" -Details $runtimeExportDetails
    }
    else {
        Add-StepResult -Context $Context -Step "export-runtime-models" -Status "OK" -Details "Skipped runtime export by request."
    }

    $hadSimulationFailure = $false
    foreach ($configName in $configNames) {
        foreach ($runNumber in $Options.Runs) {
            try {
                Invoke-SimulationConfig -Context $Context -Preset $preset -ConfigName $configName -RunNumber $runNumber -DryRun:$Options.DryRun
            }
            catch {
                $hadSimulationFailure = $true
                Add-StepResult -Context $Context -Step ("simulate-regionalbackbone-{0}-run{1}" -f $configName, $runNumber) -Status "FAILED" -Details $_.Exception.Message
                if (-not $Options.ContinueOnError) {
                    throw
                }
                Write-Warning $_.Exception.Message
            }
        }
    }

    if (-not $hadSimulationFailure) {
        Request-OutputFolderOpen `
            -Context $Context `
            -Options $Options `
            -FolderPath $preset.EvalDir `
            -Reason "regionalbackbone AI-MRCE eval outputs"

        if ($runtimeExportPerformed) {
            Request-OutputFolderOpen `
                -Context $Context `
                -Options $Options `
                -FolderPath $preset.ScenarioDir `
                -Reason "regionalbackbone runtime export artifacts"
        }
    }

    return (-not $hadSimulationFailure)
}

function Invoke-RegionalCongestionProtectionBatchCore {
    param(
        $Context,
        $Options
    )

    $preset = $script:RegionalBackboneCongestionProtectionCohortPreset
    $runNumbers = @(Resolve-RegionalCongestionProtectionRunNumbers -Options $Options)
    $runtimeExportPerformed = $false

    Write-Host ""
    Write-Host "Regional congestion protection cohort batch"
    Write-Host "  Purpose: $($preset.Description)"
    Write-Host "  Configs: $($preset.EvalConfigs -join ', ')"
    Write-Host "  Runs: $($runNumbers -join ', ')"
    Write-Host "  Eval directory: $($preset.EvalDir)"

    if (-not $Options.SkipRuntimeExport) {
        if (-not $Options.DryRun -and -not (Test-Path $script:ScenarioPresets["regionalbackbone"].DatasetPath)) {
            throw "regional-congestion-protection-batch requires the existing regionalbackbone dataset for runtime export: $($script:ScenarioPresets["regionalbackbone"].DatasetPath). Generate it first or rerun with --skip-runtime-export to reuse the current runtime artifacts."
        }

        $runtimeExportStepName = "export-runtime-models"
        $runtimeExportCommandResult = Invoke-RunAnalysisCommand `
            -Context $Context `
            -Subcommand "export-runtime-models" `
            -SubcommandArgs @("--configs", "RegionalBackboneCongestionDegradation") `
            -LogName "export-runtime-models.log" `
            -Description "Export the AI-MRCE runtime deployment artifacts for the regional congestion protection cohort" `
            -DryRun:$Options.DryRun

        if (-not $Options.DryRun) {
            $runtimeArtifacts = @()
            foreach ($artifactPath in $script:RegionalBackboneRuntimeArtifactPaths) {
                $artifact = Get-ArtifactMetadata -Path $artifactPath -Category "Runtime deployment artifact (.csv)" -SourceStep $runtimeExportStepName
                if ($null -ne $artifact) {
                    $runtimeArtifacts += $artifact
                }
            }
            Publish-StepArtifacts `
                -Context $Context `
                -LogPath $runtimeExportCommandResult.LogPath `
                -Heading "Created or updated runtime export artifacts" `
                -Artifacts $runtimeArtifacts
        }

        $runtimeExportPerformed = $true
        $runtimeExportDetails = if ($Options.DryRun) { "Dry run only; runtime deployment artifact export not executed." } else { "Runtime deployment artifact export completed." }
        Add-StepResult -Context $Context -Step $runtimeExportStepName -Status "OK" -Details $runtimeExportDetails
    }
    else {
        Add-StepResult -Context $Context -Step "export-runtime-models" -Status "OK" -Details "Skipped runtime export by request."
    }

    $batchSucceeded = Invoke-DatasetBatchCore `
        -Context $Context `
        -Preset $preset `
        -ConfigNames $preset.EvalConfigs `
        -RunNumbers $runNumbers `
        -Options $Options

    if (-not $batchSucceeded) {
        Add-StepResult -Context $Context -Step "compare-outcomes-regional-congestion-protection" -Status "SKIPPED" -Details "Skipped cohort comparison because an earlier simulation or dataset step failed."
        return $false
    }

    $comparisonStepName = "compare-outcomes-regional-congestion-protection"
    $comparisonCommandResult = Invoke-RunAnalysisCommand `
        -Context $Context `
        -Subcommand "compare-outcomes" `
        -SubcommandArgs @("--inputs", $preset.OutcomeSummaryPath, "--output-prefix", $preset.ComparisonOutputPrefix) `
        -LogName ("{0}.log" -f $comparisonStepName) `
        -Description "Build the focused practical comparison for the regional congestion protection cohort" `
        -DryRun:$Options.DryRun

    if (-not $Options.DryRun) {
        foreach ($requiredPath in @($preset.ComparisonRunsPath, $preset.ComparisonSummaryPath, $preset.ComparisonReportPath)) {
            if (-not (Test-Path $requiredPath)) {
                throw "regional-congestion-protection-batch comparison step did not create the expected file: $requiredPath"
            }
        }

        $comparisonArtifacts = @(
            (Get-ArtifactMetadata -Path $preset.ComparisonRunsPath -Category "Cohort comparison runs (.csv)" -SourceStep $comparisonStepName),
            (Get-ArtifactMetadata -Path $preset.ComparisonSummaryPath -Category "Cohort comparison summary (.csv)" -SourceStep $comparisonStepName),
            (Get-ArtifactMetadata -Path $preset.ComparisonReportPath -Category "Cohort comparison report (.txt)" -SourceStep $comparisonStepName)
        )
        Publish-StepArtifacts `
            -Context $Context `
            -LogPath $comparisonCommandResult.LogPath `
            -Heading "Created or updated cohort comparison artifacts" `
            -Artifacts $comparisonArtifacts
    }

    $comparisonDetails = if ($Options.DryRun) { "Dry run only; focused regional congestion protection comparison not executed." } else { "Focused regional congestion protection cohort comparison completed." }
    Add-StepResult -Context $Context -Step $comparisonStepName -Status "OK" -Details $comparisonDetails

    if ($runtimeExportPerformed) {
        Request-OutputFolderOpen `
            -Context $Context `
            -Options $Options `
            -FolderPath $script:RegionalBackboneCongestionProtectionCohortPreset.ScenarioDir `
            -Reason "regionalbackbone runtime export artifacts"
    }

    Request-OutputFolderOpen `
        -Context $Context `
        -Options $Options `
        -FolderPath $outcomesDir `
        -Reason "regional congestion protection cohort analysis artifacts"

    return $true
}

function Invoke-RegionalMixedTrafficProtectionBatchCore {
    param(
        $Context,
        $Options
    )

    $preset = $script:RegionalBackboneMixedTrafficProtectionCohortPreset
    $runNumbers = @(Resolve-RegionalMixedTrafficProtectionRunNumbers -Options $Options)
    $runtimeExportPerformed = $false

    Write-Host ""
    Write-Host "Regional mixed UDP/TCP protection cohort batch"
    Write-Host "  Purpose: $($preset.Description)"
    Write-Host "  Configs: $($preset.EvalConfigs -join ', ')"
    Write-Host "  Runs: $($runNumbers -join ', ')"
    Write-Host "  Eval directory: $($preset.EvalDir)"

    if (-not $Options.SkipRuntimeExport) {
        if (-not $Options.DryRun -and -not (Test-Path $script:ScenarioPresets["regionalbackbone"].DatasetPath)) {
            throw "regional-mixed-traffic-protection-batch requires the existing regionalbackbone dataset for runtime export: $($script:ScenarioPresets["regionalbackbone"].DatasetPath). Generate it first or rerun with --skip-runtime-export to reuse the current runtime artifacts."
        }

        $runtimeExportStepName = "export-runtime-models"
        $runtimeExportCommandResult = Invoke-RunAnalysisCommand `
            -Context $Context `
            -Subcommand "export-runtime-models" `
            -SubcommandArgs @("--configs", "RegionalBackboneCongestionDegradation") `
            -LogName "export-runtime-models.log" `
            -Description "Export the AI-MRCE runtime deployment artifacts for the regional mixed UDP/TCP protection cohort" `
            -DryRun:$Options.DryRun

        if (-not $Options.DryRun) {
            $runtimeArtifacts = @()
            foreach ($artifactPath in $script:RegionalBackboneRuntimeArtifactPaths) {
                $artifact = Get-ArtifactMetadata -Path $artifactPath -Category "Runtime deployment artifact (.csv)" -SourceStep $runtimeExportStepName
                if ($null -ne $artifact) {
                    $runtimeArtifacts += $artifact
                }
            }
            Publish-StepArtifacts `
                -Context $Context `
                -LogPath $runtimeExportCommandResult.LogPath `
                -Heading "Created or updated runtime export artifacts" `
                -Artifacts $runtimeArtifacts
        }

        $runtimeExportPerformed = $true
        $runtimeExportDetails = if ($Options.DryRun) { "Dry run only; runtime deployment artifact export not executed." } else { "Runtime deployment artifact export completed." }
        Add-StepResult -Context $Context -Step $runtimeExportStepName -Status "OK" -Details $runtimeExportDetails
    }
    else {
        Add-StepResult -Context $Context -Step "export-runtime-models" -Status "OK" -Details "Skipped runtime export by request."
    }

    $batchSucceeded = Invoke-DatasetBatchCore `
        -Context $Context `
        -Preset $preset `
        -ConfigNames $preset.EvalConfigs `
        -RunNumbers $runNumbers `
        -Options $Options

    if (-not $batchSucceeded) {
        Add-StepResult -Context $Context -Step "compare-outcomes-regional-mixed-traffic-protection" -Status "SKIPPED" -Details "Skipped cohort comparison because an earlier simulation or dataset step failed."
        return $false
    }

    $comparisonStepName = "compare-outcomes-regional-mixed-traffic-protection"
    $comparisonCommandResult = Invoke-RunAnalysisCommand `
        -Context $Context `
        -Subcommand "compare-outcomes" `
        -SubcommandArgs @("--inputs", $preset.OutcomeSummaryPath, "--output-prefix", $preset.ComparisonOutputPrefix) `
        -LogName ("{0}.log" -f $comparisonStepName) `
        -Description "Build the focused practical comparison for the regional mixed UDP/TCP protection cohort" `
        -DryRun:$Options.DryRun

    if (-not $Options.DryRun) {
        foreach ($requiredPath in @($preset.ComparisonRunsPath, $preset.ComparisonSummaryPath, $preset.ComparisonReportPath)) {
            if (-not (Test-Path $requiredPath)) {
                throw "regional-mixed-traffic-protection-batch comparison step did not create the expected file: $requiredPath"
            }
        }

        $comparisonArtifacts = @(
            (Get-ArtifactMetadata -Path $preset.ComparisonRunsPath -Category "Cohort comparison runs (.csv)" -SourceStep $comparisonStepName),
            (Get-ArtifactMetadata -Path $preset.ComparisonSummaryPath -Category "Cohort comparison summary (.csv)" -SourceStep $comparisonStepName),
            (Get-ArtifactMetadata -Path $preset.ComparisonReportPath -Category "Cohort comparison report (.txt)" -SourceStep $comparisonStepName)
        )
        Publish-StepArtifacts `
            -Context $Context `
            -LogPath $comparisonCommandResult.LogPath `
            -Heading "Created or updated mixed UDP/TCP cohort comparison artifacts" `
            -Artifacts $comparisonArtifacts
    }

    $comparisonDetails = if ($Options.DryRun) { "Dry run only; focused regional mixed UDP/TCP comparison not executed." } else { "Focused regional mixed UDP/TCP protection cohort comparison completed." }
    Add-StepResult -Context $Context -Step $comparisonStepName -Status "OK" -Details $comparisonDetails

    if ($runtimeExportPerformed) {
        Request-OutputFolderOpen `
            -Context $Context `
            -Options $Options `
            -FolderPath $preset.ScenarioDir `
            -Reason "regionalbackbone runtime export artifacts"
    }

    Request-OutputFolderOpen `
        -Context $Context `
        -Options $Options `
        -FolderPath $outcomesDir `
        -Reason "regional mixed UDP/TCP protection cohort analysis artifacts"

    return $true
}

function Require-CleanConfirmation {
    param(
        $Options
    )

    if ($Options.Clean -and -not $Options.Yes -and -not $Options.DryRun) {
        throw "--clean requires --yes for actual deletion. Use --dry-run to preview the cleanup safely."
    }
}

function Validate-CommandOptions {
    param(
        [string]$BatchCommand,
        $Options
    )

    switch ($BatchCommand) {
        "dataset-batch" {
            if ($Options.IncludeAimrce) {
                throw "--include-aimrce is only supported by full-pipeline."
            }
        }
        "training-batch" {
            if ($Options.Configs.Count -gt 0) {
                throw "--configs is not supported by training-batch."
            }
            if ($Options.Clean) {
                throw "--clean is not supported by training-batch because it does not run simulations."
            }
            if ($Options.SkipAnalysis) {
                throw "--skip-analysis is not supported by training-batch."
            }
            if ($Options.IncludeAimrce) {
                throw "--include-aimrce is only supported by full-pipeline."
            }
        }
        "aimrce-batch" {
            if ($Options.Scenarios.Count -gt 0) {
                if ($Options.Scenarios.Count -ne 1 -or $Options.Scenarios[0] -ne "regionalbackbone") {
                    throw "aimrce-batch only supports the regionalbackbone scenario."
                }
            }
            if ($Options.SkipAnalysis) {
                throw "--skip-analysis is not supported by aimrce-batch."
            }
            if ($Options.SkipTraining) {
                throw "--skip-training is only supported by full-pipeline."
            }
            if ($Options.RebuildMissingDatasets) {
                throw "--rebuild-missing-datasets is only supported by training-batch."
            }
            if ($Options.StrongerEvaluationsOnly) {
                throw "--stronger-evaluations-only is only supported by training-batch or full-pipeline."
            }
            if ($Options.IncludeAimrce) {
                throw "--include-aimrce is only supported by full-pipeline."
            }
        }
        "regional-congestion-protection-batch" {
            if ($Options.Scenarios.Count -gt 0) {
                throw "--scenario is not supported by regional-congestion-protection-batch because it is pinned to the dedicated regional backbone congestion protection cohort."
            }
            if ($Options.Configs.Count -gt 0) {
                throw "--configs is not supported by regional-congestion-protection-batch because it always runs the full comparison cohort."
            }
            if ($Options.SkipAnalysis) {
                throw "--skip-analysis is not supported by regional-congestion-protection-batch because dataset, outcome, and comparison artifacts are the purpose of the command."
            }
            if ($Options.SkipTraining) {
                throw "--skip-training is only supported by full-pipeline."
            }
            if ($Options.RebuildMissingDatasets) {
                throw "--rebuild-missing-datasets is only supported by training-batch."
            }
            if ($Options.StrongerEvaluationsOnly) {
                throw "--stronger-evaluations-only is only supported by training-batch or full-pipeline."
            }
            if ($Options.IncludeAimrce) {
                throw "--include-aimrce is only supported by full-pipeline."
            }
        }
        "regional-mixed-traffic-protection-batch" {
            if ($Options.Scenarios.Count -gt 0) {
                throw "--scenario is not supported by regional-mixed-traffic-protection-batch because it is pinned to the dedicated regional backbone mixed UDP/TCP protection cohort."
            }
            if ($Options.Configs.Count -gt 0) {
                throw "--configs is not supported by regional-mixed-traffic-protection-batch because it always runs the full mixed UDP/TCP comparison cohort."
            }
            if ($Options.SkipAnalysis) {
                throw "--skip-analysis is not supported by regional-mixed-traffic-protection-batch because dataset, outcome, and comparison artifacts are the purpose of the command."
            }
            if ($Options.SkipTraining) {
                throw "--skip-training is only supported by full-pipeline."
            }
            if ($Options.RebuildMissingDatasets) {
                throw "--rebuild-missing-datasets is only supported by training-batch."
            }
            if ($Options.StrongerEvaluationsOnly) {
                throw "--stronger-evaluations-only is only supported by training-batch or full-pipeline."
            }
            if ($Options.IncludeAimrce) {
                throw "--include-aimrce is only supported by full-pipeline."
            }
        }
        "full-pipeline" {
            if ($Options.Configs.Count -gt 0) {
                throw "--configs is not supported by full-pipeline. Use dataset-batch or aimrce-batch for manual config subsets."
            }
        }
        default {
            throw "Unsupported command '$BatchCommand'. Run 'run_experiments.bat help' to see supported commands."
        }
    }
}

$scriptExitCode = 0

Push-Location $projectRoot
try {
    $options = Parse-CommandArguments -Arguments $CommandArgs
    if ($Command -eq "help" -or $options.Help) {
        Show-Usage
    }
    else {
        Require-CleanConfirmation -Options $options
        Validate-CommandOptions -BatchCommand $Command -Options $options

        switch ($Command) {
            "dataset-batch" {
                $scenarioName = Resolve-SingleDatasetScenario -RequestedScenarios $options.Scenarios
                $preset = $script:ScenarioPresets[$scenarioName]
                $configNames = Resolve-ConfigSelection -AllowedConfigs $preset.EvalConfigs -RequestedConfigs $options.Configs
                $context = New-BatchContext -BatchCommand $Command -ScenarioNames @($scenarioName)
                $overallStatus = "OK"

                try {
                    if (-not $options.SkipBuild) {
                        Build-Project -Context $context -DryRun:$options.DryRun
                    }
                    else {
                        Add-StepResult -Context $context -Step "build" -Status "OK" -Details "Skipped build by request."
                    }

                    $batchSucceeded = Invoke-DatasetBatchCore -Context $context -Preset $preset -ConfigNames $configNames -RunNumbers $options.Runs -Options $options
                    if (-not $batchSucceeded) {
                        $overallStatus = "FAILED"
                        $scriptExitCode = 1
                    }
                }
                catch {
                    $overallStatus = "FAILED"
                    $scriptExitCode = 1
                    Add-StepResult -Context $context -Step $Command -Status "FAILED" -Details $_.Exception.Message
                    Write-Error $_.Exception.Message
                }
                finally {
                    Write-BatchSummary -Context $context -OverallStatus $overallStatus
                }
            }

            "training-batch" {
                $scenarioNames = Resolve-DatasetScenarios -RequestedScenarios $options.Scenarios
                $context = New-BatchContext -BatchCommand $Command -ScenarioNames $scenarioNames
                $overallStatus = "OK"

                try {
                    Invoke-TrainingBatchCore -Context $context -ScenarioNames $scenarioNames -Options $options
                }
                catch {
                    $overallStatus = "FAILED"
                    $scriptExitCode = 1
                    Add-StepResult -Context $context -Step $Command -Status "FAILED" -Details $_.Exception.Message
                    Write-Error $_.Exception.Message
                }
                finally {
                    Write-BatchSummary -Context $context -OverallStatus $overallStatus
                }
            }

            "aimrce-batch" {
                $context = New-BatchContext -BatchCommand $Command -ScenarioNames @("regionalbackbone")
                $overallStatus = "OK"

                try {
                    if (-not $options.SkipBuild) {
                        Build-Project -Context $context -DryRun:$options.DryRun
                    }
                    else {
                        Add-StepResult -Context $context -Step "build" -Status "OK" -Details "Skipped build by request."
                    }

                    $batchSucceeded = Invoke-AiMrceBatchCore -Context $context -Options $options
                    if (-not $batchSucceeded) {
                        $overallStatus = "FAILED"
                        $scriptExitCode = 1
                    }
                }
                catch {
                    $overallStatus = "FAILED"
                    $scriptExitCode = 1
                    Add-StepResult -Context $context -Step $Command -Status "FAILED" -Details $_.Exception.Message
                    Write-Error $_.Exception.Message
                }
                finally {
                    Write-BatchSummary -Context $context -OverallStatus $overallStatus
                }
            }

            "regional-congestion-protection-batch" {
                $context = New-BatchContext -BatchCommand $Command -ScenarioNames @("regionalbackbone_congestion_protection")
                $overallStatus = "OK"

                try {
                    if (-not $options.SkipBuild) {
                        Build-Project -Context $context -DryRun:$options.DryRun
                    }
                    else {
                        Add-StepResult -Context $context -Step "build" -Status "OK" -Details "Skipped build by request."
                    }

                    $batchSucceeded = Invoke-RegionalCongestionProtectionBatchCore -Context $context -Options $options
                    if (-not $batchSucceeded) {
                        $overallStatus = "FAILED"
                        $scriptExitCode = 1
                    }
                }
                catch {
                    $overallStatus = "FAILED"
                    $scriptExitCode = 1
                    Add-StepResult -Context $context -Step $Command -Status "FAILED" -Details $_.Exception.Message
                    Write-Error $_.Exception.Message
                }
                finally {
                    Write-BatchSummary -Context $context -OverallStatus $overallStatus
                }
            }

            "regional-mixed-traffic-protection-batch" {
                $context = New-BatchContext -BatchCommand $Command -ScenarioNames @("regionalbackbone_mixed_traffic_protection")
                $overallStatus = "OK"

                try {
                    if (-not $options.SkipBuild) {
                        Build-Project -Context $context -DryRun:$options.DryRun
                    }
                    else {
                        Add-StepResult -Context $context -Step "build" -Status "OK" -Details "Skipped build by request."
                    }

                    $batchSucceeded = Invoke-RegionalMixedTrafficProtectionBatchCore -Context $context -Options $options
                    if (-not $batchSucceeded) {
                        $overallStatus = "FAILED"
                        $scriptExitCode = 1
                    }
                }
                catch {
                    $overallStatus = "FAILED"
                    $scriptExitCode = 1
                    Add-StepResult -Context $context -Step $Command -Status "FAILED" -Details $_.Exception.Message
                    Write-Error $_.Exception.Message
                }
                finally {
                    Write-BatchSummary -Context $context -OverallStatus $overallStatus
                }
            }

            "full-pipeline" {
                $scenarioNames = Resolve-DatasetScenarios -RequestedScenarios $options.Scenarios
                $context = New-BatchContext -BatchCommand $Command -ScenarioNames $scenarioNames
                $overallStatus = "OK"
                $pipelineHealthy = $true

                try {
                    if (-not $options.SkipBuild) {
                        Build-Project -Context $context -DryRun:$options.DryRun
                    }
                    else {
                        Add-StepResult -Context $context -Step "build" -Status "OK" -Details "Skipped build by request."
                    }

                    foreach ($scenarioName in $scenarioNames) {
                        $preset = $script:ScenarioPresets[$scenarioName]
                        $datasetSucceeded = Invoke-DatasetBatchCore -Context $context -Preset $preset -ConfigNames $preset.EvalConfigs -RunNumbers $options.Runs -Options $options
                        if (-not $datasetSucceeded) {
                            $pipelineHealthy = $false
                            if (-not $options.ContinueOnError) {
                                throw "Stopping full-pipeline because dataset-batch for '$scenarioName' failed."
                            }
                        }
                    }

                    if (-not $options.SkipTraining) {
                        if ($pipelineHealthy) {
                            Invoke-TrainingBatchCore -Context $context -ScenarioNames $scenarioNames -Options $options
                        }
                        else {
                            Add-StepResult -Context $context -Step "train-risk-model" -Status "SKIPPED" -Details "Skipped training because an earlier dataset batch failed."
                        }
                    }
                    else {
                        Add-StepResult -Context $context -Step "train-risk-model" -Status "OK" -Details "Skipped training by request."
                    }

                    if ($options.IncludeAimrce) {
                        if ($pipelineHealthy) {
                            $aimrceSucceeded = Invoke-AiMrceBatchCore -Context $context -Options $options
                            if (-not $aimrceSucceeded) {
                                $pipelineHealthy = $false
                                if (-not $options.ContinueOnError) {
                                    throw "Stopping full-pipeline because the AI-MRCE runtime batch failed."
                                }
                            }
                        }
                        else {
                            Add-StepResult -Context $context -Step "aimrce-batch" -Status "SKIPPED" -Details "Skipped AI-MRCE runtime batch because an earlier step failed."
                        }
                    }
                    else {
                        Add-StepResult -Context $context -Step "aimrce-batch" -Status "OK" -Details "Skipped AI-MRCE runtime configs by default."
                    }

                    if (-not $pipelineHealthy) {
                        $overallStatus = "FAILED"
                        $scriptExitCode = 1
                    }
                    else {
                        Open-PendingOutputFolders -Context $context -Options $options
                    }
                }
                catch {
                    $overallStatus = "FAILED"
                    $scriptExitCode = 1
                    Add-StepResult -Context $context -Step $Command -Status "FAILED" -Details $_.Exception.Message
                    Write-Error $_.Exception.Message
                }
                finally {
                    Write-BatchSummary -Context $context -OverallStatus $overallStatus
                }
            }

            default {
                throw "Unsupported command '$Command'. Run 'run_experiments.bat help' to see supported commands."
            }
        }
    }
}
catch {
    Write-Error $_.Exception.Message
    $scriptExitCode = 1
}
finally {
    Pop-Location
}

exit $scriptExitCode
