; installer/AntiMatter.iss
; Inno Setup script for Anti Matter — bundles the PyInstaller onedir build
; and registers/unregisters Explorer context-menu entries via the packaged
; exe's own --register/--unregister mode (see registration.py). No-admin
; end-to-end: per-user install dir + PrivilegesRequired=lowest + HKCU-only
; registry writes.

[Setup]
AppName=Anti Matter
AppVersion=1.0.1
AppPublisher=Anti Matter
DefaultDirName={localappdata}\Programs\Anti Matter
DefaultGroupName=Anti Matter
PrivilegesRequired=lowest
OutputDir=..\dist_installer
OutputBaseFilename=AntiMatterSetup
Compression=lzma2
SolidCompression=yes
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\AntiMatter.exe

[Files]
Source: "..\dist\AntiMatter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Anti Matter"; Filename: "{app}\AntiMatter.exe"
Name: "{group}\Uninstall Anti Matter"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\AntiMatter.exe"; Parameters: "--register"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Registering Explorer integration..."
Filename: "{app}\AntiMatter.exe"; Description: "Launch Anti Matter"; \
    Flags: postinstall nowait skipifsilent unchecked

[UninstallRun]
Filename: "{app}\AntiMatter.exe"; Parameters: "--unregister"; \
    Flags: runhidden waituntilterminated
