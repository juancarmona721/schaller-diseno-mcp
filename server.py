"""diseno-mcp: servidor MCP interno para el equipo de diseno. Por ahora, todo es de SOLO LECTURA."""
import functools
import json
import math
import time
import os
import tomllib
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import acad
import fichas
import metricas
import salud
import guia_diseno
import motor_ubicacion
import operaciones
import productos
import zonas_motor
import referencias

AQUI = Path(__file__).resolve().parent


def cargar_config() -> dict:
    ruta = Path(os.environ.get("DISENO_MCP_CONFIG") or AQUI / "config.toml")
    with open(ruta, "rb") as fh:
        return tomllib.load(fh)


CFG = cargar_config()

# Ajustes y registro de uso: en la carpeta del usuario, compartidos por cualquier copia del MCP (como los perfiles).
_RAIZ_USUARIO = Path.home() / ".schaller-diseno"
RUTA_AJUSTES = Path(os.environ.get("SCHALLER_AJUSTES") or _RAIZ_USUARIO / "ajustes.json")
RUTA_USO = Path(os.environ.get("SCHALLER_USO") or _RAIZ_USUARIO / "logs" / "uso.jsonl")
RUTA_CONEXION = Path(os.environ.get("SCHALLER_CONEXION") or _RAIZ_USUARIO / "estado_conexion.json")
RUTA_OPERACIONES = Path(os.environ.get("SCHALLER_OPERACIONES") or _RAIZ_USUARIO / "operaciones")      # diario de operaciones de escritura


def _ajustes() -> dict:
    try:
        return json.loads(RUTA_AJUSTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _max_objetos() -> int:
    """Umbral del candado de planos grandes. En modo_prueba no se pide codigo."""
    return 10 ** 9 if _ajustes().get("modo_prueba") else int(CFG.get("escritura", {}).get("max_objetos_dibujo", 300))


def _registrar_uso(nombre: str, argumentos, ms: float, ok: bool, error=None) -> None:
    """Una linea por llamada: herramienta, duracion, resultado y un resumen CORTO de los argumentos. Nunca rompe la herramienta."""
    try:
        resumen = {k: (str(v)[:60]) for k, v in (argumentos or {}).items()}
        RUTA_USO.parent.mkdir(parents=True, exist_ok=True)
        with open(RUTA_USO, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "herramienta": nombre, "ms": int(ms), "ok": ok,
                                 "error": error, "args": resumen}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _serializado(fn):
    """Una herramienta que toca AutoCAD se ejecuta ENTERA antes de que empiece otra (Claude Desktop las lanza en paralelo y se pisaban)."""
    @functools.wraps(fn)
    def envuelta(*args, **kwargs):
        with acad.LOCK:
            return fn(*args, **kwargs)
    return envuelta

mcp = FastMCP("diseno-mcp", instructions=guia_diseno.instrucciones(referencias.REGLA))
REF_JSON = AQUI / "referencias_finales.json"


@mcp.prompt(name="guia_de_diseno", description="Como usar el MCP de diseno: flujo de zonas y ubicacion, y las reglas que no se negocian.")
def guia_de_diseno() -> str:
    """Pega la guia de trabajo en la conversacion (util si el asistente no la esta aplicando)."""
    return guia_diseno.FLUJO + "\nAplica esta guia en todo lo que sigue. Empieza revisando el estado de AutoCAD."


def _hoja():
    cfg = CFG.get("productos", {})
    return productos.cargar(cfg.get("ruta_hoja"), cfg.get("hoja", "Productos"))


def _error(e: productos.HojaError) -> dict:
    return {"ok": False, "error": "hoja_no_disponible", "detalle": str(e)}


@mcp.tool()
def ping() -> str:
    """Comprueba que el servidor responde. Devuelve 'ok'."""
    return "ok"


@mcp.tool()
def estado_mcp(verificar: bool = False) -> dict:
    """Estado del MCP (rapido, sin tocar AutoCAD): version, perfil de instalacion, capacidades, ultima conexion medida y entorno.

    Por defecto NO se conecta a AutoCAD: devuelve lo ultimo medido y marca `estado_actual_verificado: false` (no afirmes que AutoCAD esta
    disponible solo por eso). Con verificar=True hace UNA conexion real, guarda el resultado y lo devuelve actualizado. No recorre el plano.
    """
    verificado = None
    if verificar:
        t = time.perf_counter()
        est = acad.estado(timeout_s=float(CFG.get("autocad", {}).get("timeout_s", 10)))
        salud.guardar_conexion(RUTA_CONEXION, bool(est.get("ok")), (time.perf_counter() - t) * 1000, est.get("version_interna"))
        verificado = salud.leer_ultima_conexion(RUTA_CONEXION) or {"estado": "no_disponible"}
    try:
        n = len(mcp._tool_manager.list_tools())
    except Exception:
        n = None
    return salud.estado_basico(AQUI, RUTA_CONEXION, CARPETA_PERFILES, n, metricas.ACTIVA, verificado)


@mcp.tool()
def estado_autocad() -> dict:
    """Estado de AutoCAD (solo lectura): version, dibujo abierto, unidades y si es la version completa con COM.

    Si AutoCAD no responde en el tiempo limite de config.toml, devuelve un error claro.
    """
    return acad.estado(timeout_s=float(CFG.get("autocad", {}).get("timeout_s", 10)))


@mcp.tool()
def listar_productos(sistema: str | None = None) -> dict:
    """Lista los productos de la hoja: referencia, nombre corto, marca y sistema.

    sistema (opcional): filtra por sistema, sin importar mayusculas ni tildes (ej. 'iluminacion', 'audio').
    """
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    lista = productos.listar(prods, sistema)
    return {"ok": True, "total": len(lista), "productos": lista}


@mcp.tool()
def ver_producto(referencia: str) -> dict:
    """Todos los campos de un producto, por referencia exacta (ej. '1T8447DATR').

    Si el producto tiene campos inventados, trae el aviso 'DATOS DE PRUEBA: <campos>'.
    Si la referencia esta repetida (p. ej. 'SIN REFERENCIA'), devuelve todas las filas con ese valor.
    """
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    hallados = productos.ver(prods, referencia)
    if not hallados:
        return {"ok": False, "error": "no_encontrado",
                "detalle": f"No hay ninguna fila con la referencia '{referencia}'. Prueba buscar_producto."}
    fichas = [productos.ficha(p) for p in hallados]
    if len(fichas) == 1:
        return {"ok": True, "producto": fichas[0]}
    return {"ok": True, "aviso": f"Hay {len(fichas)} filas con la referencia '{referencia}'; distingue por fila_excel.",
            "productos": fichas}


@mcp.tool()
def buscar_producto(texto: str) -> dict:
    """Busca por texto en la referencia, el nombre corto y el nombre en Odoo (sin importar mayusculas ni tildes)."""
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    r = productos.buscar(prods, texto)
    return {"ok": True, "total": len(r), "productos": r}


@mcp.tool()
def validar_hoja() -> dict:
    """Revisa la hoja: referencias repetidas o 'SIN REFERENCIA', campos vacios y campos inventados, por producto.

    'N/A' es un valor valido, no un campo vacio.
    """
    try:
        enc, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    return {"ok": True, **productos.validar(prods, enc)}


def _tiempos() -> dict:
    a = CFG.get("autocad", {})
    return {"timeout_s": float(a.get("timeout_s", 10)), "timeout_lectura_s": float(a.get("timeout_lectura_s", 60))}


def _producto_unico(referencia, fila_excel=None, prods=None):
    """(producto, None) si hay exactamente uno; (None, dict_de_error) si no. `prods` evita releer el Excel."""
    if prods is None:
        try:
            _, prods = _hoja()
        except productos.HojaError as e:
            return None, _error(e)
    hallados = productos.ver(prods, referencia)
    if fila_excel is not None:
        hallados = [p for p in hallados if p["_fila"] == fila_excel]
    if not hallados:
        return None, {"ok": False, "error": "no_encontrado",
                      "detalle": f"No hay ninguna fila con la referencia '{referencia}'. Prueba buscar_producto."}
    if len(hallados) > 1:
        return None, {"ok": False, "error": "referencia_ambigua",
                      "detalle": "Hay varias filas con esa referencia; repite la llamada con fila_excel.",
                      "filas": [{"fila_excel": p["_fila"], "nombre_corto": p.get(productos.CORTO)} for p in hallados]}
    return hallados[0], None


def _base(p: dict) -> dict:
    return {"referencia": p.get(productos.REF), "nombre_corto": p.get(productos.CORTO), "fila_excel": p["_fila"]}


def _escritura() -> dict:
    return CFG.get("escritura", {})


def _escribir(args: dict) -> dict:
    cfg = _escritura()
    args = {**args, "max_objetos": int(cfg.get("max_objetos_dibujo", 300))}
    t = _tiempos()
    return acad.escribir(args, timeout_s=t["timeout_s"], timeout_escritura_s=float(cfg.get("timeout_escritura_s", 30)))


def _escritura_off() -> dict | None:
    if not _escritura().get("habilitada", False):
        return {"ok": False, "error": "escritura_desactivada",
                "detalle": "Las herramientas que modifican el dibujo estan apagadas ([escritura].habilitada en config.toml)."}
    return None


def nombre_capa(prefijo: str, sistema) -> str:
    """DL-TEST- + sistema en mayusculas, sin tildes ni caracteres raros (ej. 'Cinta LED' -> DL-TEST-CINTA-LED)."""
    limpio = "".join(c if c.isalnum() else "-" for c in productos.norm(sistema).upper()).strip("-")
    return f"{prefijo}{limpio or 'PRODUCTOS'}"


@mcp.tool()
def crear_bloque_producto(referencia: str, fila_excel: int | None = None, tamano: float = 100.0,
                          ejecutar: bool = False, confirmacion: str | None = None) -> dict:
    """MODIFICA EL DIBUJO (solo agrega): crea la definicion de bloque PROVISIONAL de un producto.

    Usa el nombre de la columna 'Bloque en CAD' de la hoja. El simbolo es un circulo con el nombre del bloque
    (no el simbolo real del fabricante). `tamano` es el diametro, en unidades del dibujo.
    Por defecto es un ENSAYO: dice que haria sin tocar el dibujo; con ejecutar=True lo crea.
    Si el bloque ya existe no se toca. En dibujos grandes (planos reales) solo escribe con `confirmacion` (ver CANDADO).
    """
    if (off := _escritura_off()):
        return off
    if tamano <= 0:
        return {"ok": False, "error": "tamano_invalido", "detalle": "tamano debe ser mayor que 0."}
    p, err = _producto_unico(referencia, fila_excel)
    if err:
        return err
    nombres = productos.bloques_cad(p)
    if not nombres:
        return {"ok": False, "error": "sin_bloque_asignado", **_base(p),
                "detalle": "La hoja no tiene nombre de bloque CAD para este producto (columna vacia)."}
    r = _escribir({"op": "crear_bloque", "nombres": nombres, "tamano": float(tamano), "ejecutar": bool(ejecutar),
                   "confirmacion": confirmacion})
    return {**_base(p), **r, **({} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."})}


@mcp.tool()
def insertar_producto(referencia: str, puntos: list[list[float]], rotacion_grados: float = 0.0,
                      fila_excel: int | None = None, ejecutar: bool = False, confirmacion: str | None = None) -> dict:
    """MODIFICA EL DIBUJO (solo agrega): inserta copias del bloque de un producto en los puntos [[x, y], ...].

    Coordenadas en unidades del dibujo. Las copias van en la capa DL-TEST-<SISTEMA> (se crea si no existe).
    El bloque debe existir ya (ver crear_bloque_producto). Si el producto tiene varios nombres de bloque, usa el primero.
    Por defecto es un ENSAYO: no toca el dibujo; con ejecutar=True inserta. Maximo de puntos en config.toml.
    """
    if (off := _escritura_off()):
        return off
    maximo = int(_escritura().get("max_puntos", 100))
    if not puntos or len(puntos) > maximo:
        return {"ok": False, "error": "puntos_invalidos", "detalle": f"Indica entre 1 y {maximo} puntos [x, y]."}
    try:
        pts = [[float(x), float(y)] for x, y in puntos]
    except (TypeError, ValueError):
        return {"ok": False, "error": "puntos_invalidos", "detalle": "Cada punto debe ser [x, y] con numeros."}
    if any(abs(v) > 1e9 or v != v for pt in pts for v in pt):
        return {"ok": False, "error": "puntos_invalidos", "detalle": "Coordenadas fuera de rango."}
    p, err = _producto_unico(referencia, fila_excel)
    if err:
        return err
    nombres = productos.bloques_cad(p)
    if not nombres:
        return {"ok": False, "error": "sin_bloque_asignado", **_base(p),
                "detalle": "La hoja no tiene nombre de bloque CAD para este producto (columna vacia)."}
    capa = nombre_capa(_escritura().get("prefijo_capa", "DL-TEST-"), p.get(productos.SISTEMA))
    r = _escribir({"op": "insertar", "nombre": nombres[0], "capa": capa, "puntos": pts,
                   "rotacion_grados": float(rotacion_grados), "ejecutar": bool(ejecutar), "confirmacion": confirmacion})
    aviso = {} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."}
    return {**_base(p), **r, **aviso}


@mcp.tool()
def insertar_productos(items: list[dict], ejecutar: bool = False, confirmacion: str | None = None) -> dict:
    """MODIFICA EL DIBUJO (solo agrega): inserta VARIOS productos de una vez.

    items: lista de {"referencia": "...", "x": n, "y": n, "rotacion_grados": 0 (opcional), "fila_excel": n (solo si la
    referencia esta repetida)}. Coordenadas en unidades del dibujo. Cada producto va en la capa DL-TEST-<SISTEMA>.
    TODO O NADA: si un item es invalido o falta algun bloque en el dibujo, no se inserta nada y se lista cada problema.
    Por defecto es un ENSAYO (no toca el dibujo); con ejecutar=True inserta. Maximo de items en config.toml.
    """
    if (off := _escritura_off()):
        return off
    maximo = int(_escritura().get("max_puntos", 100))
    if not isinstance(items, list) or not items or len(items) > maximo:
        return {"ok": False, "error": "items_invalidos", "detalle": f"Indica entre 1 y {maximo} items."}
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    prefijo = _escritura().get("prefijo_capa", "DL-TEST-")
    grupos, problemas, resumen = {}, [], []
    for i, it in enumerate(items, start=1):
        try:
            x, y = float(it["x"]), float(it["y"])
            rot = float(it.get("rotacion_grados", 0) or 0)
            if any(abs(v) > 1e9 or v != v for v in (x, y, rot)):
                raise ValueError
        except (TypeError, ValueError, KeyError, AttributeError):
            problemas.append({"item": i, "error": "coordenadas_invalidas", "detalle": "Cada item necesita x e y numericos."})
            continue
        p, err = _producto_unico(it.get("referencia"), it.get("fila_excel"), prods)
        if err:
            problemas.append({"item": i, "referencia": it.get("referencia"), **{k: v for k, v in err.items() if k != "ok"}})
            continue
        nombres = productos.bloques_cad(p)
        if not nombres:
            problemas.append({"item": i, "referencia": it.get("referencia"), "error": "sin_bloque_asignado",
                              "detalle": "La hoja no tiene nombre de bloque CAD para este producto."})
            continue
        capa = nombre_capa(prefijo, p.get(productos.SISTEMA))
        grupos.setdefault((nombres[0], capa), []).append([x, y, rot])
        resumen.append({"item": i, "referencia": p.get(productos.REF), "bloque": nombres[0], "capa": capa, "x": x, "y": y})
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se inserto nada: corrige estos items.",
                "problemas": problemas}
    r = _escribir({"op": "insertar_varios", "ejecutar": bool(ejecutar), "confirmacion": confirmacion,
                   "grupos": [{"nombre": n, "capa": c, "puntos": pts} for (n, c), pts in grupos.items()]})
    aviso = {} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."}
    return {**r, "items": resumen, **aviso}


@mcp.tool()
def insertar_bloques(items: list[dict], ejecutar: bool = False, confirmacion: str | None = None) -> dict:
    """MODIFICA EL DIBUJO (solo agrega): inserta bloques de la BIBLIOTECA por su nombre (no usa la hoja de Excel).

    items: [{"bloque": "<nombre exacto, ej. 'Mira R_Davide Groppi'>", "x": n, "y": n, "rotacion_grados": 0 (opcional),
    "largo": n (opcional), "escala_x": n, "escala_y": n (opcionales)}]. x, y es el punto base del bloque (en la mayoria, su centro).
    ADAPTAR UN BLOQUE: el bloque de la biblioteca es la referencia de forma; con `largo` (en unidades del dibujo) se estira sobre su
    eje X local hasta ese largo (p. ej. una tira lineal a la medida de una pared; con rotacion_grados=90 queda vertical), o se
    da escala_x / escala_y. Sigue siendo el MISMO bloque (mismo nombre y atributos), solo insertado con otra escala.
    Los bloques deben existir ya en el plano (copiarlos antes con importar_biblioteca). Van en la capa [escritura].capa_bloques
    (por defecto SCH_BLOQUES). TODO O NADA: si un item es invalido o falta un bloque, no se inserta nada.
    Por defecto es un ENSAYO; con ejecutar=True inserta. En planos grandes exige `confirmacion` (CANDADO: el codigo que
    sale en la linea de comandos de AutoCAD; pidelo a la persona, nunca lo inventes ni lo repitas de memoria).
    """
    if (off := _escritura_off()):
        return off
    maximo = int(_escritura().get("max_puntos", 100))
    if not isinstance(items, list) or not items or len(items) > maximo:
        return {"ok": False, "error": "items_invalidos", "detalle": f"Indica entre 1 y {maximo} items."}
    capa = str(_escritura().get("capa_bloques", "SCH_BLOQUES"))
    grupos, problemas = {}, []
    for i, it in enumerate(items, start=1):
        try:
            nombre = str(it["bloque"]).strip()
            x, y = float(it["x"]), float(it["y"])
            rot = float(it.get("rotacion_grados", 0) or 0)
            largo, ex, ey = (float(it[k]) if it.get(k) else None for k in ("largo", "escala_x", "escala_y"))
            if (not nombre or any(abs(v) > 1e9 or v != v for v in (x, y, rot))
                    or any(v is not None and not 0 < v <= 1e6 for v in (largo, ex, ey))
                    or (largo is not None and ex is not None)):
                raise ValueError
        except (TypeError, ValueError, KeyError, AttributeError):
            problemas.append({"item": i, "error": "item_invalido",
                              "detalle": "Cada item necesita bloque (texto), x e y numericos; largo/escalas, si se dan, mayores que 0 "
                                         "(y no a la vez largo y escala_x)."})
            continue
        grupos.setdefault((nombre, largo, ex, ey), []).append([x, y, rot])
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se inserto nada: corrige estos items.",
                "problemas": problemas}
    r = _escribir({"op": "insertar_varios", "ejecutar": bool(ejecutar), "confirmacion": confirmacion,
                   "grupos": [{"nombre": n, "capa": capa, "puntos": pts, "largo": lg, "escala_x": ex, "escala_y": ey}
                              for (n, lg, ex, ey), pts in grupos.items()]})
    aviso = {} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."}
    return {**r, "capa": capa, **aviso}


@mcp.tool()
def importar_simbolos(origen_contiene: str, destino_contiene: str | None = None,
                      referencias: list[str] | None = None, ejecutar: bool = False,
                      confirmacion: str | None = None) -> dict:
    """MODIFICA EL DIBUJO DESTINO (solo agrega): copia los SIMBOLOS reales (definiciones de bloque) de un plano abierto.

    origen_contiene: fragmento del nombre del plano ORIGEN (solo se lee su geometria; debe coincidir con 1 documento abierto).
    destino_contiene: fragmento del nombre del dibujo DESTINO; si se omite, el dibujo activo. Se niega a escribir si el
    destino tiene mas de [escritura].max_objetos_dibujo objetos (usa un dibujo de prueba).
    referencias: productos a importar; si se omite, todos los de la hoja que tengan nombre de bloque.
    Los simbolos se escalan a las unidades del destino segun la escala tipica con que se insertan en el origen, y se
    CENTRAN en su punto base (asi, al insertar un producto en x, y, ese punto es el centro del simbolo).
    Por defecto es un ENSAYO (lee el origen y dice que haria); con ejecutar=True los crea. Si el bloque ya existe, no se toca.
    """
    if (off := _escritura_off()):
        return off
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    problemas, nombres = [], []
    if referencias is None:
        elegidos = [p for p in prods if productos.bloques_cad(p)]
    else:
        elegidos = []
        for ref in referencias:
            p, err = _producto_unico(ref, None, prods)
            if err:
                problemas.append({"referencia": ref, **{k: v for k, v in err.items() if k != "ok"}})
            elif not productos.bloques_cad(p):
                problemas.append({"referencia": ref, "error": "sin_bloque_asignado"})
            else:
                elegidos.append(p)
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se importo nada: corrige estas referencias.",
                "problemas": problemas}
    for p in elegidos:
        for n in productos.bloques_cad(p):
            if n not in nombres:
                nombres.append(n)
    maximo = int(CFG.get("simbolos", {}).get("max_simbolos", 60))
    if not nombres or len(nombres) > maximo:
        return {"ok": False, "error": "cantidad_invalida", "detalle": f"Se necesitan entre 1 y {maximo} bloques (hay {len(nombres)})."}
    r = acad.importar_simbolos(
        {"origen_contiene": origen_contiene, "destino_contiene": destino_contiene, "nombres": nombres,
         "ejecutar": bool(ejecutar), "max_objetos": int(_escritura().get("max_objetos_dibujo", 300)),
         "confirmacion": confirmacion},
        timeout_s=_tiempos()["timeout_s"], timeout_importar_s=float(CFG.get("simbolos", {}).get("timeout_importar_s", 300)))
    aviso = {} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: se leyo el origen pero no se modifico nada. Repite con ejecutar=True."}
    return {**r, "bloques_pedidos": nombres, **aviso}


