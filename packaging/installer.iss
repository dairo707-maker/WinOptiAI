; Inno Setup 6 script for WinOptiAI — Dual-Mode Windows Installer Wizard
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "WinOptiAI"
#define MyAppPublisher "WinOptiAI Open Source"
#define MyAppURL "https://github.com/dairo/WinOptiAI"
#define MyAppExeName "WinOptiAI.exe"
#define SourcePortableExe "..\dist\WinOptiAI-Portable.exe"

[Setup]
AppId={{8F9D4A1C-3E2B-49A7-9C5D-7F120A98B31E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
; Dual mode: user chooses "Solo para mi" (%LOCALAPPDATA%\Programs\WinOptiAI)
; or "Todos los usuarios" (C:\Program Files\WinOptiAI) and can browse any directory
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
AllowNoIcons=yes
DisableProgramGroupPage=no
DefaultGroupName={#MyAppName}
LicenseFile=..\LICENSE
SetupIconFile=..\assets\icons\winoptiai.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=WinOptiAI-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos:"
Name: "startmenuicon"; Description: "Crear acceso directo en el Menu Inicio"; GroupDescription: "Accesos directos:"
Name: "autostart"; Description: "Iniciar WinOptiAI minimizado en la bandeja al arrancar Windows"; GroupDescription: "Automatizacion SRE:"; Flags: unchecked

[Files]
Source: "{#SourcePortableExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\INSTALL_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\BIOS_AND_THERMAL_GUIDE_LENOVO_82FE.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Guia de Instalacion"; Filename: "{app}\docs\INSTALL_GUIDE.md"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon

[Registry]
; Optional minimized startup in user Run key (only if user checks autostart task)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName} ahora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\docs"
