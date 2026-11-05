<# Install/update/remove the self-contained Portal system service. Run elevated.
   Removing the service deliberately preserves program files, config and data.
#>
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Uninstall', 'Start', 'Stop', 'Restart', 'Status')]
    [string]$Action = 'Status'
)
$ErrorActionPreference = 'Stop'
$install = Join-Path $env:ProgramFiles 'OpenASRPortal'
$data = Join-Path $env:ProgramData 'OpenASRPortal'
$wrapper = Join-Path $install 'OpenASRPortal.exe'
$python = Join-Path $install 'python\python.exe'
$config = Join-Path $data 'service.json'

function Invoke-Checked([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File failed (exit $LASTEXITCODE)" }
}
function Assert-OwnedService {
    $service = Get-CimInstance Win32_Service -Filter "Name='OpenASRPortal'"
    if ($service -and $service.PathName.Trim('"') -ne $wrapper) {
        throw 'OpenASRPortal is registered at a different location; refusing to modify it.'
    }
    if ($service -and $service.StartName -ne 'NT AUTHORITY\LocalService') {
        throw 'Existing Portal service uses an unexpected account; refusing to change it.'
    }
    return $service
}
function Protect-Directory([string]$Directory, [string]$ServiceRights) {
    if ((Get-Item -LiteralPath $Directory).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing a reparse-point installation/data directory: $Directory"
    }
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetSecurityDescriptorSddlForm("D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;$ServiceRights;;;LS)")
    Set-Acl -LiteralPath $Directory -AclObject $acl
}
function Assert-NoReparsePoints([string]$Directory) {
    if (Test-Path -LiteralPath $Directory) {
        $links = Get-ChildItem -LiteralPath $Directory -Recurse -Force -Attributes ReparsePoint
        if ($links) { throw "Refusing reparse points inside product directory: $Directory" }
    }
}
if ($Action -eq 'Status') {
    Get-Service -Name OpenASRPortal -ErrorAction SilentlyContinue
    exit 0
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open an Administrator PowerShell to manage the Portal system service.'
}
$existing = Assert-OwnedService
switch ($Action) {
    'Install' {
        if (-not (Test-Path (Join-Path $PSScriptRoot 'python\python.exe'))) {
            throw 'Extract the complete Portal Windows bundle before installing.'
        }
        foreach ($directory in @($PSScriptRoot, $install, $data)) {
            Assert-NoReparsePoints $directory
        }
        # Protect both executable code and secrets before copying or generating them.
        foreach ($directory in @($install, $data)) {
            New-Item -ItemType Directory -Force $directory | Out-Null
        }
        Protect-Directory $install 'FRFX'
        # LocalService can modify only its state/logs, never installed Python/code.
        Protect-Directory $data '0x1301bf'
        if ($existing -and $existing.State -ne 'Stopped') {
            Invoke-Checked $wrapper @('stopwait')
        }
        if ([IO.Path]::GetFullPath($PSScriptRoot) -ne [IO.Path]::GetFullPath($install)) {
            # /E, not /MIR: never delete unknown files from an existing installation.
            & robocopy.exe $PSScriptRoot $install /E /XJ /R:2 /W:1 /NFL /NDL /NJH /NJS
            if ($LASTEXITCODE -ge 8) { throw "Copy failed (robocopy exit $LASTEXITCODE)" }
        }
        # Ensure copied files inherit the protected installation ACL.
        Invoke-Checked 'icacls.exe' @("$install\*", '/reset', '/T', '/Q')
        if (Get-ChildItem -LiteralPath $data -Force) {
            Invoke-Checked 'icacls.exe' @("$data\*", '/reset', '/T', '/Q')
        }
        Invoke-Checked $python @('-B', '-m', 'openasrportal.entrypoints.service',
            'initialize', '--config', $config)
        if (-not $existing) { Invoke-Checked $wrapper @('install') }
        $readyFile = Join-Path $data 'control\ready.json'
        $oldReady = if (Test-Path -LiteralPath $readyFile) {
            Get-Content -LiteralPath $readyFile -Raw -Encoding UTF8
        } else { '' }
        Invoke-Checked $wrapper @('start')
        $settings = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
        $probeHost = $settings.host
        if ($probeHost -eq '0.0.0.0') { $probeHost = '127.0.0.1' }
        if ($probeHost -eq '::') { $probeHost = '[::1]' }
        elseif ($probeHost.Contains(':')) { $probeHost = "[$probeHost]" }
        $deadline = (Get-Date).AddSeconds(30)
        do {
            try {
                $health = Invoke-RestMethod -Uri "http://${probeHost}:$($settings.port)/health" -TimeoutSec 2
                $currentReady = Get-Content -LiteralPath $readyFile -Raw -Encoding UTF8
                $running = (Get-Service -Name OpenASRPortal).Status -eq 'Running'
                if ($running -and $currentReady -ne $oldReady -and
                    $health.service -eq 'OpenASRPortal' -and $health.status -eq 'ok') { break }
            } catch { }
            if ((Get-Date) -gt $deadline) { throw "Service did not become healthy; inspect $data\logs" }
            Start-Sleep -Milliseconds 200
        } while ($true)
        Write-Output "Portal installed. Configuration and keys: $config (administrators only)."
    }
    'Uninstall' {
        if ($existing) {
            if ($existing.State -ne 'Stopped') { Invoke-Checked $wrapper @('stopwait') }
            Invoke-Checked $wrapper @('uninstall')
        }
        Write-Output "Service removed. Files and data preserved at $install and $data."
    }
    'Start' { if (-not $existing) { throw 'Install Portal first.' }; Invoke-Checked $wrapper @('start') }
    'Stop' { if ($existing) { Invoke-Checked $wrapper @('stopwait') } }
    'Restart' { if (-not $existing) { throw 'Install Portal first.' }; Invoke-Checked $wrapper @('restart') }
}
