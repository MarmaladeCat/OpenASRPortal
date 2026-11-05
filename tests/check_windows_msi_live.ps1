<# Explicit opt-in host acceptance. UAC is requested normally, never bypassed.
   Installs only into unique test directories, and refuses any existing Portal.
   It removes its own MSI registration afterwards but preserves test state/logs.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Msi,
    [Parameter(Mandatory=$true)][string]$ReportDir,
    [string]$CleanupPreviousReport
)
$ErrorActionPreference = 'Stop'
$Msi = [IO.Path]::GetFullPath($Msi)
$ReportDir = [IO.Path]::GetFullPath($ReportDir)
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$elevated = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $elevated) {
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath +
        '" -Msi "' + $Msi + '" -ReportDir "' + $ReportDir + '"'
    if ($CleanupPreviousReport) {
        $arguments += ' -CleanupPreviousReport "' + [IO.Path]::GetFullPath($CleanupPreviousReport) + '"'
    }
    try {
        $process = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
            -Verb RunAs -ArgumentList $arguments -PassThru -Wait
        exit $process.ExitCode
    } catch {
        [IO.File]::WriteAllText((Join-Path $ReportDir 'result.json'),
            '{"status":"elevation-not-granted","message":"UAC consent was not granted."}')
        throw
    }
}

$checks = New-Object Collections.Generic.List[string]
$installer = New-Object -ComObject WindowsInstaller.Installer
$ownedCodes = New-Object Collections.Generic.List[string]
$stamp = 'OpenASRPortal-MsiTest-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$install = Join-Path $env:ProgramFiles $stamp
$data = Join-Path $env:ProgramData $stamp
$config = Join-Path $data 'service.json'
$python = Join-Path $install 'python\python.exe'
$foreground = $null
$status = 'failed'
$failure = ''
Write-Host 'Portal MSI acceptance: temporary installation only. Please wait until this window closes.'

function Assert([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $checks.Add($Message)
}
function Invoke-Msi([string[]]$Arguments, [string]$Label, [int[]]$Expected = @(0, 3010)) {
    Write-Host "[Portal MSI acceptance] $Label"
    $line = ($Arguments + @('/qn', '/norestart', '/l*v', ('"' + (Join-Path $ReportDir "$Label.log") + '"'))) -join ' '
    $process = Start-Process msiexec.exe -ArgumentList $line -PassThru
    $null = $process.Handle
    if (-not $process.WaitForExit(180000)) {
        # Only the client started by this test; never terminate the shared MSI
        # service or another installer's process. Its transaction can roll back.
        Stop-Process -Id $process.Id -Force
        throw "$Label exceeded its acceptance-test time limit. Inspect its log before retrying."
    }
    if ($process.ExitCode -notin $Expected) {
        throw "$Label failed (MSI $($process.ExitCode)); see its log."
    }
    Write-Host "[Portal MSI acceptance] $Label completed (exit $($process.ExitCode))."
}
function Product-Code([string]$File) {
    $database = $installer.OpenDatabase($File, 0)
    $view = $database.OpenView("SELECT ``Value`` FROM ``Property`` WHERE ``Property``='ProductCode'")
    [void]$view.Execute()
    $record = $view.Fetch()
    return ([string]$record.StringData(1)).Trim()
}
function Free-Port {
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return $listener.LocalEndpoint.Port } finally { $listener.Stop() }
}
function Create-Config([string]$Path, [int]$Port) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Path) | Out-Null
    & $python -B -m openasrportal.entrypoints.service initialize --config $Path
    if ($LASTEXITCODE) { throw 'Could not initialize isolated acceptance configuration.' }
    $settings = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $settings.port = $Port
    [IO.File]::WriteAllText($Path, ($settings | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    return $settings
}
function Wait-Healthy([int]$Port, [int]$Timeout = 30) {
    $deadline = (Get-Date).AddSeconds($Timeout)
    do {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.service -eq 'OpenASRPortal' -and $health.status -eq 'ok') { return }
        } catch { }
        if ((Get-Date) -gt $deadline) { throw 'Portal did not become healthy in time.' }
        Start-Sleep -Milliseconds 200
    } while ($true)
}
function Profile-Request([int]$Port, [string]$Key, [string]$Method = 'Get', [string]$Body = '') {
    $parameters = @{ Uri="http://127.0.0.1:$Port/v1/admin/profiles"; Method=$Method;
        Headers=@{ Authorization=('Bearer ' + $Key) }; TimeoutSec=5 }
    if ($Body) { $parameters.ContentType='application/json'; $parameters.Body=[Text.Encoding]::UTF8.GetBytes($Body) }
    return Invoke-RestMethod @parameters
}
function Setup-Admin([int]$Port) {
    $base = "http://127.0.0.1:$Port/v1/admin/auth"
    $state = Invoke-RestMethod -Uri "$base/status" -TimeoutSec 5
    Assert (-not $state.initialized) 'New service has no default administrator password.'
    $password = 'MSI acceptance password ' + [guid]::NewGuid().ToString()
    $body = @{password=$password; confirmPassword=$password; setupChallenge=$state.setupChallenge} | ConvertTo-Json
    $session = Invoke-RestMethod -Uri "$base/setup" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 5
    $login = @{password=$password} | ConvertTo-Json
    $verified = Invoke-RestMethod -Uri "$base/login" -Method Post -ContentType 'application/json' -Body $login -TimeoutSec 5
    Assert ([bool]$verified.token) 'Administrator password is set through first-run API and accepted at login.'
    return $session.token
}

