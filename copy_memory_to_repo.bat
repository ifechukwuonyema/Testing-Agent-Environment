@echo off
set SRC=%USERPROFILE%\.claude\projects\C--WINDOWS-system32\memory
set DST=%~dp0.claude\memory

if not exist "%DST%" mkdir "%DST%"
copy "%SRC%\*.md" "%DST%\" /Y
echo Done. Copied memory files to %DST%
pause