@mcp.tool()
def dibujar_espacios(espacios: list[dict], altura_texto: float = 200.0, ejecutar: bool = False,
                     confirmacion: str | None = None) -> dict:
    """MODIFICA EL DIBUJO (solo agrega): dibuja espacios como rectangulos (muros esquematicos) con su nombre en el centro.

    espacios: [{"nombre": "Sala", "x0": n, "y0": n, "x1": n, "y1": n}] (esquinas opuestas, en unidades del dibujo; x1>x0, y1>y0).
    Rectangulos en la capa [escritura].capa_muros (SCH_MUROS) y nombres en [escritura].capa_espacios (SCH_ESPACIOS).
    Sirve para armar plantas de prueba. Por defecto es un ENSAYO; con ejecutar=True dibuja. En planos grandes exige
    `confirmacion` (CANDADO). Nunca borra ni cambia lo existente.
    """
    if (off := _escritura_off()):
        return off
    maximo = int(_escritura().get("max_puntos", 100))
    if not isinstance(espacios, list) or not espacios or len(espacios) > maximo:
        return {"ok": False, "error": "espacios_invalidos", "detalle": f"Indica entre 1 y {maximo} espacios."}
    limpios, problemas = [], []
    for i, e in enumerate(espacios, start=1):
        try:
            nombre = str(e["nombre"]).strip()
            x0, y0, x1, y1 = (float(e[k]) for k in ("x0", "y0", "x1", "y1"))
            if not nombre or x1 <= x0 or y1 <= y0 or any(abs(v) > 1e9 or v != v for v in (x0, y0, x1, y1)):
                raise ValueError
        except (TypeError, ValueError, KeyError, AttributeError):
            problemas.append({"espacio": i, "detalle": "Necesita nombre y x0<x1, y0<y1 numericos."})
            continue
        limpios.append({"nombre": nombre, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se dibujo nada: corrige estos espacios.",
                "problemas": problemas}
    if not 0 < float(altura_texto) <= 1e6:
        return {"ok": False, "error": "altura_invalida", "detalle": "altura_texto debe ser mayor que 0."}
    cfg = _escritura()
    r = _escribir({"op": "espacios", "espacios": limpios, "altura_texto": float(altura_texto), "ejecutar": bool(ejecutar),
                   "confirmacion": confirmacion, "capa_muros": str(cfg.get("capa_muros", "SCH_MUROS")),
                   "capa_espacios": str(cfg.get("capa_espacios", "SCH_ESPACIOS"))})
    aviso = {} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."}
    return {**r, **aviso}


def nombre_visible(bloque: str) -> str:
    """'Durastrip IP20_75W_Targetti' -> 'Durastrip IP20 75W' (sin la marca final; guiones bajos como espacios)."""
    base = str(bloque).rpartition("_")[0] or str(bloque)
    return " ".join(base.replace("_", " ").split())


@mcp.tool()
def ver_plano(destino_contiene: str | None = None, limite_objetos: int = 20000, max_espacios: int = 60) -> dict:
    """SOLO LECTURA: resumen simple del plano (unidades, espacios con texto, bloques). Para DETECTAR ZONAS usa escanear_zonas (es la herramienta
    principal y entiende planos sin rotulos); esta es un apoyo. No tomes capturas de pantalla: no hace falta.

    Devuelve las unidades (con aviso si no cuadran con el tamano de los bloques), los ESPACIOS detectados (poligonos cerrados con
    un texto dentro: nombre, limites x0,y0,x1,y1, ancho, alto, area y los productos que contiene), los bloques colocados por
    nombre y los que quedan fuera de todo espacio. Con esto se calculan posiciones sin adivinar coordenadas.
    destino_contiene: fragmento del nombre del dibujo; si se omite, el dibujo activo. No devuelve el nombre del archivo.
    En planos reales los nombres de espacios y bloques pueden ser datos del cliente: no mostrarlos en el chat.
    """
    return acad.ver_plano(destino_contiene, int(limite_objetos), int(max_espacios), **_tiempos())


# Datos propios de cada proyecto (roles de bloques, zonas manuales): NO se versionan. Viven en UN solo sitio por usuario, compartido por
# cualquier copia del MCP (la instalada para Claude Desktop y la de desarrollo): si cada copia tuviera su carpeta, el perfil creado en una
# no lo veria la otra y el escaner devolveria 0 zonas sin ningun error. Se puede cambiar con SCHALLER_PERFILES.
CARPETA_PERFILES = Path(os.environ.get("SCHALLER_PERFILES") or Path.home() / ".schaller-diseno" / "perfiles")
CARPETA_CACHE = AQUI / "cache"
VOCAB = zonas_motor.cargar_vocabulario()


def _zonas_del_plano(forzar: bool = False, tipologia: str | None = None) -> dict:
    """Zonas del dibujo ACTIVO. La cache se identifica por dibujo + numero de objetos + perfil, asi que cambiar de plano no mezcla datos."""
    est = acad.estado(timeout_s=float(CFG.get("autocad", {}).get("timeout_s", 10)))
    if not est.get("ok"):
        return est
    nombre = est.get("dibujo_activo")
    if not nombre:
        return {"ok": False, "error": "sin_dibujo", "detalle": "No hay ningun dibujo activo en AutoCAD."}
    perfil = zonas_motor.cargar_perfil(CARPETA_PERFILES, nombre)
    clave = zonas_motor.clave_cache(nombre, int(est.get("objetos_en_modelo") or 0), perfil, tipologia, zonas_motor.version_motor())
    ruta = CARPETA_CACHE / f"zonas_{zonas_motor.slug_proyecto(nombre)}_{clave}.json"
    if not forzar and ruta.is_file():
        try:
            return {**json.loads(ruta.read_text(encoding="utf-8")), "origen_datos": "cache"}
        except (OSError, ValueError):
            pass
    t = _tiempos()
    raw = acad.plano_crudo(timeout_s=t["timeout_s"], timeout_lectura_s=max(t["timeout_lectura_s"], 60.0))
    if not raw.get("ok"):
        return raw
    res = zonas_motor.construir_zonas(raw, VOCAB, perfil, tipologia)
    res = {"ok": True, "plano": raw.get("plano"), "origen_datos": "lectura", "tiempo_lectura_s": raw.get("tiempo_lectura_s"),
           "leido": {"textos": len(raw["textos"]), "poligonos": len(raw["poligonos"]), "bloques": len(raw["bloques"]),
                      "definiciones": len(raw.get("definiciones") or {}),
                     "elementos_en_contenedores": raw.get("elementos_en_contenedores", 0)},
           "avisos": raw.get("avisos", []) + ([res["aviso_unidades"]] if res.get("aviso_unidades") else []), **res}
    try:
        CARPETA_CACHE.mkdir(exist_ok=True)
        ruta.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return res


def _diagnostico_sin_zonas(r: dict) -> dict:
    """Explica por que no hubo zonas y que hacer, para que el asistente no tenga que adivinar ni tomar capturas."""
    causas, pasos = [], []
    if not r.get("textos_con_nombre_de_espacio"):
        causas.append(f"Ninguno de los {r.get('textos', 0)} textos leidos es un nombre de espacio conocido (el plano no rotula ambientes).")
    if not r.get("poligonos_con_area_de_recinto"):
        causas.append(f"Ninguno de los {r.get('poligonos', 0)} poligonos cerrados tiene area de recinto (1.5 a 4000 m2).")
    elif not r.get("recintos_candidatos"):
        causas.append(f"Hay {r['poligonos_con_area_de_recinto']} poligonos con area de recinto, pero ninguno tiene tamano de habitacion (3 m2 o mas y lado de 1.2 m o mas), "
                      "o estan duplicados o contienen a otros (contornos).")
    if not r.get("bloques_con_rol"):
        causas.append(f"Ninguno de los {r.get('bloques', 0)} bloques tiene un rol de mobiliario (nombres genericos o sin perfil del proyecto).")
    pasos.append("Revisa `sugerencias_roles` y clasifica los bloques con perfil_proyecto(accion='rol'); vuelve a escanear con forzar_recarga=True.")
    pasos.append("Si el plano trae las zonas como puntos conocidos, registralas con perfil_proyecto(accion='zona').")
    pasos.append("Usa bloques_en_dibujo (lista de bloques con posicion y capa) y listar_anfitriones para elegir anfitriones sin depender de zonas.")
    pasos.append("No tomes capturas ni controles el equipo: es lento y no hace falta.")
    return {"por_que_no_hay_zonas": causas, "que_hacer": pasos}


@mcp.tool()
@_serializado
def escanear_zonas(destino_contiene: str | None = None, forzar_recarga: bool = False, tipologia: str | None = None) -> dict:
    """SOLO LECTURA: detecta zonas/espacios del plano ACTIVO para CUALQUIER tipo de proyecto (vivienda, oficina, hotel, comercial,
    restaurante, salud, educacion, industrial). Se adapta al plano en vez de asumir una casa.

    Evidencia: textos con nombre de espacio (vocabulario editable vocabulario_espacios.json, es/en/it) + poligono cerrado que los
    contiene (limites y area reales); roles de mobiliario (cama, escritorio, mostrador...) por nombre, por vocabulario o por el
    PERFIL del proyecto; y, sin textos ni poligonos, zonas inferidas por agrupamiento (confianza baja).
    Devuelve zonas (nombre, tipo_espacio, x, y, bbox, area_m2, origen, confianza, muebles), la tipologia detectada del proyecto y
    `sugerencias_roles`: bloques con nombre anonimo que conviene clasificar con perfil_proyecto(accion='rol').
    Cache por dibujo; forzar_recarga=True si cambiaste el plano sin cambiar su numero de objetos. tipologia fuerza el tipo de proyecto.
    `vistas`: grupos de geometria separados dentro del dibujo (p. ej. dos plantas lado a lado); cada zona trae su `vista`. Una vista NO es un piso:
    no asumas que la de la izquierda es la planta baja; el nivel solo se nombra si un texto cercano lo dice (`nombre`).
    En planos reales los nombres de espacios y bloques pueden ser datos del cliente: no los muestres en el chat sin necesidad.
    MODO: si el usuario pidio SOLO consultar, evaluar o escanear, no coloques nada. Si pidio colocar, no le preguntes: si el plano NO trae
    nombres de ambientes o hay bloques anonimos, decide el rol mas probable segun tamano/posicion (sugerencias_roles), registralo con
    perfil_proyecto(accion='rol'), declaralo como supuesto y coloca con UNA llamada a ubicar_varios. No llames herramientas en paralelo.
    Con 0 zonas el resultado trae `diagnostico` (que se leyo, por que no hubo zonas y que hacer): sigue esa ruta y no tomes capturas.
    """
    res = _zonas_del_plano(forzar_recarga, tipologia)
    if isinstance(res, dict) and res.get("ok"):
        res = {**res, "siguiente_paso": "Si el usuario pidio COLOCAR: no preguntes; clasifica tu los bloques sin rol (perfil_proyecto accion='rol'), "
                                        "elige anfitriones (listar_anfitriones una sola vez) y coloca TODO con UNA llamada a ubicar_varios(ejecutar=True); "
                                        "informa supuestos y omitidos al final. Si pidio solo CONSULTAR o evaluar: no coloques nada. "
                                        "Las zonas con candidato=true o confianza baja son HIPOTESIS (poligonos sin rotulo): usalas para decidir, pero declaralas como "
                                        "supuesto y no las presentes como confirmadas. Los muebles con rol_origen='inferido' vienen de la definicion de su bloque."}
        if not res.get("total"):
            res["diagnostico"] = _diagnostico_sin_zonas(res.get("resumen_lectura") or {})
    return res


@mcp.tool()
def perfil_proyecto(accion: str = "ver", bloque: str | None = None, rol: str | None = None, nombre: str | None = None,
                    tipo: str | None = None, x: float | None = None, y: float | None = None, tipologia: str | None = None,
                    atributos: dict | None = None) -> dict:
    """Perfil del PROYECTO ACTIVO: lo que es propio de este plano y el escaner no puede adivinar. Solo escribe un JSON local (perfiles/),
    no toca el dibujo. Acciones:
    - 'ver': muestra el perfil y los roles disponibles.
    - 'rol': bloque + rol -> clasifica un bloque anonimo (ej. bloque 'Mod-120', rol 'cama'); rol vacio lo quita.
    - 'ignorar': bloque -> el escaner lo descarta (puertas, vegetacion, marcos...).
    - 'zona': nombre + tipo + x + y -> agrega una zona manual (ej. un espacio sin texto ni poligono).
    - 'tipologia': tipologia -> fija el tipo de proyecto (vivienda, oficina, hotel, comercial, restaurante, salud, educacion, industrial).
    - 'atributos': bloque + atributos={...} -> RECUERDA lo que el usuario ya respondio sobre un bloque para no volver a preguntarlo
      (cabecera "N"/"S"/"E"/"O" de una cama, ancho_cama en m, filas, puntos [[x,y],...] exactos, etc.). Se fusiona con lo existente; un valor
      null borra esa clave; atributos={} borra todos los del bloque. escanear_zonas los devuelve en cada mueble y ubicar_en_anfitrion
      los usa solos como valores por defecto.
    """
    est = acad.estado(timeout_s=float(CFG.get("autocad", {}).get("timeout_s", 10)))
    if not est.get("ok"):
        return est
    dibujo = est.get("dibujo_activo")
    if not dibujo:
        return {"ok": False, "error": "sin_dibujo", "detalle": "No hay ningun dibujo activo."}
    perfil = zonas_motor.cargar_perfil(CARPETA_PERFILES, dibujo)
    if accion == "ver":
        return {"ok": True, "perfil": perfil, "roles_disponibles": VOCAB.nombres_roles, "tipologias": VOCAB.tipologias,
                "archivo": f"perfiles/{zonas_motor.slug_proyecto(dibujo)}.json"}
    if accion == "rol":
        if not bloque:
            return {"ok": False, "error": "falta_bloque"}
        if rol and rol not in VOCAB.nombres_roles:
            return {"ok": False, "error": "rol_desconocido", "detalle": f"Roles validos: {', '.join(VOCAB.nombres_roles)}."}
        if rol:
            perfil["roles_bloques"][bloque] = rol
        else:
            perfil["roles_bloques"].pop(bloque, None)
    elif accion == "ignorar":
        if not bloque:
            return {"ok": False, "error": "falta_bloque"}
        if bloque not in perfil["ignorar_bloques"]:
            perfil["ignorar_bloques"].append(bloque)
    elif accion == "zona":
        if not nombre or x is None or y is None:
            return {"ok": False, "error": "faltan_datos", "detalle": "Una zona manual necesita nombre, x e y (y opcionalmente tipo)."}
        perfil["zonas_manuales"] = [z for z in perfil["zonas_manuales"] if z["nombre"] != nombre] + [{"nombre": nombre, "tipo": tipo or "otro", "x": x, "y": y}]
    elif accion == "atributos":
        if not bloque or not isinstance(atributos, dict):
            return {"ok": False, "error": "faltan_datos", "detalle": "Indica bloque y atributos={clave: valor}."}
        guardados = perfil.setdefault("atributos_bloques", {})
        clave = next((k for k in guardados if k.casefold() == bloque.casefold()), bloque)
        if not atributos:
            guardados.pop(clave, None)
        else:
            actuales = dict(guardados.get(clave, {}))
            for k, v in atributos.items():
                if v is None:
                    actuales.pop(k, None)
                else:
                    actuales[k] = v
            if actuales:
                guardados[clave] = actuales
            else:
                guardados.pop(clave, None)
    elif accion == "tipologia":
        if tipologia not in VOCAB.tipologias:
            return {"ok": False, "error": "tipologia_desconocida", "detalle": f"Opciones: {', '.join(VOCAB.tipologias)}."}
        perfil["tipologia"] = tipologia
    else:
        return {"ok": False, "error": "accion_desconocida", "detalle": "Acciones: ver, rol, ignorar, zona, atributos, tipologia."}
    zonas_motor.guardar_perfil(CARPETA_PERFILES, dibujo, perfil)
    return {"ok": True, "perfil": perfil, "aviso": "Perfil guardado. Vuelve a llamar escanear_zonas: la cache se renueva sola."}


@mcp.tool()
def consultar_zona(zona: str) -> dict:
    """CONSULTA INSTANTANEA DE UNA ZONA (< 0.01 s): devuelve coordenadas, muebles y estado de un ambiente especifico."""
    z_low = zona.strip().lower()
    scan = escanear_zonas()
    if not scan.get("ok"):
        return scan
    coincidencias = []
    for z in scan.get("zonas", []):
        if z_low in z.get("nombre", "").lower() or z_low in z.get("tipo_espacio", "").lower():
            coincidencias.append(z)
    if not coincidencias:
        return {"ok": False, "error": "zona_no_encontrada", "detalle": f"No se encontro ninguna zona que coincida con '{zona}'."}
    return {"ok": True, "total": len(coincidencias), "zonas": coincidencias}


@mcp.tool()
def buscar_en_plano(termino: str, tipo_espacio: str | None = None, limite: int = 20) -> dict:
    """BUSQUEDA INSTANTANEA EN EL PLANO (< 0.01 s): busca recintos, muebles o zonas por cualquier palabra clave.

    Permite buscar al instante sin consultar AutoCAD repetidamente:
    - buscar_en_plano('comedor') -> devuelve las zonas de comedor, coordenadas y mesas.
    - buscar_en_plano('cama') -> devuelve las alcobas donde hay camas asociadas.
    - buscar_en_plano('baño') -> devuelve todos los baños del plano.
    - buscar_en_plano('cocina') -> devuelve la ubicación exacta de las cocinas.
    """
    scan = escanear_zonas()
    if not scan.get("ok"):
        return scan
    term = termino.strip().lower()
    coincidencias = []
    for z in scan.get("zonas", []):
        nom = z.get("nombre", "").lower()
        tipo = z.get("tipo_espacio", "").lower()
        muebles = " ".join(z.get("muebles", [])).lower()
        if term in nom or term in tipo or term in muebles:
            if not tipo_espacio or tipo_espacio.lower() in tipo:
                coincidencias.append(z)
                if len(coincidencias) >= limite:
                    break
    return {
        "ok": True,
        "plano": scan.get("plano"),
        "total": len(coincidencias),
        "resultados": coincidencias
    }


# Desactivada por ahora (no expuesta al asistente): clasificaba mobiliario con criterios distintos al escaner y confundia.
def extraer_patrones_diseno(destino_contiene: str | None = None) -> dict:
    """SOLO LECTURA: analiza un plano de diseno terminado para extraer el ADN de diseno de Schaller.

    Extrae relaciones relativas (vectores de intencion) en vez de coordenadas rigidas:
    - Distancia al muro mas cercano (para acento de arte o foseados).
    - Elemento anfitrion mas cercano (mesa, cama, isla, etc.).
    - Interdistancia ritmica entre luminarias o parlantes repetidos.
    - Intencion inferida (audio comensales, perimetro rasante, tarea cocina, etc.).
    Permite aprender los criterios de diseno de la firma a partir de planos historicos.
    """
    return acad.extraer_patrones(destino_contiene, **_tiempos())


@mcp.tool()
def ubicar_por_intencion(intencion: str, zona: str | None = None, zona_x: float | None = None,
                        zona_y: float | None = None, usar_seleccion: bool = False,
                        ejecutar: bool = True) -> dict:
    """UBICACION DE ALTA VELOCIDAD POR INTENCION ARQUITECTONICA: ubica productos segun reglas probadas.

    Intenciones soportadas:
    - 'audio_comedor_4x': 4 parlantes KEF enfrentados 2 y 2 centrados matematicamente sobre la mesa (ignorando sillas).
    - 'audio_bano_individual': 1 parlante KEF centrado en el compartimento de bano.
    - 'perimetro_cocina_durastrip': tira LED estanca IP68 continua con escala modular EWC (0.5) y ancho de 4 cm.
    - 'combo_cama_iluminacion': tira LED en cabecera + 6 spots CCTEvo perimetrales.
    - 'moon_ambiente': luminaria de suspension Moon 60 centrada en sala o estar.

    Parametros:
    - intencion: nombre de la intencion a aplicar.
    - zona: nombre del recinto (si se proporciona, busca su centro automaticamente con escanear_zonas).
    - zona_x, zona_y: coordenadas centrales del espacio (opcional si se pasa zona o usar_seleccion).
    - usar_seleccion: si True, toma el elemento o espacio seleccionado con el raton en AutoCAD.
    - ejecutar: True para insertar directamente en AutoCAD; False para ensayo de verificacion.
    """
    if (off := _escritura_off()):
        return off
    
    # Si se indico nombre de zona pero no coordenadas, resolver mediante escanear_zonas
    if zona and (zona_x is None or zona_y is None):
        res_zonas = _zonas_del_plano()
        if res_zonas.get("ok"):
            zona_low = zona.lower()
            for z in res_zonas.get("zonas", []):
                if zona_low in z.get("nombre", "").lower() or zona_low in z.get("tipo_espacio", "").lower():
                    zona_x, zona_y = z["x"], z["y"]
                    break
                    
    args = {
        "intencion": intencion,
        "zona_x": zona_x,
        "zona_y": zona_y,
        "usar_seleccion": usar_seleccion,
        "ejecutar": bool(ejecutar)
    }
    return acad.ubicar_por_intencion(args, **_tiempos())


@mcp.tool()
def ubicar_en_seleccion(intencion: str, ejecutar: bool = True) -> dict:
    """UBICACION INSTANTANEA EN SELECCION: aplica una intencion de diseno sobre lo que el usuario tiene seleccionado en AutoCAD.

    El usuario simplemente hace clic en una mesa, cama o zona en AutoCAD y pide ubicar la solucion.
    """
    return ubicar_por_intencion(intencion=intencion, usar_seleccion=True, ejecutar=ejecutar)


# ---------------------------------------------------------------------------------------------------------------------
# UBICACION POR ANFITRION (geometria real, sin coordenadas fijas): listar_anfitriones -> ubicar_en_anfitrion
# ---------------------------------------------------------------------------------------------------------------------
DISENO_ID_PREDETERMINADO = "d1"
# Errores que ocurren ANTES de tocar el dibujo: la operacion queda "fallida" (nada se escribio). Cualquier otro fallo de una escritura
# (tiempo agotado, error a mitad) deja la operacion "incierta" hasta reconciliarla con lo que haya en el dibujo.
_ERRORES_SIN_ESCRITURA = {"dibujo_grande_requiere_confirmacion", "confirmacion_invalida", "bloques_no_disponibles", "autocad_no_abierto", "sin_pywin32",
                          "sin_dibujo", "escritura_desactivada"}


def _diario() -> operaciones.Diario:
    return operaciones.Diario(RUTA_OPERACIONES)


def _reconciliar_previas(nombre_plano: str, existentes: list, u: float = 1.0) -> list[dict]:
    """Cierra las operaciones que quedaron pendientes o inciertas en este documento, mirando lo que hay realmente en el dibujo (marcas XData)."""
    d, doc, salida = _diario(), operaciones.doc_id(nombre_plano), []
    for pend in d.pendientes(doc):
        marcados = [{"item_id": e["item_id"], "handle": e.get("handle")} for e in existentes if e.get("op_id") == pend["op_id"]]
        sin_marca = [e for e in existentes if not e.get("item_id") and e.get("handle")]
        r = operaciones.reconciliar(pend.get("items", []), marcados, sin_marca, pend.get("previos", []), tol=operaciones.TOL_ADOPCION / (u or 1.0))
        d.finalizar(pend["op_id"], r["estado"], {k: r[k] for k in ("aplicados", "adoptables", "ambiguas", "pendientes")})
        mal_capa = sum(1 for e in existentes if e.get("op_id") == pend["op_id"] and e.get("capa_incorrecta"))
        salida.append({"op_id": pend["op_id"], "estado": r["estado"], "aplicadas": r["aplicados"], "faltan": len(r["pendientes"]),
                       "adoptables_sin_marca": len(r["adoptables"]), "ambiguas": len(r["ambiguas"]),
                       **({"con_capa_incorrecta": mal_capa} if mal_capa else {})})
    return salida


def _insertar_con_operacion(t: dict, nombre_plano: str, colocaciones: list, existentes: list, ejecutar: bool, confirmacion, unidad_m: float = 1.0) -> tuple[dict, str | None]:
    """Inserta dejando constancia: diario con la INTENCION antes de tocar el dibujo, XData en cada entidad y cierre con su estado real.
    Ensayo: sin diario. Si no se puede abrir el diario, NO se escribe (la trazabilidad es obligatoria en las escrituras)."""
    args = {"op": "insertar", "colocaciones": colocaciones, "ejecutar": bool(ejecutar), "confirmacion": confirmacion, "max_objetos": _max_objetos(),
            "unidad_m": unidad_m}
    if not ejecutar:
        return acad.diseno(args, **t), None
    op_id, d = operaciones.nuevo_operation_id(), _diario()
    try:
        d.iniciar(op_id, operaciones.doc_id(nombre_plano), operaciones.plan_hash(colocaciones), colocaciones,
                  previos=[e["handle"] for e in existentes if e.get("handle")])
    except OSError as e:
        return {"ok": False, "error": "diario_no_disponible", "detalle": f"No pude abrir el diario de operaciones ({e.__class__.__name__}); no se escribio nada."}, None
    args["operacion"] = {"id": op_id, "diario": str(RUTA_OPERACIONES), "cada": operaciones.CHECKPOINT_CADA}
    r = acad.diseno(args, **t)
    try:
        if r.get("ok"):
            info = r.get("operacion") or {}
            d.finalizar(op_id, "aplicada", {"insertados": r.get("insertados"), "piezas_marcadas": info.get("piezas_marcadas"), "fallos_xdata": info.get("fallos_xdata")})
        elif r.get("error") in _ERRORES_SIN_ESCRITURA:
            d.finalizar(op_id, "fallida", {"error": r.get("error")})
        else:
            d.finalizar(op_id, "incierta", {"error": r.get("error")})
    except OSError:
        pass
    return r, op_id


@mcp.tool()
@_serializado
def ubicar_varios(items: list[dict], ejecutar: bool = False, confirmacion: str | None = None) -> dict:
    """UBICA TODO UN DISENO EN UNA SOLA LLAMADA (rapido): varias ubicaciones sobre varios anfitriones, leyendo el plano UNA vez.

    items = [{"receta": ..., "anfitrion": "<bloque>", "opciones": {...}?, "cerca_de": [x, y]?}, ...]; mismas recetas y opciones que
    ubicar_en_anfitrion. Es ~10 veces mas rapido que llamar a ubicar_en_anfitrion una por una (cada una releia el plano entero) y no deja
    que se pisen las llamadas en paralelo. Un item que no se puede resolver (anfitrion inexistente, receta imposible, sin muros) se OMITE y
    se reporta; no frena a los demas. No duplica lo ya colocado ni lo colocado por otro item del mismo lote. Aplica solos los atributos
    guardados en el perfil de cada mueble (cabecera, ancho_cama, puntos...). Con ejecutar=False es un ensayo; con ejecutar=True inserta todo
    junto. NO preguntes ni pidas ensayo: decide y ejecuta con ejecutar=True; informa supuestos y omitidos al final. Planos grandes: pide `confirmacion` (codigo de la linea de comandos de AutoCAD) salvo que ajustes(modo_prueba=True).
    Devuelve, por item, estado (ok/omitido), cuantas piezas, avisos y motivo; y los totales por producto.
    """
    if (off := _escritura_off()):
        return off
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "items_invalidos", "detalle": "Pasa una lista de items [{receta, anfitrion, opciones?}]."}
    t = _diseno_tiempos()
    bbox_blk = [v["bloque"] for v in motor_ubicacion.PRODUCTOS.values() if v.get("ancla") == "bbox"]
    ped = [{"nombre": it.get("anfitrion") if isinstance(it, dict) else None, "cerca_de": it.get("cerca_de") if isinstance(it, dict) else None}
           for it in items]
    ctx = acad.diseno({"op": "contexto_varios", "anfitriones": ped, "bloques_bbox": bbox_blk}, **t)
    if not ctx.get("ok"):
        return ctx
    perfil = zonas_motor.cargar_perfil(CARPETA_PERFILES, ctx["plano"]) if ctx.get("plano") else zonas_motor.perfil_vacio()
    muros = [tuple(m) for m in ctx.get("muros", [])]
    existentes = list(ctx.get("existentes", []))
    u = float(ctx.get("unidad_m") or 1.0)                 # metros por unidad del dibujo (declarada o corregida por el tamano de lo dibujado)
    existentes_dibujo = list(existentes)                  # lo que habia en el dibujo (sin lo que sumen los items de este lote)
    previas = _reconciliar_previas(ctx.get("plano") or "", existentes_dibujo, u) if ejecutar else []
    if any(x["ambiguas"] for x in previas):
        return {"ok": False, "error": "operacion_previa_ambigua", "operaciones_previas": previas,
                "detalle": "Una operacion anterior quedo a medias y hay piezas sin marca que no se pueden atribuir con seguridad. "
                           "Revisa el dibujo (o usa quitar_colocaciones) antes de volver a escribir aqui. No se escribio nada."}
    todas, detalle = [], []
    for it, h in zip(items, ctx.get("hosts", [])):
        r = {"receta": it.get("receta") if isinstance(it, dict) else None, "anfitrion": h.get("nombre")}
        if not isinstance(it, dict) or it.get("receta") not in motor_ubicacion.RECETAS:
            detalle.append({**r, "estado": "omitido", "error": "receta_desconocida", "detalle": f"Recetas: {', '.join(motor_ubicacion.RECETAS)}."})
            continue
        if "error" in h:
            detalle.append({**r, "estado": "omitido", "error": h["error"], "detalle": h["detalle"]})
            continue
        host = h["host"]
        guardado = {k: v for k, v in zonas_motor.atributos_de(perfil, host["nombre"]).items() if k in motor_ubicacion.OPCIONES_DEL_PERFIL}
        try:
            plan, avisos = motor_ubicacion.planear_en_unidades(it["receta"], host, motor_ubicacion.combinar_opciones(guardado, it.get("opciones")), muros, u)
        except motor_ubicacion.ErrorUbicacion as e:
            detalle.append({**r, "estado": "omitido", "error": "no_se_puede_ubicar", "detalle": str(e)})
            continue
        plan = operaciones.asignar_ids(plan, it.get("diseno_id") or DISENO_ID_PREDETERMINADO, host.get("handle") or host["nombre"], it["receta"])
        nuevas, omitidas, cambiadas = operaciones.sin_duplicados_logico(plan, existentes, tol=motor_ubicacion.TOL_DUPLICADO / u, u=u)
        existentes += [{"bloque": c["bloque"], "x": c["x"], "y": c["y"], "item_id": c["item_id"]} for c in nuevas]      # tambien contra lo del propio lote
        todas += nuevas
        detalle.append({**r, "estado": "ok", "a_colocar": len(nuevas), "ya_colocadas": len(omitidas), "avisos": avisos or None,
                        "cambiadas": cambiadas or None, "opciones_del_perfil": guardado or None,
                        "piezas": [[c["producto"], c["x"], c["y"], round(c["rot"], 3)] for c in nuevas]})
    por_producto = {}
    for c in todas:
        por_producto[c["producto"]] = por_producto.get(c["producto"], 0) + 1
    omitidos = [d for d in detalle if d["estado"] == "omitido"]
    resumen = {"ok": True, "items": detalle, "a_colocar": len(todas), "por_producto": por_producto,
               "con_rotulo": sum(1 for c in todas if c.get("etiqueta")), "omitidos": [{"anfitrion": d["anfitrion"], "receta": d["receta"],
                                                                                        "motivo": d["detalle"]} for d in omitidos]}
    if not todas:
        return {**resumen, "aviso": "No hay nada nuevo que colocar (todo ya estaba puesto o se omitio).", **({"operaciones_previas": previas} if previas else {})}
    if len(todas) > 400:
        return {**resumen, "ok": False, "error": "demasiados_objetos", "detalle": "Mas de 400 piezas en una llamada: divide el lote."}
    r, op_id = _insertar_con_operacion(t, ctx.get("plano") or "", todas, existentes_dibujo, ejecutar, confirmacion, u)
    extra = {}
    if ctx.get("aviso_unidades"):
        extra["aviso_unidades"] = ctx["aviso_unidades"]
    if previas:
        extra["operaciones_previas"] = previas
    if not r.get("ok"):
        return {**resumen, **r, "ok": False, **({"operacion_id": op_id} if op_id else {}), **extra}
    aviso = {} if ejecutar else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True para colocarlo todo."}
    if ejecutar:
        extra["operacion_id"] = op_id
        if (r.get("operacion") or {}).get("fallos_xdata"):
            extra["aviso_marcas"] = f"{r['operacion']['fallos_xdata']} pieza(s) se colocaron pero sin marca: no podran reconocerse por identidad al repetir."
    return {**resumen, "insercion": {k: r.get(k) for k in ("insertados", "avisos", "bloques_importados", "escalas_aplicadas", "desviacion_max_m") if r.get(k)}, **extra, **aviso}


