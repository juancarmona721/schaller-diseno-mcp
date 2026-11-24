# Diagnostico: por que no aparece schaller-diseno en Claude Desktop. SOLO LEE, no cambia nada.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -Command "irm <url>/diagnostico_claude.ps1 | iex"
$ErrorActionPreference = "Continue"
function Linea($t) { Write-Host $t }
Linea "=== 1. Claude Desktop instalado y en ejecucion ==="
$normal = Test-Path "$env:LOCALAPPDATA\AnthropicClaude"
$store = @(Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue)
Linea ("Instalacion normal (AnthropicClaude): " + $normal)
Linea ("Version Microsoft Store (Claude_*): " + $store.Count)
$procs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "claude*" })
Linea ("Procesos con nombre claude abiertos ahora: " + $procs.Count + "  (pueden incluir otras herramientas de Claude; Claude Desktop debe cerrarse del todo y reabrirse tras instalar)")

Linea ""
Linea "=== 2. Archivos de configuracion ==="
$cfgs = @("$env:APPDATA\Claude\claude_desktop_config.json")
foreach ($p in $store) { $cfgs += (Join-Path $p.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json") }
$hayEntrada = $false
foreach ($c in $cfgs) {
    Linea ("ARCHIVO: " + $c + "  | existe: " + (Test-Path $c))
    if (-not (Test-Path $c)) { continue }
    try {
        $j = Get-Content $c -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $j.mcpServers) { Linea "   Sin seccion mcpServers (el instalador no escribio aqui)."; continue }
        $nombres = @($j.mcpServers.PSObject.Properties.Name)
        Linea ("   Servidores registrados: " + ($nombres -join ", "))
        $s = $j.mcpServers.'schaller-diseno'
        if (-not $s) { Linea "   >> schaller-diseno NO esta en este archivo."; continue }
        $hayEntrada = $true
        $cmd = $s.command; $srv = $s.args[0]
        Linea ("   python del MCP existe: " + (Test-Path $cmd) + "  -> " + $cmd)
        Linea ("   server.py existe:      " + (Test-Path $srv) + "  -> " + $srv)
        if ((Test-Path $cmd) -and (Test-Path $srv)) {
            $dir = Split-Path $srv -Parent
            $out = & $cmd -c "import sys; sys.path.insert(0, r'$dir'); import server; print('SERVIDOR OK, herramientas:', len(server.mcp._tool_manager.list_tools()))" 2>&1 | Select-Object -Last 3
            Linea ("   Prueba de arranque: " + ($out -join " | "))
        }
    } catch { Linea ("   JSON invalido o ilegible: " + $_.Exception.Message) }
}
if (-not $hayEntrada) { Linea ""; Linea ">> RESULTADO: schaller-diseno no esta registrado en ninguna configuracion. Vuelve a ejecutar el instalador y mira si termina con LISTO." }

Linea ""
Linea "=== 3. Logs recientes del MCP ==="
$carpetasLog = @("$env:APPDATA\Claude\logs")
foreach ($p in $store) { $carpetasLog += (Join-Path $p.FullName "LocalCache\Roaming\Claude\logs") }
$visto = $false
foreach ($d in $carpetasLog) {
    if (-not (Test-Path $d)) { continue }
    Get-ChildItem $d -Filter "mcp*.log" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | ForEach-Object {
        $visto = $true
        Linea ("--- " + $_.FullName + " (" + $_.LastWriteTime + ")")
        Get-Content $_.FullName -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object { Linea ("    " + $_) }
    }
}
if (-not $visto) { Linea "No hay logs de MCP: Claude Desktop nunca intento cargar servidores (instalacion distinta o MCP bloqueado)." }
Linea ""
Linea "=== Fin. Copia TODO lo de arriba y mandaselo a Juan. ==="
