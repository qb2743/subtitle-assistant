; Inno Setup - Subtitle Assistant 1.0
; Prerequisite: run packaging/scripts/build_pyinstaller.ps1
; Install Inno Setup 6 from https://jrsoftware.org/isinfo.php

#define MyAppName "字幕助手"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "qb2743"
#define MyAppURL "https://github.com/qb2743/subtitle-assistant"
#define MyAppExeName "字幕助手.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-SUBTITLEASSIST01}
SetupIconFile=..\..\resource\assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=SubtitleAssistant-{#MyAppVersion}-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
Source: "..\..\dist\字幕助手\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent