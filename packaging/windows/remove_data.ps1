[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$DataDir, [string]$UserDataDir, [switch]$AllUsers)
$ErrorActionPreference='Stop'
$DataDir=[IO.Path]::GetFullPath($DataDir).TrimEnd('\')
function Assert-NoLinks([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        $item=Get-Item -LiteralPath $Path -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            (Get-ChildItem -LiteralPath $Path -Recurse -Force -Attributes ReparsePoint)) {throw 'Refusing Portal data deletion through reparse points.'}
    }
}
function Remove-OwnedDirectory([string]$Path) {
    if (-not $Path) {return}
    $full=[IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ([IO.Path]::GetFileName($full) -notmatch '^OpenASRPortal(?:-MsiTest-[a-f0-9]+)?$') {throw 'Refusing unrecognized Portal state directory.'}
    if (-not (Test-Path -LiteralPath $full)) {return}
    Assert-NoLinks $full
    $config=Join-Path $full 'service.json'
    if (Test-Path -LiteralPath $config) {
        $settings=Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
        $data=$settings.dataDir
        if ($data -and -not [IO.Path]::IsPathRooted($data)) {$data=Join-Path $full $data}
        if ($data) {
            $data=[IO.Path]::GetFullPath($data)
            Assert-NoLinks $data
            # External directories may contain unrelated work: delete only files
            # this product owns, never recursively erase an arbitrary custom path.
            if (-not $data.StartsWith($full+'\',[StringComparison]::OrdinalIgnoreCase)) {
                foreach($name in @('portal.db','portal.db-wal','portal.db-shm','portal.db-journal','asr-key-vault.key','service-credentials.json')) {
                    $file=Join-Path $data $name
                    if (Test-Path -LiteralPath $file -PathType Leaf) {Remove-Item -LiteralPath $file -Force}
                }
            }
        }
    }
    Remove-Item -LiteralPath $full -Recurse -Force
}
$isolated=[IO.Path]::GetFileName($DataDir) -like 'OpenASRPortal-MsiTest-*'
$targets=@($DataDir)
if (-not $isolated) {$targets += $UserDataDir}
if ($AllUsers -and [IO.Path]::GetFileName($DataDir) -notlike 'OpenASRPortal-MsiTest-*') {
    $targets += @(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\*' |
        Where-Object {$_.ProfileImagePath} | ForEach-Object {Join-Path ([Environment]::ExpandEnvironmentVariables($_.ProfileImagePath)) 'AppData\Local\OpenASRPortal'})
}
foreach($target in ($targets | Select-Object -Unique)) {Remove-OwnedDirectory $target}
