; Inno Setup 6 Installer Script for PakPharma POS & Medical Store Management System
; Compiles dist\PakPharmaPOS into a single-file Windows 10/11 Setup Wizard (PakPharmaPOS_Setup_v1.0.0.exe)
; Preserves %LOCALAPPDATA%\PakPharmaPOS database and backups during upgrades and uninstalls.

#define MyAppName "PakPharma POS & Medical Store Management System"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "PakPharma Retail Systems Pakistan"
#define MyAppExeName "PakPharmaPOS.exe"

[Setup]
AppId={{8F9E4A2B-6C1D-4E8F-9A3B-7D2C5E1F0A9B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PakPharmaPOS
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=PakPharmaPOS_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PakPharmaPOS\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\PakPharmaPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Create persistent user data and backup directories that are NEVER deleted on upgrade or uninstall
Name: "{localappdata}\PakPharmaPOS\data"; Flags: uninsneveruninstall
Name: "{localappdata}\PakPharmaPOS\backups"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
