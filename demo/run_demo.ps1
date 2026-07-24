[CmdletBinding()]
param(
    [ValidateSet("dry-run", "local", "execute-github", "baseline")]
    [string]$Mode = "dry-run",
    [string]$Out = "build/demo",
    [string]$SoftwarePdf = "",
    [string]$ResearchPdf = "",
    [switch]$IUnderstandGitHubMutations
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = $null
foreach ($candidate in @(".\.venv312\Scripts\python.exe", "python", "py")) {
    if ($candidate -like ".\*") {
        if (Test-Path $candidate) { $python = (Resolve-Path $candidate).Path; break }
    } else {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { $python = $cmd.Source; break }
    }
}
if ($null -eq $python) { throw "Python not found" }

$arguments = @(
    "demo/run_demo.py",
    "--mode", $Mode,
    "--out", $Out
)
if ($SoftwarePdf) { $arguments += @("--software-pdf", $SoftwarePdf) }
if ($ResearchPdf) { $arguments += @("--research-pdf", $ResearchPdf) }
if ($IUnderstandGitHubMutations) { $arguments += "--i-understand-github-mutations" }

& $python @arguments
exit $LASTEXITCODE
