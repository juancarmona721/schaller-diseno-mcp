# Instalador de Schaller MCP Diseno para Claude Desktop (Windows PowerShell 5.1 o superior).
# Uso desde una carpeta con el proyecto:   powershell -ExecutionPolicy Bypass -File instalar.ps1
# Uso en una linea:                         irm <url>/instalar.ps1 | iex
# Variables opcionales (entorno): SCHALLER_DIR (destino), SCHALLER_REPO (url git), SCHALLER_CLAUDE_CONFIG (json de Claude),
# SCHALLER_SIN_VERIFICAR=1 (omite la prueba final).
$ErrorActionPreference = "Stop"

function Paso($t) { Write-Host "-> $t" -ForegroundColor Yellow }
function Fallo($t) { Write-Host ""; Write-Host "ERROR: $t" -ForegroundColor Red; throw $t }

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Instalador de Schaller MCP Diseno" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$InstallDir = if ($env:SCHALLER_DIR) { $env:SCHALLER_DIR } else { Join-Path $env:USERPROFILE ".schaller-diseno" }
$Repo = if ($env:SCHALLER_REPO) { $env:SCHALLER_REPO } else { "https://github.com/juancarmona721/schaller-diseno-mcp.git" }
Paso "Carpeta de instalacion: $InstallDir"

# 1. Python 3.11+ -------------------------------------------------------------
function Buscar-Python {
    $candidatos = @(@("py", "-3.12"), @("py", "-3.11"), @("py", "-3"), @("python"))
    foreach ($c in $candidatos) {
        try {
            $exe = $c[0]; $args2 = @()
            if ($c.Count -gt 1) { $args2 = $c[1..($c.Count - 1)] }
            $v = & $exe @args2 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $p = $v.Trim().Split(".")
                if ([int]$p[0] -gt 3 -or ([int]$p[0] -eq 3 -and [int]$p[1] -ge 11)) { return ,@($exe) + $args2 }
            }
        } catch {}
    }
    return $null
}
$Py = Buscar-Python
if (-not $Py) {
    Paso "Python 3.11+ no encontrado. Intentando instalarlo con winget..."
    try {
        winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    } catch {}
    $Py = Buscar-Python
}
if (-not $Py) { Fallo "Falta Python 3.11 o superior. Instalalo desde python.org (marca 'Add Python to PATH') y vuelve a ejecutar este instalador." }

# 2. Obtener los archivos --------------------------------------------------------
$Origen = $env:SCHALLER_ORIGEN
if (-not $Origen -and $PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "server.py"))) { $Origen = $PSScriptRoot }

if ($Origen) {
    Paso "Copiando desde $Origen"
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    if ((Resolve-Path $Origen).Path -ne (Resolve-Path $InstallDir).Path) {
        robocopy $Origen $InstallDir /E /NFL /NDL /NJH /NJS /NP `
            /XD .venv .git .claude .pytest_cache __pycache__ tests scratch_agente respaldo_antes_de_limpiar fichas `
            /XF *.dwg *.bak *.log *.xlsx zonas_activas.json | Out-Null
        if ($LASTEXITCODE -ge 8) { Fallo "No se pudieron copiar los archivos (robocopy $LASTEXITCODE)." }
    }
} elseif (Test-Path (Join-Path $InstallDir ".git")) {
    Paso "Actualizando instalacion existente..."
    git -C "$InstallDir" pull
    if ($LASTEXITCODE -ne 0) { Fallo "git pull fallo. Revisa tu acceso al repositorio." }
} else {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fallo "Falta git. Instalalo (winget install Git.Git) o pide la carpeta del proyecto y ejecuta instalar.ps1 desde ella." }
    Paso "Descargando el proyecto..."
    git clone $Repo "$InstallDir"
    if ($LASTEXITCODE -ne 0) { Fallo "No se pudo descargar el repositorio. Verifica tu acceso o ejecuta instalar.ps1 desde la carpeta del proyecto." }
}
if (-not (Test-Path (Join-Path $InstallDir "server.py")) -or -not (Test-Path (Join-Path $InstallDir "sondas"))) {
    Fallo "La instalacion esta incompleta (faltan server.py o la carpeta sondas)."
}

# 3. Entorno virtual y dependencias ----------------------------------------------
$VenvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Paso "Creando entorno virtual..."
    $exe = $Py[0]; $a = @(); if ($Py.Count -gt 1) { $a = $Py[1..($Py.Count - 1)] }
    & $exe @a -m venv (Join-Path $InstallDir ".venv")
    if ($LASTEXITCODE -ne 0) { Fallo "No se pudo crear el entorno virtual." }
}
Paso "Instalando dependencias (puede tardar un minuto)..."
& $VenvPython -m pip install -q --disable-pip-version-check -r (Join-Path $InstallDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fallo "Fallo la instalacion de dependencias. Revisa tu conexion a internet." }

# 4. Verificar que el servidor arranca ----------------------------------------------
if ($env:SCHALLER_SIN_VERIFICAR -ne "1") {
    Paso "Verificando el servidor..."
    Push-Location $InstallDir
    try {
        $r = & $VenvPython -c "import server; print(len(server.mcp._tool_manager.list_tools()))"
        if ($LASTEXITCODE -ne 0) { Fallo "El servidor no arranca. Ejecuta: $VenvPython -c 'import server' para ver el detalle." }
        Write-Host "   Servidor OK ($r herramientas)." -ForegroundColor Green
    } finally { Pop-Location }
}

# 5. Registrar en Claude Desktop (conserva lo que ya tengas) ---------------------------
Paso "Registrando en Claude Desktop..."
$reg = Join-Path $InstallDir "registrar_claude.py"
$argsReg = @($reg, $VenvPython, (Join-Path $InstallDir "server.py"))
if ($env:SCHALLER_CLAUDE_CONFIG) { $argsReg += @("--config", $env:SCHALLER_CLAUDE_CONFIG) }
& $VenvPython @argsReg
if ($LASTEXITCODE -ne 0) { Fallo "No se pudo actualizar la configuracion de Claude Desktop (ver mensaje arriba). Tu archivo original no se modifico." }

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  LISTO. Schaller MCP Diseno instalado." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "1. CIERRA Claude Desktop por completo (icono de la bandeja > Quit) y vuelve a abrirlo." -ForegroundColor White
Write-Host "2. Ve a Settings > Developer: veras 'schaller-diseno' con su interruptor." -ForegroundColor White
Write-Host "3. Abre AutoCAD con 'bloques_schaller.dwg' y el plano donde vas a trabajar." -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan
