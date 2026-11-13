#define AppName "PC to Phone"
#define AppExe "PC2Phone.exe"
#define AppVersion "1.0.0"

[Setup]
AppId={{6F0D8E1B-3C52-4D8A-9B7E-2A5C41F7D9E3}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=talls2
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=admin
OutputDir=output
OutputBaseFilename=PC2Phone-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "build\dist\PC2Phone\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""PC to Phone"" dir=in action=allow program=""{app}\{#AppExe}"" profile=private enable=yes"; Flags: runhidden; StatusMsg: "Allowing the app through the firewall (private networks)..."
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""PC to Phone"""; Flags: runhidden; RunOnceId: "RemoveFirewallRule"
