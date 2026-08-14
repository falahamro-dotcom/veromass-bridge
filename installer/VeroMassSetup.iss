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
; Also starts a background "--watch" instance immediately after install AND
; registers a per-user Startup-folder entry so it auto-starts on every
; login from then on ({userstartup} — HKCU-equivalent, no admin needed,
; same no-admin philosophy as everything else here). Before this, Bridge
; only ever ran the FIRST time a scientist actually clicked "Process
; locally" — meaning GET /health (app.veromass.com's pre-flight check for
; "is Bridge installed") had no way to say yes on a fresh install that had
; never been used yet, since nothing was listening on 127.0.0.1:58765 until
; then. Keeping a watcher running continuously closes that gap for real,
; the same way Dropbox/similar background-sync tools stay running rather
; than only starting the moment they're needed.
;
; Build with: ISCC VeroMassSetup.iss
; (expects ..\dist\VeroMass_Bridge\ and the aligner repo's ..\..\veromass-aligner\dist\VeroMass_Aligner.exe
; to already exist — see build_installer.ps1 in this same folder, which
; builds both frozen exes fresh before compiling this script.)

#define MyAppName "VeroMass Desktop Bridge"
#define MyAppVersion "0.3.4"
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

[Icons]
; Per-user Startup-folder entry so the Bridge watcher auto-starts on every
; login from now on — {userstartup} is a normal shell:startup shortcut,
; no admin/Task Scheduler needed. --windowed build has no console for any
; argument combination, so this is invisible either way.
Name: "{userstartup}\VeroMass Bridge"; Filename: "{app}\VeroMass_Bridge.exe"; Parameters: "--watch"; IconFilename: "{app}\VeroMass_Bridge.exe"

[Run]
; Registers the veromass:// URI scheme for THIS Windows user
; (HKEY_CURRENT_USER — see register_scheme.py). Runs hidden and waits for
; it to finish before the installer's own "Finished" page appears, so a
; customer never sees a flash of anything.
Filename: "{app}\VeroMass_Bridge.exe"; Parameters: "--register-scheme"; Flags: runhidden waituntilterminated
; Starts the background watcher right away, not just registers it for NEXT
; login — "nowait" so the installer's Finished page doesn't sit waiting on
; a process that runs forever by design. Unconditional (no "postinstall"
; checkbox flag) — this should always happen, not be an optional launch.
Filename: "{app}\VeroMass_Bridge.exe"; Parameters: "--watch"; Flags: runhidden nowait

[UninstallRun]
; Best-effort cleanup — if this fails for any reason (e.g. the key was
; already removed by hand), the uninstall itself must not fail because
; of it, hence "skipifdoesntexist" is not enough alone; runhidden hides
; any transient window and we don't otherwise gate uninstall success on
; this succeeding.
Filename: "reg.exe"; Parameters: "delete HKCU\Software\Classes\veromass /f"; Flags: runhidden skipifdoesntexist waituntilterminated; RunOnceId: "RemoveVeromassScheme"
