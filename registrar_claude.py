"""Registra el MCP en la configuracion de Claude Desktop sin pisar lo que el usuario ya tenga.

Uso: python registrar_claude.py <python_del_venv> <server.py> [--config RUTA] [--nombre schaller-diseno]
Cada configuracion se respalda (.bak) antes de tocarla. Si el JSON existente esta danado NO se modifica.
"""
import glob
import json
import os
import shutil
import sys
from pathlib import Path

NOMBRE = "schaller-diseno"


def rutas_config() -> list[Path]:
    """Configuraciones donde ESCRIBIR para que Claude Desktop las lea.

    - Instalacion clasica: %APPDATA%\\Claude (solo si esa carpeta ya existe).
    - Version MSIX (la que instala claude.ai/download y la Store): la app lee SU carpeta virtualizada
      Packages\\Claude_*\\LocalCache\\Roaming\\Claude, no %APPDATA%. Se escribe ahi AUNQUE aun no exista (se crea): una instalacion
      recien hecha todavia no la ha creado, y escribir en %APPDATA% seria silencio total (la app no lo lee ni avisa).
    """
    cfg = "claude_desktop_config.json"
    appdata = os.environ.get("APPDATA")
    clasica = Path(appdata) / "Claude" / cfg if appdata else None
    destinos = []
    if clasica is not None and clasica.parent.exists():
        destinos.append(clasica)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for p in sorted(glob.glob(str(Path(local) / "Packages" / "Claude_*"))):
            if os.path.isdir(p):
                destinos.append(Path(p) / "LocalCache" / "Roaming" / "Claude" / cfg)
    return destinos or ([clasica] if clasica is not None else [])


def registrar(config: Path, python: str, server: str, nombre: str = NOMBRE) -> str:
    """Agrega/actualiza el servidor. Devuelve 'creado', 'actualizado' o lanza ValueError si el JSON esta danado."""
    config = Path(config)
    datos = {}
    existia = config.is_file()
    if existia:
        texto = config.read_text(encoding="utf-8-sig").strip()
        if texto:
            try:
                datos = json.loads(texto)
            except json.JSONDecodeError as e:
                raise ValueError(f"{config} no es JSON valido ({e}); no se modifico.") from e
            if not isinstance(datos, dict):
                raise ValueError(f"{config} no tiene el formato esperado; no se modifico.")
        shutil.copy2(config, str(config) + ".bak")
    servidores = datos.setdefault("mcpServers", {})
    estado = "actualizado" if nombre in servidores else "creado"
    servidores[nombre] = {"command": str(python), "args": [str(server)]}
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    return estado


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 2:
        print("Uso: registrar_claude.py <python> <server.py> [--config RUTA] [--nombre N]")
        return 2
    python, server = a[0], a[1]
    config = None
    nombre = NOMBRE
    if "--config" in a:
        config = Path(a[a.index("--config") + 1])
    if "--nombre" in a:
        nombre = a[a.index("--nombre") + 1]
    destinos = [config] if config else rutas_config()
    codigo = 0
    for d in destinos:
        try:
            print(f"OK ({registrar(d, python, server, nombre)}): {d}")
        except ValueError as e:
            print(f"ERROR: {e}")
            codigo = 1
    return codigo


if __name__ == "__main__":
    sys.exit(main())