@mcp.tool()
def ajustes(modo_prueba: bool | None = None) -> dict:
    """Ajustes locales del MCP (se guardan en el PC del usuario). Sin argumentos, muestra los actuales.

    modo_prueba=True: en planos grandes NO pide el codigo de confirmacion de AutoCAD. Solo para sesiones de prueba: todo lo colocado va a las
    capas SCH_ILUMINACION y SCH_AUDIO y se deshace con quitar_colocaciones (o Ctrl+Z). modo_prueba=False restablece la proteccion.
    """
    actuales = _ajustes()
    if modo_prueba is not None:
        actuales["modo_prueba"] = bool(modo_prueba)
        try:
            RUTA_AJUSTES.parent.mkdir(parents=True, exist_ok=True)
            RUTA_AJUSTES.write_text(json.dumps(actuales, indent=1), encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": "no_pude_guardar", "detalle": str(e)}
    return {"ok": True, "ajustes": actuales, "candado_de_planos_grandes": "DESACTIVADO (modo prueba)" if actuales.get("modo_prueba") else "activo",
            "aviso": "Con modo_prueba la escritura en planos grandes ya no pide codigo: ejecuta directamente." if actuales.get("modo_prueba") else None}


@mcp.tool()
def ver_uso(ultimos: int = 40) -> dict:
    """SOLO LECTURA: registro de uso del MCP (que herramientas se llamaron, en que orden, cuanto tardaron y cuales fallaron).

    Sirve para medir velocidad y entender como esta trabajando el asistente. Se guarda en el PC del usuario (logs/uso.jsonl)."""
    try:
        lineas = RUTA_USO.read_text(encoding="utf-8").splitlines()[-max(1, min(int(ultimos), 500)):]
        reg = [json.loads(x) for x in lineas if x.strip()]
    except (OSError, ValueError):
        return {"ok": True, "llamadas": 0, "detalle": "Todavia no hay registro de uso."}
    total = sum(r.get("ms", 0) for r in reg)
    por = {}
    for r in reg:
        d = por.setdefault(r["herramienta"], {"n": 0, "ms": 0, "fallos": 0})
        d["n"] += 1
        d["ms"] += r.get("ms", 0)
        d["fallos"] += 0 if r.get("ok", True) else 1
    return {"ok": True, "llamadas": len(reg), "tiempo_total_s": round(total / 1000, 1), "por_herramienta": por, "recientes": reg[-15:]}


@mcp.tool()
@_serializado
def quitar_colocaciones(ejecutar: bool = False, confirmacion: str | None = None) -> dict:
    """BORRA lo que este MCP coloco: SOLO las entidades de las capas SCH_ILUMINACION y SCH_AUDIO (luminarias, parlantes, tiras, rotulos).
    Nunca toca otras capas (mobiliario, arquitectura, vegetacion) ni borra las capas. Sirve para repetir pruebas.

    Ensayo por defecto: cuenta que se borraria. En planos grandes exige `confirmacion` (CANDADO: el codigo que aparece en la linea de
    comandos de AutoCAD; pidelo a la persona, nunca lo inventes). Es un borrado: antes de ejecutar=True confirma con la persona el
    alcance. Ctrl+Z en AutoCAD lo deshace.
    """
    if (off := _escritura_off()):
        return off
    return acad.diseno({"op": "quitar", "ejecutar": bool(ejecutar), "confirmacion": confirmacion,
                        "max_objetos": _max_objetos()}, **_diseno_tiempos())


@mcp.tool()
def catalogo_ubicacion() -> dict:
    """SOLO LECTURA: productos Schaller disponibles (bloque, capa, escala, rotulo) y recetas de ubicacion por anfitrion."""
    return {"ok": True, **motor_ubicacion.catalogo()}


@mcp.tool()
def listar_anfitriones(filtro: str | None = None, cerca_de: list[float] | None = None, radio: float = 15.0,
                       limite: int = 40) -> dict:
    """SOLO LECTURA (rapido): muebles/bloques del plano que pueden ser ANFITRION de una ubicacion (cama, mesa, isla...).

    Devuelve nombre del bloque, capa, caja (x0,y0,x1,y1), ancho, alto y rotacion. filtro: texto en nombre o capa.
    cerca_de=[x, y] ordena por distancia y limita al radio (m). Usalo para elegir el anfitrion de ubicar_en_anfitrion.
    Los nombres de bloques de planos de clientes pueden ser datos del cliente: no los muestres en el chat sin necesidad.
    """
    return acad.diseno({"op": "anfitriones", "filtro": filtro, "cerca_de": cerca_de, "radio": float(radio), "limite": int(limite)},
                       **_diseno_tiempos())


def _diseno_tiempos() -> dict:
    t = _tiempos()
    return {"timeout_s": t["timeout_s"], "timeout_op_s": float(_escritura().get("timeout_escritura_s", 30)) + t["timeout_lectura_s"] / 2}


@mcp.tool()
@_serializado
def ubicar_en_anfitrion(receta: str, anfitrion: str | None = None, usar_seleccion: bool = False,
                        cerca_de: list[float] | None = None, opciones: dict | None = None,
                        ejecutar: bool = False, confirmacion: str | None = None) -> dict:
    """UBICA PRODUCTOS SEGUN LA GEOMETRIA REAL DE UN MUEBLE (no coordenadas fijas). Ensayo por defecto; solo AGREGA.

    Calcula las posiciones desde el bbox del anfitrion y, cuando hay muros, con RAYOS a muros (primer muro, sin saltar de
    ambiente). Es idempotente: lo que ya esta puesto (mismo bloque a <0.30 m) no se duplica. Rotula solo los bloques que no
    traen su referencia dibujada (H=0.035 m). Los bloques que falten se importan de bloques_schaller_corregido.dwg (debe estar abierto).

    Anfitrion: `anfitrion` (nombre del bloque; con varios iguales usa cerca_de=[x,y]) o usar_seleccion=True (el mueble
    seleccionado en AutoCAD).
    Recetas (ver catalogo_ubicacion): cama (opciones.cabecera N/S/E/O; si el plano tiene muros se deduce sola; ancho_cama,
    margen_lateral, filas), pared_frente (parlantes Ci200QS en el primer muro frente al mueble, mirando a el), centro
    (producto, du, dv), mesa_4x, tira_borde (borde), linea (producto, n, offset).
    Siempre revisa el ensayo (posiciones, avisos, omitidas) antes de ejecutar=True. En planos grandes exige `confirmacion`
    (CANDADO: el codigo que aparece en la linea de comandos de AutoCAD; pidelo a la persona, nunca lo inventes).
    Si no hay muros dibujados cerca, el motor NO adivina la cabecera ni la pared: pide indicarlas.
    """
    if (off := _escritura_off()):
        return off
    if receta not in motor_ubicacion.RECETAS:
        return {"ok": False, "error": "receta_desconocida", "detalle": f"Opciones: {', '.join(motor_ubicacion.RECETAS)}."}
    t = _diseno_tiempos()
    bbox_blk = [v["bloque"] for v in motor_ubicacion.PRODUCTOS.values() if v.get("ancla") == "bbox"]
    ctx = acad.diseno({"op": "contexto", "anfitrion": anfitrion, "usar_seleccion": bool(usar_seleccion), "cerca_de": cerca_de,
                       "bloques_bbox": bbox_blk}, **t)
    if not ctx.get("ok"):
        return ctx
    host = ctx["anfitrion"]
    u = float(ctx.get("unidad_m") or 1.0)
    guardado = {}
    if ctx.get("plano"):
        guardado = zonas_motor.atributos_de(zonas_motor.cargar_perfil(CARPETA_PERFILES, ctx["plano"]), host["nombre"])
    opciones = motor_ubicacion.combinar_opciones({k: v for k, v in guardado.items() if k in motor_ubicacion.OPCIONES_DEL_PERFIL}, opciones)   # lo explicito manda
    try:
        plan, avisos = motor_ubicacion.planear_en_unidades(receta, host, opciones, [tuple(m) for m in ctx.get("muros", [])], u)
    except motor_ubicacion.ErrorUbicacion as e:
        return {"ok": False, "error": "no_se_puede_ubicar", "detalle": str(e),
                "anfitrion": {k: host[k] for k in ("nombre", "x0", "y0", "x1", "y1", "w", "h")}, "muros_cercanos": ctx.get("n_muros", 0)}
    plan = operaciones.asignar_ids(plan, DISENO_ID_PREDETERMINADO, host.get("handle") or host["nombre"], receta)
    existentes_dibujo = list(ctx.get("existentes", []))
    previas = _reconciliar_previas(ctx.get("plano") or "", existentes_dibujo, u) if ejecutar else []
    if any(x["ambiguas"] for x in previas):
        return {"ok": False, "error": "operacion_previa_ambigua", "operaciones_previas": previas,
                "detalle": "Una operacion anterior quedo a medias y hay piezas sin marca que no se pueden atribuir con seguridad. No se escribio nada."}
    nuevas, omitidas, cambiadas = operaciones.sin_duplicados_logico(plan, existentes_dibujo, tol=motor_ubicacion.TOL_DUPLICADO / u, u=u)
    resumen = {"ok": True, "receta": receta, "anfitrion": {k: host[k] for k in ("nombre", "x0", "y0", "x1", "y1", "w", "h")},
               "muros_cercanos": ctx.get("n_muros", 0), "a_colocar": len(nuevas), "ya_colocadas_omitidas": len(omitidas),
               "opciones_del_perfil": {k: v for k, v in guardado.items() if k in motor_ubicacion.OPCIONES_DEL_PERFIL} or None,
               "colocaciones": nuevas, "omitidas": omitidas, "avisos": avisos, **({"cambiadas": cambiadas} if cambiadas else {})}
    if not nuevas:
        return {**resumen, "aviso": "Todo lo de esta receta ya esta colocado: no se hizo nada."}
    if len(nuevas) > int(_escritura().get("max_puntos", 100)):
        return {**resumen, "ok": False, "error": "demasiados_objetos"}
    r, op_id = _insertar_con_operacion(t, ctx.get("plano") or "", nuevas, existentes_dibujo, ejecutar, confirmacion, u)
    if ctx.get("aviso_unidades"):
        resumen["aviso_unidades"] = ctx["aviso_unidades"]
    if not r.get("ok"):
        return {**resumen, **r, "ok": False, **({"operacion_id": op_id} if op_id else {})}
    aviso = {} if ejecutar else {"aviso": "ENSAYO: no se modifico nada. Revisa las colocaciones y repite con ejecutar=True."}
    return {**resumen, "insercion": r, **({"operacion_id": op_id} if op_id else {}), **({"operaciones_previas": previas} if previas else {}), **aviso}



@mcp.tool()
def dibujar_textos(textos: list[dict], altura: float = 0.15, ejecutar: bool = False,
                   confirmacion: str | None = None) -> dict:
    """MODIFICA EL DIBUJO (solo agrega): escribe rotulos de texto (por ejemplo el nombre de cada producto al lado de su bloque).

    textos: [{"bloque": "<nombre de bloque>" o "texto": "<texto libre>", "x": n, "y": n, "rotacion_grados": 0 (opcional),
    "altura": n (opcional)}]. Con `bloque` el rotulo es su nombre sin la marca final ('Durastrip IP20 75W'). El texto queda CENTRADO
    en (x, y). `altura` por defecto, en unidades del dibujo (0.15 = 15 cm si el dibujo esta en metros). Capa [escritura].capa_etiquetas
    (SCH_ETIQUETAS). Por defecto es un ENSAYO; con ejecutar=True escribe. En planos grandes exige `confirmacion` (CANDADO).
    """
    if (off := _escritura_off()):
        return off
    maximo = int(_escritura().get("max_puntos", 100))
    if not isinstance(textos, list) or not textos or len(textos) > maximo or not 0 < float(altura) <= 1e6:
        return {"ok": False, "error": "textos_invalidos", "detalle": f"Indica entre 1 y {maximo} textos y una altura mayor que 0."}
    limpios, problemas = [], []
    for i, t in enumerate(textos, start=1):
        try:
            texto = nombre_visible(t["bloque"]) if t.get("bloque") else str(t["texto"]).strip()
            x, y = float(t["x"]), float(t["y"])
            rot = float(t.get("rotacion_grados", 0) or 0)
            alto = float(t.get("altura") or altura)
            if not texto or alto <= 0 or any(abs(v) > 1e9 or v != v for v in (x, y, rot, alto)):
                raise ValueError
        except (TypeError, ValueError, KeyError, AttributeError):
            problemas.append({"texto": i, "detalle": "Necesita 'bloque' o 'texto', y x, y numericos."})
            continue
        limpios.append({"texto": texto, "x": x, "y": y, "rotacion_grados": rot, "altura": alto})
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se escribio nada: corrige estos textos.",
                "problemas": problemas}
    r = _escribir({"op": "textos", "textos": limpios, "ejecutar": bool(ejecutar), "confirmacion": confirmacion,
                   "capa": str(_escritura().get("capa_etiquetas", "SCH_ETIQUETAS"))})
    aviso = {} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."}
    return {**r, "rotulos": [t["texto"] for t in limpios], **aviso}


