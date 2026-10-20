param([string]$Version)
$ErrorActionPreference = 'Stop'
$installer = (Resolve-Path "dist/Zenshin-Setup-$Version-windows-x64.exe").Path
$installDir = Join-Path $env:TEMP "Zenshin installer check $([guid]::NewGuid())"
$shortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Zenshin\Zenshin.lnk'

function Install-Zenshin {
    $process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$installDir`"") -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installation failed: $($process.ExitCode)" }
}

function Assert-ZenshinShortcut {
    if (!(Test-Path $shortcut)) { throw 'Start Menu shortcut is missing' }
    $iconPath = Join-Path $installDir 'zenshin.ico'
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    if ($link.IconLocation -ne "$iconPath,0") { throw 'Start Menu shortcut does not use the installed Zenshin icon' }
    $item = (New-Object -ComObject Shell.Application).NameSpace((Split-Path $shortcut)).ParseName((Split-Path $shortcut -Leaf))
    if ($item.ExtendedProperty('System.AppUserModel.ID') -ne 'Zenshin.Desktop') { throw 'Start Menu shortcut has the wrong application identity' }
    Add-Type -AssemblyName System.Drawing
    # Both shell-resolved icons include the normal shortcut arrow overlay.
    $referencePath = Join-Path $installDir 'icon-reference.lnk'
    $reference = (New-Object -ComObject WScript.Shell).CreateShortcut($referencePath)
    $reference.TargetPath = Join-Path $installDir 'Zenshin.exe'
    $reference.IconLocation = "$iconPath,0"
    $reference.Save()
    $actual = [System.Drawing.Icon]::ExtractAssociatedIcon($shortcut)
    $expected = [System.Drawing.Icon]::ExtractAssociatedIcon($referencePath)
    $actualBitmap, $expectedBitmap = $actual.ToBitmap(), $expected.ToBitmap()
    try {
        for ($x = 0; $x -lt $actual.Width; $x++) {
            for ($y = 0; $y -lt $actual.Height; $y++) {
                if ($actualBitmap.GetPixel($x, $y).ToArgb() -ne $expectedBitmap.GetPixel($x, $y).ToArgb()) {
                    throw 'Start Menu shortcut resolves to an icon other than the Zenshin logo'
                }
            }
        }
    } finally {
        $actualBitmap.Dispose()
        $expectedBitmap.Dispose()
        $actual.Dispose()
        $expected.Dispose()
        Remove-Item -LiteralPath $referencePath
    }
}

try {
    Install-Zenshin
    Assert-ZenshinShortcut
    if (!(Test-Path "$installDir/QUICK_START.txt")) { throw 'Setup guide is missing' }
    python scripts/smoke_bundle.py "$installDir/Zenshin.exe" --installed
    if ($LASTEXITCODE -ne 0) { throw 'Installed app failed its smoke check' }
    python scripts/smoke_desktop.py "$installDir/Zenshin.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Desktop window failed its smoke check' }
    $state = Get-Content "$installDir/.local/state.json" -Raw
    Install-Zenshin
    Assert-ZenshinShortcut
    if ((Get-Content "$installDir/.local/state.json" -Raw) -ne $state) { throw 'Reinstall changed saved settings' }
    python scripts/smoke_desktop.py "$installDir/Zenshin.exe" $installer
    if ($LASTEXITCODE -ne 0) { throw 'In-place update with loaded MCP bridge failed' }
    Assert-ZenshinShortcut
    if ((Get-Content "$installDir/.local/state.json" -Raw) -ne $state) { throw 'Update changed saved settings' }
    $process = Start-Process "$installDir/unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw 'Uninstall failed' }
    if ((Test-Path "$installDir/Zenshin.exe") -or (Test-Path "$installDir/Zenshin-bridge.exe") -or (Test-Path $shortcut)) { throw 'Uninstall left app or shortcut behind' }
    if ((Get-Content "$installDir/.local/state.json" -Raw) -ne $state) { throw 'Uninstall removed saved settings' }
    Write-Output 'Installer passed: installation, Zenshin shortcut icon and identity, installed app, reinstall, uninstall, and preserved settings.'
} finally {
    if (Test-Path $installDir) { Remove-Item $installDir -Recurse -Force }
}
