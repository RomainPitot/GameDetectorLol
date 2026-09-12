; Installeur Windows pour GameDetectorLol — remplace le "python -m venv / pip install /
; python notifier.py" par un vrai "télécharge, double-clique, installe" : raccourci Menu
; Démarrer, désinstalleur listé dans "Applications", case "Lancer au démarrage de
; Windows", et enregistrement automatique du protocole gamedetectorlol:// (remplace
; l'ancien register_protocol.reg à double-cliquer à la main, qui pointait en plus vers un
; chemin figé — {app} s'adapte à l'endroit réellement choisi à l'installation).
;
; Compiler : ISCC installer.iss (Inno Setup 6, https://jrsoftware.org/isinfo.php)
; Nécessite dist\GameDetectorLol.exe déjà construit (voir README.md — PyInstaller).

#define MyAppName "GameDetectorLol"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "Romain Pitot"
#define MyAppURL "https://romainpitot.github.io/lol-climb-tracker/"
#define MyAppExeName "GameDetectorLol.exe"

[Setup]
AppId={{B8B0F6D0-6C4E-4B8B-9D8E-2E4E7B4E3C1A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
; Installation par utilisateur (pas besoin d'admin) : la plupart des joueurs installent
; League of Legends elles-mêmes sans droits admin, ce companion doit rester aussi simple.
DefaultDirName={autopf}\{#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=GameDetectorLol-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Pas de fichier .ico séparé à maintenir (voir build_tray_icon_image dans notifier.py) —
; l'icône par défaut de l'installeur suffit ici.
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"
Name: "startup"; Description: "Lancer {#MyAppName} au démarrage de Windows"; GroupDescription: "Options :"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
; config.json (avec le token de contrôle à distance) n'est jamais inclus ici — généré au
; tout premier lancement (voir load_config dans notifier.py), jamais écrasé par une
; réinstallation ou une mise à jour ultérieure.

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Remplace register_protocol.reg — même clé, mais {app} s'adapte au vrai dossier
; d'installation plutôt qu'un chemin personnel figé en dur.
Root: HKCU; Subkey: "Software\Classes\gamedetectorlol"; ValueType: string; ValueName: ""; ValueData: "URL:GameDetectorLol Protocol"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\gamedetectorlol"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\gamedetectorlol\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"""
; Case "Lancer au démarrage de Windows" — remplace le raccourci manuel dans shell:startup
; décrit dans l'ancien README.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName} maintenant"; Flags: nowait postinstall skipifsilent
