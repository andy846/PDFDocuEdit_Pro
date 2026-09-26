#define MyAppName "PDFDocuEdit Pro"
#ifndef ManagedVersion
  #error Supply /DManagedVersion from build_managed_installer.py
#endif
#ifndef ManagedStage
  #error Supply /DManagedStage from build_managed_installer.py
#endif
#define MyAppVersion ManagedVersion
#define MyAppPublisher "Andy Leung"
#define MyAppExeName "Launcher.exe"
#define MyAppProgId "PDFDocuEditPro.Managed.Document"
#define MyRegisteredName "PDFDocuEdit Pro Managed"
#define MyAppUserModelId "AndyLeung.PDFDocuEditPro"
#define MyAppDescription "Professional PDF viewing, editing, annotation, conversion, and document tools."
#define MyAppCopyright "Copyright © 2026 Andy Leung. All rights reserved."
#define MySetupFilename "PDFDocuEdit-Pro-v" + MyAppVersion + "-Setup-Windows-x64"

[Setup]
AppId={{C17A5D2E-1A04-45D5-95CE-295E1D9884B0}
AppName={#MyAppName}
AppVerName={#MyAppName} {#MyAppVersion}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright={#MyAppCopyright}
AppComments={#MyAppDescription}
DefaultDirName={localappdata}\Programs\PDFDocuEditPro
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename={#MySetupFilename}
Compression=lzma2/ultra
SolidCompression=yes
SetupIconFile=..\icon.ico
WizardStyle=modern
WizardSizePercent=110
DisableStartupPrompt=yes
DisableWelcomePage=no
SetupLogging=yes
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no
UsePreviousAppDir=no
UsePreviousGroup=yes
UsePreviousTasks=yes
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesAssociations=yes
VersionInfoVersion={#MyAppVersion}
VersionInfoTextVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoCopyright={#MyAppCopyright}
VersionInfoOriginalFileName={#MySetupFilename}.exe
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoProductTextVersion={#MyAppVersion}
#ifdef MySignTool
SignTool={#MySignTool}
SignedUninstaller=yes
SignToolRetryCount=3
SignToolRetryDelay=2000
SignToolRunMinimized=yes
#endif

[Files]
Source: "{#ManagedStage}\PDFDocuEditPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "{#MyAppDescription}"; AppUserModelID: "{#MyAppUserModelId}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "{#MyAppDescription}"; AppUserModelID: "{#MyAppUserModelId}"; Tasks: desktopicon

[Registry]
; Register as an available handler without overriding the user's Windows defaults.
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}"; ValueType: string; ValueData: "{#MyAppName} Document"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}\DefaultIcon"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.ps\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.eps\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty

; Register the managed handler in Default Apps without claiming the generic Launcher.exe name.
Root: HKCU; Subkey: "Software\{#MyRegisteredName}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyRegisteredName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "{#MyAppDescription}"
Root: HKCU; Subkey: "Software\{#MyRegisteredName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyAppProgId}"
Root: HKCU; Subkey: "Software\{#MyRegisteredName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ps"; ValueData: "{#MyAppProgId}"
Root: HKCU; Subkey: "Software\{#MyRegisteredName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".eps"; ValueData: "{#MyAppProgId}"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyRegisteredName}"; ValueData: "Software\{#MyRegisteredName}\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
function NextButtonClick(CurPageID: Integer): Boolean;
var
  InstallRoot: String;
begin
  Result := True;
  if CurPageID <> wpSelectDir then
    Exit;
  InstallRoot := AddBackslash(WizardDirValue);
  if FileExists(InstallRoot + 'state.json') or
     FileExists(InstallRoot + 'PDFDocuEdit Pro.exe') then
  begin
    MsgBox('This folder already contains PDFDocuEdit Pro. Use its updater, or choose an empty folder for a fresh managed installation.', mbError, MB_OK);
    Result := False;
  end;
end;
