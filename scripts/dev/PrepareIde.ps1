# Prepare ignored, local IDE configuration. Does not start or stop any service.
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. (Join-Path $PSScriptRoot 'VmEnvironment.ps1')
Set-TaskVmEnvironment $taskProjectRoot
$env:LISTENING_DEMO_LOGIN = 'true'
$env:LISTENING_USE_LLM = 'true'
$env:LISTENING_USER_URL = 'http://127.0.0.1:19201'
$env:LISTENING_ORDER_URL = 'http://127.0.0.1:19204'
$env:LISTENING_CONTENT_URL = 'http://127.0.0.1:19202'
$env:LISTENING_KNOWLEDGE_URL = 'http://127.0.0.1:29184'
$env:LISTENING_OPERATIONS_URL = 'http://127.0.0.1:29185'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$taskPythonPaths = @('shared','assistant','knowledge','operations','workers') | ForEach-Object { Join-Path $taskProjectRoot "python\$_" }
$env:PYTHONPATH = $taskPythonPaths -join [IO.Path]::PathSeparator
$taskVariables = @(
    'LISTENING_INFRASTRUCTURE','LISTENING_DB_HOST','LISTENING_DB_PORT',
    'LISTENING_APP_DB_PASSWORD','LISTENING_READER_USER','LISTENING_READER_PASSWORD',
    'LISTENING_OPS_DATABASE','LISTENING_REDIS_PASSWORD','LISTENING_RABBIT_PASSWORD',
    'LISTENING_MONGO_URI','LISTENING_ES_URL','LISTENING_ES_ENABLED',
    'LISTENING_VECTOR_BACKEND','LISTENING_QDRANT_ENABLED','LISTENING_KG_ENABLED',
    'LISTENING_ADVANCED_RAG','LISTENING_SERVICE_KEY','LISTENING_PAYMENT_CALLBACK_SECRET',
    'LISTENING_HISTORY_DB','LISTENING_INDEX_DB','LISTENING_MODEL_SETTINGS_FILE',
    'LISTENING_DEMO_LOGIN','LISTENING_USE_LLM','LISTENING_USER_URL','LISTENING_ORDER_URL',
    'LISTENING_CONTENT_URL','LISTENING_KNOWLEDGE_URL','LISTENING_OPERATIONS_URL',
    'PYTHONUTF8','PYTHONUNBUFFERED','PYTHONPATH'
)
$taskOutput = Join-Path $taskProjectRoot '.runtime\ide'
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskLines = foreach ($taskName in $taskVariables) {
    $taskValue = [Environment]::GetEnvironmentVariable($taskName,'Process')
    if ([string]::IsNullOrEmpty($taskValue) -or $taskValue -match '[\r\n]') {throw "IDE environment value is missing or invalid: $taskName"}
    # Normalize paths only; never modify credential characters.
    if ($taskName -in @('PYTHONPATH','LISTENING_HISTORY_DB','LISTENING_INDEX_DB','LISTENING_MODEL_SETTINGS_FILE')) {
        $taskValue = $taskValue.Replace('\','/')
    }
    $taskEscaped = $taskValue.Replace('\','\\').Replace('"','\"')
    $taskName + '="' + $taskEscaped + '"'
}
[IO.File]::WriteAllLines((Join-Path $taskOutput 'application.env'),[string[]]$taskLines,[Text.UTF8Encoding]::new($false))
foreach ($taskModule in @('user','album','order')) {
    $taskFlags = @(Get-TaskJavaFlags 'vm' $taskModule) -join ' '
    [IO.File]::WriteAllText((Join-Path $taskOutput "java-$taskModule.args"),$taskFlags,[Text.UTF8Encoding]::new($false))
}
[IO.File]::WriteAllText((Join-Path $taskOutput 'java.vmoptions'),'-Xms32m -Xmx192m -Xss512k -XX:ActiveProcessorCount=2 -XX:MaxMetaspaceSize=160m -XX:TieredStopAtLevel=1 -XX:ReservedCodeCacheSize=48m -Dfile.encoding=UTF-8',[Text.UTF8Encoding]::new($false))
& (Join-Path $taskProjectRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'ConfigureIde.py')
if ($LASTEXITCODE -ne 0) { throw 'Failed to save local IDE run configurations.' }
Write-Output "IDE files prepared in $taskOutput"
Write-Output 'application.env contains private credentials: keep it local. Services were not restarted.'
