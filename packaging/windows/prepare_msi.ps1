<# Elevated MSI preparation only. Windows Installer owns service registration.
   No credentials appear in MSI properties, command arguments, or installer logs.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$DataDir,
    [Parameter(Mandatory=$true)][string]$InstallDir
)
$ErrorActionPreference = 'Stop'
$DataDir = [IO.Path]::GetFullPath($DataDir)
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
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
