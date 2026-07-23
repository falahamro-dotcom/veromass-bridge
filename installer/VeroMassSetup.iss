; VeroMass Desktop Bridge + Aligner installer.
;
; Installs to %LOCALAPPDATA%\VeroMassBridge\app — same no-admin-required
; philosophy as everything else in this repo (register_scheme.py/auth.py's
; DPAPI use HKEY_CURRENT_USER, never HKEY_LOCAL_MACHINE). This is why
; PrivilegesRequired is "lowest", not "admin" — a scientist installing
; this on a locked-down lab machine shouldn't need IT involved.
;
; Post-install runs "VeroMass_Bridge.exe --register-scheme" once, so a
; customer never has to open a terminal — that's the whole point of this
; installer existing at all.
;
; Build with: ISCC VeroMassSetup.iss
; (expects ..\dist\VeroMass_Bridge\ and the aligner repo's ..\..\veromass-aligner\dist\VeroMass_Aligner.exe
; to already exist — see build_installer.ps1 in this same folder, which
; builds both frozen exes fresh before compiling this script.)

#define MyAppName "VeroMass Desktop Bridge"
#define MyAppVersion "0.2.1"
#define MyAppPublisher "VeroMass"
#define MyAppURL "https://app.veromass.com"

[Setup]
AppId={{8F2C9E1A-6B3D-4E5F-9A1B-2C3D4E5F6A7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\VeroMassBridge\app
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
OutputBaseFilename=VeroMassBridgeSetup-{#MyAppVersion}
OutputDir=output
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\VeroMass_Bridge.exe
WizardStyle=modern

[Files]
Source: "..\dist\VeroMass_Bridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\veromass-aligner\dist\VeroMass_Aligner.exe"; DestDir: "{app}"; Flags: ignoreversion

[Run]
; Registers the veromass:// URI scheme for THIS Windows user
; (HKEY_CURRENT_USER — see register_scheme.py). Runs hidden and waits for
; it to finish before the installer's own "Finished" page appears, so a
; customer never sees a flash of anything.
Filename: "{app}\VeroMass_Bridge.exe"; Parameters: "--register-scheme"; Flags: runhidden waituntilterminated

[UninstallRun]
; Best-effort cleanup — if this fails for any reason (e.g. the key was
; already removed by hand), the uninstall itself must not fail because
; of it, hence "skipifdoesntexist" is not enough alone; runhidden hides
; any transient window and we don't otherwise gate uninstall success on
; this succeeding.
Filename: "reg.exe"; Parameters: "delete HKCU\Software\Classes\veromass /f"; Flags: runhidden skipifdoesntexist waituntilterminated; RunOnceId: "RemoveVeromassScheme"
