// Lanzador de la extension de Claude Desktop: arranca el servidor MCP de Python ya instalado y le RETRANSMITE la entrada y la salida.
// Python (con pywin32) no se puede empaquetar dentro de una extension, por eso la instalacion vive en la carpeta del usuario
// (instalar.ps1 la crea). Esta extension solo da el interruptor en Settings > Extensions y evita los archivos de configuracion.
//
// IMPORTANTE: NO usar stdio:"inherit". Dentro de Claude Desktop este Node es el de Electron y su stdin no es una entrada del sistema
// heredable: el hijo recibia fin de entrada al instante y Python terminaba en silencio ("process exiting early"). Se retransmite
// con tuberias explicitas, que funciona igual en Electron que en un Node normal.
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

process.stderr.write("[schaller-diseno] arrancando " + servidor + "\n");
const hijo = spawn(python, [servidor], { cwd: carpeta, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });

hijo.on("error", (e) => fallar("No pude iniciar Python: " + e.message));

process.stdin.pipe(hijo.stdin);                 // Claude -> Python
hijo.stdout.pipe(process.stdout);               // Python -> Claude (solo JSON-RPC)
hijo.stderr.pipe(process.stderr);               // diagnosticos de Python -> log de la extension
hijo.stdin.on("error", () => { /* EPIPE: Python ya termino */ });
process.stdin.on("end", () => { try { hijo.stdin.end(); } catch (e) { /* ya cerrado */ } });

// "close" (no "exit") espera a que se vacien las tuberias: no se pierde el ultimo mensaje.
hijo.on("close", (codigo, senal) => {
  process.stderr.write("[schaller-diseno] el servidor termino (codigo " + codigo + (senal ? ", senal " + senal : "") + ")\n");
  process.exit(senal ? 1 : codigo === null ? 1 : codigo);
});

for (const s of ["SIGINT", "SIGTERM"]) {
  process.on(s, () => {
    try { hijo.kill(); } catch (e) { /* ya termino */ }
    process.exit(0);
  });
}
