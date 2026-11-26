"""Medidas geometricas de un recinto o de un elemento (PURO, solo stdlib): no dependen de Shapely ni de AutoCAD, asi que dan los MISMOS numeros en
cualquier instalacion. Todo en las unidades que se pasen (el llamador convierte con la unidad efectiva del dibujo).

Un recinto no es solo su caja del plano: un cuarto girado 30 grados tiene una caja mayor que su ancho y largo reales. Aqui se mide el rectangulo
orientado de area minima (ancho x largo y su angulo), el perimetro, el area y el centro.
"""
import math


def area(pts: list) -> float:
    """Area con signo -> valor absoluto (formula del poligono, vertices en orden)."""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def perimetro(pts: list) -> float:
    n = len(pts)
    return sum(math.hypot(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1]) for i in range(n)) if n >= 2 else 0.0


def centroide(pts: list) -> tuple[float, float]:
    """Centroide del poligono (si su area es casi 0, el promedio de sus vertices)."""
    n = len(pts)
    a2 = cx = cy = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        c = x1 * y2 - x2 * y1
        a2 += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if abs(a2) < 1e-12:
        return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    return cx / (3 * a2), cy / (3 * a2)


def casco_convexo(pts: list) -> list:
    """Cadena monotona de Andrew: vertices del casco convexo en sentido antihorario."""
    p = sorted(set((float(x), float(y)) for x, y in pts))
    if len(p) <= 2:
        return p

    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    inf, sup = [], []
    for q in p:
        while len(inf) >= 2 and cruz(inf[-2], inf[-1], q) <= 0:
            inf.pop()
        inf.append(q)
    for q in reversed(p):
        while len(sup) >= 2 and cruz(sup[-2], sup[-1], q) <= 0:
            sup.pop()
        sup.append(q)
    return inf[:-1] + sup[:-1]


def rectangulo_minimo(pts: list) -> dict:
    """Rectangulo orientado de area minima que contiene al poligono: {ancho, largo, angulo_grados, centro}. `largo` >= `ancho`; el angulo es el del lado
    LARGO respecto al eje X (0 a 180). Exacto: uno de sus lados es siempre colineal con un lado del casco convexo."""
    casco = casco_convexo(pts)
    if len(casco) < 2:
        return {"ancho": 0.0, "largo": 0.0, "angulo_grados": 0.0, "centro": (casco[0] if casco else (0.0, 0.0))}
    mejor = None
    n = len(casco)
    for i in range(n):
        x1, y1 = casco[i]
        x2, y2 = casco[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-12:
            continue
        ux, uy = dx / L, dy / L                      # eje a lo largo del lado
        vx, vy = -uy, ux
        us = [(x - x1) * ux + (y - y1) * uy for x, y in casco]
        vs = [(x - x1) * vx + (y - y1) * vy for x, y in casco]
        w, h = max(us) - min(us), max(vs) - min(vs)
        if mejor is None or w * h < mejor[0] - 1e-12:
            cu, cv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
            mejor = (w * h, w, h, (ux, uy), (x1 + cu * ux + cv * vx, y1 + cu * uy + cv * vy))
    if mejor is None:
        return {"ancho": 0.0, "largo": 0.0, "angulo_grados": 0.0, "centro": casco[0]}
    _, w, h, (ux, uy), centro = mejor
    if w >= h:
        largo, ancho, ang = w, h, math.degrees(math.atan2(uy, ux))
    else:
        largo, ancho, ang = h, w, math.degrees(math.atan2(ux, -uy))          # el lado largo es el perpendicular
    return {"ancho": ancho, "largo": largo, "angulo_grados": ang % 180.0, "centro": centro}


def medidas_recinto(pts: list, u: float = 1.0) -> dict:
    """Medidas de un recinto en METROS (u = metros por unidad del dibujo): area, perimetro, ancho x largo orientados, angulo, relacion de aspecto,
    compacidad (4*pi*A/P^2: 1 = circulo, ~0.78 = cuadrado, bajo = alargado o con entrantes) y centro (en unidades del dibujo)."""
    a, p = area(pts) * u * u, perimetro(pts) * u
    r = rectangulo_minimo(pts)
    ancho, largo = r["ancho"] * u, r["largo"] * u
    cx, cy = centroide(pts)
    return {"area_m2": round(a, 3), "perimetro_m": round(p, 3), "ancho_m": round(ancho, 3), "largo_m": round(largo, 3),
            "angulo_grados": round(r["angulo_grados"], 2), "relacion_aspecto": round(largo / ancho, 2) if ancho > 1e-9 else None,
            "compacidad": round(4 * math.pi * a / (p * p), 3) if p > 1e-9 else None,
            "rectangularidad": round(a / (ancho * largo), 3) if ancho * largo > 1e-9 else None,
            "centro": [round(cx, 3), round(cy, 3)]}
