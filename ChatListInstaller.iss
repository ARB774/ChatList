#include "build_assets\installer_defines.iss"

[Setup]
AppId={{8F06D6D5-5ED5-4CE5-9157-988B4F4FC9BD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=ChatList
AppPublisherURL=https://github.com/ARB774/ChatList
AppSupportURL=https://github.com/ARB774/ChatList
AppUpdatesURL=https://github.com/ARB774/ChatList
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyInstallerBaseName}
SetupIconFile=app_green.ico
UninstallDisplayIcon={app}\ChatListApp.exe
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные задачи:"

[Files]
Source: "{#MyAppExeSource}"; DestDir: "{app}"; DestName: "ChatListApp.exe"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\ChatListApp.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\ChatListApp.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ChatListApp.exe"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
