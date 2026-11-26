"""Motor de ZONAS adaptable a cualquier tipo de proyecto (puro: sin AutoCAD, probable con pytest).

Evidencia, de mas a menos fiable:
  1. TEXTOS con nombre de espacio (vocabulario editable, multi-tipologia y multi-idioma) + POLIGONO cerrado que los contiene (limites reales).
  2. ROLES de mobiliario (cama, escritorio, mostrador...) por nombre de bloque, por el PERFIL del proyecto o por vocabulario.
  3. Agrupamiento de mobiliario cuando no hay textos ni poligonos (zonas "inferidas", confianza baja).
Nada de nombres ni coordenadas de un proyecto concreto vive aqui: lo propio de cada proyecto va en perfiles/<proyecto>.json.
"""
import hashlib
import json
import math
import re
from pathlib import Path

import clasificador
import medidas
import muros as muros_mod
import recintos
import plantas
import unidades

AQUI = Path(__file__).resolve().parent
RUTA_VOCABULARIO = AQUI / "vocabulario_espacios.json"

PRIORIDAD_ROL = ["cama", "sanitario", "isla", "cocina_mueble", "mesa_reuniones", "escritorio", "mostrador", "camilla",
                 "vitrina_exhibidor", "mesa_comedor", "sofa"]
CATEGORIAS_UBICUAS = 4           # una categoria presente en mas de 4 tipologias no aporta para deducir el tipo de proyecto
AREA_MIN_M2, AREA_MAX_M2 = 1.5, 4000.0
RECINTO_MIN_M2, RECINTO_MAX_M2, RECINTO_LADO_MIN_M = 3.0, 600.0, 1.2
RECINTO_MURO_MIN_M2, RECINTO_MURO_LADO_MIN_M = 1.5, 0.8      # un recinto ENCERRADO por muros puede ser pequeno (bano, closet); un poligono suelto de ese tamano es un mueble     # un poligono sin texto solo es CANDIDATO a recinto si es del tamano de una habitacion
MAX_RECINTOS_CANDIDATOS = 60
RADIO_ASOCIAR_M = 4.0            # mueble <-> texto cuando no hay poligono
HUECO_CLUSTER_M = 3.0            # muebles con menos de esto entre sus cajas son de la misma zona (sofas enfrentados, escritorios contiguos)


class Vocabulario:
    def __init__(self, datos: dict):
        self.datos = datos
        self.espacios = [(e["categoria"], list(e.get("grupos", [])), re.compile(e["patron"], re.I)) for e in datos["espacios"]]
        self.excluir = re.compile(datos["excluir_texto"], re.I)
        self.capas_rotulos = re.compile(datos["capas_rotulos"], re.I)
        self.contenedores = re.compile(datos["contenedores"], re.I)
        self.roles = [(r["rol"], re.compile(r["patron"], re.I)) for r in datos["roles"]]
        self.ignorar = re.compile(datos["ignorar_bloques"], re.I)
        self.capas_muros_rx = re.compile("|".join(datos.get("capas_muros") or []) or r"(?!x)x", re.I)
        self.capas_anotacion = re.compile(datos.get("capas_anotacion") or r"(?!x)x", re.I)     # cajetines, marcos, leyendas: ni recintos ni vistas
        self.capas_no_recinto = re.compile(datos.get("capas_no_recinto") or r"(?!x)x", re.I)  # ademas: mobiliario, vegetacion, cotas
        self.rol_a_zona = dict(datos["rol_a_zona"])
        self.nombres_roles = [r for r, _ in self.roles]
        self.tipologias = list(datos.get("tipologias", []))


def cargar_vocabulario(ruta=None) -> Vocabulario:
    with open(ruta or RUTA_VOCABULARIO, encoding="utf-8") as fh:
        return Vocabulario(json.load(fh))


# ----------------------------------------------------------------------------------------------------------------- textos
def normalizar(s) -> str:
    """Para comparar nombres: separadores (_ - .) y cambios letra/digito pasan a espacio, asi \b funciona en 'BED_KING_01' y 'WC2'."""
    s = re.sub(r"[_\-\.]+", " ", str(s or ""))
    s = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", s)
    return " ".join(s.split())


