$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskPidFile = Join-Path $taskProjectRoot '.runtime\processes.json'
if (Test-Path -LiteralPath $taskPidFile) {
    $taskPids = Get-Content -LiteralPath $taskPidFile -Raw | ConvertFrom-Json
    foreach ($taskProperty in $taskPids.PSObject.Properties) {
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskProperty.Value)"
        # PID 可能被系统复用，只停止本任务明确匹配的命令。
        if ($taskProcess -and $taskProcess.CommandLine -match [regex]::Escape($taskProjectRoot) -and ($taskProcess.CommandLine -match 'tingshu-parent.*service-(user|order|album)\.jar|atguigu\.listening\.app:app|app\.listening\.service:app|uvicorn listening\.service:app|listening_jobs\.worker')) {
            $taskChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($taskProperty.Value)"
            foreach ($taskChild in $taskChildren) {
                if ($taskChild.CommandLine -match 'atguigu\.listening\.app:app|app\.listening\.service:app|uvicorn listening\.service:app|listening_jobs\.worker') {
                    Stop-Process -Id $taskChild.ProcessId -ErrorAction SilentlyContinue
                }
            }
            Stop-Process -Id $taskProperty.Value -ErrorAction SilentlyContinue
        }
    }
}
$taskEnvironmentFile = Join-Path $taskProjectRoot '.runtime\environment.json'
$taskVmMode = $false
if (Test-Path -LiteralPath $taskEnvironmentFile) {
    $taskVmMode = (Get-Content -LiteralPath $taskEnvironmentFile -Raw | ConvertFrom-Json).infrastructure -eq 'vm'
}
if (!$taskVmMode) {
    Push-Location $taskProjectRoot
    try { docker compose stop } finally { Pop-Location }
}
Write-Output '已停止本项目服务，数据库卷保留。'
