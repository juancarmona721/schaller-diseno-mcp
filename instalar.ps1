# Script de instalacion de 1 linea para el equipo de Schaller
$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Instalador Automatico de Schaller MCP Diseno" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Determinar directorio de instalacion
$InstallDir = "$env:USERPROFILE\.schaller-diseno"
Write-Host "-> Instalando en: $InstallDir" -ForegroundColor Yellow

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# 2. Copiar archivos del servidor
$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (Test-Path "$CurrentDir\server.py") {
    Copy-Item "$CurrentDir\*.py" "$InstallDir\" -Force
    Copy-Item "$CurrentDir\requirements.txt" "$InstallDir\" -Force
    Copy-Item "$CurrentDir\config.toml" "$InstallDir\" -Force
}

# 3. Crear entorno virtual
Write-Host "-> Configurando entorno virtual Python..." -ForegroundColor Yellow
$VenvPython = "$InstallDir\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    python -m venv "$InstallDir\.venv"
}

# 4. Instalar librerias
Write-Host "-> Instalando dependencias de AutoCAD y MCP..." -ForegroundColor Yellow
& "$VenvPython" -m pip install -q -r "$InstallDir\requirements.txt"

# 5. Configurar Claude Desktop automaticamente
$ClaudeConfigDir = "$env:APPDATA\Claude"
$ClaudeConfigFile = "$ClaudeConfigDir\claude_desktop_config.json"

if (-not (Test-Path $ClaudeConfigDir)) {
    New-Item -ItemType Directory -Path $ClaudeConfigDir -Force | Out-Null
}

$ConfigJson = @{ mcpServers = @{} }
if (Test-Path $ClaudeConfigFile) {
    try {
        $RawContent = Get-Content $ClaudeConfigFile -Raw
        if ($RawContent.Trim()) {
            $ConfigJson = $RawContent | ConvertFrom-Json -AsHashtable
            if (-not $ConfigJson.ContainsKey("mcpServers")) {
                $ConfigJson["mcpServers"] = @{}
            }
        }
    } catch {}
}

$ConfigJson["mcpServers"]["schaller-diseno"] = @{
    command = $VenvPython
    args = @("$InstallDir\server.py")
}

$ConfigJson | ConvertTo-Json -Depth 10 | Set-Content $ClaudeConfigFile -Encoding UTF8

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  LISTO! SCHALLER MCP DISENO HA SIDO CONFIGURADO" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Tu Claude Desktop ya tiene acceso directo al servidor." -ForegroundColor Green
Write-Host "Instrucciones de uso:" -ForegroundColor Cyan
Write-Host "1. Abre AutoCAD y ten abierto el archivo 'bloques_schaller.dwg'." -ForegroundColor White
Write-Host "2. Abre el plano arquitectonico donde vas a trabajar." -ForegroundColor White
Write-Host "3. Abre Claude Desktop o Claude Code y escribe tu solicitud." -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan
