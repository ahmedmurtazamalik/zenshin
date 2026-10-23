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
UninstallDisplayIcon={app}\zenshin.ico
InfoBeforeFile=QUICK_START.txt
CloseApplications=yes
CloseApplicationsFilter=Zenshin.exe,Zenshin-bridge.exe
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\assets\zenshin.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Zenshin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Zenshin-bridge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy
Source: "QUICK_START.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Zenshin"; Filename: "{app}\Zenshin.exe"; WorkingDir: "{app}"; IconFilename: "{app}\zenshin.ico"; AppUserModelID: "Zenshin.Desktop"
Name: "{group}\Zenshin setup guide"; Filename: "{app}\QUICK_START.txt"
Name: "{autodesktop}\Zenshin"; Filename: "{app}\Zenshin.exe"; WorkingDir: "{app}"; IconFilename: "{app}\zenshin.ico"; AppUserModelID: "Zenshin.Desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\Zenshin.exe"; Parameters: "--repair-registration"; Description: "Launch Zenshin and connect Codex tools"; Flags: nowait postinstall skipifsilent; Check: not IsUpdate
Filename: "{app}\Zenshin.exe"; Parameters: "--repair-registration --finish-update --port {param:PORT|8765} --state ""{param:STATE|{app}\.local\state.json}"""; Description: "Finish update and reconnect Codex (restarts Codex)"; Flags: nowait postinstall; Check: FinishUpdate

[Code]
var
  UpdateFinishChoice: Integer;

function SetEnvironmentVariable(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function InitializeSetup: Boolean;
begin
  // Older updaters pass their onefile runtime to Setup. Reopen independently
  // after that app exits and its extraction directory has been removed.
  Result := SetEnvironmentVariable('PYINSTALLER_RESET_ENVIRONMENT', '1');
end;

function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function FinishUpdate: Boolean;
begin
  Result := IsUpdate;
  // v0.2.16 launches Setup in silent mode, which has no Finish page.
  // Keep one visible completion button for that already-shipped updater.
  if Result and WizardSilent then begin
    if UpdateFinishChoice = 0 then
      UpdateFinishChoice := SuppressibleMsgBox('Zenshin is installed. Click OK to finish the update: restart Codex, reconnect Zenshin, and restore its previous monitoring state. Running Codex work will be interrupted.', mbInformation, MB_OKCANCEL, IDOK);
    Result := UpdateFinishChoice = IDOK;
  end;
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
  Locator, Services, Processes, Process: Variant;
  Index: Integer;
begin
  Result := '';
  if not WebView2Installed then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := 'Could not start Microsoft WebView2 setup. Check your internet connection and try again.'
    else if not WebView2Installed then
      Result := 'Microsoft WebView2 Runtime could not be installed. Connect to the internet, install WebView2 Runtime from Microsoft, and try again.';
  end;
  if Result = '' then begin
    // Restart Manager can close the Python child but leave its onefile loader
    // holding Codex's MCP pipes open. Close the whole installed bridge tree.
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Services := Locator.ConnectServer('', 'root\CIMV2');
    Processes := Services.ExecQuery(
      'SELECT ExecutablePath, ProcessId FROM Win32_Process WHERE Name = ''Zenshin-bridge.exe''');
    for Index := 0 to Processes.Count - 1 do begin
      Process := Processes.ItemIndex(Index);
      if not VarIsNull(Process.ExecutablePath) then
        if CompareText(Process.ExecutablePath, ExpandConstant('{app}\Zenshin-bridge.exe')) = 0 then
          Exec(ExpandConstant('{sys}\taskkill.exe'), '/PID ' + IntToStr(Process.ProcessId) + ' /T /F',
            '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;
