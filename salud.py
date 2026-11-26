"""Estado del MCP sin tocar AutoCAD (pista 0A). Solo stdlib; no importa dependencias pesadas (usa find_spec).

La consulta basica NO se conecta a AutoCAD, no recorre entidades ni consulta internet: devuelve lo almacenado y dice que no esta verificado
en tiempo real. La comprobacion activa (`verificar=True`) hace UNA conexion y guarda el resultado para las consultas basicas siguientes.
"""
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path

ESQUEMA = 1


def version_mcp(aqui: Path) -> str:
    """Commit corto leyendo .git sin ejecutar git; si no hay repositorio, la version de pyproject.toml."""
    try:
        git = aqui / ".git"
        if git.is_file():                                   # worktrees: "gitdir: ..."
            git = (aqui / git.read_text(encoding="utf-8").split(":", 1)[1].strip()).resolve()
        cabeza = (git / "HEAD").read_text(encoding="utf-8").strip()
        if cabeza.startswith("ref:"):
            ref = cabeza.split(None, 1)[1]
            f = git / ref
            if f.is_file():
                return f.read_text(encoding="utf-8").strip()[:7]
            for linea in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
                if linea.endswith(" " + ref):
                    return linea.split()[0][:7]
        elif len(cabeza) >= 7:
            return cabeza[:7]
    except (OSError, ValueError, IndexError):
        pass
    try:
        for linea in (aqui / "pyproject.toml").read_text(encoding="utf-8").splitlines():
            if linea.strip().startswith("version"):
                return linea.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "desconocida"


def _hay(modulo: str) -> bool:
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


def capacidades() -> dict:
    """Que puede hacer esta instalacion. 'no_verificado' = presente o por probar, sin haberlo comprobado en tiempo real."""
    return {
        "autocad_com": "instalado" if _hay("win32com") else "no_instalado",
        "geometria_avanzada": "instalado" if _hay("shapely") else "no_instalado",
        "render_imagenes": "instalado" if _hay("PIL") else "no_instalado",
        "imagenes_en_cliente": "no_verificado",
        "elicitacion": "no_verificado",
    }


def perfil_instalacion(caps: dict) -> str:
    return "completo" if caps["geometria_avanzada"] == "instalado" and caps["render_imagenes"] == "instalado" else "compatibilidad"


def leer_ultima_conexion(ruta: Path) -> dict:
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_conexion(ruta: Path, ok: bool, ms: float | None, autocad_version: str | None = None) -> None:
    """Guarda SOLO estado y latencia (nada del dibujo: ni nombre ni contenido)."""
    try:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps({"estado": "disponible" if ok else "no_disponible", "ms": None if ms is None else round(ms),
                                   "marca_tiempo": time.strftime("%Y-%m-%dT%H:%M:%S"), "autocad_version": autocad_version}), encoding="utf-8")
        os.replace(tmp, ruta)
    except OSError:
        pass


def estado_basico(aqui: Path, ruta_conexion: Path, carpeta_perfiles: Path, n_herramientas: int | None, instrumentacion: bool,
                  verificado: dict | None = None) -> dict:
    caps = capacidades()
    ult = verificado if verificado is not None else leer_ultima_conexion(ruta_conexion)
    try:
        n_perfiles = len(list(Path(carpeta_perfiles).glob("*.json")))
    except OSError:
        n_perfiles = 0
    return {
        "ok": True,
        "esquema": ESQUEMA,
        "version_mcp": version_mcp(aqui),
        "perfil_instalacion": perfil_instalacion(caps),
        "capacidades": caps,
        "autocad": {
            "ultima_conexion": ult.get("estado", "sin_medir"),
            "ultima_conexion_ms": ult.get("ms"),
            "marca_tiempo": ult.get("marca_tiempo"),
            "version": ult.get("autocad_version"),
            "estado_actual_verificado": verificado is not None,
        },
        "perfiles_de_proyecto": n_perfiles,
        "herramientas": n_herramientas,
        "instrumentacion": {"activa": bool(instrumentacion)},
        "entorno": {"python": platform.python_version(), "arquitectura": platform.architecture()[0], "windows": platform.version()},
    }
