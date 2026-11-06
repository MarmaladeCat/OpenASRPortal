<# Elevated MSI preparation only. Windows Installer owns service registration.
   No credentials appear in MSI properties, command arguments, or installer logs.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$DataDir,
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [string]$LegacyDataDir,
    [string]$PreviousInstallation
)
$ErrorActionPreference = 'Stop'
$DataDir = [IO.Path]::GetFullPath($DataDir)
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$parent = [IO.DirectoryInfo]$DataDir
while ($parent.Parent) {
    if ($parent.Exists -and ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Portal state parent cannot be a reparse point.' }
    $parent = $parent.Parent
}
$service = Get-Service -Name OpenASRPortal -ErrorAction SilentlyContinue
if ($service -and $service.Status -ne 'Stopped') {
    throw 'MSI preparation requires the previous service instance to be stopped.'
}
if (-not $LegacyDataDir) { $LegacyDataDir = Join-Path $env:ProgramData 'OpenASRPortal' }
if (-not (Test-Path -LiteralPath (Join-Path $DataDir 'service.json')) -and
    (Test-Path -LiteralPath (Join-Path $LegacyDataDir 'service.json')) -and
    [IO.Path]::GetFullPath($LegacyDataDir) -ne $DataDir) {
    $legacy = Get-Item -LiteralPath $LegacyDataDir
    if (($legacy.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        (Get-ChildItem -LiteralPath $LegacyDataDir -Recurse -Force -Attributes ReparsePoint)) {
        throw 'Legacy Portal data cannot contain reparse points.'
    }
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $migrationAcl = New-Object Security.AccessControl.DirectorySecurity
    $migrationAcl.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;LS)')
    Set-Acl -LiteralPath $DataDir -AclObject $migrationAcl
    # service.json is the completion marker: an interrupted copy must be retried
    # before a service can open a partially migrated database.
    Get-ChildItem -LiteralPath $LegacyDataDir -Force |
        Where-Object { $_.Name -ne 'service.json' -and $_.Name -notin @('control', 'logs') } |
        Copy-Item -Destination $DataDir -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $LegacyDataDir 'service.json') -Destination (Join-Path $DataDir 'service.json.migrating') -Force
    Move-Item -LiteralPath (Join-Path $DataDir 'service.json.migrating') -Destination (Join-Path $DataDir 'service.json') -Force
}
$retained = Test-Path -LiteralPath (Join-Path $DataDir 'service.json')
foreach ($directory in @($DataDir, $InstallDir)) {
    if (Test-Path -LiteralPath $directory) {
        $item = Get-Item -LiteralPath $directory
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            (Get-ChildItem -LiteralPath $directory -Recurse -Force -Attributes ReparsePoint)) {
            throw 'Portal installation/state directories cannot contain reparse points.'
        }
    }
}
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;LS)')
Set-Acl -LiteralPath $DataDir -AclObject $acl
if (Get-ChildItem -LiteralPath $DataDir -Force) {
    & icacls.exe "$DataDir\*" /reset /T /Q | Out-Null
    if ($LASTEXITCODE) { throw 'Could not protect Portal state files.' }
}
# Read-only service access; ordinary users may read code, but not service state.
& icacls.exe $InstallDir /grant:r '*S-1-5-19:(OI)(CI)RX' /Q | Out-Null
if ($LASTEXITCODE) { throw 'Could not grant Portal runtime read access.' }
$config = Join-Path $DataDir 'service.json'
& $Python -B -m openasrportal.entrypoints.service initialize --config $config
if ($LASTEXITCODE) { throw 'Portal configuration validation failed; existing data was preserved.' }
$operation = if ($PreviousInstallation) { 'upgrade' } elseif ($retained) { 'reinstall' } else { 'first-install' }
@{ schemaVersion = 1; operation = $operation } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $DataDir 'installation.json') -Encoding UTF8
$configuration = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
$legacyDefault = Join-Path $LegacyDataDir 'data'
if ([IO.Path]::IsPathRooted($configuration.dataDir) -and
    [IO.Path]::GetFullPath($configuration.dataDir).TrimEnd('\') -eq [IO.Path]::GetFullPath($legacyDefault).TrimEnd('\')) {
    $configuration.dataDir = 'data'
    $configuration | ConvertTo-Json | Set-Content -LiteralPath $config -Encoding UTF8
}
$hostName = switch ($configuration.host) { '0.0.0.0' { '127.0.0.1' } '::' { '::1' } default { $configuration.host } }
if ($hostName.Contains(':')) { $hostName = '[' + $hostName + ']' }
$address = 'http://' + $hostName + ':' + $configuration.port + '/admin'
[IO.File]::WriteAllText((Join-Path $InstallDir 'PortalAdmin.url'), "[InternetShortcut]`r`nURL=$address`r`n")
# MSI's configurable state directory also supports isolated acceptance tests.
# This changes paths only, never keys; native ServiceInstall/ServiceControl own SCM.
$xmlPath = Join-Path $InstallDir 'OpenASRPortal.xml'
[xml]$xml = Get-Content -LiteralPath $xmlPath -Raw -Encoding UTF8
$module = '-B -m openasrportal.entrypoints.service '
$xml.service.startarguments = $module + 'run --config "' + $config + '"'
$xml.service.stoparguments = $module + 'stop --config "' + $config + '"'
$xml.service.logpath = [string](Join-Path $DataDir 'logs')
$xml.Save($xmlPath)
$service = Get-Service -Name OpenASRPortal -ErrorAction SilentlyContinue
if ($service -and $service.Status -ne 'Stopped') {
    throw 'MSI preparation requires the previous service instance to be stopped.'
}
# A previous crash must not make an unrelated listener look like a healthy start.
$ready = Join-Path $DataDir 'control\ready.json'
if (Test-Path -LiteralPath $ready) { Remove-Item -LiteralPath $ready }
