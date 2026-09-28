$ErrorActionPreference = 'Stop'
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onedir --name ChartOrganizer launcher.py
Write-Host "Built dist\ChartOrganizer\ChartOrganizer.exe"
