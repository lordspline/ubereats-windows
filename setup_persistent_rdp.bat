@echo off
powershell -ExecutionPolicy Bypass -File setup_autologon.ps1
powershell -ExecutionPolicy Bypass -File rdp_service.ps1
