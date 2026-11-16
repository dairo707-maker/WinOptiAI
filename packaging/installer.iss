; Inno Setup 6 script for WinOptiAI (for CI/CD or local ISCC builds)
#define MyAppName "WinOptiAI"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "WinOptiAI Open Source"
#define MyAppExeName "WinOptiAI-Portable.exe"

[Setup]
AppId={{8F9D4A1C-3E2B-49A7-9C5D-7F120A98B31E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=WinOptiAI-InnoSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; DestName: "WinOptiAI.exe"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\WinOptiAI.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\WinOptiAI.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WinOptiAI.exe"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
