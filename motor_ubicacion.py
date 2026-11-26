"""Motor de ubicacion por ANFITRION (puro: sin AutoCAD, probable con pytest).

Idea: una posicion nunca es una coordenada fija. Se calcula desde la geometria real del mueble anfitrion
(cama, mesa, isla...) con reglas relativas, asi sirve en cualquier plano. Las reglas por defecto se ajustaron
contra el diseno aprobado de la Villa Schaller (ver tests/test_motor_ubicacion.py).

Marco local de un anfitrion: u = a lo largo del borde de referencia, v = alejandose de ese borde hacia el interior.
"""
import math
import re

import patrones_diseno as pd

# ---------------------------------------------------------------------------------------------------------------------
# Catalogo unico de productos Schaller. La escala sale de patrones_diseno (unidades del bloque: mm o m).
# ancla: "insercion" = el punto de insercion es el centro del dibujo; "bbox" = hay que centrar la geometria en el punto
#        (el bloque tiene el punto base lejos de lo que dibuja).
# ---------------------------------------------------------------------------------------------------------------------
PRODUCTOS = {
    "cctevo58":       {"bloque": "CCTEvo Architectural_58_Targetti", "capa": "SCH_ILUMINACION", "descripcion": "Proyector CCTEvo 58 (Targetti)"},
    "cctevo160":      {"bloque": "CCTEvo Architectural_160_Targetti", "capa": "SCH_ILUMINACION", "descripcion": "Proyector CCTEvo 160 (Targetti)"},
    "l7":             {"bloque": "FORTYEIGHT Label_7_Targetti", "capa": "SCH_ILUMINACION", "frente": 0.0, "descripcion": "Proyector FORTYEIGHT Label 7 (Targetti)"},
    "simbiosis":      {"bloque": "Simbiosis_Davide Groppi", "capa": "SCH_ILUMINACION", "descripcion": "Suspension SIMBIOSIS (Davide Groppi)"},
    "moon60":         {"bloque": "Moon_60_Davide Groppi", "capa": "SCH_ILUMINACION", "descripcion": "Suspension Moon 60 (Davide Groppi)"},
    "durastrip_ip68": {"bloque": "Durastrip IP68_45W_Targetti", "capa": "SCH_ILUMINACION", "lineal": True, "descripcion": "Tira LED Durastrip IP68 45W"},
    "durastrip_ip20": {"bloque": "Durastrip IP20_75W_Targetti", "capa": "SCH_ILUMINACION", "lineal": True, "descripcion": "Tira LED Durastrip IP20 75W"},
    "ci160":          {"bloque": "Ci160CRDS_KEF", "capa": "SCH_AUDIO", "descripcion": "Parlante de techo KEF Ci160CRDS"},
    "ci200qr":        {"bloque": "Ci200QR_KEF", "capa": "SCH_AUDIO", "descripcion": "Parlante de techo KEF Ci200QR"},
    "ci200qs":        {"bloque": "Ci200QS Pared_KEF", "capa": "SCH_AUDIO", "frente": -math.pi / 2, "descripcion": "Parlante de pared KEF Ci200QS"},
}

# Dimension mayor REAL (m) de cada bloque tal como se ve en el diseno aprobado (medida de las instancias de la Villa).
# Sirve para autocalibrar la escala: definiciones en mm (biblioteca) o en m (convertidas a mano) y planos en otras unidades.
# Medidas de la INSTANCIA insertada desde bloques_schaller_corregido (mm -> m), no de la definicion.
TAM_M = {"cctevo58": 0.2685, "cctevo160": 0.4147, "l7": 0.3294, "simbiosis": 0.7524, "moon60": 0.692,
         "durastrip_ip68": 1.807, "durastrip_ip20": 1.816, "ci160": 0.450, "ci200qr": 0.5733, "ci200qs": 0.583}

# Bloques que el MCP sabe CREAR si no estan ni en el plano ni en la biblioteca (asi un companero no queda bloqueado por una
# biblioteca incompleta). Circulos [dx, dy, radio] en METROS, centrados en el origen. SIMBIOSIS: 0.55 x 0.40 m (medido del plano aprobado).
DEFINICIONES_INTERNAS: dict = {}   # {nombre_de_bloque: {"circulos": [[dx, dy, radio], ...]}}; vacio: la biblioteca corregida trae todo

