; Inno Setup script — 字幕助手 1.0.0
; 用法: ISCC.exe "packaging/字幕助手.iss"
; 依赖: 先用 build_pyinstaller.ps1 生成 dist/字幕助手/

#define MyAppName "字幕助手"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "qb2743"
#define MyAppExeName "字幕助手.exe"
#define MyAppAssocName MyAppName + " 文件"
#define MyAppAssocExt ".srt"
#define MyAppAssocKey StringChange(MyAppName, " ", "") + MyAppAssocExt

[Setup]
; 所有相对路径以项目根为基准（.iss 位于 packaging/ 下）
SourceDir=..
; 高版本 Windows 10+ 可用，避免警告
AppId={{B7A4E3C2-9F1D-4E8B-A5C6-1F2E3D4C5B6A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 使用 dist 里的 ico
SetupIconFile=resource\assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=dist\installer
OutputBaseFilename=字幕助手_Setup_1.0.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; 关联 .srt 文件（可选）
ChangesAssociations=no
; 单语言：简体中文
ShowLanguageDialog=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 把 PyInstaller 产物整个目录打进安装包
Source: "dist\字幕助手\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram, {#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 清理用户数据目录（settings/cache/logs）—— 静默卸载时一并删除
Type: filesandordirs; Name: "{userappdata}\{#MyAppName}"
