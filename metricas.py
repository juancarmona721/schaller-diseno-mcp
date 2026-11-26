"""Instrumentacion opcional del MCP (pista 0A). APAGADA por defecto: cuesta lo de llamar a una funcion vacia.

Se activa con la variable de entorno SCHALLER_TRACE=1 (o creando el modulo con `crear(True)` en pruebas/benchmarks).
La implementacion se elige UNA vez al crear el modulo: apagada no consulta el reloj, no reserva memoria ni escribe nada en disco.
Encendida acumula en memoria (conteo de llamadas COM por tipo y tiempos por etapa) y se vuelca agrupada al terminar la operacion.

Uso explicito en los puntos criticos (sin proxies sobre objetos COM, que alterarian el comportamiento de pywin32):
    from metricas import llamada, etapa
    llamada("InsertBlock")
    with etapa("insercion"):
        ...
"""
import json
import os
import time
from pathlib import Path


class _Nulo:
    """Administrador de contexto compartido y vacio: `with etapa(...)` no asigna nada cuando esta apagada."""
    __slots__ = ()

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


_NULO = _Nulo()


def _sin_llamada(tipo, n=1):
    return None


def _sin_etapa(nombre):
    return _NULO


def _sin_resumen():
    return None


def _sin_absorber(datos):
    return None


def _sin_volcar(ruta=None, contexto=None):
    return None


def _sin_reiniciar():
    return None


class _Etapa:
    __slots__ = ("_t", "_nombre", "_acum")

    def __init__(self, nombre, acum):
        self._nombre, self._acum, self._t = nombre, acum, 0

    def __enter__(self):
        self._t = time.perf_counter_ns()
        return None

    def __exit__(self, *exc):
        self._acum.setdefault(self._nombre, []).append((time.perf_counter_ns() - self._t) / 1e6)
        return False


def crear(activa: bool):
    """Devuelve (llamada, etapa, resumen, absorber, volcar, reiniciar). Apagada: todo son funciones vacias."""
    if not activa:
        return _sin_llamada, _sin_etapa, _sin_resumen, _sin_absorber, _sin_volcar, _sin_reiniciar
    llamadas: dict = {}
    etapas: dict = {}

    def llamada(tipo, n=1):
        llamadas[tipo] = llamadas.get(tipo, 0) + n

    def etapa(nombre):
        return _Etapa(nombre, etapas)

    def resumen():
        return {"llamadas_com": dict(llamadas), "total_llamadas_com": sum(llamadas.values()),
                "etapas_ms": {k: {"n": len(v), "total": round(sum(v), 3), "max": round(max(v), 3)} for k, v in etapas.items()}}

    def absorber(datos):
        """Suma lo que midio un subproceso (sondas) a lo acumulado por el servidor."""
        if not isinstance(datos, dict):
            return
        for k, v in (datos.get("llamadas_com") or {}).items():
            llamadas[k] = llamadas.get(k, 0) + int(v)
        for k, v in (datos.get("etapas_ms") or {}).items():
            etapas.setdefault("sonda." + k, []).append(float(v.get("total", 0)))

    def reiniciar():
        llamadas.clear()
        etapas.clear()

    def volcar(ruta=None, contexto=None):
        """UNA linea agrupada por operacion (nunca una por llamada COM). Despues reinicia los contadores."""
        r = resumen()
        if not r["total_llamadas_com"] and not r["etapas_ms"]:
            return None
        r.update({"t": time.strftime("%Y-%m-%d %H:%M:%S"), **(contexto or {})})
        try:
            destino = Path(ruta or os.environ.get("SCHALLER_METRICAS") or Path.home() / ".schaller-diseno" / "logs" / "metricas.jsonl")
            destino.parent.mkdir(parents=True, exist_ok=True)
            with open(destino, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        except OSError:
            pass
        reiniciar()
        return r

    return llamada, etapa, resumen, absorber, volcar, reiniciar


ACTIVA = os.environ.get("SCHALLER_TRACE", "").strip().lower() in ("1", "true", "si", "yes")
llamada, etapa, resumen, absorber, volcar, reiniciar = crear(ACTIVA)
