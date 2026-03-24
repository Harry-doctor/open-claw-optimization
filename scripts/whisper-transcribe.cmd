@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0whisper-transcribe.ps1" %*
endlocal
