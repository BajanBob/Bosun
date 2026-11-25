; Inno Setup script for the Bosun Windows desktop installer.
; Per-user install: no administrator rights needed.
#define AppVersion GetEnv("BOSUN_VERSION")

[Setup]
AppId={{6F1B2C2E-9C1E-4C8E-B7A5-5B0D7E2B05A1}
AppName=Bosun
AppVersion={#AppVersion}
AppPublisher=BajanBob
AppPublisherURL=https://github.com/BajanBob/Bosun
DefaultDirName={localappdata}\Programs\Bosun
DefaultGroupName=Bosun
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\installer
OutputBaseFilename=Bosun-Windows-Desktop-Setup
SetupIconFile=bosun.ico
UninstallDisplayIcon={app}\Bosun.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\Bosun\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\dist\bosun-cli.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\Bosun"; Filename: "{app}\Bosun.exe"
Name: "{group}\Bosun Faceplate (touch screen)"; Filename: "{app}\Bosun.exe"; Parameters: "--faceplate --full-screen"
Name: "{group}\Uninstall Bosun"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Bosun"; Filename: "{app}\Bosun.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Bosun.exe"; Description: "Launch Bosun"; Flags: nowait postinstall skipifsilent
