"""Acceso de SOLO LECTURA a AutoCAD, con limite de tiempo.

Cada llamada COM corre en un proceso hijo (sondas/sonda_*.py). Si AutoCAD no responde dentro del limite,
el hijo se termina y se devuelve un error claro; el servidor nunca se bloquea.
Dos limites: `timeout_s` (AutoCAD responde, 10 s) y `timeout_lectura_s` (lecturas largas, p. ej. recorrer bloques).
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

import metricas

AQUI = Path(__file__).resolve().parent
PROBE_ESTADO = AQUI / "sondas" / "sonda_estado.py"
PROBE_BLOQUES = AQUI / "sondas" / "sonda_bloques.py"
PROBE_ESCRIBIR = AQUI / "sondas" / "sonda_escribir.py"
PROBE_VISTA = AQUI / "sondas" / "sonda_vista.py"
PROBE_SIMBOLOS = AQUI / "sondas" / "sonda_simbolos.py"
PROBE_SVG = AQUI / "sondas" / "sonda_svg.py"
PROBE_TARJETAS = AQUI / "sondas" / "sonda_tarjetas.py"
PROBE_PLANO = AQUI / "sondas" / "sonda_plano.py"
PROBE_ZONAS = AQUI / "sondas" / "sonda_zonas.py"
PROBE_PATRONES = AQUI / "sondas" / "sonda_patrones.py"
PROBE_INTENCIONES = AQUI / "sondas" / "sonda_intenciones.py"
PROBE_DISENO = AQUI / "sondas" / "sonda_diseno.py"


# UN solo acceso a AutoCAD a la vez. Claude Desktop lanza varias herramientas EN PARALELO; cada una abre su propio proceso contra el mismo
# AutoCAD y, sin esto, se pisan (conjuntos de seleccion borrados, "llamada rechazada"): 5 de 6 llamadas fallaban. Es un RLock: una operacion
# de varios pasos (leer contexto + insertar) puede tomarlo entera y sus pasos internos lo re-toman sin bloquearse.
LOCK = threading.RLock()


def _correr(script: Path, timeout_s: float, argumentos=None, mensaje_timeout: str | None = None) -> dict:
    with LOCK:
        return _correr_sin_candado(script, timeout_s, argumentos, mensaje_timeout)


def _correr_sin_candado(script: Path, timeout_s: float, argumentos=None, mensaje_timeout: str | None = None) -> dict:
    with metricas.etapa("subproceso." + script.stem):         # apagada: un contexto vacio compartido, sin reloj ni memoria
        res = _lanzar(script, timeout_s, argumentos, mensaje_timeout)
    if isinstance(res, dict) and "_metricas" in res:
        metricas.absorber(res.pop("_metricas"))
    return res


def _lanzar(script: Path, timeout_s: float, argumentos=None, mensaje_timeout: str | None = None) -> dict:
    try:
        r = subprocess.run(
            [sys.executable, "-I", str(script), *(argumentos or [])],
            capture_output=True, text=True, timeout=timeout_s,
            stdin=subprocess.DEVNULL,  # no heredar el stdin del servidor (es el canal MCP)
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "autocad_no_responde",
                "detalle": mensaje_timeout or (
                    f"AutoCAD no respondio en {timeout_s:g} s. Suele pasar si hay una ventana "
                    "de dialogo abierta o un comando en curso. Cierra el dialogo y reintenta.")}
    except OSError as e:
        return {"ok": False, "error": "no_pude_lanzar_sonda", "detalle": str(e)}
    linea = (r.stdout or "").strip().splitlines()[-1:] or [""]
    try:
        return json.loads(linea[0])
    except json.JSONDecodeError:
        return {"ok": False, "error": "respuesta_invalida",
                "detalle": (r.stderr or r.stdout or "sin salida")[-500:]}


def estado(timeout_s: float = 10.0) -> dict:
    return _correr(PROBE_ESTADO, timeout_s)


def escribir(args: dict, timeout_s: float = 10.0, timeout_escritura_s: float = 30.0) -> dict:
    """Operacion de ESCRITURA acotada (solo agrega). Primero comprueba que AutoCAD responde."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    if not previo.get("dibujo_activo"):
        return {"ok": False, "error": "sin_dibujo", "detalle": "AutoCAD esta abierto pero no hay ningun dibujo activo."}
    return _correr(
        PROBE_ESCRIBIR, timeout_escritura_s, [json.dumps(args)],
        mensaje_timeout=(f"La escritura no termino en {timeout_escritura_s:g} s y NO se sabe si quedo a medias. "
                         "Revisa el dibujo (Ctrl+Z en AutoCAD deshace) y cierra cualquier dialogo abierto."))


