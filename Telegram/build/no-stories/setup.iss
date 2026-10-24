#ifndef PackageDir
  #error PackageDir must point to the prepared package.
#endif
#ifndef OutputDir
  #error OutputDir must point to the artifact folder.
#endif
#ifndef PackageVersion
  #error PackageVersion is required.
#endif
#ifndef PackageName
  #error PackageName is required.
#endif

[Setup]
AppId={{08DF0784-3B6C-44C3-8CBC-A7764CDB3C9E}
AppName=Telegram No Stories
AppVersion={#PackageVersion}
AppPublisher=mennya
AppPublisherURL=https://github.com/mennya/tdesktop-no-stories
DefaultDirName={localappdata}\Programs\Telegram No Stories
DefaultGroupName=Telegram No Stories
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableDirPage=no
UninstallDisplayIcon={app}\Telegram.exe
OutputDir={#OutputDir}
OutputBaseFilename={#PackageName}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no

[Languages]
Name: english; MessagesFile: compiler:Default.isl
Name: russian; MessagesFile: compiler:Languages\Russian.isl

[Tasks]
Name: desktopicon; Description: {cm:CreateDesktopIcon}; Flags: unchecked

[Dirs]
Name: {app}\TelegramForcePortable; Flags: uninsneveruninstall

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\Telegram No Stories; Filename: {app}\Telegram.exe; WorkingDir: {app}
Name: {userdesktop}\Telegram No Stories; Filename: {app}\Telegram.exe; WorkingDir: {app}; Tasks: desktopicon
