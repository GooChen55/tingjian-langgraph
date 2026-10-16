param([switch]$Live,[string]$JavaHome='D:\develop\JAVA\jdk\ms-17.0.18')
$ErrorActionPreference='Stop'
$taskProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Push-Location $taskProjectRoot
try {
 $taskPython=Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
 $env:PYTHONUTF8='1';$env:JAVA_HOME=$JavaHome;$env:PATH="$JavaHome\bin;$env:PATH"
 $env:MAVEN_OPTS='-Xmx256m -XX:ActiveProcessorCount=2'
 $env:PYTHONPATH="$PWD\python\shared;$PWD\python\assistant;$PWD\python\knowledge;$PWD\python\operations;$PWD\python\workers"
 & $taskPython -m pytest tests -q
 if($LASTEXITCODE -ne 0){throw 'Python tests failed'}
 mvn -B -ntp -f 'backend\java\tingshu-parent\pom.xml' -pl 'service/service-user,service/service-order,service/service-album' -am '-DskipTests=false' '-Dtest=AssistantOrderServiceTest,AssistantUserApiControllerTest,AccessServiceTest,LocalPaymentServiceTest,NamespacedKeySerializerTest,ProgressCollectionTest,ContentErrorsTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-DargLine=-Xmx192m -XX:ActiveProcessorCount=2 -XX:TieredStopAtLevel=1' test
 if($LASTEXITCODE -ne 0){throw 'Java tests failed'}
 . '.\scripts\dev\VmEnvironment.ps1'
 $taskEnvironmentFile=Join-Path $taskProjectRoot '.runtime\environment.json'
 if((Test-Path -LiteralPath $taskEnvironmentFile) -and ((Get-Content $taskEnvironmentFile -Raw | ConvertFrom-Json).infrastructure -eq 'vm')) {Set-TaskVmEnvironment $taskProjectRoot}
 & '.\scripts\dev\Doctor.ps1' -JavaHome $JavaHome
 if($Live){
  foreach($taskScript in @('VerifyModelCompatibility.py','EvaluateKnowledge.py','EvaluateAgent.py','VerifyPayments.py')) {
   & $taskPython (Join-Path 'scripts\verify' $taskScript)
   if($LASTEXITCODE -ne 0){throw "$taskScript failed"}
  }
  $taskRecords=Get-Content '.runtime\processes.json' -Raw | ConvertFrom-Json
  $taskOrderProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskRecords.order)"
  if(!$taskOrderProcess -or $taskOrderProcess.CommandLine -notmatch 'tingshu-parent.*service-order.jar'){throw 'Order process identity mismatch'}
  Stop-Process -Id $taskOrderProcess.ProcessId
  & '.\Start.ps1' -SkipBuild -UseLlm -WithKnowledge -WithOperations -JavaHome $JavaHome
  & $taskPython '.\scripts\verify\VerifyPayments.py' --verify-restart
  if($LASTEXITCODE -ne 0){throw 'Restart acceptance failed'}
 }
} finally {Pop-Location}
