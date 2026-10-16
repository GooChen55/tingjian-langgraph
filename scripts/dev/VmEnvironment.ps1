# Dot-source only for this process; no machine-wide environment changes.
function Set-TaskVmEnvironment([string]$ProjectRoot) {
    $taskVmFile = Join-Path $ProjectRoot '.runtime\vm-app-private.json'
    if (!(Test-Path -LiteralPath $taskVmFile)) { throw '先运行 scripts/setup/ProvisionVm.py --apply 创建专属资源' }
    $taskVm = Get-Content -LiteralPath $taskVmFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($taskVm.owner -ne 'aillisten-dev/v1' -or $taskVm.host -ne '192.168.6.100') { throw '虚拟机资源归属不匹配' }
    if (!$taskVm.mongo_password) { throw '尚未初始化项目专属 MongoDB' }
    if (!$taskVm.service_key -or !$taskVm.payment_callback_secret) { throw '请重新运行 ProvisionVm.py --apply 生成虚拟机专属服务凭据' }
    $env:LISTENING_INFRASTRUCTURE = 'vm'
    $env:LISTENING_DB_HOST = $taskVm.host
    $env:LISTENING_DB_PORT = '3306'
    $env:LISTENING_APP_DB_PASSWORD = $taskVm.mysql_password
    $env:LISTENING_READER_USER = 'aillisten_dev_reader'
    $env:LISTENING_READER_PASSWORD = $taskVm.reader_password
    $env:LISTENING_OPS_DATABASE = 'aillisten_dev_ops'
    $env:LISTENING_REDIS_PASSWORD = $taskVm.redis_password
    $env:LISTENING_RABBIT_PASSWORD = $taskVm.rabbit_password
    $env:LISTENING_MONGO_URI = 'mongodb://aillisten_admin:' + [uri]::EscapeDataString($taskVm.mongo_password) + '@192.168.6.100:37017/aillisten_dev?authSource=admin'
    $env:LISTENING_ES_URL = 'http://192.168.6.100:9200'
    $env:LISTENING_ES_ENABLED = 'true'
    $env:LISTENING_VECTOR_BACKEND = 'milvus'
    $env:LISTENING_QDRANT_ENABLED = 'true'
    $env:LISTENING_KG_ENABLED = 'true'
    $env:LISTENING_ADVANCED_RAG = 'true'
    $env:LISTENING_SERVICE_KEY = $taskVm.service_key
    $env:LISTENING_PAYMENT_CALLBACK_SECRET = $taskVm.payment_callback_secret
    $taskVmRuntime = Join-Path $ProjectRoot '.runtime\vm'
    New-Item -ItemType Directory -Path $taskVmRuntime -Force | Out-Null
    $env:LISTENING_HISTORY_DB = Join-Path $taskVmRuntime 'history.sqlite'
    $env:LISTENING_INDEX_DB = Join-Path $taskVmRuntime 'knowledge.sqlite'
    $env:LISTENING_MODEL_SETTINGS_FILE = Join-Path $taskVmRuntime 'model-settings.json'
    foreach ($taskSharedFile in @('model-settings.json','knowledge.sqlite')) {
        $taskOldFile = Join-Path $ProjectRoot ".runtime\$taskSharedFile"
        $taskNewFile = Join-Path $taskVmRuntime $taskSharedFile
        if (!(Test-Path -LiteralPath $taskNewFile) -and (Test-Path -LiteralPath $taskOldFile)) {
            Copy-Item -LiteralPath $taskOldFile -Destination $taskNewFile
        }
    }
}

function Get-TaskJavaFlags([string]$Infrastructure, [string]$Module) {
    if ($Infrastructure -eq 'vm') {
        return @(
            '--spring.profiles.active=vm', '--spring.cloud.bootstrap.enabled=true',
            "--spring.application.name=aillisten-dev-$Module",
            '--spring.cloud.nacos.config.enabled=true', '--spring.cloud.nacos.discovery.enabled=true',
            '--spring.cloud.nacos.config.server-addr=192.168.6.100:8848',
            '--spring.cloud.nacos.discovery.server-addr=192.168.6.100:8848',
            '--spring.cloud.nacos.config.namespace=aillisten-dev',
            '--spring.cloud.nacos.discovery.namespace=aillisten-dev',
            '--spring.cloud.nacos.config.group=AILLISTEN_DEV',
            '--spring.cloud.nacos.discovery.group=AILLISTEN_DEV',
            '--spring.cloud.nacos.discovery.ip=127.0.0.1',
            '--spring.cloud.nacos.discovery.metadata.owner=aillisten-dev/v1',
            "--spring.cloud.nacos.config.prefix=aillisten-dev-$Module",
            '--spring.cloud.nacos.config.shared-configs[0].data-id=aillisten-common.yaml',
            '--spring.cloud.nacos.config.shared-configs[0].group=AILLISTEN_DEV',
            '--spring.cloud.nacos.config.shared-configs[0].refresh=true',
            '--spring.cloud.bus.enabled=false'
        )
    }
    return @('--spring.profiles.active=local', '--spring.cloud.bootstrap.enabled=false',
        '--spring.cloud.nacos.config.enabled=false', '--spring.cloud.nacos.discovery.enabled=false', '--spring.cloud.bus.enabled=false')
}
