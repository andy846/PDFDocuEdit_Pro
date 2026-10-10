#ifdef AuthPrivateBuild
  #define MyAppName "PDFDocuEdit Pro Private Auth Test"
#else
  #define MyAppName "PDFDocuEdit Pro"
#endif
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
#ifdef AuthPrivateBuild
  #define MySetupFilename "PDFDocuEdit-Pro-v" + MyAppVersion + "-Private-Auth-Setup-Windows-x64"
#else
  #define MySetupFilename "PDFDocuEdit-Pro-v" + MyAppVersion + "-Setup-Windows-x64"
#endif

[Setup]
#ifdef AuthPrivateBuild
AppId={{78A4BA20-C425-4B80-9360-4F07D06F786D}
#else
AppId={{C17A5D2E-1A04-45D5-95CE-295E1D9884B0}
#endif
AppName={#MyAppName}
; AccountRelease uses the production product identity and empty-folder safety.
; Its initial editor and fixed launcher are both account-bound.
AppVerName={#MyAppName} {#MyAppVersion}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright={#MyAppCopyright}
AppComments={#MyAppDescription}
#ifdef AuthPrivateBuild
DefaultDirName={localappdata}\Programs\PDFDocuEditProPrivateAuthTest
#else
DefaultDirName={localappdata}\Programs\PDFDocuEditPro
#endif
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
#ifdef AuthPrivateBuild
ChangesAssociations=no
#else
ChangesAssociations=yes
#endif
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
#ifndef AuthPrivateBuild
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
#endif

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
