param(
    [string]$JavaHome = 'D:\develop\JAVA\jdk\ms-17.0.18',
    [string]$PythonExe = 'python',
    [ValidateSet('auto','local','vm')][string]$Infrastructure = 'auto',
    [switch]$SkipBuild,
    [switch]$UseLlm,
    [switch]$WithKnowledge,
    [switch]$WithOperations
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'scripts\dev\Start.ps1') @PSBoundParameters
