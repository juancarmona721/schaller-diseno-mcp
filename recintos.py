"""Recintos reconstruidos a partir de MUROS (Fase 4; usa Shapely con importacion PEREZOSA: sin Shapely instalado devuelve un diagnostico y nada mas).

Idea: los muros (lineas, polilineas abiertas, trazos finos) se tratan como OBSTACULOS; lo que queda libre y esta encerrado es un recinto. No depende de
que haya rotulos, mobiliario ni polilineas de habitacion cerradas. Pasos: (1) cierre de las aberturas de puerta con segmentos virtuales (no se toca el
DWG); (2) los muros se engrosan un radio y se unen; (3) se resta de una envolvente: las regiones que tocan el borde son el exterior, las encerradas son
recintos; (4) se les devuelve el radio para volver a las caras de los muros. Todo en METROS internamente; las coordenadas de salida van en unidades
del dibujo. No se aplica ninguna regla de diseno: solo geometria y medidas.
"""
import importlib.util
import math

PARAMETROS = {
    "radio_muro_m": 0.12,         # un muro de dos caras de hasta ~24 cm se cierra solo; una cara suelta se engrosa a 24 cm
    "abertura_max_m": 1.1,        # una puerta o vano de hasta esto se cierra con un segmento virtual
    "tolerancia_extremo_m": 0.03, # un extremo de muro a menos de esto de otro muro "toca" (no es un extremo libre)
    "longitud_min_m": 0.02,       # trazos mas cortos son ruido (hatch explotado, puntos)
    "area_min_m2": 1.5,
    "area_max_m2": 600.0,
    "max_segmentos": 12000,
    "simplificar_m": 0.02,
}


def disponible() -> bool:
    try:
        return importlib.util.find_spec("shapely") is not None
    except (ImportError, ValueError):
        return False


def _segmentos_a_metros(segmentos, u, minimo):
    vistos, salida = set(), []
    for s in segmentos:
        x1, y1, x2, y2 = (float(v) * u for v in s[:4])
        if math.hypot(x2 - x1, y2 - y1) < minimo:
            continue
        clave = (round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3))
        inversa = (clave[2], clave[3], clave[0], clave[1])
        if clave in vistos or inversa in vistos:
            continue
        vistos.add(clave)
        salida.append((x1, y1, x2, y2))
    return salida


def _cierres_de_aberturas(lineas, p, sh):
    """Segmentos virtuales entre extremos LIBRES de muros distintos, a menos de `abertura_max_m`, sin cruzar otro muro. `lineas`: trozos de muro YA nodados
    (sin solapes duplicados). Un extremo es libre si ninguna otra linea lo toca (un extremo compartido por dos trozos colineales cuenta como compartido solo
    si el muro continua: aqui se cuenta cuantos trozos terminan en ese punto). Devuelve (lista de (x1,y1,x2,y2), cantidad de extremos libres)."""
    from shapely.strtree import STRtree
    arbol = STRtree(lineas)
    tol = p["tolerancia_extremo_m"]
    grado = {}
    for g in lineas:
        for q in (g.coords[0], g.coords[-1]):
            k = (round(q[0], 3), round(q[1], 3))
            grado[k] = grado.get(k, 0) + 1
    libres = []                                                   # (x, y, indice_de_trozo)
    for i, g in enumerate(lineas):
        for q in (g.coords[0], g.coords[-1]):
            if grado[(round(q[0], 3), round(q[1], 3))] != 1:
                continue
            pt = sh.Point(q[0], q[1])
            cerca = [j for j in arbol.query(pt.buffer(tol)) if j != i and lineas[j].distance(pt) <= tol]
            if not cerca:
                libres.append((q[0], q[1], i))
    if len(libres) < 2:
        return [], len(libres)
    pts = [sh.Point(x, y) for x, y, _ in libres]
    arbol_pts = STRtree(pts)
    cierres, usados = [], set()
    for k, (x, y, i) in enumerate(libres):
        cand = []
        for m in arbol_pts.query(pts[k].buffer(p["abertura_max_m"])):
            if m == k or libres[m][2] == i:
                continue
            d = pts[k].distance(pts[m])
            if d <= p["abertura_max_m"]:
                cand.append((d, m))
        cand.sort()
        for d, m in cand[:6]:                       # TODOS los extremos libres cercanos (no solo el mas cercano: el mas cercano suele ser la otra cara del
            par = (min(k, m), max(k, m))            # mismo muro, que cierra el grosor pero no el vano)
            if par in usados:
                continue
            cierre = sh.LineString([(x, y), (libres[m][0], libres[m][1])])
            cruza = False
            for j in arbol.query(cierre):
                if j in (i, libres[m][2]):
                    continue
                inter = cierre.intersection(lineas[j])
                if not inter.is_empty and inter.distance(pts[k]) > tol and inter.distance(pts[m]) > tol:
                    cruza = True                    # atraviesa otro muro: no es una abertura de ese muro
                    break
            if not cruza:
                usados.add(par)
                cierres.append((x, y, libres[m][0], libres[m][1]))
    return cierres, len(libres)


