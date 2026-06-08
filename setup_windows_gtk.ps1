# Setup script: Install GTK runtime for Pango/Cairo support on Windows
# Downloads the gvsbuild GTK3 bundle and installs PyGObject from the bundled wheel.

$ErrorActionPreference = "Stop"
$GTK_DIR = "C:\gtk"
$GTK_ZIP = "$env:TEMP\gtk3.zip"
$BACKEND_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV_PYTHON = Join-Path $BACKEND_DIR "venv\Scripts\python.exe"

# Check if GTK is already installed
if (Test-Path "$GTK_DIR\bin\libpango-1.0-0.dll") {
    Write-Host "GTK runtime already present at $GTK_DIR"
} else {
    Write-Host "Downloading GTK3 bundle (gvsbuild)..."

    # Find latest release from wingtk/gvsbuild
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

    Write-Host "Extracting to $GTK_DIR..."
    if (-not (Test-Path $GTK_DIR)) {
        New-Item -ItemType Directory -Path $GTK_DIR -Force | Out-Null
    }
    Expand-Archive -Path $GTK_ZIP -DestinationPath $GTK_DIR -Force
    Remove-Item $GTK_ZIP -Force
    Write-Host "GTK runtime installed at $GTK_DIR"
}

# Add GTK bin to PATH for this session
$env:Path = "$GTK_DIR\bin;" + $env:Path
$env:GI_TYPELIB_PATH = "$GTK_DIR\lib\girepository-1.0"

# Install PyGObject from bundled wheel
if (Test-Path $VENV_PYTHON) {
    $wheel = Get-ChildItem -Path "$GTK_DIR\wheels" -Filter "pygobject-*.whl" | Select-Object -First 1
    if ($wheel) {
        Write-Host "Installing PyGObject from bundled wheel: $($wheel.Name)"
        & $VENV_PYTHON -m pip install "$($wheel.FullName)"
    } else {
        Write-Host "No PyGObject wheel found in bundle, trying pip..."
        & $VENV_PYTHON -m pip install pygobject
    }
} else {
    Write-Host "Virtual environment not found at $VENV_PYTHON"
    Write-Host "Please create it first: python -m venv venv"
}

Write-Host ""
Write-Host "GTK setup complete!"
Write-Host "Add these to your environment or run before starting the app:"
Write-Host '  $env:Path = "C:\gtk\bin;" + $env:Path'
Write-Host '  $env:GI_TYPELIB_PATH = "C:\gtk\lib\girepository-1.0"'
