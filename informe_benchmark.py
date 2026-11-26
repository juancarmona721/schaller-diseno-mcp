"""Formato comun de los informes de benchmark (pista 0A): comparables entre versiones y equipos. Solo stdlib.

Reglas: las metricas no medidas son null (nunca 0); se conservan las muestras individuales; el informe NO lleva nombres de clientes,
contenido de planos, nombres de personas ni rutas privadas. `entorno()` solo recoge versiones.
"""
import platform
import re
import statistics

ESQUEMA = 1
METRICAS = ("total_ms", "connection_ms", "extraction_ms", "planning_ms", "insertion_ms", "xdata_ms", "verification_ms", "com_call_count")
MODOS = ("cold", "warm")


def entorno(autocad_version=None, autocad_idioma=None, cliente_version=None) -> dict:
    return {"windows_version": platform.version(), "python_version": platform.python_version(), "python_architecture": platform.architecture()[0],
            "autocad_version": autocad_version, "autocad_language": autocad_idioma, "client_version": cliente_version}


def resumir(muestras_ms: list[float]) -> dict:
    """Mediana y maximo siempre; p95 solo con 20 o mas muestras (con menos no es una estimacion fiable)."""
    m = sorted(float(x) for x in muestras_ms)
    if not m:
        return {"n": 0, "mediana": None, "max": None, "p95": None, "muestras": []}
    p95 = m[min(len(m) - 1, max(0, round(0.95 * len(m)) - 1))] if len(m) >= 20 else None
    return {"n": len(m), "mediana": round(statistics.median(m), 3), "max": round(m[-1], 3), "p95": None if p95 is None else round(p95, 3), "muestras": [round(x, 3) for x in m]}


def nuevo_informe(escenario_id: str, mcp_version: str, entidades: int | None = None, definiciones: int | None = None, instrumentacion: bool = False,
                  modo: str = "warm", fixture_version: int = 1, env: dict | None = None) -> dict:
    return {"benchmark_schema_version": ESQUEMA, "mcp_version": mcp_version, "environment": env or entorno(),
            "scenario": {"id": escenario_id, "fixture_version": fixture_version, "entity_count": entidades, "unique_definitions": definiciones,
                         "instrumentation_enabled": bool(instrumentacion), "execution_mode": modo},
            "metrics": {k: None for k in METRICAS}, "samples": {},
            "result": {"status": "pending", "expected_entities": entidades, "actual_entities": None, "warnings": []}}


def validar(inf: dict) -> list[str]:
    """Lista de problemas; vacia = valido. Detecta metricas en cero (deben ser null si no se midieron) y datos privados evidentes."""
    p = []
    if inf.get("benchmark_schema_version") != ESQUEMA:
        p.append("benchmark_schema_version incorrecto")
    for k in ("mcp_version", "environment", "scenario", "metrics", "result"):
        if k not in inf:
            p.append(f"falta {k}")
    sc, me = inf.get("scenario", {}), inf.get("metrics", {})
    if sc.get("execution_mode") not in MODOS:
        p.append("execution_mode debe ser cold o warm")
    for k in METRICAS:
        if k not in me:
            p.append(f"falta la metrica {k}")
        elif me[k] == 0:
            p.append(f"{k} es 0: una metrica no medida debe ser null")
    if inf.get("result", {}).get("status") not in ("ok", "partial", "failed", "pending"):
        p.append("result.status invalido")
    texto = str(inf).lower()
    if re.search(r"[a-z]:\\+users", texto) or "/users/" in texto:
        p.append("el informe contiene una ruta de usuario")
    return p


def comparar(referencia_ms: float, nuevo_ms: float, estricto: bool = False) -> dict:
    """Umbral de investigacion: mayor entre 5% y 100 ms (general), o entre 1% y 10 ms (instrumentacion apagada de extremo a extremo)."""
    pct, minimo = (0.01, 10.0) if estricto else (0.05, 100.0)
    umbral = max(pct * referencia_ms, minimo)
    delta = nuevo_ms - referencia_ms
    return {"delta_ms": round(delta, 3), "umbral_ms": round(umbral, 3), "investigar": delta > umbral}
