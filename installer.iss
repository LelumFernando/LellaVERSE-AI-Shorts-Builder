; ======================================================================
; LellaVERSE AI Shorts Builder - Inno Setup Script
; Version: 1.0.0
; Author: Lelum Anuradha Fernando (LellaVERSE)
; ======================================================================

#define MyAppName "LellaVERSE AI Shorts Builder"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Lelum Anuradha Fernando (LellaVERSE)"
#define MyAppURL "https://github.com/LelumFernando"
#define MyAppExeName "LellaVERSE.exe"

[Setup]
AppId={{9F7B183E-812C-426F-A029-79730D35914E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE
InfoBeforeFile=INSTALLATION_GUIDE.md
OutputDir=dist
OutputBaseFilename=LellaVERSE_AI_Shorts_Builder_v1.0.0_Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Main executable launcher and batch launchers
Source: "LellaVERSE.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "Run_LellaVerse.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "open_browser.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "Create_Desktop_Shortcut.bat"; DestDir: "{app}"; Flags: ignoreversion

; Core Python Application Files
Source: "app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "video_editor.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "gemini_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "subtitle_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "pipeline.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "downloader.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "sfx.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "color_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "ai_analyzer.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "maintenance.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "make_assets.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "test_suite.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "settings.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

; Configuration & Documentation
Source: ".streamlit\*"; DestDir: "{app}\.streamlit"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "INSTALLATION_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion

; Assets & CNN Models
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs

; Bundled FFmpeg Binaries
Source: "bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

; Pre-configured Python Runtime Environment
Source: "venv\*"; DestDir: "{app}\venv"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"

[Dirs]
Name: "{app}\temp"; Permissions: users-full
Name: "{app}\outputs"; Permissions: users-full
Name: "{app}\workspace"; Permissions: users-full

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\Documentation"; Filename: "{app}\INSTALLATION_GUIDE.md"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
