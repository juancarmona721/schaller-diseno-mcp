# Instalar el MCP de Diseño Schaller (guía para el equipo)

Tiempo: unos 5 minutos. No necesitas saber programar.

## Antes de empezar: 4 cosas en tu PC

1. **Windows 10 u 11** y **AutoCAD completo** (no LT) con licencia activa.
2. **Claude Desktop**, la **aplicación** que se descarga en `https://claude.ai/download`. Instálala, ábrela **una vez** e inicia sesión.
   - Ojo: una "app" de Claude creada desde Chrome o Edge (menú del navegador → *Instalar Claude como aplicación*) **se parece pero no sirve**: es solo la web y no admite MCP.
   - Cómo saber cuál tienes: clic derecho en el acceso directo de Claude → *Abrir ubicación del archivo*. Si abre una carpeta llamada **Aplicaciones de Chrome** (o Edge), es la web app: instala la aplicación real.
3. El archivo **`bloques_schaller_corregido.dwg`** que te pasó Juan, guardado en **Descargas, Escritorio, Documentos o OneDrive** (puede llamarse `bloques schaller_corregido.dwg`; da igual).
4. Conexión a internet. Python lo instala el instalador si falta (no necesitas git).

## Paso 1: instalar (una sola línea)

Abre **PowerShell** o **Símbolo del sistema** (da igual), pega esta línea completa y pulsa Enter:

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; irm https://raw.githubusercontent.com/juancarmona721/schaller-diseno-mcp/main/instalar.ps1 -OutFile $env:TEMP\schaller_instalar.ps1; & $env:TEMP\schaller_instalar.ps1"
```

El instalador hace todo solo: instala el MCP, lo conecta a Claude Desktop, comprueba AutoCAD, **busca `bloques_schaller_corregido.dwg` y lo abre**, y termina con un diagnóstico.
- Si **Claude Desktop está abierto**, te pregunta si lo cierra (responde `S`): necesita cerrarlo para registrar el MCP.
- Debe terminar con **`LISTO. Schaller MCP Diseno instalado.`** Si algo falla, el mensaje en rojo dice qué.
- Si guardaste la biblioteca en otra carpeta, antes de pegar la línea indica la ruta (en PowerShell): `$env:SCHALLER_BIBLIOTECA = "C:\ruta\bloques_schaller_corregido.dwg"`

El instalador no borra tus otros conectores de Claude (hace una copia `.bak` de su configuración).

## Paso 2: abrir Claude Desktop y comprobar

1. Abre **Claude Desktop** desde el menú Inicio.
2. Ve a **Configuración → Aplicación de escritorio → Extensiones**. Abajo, en **Servidores MCP locales**, debe aparecer **`schaller-diseno`**.
   (En inglés: *Settings → Desktop app → Extensions → Local MCP servers*.)
3. En una **conversación nueva** escribe: *"Revisa el estado de AutoCAD"*. Debe responder con tu dibujo activo.

## Paso 3: cada vez que vayas a trabajar

1. Abre **una sola ventana de AutoCAD** con **`bloques_schaller_corregido.dwg`** y **tu plano**, y deja activa la **pestaña del plano**.
   - Si la pestaña activa es *Start*, o no hay ningún dibujo, las herramientas fallan ("no hay dibujo activo").
2. Pide lo que necesites. Ejemplos:
   - *"Escanea las zonas del plano"*
   - *"Ubica las luminarias de la cama X con la cabecera al norte"*: Claude decide y coloca directo, y al final te informa supuestos y omitidos. Para ver antes de colocar, pídele *"muéstrame primero (ensayo)"*.
   - *"Quita lo que colocamos"*: borra solo las capas `SCH_ILUMINACION` y `SCH_AUDIO`.
3. Si Claude no parece seguir el método, en el chat pulsa **`+`** y elige el prompt **`guia_de_diseno`** de `schaller-diseno`.

**Planos grandes:** al escribir en un plano de más de 300 objetos, AutoCAD muestra un **código de 4 caracteres en la línea de comandos**. Claude te lo pedirá; léelo en AutoCAD y escríbeselo. Es una protección: nunca se escribe sin ese paso.

**Planos sin textos de ambientes:** el escáner no encuentra zonas hasta que le dices qué son los bloques. Claude elegirá el rol más probable, lo declarará como supuesto y lo guardará en el perfil del proyecto.

## Actualizar

Vuelve a pegar la misma línea del Paso 1 y reinicia Claude Desktop. Se conservan tus perfiles de proyecto.

## Plan B: modo extensión

Si después del Paso 2 `schaller-diseno` no aparece en *Servidores MCP locales*, instala el MCP como extensión (no usa el archivo de configuración). En PowerShell:

```powershell
$env:SCHALLER_MODO = "extension"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; irm https://raw.githubusercontent.com/juancarmona721/schaller-diseno-mcp/main/instalar.ps1 -OutFile $env:TEMP\schaller_instalar.ps1; & $env:TEMP\schaller_instalar.ps1"
```

Se abre una ventana de Claude Desktop: pulsa **Instalar**. Si no se abre sola, arrastra el archivo `schaller-diseno.mcpb` (el instalador te muestra su carpeta) a la ventana de Claude. Después verás **Schaller Diseno (AutoCAD)** en *Configuración → Aplicación de escritorio → Extensiones*, con su interruptor.

## Si algo no funciona

Primero ejecuta el diagnóstico (solo lee, no cambia nada) y mándale el resultado completo a Juan:

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; irm https://raw.githubusercontent.com/juancarmona721/schaller-diseno-mcp/main/diagnostico_claude.ps1 -OutFile $env:TEMP\schaller_diag.ps1; & $env:TEMP\schaller_diag.ps1"
```