CAPAS_COLOR = {"SCH_ILUMINACION": 4, "SCH_AUDIO": 6}
ALTURA_ROTULO = 0.035
TOL_DUPLICADO = 0.30          # m: mismo bloque a menos de esto de una posicion = ya esta puesto (evita luces "casi duplicadas")
SEPARACION_MINIMA = 0.15      # m entre dos luminarias del mismo plan (aviso, no error)


class ErrorUbicacion(ValueError):
    """Peticion que no se puede resolver (receta o producto desconocido, datos que faltan)."""


# ----------------------------------------------------------------------------------------------------------------- geometria
def rect(host: dict) -> dict:
    x0, y0, x1, y1 = (float(host[k]) for k in ("x0", "y0", "x1", "y1"))
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2, "w": x1 - x0, "h": y1 - y0}


def marco_borde(r: dict, borde: str) -> dict:
    """Marco con origen en el centro del borde `borde` (N/S/E/W); v entra hacia el interior del mueble.

    Devuelve: origen, ejes u y v (vectores unitarios), ancho (largo del borde) y largo (profundidad del mueble desde ese borde).
    """
    b = str(borde or "").strip().upper()[:1]
    if b == "N":
        return {"o": (r["cx"], r["y1"]), "u": (1, 0), "v": (0, -1), "ancho": r["w"], "largo": r["h"], "rot": 0.0}
    if b == "S":
        return {"o": (r["cx"], r["y0"]), "u": (1, 0), "v": (0, 1), "ancho": r["w"], "largo": r["h"], "rot": 0.0}
    if b in ("W", "O"):
        return {"o": (r["x0"], r["cy"]), "u": (0, 1), "v": (1, 0), "ancho": r["h"], "largo": r["w"], "rot": math.pi / 2}
    if b == "E":
        return {"o": (r["x1"], r["cy"]), "u": (0, 1), "v": (-1, 0), "ancho": r["h"], "largo": r["w"], "rot": math.pi / 2}
    raise ErrorUbicacion("Indica el borde/cabecera: N, S, E u O (oeste).")


def punto(m: dict, u: float, v: float) -> tuple[float, float]:
    return (m["o"][0] + u * m["u"][0] + v * m["v"][0], m["o"][1] + u * m["u"][1] + v * m["v"][1])


# ----------------------------------------------------------------------------------------------------------------- rayos y muros
DIST_MAX_RAYO = 6.0           # m: mas lejos que esto no se considera "el muro de este mueble"
DIST_CABECERA = 0.60          # m: una cabecera se apoya (casi) contra el muro
LADOS = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "O": (-1, 0)}


def rayo_a_segmento(px, py, dx, dy, seg) -> float | None:
    """Distancia a lo largo del rayo (px,py)+t*(dx,dy), t>=0, hasta el segmento seg=(x1,y1,x2,y2). None si no lo cruza."""
    x1, y1, x2, y2 = seg
    ex, ey = x2 - x1, y2 - y1
    den = dx * ey - dy * ex
    if abs(den) < 1e-12:
        return None                         # paralelos
    t = ((x1 - px) * ey - (y1 - py) * ex) / den
    u = ((x1 - px) * dy - (y1 - py) * dx) / den
    if t < 0 or not -1e-9 <= u <= 1 + 1e-9:
        return None
    return t


def rayo_a_muros(px, py, dx, dy, muros, max_dist=DIST_MAX_RAYO):
    """(distancia, segmento) del primer muro en esa direccion, o (None, None). El primero que cruza el rayo: no salta a otro ambiente."""
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    mejor, seg_mejor = None, None
    for seg in muros:
        t = rayo_a_segmento(px, py, dx, dy, seg)
        if t is not None and t <= max_dist and (mejor is None or t < mejor):
            mejor, seg_mejor = t, seg
    return mejor, seg_mejor


