"""Empaqueta la extension de Claude Desktop (.mcpb = zip con manifest.json en la raiz) sin dependencias externas.

Uso:  .venv\\Scripts\\python.exe construir_mcpb.py
Salida: extension/schaller-diseno.mcpb (se versiona: el instalador lo abre en Claude Desktop).
Valida el manifest contra los campos obligatorios de la especificacion MCPB 0.3 antes de empaquetar.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ORIGEN = RAIZ / "extension"
SALIDA = ORIGEN / "schaller-diseno.mcpb"
OBLIGATORIOS = ("manifest_version", "name", "version", "description", "author", "server")
FECHA_FIJA = (2026, 1, 1, 0, 0, 0)          # el zip sale identico siempre: git no ve cambios si nada cambio


def validar(manifest: dict) -> list[str]:
    """Problemas del manifest segun la especificacion (lista vacia = valido)."""
    errores = [f"falta '{c}'" for c in OBLIGATORIOS if c not in manifest]
    if manifest.get("manifest_version") not in ("0.2", "0.3", "0.4"):
        errores.append("manifest_version debe ser 0.2, 0.3 o 0.4")
    if not re.fullmatch(r"\d+\.\d+\.\d+([-+].*)?", str(manifest.get("version", ""))):
        errores.append("version debe ser semver (x.y.z)")
    if not isinstance(manifest.get("author"), dict) or not manifest["author"].get("name"):
        errores.append("author.name es obligatorio")
    srv = manifest.get("server", {})
    if srv.get("type") not in ("node", "python", "binary", "uv"):
        errores.append("server.type invalido")
    if not srv.get("entry_point"):
        errores.append("server.entry_point es obligatorio")
    if "mcp_config" not in srv or "command" not in srv.get("mcp_config", {}):
        errores.append("server.mcp_config.command es obligatorio")
    plataformas = manifest.get("compatibility", {}).get("platforms", ["win32"])
    if any(p not in ("darwin", "win32", "linux") for p in plataformas):
        errores.append("compatibility.platforms solo admite darwin, win32, linux")
    return errores


def construir() -> Path:
    manifest = json.loads((ORIGEN / "manifest.json").read_text(encoding="utf-8"))
    errores = validar(manifest)
    entrada = ORIGEN / manifest["server"]["entry_point"]
    if not entrada.is_file():
        errores.append(f"no existe el entry_point {entrada.relative_to(RAIZ)}")
    if errores:
        raise SystemExit("manifest invalido:\n  - " + "\n  - ".join(errores))
    archivos = [p for p in sorted(ORIGEN.rglob("*")) if p.is_file() and p.suffix != ".mcpb"]
    with zipfile.ZipFile(SALIDA, "w", zipfile.ZIP_DEFLATED) as z:
        for p in archivos:
            info = zipfile.ZipInfo(p.relative_to(ORIGEN).as_posix(), FECHA_FIJA)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
    return SALIDA


if __name__ == "__main__":
    destino = construir()
    with zipfile.ZipFile(destino) as z:
        print(f"{destino.relative_to(RAIZ)} ({destino.stat().st_size} bytes): " + ", ".join(z.namelist()))
    sys.exit(0)
