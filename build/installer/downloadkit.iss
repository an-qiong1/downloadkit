[Setup]
AppName=downloadkit
AppVersion=1.0.0
AppPublisher=downloadkit
DefaultDirName={autopf}\downloadkit
DefaultGroupName=downloadkit
OutputDir=..\..\dist
OutputBaseFilename=downloadkit-setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\downloadkit.exe
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; PyInstaller build output (all files from onedir)
Source: "..\..\dist\downloadkit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Static frontend files
Source: "..\..\downloadkit\static\*"; DestDir: "{app}\downloadkit\static"; Flags: ignoreversion recursesubdirs createallsubdirs

; (no templates directory - SPA frontend is served from static/)

[Icons]
Name: "{group}\downloadkit"; Filename: "{app}\downloadkit.exe"; WorkingDir: "{app}"
Name: "{commondesktop}\downloadkit"; Filename: "{app}\downloadkit.exe"; WorkingDir: "{app}"
Name: "{group}\卸载 downloadkit"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\downloadkit.exe"; Description: "启动 downloadkit"; Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /f /im downloadkit.exe 2>nul"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