@mcp.tool()
def dibujar_flechas(flechas: list[dict], ejecutar: bool = False, confirmacion: str | None = None) -> dict:
    """MODIFICA EL DIBUJO (solo agrega): dibuja flechas (linea + punta) para indicar hacia donde apunta un producto.

    flechas: [{"x": n, "y": n, "angulo_grados": n, "largo": n}]; angulo 0 = derecha (+X), 90 = arriba, 180 = izquierda, 270 = abajo.
    Salen del punto (x, y) y miden `largo` (unidades del dibujo). Capa [escritura].capa_apuntado (SCH_APUNTADO, roja).
    Por defecto es un ENSAYO; con ejecutar=True dibuja. En planos grandes exige `confirmacion` (CANDADO).
    """
    if (off := _escritura_off()):
        return off
    maximo = int(_escritura().get("max_puntos", 100))
    if not isinstance(flechas, list) or not flechas or len(flechas) > maximo:
        return {"ok": False, "error": "flechas_invalidas", "detalle": f"Indica entre 1 y {maximo} flechas."}
    segmentos, problemas = [], []
    for i, f in enumerate(flechas, start=1):
        try:
            x, y, ang, largo = (float(f[k]) for k in ("x", "y", "angulo_grados", "largo"))
            if largo <= 0 or any(abs(v) > 1e9 or v != v for v in (x, y, ang, largo)):
                raise ValueError
        except (TypeError, ValueError, KeyError, AttributeError):
            problemas.append({"flecha": i, "detalle": "Necesita x, y, angulo_grados y largo (> 0), numericos."})
            continue
        a = math.radians(ang)
        x1, y1 = x + largo * math.cos(a), y + largo * math.sin(a)
        punta = min(largo * 0.25, 0.4 * largo)
        segmentos.append([x, y, x1, y1])
        for d in (150, -150):  # dos lineas hacia atras desde la punta
            b = a + math.radians(d)
            segmentos.append([x1, y1, x1 + punta * math.cos(b), y1 + punta * math.sin(b)])
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se dibujo nada: corrige estas flechas.",
                "problemas": problemas}
    r = _escribir({"op": "lineas", "segmentos": [[round(v, 6) for v in s] for s in segmentos], "ejecutar": bool(ejecutar),
                   "confirmacion": confirmacion, "capa": str(_escritura().get("capa_apuntado", "SCH_APUNTADO")), "color": 1})
    aviso = {} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."}
    return {**r, "flechas": len(flechas), **aviso}


