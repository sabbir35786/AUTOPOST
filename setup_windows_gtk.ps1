# Setup script: Install GTK runtime for Pango/Cairo support on Windows
# Downloads the gvsbuild GTK3 bundle and installs PyGObject + PyCairo.
# Run this from an elevated (Admin) PowerShell prompt for persistent PATH updates.
# Usage: .\setup_windows_gtk.ps1

$ErrorActionPreference = "Stop"

# --- Configuration ---
$GTK_DIR = "C:\gtk"
$GTK_ZIP = "$env:TEMP\gtk3.zip"
$BACKEND_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV_PYTHON = Join-Path $BACKEND_DIR "backend\venv\Scripts\python.exe"
if (-not (Test-Path $VENV_PYTHON)) {
    $VENV_PYTHON = Join-Path $BACKEND_DIR "venv\Scripts\python.exe"
}
$GTK_BIN = "$GTK_DIR\bin"
$GTK_TYPELIB = "$GTK_DIR\lib\girepository-1.0"

# --- Step 1: Download & extract GTK3 bundle ---
if (Test-Path "$GTK_BIN\libpango-1.0-0.dll") {
    Write-Host "[OK] GTK runtime already present at $GTK_DIR"
} else {
    Write-Host ">>> Downloading GTK3 bundle (gvsbuild)..."
    $apiUrl = "https://api.github.com/repos/wingtk/gvsbuild/releases/latest"
    try {
        $release = Invoke-RestMethod -Uri $apiUrl -UseBasicParsing
        $asset = $release.assets | Where-Object { $_.name -like "GTK3_Gvsbuild_*_x64.zip" }
        if (-not $asset) {
            throw "No GTK3 zip asset found in latest release"
        }
        $downloadUrl = $asset.browser_download_url
        Write-Host "Downloading: $($asset.name)"
        Invoke-WebRequest -Uri $downloadUrl -OutFile $GTK_ZIP -UseBasicParsing
    } catch {
        Write-Host "Failed to fetch from GitHub API, trying fallback URL..."
        $fallbackUrl = "https://github.com/wingtk/gvsbuild/releases/download/2026.1.0/GTK3_Gvsbuild_2026.1.0_x64.zip"
        Invoke-WebRequest -Uri $fallbackUrl -OutFile $GTK_ZIP -UseBasicParsing
    }

    Write-Host ">>> Extracting to $GTK_DIR..."
    if (-not (Test-Path $GTK_DIR)) {
        New-Item -ItemType Directory -Path $GTK_DIR -Force | Out-Null
    }
    Expand-Archive -Path $GTK_ZIP -DestinationPath $GTK_DIR -Force
    Remove-Item $GTK_ZIP -Force
    Write-Host "[OK] GTK runtime installed at $GTK_DIR"
}

# --- Step 2: Set PATH and GI_TYPELIB_PATH for current session ---
$env:Path = "$GTK_BIN;" + $env:Path
$env:GI_TYPELIB_PATH = "$GTK_TYPELIB"

# --- Step 3: Persist PATH in user-level environment (non-elevated: HKCU) ---
try {
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -notlike "*$GTK_BIN*") {
        [Environment]::SetEnvironmentVariable("Path", "$GTK_BIN;$currentPath", "User")
        Write-Host "[OK] Added $GTK_BIN to user PATH (persistent)"
    } else {
        Write-Host "[OK] $GTK_BIN already in user PATH"
    }

    $currentTypelib = [Environment]::GetEnvironmentVariable("GI_TYPELIB_PATH", "User")
    if ($currentTypelib -notlike "*$GTK_TYPELIB*") {
        [Environment]::SetEnvironmentVariable("GI_TYPELIB_PATH", "$GTK_TYPELIB;$currentTypelib", "User")
        Write-Host "[OK] Added $GTK_TYPELIB to user GI_TYPELIB_PATH (persistent)"
    } else {
        Write-Host "[OK] $GTK_TYPELIB already in user GI_TYPELIB_PATH"
    }
} catch {
    Write-Host "[WARNING] Could not update persistent environment variables (run as Admin?): $_"
}

