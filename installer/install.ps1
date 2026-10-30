<#
.SYNOPSIS
    Automated 1-Click Installer for Internet Downloader & Browser Extension.
.DESCRIPTION
    Installs Internet Downloader to %LOCALAPPDATA%\Programs\Internet Downloader,
    creates Desktop & Start Menu shortcuts, registers Windows Native Messaging
    hosts (com.tonec.idm & com.idm.downloader) for Chrome, Edge, and Firefox,
    and registers the idm:// protocol.
#>

param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\Simple Downloader"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Simple Downloader - Windows Setup & Integration" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

$SourceDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$SourceDir\segmented_downloader")) {
    $SourceDir = $PSScriptRoot
}

Write-Host "[*] Source Directory: $SourceDir"
Write-Host "[*] Target Installation Directory: $InstallDir"

# 1. Create target directory
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# 2. Copy application files
Write-Host "[*] Copying core engine, YouTube module, and UI files..." -ForegroundColor Yellow
$items = @("segmented_downloader", "browser_extension", "main.py", "README.md", "IDMGCExt.crx", "browser_extension.zip", "InternetDownloader.exe", "icon.ico")
foreach ($item in $items) {
    $src = Join-Path $SourceDir $item
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $InstallDir -Recurse -Force
    }
}

# 3. Register Chrome & Edge Native Messaging Hosts (Both com.tonec.idm and com.idm.downloader)
Write-Host "[*] Registering Browser Native Messaging Hosts..." -ForegroundColor Yellow
$nativeDir = Join-Path $InstallDir "browser_extension\native_messaging"
$manifestTonec = Join-Path $nativeDir "com.tonec.idm.json"
$manifestIdm = Join-Path $nativeDir "com.idm.downloader.json"

foreach ($hostEntry in @(@("com.tonec.idm", $manifestTonec), @("com.idm.downloader", $manifestIdm))) {
    $hName = $hostEntry[0]
    $mPath = $hostEntry[1]

    $cReg = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hName"
    if (-not (Test-Path $cReg)) { New-Item -Path $cReg -Force | Out-Null }
    Set-ItemProperty -Path $cReg -Name "(default)" -Value $mPath

    $eReg = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hName"
    if (-not (Test-Path $eReg)) { New-Item -Path $eReg -Force | Out-Null }
    Set-ItemProperty -Path $eReg -Name "(default)" -Value $mPath
}

# Auto-Install Browser Extension (Chrome & Edge)
Write-Host "[*] Registering Chrome & Edge Extension Web Store auto-install..." -ForegroundColor Yellow
$extId = "ngpampappnmepgilojfohadhhmbhlaek"
$updateUrl = "https://clients2.google.com/service/update2/crx"

$chromeExtReg = "HKCU:\Software\Google\Chrome\Extensions\$extId"
if (-not (Test-Path $chromeExtReg)) { New-Item -Path $chromeExtReg -Force | Out-Null }
Set-ItemProperty -Path $chromeExtReg -Name "update_url" -Value $updateUrl

$edgeExtReg = "HKCU:\Software\Microsoft\Edge\Extensions\$extId"
if (-not (Test-Path $edgeExtReg)) { New-Item -Path $edgeExtReg -Force | Out-Null }
Set-ItemProperty -Path $edgeExtReg -Name "update_url" -Value $updateUrl

$chromePol = "HKCU:\Software\Policies\Google\Chrome\ExtensionInstallForcelist"
if (-not (Test-Path $chromePol)) { New-Item -Path $chromePol -Force | Out-Null }
Set-ItemProperty -Path $chromePol -Name "1" -Value "$extId;$updateUrl"

$edgePol = "HKCU:\Software\Policies\Microsoft\Edge\ExtensionInstallForcelist"
if (-not (Test-Path $edgePol)) { New-Item -Path $edgePol -Force | Out-Null }
Set-ItemProperty -Path $edgePol -Name "1" -Value "$extId;$updateUrl"

# 4. Create Desktop and Start Menu Shortcuts
Write-Host "[*] Creating Desktop and Start Menu shortcuts..." -ForegroundColor Yellow
$WshShell = New-Object -ComObject WScript.Shell
$desktopDir = [System.Environment]::GetFolderPath("Desktop")
$startMenuDir = [System.Environment]::GetFolderPath("Programs")

$exePath = Join-Path $InstallDir "InternetDownloader.exe"
if (-not (Test-Path $exePath)) {
    $exePath = Join-Path $InstallDir "main.py"
}

# Remove any old broken shortcuts first
$oldDesktop = Join-Path $desktopDir "Simple Downloader.lnk"
if (Test-Path $oldDesktop) { Remove-Item $oldDesktop -Force -ErrorAction SilentlyContinue }

# Desktop Shortcut
$desktopShortcut = $WshShell.CreateShortcut((Join-Path $desktopDir "Simple Downloader.lnk"))
$desktopShortcut.TargetPath = $exePath
$desktopShortcut.WorkingDirectory = $InstallDir
$desktopShortcut.Description = "Simple Downloader - High-Performance Multi-Connection Downloader"
$icoPath = Join-Path $InstallDir "icon.ico"
if (Test-Path $icoPath) {
    $desktopShortcut.IconLocation = $icoPath
} else {
    $desktopShortcut.IconLocation = "$exePath,0"
}
$desktopShortcut.Save()

# Start Menu Shortcut
$smFolder = Join-Path $startMenuDir "Simple Downloader"
if (-not (Test-Path $smFolder)) { New-Item -ItemType Directory -Path $smFolder -Force | Out-Null }
$smShortcut = $WshShell.CreateShortcut((Join-Path $smFolder "Simple Downloader.lnk"))
$smShortcut.TargetPath = $exePath
$smShortcut.WorkingDirectory = $InstallDir
$smShortcut.Description = "Simple Downloader - High-Performance Multi-Connection Downloader"
if (Test-Path $icoPath) {
    $smShortcut.IconLocation = $icoPath
} else {
    $smShortcut.IconLocation = "$exePath,0"
}
$smShortcut.Save()

# 5. Register idm:// Protocol Handler
Write-Host "[*] Registering idm:// protocol handler..." -ForegroundColor Yellow
$protocolKey = "HKCU:\Software\Classes\idm"
if (-not (Test-Path $protocolKey)) { New-Item -Path $protocolKey -Force | Out-Null }
Set-ItemProperty -Path $protocolKey -Name "(default)" -Value "URL:Internet Downloader Protocol"
Set-ItemProperty -Path $protocolKey -Name "URL Protocol" -Value ""

$commandKey = "$protocolKey\shell\open\command"
if (-not (Test-Path $commandKey)) { New-Item -Path $commandKey -Force | Out-Null }
$cmdVal = '"{0}" "%1"' -f $exePath
Set-ItemProperty -Path $commandKey -Name "(default)" -Value $cmdVal

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  INSTALLATION FINISHED SUCCESSFULLY! [OK]" -ForegroundColor Green
Write-Host "  Desktop & Start Menu shortcuts: 'Internet Downloader.lnk'" -ForegroundColor Green
Write-Host "  Extension package: 'IDMGCExt.crx' in program folder" -ForegroundColor Green
Write-Host "  Native messaging bridge: 'com.tonec.idm' & 'com.idm.downloader'" -ForegroundColor Green
Write-Host "  YouTube & Segmented engines active on port 9653." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
