; Інсталятор URBAN (Inno Setup 6). Збирати: build.ps1 (спершу PyInstaller → dist\URBAN, потім цей сценарій).
; Створено 27.11.2026 (CLAUDE); код — G:\URBAN\URBAN [app]. Встановлення без прав адміністратора — у %LOCALAPPDATA%\Programs\URBAN.
; Версія — з version.py (build.ps1 передає /DAppVer=...). Файли транслятора й шаблону — installer\files (у репозиторії).
#ifndef AppVer
  #define AppVer "0.0.0"
#endif
#ifndef Dist
  #define Dist "..\..\..\..\Temp\URBAN_build\dist\URBAN"
#endif
#ifndef OutDir
  #define OutDir "G:\URBAN\Документація"
#endif

[Setup]
AppId={{8B7F628D-2AB4-45D8-A073-6DA1BAAF9497}
AppName=URBAN
AppVersion={#AppVer}
AppVerName=URBAN {#AppVer}
AppPublisher=URBAN
AppComments=Archicad DXF → Digitals, DMF → DXF, ключі систем координат
DefaultDirName={localappdata}\Programs\URBAN
DefaultGroupName=URBAN
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
VersionInfoVersion={#AppVer}
CloseApplications=yes
OutputDir={#OutDir}
OutputBaseFilename=URBAN_Setup
SetupIconFile=..\assets\urban.ico
UninstallDisplayIcon={app}\URBAN.exe
UninstallDisplayName=URBAN
WizardStyle=modern
WizardImageFile=wizard_big.bmp
WizardSmallImageFile=wizard_small.bmp
InfoAfterFile=Як підключити транслятор.txt
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Dist}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "files\07 Для Digitals (МСК).Xml"; DestDir: "{app}\Транслятор Archicad"; Flags: ignoreversion
Source: "Як підключити транслятор.txt"; DestDir: "{app}\Транслятор Archicad"; Flags: ignoreversion
Source: "files\Пункти — шаблон.txt"; DestDir: "{app}\Приклади"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\URBAN"; Filename: "{app}\URBAN.exe"
Name: "{autoprograms}\URBAN — транслятор Archicad"; Filename: "{app}\Транслятор Archicad"; IconFilename: "{app}\URBAN.exe"
Name: "{autodesktop}\URBAN"; Filename: "{app}\URBAN.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Транслятор Archicad"; Description: "Відкрити папку з транслятором Archicad"; Flags: postinstall shellexec skipifsilent
; без skipifsilent: після тихого оновлення з програми URBAN запускається знову
Filename: "{app}\URBAN.exe"; Description: "Запустити URBAN"; Flags: postinstall nowait

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
