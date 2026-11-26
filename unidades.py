"""Unidad efectiva de un dibujo (PURO, solo stdlib): contrasta la unidad declarada (INSUNITS) con el tamano de lo que hay dibujado.

Un dibujo puede declarar milimetros y estar dibujado en metros (o al reves): todo lo que se calcule con la unidad declarada sale 1000 veces mal
(areas, tamanos de mueble, escala de los productos que se insertan). El criterio es la FRACCION de elementos con un tamano fisico plausible bajo
cada unidad (no una mediana: los planos importados de PDF traen miles de trazos finos que la dominan). Es conservador: solo corrige si la
declarada NO es plausible y hay una unica alternativa clara; en cualquier otro caso conserva la declarada y avisa.
"""
import math
import statistics

CANDIDATAS = (0.001, 0.01, 0.0254, 1.0)          # mm, cm, pulgada, m
ELEMENTO_M = (0.02, 60.0)                         # un elemento (bloque, trazo, mueble) mide entre 2 cm y 60 m
TIPICO_M = (0.05, 8.0)                            # y su tamano MEDIANO es el de un simbolo, un mueble o una habitacion
MIN_FRACCION = 0.5
MARGEN = 0.15
MIN_MUESTRAS = 3


def _nombre(u: float) -> str:
    return {0.001: "milimetros", 0.01: "centimetros", 0.0254: "pulgadas", 1.0: "metros"}.get(u, f"{u:g} m por unidad")


def _fraccion(dims: list[float], u: float) -> float:
    lo, hi = ELEMENTO_M
    return sum(1 for d in dims if lo <= d * u <= hi) / len(dims)


def _valida(dims: list[float], med: float, u: float) -> tuple[bool, float]:
    f = _fraccion(dims, u)
    return (f >= MIN_FRACCION and TIPICO_M[0] <= med * u <= TIPICO_M[1]), f


def unidad_efectiva(u_declarada: float, dimensiones: list[float]) -> tuple[float, str | None]:
    """(metros por unidad a usar, aviso|None). `dimensiones`: lado mayor de bloques y poligonos en UNIDADES DEL DIBUJO (ceros y negativos se ignoran)."""
    dims = [float(d) for d in dimensiones if d and d > 0]
    if len(dims) < MIN_MUESTRAS:
        return u_declarada, None
    med = statistics.median(dims)
    ok_decl, _ = _valida(dims, med, u_declarada)
    if ok_decl:
        return u_declarada, None
    elegibles = [u for u in CANDIDATAS if _valida(dims, med, u)[0]]
    # varias unidades pueden ser plausibles (3 m o 9 cm): gana la que deja el tamano MEDIANO mas cercano a ~1 m (el de un mueble o un muro), si es claramente
    # mejor (un factor de e o mas); si no, no se adivina
    cerca = sorted((abs(math.log(med * u)), u) for u in elegibles)
    if len(cerca) == 1 or (len(cerca) > 1 and cerca[1][0] - cerca[0][0] >= 1.0):
        u = cerca[0][1]
        return u, (f"El dibujo declara {_nombre(u_declarada)} pero lo dibujado mide ~{med:g} unidades (serian {med * u_declarada:.3g} m): "
                   f"se asume {_nombre(u)}. Revisa las unidades del dibujo (UNITS/INSUNITS).")
    if cerca:                                       # ambiguo: no se adivina
        opciones = " o ".join(_nombre(u) for _d, u in cerca)
        return u_declarada, (f"Las unidades declaradas ({_nombre(u_declarada)}) no cuadran con el tamano de lo dibujado (~{med:g} unidades); podrian ser "
                             f"{opciones}: no se corrigieron. Confirma las unidades.")
    return u_declarada, (f"Las unidades declaradas ({_nombre(u_declarada)}) no cuadran con el tamano de lo dibujado (~{med:g} unidades) y ninguna "
                         "unidad habitual lo explica: no se corrigieron.")
