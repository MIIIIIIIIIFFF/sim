#define MyAppName "Overnight Edge"
#define MyAppVersion "3.0.0"
#define MyAppPublisher "Overnight Edge"
#define MyAppExeName "OvernightEdge.exe"

[Setup]
AppId={{8F3C1A2E-9B74-4D11-A6E8-OVERNIGHTEDGE23}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Overnight Edge
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE.txt
OutputDir=..\dist\GiveToBoss
OutputBaseFilename=OvernightEdgeSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\OvernightEdge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\FOR_THE_BOSS.md"; DestDir: "{app}"; DestName: "READ_ME_FIRST.txt"; Flags: ignoreversion
Source: "..\EXECUTIVE_BRIEF.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Overnight Edge"; Flags: nowait postinstall skipifsilent