def distancias_por_lado(r: dict, muros, max_dist=DIST_MAX_RAYO) -> dict:
    """Distancia al muro mas cercano saliendo de cada borde del mueble (3 rayos por lado: a 1/4, 1/2 y 3/4 del borde)."""
    res = {}
    for lado, (dx, dy) in LADOS.items():
        if lado in ("N", "S"):
            y = r["y1"] if lado == "N" else r["y0"]
            origenes = [(r["x0"] + f * r["w"], y) for f in (0.25, 0.5, 0.75)]
        else:
            x = r["x1"] if lado == "E" else r["x0"]
            origenes = [(x, r["y0"] + f * r["h"]) for f in (0.25, 0.5, 0.75)]
        ds = [d for d in (rayo_a_muros(ox, oy, dx, dy, muros, max_dist)[0] for ox, oy in origenes) if d is not None]
        res[lado] = round(min(ds), 3) if ds else None
    return res


def inferir_cabecera(r: dict, muros) -> tuple[str | None, dict]:
    """Lado de la cabecera = el borde apoyado contra un muro (< 0.6 m) y claramente mas cerca que los demas.

    Devuelve (lado o None, distancias por lado). None = sin muros utiles o ambiguo: hay que pedir la cabecera, no adivinar.
    """
    dist = distancias_por_lado(r, muros)
    cerca = sorted((d, l) for l, d in dist.items() if d is not None and d <= DIST_CABECERA)
    if not cerca:
        return None, dist
    if len(cerca) > 1 and cerca[1][0] - cerca[0][0] < 0.15:
        return None, dist                   # dos lados igual de pegados: ambiguo
    return cerca[0][1], dist


def rot_para_apuntar(producto: str, dx: float, dy: float) -> float:
    """Rotacion (rad) para que el frente del bloque (a rotacion 0) apunte hacia (dx,dy)."""
    frente = PRODUCTOS[producto].get("frente")
    if frente is None:
        raise ErrorUbicacion(f"'{producto}' no tiene direccion de frente definida (no es un elemento direccional).")
    return (math.atan2(dy, dx) - frente) % (2 * math.pi)


# ----------------------------------------------------------------------------------------------------------------- piezas
CANDIDATAS_ESCALA = (1.0, 0.001, 0.01, 0.1, 0.0254, 1000.0, 100.0, 10.0)


def escala_por_medida(d_def: float | None, tam_m: float | None, unidad_m: float, escala_catalogo: float) -> tuple[float, str]:
    """Escala de insercion a partir de lo MEDIDO: d_def = dimension mayor de la definicion (unidades del bloque), tam_m = tamano
    fisico esperado (m), unidad_m = metros por unidad del plano. Acierta con definiciones en mm o en m y con planos en cualquier unidad."""
    if not tam_m or not d_def or d_def <= 0 or unidad_m <= 0:
        return escala_catalogo, "catalogo (no se pudo medir)"
    ideal = (tam_m / unidad_m) / d_def
    cand = min(CANDIDATAS_ESCALA, key=lambda c: abs(math.log(ideal / c)))
    if 0.7 <= ideal / cand <= 1.43:
        return cand, "medida"
    return escala_catalogo, f"catalogo (la medida no cuadra: escala ideal {ideal:.4g})"


ALIAS_PRODUCTOS = {"simbiosi": "simbiosis"}      # nombres que la gente escribe mal o abrevia -> clave del catalogo


def _compacto(nombre) -> str:
    return re.sub(r"[^a-z0-9]", "", str(nombre).lower())


def es_biblioteca(nombre) -> bool:
    """True si el dibujo es una biblioteca de bloques Schaller. Acepta espacio, guion o guion bajo: 'bloques schaller_corregido.dwg'."""
    return "bloquesschaller" in _compacto(nombre)


def prioridad_biblioteca(nombre) -> int:
    """0 = biblioteca CORREGIDA (la oficial desde 25/11/2026), 1 = otra biblioteca Schaller (antigua), 2 = no es biblioteca."""
    if not es_biblioteca(nombre):
        return 2
    return 0 if "corregid" in _compacto(nombre) else 1


