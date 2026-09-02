$ErrorActionPreference = "Stop"

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$virtualEnvironmentPythonw = Join-Path $scriptDirectory ".venv\Scripts\pythonw.exe"
$virtualEnvironmentPython = Join-Path $scriptDirectory ".venv\Scripts\python.exe"
$appPath = Join-Path $scriptDirectory "app.py"
$pythonArguments = @()

if (Test-Path -LiteralPath $virtualEnvironmentPythonw) {
    Start-Process `
        -FilePath $virtualEnvironmentPythonw `
        -ArgumentList @($appPath) `
        -WorkingDirectory $scriptDirectory
    exit 0
}
elseif (Test-Path -LiteralPath $virtualEnvironmentPython) {
    $pythonCommand = $virtualEnvironmentPython
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = (Get-Command python).Source
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = (Get-Command py).Source
    $pythonArguments = @("-3")
}
else {
    throw "Python 3 was not found. Install Python and run setup first."
}

# Start from this directory so relative asset paths are stable.
Push-Location $scriptDirectory
try {
    & $pythonCommand @pythonArguments $appPath
    $appExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $appExitCode