@mcp.tool()
def comparar_biblioteca(destino_contiene: str | None = None, origen_contiene: str = "bloques_schaller_corregido",
                        mostrar_solo_en_plano: bool = False) -> dict:
    """SOLO LECTURA: compara la biblioteca (bloques_schaller_corregido) con un plano abierto y dice que bloques estan al dia.

    Devuelve: cuantos iguales, cuales FALTAN en el plano (se copian con importar_biblioteca), cuales estan POSIBLEMENTE
    DESACTUALIZADOS (mismo nombre pero otra forma o tamano; no se actualizan solos) y cuantos bloques del plano no estan en
    la biblioteca (sus nombres se ocultan salvo mostrar_solo_en_plano=True; usar solo si no hay datos de cliente en ellos).
    No modifica ningun dibujo.
    """
    r = acad.importar_simbolos(
        {"origen_contiene": origen_contiene, "destino_contiene": destino_contiene, "comparar": True,
         "mostrar_solo_en_plano": bool(mostrar_solo_en_plano)},
        timeout_s=_tiempos()["timeout_s"], timeout_importar_s=float(CFG.get("simbolos", {}).get("timeout_importar_s", 300)))
    return r


@mcp.tool()
def importar_biblioteca(destino_contiene: str | None = None, origen_contiene: str = "bloques_schaller_corregido",
                        ejecutar: bool = False, confirmacion: str | None = None, solo_con_ficha: bool = True) -> dict:
    """MODIFICA EL DIBUJO DESTINO (solo agrega): copia los bloques de PRODUCTO de la biblioteca (bloques_schaller_corregido) a un plano.

    Por defecto solo los que tienen ficha (estan colocados en el modelo de la biblioteca) y sus sub-bloques internos; asi no se
    cuelan definiciones sueltas ni restos de otros planos (cotas, niveles, nombres de proyectos). solo_con_ficha=False copia
    TODAS las definiciones (no recomendado).
    Asi todos los planos quedan con los bloques nombrados igual. Copia cada definicion tal cual, con su mismo nombre (solo
    convierte unidades si el plano y la biblioteca usan unidades distintas). Los bloques que el plano ya tiene NO se tocan.
    origen_contiene: fragmento del nombre de la biblioteca abierta (debe coincidir con 1 documento).
    destino_contiene: fragmento del nombre del plano destino; si se omite, el dibujo activo.
    Por defecto es un ENSAYO (dice cuantos copiaria y cuantos ya existen). En planos grandes, ejecutar=True exige
    `confirmacion`: el codigo que aparece en la linea de comandos de AutoCAD (CANDADO); pidelo a la persona.
    """
    if (off := _escritura_off()):
        return off
    r = acad.importar_simbolos(
        {"origen_contiene": origen_contiene, "destino_contiene": destino_contiene, "nombres": None, "como_esta": True,
         "solo_con_ficha": bool(solo_con_ficha), "ejecutar": bool(ejecutar),
         "max_objetos": int(_escritura().get("max_objetos_dibujo", 300)), "confirmacion": confirmacion},
        timeout_s=_tiempos()["timeout_s"], timeout_importar_s=float(CFG.get("simbolos", {}).get("timeout_importar_s", 300)))
    if not r.get("ok"):
        return r
    est = [v.get("estado", "") for v in r["simbolos"].values()]
    resumen = {"total": len(est), "se_importarian_o_importados": sum(e in ("se_importaria", "importado") for e in est),
               "ya_existian": sum(e.startswith("ya_existia") for e in est), "fallaron": sum(e == "fallo" for e in est)}
    aviso = {} if ejecutar else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."}
    return {"ok": True, "ejecutado": r["ejecutado"], "dibujo_grande": r.get("dibujo_grande"), "resumen": resumen,
            "fallos": {n: v for n, v in r["simbolos"].items() if v.get("estado") == "fallo"}, "avisos": r["avisos"], **aviso}


