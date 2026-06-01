[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs = @()
)

$ErrorActionPreference = "Stop"

$analysisDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $analysisDir "..")
$requirementsPath = Join-Path $analysisDir "requirements.txt"
$venvRoot = Join-Path $analysisDir "sklearn-env"

function Test-PythonExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    try {
        & $Path --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Get-AnalysisPython {
    $venvCandidates = @(
        (Join-Path $venvRoot "Scripts\\python.exe"),
        (Join-Path $venvRoot "bin\\python.exe")
    )

    foreach ($candidate in $venvCandidates) {
        if (Test-Path $candidate) {
            if (-not (Test-PythonExecutable -Path $candidate)) {
                Write-Warning "Ignoring analysis virtualenv Python because it could not be started: $candidate"
                continue
            }
            return @{
                Type = "executable"
                Command = (Resolve-Path $candidate).Path
                Display = (Resolve-Path $candidate).Path
            }
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        return @{
            Type = "launcher"
            Command = "py"
            PrefixArgs = @("-3")
            Display = "py -3"
        }
    }

    throw "No Python interpreter was found. Create analysis\sklearn-env or install the Python launcher."
}

function Invoke-AnalysisPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $python = Get-AnalysisPython
    if ($python.Type -eq "executable") {
        & $python.Command @Arguments
    }
    else {
        $fullArguments = @($python.PrefixArgs) + $Arguments
        & $python.Command @fullArguments
    }

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Ensure-AnalysisVenv {
    if ((Test-Path (Join-Path $venvRoot "Scripts\\python.exe")) -or (Test-Path (Join-Path $venvRoot "bin\\python.exe"))) {
        return
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $pyLauncher) {
        throw "Cannot create analysis\sklearn-env because the Python launcher 'py' is not available."
    }

    Write-Host "Creating analysis environment at $venvRoot"
    & py -3 -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Invoke-AnalysisScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptName,

        [Parameter()]
        [string[]]$ScriptArgs = @()
    )

    $scriptPath = Join-Path $analysisDir $ScriptName
    if (-not (Test-Path $scriptPath)) {
        throw "Analysis script not found: $scriptPath"
    }

    Invoke-AnalysisPython -Arguments (@($scriptPath) + $ScriptArgs)
}

function Install-AnalysisRequirements {
    Ensure-AnalysisVenv
    Invoke-AnalysisPython -Arguments @("-m", "pip", "install", "-r", $requirementsPath)
}

function Show-Usage {
    @"
Usage:
  run_analysis.bat <command> [arguments...]
  powershell -ExecutionPolicy Bypass -File analysis\run_analysis.ps1 <command> [arguments...]

Commands:
  help                  Show this help text.
  python-info           Show the Python interpreter that will be used.
  setup-env             Create analysis\sklearn-env if it does not already exist.
  install-ml-deps       Install analysis\requirements.txt into analysis\sklearn-env.
  build-dataset         Forward to analysis\build_dataset.py.
  dataset-report        Forward to analysis\dataset_report.py.
  compare-outcomes      Forward to analysis\compare_outcomes.py.
  model-risk-trace      Forward to analysis\extract_aimrce_risk_trace.py.
  network-impact        Generate UDP/QoS network-impact diagnostics from existing outputs.
  offline-ml-audit      Run offline telemetry-v2 ML feature-quality and feasibility audit.
  activation-root-cause Explain AI-MRCE activation timing from existing traces and artifacts.
  evaluate-results      Build the unified final evaluation report, compact tables, and figures.
  pipeline-integrity    Forward to analysis\pipeline_integrity.py.
  package-current-experiment
                        Create a compact sendable package for the active current experiment.
  clean-final-evaluation
                        Dry-run-first cleanup of generated final-evaluation figure files.
  clean-generated       Forward to analysis\clean_generated.py.
  export-runtime-models Forward to analysis\export_runtime_models.py.

Examples:
  run_analysis.bat python-info
  run_analysis.bat setup-env
  run_analysis.bat install-ml-deps
  run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degraded_link_model_family
  run_analysis.bat build-dataset --scenario regionalbackbone_failure_detection_degraded_link_model_family --feature-set extended
  run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degraded_link_model_family
  run_analysis.bat dataset-report --scenario regionalbackbone_failure_detection_degraded_link_model_family --feature-set extended
  run_analysis.bat compare-outcomes --scenarios regionalbackbone_failure_detection_degraded_link_model_family --output-prefix analysis\output\outcomes\regionalbackbone_failure_detection_degraded_link_model_family
  run_analysis.bat model-risk-trace --scenario regionalbackbone_failure_detection_degraded_link_model_family --runs 0 --start 78 --end 86
  run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_degraded_link_model_family
  run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_backup
  run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
  run_analysis.bat network-impact --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
  run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_degraded_link_model_family
  run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_degradation_sensitivity
  run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_cost_aware_backup
  run_analysis.bat offline-ml-audit --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
  run_analysis.bat activation-root-cause
  run_analysis.bat activation-root-cause --scenario regionalbackbone_failure_detection_cost_aware_backup
  run_analysis.bat evaluate-results
  run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degraded_link_model_family
  run_analysis.bat pipeline-integrity --scenario regionalbackbone_failure_detection_degradation_sensitivity
  run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_degraded_link_model_family
  run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_degradation_sensitivity
  run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_cost_aware_backup
  run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_cost_aware_transport_impact
  run_analysis.bat package-current-experiment --scenario regionalbackbone_failure_detection_cost_aware_transport_impact_instrumented
  run_analysis.bat clean-final-evaluation --dry-run
  run_analysis.bat clean-final-evaluation --yes
  run_analysis.bat clean-generated
  run_analysis.bat clean-generated --include-results --scenario regionalbackbone_failure_detection_degraded_link_model_family
  run_analysis.bat export-runtime-models --configs RegionalBackboneCongestionDegradation

Reliability notes:
  - pipeline-integrity reports OK for complete five-run publication outputs and OK_WITH_WARNINGS for expected run-0 development outputs.
  - clean-generated is dry-run by default; use --clean --yes only when you intentionally want to remove generated artifacts.
  - build-dataset prints per-file progress because regional .vec files can be hundreds of MB each.
"@ | Write-Host
}

Push-Location $projectRoot
try {
    switch ($Command) {
        "help" {
            Show-Usage
        }
        "python-info" {
            $python = Get-AnalysisPython
            Write-Host "Project root: $projectRoot"
            Write-Host "Analysis environment: $venvRoot"
            Write-Host "Python command: $($python.Display)"
        }
        "setup-env" {
            Ensure-AnalysisVenv
            $python = Get-AnalysisPython
            Write-Host "Analysis environment ready."
            Write-Host "Python command: $($python.Display)"
        }
        "install-ml-deps" {
            Install-AnalysisRequirements
        }
        "build-dataset" {
            Invoke-AnalysisScript -ScriptName "build_dataset.py" -ScriptArgs $CommandArgs
        }
        "dataset-report" {
            Invoke-AnalysisScript -ScriptName "dataset_report.py" -ScriptArgs $CommandArgs
        }
        "compare-outcomes" {
            Invoke-AnalysisScript -ScriptName "compare_outcomes.py" -ScriptArgs $CommandArgs
        }
        "model-risk-trace" {
            Invoke-AnalysisScript -ScriptName "extract_aimrce_risk_trace.py" -ScriptArgs $CommandArgs
        }
        "network-impact" {
            Invoke-AnalysisScript -ScriptName "network_impact_report.py" -ScriptArgs $CommandArgs
        }
        "offline-ml-audit" {
            Invoke-AnalysisScript -ScriptName "offline_ml_audit.py" -ScriptArgs $CommandArgs
        }
        "activation-root-cause" {
            Invoke-AnalysisScript -ScriptName "activation_root_cause.py" -ScriptArgs $CommandArgs
        }
        "evaluate-results" {
            Invoke-AnalysisScript -ScriptName "evaluate_results.py" -ScriptArgs $CommandArgs
        }
        "pipeline-integrity" {
            Invoke-AnalysisScript -ScriptName "pipeline_integrity.py" -ScriptArgs $CommandArgs
        }
        "package-current-experiment" {
            Invoke-AnalysisScript -ScriptName "package_current_experiment.py" -ScriptArgs $CommandArgs
        }
        "clean-final-evaluation" {
            $cleanupArgs = @("--scope", "final-evaluation")
            if ($CommandArgs -contains "--yes" -and -not ($CommandArgs -contains "--clean")) {
                $cleanupArgs += "--clean"
            }
            $cleanupArgs += $CommandArgs
            Invoke-AnalysisScript -ScriptName "clean_generated.py" -ScriptArgs $cleanupArgs
        }
        "clean-generated" {
            Invoke-AnalysisScript -ScriptName "clean_generated.py" -ScriptArgs $CommandArgs
        }
        "export-runtime-models" {
            Invoke-AnalysisScript -ScriptName "export_runtime_models.py" -ScriptArgs $CommandArgs
        }
        default {
            throw "Unsupported command '$Command'. Run 'run_analysis.bat help' to see the supported commands."
        }
    }
}
finally {
    Pop-Location
}
