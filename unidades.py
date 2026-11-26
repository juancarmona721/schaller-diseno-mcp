"""Unidad efectiva de un dibujo (PURO, solo stdlib): contrasta la unidad declarada (INSUNITS) con el tamano de lo que hay dibujado.

Un dibujo puede declarar milimetros y estar dibujado en metros (o al reves): todo lo que se calcule con la unidad declarada sale 1000 veces mal
(areas, tamanos de mueble, escala de los productos que se insertan). La comprobacion es conservadora: solo corrige si la declarada NO es plausible
y exactamente una unidad candidata si lo es; en cualquier otro caso conserva la declarada y avisa.
"""
import statistics

CANDIDATAS = (0.001, 0.01, 0.0254, 1.0)          # mm, cm, pulgada, m
PLAUSIBLE_M = (0.08, 6.0)                         # tamano mediano razonable de bloques/mobiliario/simbolos en metros
MIN_MUESTRAS = 3


def _nombre(u: float) -> str:
    return {0.001: "milimetros", 0.01: "centimetros", 0.0254: "pulgadas", 1.0: "metros"}.get(u, f"{u:g} m por unidad")


def unidad_efectiva(u_declarada: float, dimensiones: list[float]) -> tuple[float, str | None]:
    """(metros por unidad a usar, aviso|None). `dimensiones`: lado mayor de bloques y poligonos en UNIDADES DEL DIBUJO (ceros y negativos se ignoran)."""
    dims = [float(d) for d in dimensiones if d and d > 0]
    if len(dims) < MIN_MUESTRAS:
        return u_declarada, None
    med = statistics.median(dims)
    lo, hi = PLAUSIBLE_M
    if lo <= med * u_declarada <= hi:
        return u_declarada, None
    validas = [u for u in CANDIDATAS if lo <= med * u <= hi]
    if len(validas) == 1:
        u = validas[0]
        return u, (f"El dibujo declara {_nombre(u_declarada)} pero lo dibujado mide ~{med:g} unidades (serian {med * u_declarada:.3g} m): "
                   f"se asume {_nombre(u)}. Revisa las unidades del dibujo (UNITS/INSUNITS).")
    if validas:                                   # ambiguo (p. ej. mediana entre dos candidatas): no se adivina
        return u_declarada, (f"Las unidades declaradas ({_nombre(u_declarada)}) no cuadran con el tamano de lo dibujado (~{med:g} unidades) y hay mas de una "
                             "posibilidad: no se corrigieron. Confirma las unidades.")
    return u_declarada, (f"Las unidades declaradas ({_nombre(u_declarada)}) no cuadran con el tamano de lo dibujado (~{med:g} unidades) y ninguna "
                         "unidad habitual lo explica: no se corrigieron.")