def colocacion(producto: str, x: float, y: float, rot: float = 0.0, etiquetar: bool = True, nota: str = "") -> dict:
    producto = ALIAS_PRODUCTOS.get(str(producto).strip().lower(), str(producto).strip().lower())
    if producto not in PRODUCTOS:
        raise ErrorUbicacion(f"Producto '{producto}' no esta en el catalogo. Opciones: {', '.join(sorted(PRODUCTOS))}.")
    p = PRODUCTOS[producto]
    c = {"producto": producto, "bloque": p["bloque"], "x": round(x, 3), "y": round(y, 3), "rot": round(rot, 5),
         "capa": p["capa"], "escala": pd.obtener_escala_bloque(p["bloque"]), "ancla": p.get("ancla", "insercion"),
         "tam_m": TAM_M.get(producto)}
    if nota:
        c["nota"] = nota
    if etiquetar:
        pide, texto, capa, color = pd.requiere_texto_referencia(p["bloque"])
        if pide:   # solo los bloques que NO traen su referencia dibujada
            c["etiqueta"] = {"texto": texto, "x": round(x + 0.12, 3), "y": round(y + 0.06, 3), "altura": ALTURA_ROTULO,
                             "capa": capa, "color": color}
    return c


def _verificar_host(r: dict, minimo: float, nombre: str, avisos: list):
    if min(r["w"], r["h"]) < minimo:
        avisos.append(f"El anfitrion mide {r['w']:.2f} x {r['h']:.2f} m: parece demasiado pequeno para '{nombre}'. Revisa que sea el mueble correcto.")


# ----------------------------------------------------------------------------------------------------------------- recetas
def receta_cama(host: dict, op: dict) -> tuple[list, list]:
    """Tira en la cabecera + 6 proyectores: 2 filas laterales a cada lado y 2 a los pies.

    Opciones: cabecera (N/S/E/O, obligatoria), ancho_cama (si el bloque incluye mesas de noche y el bbox es mayor que la cama),
    margen_lateral (0.45), filas (0.70, 1.70) distancia desde la cabecera, margen_pies (0.38), u_pies (0.45),
    producto (cctevo58), tira (durastrip_ip68 o None).
    """
    r, avisos = rect(host), []
    m = marco_borde(r, op.get("cabecera"))
    _verificar_host(r, 0.8, "cama", avisos)
    ancho = float(op.get("ancho_cama") or m["ancho"])
    largo = m["largo"]
    ml = float(op.get("margen_lateral", 0.45))
    filas = [float(f) for f in op.get("filas", (0.70, 1.70))]
    mp = float(op.get("margen_pies", 0.38))
    up = float(op.get("u_pies", 0.45))
    spot = op.get("producto", "cctevo58")
    etiquetar = bool(op.get("etiquetar", True))
    fuera = [f for f in filas if f > largo - 0.2]
    if fuera:
        avisos.append(f"Fila(s) a {fuera} m exceden el largo de la cama ({largo:.2f} m); se mantienen, revisa.")
    plan = []
    if op.get("tira", "durastrip_ip68"):
        x, y = punto(m, 0.0, 0.05)
        plan.append(colocacion(op.get("tira", "durastrip_ip68"), x, y, m["rot"], etiquetar, "tira en la cabecera"))
    for v in filas:
        for lado in (-1, 1):
            x, y = punto(m, lado * (ancho / 2 + ml), v)
            plan.append(colocacion(spot, x, y, 0.0, etiquetar, f"lateral a {v:.2f} m de la cabecera"))
    for lado in (-1, 1):
        x, y = punto(m, lado * up, largo + mp)
        plan.append(colocacion(spot, x, y, 0.0, etiquetar, "a los pies"))
    return plan, avisos


def receta_centro(host: dict, op: dict) -> tuple[list, list]:
    """1 producto centrado en el anfitrion (suspension sobre mesa, parlante en bano o estar). Opciones: producto, du, dv (m)."""
    r = rect(host)
    prod = op.get("producto")
    if not prod:
        raise ErrorUbicacion("receta 'centro' necesita producto (ej. simbiosis, moon60, ci160, ci200qr).")
    x, y = r["cx"] + float(op.get("du", 0)), r["cy"] + float(op.get("dv", 0))
    return [colocacion(prod, x, y, math.radians(float(op.get("rotacion_grados", 0))), bool(op.get("etiquetar", True)), "centro del anfitrion")], []


