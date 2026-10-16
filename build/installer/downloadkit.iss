[Setup]
AppName=downloadkit
AppVersion=0.7.0
AppPublisher=downloadkit
AppPublisherURL=https://github.com/an-qiong1/downloadkit
DefaultDirName={localappdata}\Programs\downloadkit
DefaultGroupName=downloadkit
OutputDir=..\..\dist
OutputBaseFilename=downloadkit-setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=..\..\downloadkit.ico
UninstallDisplayIcon={app}\downloadkit.exe
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; onefile: single self-contained EXE (Python + deps + static frontend all embedded)
Source: "..\..\dist\downloadkit.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\downloadkit"; Filename: "{app}\downloadkit.exe"; WorkingDir: "{app}"
Name: "{commondesktop}\downloadkit"; Filename: "{app}\downloadkit.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall downloadkit"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\downloadkit.exe"; Description: "Launch downloadkit"; Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /f /im downloadkit.exe 2>nul"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
