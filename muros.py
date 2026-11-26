"""Que lineas son MUROS (PURO, solo stdlib): primero por el nombre de la capa (vocabulario editable); si el plano no los nombra, por su GEOMETRIA.

Los planos reales traen la arquitectura con nombres de capa de todo tipo (o dentro de un bloque, importada de un PDF). El nombre es la mejor evidencia, pero no
puede ser la unica: cuando ninguna capa se llama como un muro se eligen las capas cuya geometria se comporta como muros (trazos largos, mayoritariamente
ortogonales, en cantidad suficiente; el ruido de trazos diminutos no cuenta), excluyendo las que el vocabulario marca como mobiliario, vegetacion, cotas o cajetin. Esa eleccion es una HIPOTESIS de
confianza baja y se informa (modo y capas usadas), nunca se presenta como un hecho.
"""
import math

ANGULO_ORTOGONAL = 3.0           # grados: un trazo a menos de esto de 0/90 cuenta como ortogonal
LARGO_MIN_M = 0.5                # un trazo "largo" (candidato a cara de muro); el ruido de un PDF (texto, hachura) son miles de trazos de 1-5 cm
SEGMENTO_MIN_M = 0.3             # al elegir por geometria solo se usan trazos de al menos esto
MIN_LARGOS, MIN_LONGITUD_LARGA_M, MIN_ORTOGONAL = 8, 10.0, 0.6


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
        d = acum.setdefault(capa, {"longs": [], "orto": 0.0, "orto_largos": 0.0})
        d["longs"].append(L)
        if _angulo_ortogonal(x2 - x1, y2 - y1):
            d["orto"] += L
            if L >= LARGO_MIN_M:
                d["orto_largos"] += L
    out = {}
    for capa, d in acum.items():
        longs = sorted(d["longs"])
        total = sum(longs)
        largos = [x for x in longs if x >= LARGO_MIN_M]
        out[capa] = {"n": len(longs), "longitud_m": round(total, 2), "mediana_m": round(longs[len(longs) // 2], 3),
                     "ortogonal": round(d["orto"] / total, 2) if total > 0 else 0.0,
                     "trazos_largos": len(largos), "longitud_larga_m": round(sum(largos), 2),
                     "ortogonal_largos": round(d["orto_largos"] / sum(largos), 2) if largos else 0.0}
    return out


def capas_por_geometria(estadisticas: dict, excluir) -> list:
    """Capas cuya geometria parece de muros. `excluir`: regex con las capas que NO pueden ser muros (mobiliario, cotas, cajetin, vegetacion...)."""
    return sorted(c for c, e in estadisticas.items()
                  if e["trazos_largos"] >= MIN_LARGOS and e["longitud_larga_m"] >= MIN_LONGITUD_LARGA_M and e["ortogonal_largos"] >= MIN_ORTOGONAL
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
        return {"segmentos": [s[:4] for s in lineas if len(s) > 4 and s[4] in usados and math.hypot(s[2] - s[0], s[3] - s[1]) * u >= SEGMENTO_MIN_M],
                "modo": "geometria", "capas": capas, "estadisticas": _top(estad)}
    return {"segmentos": [], "modo": "ninguno", "capas": [], "estadisticas": _top(estad)}


def _top(estad: dict, n: int = 12) -> dict:
    return dict(sorted(estad.items(), key=lambda kv: -kv[1]["longitud_m"])[:n])


ESPESOR_MIN_M, ESPESOR_MAX_M, SOLAPE_MIN_M = 0.04, 0.45, 0.3


def ejes_de_muro(segmentos: list, u: float = 1.0) -> dict:
    """Une las DOS CARAS de cada muro (pares de segmentos paralelos, ortogonales, a 4-45 cm que se solapan) en un eje: longitud real del muro y espesor.

    Un plano dibujado a doble linea cuenta cada muro dos veces; aqui se mide una. Los segmentos sin cara pareja (cerramientos, puertas, ruido) se
    informan aparte. PURO. -> {"longitud_eje_m", "espesor_mediano_m", "espesor_p10_m", "espesor_p90_m", "pares", "longitud_sin_pareja_m", "longitud_caras_m"}
    """
    horiz, vert, otros_m = [], [], 0.0
    for s in segmentos:
        x1, y1, x2, y2 = s[0] * u, s[1] * u, s[2] * u, s[3] * u
        L = math.hypot(x2 - x1, y2 - y1)
        if L <= 0:
            continue
        if _angulo_ortogonal(x2 - x1, y2 - y1):
            if abs(y2 - y1) <= abs(x2 - x1):
                horiz.append((round((y1 + y2) / 2, 4), min(x1, x2), max(x1, x2)))
            else:
                vert.append((round((x1 + x2) / 2, 4), min(y1, y2), max(y1, y2)))
        else:
            otros_m += L
    total = sum(h[2] - h[1] for h in horiz) + sum(v[2] - v[1] for v in vert) + otros_m
    if total <= 0:
        return {}
    espesores, longitud_eje, emparejado = [], 0.0, 0.0
    for grupo in (horiz, vert):
        grupo.sort()
        usados = [0.0] * len(grupo)                                   # longitud ya emparejada de cada cara
        for i, (c1, a1, b1) in enumerate(grupo):
            for j in range(i + 1, len(grupo)):
                c2, a2, b2 = grupo[j]
                d = c2 - c1
                if d > ESPESOR_MAX_M:
                    break
                if d < ESPESOR_MIN_M:
                    continue
                solape = min(b1, b2) - max(a1, a2)
                if solape < SOLAPE_MIN_M:
                    continue
                libre_i, libre_j = (b1 - a1) - usados[i], (b2 - a2) - usados[j]
                tramo = min(solape, libre_i, libre_j)
                if tramo <= 0:
                    continue
                usados[i] += tramo
                usados[j] += tramo
                longitud_eje += tramo
                espesores.append((d, tramo))
                emparejado += 2 * tramo
    if not espesores:
        return {"pares": 0, "longitud_caras_m": round(total, 1), "longitud_sin_pareja_m": round(total, 1)}
    esp = sorted(espesores)
    acum, p = 0.0, {}
    for d, tramo in esp:                                              # percentiles ponderados por longitud
        acum += tramo
        for nombre, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
            if nombre not in p and acum >= q * longitud_eje:
                p[nombre] = d
    return {"pares": len(espesores), "longitud_eje_m": round(longitud_eje, 1), "espesor_mediano_m": round(p.get("p50", 0), 3),
            "espesor_p10_m": round(p.get("p10", 0), 3), "espesor_p90_m": round(p.get("p90", 0), 3),
            "longitud_caras_m": round(total, 1), "longitud_sin_pareja_m": round(max(0.0, total - emparejado), 1)}
