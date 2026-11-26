"""Nivel A (sin AutoCAD): cuanto cuesta la instrumentacion apagada y encendida frente a no tenerla.

Compara, con muestras emparejadas y orden alternado:
    A. base      : bucle que lee atributos de un objeto simulado (como las propiedades COM), sin instrumentacion
    B. apagada   : el mismo bucle llamando a metricas.llamada() de la implementacion APAGADA
    C. encendida : el mismo bucle con la implementacion encendida
Criterio provisional (acordado): sobrecoste de B <= 1000 ns por operacion (mediana), sin escrituras ni reloj cuando esta apagada.
Uso:  python benchmarks/bench_instrumentacion.py [--muestras 30] [--n 200000]
"""
import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import informe_benchmark  # noqa: E402
import metricas  # noqa: E402


class Falso:
    """Imita un objeto COM: lee de atributos."""
    Layer = "SCH_T"
    Handle = "8A21"


def medir_base(obj, n):
    t = time.perf_counter_ns()
    for _ in range(n):
        _ = obj.Layer
        _ = obj.Handle
    return time.perf_counter_ns() - t


def medir_con(obj, n, llamada):
    t = time.perf_counter_ns()
    for _ in range(n):
        llamada("Layer")
        _ = obj.Layer
        llamada("Handle")
        _ = obj.Handle
    return time.perf_counter_ns() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestras", type=int, default=30)
    ap.add_argument("--n", type=int, default=200_000)
    a = ap.parse_args()
    off = metricas.crear(False)[0]
    on = metricas.crear(True)[0]
    obj = Falso()
    for f in (lambda: medir_base(obj, 20000), lambda: medir_con(obj, 20000, off), lambda: medir_con(obj, 20000, on)):
        f()                                                         # calentamiento
    base, apagada, encendida = [], [], []
    for i in range(a.muestras):
        orden = [("base", lambda: medir_base(obj, a.n)), ("off", lambda: medir_con(obj, a.n, off)), ("on", lambda: medir_con(obj, a.n, on))]
        if i % 2:
            orden.reverse()                                         # alternar el orden evita sesgos de calentamiento
        for nombre, f in orden:
            (base if nombre == "base" else apagada if nombre == "off" else encendida).append(f())
    ops = a.n * 2                                                   # dos "llamadas" instrumentadas por vuelta
    por_op = lambda v, b: [(x - y) / ops for x, y in zip(v, b)]
    s_off, s_on = por_op(apagada, base), por_op(encendida, base)
    out = {"benchmark_schema_version": informe_benchmark.ESQUEMA, "scenario": "instrumentation_overhead_microbenchmark", "n_ops_per_sample": ops,
           "samples": a.muestras, "base_ns_per_op_median": round(statistics.median(x / ops for x in base), 1),
           "off_overhead_ns_per_op": {"median": round(statistics.median(s_off), 1), "p95": round(sorted(s_off)[round(0.95 * len(s_off)) - 1], 1)},
           "on_overhead_ns_per_op": {"median": round(statistics.median(s_on), 1), "p95": round(sorted(s_on)[round(0.95 * len(s_on)) - 1], 1)},
           "environment": informe_benchmark.entorno(),
           "criterion_off_median_le_1000ns": statistics.median(s_off) <= 1000,
           "nota": "microbenchmark con un objeto simulado; no mide AutoCAD. El nivel B (extremo a extremo) pertenece a la pista 0B."}
    print(json.dumps(out, indent=1))
    return 0 if out["criterion_off_median_le_1000ns"] else 1


if __name__ == "__main__":
    sys.exit(main())
