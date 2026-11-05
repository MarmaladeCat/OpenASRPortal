<# Deferred, elevated MSI health check. Failure triggers native MSI rollback. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$DataDir)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath (Join-Path $DataDir 'service.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$probeHost = $settings.host
if ($probeHost -eq '0.0.0.0') { $probeHost = '127.0.0.1' }
if ($probeHost -eq '::') { $probeHost = '[::1]' }
elseif ($probeHost.Contains(':')) { $probeHost = "[$probeHost]" }
$ready = Join-Path $DataDir 'control\ready.json'
$deadline = (Get-Date).AddSeconds(30)
do {
    try {
        $state = Get-Service -Name OpenASRPortal
        $instance = Get-Content -LiteralPath $ready -Raw -Encoding UTF8 | ConvertFrom-Json
        $health = Invoke-RestMethod -Uri "http://${probeHost}:$($settings.port)/health" -TimeoutSec 2
        if ($state.Status -eq 'Running' -and $instance.instance -and
            $health.service -eq 'OpenASRPortal' -and $health.status -eq 'ok') { exit 0 }
    } catch { }
    if ((Get-Date) -gt $deadline) { throw 'Portal startup failed; installation is rolling back. Inspect the preserved state/logs directory.' }
    Start-Sleep -Milliseconds 200
} while ($true)