def receta_mesa_4x(host: dict, op: dict) -> tuple[list, list]:
    """4 productos (2x2) centrados sobre una mesa, ignorando las sillas. Separacion segun el tamano de la mesa."""
    r, avisos = rect(host), []
    _verificar_host(r, 0.6, "mesa", avisos)
    du = float(op.get("du") or min(max(r["w"] * 0.2, 0.30), 0.75))
    dv = float(op.get("dv") or min(max(r["h"] * 0.25, 0.30), 0.60))
    prod = op.get("producto", "ci160")
    plan = [colocacion(prod, r["cx"] + sx * du, r["cy"] + sy * dv, 0.0, bool(op.get("etiquetar", True)), "2x2 sobre la mesa")
            for sy in (1, -1) for sx in (-1, 1)]
    return plan, avisos


def receta_tira_borde(host: dict, op: dict) -> tuple[list, list]:
    """Una tira Durastrip centrada en un borde del anfitrion (cabecera, mesada, foseado). Opciones: borde, tira, inset (0.05)."""
    r = rect(host)
    m = marco_borde(r, op.get("borde") or op.get("cabecera"))
    x, y = punto(m, 0.0, float(op.get("inset", 0.05)))
    return [colocacion(op.get("tira", "durastrip_ip68"), x, y, m["rot"], bool(op.get("etiquetar", True)), "tira sobre el borde")], []


def receta_linea(host: dict, op: dict) -> tuple[list, list]:
    """n productos repartidos a lo largo del eje largo del anfitrion (isla, mesada). Opciones: producto, n (2), offset (m, perpendicular)."""
    r = rect(host)
    n = int(op.get("n", 2))
    if not 1 <= n <= 12:
        raise ErrorUbicacion("n debe estar entre 1 y 12.")
    prod = op.get("producto")
    if not prod:
        raise ErrorUbicacion("receta 'linea' necesita producto.")
    off = float(op.get("offset", 0.0))
    horizontal = r["w"] >= r["h"]
    plan = []
    for i in range(n):
        f = (i + 1) / (n + 1)
        if horizontal:
            x, y = r["x0"] + f * r["w"], r["cy"] + off
        else:
            x, y = r["cx"] + off, r["y0"] + f * r["h"]
        plan.append(colocacion(prod, x, y, 0.0, bool(op.get("etiquetar", True)), f"{i + 1}/{n} a lo largo del eje largo"))
    return plan, []


def receta_pared_frente(host: dict, op: dict) -> tuple[list, list]:
    """Productos de pared (parlantes Ci200QS) en el muro que mira el anfitrion, orientados hacia el.

    Lanza un rayo desde el centro del anfitrion hacia `direccion` (N/S/E/O; si se da `cabecera`, hacia los pies) hasta el
    PRIMER muro y coloca n productos a +-separacion/2 del punto de impacto, sobre la cara interior. Requiere muros.
    Opciones: direccion o cabecera, producto (ci200qs), n (2), separacion (1.30 m).
    """
    r = rect(host)
    muros = op.get("_muros") or []
    lado = str(op.get("direccion") or "").strip().upper()[:1].replace("W", "O")
    if not lado and op.get("cabecera"):
        lado = {"N": "S", "S": "N", "E": "O", "O": "E", "W": "E"}.get(str(op["cabecera"]).strip().upper()[:1], "")
    if lado not in LADOS:
        raise ErrorUbicacion("receta 'pared_frente' necesita direccion (N/S/E/O) o cabecera.")
    dx, dy = LADOS[lado]
    dist, _ = rayo_a_muros(r["cx"], r["cy"], dx, dy, muros)
    if dist is None:
        raise ErrorUbicacion(f"No hay muro al {lado} del anfitrion en {DIST_MAX_RAYO:g} m: el plano no trae muros ahi "
                             "(revisa las capas de muros) o usa la receta 'centro' con du/dv para fijar el punto.")
    hx, hy = r["cx"] + dx * dist, r["cy"] + dy * dist
    prod = op.get("producto", "ci200qs")
    n = int(op.get("n", 2))
    sep = float(op.get("separacion", 1.30))
    rot = rot_para_apuntar(prod, -dx, -dy)                      # la rejilla mira hacia el anfitrion
    plan = []
    for i in range(n):
        off = (i - (n - 1) / 2) * sep
        x, y = (hx + off, hy) if lado in ("N", "S") else (hx, hy + off)
        plan.append(colocacion(prod, x, y, rot, bool(op.get("etiquetar", True)), f"en el muro {lado} a {dist:.2f} m, mirando al anfitrion"))
    return plan, []


