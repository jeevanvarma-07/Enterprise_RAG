<#
.SYNOPSIS
  Build the Enterprise RAG desktop app end to end on Windows.

.DESCRIPTION
  1. Freezes the FastAPI backend into a single .exe (PyInstaller).
  2. Copies it to src-tauri/binaries/ with the Rust target-triple suffix that
     Tauri's externalBin sidecar expects.
  3. Builds the Tauri app (frontend bundle + .msi/.exe installers).

.PARAMETER Flavour
  'lite' (default; fastembed/ONNX, no torch) or 'full' (bundles torch for the
  Power profile's local embeddings — much larger).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1
  powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1 -Flavour full

  Prereqs (see PHASE4_PACKAGING.md): Rust + cargo, the Tauri CLI (already an npm
  devDependency), the backend venv with deps + pyinstaller, and the WebView2
  runtime (preinstalled on Windows 11).
#>
param(
  [ValidateSet('lite', 'full')]
  [string]$Flavour = 'lite'
)

$ErrorActionPreference = 'Stop'
$Root     = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$BinDir   = Join-Path $Frontend 'src-tauri\binaries'

Write-Host "==> Enterprise RAG desktop build  (flavour: $Flavour)" -ForegroundColor Cyan

# --- locate venv python ------------------------------------------------------
$Py = Join-Path $Backend 'venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
  throw "No backend venv at $Backend\venv — create it and pip install -r requirements.txt"
}

# --- determine the Rust target triple ---------------------------------------
if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
  throw "rustc not found. Install Rust from https://rustup.rs and re-run."
}
$Triple = (& rustc -Vv | Select-String '^host: ').ToString().Replace('host: ', '').Trim()
Write-Host "==> Rust target triple: $Triple"

# --- 1. freeze the backend ---------------------------------------------------
Write-Host "==> Freezing backend with PyInstaller ..." -ForegroundColor Cyan
Push-Location $Backend
try {
  $env:RAG_BUILD = $Flavour
  & $Py -m PyInstaller rag-backend.spec --noconfirm --distpath dist --workpath build_pyi
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
} finally {
  Pop-Location
}

# --- 2. stage the sidecar with the target-triple name ------------------------
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Src = Join-Path $Backend 'dist\rag-backend.exe'
$Dst = Join-Path $BinDir "rag-backend-$Triple.exe"
if (-not (Test-Path $Src)) { throw "Frozen binary not found at $Src" }
Copy-Item -Force $Src $Dst
Write-Host "==> Sidecar staged: $Dst"

# --- 3. build the Tauri app --------------------------------------------------
Write-Host "==> Building Tauri app ..." -ForegroundColor Cyan
Push-Location $Frontend
try {
  & npm run tauri:build
  if ($LASTEXITCODE -ne 0) { throw "tauri build failed ($LASTEXITCODE)" }
} finally {
  Pop-Location
}

Write-Host "==> Done. Installers are under frontend\src-tauri\target\release\bundle\" -ForegroundColor Green
