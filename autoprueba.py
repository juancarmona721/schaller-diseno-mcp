"""Autoprueba de instalacion, nivel 1 (pista 0A): entorno e instalacion, SIN abrir ni tocar ningun dibujo de AutoCAD.

Comprueba operaciones reales (no solo importaciones), es segura al repetirse y no modifica nada de forma permanente: solo crea y borra
archivos temporales. No cambia la configuracion de Claude Desktop ni los perfiles. Cada comprobacion devuelve ok / aviso / fallo.
"""
import json
import os
import platform
import sys
import tempfile
import tomllib
from pathlib import Path

PYTHON_MIN, PYTHON_MAX = (3, 11), (3, 13)


def _r(id_, estado, detalle):
    return {"id": id_, "estado": estado, "detalle": detalle}


def _sistema():
    es_win = platform.system() == "Windows"
    return _r("sistema", "ok" if es_win and platform.architecture()[0] == "64bit" else "fallo",
              f"{platform.system()} {platform.version()} ({platform.architecture()[0]})")


def _python():
    v = sys.version_info[:2]
    ok_ver = PYTHON_MIN <= v <= PYTHON_MAX
    en_venv = sys.prefix != sys.base_prefix
    estado = "ok" if ok_ver and en_venv else ("aviso" if ok_ver else "fallo")
    nota = "" if en_venv else " (no es un entorno virtual)"
    return _r("python", estado, f"Python {platform.python_version()} {platform.architecture()[0]}; rango soportado {PYTHON_MIN[0]}.{PYTHON_MIN[1]}-{PYTHON_MAX[0]}.{PYTHON_MAX[1]}{nota}")


_CODIGO_COM = "\n".join([
    "import pythoncom, win32com.client",
    "pythoncom.CoInitialize()",
    "d = win32com.client.Dispatch('Scripting.Dictionary')",
    "d.Add('k', 7)",
    "print('OK' if d.Item('k') == 7 else 'MAL')",
    "del d",
])


