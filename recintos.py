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
    "ortogonal_dominante": 0.85,  # si al menos esta fraccion de la longitud de muros va en dos direcciones perpendiculares, lo inclinado es ruido (hoja de puerta, arco)
    "tolerancia_angulo": 4.0,     # grados respecto de la direccion dominante
    "filtrar_inclinados": True,
    "envolvente_de_la_casa": True,          # la envolvente es el casco de los muros de DOBLE linea (los de la casa), no de cualquier linea suelta (cercas, marcos, cotas)
    "completar_sin_lineas_sueltas": True,   # 2a pasada: recintos que solo aparecen al ignorar las lineas SUELTAS (juntas de baldosas, mobiliario) y que la 1a no cubria
    "cierre_por_prolongacion": False,   # experimental: cierra aberturas prolongando el muro; apagado porque cambia recintos ya validados a ojo
}


def _direccion_dominante(segs):
    """Direccion principal de los muros (grados, modulo 90) y fraccion de la longitud que va paralela o perpendicular a ella. PURO.
    Media circular con 4*angulo para que 0 y 90 cuenten igual."""
    sx = sy = tot = 0.0
    for a, b, c, d in segs:
        L = math.hypot(c - a, d - b)
        if L <= 0:
            continue
        ang = math.atan2(d - b, c - a)
        sx += L * math.sin(4 * ang)
        sy += L * math.cos(4 * ang)
        tot += L
    if tot <= 0:
        return 0.0, 0.0
    theta = math.degrees(math.atan2(sx, sy) / 4)
    return theta, None


def _desviacion(dx, dy, theta):
    """Grados entre una direccion y el eje (theta o theta+90) mas cercano."""
    a = math.degrees(math.atan2(dy, dx)) - theta
    return abs(((a + 45) % 90) - 45)


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


def _cierres_por_prolongacion(lineas, libres, p, sh, arbol):
    """Cierra cada abertura PROLONGANDO el muro en linea recta desde su extremo libre hasta el primer muro que encuentre (a menos de `abertura_max_m`).
    Una puerta o un vano interrumpe el muro; su cierre natural es la continuacion del propio muro, nunca una diagonal entre extremos cualesquiera.
    Devuelve [(x1, y1, x2, y2)]."""
    from shapely.ops import nearest_points
    tol, largo = p["tolerancia_extremo_m"], p["abertura_max_m"]
    cierres, vistos = [], set()
    for (x, y, i) in libres:
        cs = list(lineas[i].coords)
        a = cs[0] if (round(cs[0][0], 3), round(cs[0][1], 3)) == (round(x, 3), round(y, 3)) else cs[-1]
        b = cs[1] if a is cs[0] else cs[-2]
        dx, dy = a[0] - b[0], a[1] - b[1]
        L = math.hypot(dx, dy)
        if L <= 1e-9:
            continue
        dx, dy = dx / L, dy / L
        rayo = sh.LineString([(x + dx * 1e-4, y + dy * 1e-4), (x + dx * largo, y + dy * largo)])
        mejor = None
        pt0 = sh.Point(x, y)
        for j in arbol.query(rayo):
            if j == i:
                continue
            inter = rayo.intersection(lineas[j].buffer(tol))
            if inter.is_empty:
                continue
            q = nearest_points(pt0, inter)[1]
            d = pt0.distance(q)
            if d > tol and (mejor is None or d < mejor[0]):
                mejor = (d, q.x, q.y)
        if mejor:
            clave = tuple(sorted(((round(x, 2), round(y, 2)), (round(mejor[1], 2), round(mejor[2], 2)))))
            if clave not in vistos:
                vistos.add(clave)
                cierres.append((x, y, mejor[1], mejor[2]))
    return cierres


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
    # Plano ortogonal: cada abertura se cierra PROLONGANDO el muro en linea recta; el emparejamiento de extremos solo rescata los que quedaron sin cierre
    # (el vecino mas cercano). Plano no ortogonal: emparejamiento de siempre (todos los extremos libres cercanos).
    previos = []
    prolongar = p.get("_eje") is not None and p.get("cierre_por_prolongacion", False)
    if prolongar:
        previos = _cierres_por_prolongacion(lineas, libres, p, sh, arbol)
    pts = [sh.Point(x, y) for x, y, _ in libres]
    arbol_pts = STRtree(pts)
    cierres, usados, cerrados = list(previos), set(), set()
    for (ax, ay, bx, by) in previos:                       # extremos que la prolongacion ya cerro (el origen del cierre)
        for k, (x, y, _) in enumerate(libres):
            if abs(x - ax) < 1e-6 and abs(y - ay) < 1e-6:
                cerrados.add(k)
    for k, (x, y, i) in enumerate(libres):
        if prolongar and k in cerrados:
            continue
        cand = []
        for m in arbol_pts.query(pts[k].buffer(p["abertura_max_m"])):
            if m == k or libres[m][2] == i:
                continue
            d = pts[k].distance(pts[m])
            if d <= p["abertura_max_m"]:
                cand.append((d, m))
        cand.sort()
        for d, m in cand[: (1 if prolongar else 6)]:       # sin prolongacion: TODOS los cercanos (el mas cercano suele ser la otra cara del mismo muro)
            par = (min(k, m), max(k, m))
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


