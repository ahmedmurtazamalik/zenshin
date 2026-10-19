param([string]$Version)
$ErrorActionPreference = 'Stop'
$installer = (Resolve-Path "dist/Zenshin-Setup-$Version-windows-x64.exe").Path
$installDir = Join-Path $env:TEMP "Zenshin installer check $([guid]::NewGuid())"
$shortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Zenshin\Zenshin.lnk'

function Install-Zenshin {
    $process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$installDir`"") -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installation failed: $($process.ExitCode)" }
}

try {
    Install-Zenshin
    if (!(Test-Path $shortcut)) { throw 'Start Menu shortcut is missing' }
    if (!(Test-Path "$installDir/QUICK_START.txt")) { throw 'Setup guide is missing' }
    python scripts/smoke_bundle.py "$installDir/Zenshin.exe" --installed
    if ($LASTEXITCODE -ne 0) { throw 'Installed app failed its smoke check' }
    python scripts/smoke_desktop.py "$installDir/Zenshin.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Desktop window failed its smoke check' }
    $state = Get-Content "$installDir/.local/state.json" -Raw
    Install-Zenshin
    if ((Get-Content "$installDir/.local/state.json" -Raw) -ne $state) { throw 'Reinstall changed saved settings' }
    $process = Start-Process "$installDir/unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw 'Uninstall failed' }
    if ((Test-Path "$installDir/Zenshin.exe") -or (Test-Path "$installDir/Zenshin-bridge.exe") -or (Test-Path $shortcut)) { throw 'Uninstall left app or shortcut behind' }
    if ((Get-Content "$installDir/.local/state.json" -Raw) -ne $state) { throw 'Uninstall removed saved settings' }
    Write-Output 'Installer passed: installation, shortcut, installed app, reinstall, uninstall, and preserved settings.'
} finally {
    if (Test-Path $installDir) { Remove-Item $installDir -Recurse -Force }
}
