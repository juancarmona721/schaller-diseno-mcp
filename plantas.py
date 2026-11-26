"""Vistas (plantas candidatas) de un dibujo: separa varias vistas dibujadas lado a lado en el mismo archivo. PURO: solo stdlib, sin COM.

Una VISTA es un grupo de geometria arquitectonica (poligonos y bloques) cuyas cajas se tocan o estan a menos de `HUECO_M` entre si. NO es un piso:
dos vistas pueden ser dos pisos, una planta y una seccion, un plano de techos o dos alternativas de diseno. El nivel solo se nombra si hay un texto
cercano que lo diga (PLANTA, PISO, NIVEL, LEVEL, FLOOR...); si no, queda sin nombre y sin nivel: nunca se inventa.
Las cotas, leyendas y rotulos (textos) NO participan en el agrupamiento (podrian unir dos vistas); se asignan despues.
"""
import re

HUECO_M = 5.0                    # separacion entre cajas por encima de la cual son vistas distintas
MIN_ELEMENTOS, MIN_AREA_M2 = 3, 15.0   # un grupo menor es ruido (cotas sueltas, detalles) y se une a la vista mas cercana
DISTANCIA_NOMBRE_M = 8.0
PATRON_NIVEL = re.compile(r"\b(planta|piso|nivel|level|floor|sotano|s[oó]tano|basement|cubierta|azotea|roof|terraza|mezzanine|entrepiso)\b[\s\w.\-]{0,20}", re.I)


class _Union:
    def __init__(self, n):
        self.p = list(range(n))

    def hallar(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def unir(self, a, b):
        ra, rb = self.hallar(a), self.hallar(b)
        if ra != rb:
            self.p[rb] = ra


def _union_cajas(cajas: list, hueco: float) -> list:
    """Indice de grupo por caja. Cajas expandidas medio hueco que se solapan se unen; se usa una rejilla para no comparar todas contra todas."""
    uf = _Union(len(cajas))
    mitad, celda = hueco / 2, max(hueco, 1e-6)
    cubo: dict = {}
    for i, (x0, y0, x1, y1) in enumerate(cajas):
        for cx in range(int((x0 - mitad) // celda), int((x1 + mitad) // celda) + 1):
            for cy in range(int((y0 - mitad) // celda), int((y1 + mitad) // celda) + 1):
                cubo.setdefault((cx, cy), []).append(i)
    for miembros in cubo.values():
        # dentro de una celda solo se unen las cajas cuya expansion realmente se solapa
        base = miembros[0]
        for j in miembros[1:]:
            a, b = cajas[base], cajas[j]
            if a[0] - mitad <= b[2] + mitad and b[0] - mitad <= a[2] + mitad and a[1] - mitad <= b[3] + mitad and b[1] - mitad <= a[3] + mitad:
                uf.unir(base, j)
        for k in range(1, len(miembros)):
            for j in miembros[k + 1:]:
                a, b = cajas[miembros[k]], cajas[j]
                if a[0] - mitad <= b[2] + mitad and b[0] - mitad <= a[2] + mitad and a[1] - mitad <= b[3] + mitad and b[1] - mitad <= a[3] + mitad:
                    uf.unir(miembros[k], j)
    return [uf.hallar(i) for i in range(len(cajas))]


def _dist_cajas(a, b) -> float:
    dx = max(0.0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0.0, max(a[1] - b[3], b[1] - a[3]))
    return (dx * dx + dy * dy) ** 0.5


def detectar(cajas: list, textos: list, unidad_m: float = 1.0, hueco_m: float = HUECO_M) -> list[dict]:
    """cajas: [(x0,y0,x1,y1)] de la geometria arquitectonica (en unidades del dibujo). textos: [{t,x,y}].

    Devuelve la lista de vistas ordenadas de izquierda a derecha: {id, bbox, n_elementos, area_m2, nombre|None, texto_nivel|None, tipo_vista: "desconocido",
    nivel: None, confianza}. Con una sola vista devuelve una lista de un elemento (el dibujo no tiene varias vistas).
    """
    cajas = [tuple(float(v) for v in c) for c in cajas if c and c[2] >= c[0] and c[3] >= c[1]]
    if not cajas:
        return []
    hueco = hueco_m / unidad_m
    grupos = _union_cajas(cajas, hueco)
    por_grupo: dict = {}
    for caja, g in zip(cajas, grupos):
        por_grupo.setdefault(g, []).append(caja)

    def resumen(lista):
        return (min(c[0] for c in lista), min(c[1] for c in lista), max(c[2] for c in lista), max(c[3] for c in lista))

    info = {g: resumen(l) for g, l in por_grupo.items()}
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1]) * unidad_m * unidad_m
    grandes = [g for g, l in por_grupo.items() if len(l) >= MIN_ELEMENTOS and area(info[g]) >= MIN_AREA_M2]
    if not grandes:                                      # nada con entidad suficiente: un unico grupo con todo
        grandes = [max(por_grupo, key=lambda g: len(por_grupo[g]))]
    for g in list(por_grupo):
        if g in grandes:
            continue
        cercano = min(grandes, key=lambda h: _dist_cajas(info[g], info[h]))        # el ruido se une a la vista mas cercana
        por_grupo[cercano] += por_grupo[g]
        del por_grupo[g]
    vistas = []
    for g in sorted(grandes, key=lambda g: resumen(por_grupo[g])[0]):
        b = resumen(por_grupo[g])
        vistas.append({"bbox": [round(v, 3) for v in b], "n_elementos": len(por_grupo[g]), "area_m2": round(area(b), 1), "nombre": None,
                       "texto_nivel": None, "tipo_vista": "desconocido", "nivel": None, "confianza": "baja"})
    for t in textos or []:
        m = PATRON_NIVEL.search(str(t.get("t", "")))
        if not m:
            continue
        p = (t["x"], t["y"], t["x"], t["y"])
        v = min(vistas, key=lambda v: _dist_cajas(p, v["bbox"]))
        if _dist_cajas(p, v["bbox"]) * unidad_m <= DISTANCIA_NOMBRE_M and v["texto_nivel"] is None:
            v["texto_nivel"] = " ".join(str(t["t"]).split())[:40]
            v["nombre"] = v["texto_nivel"]
            v["confianza"] = "media"
    for i, v in enumerate(vistas, 1):
        v["id"] = f"vista_{i}"
    return vistas


def vista_de(vistas: list, x: float, y: float) -> str | None:
    """Id de la vista que contiene el punto, o la mas cercana si cae fuera de todas."""
    if not vistas:
        return None
    dentro = [v for v in vistas if v["bbox"][0] <= x <= v["bbox"][2] and v["bbox"][1] <= y <= v["bbox"][3]]
    if dentro:
        return min(dentro, key=lambda v: (v["bbox"][2] - v["bbox"][0]) * (v["bbox"][3] - v["bbox"][1]))["id"]
    return min(vistas, key=lambda v: _dist_cajas((x, y, x, y), v["bbox"]))["id"]