def _accesorios() -> list[dict]:
    cfg = CFG.get("productos", {})
    try:
        return productos.cargar_accesorios(cfg.get("ruta_hoja"), cfg.get("hoja_accesorios", "Drivers y accesorios"))
    except productos.HojaError:
        return []  # los accesorios son opcionales: la ficha sale igual, sin esa seccion


def _ficha_de(p: dict, accs: list[dict]) -> dict:
    capa = nombre_capa(_escritura().get("prefijo_capa", "DL-TEST-"), p.get(productos.SISTEMA))
    return fichas.armar_ficha(p, accs, capa)


def _elegir(prods, referencias=None, filas_excel=None, sistemas=None):
    """(productos elegidos sin repetir, problemas). Sin criterios: todos. Todo o nada si algun item es invalido."""
    if referencias is None and filas_excel is None:
        elegidos, problemas = list(prods), []
    else:
        elegidos, problemas = [], []
        for ref in referencias or []:
            p, err = _producto_unico(ref, None, prods)
            if err:
                problemas.append({"referencia": ref, **{k: v for k, v in err.items() if k != "ok"}})
            else:
                elegidos.append(p)
        for fila in filas_excel or []:
            p = next((x for x in prods if x["_fila"] == fila), None)
            if p is None:
                problemas.append({"fila_excel": fila, "error": "fila_no_encontrada"})
            else:
                elegidos.append(p)
        elegidos = list({p["_fila"]: p for p in elegidos}.values())  # sin repetir
    if sistemas:
        quiero = {productos.norm(s) for s in sistemas}
        elegidos = [p for p in elegidos if productos.norm(p.get(productos.SISTEMA)) in quiero]
    return elegidos, problemas


