param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$ProjectRoot\build", "$ProjectRoot\dist", "$ProjectRoot\ZIA-Backup-Restore.spec"
}

$PackageDir = Join-Path $ProjectRoot "dist\ZIA-Backup-Restore-Windows"
$ZipPath = Join-Path $ProjectRoot "dist\ZIA-Backup-Restore-Windows.zip"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $PackageDir
Remove-Item -Force -ErrorAction SilentlyContinue $ZipPath
Remove-Item -Force -ErrorAction SilentlyContinue "$ProjectRoot\dist\ZIA-Backup-Restore.exe"

python -m pip install --upgrade pip pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "ZIA-Backup-Restore" zia_cloner_app.py

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $PackageDir
Remove-Item -Force -ErrorAction SilentlyContinue $ZipPath
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
Copy-Item -Force "$ProjectRoot\dist\ZIA-Backup-Restore.exe" "$PackageDir\ZIA-Backup-Restore.exe"
Copy-Item -Force "$ProjectRoot\WINDOWS_USER_GUIDE.txt" "$PackageDir\README.txt"
Compress-Archive -Path "$PackageDir\*" -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Built: $ProjectRoot\dist\ZIA-Backup-Restore.exe"
Write-Host "Package: $ZipPath"
