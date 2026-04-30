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

function Get-AnalysisPython {
    $venvCandidates = @(
        (Join-Path $venvRoot "Scripts\\python.exe"),
        (Join-Path $venvRoot "bin\\python.exe")
    )

    foreach ($candidate in $venvCandidates) {
        if (Test-Path $candidate) {
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
  prepare-batch         Forward to analysis\prepare_batch.py.
  build-dataset         Forward to analysis\build_dataset.py.
  dataset-report        Forward to analysis\dataset_report.py.
  compare-outcomes      Forward to analysis\compare_outcomes.py.
  train-risk-model      Forward to analysis\train_risk_model.py.
  export-runtime-models Forward to analysis\export_runtime_models.py.
  export-runtime-logreg Forward to analysis\export_runtime_logreg.py.

Examples:
  run_analysis.bat python-info
  run_analysis.bat setup-env
  run_analysis.bat install-ml-deps
  run_analysis.bat build-dataset --scenario regionalbackbone
  run_analysis.bat dataset-report --scenario regionalbackbone
  run_analysis.bat build-dataset --scenario regionalbackbone_congestion_protection
  run_analysis.bat dataset-report --scenario regionalbackbone_congestion_protection
  run_analysis.bat build-dataset --scenario regionalbackbone_mixed_traffic_protection
  run_analysis.bat dataset-report --scenario regionalbackbone_mixed_traffic_protection
  run_analysis.bat compare-outcomes --scenarios regionalbackbone_mixed_traffic_protection --output-prefix analysis\output\outcomes\regionalbackbone_mixed_traffic_protection_multirun_comparison
  run_analysis.bat compare-outcomes --allow-missing
  run_analysis.bat train-risk-model
  run_analysis.bat export-runtime-models --configs RegionalBackboneCongestionDegradation
  run_analysis.bat export-runtime-logreg --configs RegionalBackboneCongestionDegradation
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
        "prepare-batch" {
            Invoke-AnalysisScript -ScriptName "prepare_batch.py" -ScriptArgs $CommandArgs
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
        "train-risk-model" {
            Invoke-AnalysisScript -ScriptName "train_risk_model.py" -ScriptArgs $CommandArgs
        }
        "export-runtime-models" {
            Invoke-AnalysisScript -ScriptName "export_runtime_models.py" -ScriptArgs $CommandArgs
        }
        "export-runtime-logreg" {
            Invoke-AnalysisScript -ScriptName "export_runtime_logreg.py" -ScriptArgs $CommandArgs
        }
        default {
            throw "Unsupported command '$Command'. Run 'run_analysis.bat help' to see the supported commands."
        }
    }
}
finally {
    Pop-Location
}
