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
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Zenshin-Setup-{#AppVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\zenshin.ico
UninstallDisplayIcon={app}\Zenshin.exe
InfoBeforeFile=QUICK_START.txt
CloseApplications=yes
CloseApplicationsFilter=Zenshin.exe,Zenshin-bridge.exe
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Zenshin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Zenshin-bridge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy
Source: "QUICK_START.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Zenshin"; Filename: "{app}\Zenshin.exe"; WorkingDir: "{app}"
Name: "{group}\Zenshin setup guide"; Filename: "{app}\QUICK_START.txt"
Name: "{autodesktop}\Zenshin"; Filename: "{app}\Zenshin.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Zenshin.exe"; Parameters: "--repair-registration"; Description: "Launch Zenshin and connect Codex tools"; Flags: nowait postinstall skipifsilent; Check: not IsUpdate
Filename: "{app}\Zenshin.exe"; Parameters: "--repair-registration --port {param:PORT|8765} --state ""{param:STATE|{app}\.local\state.json}"""; Flags: nowait; Check: IsUpdate

[Code]
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function WebView2Installed: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKLM32, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
  if not Result then
    Result := (RegQueryStringValue(HKCU, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if not WebView2Installed then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := 'Could not start Microsoft WebView2 setup. Check your internet connection and try again.'
    else if not WebView2Installed then
      Result := 'Microsoft WebView2 Runtime could not be installed. Connect to the internet, install WebView2 Runtime from Microsoft, and try again.';
  end;
end;
