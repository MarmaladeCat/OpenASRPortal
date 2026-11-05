# Native Windows equivalent of start.sh; keeps the same workspace data directory.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = if ($env:OPENASRPORTAL_PYTHON) { $env:OPENASRPORTAL_PYTHON } else { Join-Path $root '.venv/Scripts/python.exe' }
if (-not (Test-Path $python -PathType Leaf)) {
    throw 'Create the Portal environment first: py -3 -m venv .venv; .venv/Scripts/python.exe -m pip install -e .'
}
$previous = @{}
foreach ($name in @('PYTHONPATH', 'OPENASRPORTAL_DATA', 'PYTHONDONTWRITEBYTECODE')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:PYTHONPATH = (Join-Path $root 'src') + $(if ($env:PYTHONPATH) { [IO.Path]::PathSeparator + $env:PYTHONPATH })
    if (-not $env:OPENASRPORTAL_DATA) { $env:OPENASRPORTAL_DATA = Join-Path $root 'runtime/data' }
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $python -m openasrportal @args
    if ($LASTEXITCODE -ne 0) { throw "Portal exited with code $LASTEXITCODE" }
}
finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
