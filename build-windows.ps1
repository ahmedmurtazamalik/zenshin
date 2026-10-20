param([string]$Version = '')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (!$Version) { $Version = python -c "import updates; print(updates.VERSION)" }
    if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version' }
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name Zenshin `
        --add-data 'index.html:.' --add-data 'assets:assets' `
        --collect-all uiautomation --collect-submodules comtypes app.py
    if ($LASTEXITCODE -ne 0) { throw 'Standalone build failed' }
    python -m PyInstaller --noconfirm --clean --onefile --name Zenshin-bridge zenshin_mcp.py
    if ($LASTEXITCODE -ne 0) { throw 'MCP bridge build failed' }
    python scripts/smoke_bundle.py dist/Zenshin.exe
    if ($LASTEXITCODE -ne 0) { throw 'Standalone smoke check failed' }
    Compress-Archive -Path dist/Zenshin.exe, dist/Zenshin-bridge.exe, packaging/QUICK_START.txt -DestinationPath dist/zenshin-windows-x64.zip -Force
    Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile dist/MicrosoftEdgeWebview2Setup.exe
    $signature = Get-AuthenticodeSignature dist/MicrosoftEdgeWebview2Setup.exe
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw 'WebView2 bootstrapper must have a valid Microsoft signature'
    }
    & "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "/DAppVersion=$Version" packaging/windows.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
    ./scripts/smoke-installer.ps1 -Version $Version
    Get-FileHash dist/zenshin-windows-x64.zip, "dist/Zenshin-Setup-$Version-windows-x64.exe" -Algorithm SHA256 |
        ForEach-Object { $_.Hash.ToLower() + '  ' + (Split-Path $_.Path -Leaf) } |
        Set-Content -Encoding ascii dist/SHA256SUMS.txt
} finally {
    Pop-Location
}
