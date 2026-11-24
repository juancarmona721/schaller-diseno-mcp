@echo off
chcp 65001 > nul
echo Instalando Schaller MCP Diseno...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
if %errorlevel% neq 0 (
    echo.
    echo La instalacion no se completo. Lee el mensaje de ERROR de arriba.
)
pause
