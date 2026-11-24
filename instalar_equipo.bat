@echo off
chcp 65001 > nul
echo =====================================================================
echo   INSTALADOR DE SCHALLER MCP DISENO (Para el Equipo)
echo =====================================================================
echo.

:: 1. Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] No se encontro Python en el sistema.
    echo Por favor instala Python 3.11 o 3.12 desde python.org asegurando marcar "Add Python to PATH".
    pause
    exit /b 1
)

echo [1/3] Creando entorno virtual local (.venv)...
if not exist .venv (
    python -m venv .venv
)

echo [2/3] Instalando dependencias de Python...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo [3/3] Probando conexion con el servidor MCP...
.venv\Scripts\python.exe -c "import server; print('Servidor MCP cargado exitosamente.')"

echo.
echo =====================================================================
echo   INSTALACION COMPLETADA CON EXITO
echo =====================================================================
echo.
echo Para conectar este MCP a Claude Desktop o Antigravity, copia esta
echo configuracion en tu archivo de configuracion MCP:
echo.
echo {
echo   "mcpServers": {
echo     "schaller-diseno": {
echo       "command": "%CD%\\.venv\\Scripts\\python.exe",
echo       "args": ["%CD%\\server.py"]
echo     }
echo   }
echo }
echo.
echo =====================================================================
pause