def dibujar_tarjetas(args: dict, timeout_s: float = 10.0, timeout_escritura_s: float = 30.0) -> dict:
    """Dibuja tarjetas de producto en un dibujo (solo agrega). Primero comprueba que AutoCAD responde."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    return _correr(
        PROBE_TARJETAS, timeout_escritura_s, [json.dumps(args)],
        mensaje_timeout=(f"El dibujo de tarjetas no termino en {timeout_escritura_s:g} s y NO se sabe si quedo a medias. "
                         "Revisa el dibujo (Ctrl+Z en AutoCAD deshace) y cierra cualquier dialogo abierto."))


def exportar_svg(nombres, destino_contiene=None, timeout_s: float = 10.0, timeout_lectura_s: float = 60.0) -> dict:
    """Geometria de definiciones de bloque como SVG (solo lectura)."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    return _correr(PROBE_SVG, timeout_lectura_s, [json.dumps({"destino_contiene": destino_contiene, "nombres": list(nombres)})],
                   mensaje_timeout=f"La lectura de simbolos no termino en {timeout_lectura_s:g} s. Prueba con menos bloques o sube [autocad].timeout_lectura_s.")


def importar_simbolos(args: dict, timeout_s: float = 10.0, timeout_importar_s: float = 300.0) -> dict:
    """Copia definiciones de bloque de un dibujo origen (solo lectura) a un destino (solo agrega)."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    return _correr(
        PROBE_SIMBOLOS, timeout_importar_s, [json.dumps(args)],
        mensaje_timeout=(f"La importacion no termino en {timeout_importar_s:g} s (leer un plano grande es lento) y NO se sabe si "
                         "quedo a medias. Revisa el dibujo destino y sube [simbolos].timeout_importar_s en config.toml."))


def ver_plano(destino_contiene=None, limite_objetos: int = 20000, max_espacios: int = 60,
              timeout_s: float = 10.0, timeout_lectura_s: float = 60.0) -> dict:
    """Lectura estructurada de un plano (espacios, bloques, unidades). Solo lectura."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    if not previo.get("dibujo_activo"):
        return {"ok": False, "error": "sin_dibujo", "detalle": "AutoCAD esta abierto pero no hay ningun dibujo activo."}
    return _correr(
        PROBE_PLANO, timeout_lectura_s,
        [json.dumps({"destino_contiene": destino_contiene, "limite_objetos": int(limite_objetos), "max_espacios": int(max_espacios)})],
        mensaje_timeout=(f"La lectura del plano no termino en {timeout_lectura_s:g} s. Baja limite_objetos (ahora {limite_objetos}) "
                         "o sube [autocad].timeout_lectura_s en config.toml."))


def zoom_extents(timeout_s: float = 10.0) -> dict:
    """Zoom Extents de la vista actual. Solo mueve la vista, no cambia objetos."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    if not previo.get("dibujo_activo"):
        return {"ok": False, "error": "sin_dibujo", "detalle": "AutoCAD esta abierto pero no hay ningun dibujo activo."}
    return _correr(PROBE_VISTA, timeout_s)


def leer_bloques(nombres=None, limite: int = 5000, max_posiciones: int = 200,
                 timeout_s: float = 10.0, timeout_lectura_s: float = 60.0) -> dict:
    """Bloques insertados en el modelo. Primero comprueba (en `timeout_s`) que AutoCAD responde."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    if not previo.get("dibujo_activo"):
        return {"ok": False, "error": "sin_dibujo", "detalle": "AutoCAD esta abierto pero no hay ningun dibujo activo."}
    args = json.dumps({"nombres": list(nombres) if nombres else None, "limite": int(limite),
                       "max_posiciones": int(max_posiciones)})
    return _correr(
        PROBE_BLOQUES, timeout_lectura_s, [args],
        mensaje_timeout=(f"La lectura de bloques no termino en {timeout_lectura_s:g} s. El dibujo puede ser muy grande: "
                         f"baja limite_objetos (ahora {limite}) o sube [autocad].timeout_lectura_s en config.toml."))


