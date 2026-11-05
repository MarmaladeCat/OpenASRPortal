<# Inspect only this MSI's wizard, capture optional-feature page, then cancel.
   Never presses Install, elevates, or touches an installed application.
#>
param([Parameter(Mandatory=$true)][string]$Msi,
      [Parameter(Mandatory=$true)][string]$ReportDir,
      [string]$ExpectedText='Destination|Folder|\u76ee\u6807|\u6587\u4ef6\u5939|\u66f4\u6539')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$process = Start-Process msiexec.exe -ArgumentList ('/i "' + [IO.Path]::GetFullPath($Msi) + '"') -PassThru
$window = $null
function Find-Window {
    $condition = New-Object Windows.Automation.PropertyCondition(
        [Windows.Automation.AutomationElement]::ProcessIdProperty, $process.Id)
    return [Windows.Automation.AutomationElement]::RootElement.FindFirst(
        [Windows.Automation.TreeScope]::Children, $condition)
}
function Find-Button($Window, [string]$Pattern) {
    if (-not $Window) { return $null }
    $condition = New-Object Windows.Automation.PropertyCondition(
        [Windows.Automation.AutomationElement]::ControlTypeProperty, [Windows.Automation.ControlType]::Button)
    foreach ($control in $Window.FindAll([Windows.Automation.TreeScope]::Descendants, $condition)) {
        if ($control.Current.IsEnabled -and $control.Current.Name -match $Pattern) { return $control }
    }
}
function Click($Button) {
    if (-not $Button) { throw 'Expected wizard button was not found.' }
    $Button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
}
try {
    $deadline = (Get-Date).AddSeconds(20)
    $next = $null
    while (-not $next) {
        $window = Find-Window
        $next = Find-Button $window 'Next|\u4e0b\u4e00\u6b65'
        if ((Get-Date) -gt $deadline -or $process.HasExited) { throw 'MSI wizard did not open.' }
        Start-Sleep -Milliseconds 150
    }
    Click $next
    $deadline = (Get-Date).AddSeconds(10)
    do {
        $window = Find-Window
        if (-not $window) {
            if ((Get-Date) -gt $deadline -or $process.HasExited) { throw 'MSI feature page did not open.' }
            Start-Sleep -Milliseconds 150
            continue
        }
        $all = $window.FindAll([Windows.Automation.TreeScope]::Descendants,
                               [Windows.Automation.Condition]::TrueCondition)
        $names = @($all | ForEach-Object { $_.Current.Name })
        if ($names -match $ExpectedText) { break }
        if ((Get-Date) -gt $deadline) { throw 'Expected installer page was not visible.' }
        Start-Sleep -Milliseconds 150
    } while ($true)
    $bounds = $window.Current.BoundingRectangle
    $bitmap = New-Object Drawing.Bitmap([int]$bounds.Width, [int]$bounds.Height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen([int]$bounds.X, [int]$bounds.Y, 0, 0, $bitmap.Size)
        $bitmap.Save((Join-Path ([IO.Path]::GetFullPath($ReportDir)) 'portal-msi-features.png'), [Drawing.Imaging.ImageFormat]::Png)
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
    [IO.File]::WriteAllText((Join-Path $ReportDir 'wizard.json'), ($names | ConvertTo-Json),
        (New-Object Text.UTF8Encoding($false)))
    Write-Output 'PASS real MSI wizard: expected page captured; installation was never invoked.'
} finally {
    if (-not $process.HasExited) {
        $window = Find-Window
        if ($window) {
            $cancel = Find-Button $window 'Cancel|\u53d6\u6d88'
            if ($cancel) { Click $cancel }
            Start-Sleep -Milliseconds 300
            $confirmation = Find-Window
            $yes = if ($confirmation) { Find-Button $confirmation '^Yes|^\u662f' }
            if ($yes) { Click $yes }
            Start-Sleep -Milliseconds 300
            if (-not $process.HasExited) {
                $finish = Find-Button (Find-Window) 'Finish|\u5b8c\u6210'
                if ($finish) { Click $finish }
            }
        }
        if (-not $process.WaitForExit(5000)) { Stop-Process -Id $process.Id -Force }
    }
}
