"""Operaciones de escritura (Fase 1A): identidad logica de cada pieza, diario de operaciones y reconciliacion tras un fallo. PURO: solo stdlib.

Tres identificadores distintos (acordados):
  operation_id    una ejecucion concreta y sus reintentos
  logical_item_id una posicion funcional dentro de un diseno: diseno | anfitrion | receta | posicion (el PRODUCTO no forma parte: cambiar
                  la luminaria de una posicion es una modificacion de esa pieza, no una pieza nueva)
  plan_hash       el contenido exacto de una version de la propuesta

El dibujo guarda la verdad (XData en cada entidad). El diario local guarda la INTENCION (que se iba a colocar) con escritura atomica y
puntos de control cada N piezas, nunca una escritura por pieza.
"""
import hashlib
import json
import math
import os
import secrets
import time
from pathlib import Path

APP_XDATA = "SCHALLER"
ESQUEMA_XDATA = 1
CHECKPOINT_CADA = 50
ESTADOS = ("pendiente", "aplicada", "parcial", "fallida", "incierta")
TOL_ADOPCION = 0.05        # m: una entidad sin marca solo se adopta si coincide con lo esperado con esta tolerancia (no los 0.30 m de antes)


# ------------------------------------------------------------------------------------------------ identidad
def nuevo_operation_id() -> str:
    return "op_" + time.strftime("%Y%m%d%H%M%S") + "_" + secrets.token_hex(3)


def doc_id(nombre_dibujo: str) -> str:
    """Identidad del documento SIN guardar su nombre (privacidad): huella corta del nombre."""
    return hashlib.sha256(str(nombre_dibujo).casefold().encode("utf-8")).hexdigest()[:12]


