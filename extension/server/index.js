// Lanzador de la extension de Claude Desktop: arranca el servidor MCP de Python ya instalado y le pasa la entrada/salida tal cual.
// Python (con pywin32) no se puede empaquetar dentro de una extension, por eso la instalacion vive en la carpeta del usuario
// (instalar.ps1 la crea). Esta extension solo da el interruptor en Settings > Extensions y evita los archivos de configuracion.
"use strict";
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const carpeta = process.env.SCHALLER_DIR || path.join(os.homedir(), ".schaller-diseno");
const python = path.join(carpeta, ".venv", "Scripts", "python.exe");
const servidor = path.join(carpeta, "server.py");

function fallar(mensaje) {
  // stdout es del protocolo MCP: los mensajes para humanos van SIEMPRE a stderr (Claude los muestra en el log de la extension).
  process.stderr.write("[schaller-diseno] " + mensaje + "\n");
  process.exit(1);
}

if (!fs.existsSync(python) || !fs.existsSync(servidor)) {
  fallar(
    "No encuentro la instalacion en " + carpeta + ". Ejecuta primero instalar.ps1 (guia: INSTALACION_EQUIPO.md) y vuelve a activar la extension."
  );
}

const hijo = spawn(python, [servidor], { cwd: carpeta, stdio: "inherit", windowsHide: true });

hijo.on("error", (e) => fallar("No pude iniciar Python: " + e.message));
hijo.on("exit", (codigo, senal) => process.exit(senal ? 1 : codigo === null ? 1 : codigo));

for (const s of ["SIGINT", "SIGTERM"]) {
  process.on(s, () => {
    try { hijo.kill(); } catch (e) { /* ya termino */ }
    process.exit(0);
  });
}
// No se toca process.stdin: el hijo hereda ese mismo canal y, si Claude lo cierra, Python ve el fin de entrada y termina solo.
