"""Clasificador unico de mobiliario anonimo (descubrimiento minimo). PURO: solo stdlib, sin COM.

Clasifica la DEFINICION de un bloque por evidencias independientes del nombre del propio bloque (que ya resuelve el vocabulario/perfil):
nombres de bloques ANIDADOS, capas internas, tamano real y forma. Devuelve rol, confianza, puntaje y las evidencias (positivas y negativas).
Reglas: la ausencia de un dato no resta; solo el tamano incompatible resta. El perfil confirmado por una persona manda siempre sobre esto
(se aplica antes, en rol_de_bloque). Un rol inferido nunca se presenta como confirmado: lleva `rol_origen: inferido` y su confianza.
No usa el contexto del recinto: eso es una segunda pasada (para no razonar en circulo con la funcion del espacio).
"""
import json
import re
from pathlib import Path

RUTA = Path(__file__).resolve().parent / "clasificacion_mobiliario.json"
_cache: dict = {}


def cargar(ruta=None) -> dict:
    ruta = Path(ruta or RUTA)
    if ruta not in _cache:
        with open(ruta, encoding="utf-8") as fh:
            _cache[ruta] = json.load(fh)
    return _cache[ruta]


def _normalizar(s) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").casefold()) if unicodedata.category(c) != "Mn")


def _coincide(rx, texto) -> bool:
    return bool(rx.search(texto) or rx.search(_normalizar(texto)))


def _tamano(w_m, h_m, rango) -> bool | None:
    """True/False si el tamano cabe en el rango del rol; None si no hay dato (ausente, no negativo)."""
    if not w_m or not h_m or w_m <= 0 or h_m <= 0:
        return None
    a, b = sorted((float(w_m), float(h_m)))
    (m0, m1), (M0, M1) = rango["lado_menor"], rango["lado_mayor"]
    return m0 <= a <= m1 and M0 <= b <= M1


def clasificar(nombre: str, capa: str, w_m: float | None, h_m: float | None, interior: dict | None, vocab, datos: dict | None = None) -> dict | None:
    """interior (opcional): {"anidados": [nombres], "capas": [nombres], "n": {"circulos": n, ...}}. Devuelve None si no hay evidencia suficiente."""
    d = datos or cargar()
    pesos, um = d["pesos"], d["umbrales"]
    interior = interior or {}
    anidados = [str(x) for x in interior.get("anidados", []) if x]
    capas = [str(x) for x in interior.get("capas", []) if x]
    textos = [str(x) for x in interior.get("textos", []) if x]
    n = interior.get("n") or {}
    puntaje: dict = {}
    evid: dict = {}
    for rol, rx in vocab.roles:
        pts, ev = 0.0, []
        coinc = sorted({a for a in anidados if _coincide(rx, a)})
        if coinc:
            extra = min(pesos["nombre_anidado_extra"] * (len(coinc) - 1), pesos["nombre_anidado_extra_max"])
            pts += pesos["nombre_anidado"] + extra
            ev.append({"tipo": "nombre_anidado", "detalle": coinc[:3], "peso": round(pesos["nombre_anidado"] + extra, 2)})
        txt = sorted({t for t in textos if _coincide(rx, t)})
        if txt:
            peso_txt = pesos.get("texto_interno", 0.45) + min(pesos["nombre_anidado_extra"] * (len(txt) - 1), pesos["nombre_anidado_extra_max"])   # varios textos refuerzan
            pts += peso_txt
            ev.append({"tipo": "texto_interno", "detalle": txt[:3], "peso": round(peso_txt, 2)})
        cap = sorted({c for c in capas if _coincide(rx, c)})
        if cap:
            pts += pesos["capa_interna"]
            ev.append({"tipo": "capa_interna", "detalle": cap[:3], "peso": pesos["capa_interna"]})
        if pts <= 0 and rol not in d["rangos"]:
            continue
        rango = d["rangos"].get(rol)
        if rango is not None:
            ok = _tamano(w_m, h_m, rango)
            if ok is True:
                pts += pesos["tamano_compatible"]
                ev.append({"tipo": "tamano_compatible", "detalle": [round(float(w_m), 2), round(float(h_m), 2)], "peso": pesos["tamano_compatible"]})
            elif ok is False and pts > 0:                   # el tamano incompatible solo resta si ya habia otra evidencia
                pts += pesos["tamano_incompatible"]
                ev.append({"tipo": "tamano_incompatible", "detalle": [round(float(w_m), 2), round(float(h_m), 2)], "peso": pesos["tamano_incompatible"]})
        if rol in d.get("circular_para", []) and n.get("circulos", 0) >= 1 and w_m and h_m and abs(w_m - h_m) / max(w_m, h_m) < 0.15 and pts > 0.2:
            pts += pesos["forma_circular"]
            ev.append({"tipo": "forma_circular", "detalle": ["caja casi cuadrada con circulos"], "peso": pesos["forma_circular"]})
        if pts > 0:
            puntaje[rol], evid[rol] = round(pts, 2), ev
    if not puntaje:
        return None
    orden = sorted(puntaje.items(), key=lambda kv: -kv[1])
    rol, pts = orden[0]
    confianza = "alta" if pts >= um["alta"] else "media" if pts >= um["media"] else "baja" if pts >= um["baja"] else None
    if confianza is None:
        return None
    # empate o rivalidad cercana: no se acepta con confianza alta
    if len(orden) > 1 and orden[1][1] >= pts - 0.1 and confianza == "alta":
        confianza = "media"
    return {"rol": rol, "confianza": confianza, "puntaje": pts, "evidencias": evid[rol],
            "alternativas": [{"rol": r, "puntaje": p} for r, p in orden[1:3]], "rol_origen": "inferido"}


def aceptado(cl: dict | None) -> bool:
    """Alta o media se usa como rol; baja solo se sugiere (nunca coloca nada por si sola)."""
    return bool(cl) and cl["confianza"] in ("alta", "media")
