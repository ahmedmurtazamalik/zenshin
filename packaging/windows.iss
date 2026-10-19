#ifndef AppVersion
  #error AppVersion must be supplied by build-windows.ps1
#endif

[Setup]
AppId={{90ED059E-7374-4BEC-A638-2E9142044852}
AppName=Zenshin
AppVersion={#AppVersion}
AppPublisher=Zenshin
DefaultDirName={localappdata}\Programs\Zenshin
DefaultGroupName=Zenshin
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Zenshin-Setup-{#AppVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Zenshin.exe
InfoBeforeFile=QUICK_START.txt
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Zenshin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "QUICK_START.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Zenshin"; Filename: "{app}\Zenshin.exe"; WorkingDir: "{app}"
Name: "{group}\Zenshin setup guide"; Filename: "{app}\QUICK_START.txt"
Name: "{autodesktop}\Zenshin"; Filename: "{app}\Zenshin.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Zenshin.exe"; Description: "Launch Zenshin"; Flags: nowait postinstall skipifsilent