def plano_crudo(timeout_s: float = 10.0, timeout_lectura_s: float = 60.0, cache_dir=None, ignorar_cache_bloque: bool = False, progreso=None) -> dict:
    """Lectura cruda del plano activo (textos, poligonos cerrados, bloques con su caja, unidades) para el escaner de zonas."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    if not previo.get("dibujo_activo"):
        return {"ok": False, "error": "sin_dibujo", "detalle": "AutoCAD esta abierto pero no hay ningun dibujo activo."}
    return _correr(PROBE_ZONAS, timeout_lectura_s, [json.dumps({"tiempo_max_s": max(5.0, timeout_lectura_s - 15), **({"cache_dir": str(cache_dir)} if cache_dir else {}),
                                                                                              **({"ignorar_cache_bloque": True} if ignorar_cache_bloque else {}),
                                                                                              **({"progreso": str(progreso)} if progreso else {})})],
                   mensaje_timeout=f"La lectura del plano no termino en {timeout_lectura_s:g} s (plano muy grande o AutoCAD ocupado).")


def inventario_plano(timeout_s: float = 10.0, timeout_lectura_s: float = 60.0) -> dict:
    """Que hay en el espacio modelo por capa y tipo de objeto (rellenos, solidos, polilineas con grosor...)."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    return _correr(PROBE_ZONAS, timeout_lectura_s, [json.dumps({"modo": "inventario", "tiempo_max_s": max(5.0, timeout_lectura_s - 15)})],
                   mensaje_timeout=f"El inventario no termino en {timeout_lectura_s:g} s.")


def extraer_patrones(destino_contiene=None, timeout_s: float = 10.0, timeout_lectura_s: float = 60.0) -> dict:
    """Mina y extrae patrones de diseno e intenciones de un plano terminado."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    if not previo.get("dibujo_activo"):
        return {"ok": False, "error": "sin_dibujo", "detalle": "AutoCAD esta abierto pero no hay ningun dibujo activo."}
    return _correr(PROBE_PATRONES, timeout_lectura_s)


def ubicar_por_intencion(args: dict, timeout_s: float = 10.0, timeout_escritura_s: float = 30.0) -> dict:
    """Ubica productos en AutoCAD segun una intencion arquitectonica."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    if not previo.get("dibujo_activo"):
        return {"ok": False, "error": "sin_dibujo", "detalle": "AutoCAD esta abierto pero no hay ningun dibujo activo."}
    return _correr(PROBE_INTENCIONES, timeout_escritura_s, [json.dumps(args)])



def diseno(args: dict, timeout_s: float = 10.0, timeout_op_s: float = 30.0) -> dict:
    """Operaciones de diseno por anfitrion (leer contexto, listar anfitriones, insertar colocaciones)."""
    previo = estado(timeout_s)
    if not previo.get("ok"):
        return previo
    if not previo.get("dibujo_activo"):
        return {"ok": False, "error": "sin_dibujo", "detalle": "AutoCAD esta abierto pero no hay ningun dibujo activo."}
    return _correr(PROBE_DISENO, timeout_op_s, [json.dumps(args)],
                   mensaje_timeout=(f"La operacion no termino en {timeout_op_s:g} s. Si era una insercion, NO se sabe si quedo a medias: "
                                    "revisa el dibujo (Ctrl+Z deshace) y cierra cualquier dialogo abierto."))
