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
    (Get-FileHash dist/zenshin-windows-x64.zip -Algorithm SHA256).Hash.ToLower() + '  zenshin-windows-x64.zip' |
        Set-Content -Encoding ascii dist/SHA256SUMS.txt
} finally {
    Pop-Location
}
