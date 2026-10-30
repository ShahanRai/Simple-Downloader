; Inno Setup Script for Internet Downloader
#define MyAppName "Simple Downloader"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Internet Downloader Team"
#define MyAppURL "https://github.com/internet-downloader"
#define MyAppExeName "InternetDownloader.exe"

[Setup]
AppId={{D37F2C08-5A2F-4A6F-9C4B-0B8E1D94B8A2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Internet_Downloader_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "registerprotocol"; Description: "Register idm:// URL Protocol"; GroupDescription: "System Integration"

[Files]
Source: "..\segmented_downloader\*"; DestDir: "{app}\segmented_downloader"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\browser_extension\*"; DestDir: "{app}\browser_extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\IDMGCExt.crx"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists(ExpandConstant('{src}\..\IDMGCExt.crx'))
Source: "..\browser_extension.zip"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists(ExpandConstant('{src}\..\browser_extension.zip'))
Source: "..\main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\InternetDownloader.exe"; DestDir: "{app}"; Flags: ignoreversion; Tasks: ; Check: FileExists(ExpandConstant('{src}\..\InternetDownloader.exe'))
Source: "..\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Tonec IDM Compatible Host
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.tonec.idm"; ValueType: string; ValueData: "{app}\browser_extension\native_messaging\com.tonec.idm.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\com.tonec.idm"; ValueType: string; ValueData: "{app}\browser_extension\native_messaging\com.tonec.idm.json"; Flags: uninsdeletekey
; Internet Downloader Native Host
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.idm.downloader"; ValueType: string; ValueData: "{app}\browser_extension\native_messaging\com.idm.downloader.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\com.idm.downloader"; ValueType: string; ValueData: "{app}\browser_extension\native_messaging\com.idm.downloader.json"; Flags: uninsdeletekey
; Chrome Auto-Install Extension via Web Store
Root: HKCU; Subkey: "Software\Google\Chrome\Extensions\ngpampappnmepgilojfohadhhmbhlaek"; ValueType: string; ValueName: "update_url"; ValueData: "https://clients2.google.com/service/update2/crx"; Flags: uninsdeletekey
; Edge Auto-Install Extension via Web Store
Root: HKCU; Subkey: "Software\Microsoft\Edge\Extensions\ngpampappnmepgilojfohadhhmbhlaek"; ValueType: string; ValueName: "update_url"; ValueData: "https://clients2.google.com/service/update2/crx"; Flags: uninsdeletekey
; Chrome Enterprise Policy (Silent Install)
Root: HKCU; Subkey: "Software\Policies\Google\Chrome\ExtensionInstallForcelist"; ValueType: string; ValueName: "1"; ValueData: "ngpampappnmepgilojfohadhhmbhlaek;https://clients2.google.com/service/update2/crx"; Flags: uninsdeletekey
; Edge Enterprise Policy (Silent Install)
Root: HKCU; Subkey: "Software\Policies\Microsoft\Edge\ExtensionInstallForcelist"; ValueType: string; ValueName: "1"; ValueData: "ngpampappnmepgilojfohadhhmbhlaek;https://clients2.google.com/service/update2/crx"; Flags: uninsdeletekey
; URL Protocol
Root: HKCU; Subkey: "Software\Classes\idm"; ValueType: string; ValueData: "URL:Internet Downloader Protocol"; Flags: uninsdeletekey; Tasks: registerprotocol
Root: HKCU; Subkey: "Software\Classes\idm"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey; Tasks: registerprotocol
Root: HKCU; Subkey: "Software\Classes\idm\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: registerprotocol

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