def _pywin32():
    """Operacion COM real sin AutoCAD, en un subproceso aislado con `-I` (igual que las sondas): una falla de COM no tumba esta prueba."""
    import subprocess
    try:
        r = subprocess.run([sys.executable, "-I", "-c", _CODIGO_COM], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return _r("pywin32", "fallo", f"{type(e).__name__}: {e}")
    if r.returncode == 0 and r.stdout.strip() == "OK":
        return _r("pywin32", "ok", "COM funciona (objeto de prueba creado y leido en un subproceso)")
    return _r("pywin32", "fallo", (r.stderr or r.stdout or f"codigo de salida {r.returncode}").strip()[-300:])


_CODIGO_SHAPELY = "\n".join([
    "import shapely, shapely.geometry as sh",
    "from shapely.ops import unary_union",
    "u = unary_union([sh.LineString([(0, 0), (4, 0)]).buffer(0.1), sh.LineString([(4, 0), (4, 3)]).buffer(0.1)])",
    "print('OK' if 1.0 < u.area < 2.0 else 'MAL')",
])


def _geometria_avanzada():
    """Shapely es OPCIONAL: sin el, el MCP funciona (no reconstruye habitaciones desde muros). Si esta instalado, se prueba una operacion real."""
    import importlib.util
    import subprocess
    if importlib.util.find_spec("shapely") is None:
        return _r("geometria_avanzada", "aviso", "Shapely no esta instalado (opcional): no se reconstruiran habitaciones desde los muros")
    try:
        r = subprocess.run([sys.executable, "-I", "-c", _CODIGO_SHAPELY], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return _r("geometria_avanzada", "fallo", f"{type(e).__name__}: {e}")
    if r.returncode == 0 and r.stdout.strip() == "OK":
        return _r("geometria_avanzada", "ok", "Shapely instalado: operacion geometrica real correcta")
    return _r("geometria_avanzada", "fallo", (r.stderr or r.stdout or f"codigo de salida {r.returncode}").strip()[-300:])


def _mcp():
    try:
        from mcp.server.fastmcp import FastMCP
        s = FastMCP("autoprueba")

        @s.tool()
        def eco(x: int) -> int:
            return x

        return _r("mcp_sdk", "ok", "el SDK crea un servidor y registra una herramienta")
    except Exception as e:                                              # noqa: BLE001
        return _r("mcp_sdk", "fallo", f"{type(e).__name__}: {e}")


def _otras_dependencias():
    fallos = []
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active["A1"] = 1
    except Exception as e:                                              # noqa: BLE001
        fallos.append(f"openpyxl: {e}")
    try:
        import pydantic

        class M(pydantic.BaseModel):
            a: int

        M.model_validate({"a": 1})
    except Exception as e:                                              # noqa: BLE001
        fallos.append(f"pydantic: {e}")
    return _r("dependencias", "fallo" if fallos else "ok", "; ".join(fallos) or "openpyxl y pydantic operan")


def _ciclo_de_archivo(carpeta: Path):
    """Crear, reemplazar atomicamente y borrar un archivo en `carpeta`."""
    carpeta.mkdir(parents=True, exist_ok=True)
    a, b = carpeta / "autoprueba.tmp", carpeta / "autoprueba.final"
    a.write_text("áé ñ", encoding="utf-8")
    os.replace(a, b)
    ok = b.read_text(encoding="utf-8") == "áé ñ"
    b.unlink()
    return ok


def _rutas(aqui: Path, carpeta_perfiles: Path):
    fallos = []
    try:
        with tempfile.TemporaryDirectory(prefix="prueba ñ espacio ") as t:      # espacios y Unicode en la ruta
            if not _ciclo_de_archivo(Path(t) / "sub carpeta"):
                fallos.append("ruta con espacios/Unicode")
    except OSError as e:
        fallos.append(f"ruta con espacios/Unicode: {e}")
    for nombre, carpeta in (("instalacion", aqui), ("perfiles", carpeta_perfiles)):
        try:
            if not _ciclo_de_archivo(carpeta / ".autoprueba" if nombre == "instalacion" else carpeta):
                fallos.append(f"escritura en {nombre}")
        except OSError as e:
            fallos.append(f"escritura en {nombre}: {e}")
    try:
        (aqui / ".autoprueba").rmdir()
    except OSError:
        pass
    return _r("rutas_y_permisos", "fallo" if fallos else "ok",
              "; ".join(fallos) or "crear, reemplazar y borrar archivos funciona (incluida una ruta con espacios y Unicode)")


def _integridad(aqui: Path):
    faltan = []
    try:
        sys.path.insert(0, str(aqui))
        import acad
        for nombre in dir(acad):
            if nombre.startswith("PROBE_") and not getattr(acad, nombre).is_file():
                faltan.append(Path(getattr(acad, nombre)).name)
    except Exception as e:                                              # noqa: BLE001
        return _r("integridad", "fallo", f"no pude comprobar las sondas: {type(e).__name__}: {e}")
    for req in ("server.py", "motor_ubicacion.py", "zonas_motor.py", "vocabulario_espacios.json", "config.toml"):
        if not (aqui / req).is_file():
            faltan.append(req)
    try:
        tomllib.loads((aqui / "config.toml").read_text(encoding="utf-8"))
        json.loads((aqui / "vocabulario_espacios.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        faltan.append(f"archivo de configuracion ilegible ({type(e).__name__})")
    return _r("integridad", "fallo" if faltan else "ok", ("faltan o fallan: " + ", ".join(faltan)) if faltan else "sondas y archivos requeridos presentes y legibles")


def _cliente_mcp(nombre_servidor: str, configs: list[Path] | None):
    if configs is None:
        try:
            import registrar_claude
            configs = registrar_claude.rutas_config()
            nombre_servidor = registrar_claude.NOMBRE
        except Exception:                                               # noqa: BLE001
            configs = []
    existentes = [c for c in configs if Path(c).is_file()]
    if not existentes:
        return _r("cliente_mcp", "aviso", "no encontre la configuracion de Claude Desktop (normal si se instalo como extension)")
    problemas, registrados, otros = [], 0, 0
    for c in existentes:
        try:
            datos = json.loads(Path(c).read_text(encoding="utf-8-sig") or "{}")
        except ValueError:
            problemas.append("una configuracion no es JSON valido")
            continue
        srv = (datos.get("mcpServers") or {}) if isinstance(datos, dict) else {}
        otros += len([k for k in srv if k != nombre_servidor])
        if nombre_servidor in srv:
            registrados += 1
            cmd = (srv[nombre_servidor] or {}).get("command", "")
            args = (srv[nombre_servidor] or {}).get("args") or []
            if not Path(cmd).is_file():
                problemas.append("el ejecutable configurado no existe")
            if args and not Path(args[0]).is_file():
                problemas.append("el server.py configurado no existe")
    if problemas:
        return _r("cliente_mcp", "fallo", "; ".join(problemas))
    if not registrados:
        return _r("cliente_mcp", "aviso", f"configuracion encontrada pero {nombre_servidor} no esta registrado ({otros} otros servidores, sin tocar)")
    return _r("cliente_mcp", "ok", f"registrado y con rutas validas; {otros} otros servidores MCP, sin tocar")


def _autocad_registrado():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"AutoCAD.Application\CLSID"):
            return _r("autocad_registrado", "ok", "AutoCAD esta registrado en COM (no se conecto: eso es del nivel 2)")
    except (ImportError, OSError):
        return _r("autocad_registrado", "aviso", "AutoCAD no aparece registrado en COM en este equipo")


def ejecutar(aqui: Path, carpeta_perfiles: Path, configs: list[Path] | None = None) -> dict:
    comprobaciones = [_sistema(), _python(), _pywin32(), _geometria_avanzada(), _mcp(), _otras_dependencias(), _rutas(aqui, carpeta_perfiles), _integridad(aqui),
                      _cliente_mcp("schaller-diseno", configs), _autocad_registrado()]
    n = {e: sum(1 for c in comprobaciones if c["estado"] == e) for e in ("ok", "aviso", "fallo")}
    return {"ok": n["fallo"] == 0, "nivel": 1, "resumen": n, "comprobaciones": comprobaciones}


def informe(res: dict) -> list[str]:
    marca = {"ok": "[OK]", "aviso": "[ ]", "fallo": "[X]"}
    lineas = [f"{marca[c['estado']]} {c['id']}: {c['detalle']}" for c in res["comprobaciones"]]
    r = res["resumen"]
    lineas.append(f"Autoprueba nivel 1: {r['ok']} ok, {r['aviso']} avisos, {r['fallo']} fallos.")
    return lineas