def receta_en_puntos(host: dict, op: dict) -> tuple[list, list]:
    """Un producto en cada punto EXACTO [[x, y], ...]: los puntos confirmados por el usuario (guardados en el perfil del proyecto) o dados a mano.

    Opciones: producto, puntos, rotacion_grados (0), apuntar_a [x, y] (para productos direccionales: cada uno se gira hacia ese punto).
    No calcula nada del anfitrion: sirve cuando la posicion ya se conoce (compartimento de un bano, poceta, proyectores de una sala).
    """
    prod = op.get("producto")
    puntos = op.get("puntos")
    if not prod or not puntos:
        raise ErrorUbicacion("receta 'en_puntos' necesita producto y puntos [[x, y], ...]; si el anfitrion los tiene en su perfil, "
                             "usalos (atributos del escaner) en vez de preguntar.")
    clave = ALIAS_PRODUCTOS.get(str(prod).strip().lower(), str(prod).strip().lower())
    rot0 = math.radians(float(op.get("rotacion_grados", 0)))
    objetivo = op.get("apuntar_a")
    plan = []
    for p in puntos:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise ErrorUbicacion(f"punto invalido {p!r}: cada punto debe ser [x, y].")
        rot = rot_para_apuntar(clave, float(objetivo[0]) - x, float(objetivo[1]) - y) if objetivo else rot0
        plan.append(colocacion(prod, x, y, rot, bool(op.get("etiquetar", True)), "en punto indicado"))
    return plan, []


# Atributos del perfil del proyecto que actuan como opciones por defecto de una receta (lo que se paso explicitamente tiene prioridad).
OPCIONES_DEL_PERFIL = {"cabecera", "cabecera_local", "ancho_cama", "filas", "margen_lateral", "margen_pies", "u_pies", "puntos"}

RECETAS = {
    "en_puntos": (receta_en_puntos, "Producto en puntos exactos [[x,y],...] (confirmados en el perfil o dados a mano); opcional apuntar_a o rotacion_grados."),
    "pared_frente": (receta_pared_frente, "Parlantes de pared en el primer muro que mira el anfitrion (rayo), orientados hacia el. Requiere muros."),
    "cama": (receta_cama, "Tira Durastrip en la cabecera + 6 CCTEvo (2 filas laterales + 2 a los pies). Requiere cabecera N/S/E/O."),
    "centro": (receta_centro, "1 producto centrado en el anfitrion (suspension sobre mesa, parlante de bano/estar). Requiere producto."),
    "mesa_4x": (receta_mesa_4x, "4 productos 2x2 sobre una mesa (por defecto parlantes Ci160CRDS)."),
    "tira_borde": (receta_tira_borde, "Durastrip centrada en un borde (N/S/E/O) del anfitrion."),
    "linea": (receta_linea, "n productos a lo largo del eje largo del anfitrion. Requiere producto."),
}


# ----------------------------------------------------------------------------------------------------------------- marco local del anfitrion
# Un anfitrion girado (por ejemplo 45 grados) tiene una caja envolvente mayor que su dibujo: calcular sobre ella pone las piezas mal.
# Con la TRANSFORMACION de la instancia (punto de insercion, rotacion, escala, reflejo) y la caja LOCAL de su definicion, las recetas se
# calculan en el marco del propio mueble (sus ejes) y el resultado se lleva a coordenadas del plano. Ahi "N" es el lado +Y del DIBUJO del bloque:
# la cabecera de una cama es la misma sea cual sea el giro, el reflejo o la escala de la instancia.
EPS_ANGULO = 1e-3


def es_ortogonal(rot_rad: float) -> bool:
    """True si el giro es multiplo de 90 grados (la caja envolvente coincide con el rectangulo orientado)."""
    return abs(math.sin(2 * float(rot_rad))) < EPS_ANGULO


