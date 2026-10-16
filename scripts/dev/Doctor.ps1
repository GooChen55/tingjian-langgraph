param([string]$JavaHome='D:\develop\JAVA\jdk\ms-17.0.18')
$ErrorActionPreference='Stop'
$taskProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskChecks=@()
foreach($taskName in @('docker','mvn','node')) {
 $taskFound=Get-Command $taskName -ErrorAction SilentlyContinue
 if (!$taskFound -and $taskName -eq 'node') {$taskFound=Test-Path 'D:\develop\node\node.exe'}
 $taskChecks+= [pscustomobject]@{Check=$taskName;Ready=[bool]$taskFound}
}
$taskChecks+=[pscustomobject]@{Check='JDK 17';Ready=(Test-Path (Join-Path $JavaHome 'bin\java.exe'))}
$taskChecks+=[pscustomobject]@{Check='Python venv';Ready=(Test-Path (Join-Path $taskProjectRoot '.venv\Scripts\python.exe'))}
$taskChecks+=[pscustomobject]@{Check='UniApp source';Ready=(Test-Path (Join-Path $taskProjectRoot 'frontend\uniapp\package.json'))}
$taskChecks | Format-Table -AutoSize
$taskSavedEnvironment=Join-Path $taskProjectRoot '.runtime\environment.json'
$taskVmMode=(Test-Path -LiteralPath $taskSavedEnvironment) -and ((Get-Content -LiteralPath $taskSavedEnvironment -Raw | ConvertFrom-Json).infrastructure -eq 'vm')
if($taskVmMode){
 & (Join-Path $taskProjectRoot '.venv\Scripts\python.exe') (Join-Path $taskProjectRoot 'scripts\verify\VerifyVmInfrastructure.py')
 if($LASTEXITCODE -ne 0){throw 'VM infrastructure check failed'}
}else{
 try {docker info --format '{{.ServerVersion}}' | Out-Null;if($LASTEXITCODE -ne 0){throw 'Docker 未就绪'};Write-Output 'Docker daemon ready'}catch{Write-Output 'Docker daemon not ready'}
}
foreach($taskPort in @(29183,29184,29185)) {
 try {$taskHealth=Invoke-RestMethod "http://127.0.0.1:$taskPort/health" -TimeoutSec 3;Write-Output "Service $taskPort ready"}catch{Write-Output "Service $taskPort not started"}
}
Write-Output 'This check does not print passwords, API Keys or private configuration.'