def reconstruir(segmentos: list, u: float = 1.0, poligonos_muro: list | None = None, parametros: dict | None = None) -> dict:
    """segmentos: [(x1,y1,x2,y2)] en unidades del dibujo; poligonos_muro: [[(x,y),...]] trazos cerrados finos que SON muros (opcional).

    Devuelve {"ok", "recintos": [{"pts": [...] (unidades del dibujo), "area_m2", "area_neta_m2", "huecos": n, "aberturas_cerradas": n}], "diagnostico": {...}}.
    """
    p = {**PARAMETROS, **(parametros or {})}
    diag = {"parametros": p}
    if not disponible():
        return {"ok": False, "error": "geometria_avanzada_no_disponible", "recintos": [],
                "diagnostico": {**diag, "detalle": "Shapely no esta instalado: no se reconstruyen recintos desde muros (el resto del escaneo funciona igual)."}}
    import shapely.geometry as sh
    from shapely.ops import unary_union
    segs = _segmentos_a_metros(segmentos[:p["max_segmentos"]], u, p["longitud_min_m"])
    sol = [[(x * u, y * u) for x, y in pol] for pol in (poligonos_muro or []) if len(pol) >= 3]
    diag.update(segmentos=len(segs), poligonos_muro=len(sol), longitud_muros_m=round(sum(math.hypot(c - a, d - b) for a, b, c, d in segs), 2))
    if len(segs) < 4 and not sol:
        return {"ok": True, "recintos": [], "diagnostico": {**diag, "detalle": "Muy pocos muros para reconstruir recintos."}}
    piezas = []
    if segs:
        nodadas = unary_union(sh.MultiLineString([[(a, b), (c, d)] for a, b, c, d in segs]))      # disuelve duplicados y solapes, parte en los cruces
        piezas = [g for g in (nodadas.geoms if hasattr(nodadas, "geoms") else [nodadas]) if g.geom_type == "LineString" and g.length >= p["longitud_min_m"]]
    cierres, n_libres = _cierres_de_aberturas(piezas, p, sh) if piezas else ([], 0)
    diag.update(extremos_libres=n_libres, aberturas_cerradas=len(cierres))
    r = p["radio_muro_m"]
    obst = []
    if piezas or cierres:
        lineas_obst = [[q for q in g.coords] for g in piezas] + [[(a, b), (c, d)] for a, b, c, d in cierres]
        obst.append(sh.MultiLineString(lineas_obst).buffer(r, cap_style=2, join_style=2))
    for pol in sol:
        try:
            obst.append(sh.Polygon(pol).buffer(0).buffer(r * 0.5, join_style=2))
        except Exception:
            pass
    muros = unary_union(obst)
    if muros.is_empty:
        return {"ok": True, "recintos": [], "diagnostico": {**diag, "detalle": "Sin geometria de muros utilizable."}}
    envolvente = muros.convex_hull.buffer(1.0)
    libre = envolvente.difference(muros)
    comps = list(libre.geoms) if hasattr(libre, "geoms") else [libre]
    borde = envolvente.boundary
    recintos, descartes = [], {"exterior": 0, "pequenos": 0, "grandes": 0, "irregulares": 0}
    for c in comps:
        if c.intersects(borde):
            descartes["exterior"] += 1
            continue
        # vuelve de la cara del obstaculo a la cara del muro: el contorno con esquinas VIVAS (mitre) y los huecos (columnas) con join redondo, porque el
        # mitre pierde los huecos pequenos
        exterior = sh.Polygon(c.exterior).buffer(r, join_style=2)
        if exterior.geom_type == "MultiPolygon":
            exterior = max(exterior.geoms, key=lambda g: g.area)
        huecos = [list(h.coords) for h in c.buffer(r, join_style=1, quad_segs=3).interiors] if len(c.interiors) else []
        c = sh.Polygon(exterior.exterior, huecos) if huecos else exterior
        if c.is_empty:
            continue
        area_neta = c.area
        if area_neta < p["area_min_m2"]:
            descartes["pequenos"] += 1
            continue
        if area_neta > p["area_max_m2"]:
            descartes["grandes"] += 1
            continue
        ext = sh.Polygon(c.exterior).simplify(p["simplificar_m"])
        if ext.is_empty or ext.area < p["area_min_m2"]:
            continue
        perim = ext.length
        if perim > 0 and 4 * math.pi * ext.area / (perim * perim) < 0.04:        # tira muy larga y fina: un hueco entre muros, no un recinto
            descartes["irregulares"] += 1
            continue
        recintos.append({"pts": [(x / u, y / u) for x, y in list(ext.exterior.coords)[:-1]], "area_m2": round(ext.area, 3),
                         "area_neta_m2": round(area_neta, 3), "huecos": len(c.interiors)})
    diag.update(componentes_libres=len(comps), descartados=descartes, recintos=len(recintos))
    return {"ok": True, "recintos": recintos, "diagnostico": diag}