def marco_desde_instancia(host: dict):
    """(cx, cy, e1, e2, w, h) del anfitrion o None si no hay datos para construirlo.

    e1, e2: ejes locales (unitarios, en el plano) hacia donde apuntan +X y +Y del dibujo del bloque; un reflejo invierte el sentido del eje.
    Con `caja_local` (caja de la definicion en coordenadas del bloque) es exacto para cualquier giro; sin ella solo para giros ortogonales.
    """
    inst = host.get("instancia") or {}
    if not inst or inst.get("normal_no_z"):
        return None
    r, sx, sy = float(inst.get("rot_rad", 0.0)), float(inst.get("sx", 1.0)), float(inst.get("sy", 1.0))
    if sx == 0 or sy == 0:
        return None
    c, s_ = math.cos(r), math.sin(r)
    e1 = (math.copysign(1.0, sx) * c, math.copysign(1.0, sx) * s_)
    e2 = (-math.copysign(1.0, sy) * s_, math.copysign(1.0, sy) * c)
    caja = inst.get("caja_local")
    if caja:
        x0, y0, x1, y1 = (float(v) for v in caja)
        qx, qy = (x0 + x1) / 2, (y0 + y1) / 2
        cx = inst["ins"][0] + c * sx * qx - s_ * sy * qy
        cy = inst["ins"][1] + s_ * sx * qx + c * sy * qy
        return cx, cy, e1, e2, abs(sx) * (x1 - x0), abs(sy) * (y1 - y0)
    if not es_ortogonal(r):
        return None
    r_ = rect(host)                                           # giro de 0/90/180/270: la caja del plano ES el rectangulo orientado
    cuarto = round(r / (math.pi / 2)) % 2
    w, h = (r_["w"], r_["h"]) if cuarto == 0 else (r_["h"], r_["w"])
    return r_["cx"], r_["cy"], e1, e2, w, h


def _a_local(marco, x, y):
    cx, cy, e1, e2, _w, _h = marco
    dx, dy = x - cx, y - cy
    return dx * e1[0] + dy * e1[1], dx * e2[0] + dy * e2[1]


def _a_mundo(marco, a, b):
    cx, cy, e1, e2, _w, _h = marco
    return cx + a * e1[0] + b * e2[0], cy + a * e1[1] + b * e2[1]


def _planear_en_marco_local(receta: str, host: dict, op: dict, muros, marco) -> tuple[list, list]:
    _cx, _cy, e1, e2, w, h = marco
    local = {"nombre": host.get("nombre", ""), "x0": -w / 2, "y0": -h / 2, "x1": w / 2, "y1": h / 2, "w": w, "h": h}
    muros_local = [(*_a_local(marco, a, b), *_a_local(marco, c, d)) for a, b, c, d in (muros or [])]
    opciones = {k: v for k, v in op.items() if not k.startswith("_") and k != "marco"}
    plan, avisos = planear(receta, local, opciones, muros=muros_local)
    salida = []
    for c in plan:
        x, y = _a_mundo(marco, c["x"], c["y"])
        vx = math.cos(c["rot"]) * e1[0] + math.sin(c["rot"]) * e2[0]       # direccion local de la pieza -> direccion en el plano
        vy = math.cos(c["rot"]) * e1[1] + math.sin(c["rot"]) * e2[1]
        d = {**c, "x": round(x, 3), "y": round(y, 3), "rot": round(math.atan2(vy, vx), 5)}
        if c.get("etiqueta"):
            ex, ey = _a_mundo(marco, c["etiqueta"]["x"], c["etiqueta"]["y"])
            d["etiqueta"] = {**c["etiqueta"], "x": round(ex, 3), "y": round(ey, 3)}
        salida.append(d)
    grados = math.degrees(math.atan2(e1[1], e1[0]))
    return salida, [f"Anfitrion calculado en su marco local (giro {grados:.1f} grados): las orientaciones N/S/E/O de la receta son las de su dibujo."] + avisos


def combinar_opciones(guardado: dict | None, explicitas: dict | None) -> dict:
    """Atributos del perfil + opciones explicitas de la llamada. Lo explicito manda; y la cabecera explicita (en el plano) anula la cabecera_local
    del perfil, mientras que una cabecera_local del perfil (mas reciente, en coordenadas del dibujo del bloque) anula una cabecera global antigua."""
    g, e = dict(guardado or {}), dict(explicitas or {})
    if "cabecera" in e or "cabecera_local" in e:
        g.pop("cabecera", None)
        g.pop("cabecera_local", None)
    elif "cabecera_local" in g:
        g.pop("cabecera", None)
    return {**g, **e}


