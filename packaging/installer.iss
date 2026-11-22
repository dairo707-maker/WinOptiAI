; Inno Setup 6 script for WinOptiAI — Multilingual Dual-Mode Windows Installer Wizard
#ifndef MyAppVersion
  #define MyAppVersion "0.6.5"
#endif

#define MyAppName "WinOptiAI"
#define MyAppPublisher "TRODAI (Dairo · dairo707-maker) - WinOptiAI Open Source"
#define MyAppURL "https://github.com/dairo707-maker/WinOptiAI"
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
AppUpdatesURL={#MyAppURL}/releases
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
AllowNoIcons=yes
DisableProgramGroupPage=no
DefaultGroupName={#MyAppName}
LicenseFile=..\LICENSE
SetupIconFile=..\assets\icons\winoptiai.ico
WizardImageFile=..\assets\icons\wizard_large.bmp
WizardSmallImageFile=..\assets\icons\wizard_small.bmp
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesAssociations=yes
UninstallDisplayName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=WinOptiAI-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "pt_br"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"

[CustomMessages]
es.DesktopIcon=Crear un acceso directo en el Escritorio
en.DesktopIcon=Create a Desktop shortcut
pt_br.DesktopIcon=Criar um atalho na Area de Trabalho
pt.DesktopIcon=Criar um atalho no Ambiente de Trabalho

es.StartMenuIcon=Crear acceso directo en el Menu Inicio
en.StartMenuIcon=Create Start Menu shortcut
pt_br.StartMenuIcon=Criar atalho no Menu Iniciar
pt.StartMenuIcon=Criar atalho no Menu Iniciar

es.ShortcutsGroup=Accesos directos:
en.ShortcutsGroup=Shortcuts:
pt_br.ShortcutsGroup=Atalhos:
pt.ShortcutsGroup=Atalhos:

es.AutoStartTask=Iniciar WinOptiAI minimizado en la bandeja al arrancar Windows
en.AutoStartTask=Start WinOptiAI minimized to system tray on Windows startup
pt_br.AutoStartTask=Iniciar WinOptiAI minimizado na bandeja ao iniciar o Windows
pt.AutoStartTask=Iniciar WinOptiAI minimizado na bandeja ao arrancar o Windows

es.SreGroup=Automatizacion SRE:
en.SreGroup=SRE Automation:
pt_br.SreGroup=Automacao SRE:
pt.SreGroup=Automacao SRE:

es.LaunchNow=Ejecutar {#MyAppName} ahora
en.LaunchNow=Launch {#MyAppName} now
pt_br.LaunchNow=Executar {#MyAppName} agora
pt.LaunchNow=Executar {#MyAppName} agora

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:ShortcutsGroup}"
Name: "startmenuicon"; Description: "{cm:StartMenuIcon}"; GroupDescription: "{cm:ShortcutsGroup}"
Name: "autostart"; Description: "{cm:AutoStartTask}"; GroupDescription: "{cm:SreGroup}"; Flags: unchecked

[Files]
Source: "{#SourcePortableExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\INSTALL_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\BIOS_AND_THERMAL_GUIDE_LENOVO_82FE.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; AppUserModelID: "TRODAI.WinOptiAI"
Name: "{group}\INSTALL_GUIDE"; Filename: "{app}\docs\INSTALL_GUIDE.md"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; AppUserModelID: "TRODAI.WinOptiAI"; Tasks: desktopicon
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; AppUserModelID: "TRODAI.WinOptiAI"; Tasks: startmenuicon

[Registry]
; Sync installer language to HKCU so WinOptiAI launches in the same language
Root: HKCU; Subkey: "Software\WinOptiAI"; ValueType: string; ValueName: "Language"; ValueData: "{language}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; v0.6.1: refrescar la cache de iconos de Windows para que barra de tareas e Inicio muestren el icono nuevo.
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden skipifdoesntexist
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\docs"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /T /IM WinOptiAI.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
  Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq WinOptiAI.exe" | find /I "WinOptiAI.exe" >nul', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if ResultCode = 0 then
    Result := 'WinOptiAI sigue activo (probablemente ejecutandose como Administrador en la bandeja del reloj). Haga clic derecho en su icono junto al reloj -> "Salir de WinOptiAI", o ejecute este instalador como Administrador y vuelva a intentarlo.'
  else
    Result := '';
end;
