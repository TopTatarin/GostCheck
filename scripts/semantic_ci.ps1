[CmdletBinding()]
param(
    [string]$Provider = "",
    [string]$Source = "tests/fixtures/demo/pass",
    [string]$Out = "build/semantic",
    [switch]$AllowCloudData
)

$ErrorActionPreference = "Stop"

if ($Provider -and $Provider -notin @("ollama", "yandex", "disabled")) {
    throw "Provider must be ollama, yandex, or disabled. Got: $Provider"
}

$python = $null
foreach ($candidate in @("python", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        $python = $cmd.Source
        break
    }
}
if ($null -eq $python) {
    throw "Python was not found in PATH."
}

$arguments = @(
    "scripts/semantic_ci.py",
    "--source", $Source,
    "--out", $Out
)
if ($Provider) {
    $arguments += @("--provider", $Provider)
}
if ($AllowCloudData) {
    $arguments += "--allow-cloud-data"
}

& $python @arguments
exit $LASTEXITCODE
