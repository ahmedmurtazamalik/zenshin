param([string]$Version = '0.2.2')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python -m PyInstaller --noconfirm --clean --onefile --name Zenshin `
        --add-data 'index.html:.' --add-data 'assets:assets' `
        --collect-all uiautomation --collect-submodules comtypes app.py
    if ($LASTEXITCODE -ne 0) { throw 'Standalone build failed' }
    python scripts/smoke_bundle.py dist/Zenshin.exe
    if ($LASTEXITCODE -ne 0) { throw 'Standalone smoke check failed' }
    Compress-Archive -Path dist/Zenshin.exe -DestinationPath dist/zenshin-windows-x64.zip -Force
    & "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "/DAppVersion=$Version" packaging/windows.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
    ./scripts/smoke-installer.ps1 -Version $Version
    Get-FileHash dist/zenshin-windows-x64.zip, "dist/Zenshin-Setup-$Version-windows-x64.exe" -Algorithm SHA256 |
        ForEach-Object { $_.Hash.ToLower() + '  ' + (Split-Path $_.Path -Leaf) } |
        Set-Content -Encoding ascii dist/SHA256SUMS.txt
} finally {
    Pop-Location
}
