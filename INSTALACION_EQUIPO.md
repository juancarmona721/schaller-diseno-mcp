# Instalar el MCP de Diseño Schaller (guía para el equipo)

Tiempo: unos 3 minutos. No necesitas saber programar.

## El comando (pégalo en PowerShell)
```powershell
irm https://raw.githubusercontent.com/juancarmona721/schaller-diseno-mcp/main/instalar.ps1 | iex
```
Eso instala el MCP, lo conecta a Claude Desktop, comprueba AutoCAD, **busca `bloques_schaller.dwg` y lo abre** en AutoCAD, y termina con un diagnóstico (`[OK] ... todo listo`).
Después solo cierra Claude Desktop por completo (bandeja, *Quit*) y ábrelo otra vez.

## Antes de empezar
Necesitas en tu PC (Windows):
- **AutoCAD completo** (no LT) y **Claude Desktop** instalados.
- El archivo **`bloques_schaller.dwg`** que te pasó Juan. Guárdalo en una carpeta fija (por ejemplo `Documentos\Schaller`) y no lo muevas.
- Python 3.11 o superior: si no lo tienes, el instalador intenta instalarlo solo. Git **no** hace falta.

## Paso 1: instalar (una sola línea)
Abre **PowerShell** (tecla Windows, escribe `PowerShell`, Enter), pega el comando de arriba y espera a ver **`LISTO. Schaller MCP Diseno instalado.`** Si algo falla, el mensaje en rojo dice qué.
El instalador busca `bloques_schaller.dwg` en Descargas, Escritorio, Documentos y OneDrive. Si lo guardaste en otro lado, indica la ruta antes de pegar el comando: `$env:SCHALLER_BIBLIOTECA = "C:\ruta\bloques_schaller.dwg"`.

Alternativa sin internet: si Juan te pasó la carpeta del proyecto, haz doble clic en **`instalar_equipo.bat`**.

El instalador no borra tus otros conectores de Claude Desktop (hace una copia `.bak` de la configuración).

## Paso 2: reiniciar Claude Desktop
Ciérralo **por completo** (icono de la bandeja junto al reloj, clic derecho, *Quit*) y ábrelo otra vez.
Ve a **Settings, Developer**: debe aparecer **`schaller-diseno`** con su interruptor encendido.

## Paso 3: cada vez que vayas a trabajar
1. Abre AutoCAD con **`bloques_schaller.dwg`** (el instalador ya lo abre; si cerraste AutoCAD, ábrelo de nuevo) y **el plano donde vas a trabajar**. La biblioteca debe quedar abierta: de ahí se copian los bloques.
   Para comprobar que todo está bien, en PowerShell: `& "$env:USERPROFILE\.schaller-diseno\.venv\Scripts\python.exe" "$env:USERPROFILE\.schaller-diseno\schaller_cli.py" diagnostico`
2. En Claude Desktop, escribe por ejemplo: *"Revisa el estado de AutoCAD"*. Debe responder con tu dibujo activo.
3. Pide lo que necesites. Ejemplos:
   - *"Escanea las zonas del plano"*
   - *"Ubica las luminarias de la cama Gruppo-120 con la cabecera al norte"* (primero muestra un **ensayo**; confirma antes de que dibuje)
   - *"Quita lo que colocamos"* (borra solo las capas `SCH_ILUMINACION` y `SCH_AUDIO`)

**Planos grandes:** al escribir en un plano de más de 300 objetos, AutoCAD muestra un **código de 4 caracteres en la línea de comandos**. Claude te lo pedirá; léelo en AutoCAD y escríbeselo. Es una protección: nunca se escribe sin ese paso.

## Actualizar
Vuelve a pegar la misma línea del Paso 1 y reinicia Claude Desktop. Conserva tus perfiles de proyecto.

## Si algo no funciona
| Síntoma | Qué hacer |
|---|---|
| No aparece `schaller-diseno` en Developer | Cierra Claude Desktop **por completo** (bandeja, *Quit*) y ábrelo de nuevo. Si sigue, repite el Paso 1. |
| "No encontré AutoCAD abierto" | Abre AutoCAD con un dibujo antes de pedir nada. Debe ser AutoCAD completo, no LT. |
| "bloques_no_disponibles" | Abre `bloques_schaller.dwg` en la misma sesión de AutoCAD. |
| "La llamada fue rechazada" | AutoCAD está ocupado (un comando activo o regenerando). Pulsa Esc dos veces y repite. |
| El instalador dice que falta Python | Instálalo desde python.org marcando **Add Python to PATH** y repite el Paso 1. |
| Zonas vacías en un plano | Normal si el plano no trae textos de ambientes. Pide *"muéstrame las sugerencias de roles"* y clasifica los bloques con `perfil_proyecto`. |

## Para Juan: qué entregar a cada persona
1. Esta guía (o solo la línea del Paso 1).
2. El archivo `bloques_schaller.dwg` (por Teams o SharePoint, no por correo personal).
3. Nada más: el MCP se descarga solo.