def planear(receta: str, host: dict, opciones: dict | None = None, muros=None) -> tuple[list, list]:
    """Calcula las colocaciones. `muros` = segmentos (x1,y1,x2,y2): permiten deducir la cabecera y orientar por rayos.

    Si el anfitrion trae su `instancia` (punto de insercion, rotacion, escala, caja local) y esta girado en un angulo no ortogonal, o la
    receta pide marco="local" (o el perfil trae cabecera_local), se calcula en el marco del propio mueble. Para giros ortogonales sin esa
    peticion el resultado es el de siempre (caja del plano)."""
    if receta not in RECETAS:
        raise ErrorUbicacion(f"Receta '{receta}' desconocida. Opciones: {', '.join(RECETAS)}.")
    op = dict(opciones or {})
    if "cabecera_local" in op:                                 # orientacion funcional guardada en coordenadas del dibujo del bloque
        op["cabecera"] = op.pop("cabecera_local")
        op["marco"] = "local"
    inst = host.get("instancia")
    if inst and receta != "en_puntos":
        pide_local = op.get("marco") == "local" or not es_ortogonal(inst.get("rot_rad", 0.0))
        if pide_local:
            marco = marco_desde_instancia(host)
            if marco is not None:
                return _planear_en_marco_local(receta, host, op, muros, marco)
            if op.get("marco") == "local":
                raise ErrorUbicacion("El anfitrion esta girado en un angulo no ortogonal y no pude leer la caja de su definicion: no calculo sobre su caja envolvente.")
    op["_muros"] = list(muros or [])
    previos = []
    if inst and receta != "en_puntos" and not es_ortogonal(inst.get("rot_rad", 0.0)):
        previos.append(f"Anfitrion girado {math.degrees(inst['rot_rad']) % 360:.1f} grados y no pude leer la caja de su definicion: el calculo usa su caja "
                       "envolvente en el plano y puede no coincidir con el mueble. Revisa el resultado.")
    if receta == "cama" and not op.get("cabecera"):
        lado, dist = inferir_cabecera(rect(host), op["_muros"])
        if not lado:
            raise ErrorUbicacion(f"No pude deducir la cabecera por muros (distancia al muro por lado: {dist}). Indica cabecera N/S/E/O.")
        op["cabecera"] = lado
        previos.append(f"Cabecera {lado} deducida por rayos a muros (distancias por lado: {dist}).")
    plan, avisos = RECETAS[receta][0](host, op)
    avisos = previos + avisos
    for i, a in enumerate(plan):
        for b in plan[i + 1:]:
            if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < SEPARACION_MINIMA and a["bloque"] == b["bloque"] and not PRODUCTOS[a["producto"]].get("lineal"):
                avisos.append(f"Dos {a['producto']} quedan a menos de {SEPARACION_MINIMA} m ({a['x']}, {a['y']}).")
                break
    return plan, avisos


def sin_duplicados(plan: list, existentes: list, tol: float = TOL_DUPLICADO) -> tuple[list, list]:
    """Separa lo que ya esta puesto (mismo bloque a menos de `tol` m) de lo nuevo. Hace la colocacion idempotente."""
    nuevas, omitidas = [], []
    for c in plan:
        ya = any(e["bloque"] == c["bloque"] and math.hypot(e["x"] - c["x"], e["y"] - c["y"]) <= tol for e in existentes)
        (omitidas if ya else nuevas).append(c)
    return nuevas, omitidas


def catalogo() -> dict:
    return {
        "productos": {k: {"bloque": v["bloque"], "capa": v["capa"], "descripcion": v["descripcion"],
                          "escala": pd.obtener_escala_bloque(v["bloque"]), "rotulo_externo": pd.requiere_texto_referencia(v["bloque"])[1] or None}
                      for k, v in PRODUCTOS.items()},
        "recetas": {k: v[1] for k, v in RECETAS.items()},
    }
