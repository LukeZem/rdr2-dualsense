@echo off
rem DualSense Trigger Lab. Close DSX / DS4Windows and RDR2 first.
cd /d "%~dp0"
"%~dp0..\..\.venv\Scripts\python.exe" lab.py
if errorlevel 1 pause
