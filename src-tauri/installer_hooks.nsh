!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping existing Internet Downloader instances..."
  nsExec::Exec 'taskkill /F /IM internet-downloader.exe /T'
  nsExec::Exec 'taskkill /F /IM InternetDownloader.exe /T'
  Sleep 500
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Stopping existing Internet Downloader instances..."
  nsExec::Exec 'taskkill /F /IM internet-downloader.exe /T'
  nsExec::Exec 'taskkill /F /IM InternetDownloader.exe /T'
  Sleep 500
!macroend