def plan_hash(colocaciones: list) -> str:
    """Huella del contenido exacto de una propuesta (orden incluido)."""
    canon = [[c.get("bloque"), round(float(c.get("x", 0)), 3), round(float(c.get("y", 0)), 3), round(float(c.get("rot", 0)), 4), c.get("capa")]
             for c in colocaciones]
    return hashlib.sha256(json.dumps(canon, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def logical_item_id(design_id: str, host_id: str, receta: str, slot_id: str) -> str:
    return f"{design_id}|{host_id}|{receta}|{slot_id}"


def asignar_ids(colocaciones: list, design_id: str, host_id: str, receta: str) -> list:
    """Agrega `item_id` (y `slot`) a cada colocacion. La posicion es el ORDEN de la pieza dentro de la receta (pos_1, pos_2...) y NO incluye el
    producto: cambiar la luminaria de una posicion es una MODIFICACION de esa pieza, no una pieza nueva. Es estable mientras la receta sea
    determinista; los nombres funcionales (mesita_izq) llegan con las recetas rehechas en el marco local.
    `item_id_legado` es la identidad que usaban las piezas colocadas antes de este cambio (producto_n): sirve para reconocerlas, no para escribirlas."""
    por_producto, salida = {}, []
    for n, c in enumerate(colocaciones, 1):
        k = por_producto[c["producto"]] = por_producto.get(c["producto"], 0) + 1
        slot = f"pos_{n}"
        salida.append({**c, "slot": slot, "item_id": logical_item_id(design_id, host_id, receta, slot),
                       "item_id_legado": logical_item_id(design_id, host_id, receta, f"{c['producto']}_{k}")})
    return salida


def sin_duplicados_logico(plan: list, existentes: list, tol: float = 0.30, u: float = 1.0, reemplazar: bool = False) -> tuple[list, list, list]:
    """Separa (nuevas, ya_colocadas, cambiadas).

    1. Misma identidad logica ya presente -> ya colocada. Si esta en otra posicion (> tol) o con otro producto, se reporta en `cambiadas`
       y NO se duplica ni se mueve (modificar una pieza existente se decide con confirmacion, no en silencio).
    2. Sin identidad (piezas antiguas sin marca): vale la proximidad (mismo bloque a <= tol), como hasta ahora.
    Una pieza CON marca de otra identidad NO bloquea por cercania: dos luminarias legitimas a 15 cm ya no se descartan.
    `tol` va en UNIDADES DEL DIBUJO y `u` (metros por unidad) solo sirve para informar la distancia en metros.
    Con reemplazar=True, una pieza propia cambiada (otro producto o desplazada) pasa a `nuevas` y `cambiadas` trae el handle y la identidad de la
    anterior para retirarla: el reemplazo exige que la pieza anterior sea nuestra (marcada) y conocida por su handle.
    """
    por_id = {e["item_id"]: e for e in existentes if e.get("item_id")}
    sin_marca = [e for e in existentes if not e.get("item_id")]
    nuevas, ya, cambiadas = [], [], []
    for c in plan:
        iid = c.get("item_id")
        previo = por_id.get(iid) if iid else None
        if previo is None and c.get("item_id_legado"):
            previo = por_id.get(c["item_id_legado"])                    # pieza colocada con la identidad anterior (producto_n)
        if previo is not None:
            d = math.hypot(previo["x"] - c["x"], previo["y"] - c["y"])
            if d > tol or previo.get("bloque") != c["bloque"]:
                cambiadas.append({"item_id": iid, "slot": c.get("slot"), "bloque_existente": previo.get("bloque"), "bloque_nuevo": c["bloque"],
                                  "distancia_m": round(d * u, 3), "item_id_previo": previo.get("item_id"), "handle": previo.get("handle")})
                if reemplazar and previo.get("handle"):
                    nuevas.append(c)                                   # se coloca la nueva y se retira la anterior (solo si es nuestra y tiene handle)
                    continue
            ya.append(c)
            continue
        if any(e["bloque"] == c["bloque"] and math.hypot(e["x"] - c["x"], e["y"] - c["y"]) <= tol for e in sin_marca):
            ya.append(c)
        else:
            nuevas.append(c)
    return nuevas, ya, cambiadas


# ------------------------------------------------------------------------------------------------ diario
class Diario:
    """Un archivo JSON pequeno por operacion, escrito de forma atomica (temporal + reemplazo)."""

    def __init__(self, carpeta, checkpoint_cada: int = CHECKPOINT_CADA):
        self.carpeta = Path(carpeta)
        self.cada = max(1, int(checkpoint_cada))

    def _ruta(self, op_id: str) -> Path:
        return self.carpeta / f"{op_id}.json"

    def _escribir(self, op_id: str, datos: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self._ruta(op_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._ruta(op_id))

    def cargar(self, op_id: str) -> dict | None:
        try:
            return json.loads(self._ruta(op_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def iniciar(self, op_id: str, doc: str, plan: str, items: list, previos: list | None = None, reemplazos: list | None = None) -> None:
        """Guarda la INTENCION antes de tocar el dibujo. `previos`: handles de lo que ya existia en las capas propias (para no adoptarlo)."""
        self._escribir(op_id, {"op_id": op_id, "doc": doc, "plan_hash": plan, "estado": "pendiente", "creada": time.strftime("%Y-%m-%dT%H:%M:%S"),
                               "aplicados": 0, "previos": list(previos or []), "reemplazos": list(reemplazos or []),
                               "items": [{k: c.get(k) for k in ("item_id", "bloque", "x", "y", "rot")} for c in items]})

    def checkpoint(self, op_id: str, aplicados: int, forzar: bool = False) -> bool:
        """Solo escribe cada `cada` piezas (o al forzar). Devuelve si escribio."""
        if not forzar and aplicados % self.cada:
            return False
        d = self.cargar(op_id)
        if d is None or d.get("estado") != "pendiente":
            return False
        d["aplicados"] = int(aplicados)
        self._escribir(op_id, d)
        return True

    def finalizar(self, op_id: str, estado: str, resultado: dict | None = None) -> None:
        if estado not in ESTADOS:
            raise ValueError(f"estado invalido: {estado}")
        d = self.cargar(op_id) or {"op_id": op_id}
        d["estado"] = estado
        d["cerrada"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if resultado is not None:
            d["resultado"] = resultado
        self._escribir(op_id, d)

    def eliminar(self, op_id: str) -> None:
        """Borra el archivo de una operacion (p. ej. una que fallo ANTES de tocar el dibujo: no hay nada que reconciliar)."""
        try:
            self._ruta(op_id).unlink()
        except OSError:
            pass

    def limpiar(self, max_dias: int = 30) -> int:
        """Borra las operaciones YA CERRADAS (aplicada/parcial/fallida) con mas de `max_dias` dias. Nunca toca las pendientes o inciertas."""
        borradas, limite = 0, time.time() - max_dias * 86400
        try:
            for f in self.carpeta.glob("op_*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    if d.get("estado") in ("aplicada", "parcial", "fallida") and f.stat().st_mtime < limite:
                        f.unlink()
                        borradas += 1
                except (OSError, ValueError):
                    pass
        except OSError:
            pass
        return borradas

    def pendientes(self, doc: str) -> list[dict]:
        """Operaciones de ese documento que quedaron sin cerrar o con resultado incierto: hay que reconciliarlas antes de reintentar."""
        res = []
        try:
            for f in sorted(self.carpeta.glob("op_*.json")):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                if d.get("doc") == doc and d.get("estado") in ("pendiente", "incierta"):
                    res.append(d)
        except OSError:
            pass
        return res


# ------------------------------------------------------------------------------------------------ reconciliacion
def reconciliar(esperados: list, marcados: list, sin_marca: list, previos, tol: float = TOL_ADOPCION) -> dict:
    """Despues de un fallo: que quedo aplicado, que falta y que entidades sin marca se pueden ADOPTAR.

    esperados: [{item_id, bloque, x, y}] (del diario)   marcados: [{item_id, handle}] (XData de esta operacion en el dibujo)
    sin_marca: [{handle, bloque, x, y}] solo de capas gestionadas por el MCP y sin marca de ninguna operacion
    previos:   handles que YA existian antes de empezar la operacion (nunca se adoptan)

    Se adopta una entidad sin marca unicamente si: no estaba antes de la operacion, es el producto esperado, coincide con lo esperado
    dentro de `tol`, y es el UNICO candidato (ni mas candidatos para esa pieza, ni la misma entidad candidata de otra pieza).
    Si hay duda, la pieza queda en `ambiguas` y la operacion se considera parcial: no se convierte una hipotesis en identidad.
    """
    previos = set(previos or [])
    hechos = {m["item_id"] for m in marcados}
    aplicados = [e for e in esperados if e["item_id"] in hechos]
    faltan = [e for e in esperados if e["item_id"] not in hechos]
    candidatos = [s for s in sin_marca if s.get("handle") not in previos]
    por_pieza = {}
    for e in faltan:
        por_pieza[e["item_id"]] = [s for s in candidatos if s["bloque"] == e["bloque"] and math.hypot(s["x"] - e["x"], s["y"] - e["y"]) <= tol]
    usos = {}
    for lista in por_pieza.values():
        for s in lista:
            usos[s["handle"]] = usos.get(s["handle"], 0) + 1
    adoptables, ambiguas, sin_rastro = [], [], []
    for e in faltan:
        c = por_pieza[e["item_id"]]
        if len(c) == 1 and usos[c[0]["handle"]] == 1:
            adoptables.append({"item_id": e["item_id"], "handle": c[0]["handle"]})
        elif c:
            ambiguas.append({"item_id": e["item_id"], "candidatos": [s["handle"] for s in c]})
        else:
            sin_rastro.append(e["item_id"])
    estado = "aplicada" if not faltan else "parcial"
    return {"estado": estado, "aplicados": len(aplicados), "adoptables": adoptables, "ambiguas": ambiguas, "pendientes": sin_rastro,
            "requiere_reconciliacion": bool(ambiguas)}
