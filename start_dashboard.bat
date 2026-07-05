@echo off
set "APP_DIR=%~dp0"
set "CODEX_PY=C:\Users\jaden\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

cd /d "%APP_DIR%"

if exist "%CODEX_PY%" (
  "%CODEX_PY%" app.py
) else (
  python app.py
)

pause

