[CmdletBinding()]
param(
    [string]$Model = "qwen3:8b-q4_K_M",
    [string]$Fixture = "tests/fixtures/semantic/complete/bundle.json",
    [switch]$ForceCpu
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

Require-Command "ollama"
Require-Command "python"

$nvidiaSmi = Get-Command "nvidia-smi" -ErrorAction SilentlyContinue
if ($null -eq $nvidiaSmi) {
    Write-Warning "nvidia-smi is unavailable; the smoke can still run on CPU."
} else {
    $gpuCsv = & nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits
    if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed." }
    Write-Host "GPU: $gpuCsv"
    $driverText = ($gpuCsv -split ",")[-1].Trim()
    $driverMajor = 0
    if ([int]::TryParse(($driverText -split "\.")[0], [ref]$driverMajor) -and $driverMajor -lt 531) {
        Write-Warning "NVIDIA driver $driverText is older than the recommended 531.x baseline."
    }
}

$version = & ollama --version
if ($LASTEXITCODE -ne 0) { throw "ollama --version failed." }
Write-Host $version

$models = & ollama list
if ($LASTEXITCODE -ne 0) { throw "ollama list failed; check whether the tray/daemon owns port 11434." }
$escapedModel = [regex]::Escape($Model)
if (-not ($models | Select-String -Pattern "^$escapedModel\s" -Quiet)) {
    throw "Model '$Model' is absent. Run: ollama pull $Model"
}

Write-Host "Processor placement before request:"
& ollama ps
if ($LASTEXITCODE -ne 0) { throw "ollama ps failed." }

if ($ForceCpu -and $env:CUDA_VISIBLE_DEVICES -ne "-1") {
    throw 'To force CPU, stop the tray daemon, run Stop-Process -Name ollama -ErrorAction SilentlyContinue, then start: $env:CUDA_VISIBLE_DEVICES="-1"; ollama serve. Set the same variable in this shell and rerun with -ForceCpu.'
}

$arguments = @(
    "scripts/benchmark_llm.py",
    "--provider", "ollama",
    "--model", $Model,
    "--fixture", $Fixture,
    "--output", "benchmark-results/smoke.json",
    "--smoke-only"
)
if ($ForceCpu) { $arguments += "--force-cpu" }

& python @arguments
if ($LASTEXITCODE -ne 0) { throw "The Ollama schema smoke failed with exit code $LASTEXITCODE." }

Write-Host "Processor placement after request:"
$placement = & ollama ps
if ($LASTEXITCODE -ne 0) { throw "ollama ps failed after the request." }
$placement | Write-Host
if ($nvidiaSmi -and ($placement -match "100% CPU")) {
    Write-Warning "NVIDIA GPU is present, but Ollama reports 100% CPU placement."
}
Write-Host "Ollama advisory schema smoke passed."
