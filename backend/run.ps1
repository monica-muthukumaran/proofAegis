<#
.SYNOPSIS
    Runs the ProofAegis backend.

.DESCRIPTION
    Two modes, because they have very different requirements:

      LOCAL (default) - no credentials, no cloud, no cost.
          Seeded cases from mock_data/seed_cases.json, uploads written to
          backend/.local_storage, auth not enforced, Gemini not called.
          The whole ingestion pipeline still runs for real: PyMuPDF text
          extraction, deterministic field parsing, matching, evidence graph.
          This is the right mode for development and for a safe demo.

      LIVE (-Live) - uses backend/.env as written.
          Real Firestore, real Cloud Storage, real Gemini, auth enforced.
          Costs money and touches your Google Cloud project.

    Environment variables set here win over backend/.env, because
    python-dotenv's load_dotenv() does not override values already present in
    the environment. That is what lets LOCAL mode ignore a .env pointing at
    production without editing the file.

.EXAMPLE
    .\run.ps1
    Starts on http://localhost:8080 in local mode.

.EXAMPLE
    .\run.ps1 -Live
    Starts against the real project using backend/.env.

.EXAMPLE
    .\run.ps1 -Port 9000
#>
param(
    [switch]$Live,
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

# --- Virtual environment ---------------------------------------------------
if (-not (Test-Path $python)) {
    Write-Host "No virtual environment found at backend\venv." -ForegroundColor Yellow
    Write-Host "Create it once with:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    python -m venv venv"
    Write-Host "    .\venv\Scripts\python.exe -m pip install -r requirements.txt"
    Write-Host ""
    exit 1
}

# --- Mode ------------------------------------------------------------------
if ($Live) {
    Write-Host ""
    Write-Host "  ProofAegis backend - LIVE MODE" -ForegroundColor Red
    Write-Host "  Real Firestore, Cloud Storage, and Gemini. This costs money." -ForegroundColor Red
    Write-Host ""

    if (-not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
        Write-Host "  backend\.env is missing. Copy .env.example and fill it in first." -ForegroundColor Red
        exit 1
    }

    # Only the port is forced; everything else comes from .env so that file
    # stays the single source of truth for a real deployment.
    $env:PORT = "$Port"

    Write-Host "  Reminder: STORAGE_BUCKET should be gs://proofaegis.firebasestorage.app" -ForegroundColor Yellow
    Write-Host ""
}
else {
    $env:USE_MOCK_DATA  = "true"    # seeded cases; no Firestore, no Gemini
    $env:STORAGE_BACKEND = "local"  # uploads land in backend\.local_storage
    $env:AUTH_REQUIRED  = "false"   # sign-in still works, just not enforced
    $env:ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
    $env:PORT = "$Port"

    Write-Host ""
    Write-Host "  ProofAegis backend - LOCAL MODE" -ForegroundColor Green
    Write-Host "  No credentials used. No cloud calls. Nothing billed." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Data      seeded cases (mock_data/seed_cases.json)"
    Write-Host "  Uploads   backend\.local_storage"
    Write-Host "  Auth      not enforced"
    Write-Host "  Gemini    off - extraction uses the deterministic parser"
    Write-Host ""
}

# --- Demo PDFs -------------------------------------------------------------
# Nothing to upload means nothing to demo, and they are gitignored, so a fresh
# clone needs them generated once.
$pdfDir = Join-Path $PSScriptRoot "data\synthetic_cases"
if (-not (Test-Path $pdfDir)) {
    Write-Host "  Generating synthetic demo PDFs (first run)..." -ForegroundColor Cyan
    & $python (Join-Path $PSScriptRoot "scripts\generate_synthetic_pdfs.py")
    Write-Host ""
}

Write-Host "  http://localhost:$Port/api/health" -ForegroundColor Cyan
Write-Host "  Ctrl+C to stop."
Write-Host ""

& $python (Join-Path $PSScriptRoot "app.py")