def _completar_sin_lineas_sueltas(recintos, segs, sol, p, u, parametros, sh) -> tuple:
    """Segunda pasada: un piso en cuadricula (juntas de baldosas) o el borde de un mueble se leen como muros y parten un bano en celdas diminutas que se
    descartan. Se vuelve a reconstruir SOLO con los segmentos que tienen cara pareja (muros a doble linea) y se AGREGAN los recintos nuevos que la primera
    pasada no cubria (menos de la mitad de su area). Lo ya reconstruido no se toca."""
    import muros
    pareados, info = muros.segmentos_con_pareja(segs, 1.0)
    if info["descartados"] < 3:
        return recintos, {}
    otra = reconstruir(pareados, 1.0, sol, {**(parametros or {}), "completar_sin_lineas_sueltas": False})
    if not otra.get("ok"):
        return recintos, {}
    previos = [sh.Polygon([(x * u, y * u) for x, y in r["pts"]]).buffer(0) for r in recintos]
    nuevos = []
    for rb in otra["recintos"]:
        pb = sh.Polygon(rb["pts"]).buffer(0)                         # ya en metros (u=1)
        if pb.is_empty or pb.area < p["area_min_m2"]:
            continue
        cubierto = sum(pb.intersection(q).area for q in previos) / pb.area
        if cubierto < 0.5:
            nuevos.append({"pts": [(x / u, y / u) for x, y in rb["pts"]], "area_m2": rb["area_m2"], "area_neta_m2": rb["area_neta_m2"], "huecos": rb["huecos"],
                           "sin_lineas_sueltas": True})
    return recintos + nuevos, {"completados_sin_lineas_sueltas": len(nuevos), "lineas_sueltas_descartadas_m": info["longitud_descartada_m"]}


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
    theta, _ = _direccion_dominante(segs)
    tot_l = sum(math.hypot(c - a, d - b) for a, b, c, d in segs) or 1.0
    ort_l = sum(math.hypot(c - a, d - b) for a, b, c, d in segs if _desviacion(c - a, d - b, theta) <= p["tolerancia_angulo"])
    eje = None
    if segs and ort_l / tot_l >= p["ortogonal_dominante"]:         # plano ortogonal: lo inclinado (hojas de puerta, arcos) no es muro ni cierra aberturas
        eje = theta
        if p["filtrar_inclinados"]:
            antes = len(segs)
            segs = [s for s in segs if _desviacion(s[2] - s[0], s[3] - s[1], theta) <= p["tolerancia_angulo"]]
            diag["inclinados_descartados"] = antes - len(segs)
    diag["orientacion"] = {"eje_grados": round(theta % 90, 1), "ortogonal_pct": round(100 * ort_l / tot_l, 1), "aplicada": eje is not None}
    p = {**p, "_eje": eje}
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
    if p.get("envolvente_de_la_casa") and piezas:
        try:
            import muros as muros_geo
            pareados, info_par = muros_geo.segmentos_con_pareja([(a, b, c, d) for a, b, c, d in segs], 1.0)
            largo_par = sum(math.hypot(c - a, d - b) for a, b, c, d in pareados)
            largo_tot = sum(math.hypot(c - a, d - b) for a, b, c, d in segs) or 1.0
            if largo_par >= 30.0 and largo_par / largo_tot >= 0.2:
                # solo las lineas de doble cara definen la casa: lo que cae fuera de ese casco (jardin, cotas, marcos) no se convierte en recinto
                envolvente = sh.MultiLineString([[(a, b), (c, d)] for a, b, c, d in pareados]).convex_hull.buffer(1.0)
                diag["envolvente"] = {"tipo": "muros_de_doble_linea", "longitud_m": round(largo_par, 1), "caja_m": [round(v, 1) for v in envolvente.bounds]}
        except Exception as e:
            diag["envolvente_error"] = f"{type(e).__name__}: {e}"[:100]
    libre = envolvente.difference(muros)
    comps = list(libre.geoms) if hasattr(libre, "geoms") else [libre]
    borde = envolvente.boundary
    recintos, descartes = [], {"exterior": 0, "pequenos": 0, "grandes": 0, "irregulares": 0}
    pequenos = []
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
            bb = c.bounds
            pequenos.append({"area_m2": round(area_neta, 2), "ancho_m": round(bb[2] - bb[0], 2), "largo_m": round(bb[3] - bb[1], 2),
                             "centro": [round((bb[0] + bb[2]) / 2 / u, 3), round((bb[1] + bb[3]) / 2 / u, 3)]})
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
    if p.get("completar_sin_lineas_sueltas") and segs:
        try:
            recintos, extra = _completar_sin_lineas_sueltas(recintos, segs, sol, p, u, parametros, sh)
            diag.update(extra)
            diag["recintos"] = len(recintos)
        except Exception as e:                      # la segunda pasada nunca estropea el resultado de la primera
            diag["completar_error"] = f"{type(e).__name__}: {e}"[:120]
    if pequenos:                                  # los mayores primero: son los que podrian ser un bano o un closet
        diag["pequenos_mayores"] = sorted(pequenos, key=lambda q: -q["area_m2"])[:15]
    return {"ok": True, "recintos": recintos, "diagnostico": diag}
