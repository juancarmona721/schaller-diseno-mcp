"""diseno-mcp: servidor MCP interno para el equipo de diseno. Por ahora, todo es de SOLO LECTURA."""
import json
import math
import os
import tomllib
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import acad
import fichas
import productos
import referencias

AQUI = Path(__file__).resolve().parent


def cargar_config() -> dict:
    ruta = Path(os.environ.get("DISENO_MCP_CONFIG") or AQUI / "config.toml")
    with open(ruta, "rb") as fh:
        return tomllib.load(fh)


CFG = cargar_config()
mcp = FastMCP("diseno-mcp", instructions=(
    "REGLA DE REFERENCIAS (equipo de diseno): " + referencias.REGLA + " Cuando el usuario diga que el plano esta "
    "terminado, o pida cerrar/finalizar fichas, llama a pedir_referencias_finales y pide la cotizacion o las "
    "referencias; no escribas referencias en las fichas antes de eso."))
REF_JSON = AQUI / "referencias_finales.json"


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
    """SOLO LECTURA: resumen estructurado del plano. Llamarla ANTES de ubicar productos.

    Devuelve las unidades (con aviso si no cuadran con el tamano de los bloques), los ESPACIOS detectados (poligonos cerrados con
    un texto dentro: nombre, limites x0,y0,x1,y1, ancho, alto, area y los productos que contiene), los bloques colocados por
    nombre y los que quedan fuera de todo espacio. Con esto se calculan posiciones sin adivinar coordenadas.
    destino_contiene: fragmento del nombre del dibujo; si se omite, el dibujo activo. No devuelve el nombre del archivo.
    En planos reales los nombres de espacios y bloques pueden ser datos del cliente: no mostrarlos en el chat.
    """
    return acad.ver_plano(destino_contiene, int(limite_objetos), int(max_espacios), **_tiempos())


@mcp.tool()
def escanear_zonas(destino_contiene: str | None = None, forzar_recarga: bool = False) -> dict:
    """SOLO LECTURA ULTRA-RAPIDO: detecta y lista las zonas y ambientes del plano activo.

    Si ya se escaneo el dibujo actual, devuelve la informacion al instante (< 0.05 s) desde cache en memoria.
    Usa forzar_recarga=True si cambiaste de dibujo o modificaste los textos en AutoCAD.
    """
    if not forzar_recarga:
        try:
            cache_p = Path(__file__).resolve().parent / "zonas_activas.json"
            if cache_p.exists():
                with open(cache_p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("zonas"):
                        return {"ok": True, "origen": "cache_rapido", **data}
        except Exception:
            pass
    return acad.escanear_zonas(destino_contiene, **_tiempos())


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


@mcp.tool()
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
        res_zonas = acad.escanear_zonas()
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
def comparar_biblioteca(destino_contiene: str | None = None, origen_contiene: str = "bloques_schaller",
                        mostrar_solo_en_plano: bool = False) -> dict:
    """SOLO LECTURA: compara la biblioteca (bloques_schaller) con un plano abierto y dice que bloques estan al dia.

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
def importar_biblioteca(destino_contiene: str | None = None, origen_contiene: str = "bloques_schaller",
                        ejecutar: bool = False, confirmacion: str | None = None, solo_con_ficha: bool = True) -> dict:
    """MODIFICA EL DIBUJO DESTINO (solo agrega): copia los bloques de PRODUCTO de la biblioteca (bloques_schaller) a un plano.

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

    Devuelve, por nombre de bloque: cantidad y capas. Recorre hasta `limite_objetos` objetos; si el dibujo
    tiene mas, `truncado` sera true. Usar solo con dibujos de prueba, no con planos de clientes.
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


def main():
    mcp.run()

if __name__ == "__main__":
    main()