def _ruta_cfg(valor) -> str | None:
    """Rutas de config.toml: las relativas se resuelven contra la carpeta del servidor (sirve en cualquier PC)."""
    if not valor:
        return None
    r = Path(valor)
    return str(r if r.is_absolute() else AQUI / r)


def _carpeta_fichas():
    c = _ruta_cfg(CFG.get("fichas", {}).get("carpeta"))
    return Path(c) if c else None


@mcp.tool()
def exportar_simbolos(destino_contiene: str | None = None, referencias: list[str] | None = None,
                      filas_excel: list[int] | None = None) -> dict:
    """Guarda como imagen (SVG) el dibujo de los simbolos de los productos, leyendolos de un dibujo abierto (solo lectura).

    Lee las definiciones de bloque del dibujo indicado (destino_contiene: fragmento del nombre; si se omite, el activo),
    tipicamente el dibujo donde ya se importaron los simbolos. Escribe SOLO en [fichas].carpeta\\simbolos. Dibuja lineas,
    polilineas, circulos y arcos (y bloques anidados); rellenos, textos y solidos se cuentan como omitidos.
    Sin criterios usa todos los productos con bloque asignado. No modifica AutoCAD.
    """
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    carpeta = _carpeta_fichas()
    if not carpeta:
        return {"ok": False, "error": "sin_carpeta", "detalle": "Falta [fichas].carpeta en config.toml."}
    elegidos, problemas = _elegir(prods, referencias, filas_excel)
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se exporto nada: corrige estos items.", "problemas": problemas}
    nombres = []
    for p in elegidos:
        for n in productos.bloques_cad(p):
            if n not in nombres:
                nombres.append(n)
    if not nombres:
        return {"ok": False, "error": "sin_bloques", "detalle": "Ningun producto elegido tiene nombre de bloque CAD."}
    r = acad.exportar_svg(nombres, destino_contiene, **_tiempos())
    if not r.get("ok"):
        return r
    destino = (carpeta / "simbolos").resolve()
    destino.mkdir(parents=True, exist_ok=True)
    resumen = {}
    for n, v in r["simbolos"].items():
        if v.get("svg"):
            arch = (destino / f"{fichas.slug(n)}.svg").resolve()
            if arch.parent != destino:
                resumen[n] = {"error": "ruta_invalida"}
                continue
            arch.write_text(v["svg"], encoding="utf-8")
            resumen[n] = {"archivo": arch.name, "primitivas": v["primitivas"], "omitidas": v["omitidas"]}
        else:
            resumen[n] = {"error": v.get("error", "sin_geometria_dibujable"), "omitidas": v.get("omitidas")}
    return {"ok": True, "carpeta": str(destino), "con_imagen": sum("archivo" in v for v in resumen.values()), "simbolos": resumen}


@mcp.tool()
def generar_tarjetas(sistemas: list[str] | None = None, referencias: list[str] | None = None,
                     filas_excel: list[int] | None = None) -> dict:
    """Genera tarjetas de producto en el formato de la referencia (tarjetas.html, solo dentro de [fichas].carpeta).

    Cada tarjeta: INSTALACION, simbolo, REF (marca), DESCRIPTION, CANTIDAD y TIPO DE CONEXION, mas la leyenda de convenciones.
    El simbolo sale de las imagenes de exportar_simbolos (si no hay, queda 'sin simbolo'). CANTIDAD = copias del bloque en el
    plano de diseno, tomada de la extraccion ([fichas].extraccion); '*' si varios productos comparten el bloque; 'sin dato' si
    el producto no tiene bloque. Filtra por sistemas (ej. ['Audio', 'Control', 'Redes']) o por referencias / filas.
    Los datos inventados salen en naranja cursiva. No modifica AutoCAD ni la hoja.
    """
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    carpeta = _carpeta_fichas()
    if not carpeta:
        return {"ok": False, "error": "sin_carpeta", "detalle": "Falta [fichas].carpeta en config.toml."}
    elegidos, problemas = _elegir(prods, referencias, filas_excel, sistemas)
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se genero nada: corrige estos items.", "problemas": problemas}
    if not elegidos:
        return {"ok": False, "error": "sin_productos", "detalle": "Ningun producto cumple el filtro."}
    svgs = {}
    for p in elegidos:
        for b in productos.bloques_cad(p):
            arch = carpeta / "simbolos" / f"{fichas.slug(b)}.svg"
            if arch.is_file():
                svgs[b] = arch.read_text(encoding="utf-8")
    por_bloque = fichas.cantidades_desde_csv(_ruta_cfg(CFG.get("fichas", {}).get("extraccion")))
    cant, compartidos = fichas.calcular_cantidades(prods, elegidos, por_bloque)
    accs = _accesorios()
    lista = [_ficha_de(p, accs) for p in elegidos]
    nombre = "tarjetas.html"
    if sistemas or referencias or filas_excel:  # un filtro no pisa el archivo con todas las tarjetas
        partes = sistemas or ["seleccion"]
        nombre = "tarjetas_" + "-".join(fichas.slug(productos.norm(s)) for s in partes)[:60] + ".html"
    r = fichas.generar_tarjetas(lista, svgs, cant, carpeta, compartidos, nombre)
    return {"ok": True, **r, "con_cantidad_compartida": len(compartidos)}


