$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskBase = 'http://127.0.0.1:29183'
$taskHealth = Invoke-RestMethod "$taskBase/health" -TimeoutSec 5
$taskLogin = Invoke-RestMethod "$taskBase/api/local/login" -Method Post -TimeoutSec 15
$taskHeaders = @{ token = $taskLogin.token }
if (!$taskLogin.token) { throw '未获得演示登录 token' }
$taskSession = $null
$taskResults = foreach ($taskText in @('三体讲什么？','我上次听到哪里了？','我的会员什么时候到期？')) {
    $taskBody = @{text=$taskText;session_id=$taskSession} | ConvertTo-Json
    $taskResponse = Invoke-RestMethod "$taskBase/api/assistant/chat" -Method Post -Headers $taskHeaders -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($taskBody)) -TimeoutSec 120
    $taskSession = $taskResponse.session_id
    if (!$taskResponse.text) { throw "没有返回答案：$taskText" }
    [pscustomobject]@{query=$taskText;mode=$taskResponse.mode;tools=$taskResponse.trace.tool;answer=$taskResponse.text;sources=$taskResponse.sources}
}
$taskHistory = Invoke-RestMethod "$taskBase/api/history/$taskSession" -Headers $taskHeaders -TimeoutSec 5
if (!($taskResults[0].tools -contains 'search_knowledge') -or !$taskResults[0].sources.Count) { throw '书籍查询未检索资料或缺少来源' }
if (!($taskResults[1].tools -contains 'get_progress') -or $taskResults[1].answer -notmatch '2\s*分\s*5\s*秒') { throw '进度工具或演示进度错误' }
if (!($taskResults[2].tools -contains 'get_membership')) { throw '会员工具未执行' }
if ($taskHistory.messages.Count -ne 6) { throw '历史记录数量错误' }
$taskReport = @{ health=$taskHealth; scenarios=$taskResults; historyMessages=$taskHistory.messages.Count; checkedAt=(Get-Date -Format o) }
$taskReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $taskProjectRoot '.runtime\smoke.json') -Encoding utf8
Write-Output '知识查询、收听进度、会员和会话历史验证通过；报告保存到 .runtime/smoke.json。'