| Síntoma | Qué hacer |
|---|---|
| `irm` no se reconoce | Usa la línea del Paso 1 tal cual (empieza con `powershell`): funciona en CMD y en PowerShell. |
| "Acceso denegado" al pegar la línea | Tu equipo bloquea la descarga. Pide a Juan la carpeta del proyecto y haz doble clic en `instalar_equipo.bat`. |
| El instalador avisa *"no encontré Claude Desktop"* | Lo que usas es la web app de Chrome/Edge, o no hay nada instalado. Descarga la aplicación en `claude.ai/download`, ábrela, inicia sesión y repite el Paso 1. |
| `schaller-diseno` no aparece en *Servidores MCP locales* | Cierra Claude Desktop **por completo** (bandeja → *Quit*, o Administrador de tareas) y ábrelo. Si sigue igual, repite el Paso 1 y responde `S` cuando pregunte por cerrar Claude. Si aun así no, usa el Plan B. |
| Claude responde "no hay ningún dibujo activo" o las herramientas fallan | En AutoCAD debe estar activa la pestaña de un **dibujo**, no *Start*. Abre tu plano y haz clic en su pestaña. |
| "bloques_no_disponibles" | Abre `bloques_schaller_corregido.dwg` en la misma sesión de AutoCAD. |
| "La llamada fue rechazada" | AutoCAD está ocupado (un comando activo o regenerando). Pulsa Esc dos veces y repite. |
| Dos ventanas o procesos de AutoCAD, o la página *Start* sale gris | Guarda, cierra todo y en PowerShell pega `Get-Process acad \| Stop-Process -Force`; abre AutoCAD una sola vez. |
| El instalador dice que falta Python | Instala Python 3.12 desde python.org marcando **Add Python to PATH** y repite el Paso 1. |
| Zonas vacías en un plano | Normal si el plano no trae textos de ambientes: pídele a Claude que te muestre las sugerencias de bloques y clasifícalos. |
| AutoCAD marca *TRIAL* con unos días | Es una licencia de prueba: cuando venza dejará de funcionar y el MCP con él. Usa la licencia de BBLABS. |

## Para Juan: qué entregar a cada persona

1. Este texto (o solo el Paso 1 y el archivo del punto 3).
2. El archivo `bloques_schaller_corregido.dwg`, por Teams o SharePoint (no por correo personal).
3. Nada más: el MCP se descarga solo.

Mensaje para copiar y pegar:

> Hola. Para usar el MCP de diseño: 1) instala Claude Desktop (la aplicación, no la de Chrome) desde claude.ai/download, ábrela e inicia sesión; 2) guarda el archivo bloques_schaller_corregido.dwg en Descargas o Documentos; 3) abre PowerShell o CMD y pega la línea del Paso 1 de la guía (INSTALACION_EQUIPO.md). Cuando diga LISTO, abre Claude Desktop y escríbele "Revisa el estado de AutoCAD" con AutoCAD abierto. Si algo falla, mándame el resultado del diagnóstico de la guía.