# --- Step 4: Install PyGObject + PyCairo in the virtual environment ---
if (Test-Path $VENV_PYTHON) {
    Write-Host ">>> Installing PyGObject..."
    $wheel = Get-ChildItem -Path "$GTK_DIR\wheels" -Filter "pygobject-*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($wheel) {
        Write-Host "    Using bundled wheel: $($wheel.Name)"
        & $VENV_PYTHON -m pip install "$($wheel.FullName)" --quiet
    } else {
        Write-Host "    No bundled wheel found, installing via pip..."
        & $VENV_PYTHON -m pip install pygobject --quiet
    }

    Write-Host ">>> Installing PyCairo..."
    & $VENV_PYTHON -m pip install pycairo>=1.26 --quiet

    # Install fonttools for font family detection
    & $VENV_PYTHON -m pip install fonttools --quiet
} else {
    Write-Host "[WARNING] Virtual environment not found at $VENV_PYTHON"
    Write-Host "          Create it first: python -m venv $BACKEND_DIR\venv"
}

# --- Step 5: Verify the installation ---
Write-Host ""
Write-Host ">>> Verifying Pango/Cairo installation..."
try {
    # Add GTK bin to path for the verification
    $env:Path = "$GTK_BIN;" + $env:Path
    $env:GI_TYPELIB_PATH = "$GTK_TYPELIB"

    if (Test-Path $VENV_PYTHON) {
        $testCode = @"
import os, sys
os.environ['PATH'] = r'$GTK_BIN' + os.pathsep + os.environ.get('PATH', '')
os.environ['GI_TYPELIB_PATH'] = r'$GTK_TYPELIB' + os.pathsep + os.environ.get('GI_TYPELIB_PATH', '')

try:
    import cairo
    import gi
    gi.require_version('Pango', '1.0')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Pango, PangoCairo
    print('[OK] Pango/Cairo imports successful')

    # Verify cairo version
    print(f'     Cairo version: {cairo.cairo_version_string()}')

    # Test rendering: create a surface and layout
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 50)
    ctx = cairo.Context(surface)
    layout = PangoCairo.create_layout(ctx)
    layout.set_text('Bangla: \u09AC\u09BE\u0982\u09B2\u09BE \u09AA\u09B0\u09C0\u0995\u09CD\u09B7\u09BE', -1)
    PangoCairo.show_layout(ctx, layout)
    print('[OK] Pango text rendering works (complex script shaping supported)')
    sys.exit(0)
except ImportError as e:
    print(f'[FAIL] Pango/Cairo import failed: {e}')
    sys.exit(1)
except Exception as e:
    print(f'[FAIL] Pango/Cairo rendering failed: {e}')
    sys.exit(1)
"@
        & $VENV_PYTHON -c $testCode
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[PASS] All checks passed!"
        } else {
            Write-Host "[FAIL] Verification failed - see messages above"
        }
    }
} catch {
    Write-Host "[FAIL] Verification error: $_"
}

# --- Step 6: Create helper batch file ---
$BAT_PATH = Join-Path $BACKEND_DIR "setenv_gtk.cmd"
@"
@echo off
REM Add GTK runtime to PATH for the current session
set "PATH=$GTK_BIN;%PATH%"
set "GI_TYPELIB_PATH=$GTK_TYPELIB"
echo [OK] GTK environment set for this session
"@ | Set-Content -Path $BAT_PATH -Encoding ASCII
Write-Host "[OK] Created $BAT_PATH - run this before starting the app if PATH is not persistent"

Write-Host ""
Write-Host "========================================"
Write-Host " GTK setup complete!"
Write-Host "========================================"
Write-Host "GTK runtime : $GTK_DIR"
Write-Host ""
Write-Host "To make these changes take effect in your"
Write-Host "current terminal, the PATH has been updated"
Write-Host "for this session already."
Write-Host ""
Write-Host "If the persistent PATH doesn't take effect,"
Write-Host "run this before starting the app:"
Write-Host "  .\setenv_gtk.cmd"
Write-Host ""
Write-Host "Or in PowerShell:"
Write-Host '  $env:Path = "C:\gtk\bin;" + $env:Path'
Write-Host '  $env:GI_TYPELIB_PATH = "C:\gtk\lib\girepository-1.0"'
Write-Host "========================================"
