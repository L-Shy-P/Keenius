# ============================================================================
# Keenius Installer for Windows
# ============================================================================
# One-line install:
#   powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
#
# After publishing:
#   iex (irm https://raw.githubusercontent.com/.../install.ps1)
# ============================================================================

$ErrorActionPreference = "Stop"
$outputEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

Write-Host ""
Write-Host "===================================" -ForegroundColor Cyan
Write-Host "  Keenius Installer" -ForegroundColor Cyan
Write-Host "  CLI AI Teacher" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

# -- Step 1: Check Python --------------------------------------------
Write-Host "[1/3] Checking Python..." -ForegroundColor Yellow

$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
}

if (-not $pythonCmd) {
    Write-Host ""
    Write-Host "X Python not found. Please install Python 3.10+:" -ForegroundColor Red
    Write-Host "   winget install Python.Python.3.11" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   Or download from: https://www.python.org/downloads/" -ForegroundColor DarkGray
    Write-Host "   (Check 'Add Python to PATH' during install)" -ForegroundColor DarkGray
    Write-Host ""
    exit 1
}

$pythonVersion = & $pythonCmd --version 2>&1
Write-Host "   OK  $pythonVersion" -ForegroundColor Green

# -- Step 2: pip install ---------------------------------------------
Write-Host "[2/3] Installing Keenius..." -ForegroundColor Yellow

$projectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $projectDir) {
    $projectDir = Get-Location
}

& $pythonCmd -m pip install -e $projectDir
if ($LASTEXITCODE -ne 0) {
    Write-Host "   X Install failed (exit code: $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host "   OK  Keenius installed" -ForegroundColor Green

# -- Step 3: Check PATH ----------------------------------------------
Write-Host "[3/3] Checking PATH..." -ForegroundColor Yellow

$pythonExe = & $pythonCmd -c "import sys; print(sys.executable)"
$scriptsDir = Split-Path $pythonExe -Parent
$scriptsDir = Join-Path $scriptsDir "Scripts"

$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$scriptsDir*") {
    Write-Host "   !  Python Scripts not in user PATH, adding..." -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$scriptsDir", "User")
    $env:PATH = "$env:PATH;$scriptsDir"
    Write-Host "   OK  Added to PATH: $scriptsDir" -ForegroundColor Green
} else {
    Write-Host "   OK  Python Scripts already in PATH" -ForegroundColor Green
}

# -- Done ------------------------------------------------------------
Write-Host ""
Write-Host "===================================" -ForegroundColor Cyan
Write-Host "  Install Complete!" -ForegroundColor Green
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Yellow
Write-Host "    Keenius setup     Configure API Key" -ForegroundColor White
Write-Host "    Keenius           Launch AI Teacher" -ForegroundColor White
Write-Host ""
Write-Host "  Tip: If 'Keenius' is not found, close and reopen your terminal." -ForegroundColor DarkGray
Write-Host ""

[Console]::OutputEncoding = $outputEncoding
