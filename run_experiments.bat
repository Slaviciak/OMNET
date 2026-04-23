@echo off
rem Thin project-local wrapper for the PowerShell experiment orchestrator.
rem This entrypoint standardizes how reproducible batch runs are launched on
rem the Windows workflow without changing simulation or analysis semantics.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0analysis\run_experiments.ps1" %*
exit /b %ERRORLEVEL%