try {
    if ($CleanupPreviousReport) {
        $previous = Get-Content -LiteralPath $CleanupPreviousReport -Raw -Encoding UTF8 | ConvertFrom-Json
        $registered = Get-ItemProperty 'HKLM:\SOFTWARE\OpenASRPortal' -ErrorAction SilentlyContinue
        $prefix = Join-Path $env:ProgramFiles 'OpenASRPortal-MsiTest-'
        if (-not $previous.elevated -or -not $previous.installDirectory.StartsWith($prefix) -or
            -not $registered -or $registered.InstallDir.TrimEnd('\') -ne $previous.installDirectory.TrimEnd('\')) {
            throw 'Previous acceptance installation ownership could not be verified.'
        }
        $registeredService = Get-CimInstance Win32_Service -Filter "Name='OpenASRPortal'"
        if ($registeredService -and $registeredService.PathName.Trim('"') -ne
            (Join-Path $previous.installDirectory 'OpenASRPortal.exe')) {
            throw 'The current service is not owned by the previous acceptance test.'
        }
        $previousCodes = @($previous.productCodes)
        if (-not $previousCodes.Count -or -not $previousCodes[0]) {
            # Compatibility with the first acceptance report, which predates
            # ownership.json. The unique directory was verified against HKLM
            # above, so only that installed Portal registration is removable.
            $previousCodes = @(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' |
                Where-Object { $_.DisplayName -eq 'OpenASRPortal' } | ForEach-Object { $_.PSChildName })
            if ($previousCodes.Count -ne 1) { throw 'Previous MSI identity is ambiguous.' }
        }
        foreach ($previousCode in $previousCodes) {
            $previousCode = $previousCode.Trim()
            if ($previousCode -notmatch '^\{[0-9A-Fa-f-]{36}\}$') { throw 'Invalid previous test product identity.' }
            Invoke-Msi @('/x', $previousCode) 'cleanup-previous-acceptance' @(0, 3010, 1605, 1614)
        }
    }
    if (Get-Service -Name OpenASRPortal -ErrorAction SilentlyContinue) {
        throw 'Existing Portal service detected; host acceptance refuses to modify it.'
    }
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                       'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        if (Get-ItemProperty $key -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq 'OpenASRPortal' }) {
            throw 'Existing Portal MSI detected; refusing to change the installed product.'
        }
    }
    $firstCode = Product-Code $Msi
    $ownedCodes.Add($firstCode)
    $ownership = @{ elevated=$true; productCodes=$ownedCodes.ToArray(); installDirectory=$install;
        preservedStateDirectory=$data }
    [IO.File]::WriteAllText((Join-Path $ReportDir 'ownership.json'), ($ownership | ConvertTo-Json),
        (New-Object Text.UTF8Encoding($false)))
    $paths = @(('INSTALLDIR="' + $install + '"'), ('PORTALDATADIR="' + $data + '"'))
    Invoke-Msi (@('/i', ('"' + $Msi + '"'), 'ADDLOCAL=PortalCore') + $paths) '01-core-only'
    Assert (Test-Path -LiteralPath $python) 'Core-only installs private runtime.'
    Assert (-not (Get-Service OpenASRPortal -ErrorAction SilentlyContinue)) 'Core-only does not register a service.'
    Assert (-not (Test-Path -LiteralPath $config)) 'Core-only does not create machine-service credentials.'

    $foregroundConfig = Join-Path $ReportDir 'foreground\service.json'
    $foregroundSettings = Create-Config $foregroundConfig (Free-Port)
    $foreground = Start-Process -FilePath $python -ArgumentList (
        '-B -m openasrportal.entrypoints.service foreground --config "' + $foregroundConfig + '"') `
        -RedirectStandardOutput (Join-Path $ReportDir 'foreground.stdout.log') `
        -RedirectStandardError (Join-Path $ReportDir 'foreground.stderr.log') -PassThru
    # Cache the native handle while alive; Windows PowerShell otherwise may
    # lose ExitCode for a short-lived Start-Process -PassThru child.
    $null = $foreground.Handle
    Wait-Healthy $foregroundSettings.port
    & $python -B -m openasrportal.entrypoints.service stop --config $foregroundConfig
    if ($LASTEXITCODE) { throw 'Foreground stop failed.' }
    $exited = $foreground.WaitForExit(10000)
    Assert ($exited -and $foreground.ExitCode -eq 0) 'Installed foreground mode starts and stops cleanly.'
    $foreground = $null

    $settings = Create-Config $config (Free-Port)
    $configHash = (Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash
    $busy = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $settings.port)
    $busy.Start()
    try {
        Invoke-Msi (@('/i', ('"' + $Msi + '"'), 'ADDLOCAL=ALL') + $paths) '02a-port-conflict-rollback' @(1603)
        $failureLog = Get-Content -LiteralPath (Join-Path $ReportDir '02a-port-conflict-rollback.log') -Raw -Encoding Unicode
        Assert ($failureLog -match 'Portal startup failed|Error 1920|1: 1920') 'Occupied-port rollback is caused by failed service startup, not an unrelated setup action.'
        Assert (-not (Get-Service OpenASRPortal -ErrorAction SilentlyContinue)) 'Failed service startup rolls back SCM registration.'
        Assert (Test-Path -LiteralPath $python) 'Failed service startup preserves the already installed foreground application.'
    } finally { $busy.Stop() }
    Invoke-Msi (@('/i', ('"' + $Msi + '"'), 'ADDLOCAL=ALL') + $paths) '02-add-service'
    Wait-Healthy $settings.port
    $service = Get-CimInstance Win32_Service -Filter "Name='OpenASRPortal'"
    Assert ($service.StartName -eq 'NT AUTHORITY\LocalService') 'Service runs as LocalService, not LocalSystem.'
    Assert ($service.PathName.Trim('"') -eq (Join-Path $install 'OpenASRPortal.exe')) 'SCM points only at this test installation.'
    Assert ($service.StartMode -eq 'Auto') 'Service is configured for automatic startup.'
    $acl = Get-Acl -LiteralPath $data
    $sids = @($acl.Access | ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value })
    Assert ($acl.AreAccessRulesProtected -and $sids.Count -eq 3 -and
        'S-1-5-18' -in $sids -and 'S-1-5-32-544' -in $sids -and 'S-1-5-19' -in $sids) 'State ACL permits only SYSTEM, administrators and LocalService.'
    Assert ((Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $configHash) 'Adding the service preserves network and data paths.'
    Assert (-not ($settings.PSObject.Properties.Name -contains 'adminKey') -and
        -not ($settings.PSObject.Properties.Name -contains 'apiKey')) 'Service configuration contains no administrator password or recognition key.'
    $adminToken = Setup-Admin $settings.port
    Profile-Request $settings.port $adminToken 'Post' `
        '{"id":"msi-acceptance","title":"MSI acceptance","provider":"openlocalasr","configuration":{"apiKey":"test-upstream"}}' | Out-Null

    Stop-Service OpenASRPortal
    (Get-Service OpenASRPortal).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    Assert (-not (Test-Path -LiteralPath (Join-Path $data 'control\ready.json'))) 'SCM stop completes graceful cleanup.'
    Start-Service OpenASRPortal
    Wait-Healthy $settings.port
    $profiles = Profile-Request $settings.port $adminToken
    Assert ($profiles.profiles[0].id -eq 'msi-acceptance') 'SCM restart preserves database profiles.'

    $service = Get-CimInstance Win32_Service -Filter "Name='OpenASRPortal'"
    $child = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($service.ProcessId)" |
        Where-Object { $_.ExecutablePath -eq $python })
    Assert ($child.Count -eq 1) 'Recovery target is this service private Python only.'
    Stop-Process -Id $child[0].ProcessId -Force
    Start-Sleep -Seconds 2
    Wait-Healthy $settings.port 45
    $restarted = Get-CimInstance Win32_Service -Filter "Name='OpenASRPortal'"
    Assert ($restarted.ProcessId -ne $service.ProcessId) 'SCM failure recovery restarts the wrapper after owned child failure.'

    # A second product/package code exercises a real same-version MajorUpgrade.
    # Only the generated test copy is modified; the delivered MSI is unchanged.
    $upgrade = Join-Path $ReportDir 'upgrade-test.msi'
    Copy-Item -LiteralPath $Msi -Destination $upgrade
    $newCode = '{' + [guid]::NewGuid().ToString().ToUpperInvariant() + '}'
    $ownedCodes.Add($newCode)
    $ownership.productCodes = $ownedCodes.ToArray()
    [IO.File]::WriteAllText((Join-Path $ReportDir 'ownership.json'), ($ownership | ConvertTo-Json),
        (New-Object Text.UTF8Encoding($false)))
    $database = $installer.OpenDatabase($upgrade, 1)
    $view = $database.OpenView("UPDATE ``Property`` SET ``Value``='$newCode' WHERE ``Property``='ProductCode'")
    $view.Execute()
    $summary = $database.SummaryInformation(20)
    $summary.Property(9) = '{' + [guid]::NewGuid().ToString().ToUpperInvariant() + '}'
    $summary.Persist()
    $database.Commit()
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($summary)
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($view)
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($database)
    Invoke-Msi (@('/i', ('"' + $upgrade + '"'), 'ADDLOCAL=ALL') + $paths) '03-major-upgrade'
    Wait-Healthy $settings.port
    Assert ((Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $configHash) 'Major upgrade preserves credentials byte-for-byte.'
    $profiles = Profile-Request $settings.port $adminToken
    Assert ($profiles.profiles[0].id -eq 'msi-acceptance') 'Major upgrade preserves database profiles.'

    Invoke-Msi @('/i', ('"' + $upgrade + '"'), 'REMOVE=PortalService') '04-remove-service-feature'
    Assert (-not (Get-Service OpenASRPortal -ErrorAction SilentlyContinue)) 'Maintenance can deselect and remove just the service.'
    Assert (Test-Path -LiteralPath $python) 'Removing the service feature retains the foreground application.'
    Invoke-Msi (@('/i', ('"' + $upgrade + '"'), 'ADDLOCAL=PortalService') + $paths) '05-restore-service-feature'
    Wait-Healthy $settings.port
    Assert ((Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash -eq $configHash) 'Re-enabling the service reuses its credentials.'
    Invoke-Msi @('/x', $newCode) '06-uninstall'
    Assert (-not (Get-Service OpenASRPortal -ErrorAction SilentlyContinue)) 'Uninstall removes SCM registration.'
    Assert (-not (Test-Path -LiteralPath $python)) 'Uninstall removes the private runtime.'
    Assert ((Test-Path -LiteralPath $config) -and (Test-Path -LiteralPath (Join-Path $data 'data\portal.db'))) 'Uninstall preserves configuration and business data.'
    $status = 'passed'
} catch {
    $failure = $_.Exception.Message
} finally {
    if ($foreground -and -not $foreground.HasExited) { Stop-Process -Id $foreground.Id -Force }
    foreach ($code in $ownedCodes) {
        try {
            # Do not use a cached Installer COM object's ProductState after an
            # external msiexec changes registration. Uninstall only owned codes;
            # 1605/1614 simply mean an upgrade/already completed uninstall did it.
            Invoke-Msi @('/x', $code) ('cleanup-' + $code.Trim('{}')) @(0, 3010, 1605, 1614)
        } catch { if (-not $failure) { $failure = 'Test installation cleanup failed.' }; $status='failed' }
    }
    $report = @{ status=$status; elevated=$true; checks=$checks.ToArray(); failure=$failure;
        productCodes=$ownedCodes.ToArray();
        installDirectory=$install; preservedStateDirectory=$data }
    [IO.File]::WriteAllText((Join-Path $ReportDir 'result.json'), ($report | ConvertTo-Json -Depth 5),
        (New-Object Text.UTF8Encoding($false)))
}
if ($status -ne 'passed') { Write-Error $failure; exit 1 }
Write-Output "PASS MSI host acceptance: $($checks.Count) checks. State/logs preserved for review."