def limpiar_texto(s) -> str:
    """Quita los codigos de formato MText de AutoCAD (\\A1;, \\fCalibri;, \\P, {...}) y deja el texto legible."""
    s = str(s or "")
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace(r"\~", " ")
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\\[A-Za-z0-9._]+[^;\\]*;", "", s)
        s = re.sub(r"\\[A-Za-z][^;\\]*;", "", s)
    s = re.sub(r"\\P", " ", s)
    s = s.replace(r"\\", "").replace(r"\{", "{").replace(r"\}", "}").replace("{", "").replace("}", "")
    return " ".join(s.split())


def clasificar_texto(txt: str, vocab: Vocabulario):
    """(categoria, grupos) si el texto es el nombre de un espacio; None si no. Primera coincidencia del vocabulario."""
    t = (txt or "").strip()
    if len(t) < 3 or len(t) > 45:
        return None
    if re.search(r"^\d+([.,]\d+)?\s*(m|cm|mm|m2|m²|\"|')?$", t, re.I) or vocab.excluir.search(t):
        return None
    tn = normalizar(t)
    for cat, grupos, rx in vocab.espacios:
        if rx.search(t) or rx.search(tn):
            return cat, grupos
    return None


# ----------------------------------------------------------------------------------------------------------------- geometria
def area_poligono(pts) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def punto_en_poligono(x, y, pts) -> bool:
    dentro, n, j = False, len(pts), len(pts) - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi:
            dentro = not dentro
        j = i
    return dentro


