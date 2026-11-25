$ErrorActionPreference = 'Stop'
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onedir --name ChartOrganizer launcher.py
$appDir = "dist\ChartOrganizer"
Copy-Item "README.md" -Destination (Join-Path $appDir "README.md") -Force
$version = (python -c "from chartorganizer import __version__; print(__version__)" 2>$null)
if (-not $version) { $version = '0.1.0' }
$archive = "dist\ChartOrganizer-$version-windows-x64.zip"
Compress-Archive -Path "$appDir\*" -DestinationPath $archive -Force
Write-Host "Built dist\ChartOrganizer\ChartOrganizer.exe"
Write-Host "Created $archive"