@mcp.tool()
def crear_tarjetas_cad(destino_contiene: str | None = None, sistemas: list[str] | None = None,
                       referencias: list[str] | None = None, filas_excel: list[int] | None = None,
                       columnas: int = 8, x0: float = 0.0, y0: float = 0.0, ancho_tarjeta: float = 1800.0,
                       incluir_leyenda: bool = True, incluir_sin_simbolo: bool = False, ejecutar: bool = False) -> dict:
    """MODIFICA EL DIBUJO (solo agrega): dibuja en AutoCAD las tarjetas de producto del formato de referencia.

    Cada tarjeta: INSTALACION, simbolo real del producto (copia del bloque ya presente en el dibujo, escalada para caber),
    REF (marca), DESCRIPTION, CANTIDAD y TIPO DE CONEXION, mas la leyenda de convenciones. Valores en azul; lo inventado en
    naranja inclinado. Solo se dibujan los productos cuyo simbolo YA esta en el dibujo (importalos antes con importar_simbolos),
    salvo incluir_sin_simbolo=True. CANTIDAD viene de la extraccion del plano ([fichas].extraccion).
    destino_contiene: fragmento del nombre del dibujo destino (si se omite, el activo). x0, y0: esquina superior izquierda de la
    primera tarjeta; columnas: tarjetas por fila; ancho_tarjeta en unidades del dibujo (todo se escala proporcional).
    Por defecto es un ENSAYO (calcula y dice que haria); con ejecutar=True dibuja. Se niega en dibujos grandes.
    """
    if (off := _escritura_off()):
        return off
    if not (1 <= int(columnas) <= 20) or not (200 <= float(ancho_tarjeta) <= 20000):
        return {"ok": False, "error": "parametros_invalidos", "detalle": "columnas entre 1 y 20; ancho_tarjeta entre 200 y 20000."}
    if any(v != v or abs(v) > 1e9 for v in (float(x0), float(y0))):
        return {"ok": False, "error": "parametros_invalidos", "detalle": "x0 / y0 fuera de rango."}
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    elegidos, problemas = _elegir(prods, referencias, filas_excel, sistemas)
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se dibujo nada: corrige estos items.", "problemas": problemas}
    if not elegidos:
        return {"ok": False, "error": "sin_productos", "detalle": "Ningun producto cumple el filtro."}
    por_bloque = fichas.cantidades_desde_csv(_ruta_cfg(CFG.get("fichas", {}).get("extraccion")))
    cant, compartidos = fichas.calcular_cantidades(prods, elegidos, por_bloque)
    accs = _accesorios()
    orden = list(dict.fromkeys(p.get(productos.SISTEMA) for p in elegidos))      # sistemas en el orden de la hoja
    tarjetas = []
    for sis in orden:
        for p in (x for x in elegidos if x.get(productos.SISTEMA) == sis):
            f = _ficha_de(p, accs)
            tec = {c["nombre"]: {"v": None if c["vacio"] else c["valor"], "inv": c["inventado"]} for c in f["tecnicos"]}
            q = cant.get(p["_fila"])
            tarjetas.append({
                "fila_excel": p["_fila"], "referencia": p.get(productos.REF), "marca": p.get(productos.MARCA),
                "descripcion": p.get(productos.CORTO), "instalacion": tec["Instalación"], "conexion": tec["Tipo de conexión"],
                "cantidad": None if q is None else (f"{q}*" if p["_fila"] in compartidos else str(q)),
                "bloques": productos.bloques_cad(p)})
    cfg = _escritura()
    r = acad.dibujar_tarjetas(
        {"op": "tarjetas", "destino_contiene": destino_contiene, "tarjetas": tarjetas, "columnas": int(columnas),
         "x0": float(x0), "y0": float(y0), "ancho": float(ancho_tarjeta), "leyenda": bool(incluir_leyenda),
         "incluir_sin_simbolo": bool(incluir_sin_simbolo), "ejecutar": bool(ejecutar),
         "max_objetos": int(cfg.get("max_objetos_dibujo", 300))},
        timeout_s=_tiempos()["timeout_s"], timeout_escritura_s=float(cfg.get("timeout_escritura_s", 30)))
    aviso = {} if ejecutar or not r.get("ok") else {"aviso": "ENSAYO: no se modifico nada. Repite con ejecutar=True."}
    return {**r, **aviso}


@mcp.tool()
def ver_ficha(referencia: str, fila_excel: int | None = None) -> dict:
    """Arma la ficha de UN producto y devuelve su contenido organizado por secciones (no escribe archivos).

    Secciones: identificacion, datos tecnicos, especificaciones adicionales, drivers y accesorios asociados, CAD, fuente.
    Los datos INVENTADOS (PRUEBA) vienen con inventado=true; la ficha avisa cuantos son. Nunca se inventan referencias
    ni nombres de bloque. fila_excel: solo si la referencia esta repetida (p. ej. 'SIN REFERENCIA').
    """
    p, err = _producto_unico(referencia, fila_excel)
    if err:
        return err
    return {"ok": True, "ficha": _ficha_de(p, _accesorios())}


@mcp.tool()
def generar_fichas(referencias: list[str] | None = None, filas_excel: list[int] | None = None) -> dict:
    """Genera las fichas en HTML (una pagina por producto + indice.html), SOLO dentro de [fichas].carpeta de config.toml.

    Sin argumentos genera TODAS las fichas de la hoja. Con referencias y/o filas_excel, solo esas (todo o nada si alguna
    no existe o esta repetida; para las repetidas usa filas_excel). Reescribe las fichas anteriores de esa carpeta.
    No modifica AutoCAD ni la hoja. Los datos inventados salen en naranja cursiva con un aviso de PRUEBA.
    """
    try:
        _, prods = _hoja()
    except productos.HojaError as e:
        return _error(e)
    elegidos, problemas = _elegir(prods, referencias, filas_excel)
    if problemas:
        return {"ok": False, "error": "items_con_problemas", "detalle": "No se genero nada: corrige estos items.", "problemas": problemas}
    carpeta = _ruta_cfg(CFG.get("fichas", {}).get("carpeta"))
    if not carpeta:
        return {"ok": False, "error": "sin_carpeta", "detalle": "Falta [fichas].carpeta en config.toml."}
    accs = _accesorios()
    lista = [_ficha_de(p, accs) for p in elegidos]
    r = fichas.generar(lista, carpeta)
    return {"ok": True, "total": len(lista), "con_datos_inventados": sum(f["es_prueba"] for f in lista),
            "con_accesorios": sum(bool(f["accesorios"]) for f in lista), **r}


@mcp.tool()
def zoom_extents() -> dict:
    """Acerca la vista de AutoCAD a todo el contenido del dibujo (Zoom Extents), para ver lo recien dibujado.

    Solo mueve la vista: no crea, borra ni cambia ningun objeto. Util despues de crear o insertar productos.
    """
    return acad.zoom_extents(timeout_s=_tiempos()["timeout_s"])


@mcp.tool()
def bloques_en_dibujo(limite_objetos: int = 5000) -> dict:
    """Lista los bloques insertados en el espacio Modelo del dibujo abierto (solo lectura).

    Devuelve, por nombre de bloque: cantidad y capas. Util para ver que hay cuando el escaneo no logra clasificar el mobiliario. Recorre hasta
    `limite_objetos` objetos; si el dibujo tiene mas, `truncado` sera true. Los nombres pueden ser datos del cliente: no los muestres en el chat
    sin necesidad.
    """
    return acad.leer_bloques(limite=limite_objetos, **_tiempos())


@mcp.tool()
def ubicar_producto(referencia: str, fila_excel: int | None = None, max_posiciones: int = 50,
                    limite_objetos: int = 5000) -> dict:
    """Busca en el dibujo abierto los bloques de un producto y devuelve donde estan (solo lectura).

    Toma el nombre de bloque de la columna 'Bloque en CAD (sugerido, por confirmar)' de la hoja y devuelve, por cada
    copia en el modelo, X, Y, rotacion y capa (en las unidades del dibujo). El nombre del bloque esta 'por confirmar'.
    fila_excel: solo si la referencia esta repetida (p. ej. 'SIN REFERENCIA').
    """
    p, err = _producto_unico(referencia, fila_excel)
    if err:
        return err
    nombres = productos.bloques_cad(p)
    base = _base(p)
    if not nombres:
        return {"ok": False, "error": "sin_bloque_asignado", **base,
                "detalle": "La hoja no tiene nombre de bloque CAD para este producto (columna vacia)."}
    r = acad.leer_bloques(nombres=nombres, limite=limite_objetos, max_posiciones=max_posiciones, **_tiempos())
    if not r.get("ok"):
        return {**r, **base}
    pos = r["posiciones"]
    en_dibujo = {n.casefold(): n for n in pos}
    encontrados = {n: len(pos[en_dibujo[n.casefold()]]) for n in nombres if n.casefold() in en_dibujo}
    totales = {b["nombre"].casefold(): b["cantidad"] for b in r["bloques"]}
    return {
        "ok": True, **base,
        "bloques_buscados": nombres,
        "cantidad_en_dibujo": {n: totales.get(n.casefold(), 0) for n in nombres},
        "posiciones": pos,
        "unidades": r["unidades"],
        "truncado": r["truncado"],
        "aviso": "El nombre de bloque viene de una columna 'por confirmar'; verificar antes de usarlo."
                 + (" Lectura incompleta: el dibujo tiene mas objetos que limite_objetos." if r["truncado"] else "")
                 + ("" if encontrados else " Ninguno de esos bloques esta insertado en el dibujo abierto."),
    }


@mcp.tool()
def pedir_referencias_finales(productos_fichas: list[str]) -> dict:
    """Cierre del plano: dice que referencias faltan y redacta la peticion de la cotizacion al usuario (solo lectura).

    Llamarla cuando el usuario indique que el plano esta terminado. productos_fichas: nombres de los productos que
    tienen ficha en el DWG (sin datos de cliente). Devuelve cuales no tienen referencia confirmada y el mensaje a
    mostrar. No lee AutoCAD ni la cotizacion: la referencia la da el usuario.
    """
    sin, con = referencias.pendientes(productos_fichas, referencias.cargar(REF_JSON))
    return {"ok": True, "regla": referencias.REGLA, "marcador": referencias.MARCADOR,
            "sin_referencia": sin, "con_referencia": con, "mensaje_para_el_usuario": referencias.solicitud(sin)}


@mcp.tool()
def registrar_referencias(items: list[dict], fuente: str, confirmado_por_usuario: bool = False) -> dict:
    """Guarda las referencias REALES de la cotizacion, para ponerlas luego en las fichas.

    items: [{"producto": "<nombre de la ficha>", "referencia": "<referencia real>"}]. fuente: de donde salen (p. ej.
    'cotizacion v3'). Solo guarda si confirmado_por_usuario=true (el usuario las dio o confirmo). Escribe unicamente
    referencias_finales.json junto al servidor; no toca AutoCAD. Rechaza referencias vacias o 'POR DEFINIR'.
    """
    if not confirmado_por_usuario:
        return {"ok": False, "error": "falta_confirmacion",
                "detalle": "Las referencias deben venir del usuario o de su cotizacion. Pide confirmacion y repite con "
                           "confirmado_por_usuario=true. No se guardo nada."}
    if not fuente.strip():
        return {"ok": False, "error": "falta_fuente", "detalle": "Indica de donde salen (p. ej. 'cotizacion v3')."}
    try:
        todas = referencias.guardar(REF_JSON, items, fuente.strip())
    except ValueError as e:
        return {"ok": False, "error": "item_invalido", "detalle": str(e)}
    return {"ok": True, "guardadas": len(items), "total_confirmadas": len(todas), "archivo": REF_JSON.name}


def _resultado_como_dict(res):
    """El despachador de FastMCP devuelve el resultado convertido (lista de contenidos con el JSON como texto); lo vuelve a un dict."""
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], dict):
        return res[1]
    if isinstance(res, dict):
        return res
    if isinstance(res, list) and res and getattr(res[0], "text", None):
        try:
            d = json.loads(res[0].text)
            return d if isinstance(d, dict) else None
        except ValueError:
            return None
    return None


def _activar_registro_de_uso() -> None:
    """Envuelve el despachador de herramientas de FastMCP para registrar cada llamada (nombre, duracion, ok/error)."""
    original = mcp._tool_manager.call_tool

    async def con_registro(name, arguments, *args, **kwargs):
        t0 = time.time()
        try:
            res = await original(name, arguments, *args, **kwargs)
        except Exception as e:
            _registrar_uso(name, arguments, (time.time() - t0) * 1000, False, type(e).__name__)
            raise
        datos = _resultado_como_dict(res)
        ok = not (isinstance(datos, dict) and datos.get("ok") is False)
        _registrar_uso(name, arguments, (time.time() - t0) * 1000, ok, None if ok else (datos.get("error") if isinstance(datos, dict) else None))
        metricas.volcar(contexto={"herramienta": name})      # apagada: no hace nada
        return res
    mcp._tool_manager.call_tool = con_registro


_activar_registro_de_uso()


def main():
    mcp.run()

if __name__ == "__main__":
    main()