def _centro(b):
    return (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2


def hueco_entre_cajas(a, b) -> float:
    """Distancia minima entre dos cajas (0 si se tocan o se solapan)."""
    dx = max(a["x0"] - b["x1"], b["x0"] - a["x1"], 0.0)
    dy = max(a["y0"] - b["y1"], b["y0"] - a["y1"], 0.0)
    return math.hypot(dx, dy)


# ----------------------------------------------------------------------------------------------------------------- perfil de proyecto
def slug_proyecto(nombre: str) -> str:
    base = re.sub(r"\.dwg$", "", str(nombre or "proyecto"), flags=re.I)
    return re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or "proyecto"


def perfil_vacio() -> dict:
    # atributos_bloques: lo que el usuario ya respondio sobre un bloque y no debe volver a preguntarsele (cabecera de una cama, ancho real,
    # puntos exactos de un compartimento...). Las herramientas lo usan solas como valores por defecto.
    return {"roles_bloques": {}, "ignorar_bloques": [], "zonas_manuales": [], "tipologia": None, "atributos_bloques": {}}


def atributos_de(perfil: dict, nombre: str) -> dict:
    """Atributos guardados para un bloque (sin distinguir mayusculas). {} si no hay."""
    nombre = (nombre or "").casefold()
    for k, v in (perfil or {}).get("atributos_bloques", {}).items():
        if k.casefold() == nombre:
            return dict(v)
    return {}


def cargar_perfil(carpeta, nombre_dibujo: str) -> dict:
    ruta = Path(carpeta) / f"{slug_proyecto(nombre_dibujo)}.json"
    base = perfil_vacio()
    if ruta.is_file():
        try:
            base.update(json.loads(ruta.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return base


def guardar_perfil(carpeta, nombre_dibujo: str, perfil: dict) -> Path:
    Path(carpeta).mkdir(parents=True, exist_ok=True)
    ruta = Path(carpeta) / f"{slug_proyecto(nombre_dibujo)}.json"
    ruta.write_text(json.dumps(perfil, indent=1, ensure_ascii=False), encoding="utf-8")
    return ruta


VERSION_MOTOR = 3                # esquema del resultado; ademas la version incluye el hash del codigo y del vocabulario


def version_motor(ruta_vocabulario=None) -> str:
    """Cambia sola si cambia el CODIGO de este modulo o el vocabulario editable: las caches viejas dejan de valer."""
    h = hashlib.sha1()
    for ruta in (Path(ruta_vocabulario or RUTA_VOCABULARIO), Path(__file__), Path(clasificador.__file__), clasificador.RUTA, Path(unidades.__file__), Path(plantas.__file__)):
        try:
            h.update(ruta.read_bytes())
        except OSError:
            pass
    return f"{VERSION_MOTOR}-{h.hexdigest()[:10]}"


def clave_cache(nombre_dibujo: str, n_objetos: int, perfil: dict, tipologia=None, version: str = "") -> str:
    h = hashlib.sha1(json.dumps([nombre_dibujo.casefold(), n_objetos, perfil, tipologia, version], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return h[:16]


# ----------------------------------------------------------------------------------------------------------------- mobiliario
def rol_de_bloque(nombre: str, capa: str, vocab: Vocabulario, perfil: dict):
    """(rol|None, ignorado: bool). El perfil del proyecto manda sobre el vocabulario."""
    n = (nombre or "").strip()
    low = n.casefold()
    if low in {x.casefold() for x in perfil.get("ignorar_bloques", [])}:
        return None, True
    for k, v in perfil.get("roles_bloques", {}).items():
        if k.casefold() == low:
            return v, False
    nn, cn = normalizar(n), normalizar(capa)
    if vocab.ignorar.search(n) or vocab.ignorar.search(nn):
        return None, True
    for rol, rx in vocab.roles:
        if rx.search(n) or rx.search(nn):
            return rol, False
    for rol, rx in vocab.roles:            # la capa como segunda evidencia (ej. capa "SANITARIOS")
        if rx.search(capa or "") or rx.search(cn):
            return rol, False
    return None, False


def _iou_bbox(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _contiene_bbox(a, b, tol=0.01) -> bool:
    ancho, alto = a[2] - a[0], a[3] - a[1]
    return a[0] - tol * ancho <= b[0] and a[1] - tol * alto <= b[1] and b[2] <= a[2] + tol * ancho and b[3] <= a[3] + tol * alto


def _poligonos_candidatos(polis: list, u: float, descartes: dict | None = None, detalle: dict | None = None) -> list:
    """Poligonos libres (sin texto) que pueden ser una habitacion. Descarta los pequenos o estrechos (muebles, franjas), los duplicados,
    los contornos que contienen varias habitaciones y los dobles trazos de muro (se queda el interior). `descartes` (opcional) cuenta POR QUE se descarto
    cada uno: nada se pierde sin explicacion."""
    d = descartes if descartes is not None else {}

    def anota(motivo):
        d[motivo] = d.get(motivo, 0) + 1
    libres = []
    for p in polis:
        de_muros = p.get("origen_poli") == "muros"
        a_min, l_min = (RECINTO_MURO_MIN_M2, RECINTO_MURO_LADO_MIN_M) if de_muros else (RECINTO_MIN_M2, RECINTO_LADO_MIN_M)
        lado = min(p["bbox"][2] - p["bbox"][0], p["bbox"][3] - p["bbox"][1]) * u
        if p["area_m2"] < a_min:
            anota("area_menor_al_minimo")
        elif p["area_m2"] > RECINTO_MAX_M2:
            anota("area_mayor_al_maximo")
        elif lado < l_min:
            anota("lado_estrecho")
        else:
            libres.append(p)
    unicos = []
    for p in sorted(libres, key=lambda q: q["area_m2"]):
        if not any(_iou_bbox(p["bbox"], q["bbox"]) > 0.9 for q in unicos):
            unicos.append(p)
        else:
            anota("duplicado")
    salida = []
    for p in unicos:
        # un hijo debe estar DENTRO del poligono (centro incluido), no solo de su caja: un recinto en L tiene caja que cubre a sus vecinos
        hijos = [q for q in unicos if q is not p and _contiene_bbox(p["bbox"], q["bbox"]) and q["area_m2"] < p["area_m2"]
                 and punto_en_poligono((q["bbox"][0] + q["bbox"][2]) / 2, (q["bbox"][1] + q["bbox"][3]) / 2, p["pts"])]
        if len(hijos) >= 2:
            anota("contorno_que_contiene_varios")            # contorno del edificio o de una planta
            if detalle is not None:
                # recintos contenidos "maximales" (no dentro de otro hijo): su suma es lo ya cubierto; el resto del contorno es ESPACIO ABIERTO (medida, sin uso asignado)
                maximales = [q for q in hijos if not any(r is not q and _contiene_bbox(r["bbox"], q["bbox"]) and r["area_m2"] > q["area_m2"] for r in hijos)]
                cubierta = sum(q["area_m2"] for q in maximales)
                b = p["bbox"]
                detalle.setdefault("espacios_abiertos", []).append({
                    "area_contorno_m2": round(p["area_m2"], 1), "ancho_m": round((b[2] - b[0]) * u, 2), "largo_m": round((b[3] - b[1]) * u, 2),
                    "recintos_contenidos": len(maximales), "area_contenida_m2": round(cubierta, 1), "area_libre_m2": round(max(0.0, p["area_m2"] - cubierta), 1),
                    "centro": [round((b[0] + b[2]) / 2 * u, 2), round((b[1] + b[3]) / 2 * u, 2)],
                    "aviso": "Contorno cerrado que contiene recintos: lo que no ocupan es espacio abierto o circulacion. Es una MEDIDA, no se le asigna uso."})
            continue
        if len(hijos) == 1 and hijos[0]["area_m2"] >= 0.6 * p["area_m2"]:
            anota("doble_trazo_de_muro")                      # el interior es el recinto
            continue
        salida.append(p)
    salida.sort(key=lambda q: -q["area_m2"])
    salida = salida[:MAX_RECINTOS_CANDIDATOS]
    salida.sort(key=lambda q: (round(q["bbox"][1], 1), q["bbox"][0]))
    return salida


def _medidas_plano(u, vistas, muros, segs, zonas, reconstruccion, decision=None, detalle_cand=None) -> dict:
    """Resumen cuantitativo del plano en METROS, sin ninguna regla de diseno: extension de cada vista, muros leidos, recintos y sus areas."""
    cuenta = {}
    for z in zonas:
        cuenta[z["origen"]] = cuenta.get(z["origen"], 0) + 1
    areas = [z["medidas"]["area_m2"] for z in zonas if z.get("medidas")]
    out = {"unidad_m": u,
           "vistas": [{"id": v["id"], "ancho_m": round((v["bbox"][2] - v["bbox"][0]) * u, 2), "alto_m": round((v["bbox"][3] - v["bbox"][1]) * u, 2),
                       "area_envolvente_m2": round((v["bbox"][2] - v["bbox"][0]) * (v["bbox"][3] - v["bbox"][1]) * u * u, 1), "elementos": v["n_elementos"]} for v in vistas],
           "muros": {"segmentos": len(segs), "longitud_total_m": round(sum(math.hypot(s_[2] - s_[0], s_[3] - s_[1]) for s_ in segs) * u, 1),
                     "capas": (muros or {}).get("capas", {}), "entidades_en_capas_de_muros": (muros or {}).get("entidades", 0), "truncado": bool((muros or {}).get("truncado")),
                     "como_se_eligieron": (decision or {}).get("modo", "ninguno"), "capas_usadas": (decision or {}).get("capas", []),
                     **({"aviso": "Ninguna capa se llama como un muro: se eligieron por su geometria (trazos largos y ortogonales). Es una hipotesis de confianza baja."}
                        if (decision or {}).get("modo") == "geometria" else {})},
           "lineas_por_capa": (decision or {}).get("estadisticas", {}),
           "recintos": {"total": len(zonas), "por_origen": cuenta, "con_medidas": len(areas), "area_total_m2": round(sum(areas), 1),
                        "area_media_m2": round(sum(areas) / len(areas), 1) if areas else None}}
    try:
        ejes = muros_mod.ejes_de_muro(segs, u)
        if ejes:
            out["muros"]["ejes"] = ejes
    except Exception:
        pass
    if detalle_cand and detalle_cand.get("espacios_abiertos"):
        ab = detalle_cand["espacios_abiertos"]
        out["espacios_abiertos"] = ab
        out["cobertura"] = {"area_recintos_m2": out["recintos"]["area_total_m2"], "area_espacios_abiertos_m2": round(sum(e["area_libre_m2"] for e in ab), 1)}
    if reconstruccion is not None:
        d = reconstruccion.get("diagnostico", {})
        out["reconstruccion_por_muros"] = {"ok": reconstruccion.get("ok"), "error": reconstruccion.get("error"), "recintos": len(reconstruccion.get("recintos", [])),
                                           "recintos_reconstruidos": reconstruccion.get("detalle", []),
                                           **{k: d[k] for k in ("aberturas_cerradas", "extremos_libres", "componentes_libres", "descartados", "pequenos_mayores", "detalle") if k in d}}
    return out


def _dim(b, unidad_m):
    return (b["x1"] - b["x0"]) * unidad_m, (b["y1"] - b["y0"]) * unidad_m


def _pista_por_tamano(w, h):
    a, b = sorted((w, h))
    if 1.3 <= a <= 2.4 and 1.8 <= b <= 2.6:
        return "podria ser una cama (solo por tamano: verificar)"
    return None


# ----------------------------------------------------------------------------------------------------------------- zonas
def _detalle(h: dict, perfil: dict) -> dict:
    """Ficha de un mueble en una zona. Si el usuario ya respondio cosas sobre el (perfil), van en 'atributos': no hay que volver a preguntar."""
    d = {k: h[k] for k in ("nombre", "rol", "x", "y", "w", "h")}
    for k in ("rol_origen", "confianza_rol"):
        if k in h:
            d[k] = h[k]
    a = atributos_de(perfil, h["nombre"])
    if a:
        d["atributos"] = a
    return d


def construir_zonas(raw: dict, vocab: Vocabulario, perfil: dict | None = None, tipologia: str | None = None) -> dict:
    """raw = {"unidad_m", "textos": [{t,x,y,capa}], "poligonos": [{capa,pts}], "bloques": [{n,capa,x0,y0,x1,y1}]}."""
    perfil = {**perfil_vacio(), **(perfil or {})}
    u_declarada = float(raw.get("unidad_m") or 1.0)
    # La unidad declarada (INSUNITS) puede no ser la real: se contrasta con el tamano de lo dibujado (bloques y poligonos) y, si no cuadra, se corrige.
    dims = [max(b["x1"] - b["x0"], b["y1"] - b["y0"]) for b in raw.get("bloques", [])]
    for pol in raw.get("poligonos", []):
        pts = pol.get("pts") or []
        if len(pts) >= 3:
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            dims.append(max(max(xs) - min(xs), max(ys) - min(ys)))
    segs_nombre = (raw.get("muros") or {}).get("segmentos") or []
    lineas = (raw.get("lineas") or {}).get("segmentos") or []
    for sg in segs_nombre[:500] + lineas[:500]:
        dims.append(math.hypot(sg[2] - sg[0], sg[3] - sg[1]))
    u, aviso_unidades = unidades.unidad_efectiva(u_declarada, dims, extension=max(dims) if dims else None)
    # que lineas son muros: por el nombre de la capa y, si ninguna se llama asi, por su geometria (hipotesis de confianza baja, informada)
    decision_muros = muros_mod.elegir(segs_nombre, lineas, vocab.capas_muros_rx, vocab.capas_no_recinto, u)
    segs_muros = decision_muros["segmentos"]
    radio = RADIO_ASOCIAR_M / u
    zonas = []

    # --- poligonos validos (limites reales de recintos)
    polis = []
    for p in raw.get("poligonos", []):
        pts = [tuple(q) for q in p["pts"]]
        if len(pts) < 3:
            continue
        a_m2 = area_poligono(pts) * u * u
        if AREA_MIN_M2 <= a_m2 <= AREA_MAX_M2:
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            polis.append({"pts": pts, "area_m2": a_m2, "bbox": (min(xs), min(ys), max(xs), max(ys)), "capa": p.get("capa", "")})

    # --- recintos reconstruidos desde los MUROS (planos sin rotulos ni polilineas de habitacion). Los trazos cerrados finos de capas de muros son muros macizos.
    reconstruccion = None
    solidos = []
    for pol in raw.get("poligonos", []):
        if vocab.capas_muros_rx.search(pol.get("capa", "")) and len(pol.get("pts") or []) >= 3:
            xs_, ys_ = [q[0] for q in pol["pts"]], [q[1] for q in pol["pts"]]
            lado_menor = min(max(xs_) - min(xs_), max(ys_) - min(ys_)) * u
            if lado_menor <= 0.6:
                solidos.append([tuple(q) for q in pol["pts"]])
    if segs_muros or solidos:
        reconstruccion = recintos.reconstruir(segs_muros, u, poligonos_muro=solidos)
        reconstruccion["detalle"] = [{"area_m2": rm["area_m2"], "ancho_m": mm_["ancho_m"], "largo_m": mm_["largo_m"], "rectangularidad": mm_["rectangularidad"],
                                      "centro": mm_["centro"]}
                                     for rm in reconstruccion.get("recintos", [])[:40] for mm_ in [medidas.medidas_recinto(rm["pts"], u)]]
        for rm in reconstruccion.get("recintos", []):
            xs_, ys_ = [q[0] for q in rm["pts"]], [q[1] for q in rm["pts"]]
            polis.append({"pts": [tuple(q) for q in rm["pts"]], "area_m2": rm["area_m2"], "bbox": (min(xs_), min(ys_), max(xs_), max(ys_)),
                          "capa": "muros", "origen_poli": "muros", "area_neta_m2": rm.get("area_neta_m2"), "huecos": rm.get("huecos", 0)})

    def poligono_de(x, y):
        mejor = None
        for p in polis:
            b = p["bbox"]
            if b[0] <= x <= b[2] and b[1] <= y <= b[3] and punto_en_poligono(x, y, p["pts"]):
                if mejor is None or p["area_m2"] < mejor["area_m2"]:
                    mejor = p
        return mejor

    # --- zonas por texto (+ poligono)
    vistos = set()
    n_reconocidos = 0
    for t in raw.get("textos", []):
        txt = limpiar_texto(t["t"])
        cl = clasificar_texto(txt, vocab)
        if cl is not None:
            n_reconocidos += 1
        poli = poligono_de(t["x"], t["y"])
        if cl is None:
            # nombre desconocido: solo si esta en una capa de rotulos Y dentro de un recinto (no es ruido)
            if not (poli and vocab.capas_rotulos.search(t.get("capa", "")) and 3 <= len(txt) <= 30 and not vocab.excluir.search(txt)
                    and not re.search(r"\d{3,}", txt)):
                continue
            cl = ("otro", [])
        clave = (txt.upper(), round(t["x"] * u), round(t["y"] * u))
        if clave in vistos:
            continue
        vistos.add(clave)
        z = {"nombre": txt, "tipo_espacio": cl[0], "grupos": cl[1], "x": round(t["x"], 3), "y": round(t["y"], 3),
             "capa": t.get("capa", ""), "origen": "texto", "confianza": "media", "bbox": None, "area_m2": None,
             "muebles": [], "muebles_detalle": [], "_poli": poli}
        if poli:
            b = poli["bbox"]
            de_muros = poli.get("origen_poli") == "muros"
            z.update(x=round((b[0] + b[2]) / 2, 3), y=round((b[1] + b[3]) / 2, 3), bbox=[round(v, 3) for v in b],
                     area_m2=round(poli["area_m2"], 2), origen="texto+muros" if de_muros else "texto+poligono", confianza="media" if de_muros else "alta")
        zonas.append(z)

    # --- recintos CANDIDATOS: poligonos del tamano de una habitacion que ningun texto reclamo (planos sin rotulos). Son hipotesis de confianza baja.
    reclamados = {id(z["_poli"]) for z in zonas if z.get("_poli")}
    libres = [q for q in polis if id(q) not in reclamados and not vocab.capas_no_recinto.search(q.get("capa", ""))]
    descartes_cand, detalle_cand = {}, {}
    for i, p in enumerate(_poligonos_candidatos(libres, u, descartes_cand, detalle_cand), 1):
        b = p["bbox"]
        zonas.append({"nombre": f"Recinto {i} (sin rotulo)", "tipo_espacio": "otro", "grupos": [], "x": round((b[0] + b[2]) / 2, 3),
                      "y": round((b[1] + b[3]) / 2, 3), "capa": "", "origen": "muros" if p.get("origen_poli") == "muros" else "poligono",
                      "confianza": "baja", "candidato": True,
                      "bbox": [round(v, 3) for v in b], "area_m2": round(p["area_m2"], 2), "muebles": [], "muebles_detalle": [],
                      "inferido_por": [], "_poli": p})

    # --- mobiliario: rol y asociacion a zonas
    definiciones = raw.get("definiciones") or {}
    hosts, ignorados, sin_rol = [], 0, []
    for b in raw.get("bloques", []):
        rol, ign = rol_de_bloque(b["n"], b.get("capa", ""), vocab, perfil)
        if ign:
            ignorados += 1
            continue
        cx, cy = _centro(b)
        d = {"nombre": b["n"], "rol": rol, "x": round(cx, 3), "y": round(cy, 3), "w": round(b["x1"] - b["x0"], 3),
             "h": round(b["y1"] - b["y0"], 3), "capa": b.get("capa", ""), "_b": b}
        if rol is None and b["n"] in definiciones:          # sin perfil ni nombre util: la definicion del bloque (nombres anidados, capas, tamano)
            cl = clasificador.clasificar(b["n"], b.get("capa", ""), d["w"] * u, d["h"] * u, definiciones[b["n"]], vocab)
            if clasificador.aceptado(cl):
                rol = d["rol"] = cl["rol"]
                d["rol_origen"], d["confianza_rol"] = "inferido", cl["confianza"]
            elif cl:
                d["_cl"] = cl
        (hosts if rol else sin_rol).append(d)

    for h in hosts:
        candidatas = [z for z in zonas if z["_poli"] and punto_en_poligono(h["x"], h["y"], z["_poli"]["pts"])]
        if candidatas:
            z = min(candidatas, key=lambda z: z["_poli"]["area_m2"])
        else:
            cercanas = [(math.hypot(h["x"] - z["x"], h["y"] - z["y"]), z) for z in zonas if not z["_poli"]]
            cercanas = [c for c in cercanas if c[0] <= radio]
            z = min(cercanas, key=lambda c: c[0])[1] if cercanas else None
        if z is not None:
            z["muebles"].append(h["nombre"])
            z["muebles_detalle"].append(_detalle(h, perfil))
            h["_asignado"] = True

    candidatos = [z for z in zonas if z.get("candidato")]
    for i, z in enumerate(candidatos, 1):
        roles = [m["rol"] for m in z["muebles_detalle"] if m["rol"] in vocab.rol_a_zona]
        if roles:
            dominante = min(roles, key=lambda r: PRIORIDAD_ROL.index(r) if r in PRIORIDAD_ROL else 99)
            tipo = vocab.rol_a_zona[dominante]
            z["tipo_espacio"] = tipo
            z["grupos"] = next((g for c, g, _ in vocab.espacios if c == tipo), [])
            z["nombre"] = f"{tipo.replace('_', ' ').capitalize()} {i} (sin rotulo)"
            inferidos = [m for m in z["muebles_detalle"] if m.get("rol_origen") == "inferido"]
            z["inferido_por"] = [f"tipo deducido del mobiliario ({', '.join(sorted(set(roles)))})" + (" [parte inferido por la definicion de sus bloques]" if inferidos else "")]
        else:
            z["inferido_por"] = ["sin mobiliario clasificado dentro: tipo desconocido"]

    # --- zonas inferidas por agrupamiento de mobiliario sin zona
    libres = [h for h in hosts if not h.get("_asignado") and h["rol"] in vocab.rol_a_zona]
    grupos, usados = [], set()
    for i, h in enumerate(libres):
        if i in usados:
            continue
        cola, miembros = [i], []
        usados.add(i)
        while cola:
            k = cola.pop()
            miembros.append(libres[k])
            for j, o in enumerate(libres):
                if (j not in usados and vocab.rol_a_zona[o["rol"]] == vocab.rol_a_zona[libres[k]["rol"]]      # solo entre muebles del mismo tipo de espacio
                        and hueco_entre_cajas(o["_b"], libres[k]["_b"]) <= HUECO_CLUSTER_M / u):
                    usados.add(j)
                    cola.append(j)
        grupos.append(miembros)
    contador = {}
    for miembros in grupos:
        roles = [m["rol"] for m in miembros]
        dominante = min(roles, key=lambda r: PRIORIDAD_ROL.index(r) if r in PRIORIDAD_ROL else 99)
        tipo = vocab.rol_a_zona[dominante]
        contador[tipo] = contador.get(tipo, 0) + 1
        ancla = next(m for m in miembros if m["rol"] == dominante)
        del_tipo = [m for m in miembros if vocab.rol_a_zona.get(m["rol"]) == tipo]
        if len(del_tipo) > 1:       # varios muebles del mismo tipo: el centro es el de su conjunto, no el de uno solo
            cx = (min(m["_b"]["x0"] for m in del_tipo) + max(m["_b"]["x1"] for m in del_tipo)) / 2
            cy = (min(m["_b"]["y0"] for m in del_tipo) + max(m["_b"]["y1"] for m in del_tipo)) / 2
        else:
            cx, cy = ancla["x"], ancla["y"]
        grupos_vocab = next((g for c, g, _ in vocab.espacios if c == tipo), [])
        zonas.append({"nombre": f"{tipo.replace('_', ' ').capitalize()} {contador[tipo]} (inferida: {ancla['nombre']})", "tipo_espacio": tipo,
                      "grupos": grupos_vocab, "x": round(cx, 3), "y": round(cy, 3), "capa": ancla["capa"], "origen": "mobiliario",
                      "confianza": "baja", "bbox": None, "area_m2": None, "muebles": sorted({m["nombre"] for m in miembros}),
                      "muebles_detalle": [_detalle(m, perfil) for m in miembros], "_poli": None})

    # --- zonas manuales del perfil (el usuario manda)
    for zm in perfil.get("zonas_manuales", []):
        zonas.append({"nombre": zm["nombre"], "tipo_espacio": zm.get("tipo", "otro"), "grupos": [], "x": float(zm["x"]), "y": float(zm["y"]),
                      "capa": "", "origen": "manual", "confianza": "alta", "bbox": zm.get("bbox"), "area_m2": None, "muebles": [],
                      "muebles_detalle": [], "_poli": None})

    # --- tipologia del proyecto
    pesos = {}
    for z in zonas:
        if len(z["grupos"]) > CATEGORIAS_UBICUAS:
            continue
        for g in z["grupos"]:
            pesos[g] = pesos.get(g, 0) + 1
    orden = sorted(pesos.items(), key=lambda kv: -kv[1])
    detectada = "indeterminada"
    if orden and orden[0][1] >= 2 and (len(orden) == 1 or orden[0][1] > orden[1][1]):
        detectada = orden[0][0]
    elegida = tipologia or perfil.get("tipologia") or detectada

    # --- pistas para que el usuario clasifique bloques anonimos
    resumen_sin_rol = {}
    for h in sin_rol:
        w, hh = _dim(h["_b"], u)
        if max(w, hh) < 1.0:
            continue
        r = resumen_sin_rol.setdefault(h["nombre"], {"nombre": h["nombre"], "cantidad": 0, "ancho_m": round(w, 2), "alto_m": round(hh, 2),
                                                      "ejemplo": [h["x"], h["y"]], "pista": _pista_por_tamano(w, hh)})
        if h.get("_cl") and "clasificacion_sugerida" not in r:
            r["clasificacion_sugerida"] = {k: h["_cl"][k] for k in ("rol", "confianza", "puntaje")}
        r["cantidad"] += 1
    sugerencias = sorted(resumen_sin_rol.values(), key=lambda r: -(r["ancho_m"] * r["alto_m"]))[:15]

    # --- vistas (plantas candidatas): geometria arquitectonica agrupada por separacion; cada zona se asigna a la suya
    cajas = [p["bbox"] for p in polis if not vocab.capas_anotacion.search(p.get("capa", ""))] + \
            [(h["_b"]["x0"], h["_b"]["y0"], h["_b"]["x1"], h["_b"]["y1"]) for h in hosts + sin_rol if "_b" in h]
    vistas = plantas.detectar(cajas, raw.get("textos", []), u)
    for z in zonas:
        z["vista"] = plantas.vista_de(vistas, z["x"], z["y"])
    for v in vistas:
        v["n_zonas"] = sum(1 for z in zonas if z["vista"] == v["id"])
    for z in zonas:
        if z.get("_poli"):                                   # medidas REALES del recinto (metros): area, perimetro, ancho x largo orientados, angulo, compacidad
            z["medidas"] = medidas.medidas_recinto(z["_poli"]["pts"], u)
            if z["_poli"].get("area_neta_m2") is not None and z["_poli"].get("huecos"):
                z["medidas"]["area_neta_m2"] = z["_poli"]["area_neta_m2"]
                z["medidas"]["huecos"] = z["_poli"]["huecos"]
    for z in zonas:
        z.pop("_poli", None)
    for h in hosts + sin_rol:
        h.pop("_b", None)
        h.pop("_cl", None)
    return {"zonas": zonas, "total": len(zonas), "tipologia": elegida, "tipologia_detectada": detectada, "tipologia_pesos": dict(orden),
            "bloques_ignorados": ignorados, "bloques_con_rol": len(hosts), "bloques_sin_rol": len(sin_rol),
            "sugerencias_roles": sugerencias, "unidad_m": u, "unidad_declarada_m": u_declarada, "aviso_unidades": aviso_unidades, "vistas": vistas,
            "medidas_plano": _medidas_plano(u, vistas, raw.get("muros"), segs_muros, zonas, reconstruccion, decision_muros, detalle_cand),
            "resumen_lectura": {"textos": len(raw.get("textos", [])), "textos_con_nombre_de_espacio": n_reconocidos,
                                "poligonos": len(raw.get("poligonos", [])), "poligonos_con_area_de_recinto": len([q for q in polis if q.get("origen_poli") != "muros"]),
                                "segmentos_de_muro": len(segs_muros), "descartes_de_candidatos": descartes_cand, "recintos_por_muros": len([q for q in polis if q.get("origen_poli") == "muros"]),
                                "recintos_candidatos": len([z for z in zonas if z.get("candidato")]),
                                "bloques": len(raw.get("bloques", [])), "bloques_con_rol": len(hosts), "bloques_sin_rol": len(sin_rol)}}
