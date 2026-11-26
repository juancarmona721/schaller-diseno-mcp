"""Que lineas son MUROS (PURO, solo stdlib): primero por el nombre de la capa (vocabulario editable); si el plano no los nombra, por su GEOMETRIA.

Los planos reales traen la arquitectura con nombres de capa de todo tipo (o dentro de un bloque, importada de un PDF). El nombre es la mejor evidencia, pero no
puede ser la unica: cuando ninguna capa se llama como un muro se eligen las capas cuya geometria se comporta como muros (trazos largos, mayoritariamente
ortogonales, en cantidad suficiente), excluyendo las que el vocabulario marca como mobiliario, vegetacion, cotas o cajetin. Esa eleccion es una HIPOTESIS de
confianza baja y se informa (modo y capas usadas), nunca se presenta como un hecho.
"""
import math

ANGULO_ORTOGONAL = 3.0           # grados: un trazo a menos de esto de 0/90 cuenta como ortogonal
MIN_TRAZOS, MIN_LONGITUD_M, MIN_MEDIANA_M, MIN_ORTOGONAL = 15, 10.0, 0.2, 0.6


def _angulo_ortogonal(dx: float, dy: float) -> bool:
    a = abs(math.degrees(math.atan2(dy, dx))) % 90.0
    return a <= ANGULO_ORTOGONAL or a >= 90.0 - ANGULO_ORTOGONAL


def estadisticas_por_capa(lineas: list, u: float = 1.0) -> dict:
    """lineas: [[x1,y1,x2,y2,capa]] en unidades del dibujo -> {capa: {n, longitud_m, mediana_m, ortogonal}} (ortogonal = fraccion de la longitud)."""
    acum = {}
    for s in lineas:
        x1, y1, x2, y2, capa = s[0], s[1], s[2], s[3], s[4] if len(s) > 4 else "?"
        L = math.hypot(x2 - x1, y2 - y1) * u
        if L <= 0:
            continue
        d = acum.setdefault(capa, {"longs": [], "orto": 0.0})
        d["longs"].append(L)
        if _angulo_ortogonal(x2 - x1, y2 - y1):
            d["orto"] += L
    out = {}
    for capa, d in acum.items():
        longs = sorted(d["longs"])
        total = sum(longs)
        out[capa] = {"n": len(longs), "longitud_m": round(total, 2), "mediana_m": round(longs[len(longs) // 2], 3),
                     "ortogonal": round(d["orto"] / total, 2) if total > 0 else 0.0}
    return out


def capas_por_geometria(estadisticas: dict, excluir) -> list:
    """Capas cuya geometria parece de muros. `excluir`: regex con las capas que NO pueden ser muros (mobiliario, cotas, cajetin, vegetacion...)."""
    return sorted(c for c, e in estadisticas.items()
                  if e["n"] >= MIN_TRAZOS and e["longitud_m"] >= MIN_LONGITUD_M and e["mediana_m"] >= MIN_MEDIANA_M and e["ortogonal"] >= MIN_ORTOGONAL
                  and not excluir.search(c))


def elegir(segs_por_nombre: list, lineas: list, rx_muros, rx_excluir, u: float = 1.0) -> dict:
    """Decide los segmentos de muro a usar. Devuelve {"segmentos": [[x1,y1,x2,y2]], "modo": "nombre_de_capa"|"geometria"|"ninguno", "capas": [...], "estadisticas": {...top...}}.

    segs_por_nombre: segmentos leidos del espacio modelo en capas con nombre de muro. lineas: todas las lineas de bloques contenedor, con su capa.
    """
    estad = estadisticas_por_capa(lineas, u)
    del_contenedor = [s[:4] for s in lineas if len(s) > 4 and rx_muros.search(s[4])]
    capas_nombre = sorted({s[4] for s in lineas if len(s) > 4 and rx_muros.search(s[4])})
    if segs_por_nombre or del_contenedor:
        return {"segmentos": [list(s[:4]) for s in segs_por_nombre] + del_contenedor, "modo": "nombre_de_capa", "capas": capas_nombre,
                "estadisticas": _top(estad)}
    capas = capas_por_geometria(estad, rx_excluir)
    if capas:
        usados = set(capas)
        return {"segmentos": [s[:4] for s in lineas if len(s) > 4 and s[4] in usados], "modo": "geometria", "capas": capas, "estadisticas": _top(estad)}
    return {"segmentos": [], "modo": "ninguno", "capas": [], "estadisticas": _top(estad)}


def _top(estad: dict, n: int = 12) -> dict:
    return dict(sorted(estad.items(), key=lambda kv: -kv[1]["longitud_m"])[:n])
