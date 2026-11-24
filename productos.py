"""Lectura de la hoja de productos (Excel). SOLO LECTURA: nunca se escribe en la hoja.

Reglas:
- Se lee con openpyxl; "N/A" es un valor valido, NO un vacio. Vacio = celda None o solo espacios.
- La ruta de la hoja viene de config.toml ([productos].ruta_hoja).
- La referencia NO es clave unica: "SIN REFERENCIA" puede repetirse.
"""
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import openpyxl

SISTEMA = "Sistema"
REF = "Referencia (Odoo)"
CORTO = "Nombre corto (ficha)"
MARCA = "Marca (sigla)"
ODOO = "Nombre en Odoo"
INVENTADOS = "Campos inventados (PRUEBA)"
BLOQUE = "Bloque en CAD (sugerido, por confirmar)"
OBLIGATORIAS = (SISTEMA, REF, CORTO, MARCA, ODOO, INVENTADOS)
SIN_REF = "SIN REFERENCIA"


class HojaError(Exception):
    """Error legible para el usuario (ruta mal, hoja no existe, columnas faltantes...)."""


def norm(s) -> str:
    """Minusculas y sin tildes, para comparar ('Iluminacion' == 'Iluminación')."""
    s = unicodedata.normalize("NFKD", "" if s is None else str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).casefold().strip()


def es_vacio(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def cargar(ruta, hoja="Productos") -> tuple[list[str], list[dict]]:
    """Devuelve (encabezados, productos). Cada producto lleva '_fila' (numero de fila en Excel)."""
    if not ruta:
        raise HojaError("Falta [productos].ruta_hoja en config.toml.")
    p = Path(ruta)
    if not p.is_file():
        raise HojaError(f"No encuentro la hoja de productos: {p}")
    try:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    except Exception as e:  # archivo daniado, formato raro, bloqueado...
        raise HojaError(f"No pude abrir la hoja ({type(e).__name__}: {e}).") from e
    try:
        if hoja not in wb.sheetnames:
            raise HojaError(f"La hoja '{hoja}' no existe. Hojas disponibles: {', '.join(wb.sheetnames)}")
        filas = list(wb[hoja].iter_rows(values_only=True))
    finally:
        wb.close()
    if not filas:
        raise HojaError(f"La hoja '{hoja}' esta vacia.")
    enc = [str(h).strip() if h is not None else None for h in filas[0]]
    faltan = [c for c in OBLIGATORIAS if c not in enc]
    if faltan:
        raise HojaError(f"Faltan columnas en la hoja '{hoja}': {', '.join(faltan)}")
    prods = []
    for n, fila in enumerate(filas[1:], start=2):
        if all(es_vacio(v) for v in fila):
            continue
        d = {"_fila": n}
        for h, v in zip(enc, fila):
            if h is not None:
                d[h] = v.strip() if isinstance(v, str) else v
        prods.append(d)
    return [h for h in enc if h is not None], prods


def cargar_accesorios(ruta, hoja="Drivers y accesorios") -> list[dict]:
    """Drivers, controladores, perfiles y accesorios, con el producto al que acompanan ('junto_a')."""
    if not ruta or not Path(ruta).is_file():
        raise HojaError(f"No encuentro la hoja de productos: {ruta}")
    try:
        wb = openpyxl.load_workbook(Path(ruta), read_only=True, data_only=True)
    except Exception as e:
        raise HojaError(f"No pude abrir la hoja ({type(e).__name__}: {e}).") from e
    try:
        if hoja not in wb.sheetnames:
            return []  # la hoja de accesorios es opcional
        filas = list(wb[hoja].iter_rows(values_only=True))
    finally:
        wb.close()
    if not filas:
        return []
    enc = [norm(h) for h in filas[0]]
    col = lambda *claves: next((i for i, h in enumerate(enc) if any(h.startswith(k) for k in claves)), None)  # noqa: E731
    ci = {"referencia": col("referencia"), "nombre_corto": col("nombre corto"), "marca": col("marca"), "tipo": col("tipo"),
          "junto_a": col("aparece junto a"), "fuente": col("fuente"), "nombre_odoo": col("nombre en odoo")}
    out = []
    for fila in filas[1:]:
        if all(es_vacio(v) for v in fila):
            continue
        out.append({k: (str(fila[i]).strip() if i is not None and not es_vacio(fila[i]) else None) for k, i in ci.items()})
    return out


def accesorios_de(producto: dict, accesorios: list[dict]) -> list[dict]:
    """Accesorios cuyo 'aparece junto a' menciona este producto (por nombre, sin tildes ni mayusculas)."""
    nombre = norm(producto.get(CORTO))
    if not nombre:
        return []
    res = []
    for a in accesorios:
        partes = [norm(re.sub(r"\([^)]*\)", "", t)) for t in re.split(r"[,;]", a.get("junto_a") or "")]
        if any(t and (t in nombre or nombre in t) for t in partes):
            res.append(a)
    return res


def campos_inventados(p: dict) -> list[str]:
    v = p.get(INVENTADOS)
    if es_vacio(v) or norm(v).startswith("ninguno"):
        return []
    return [c.strip() for c in str(v).split(",") if c.strip()]


def bloques_cad(p: dict) -> list[str]:
    """Nombres de bloque sugeridos en la hoja (separados por coma, punto y coma o barra vertical)."""
    v = p.get(BLOQUE)
    if es_vacio(v):
        return []
    return [n.strip() for n in str(v).replace(";", ",").replace("|", ",").split(",") if n.strip()]


def resumen(p: dict) -> dict:
    return {"referencia": p.get(REF), "nombre_corto": p.get(CORTO), "marca": p.get(MARCA), "sistema": p.get(SISTEMA)}


def listar(prods: list[dict], sistema=None) -> list[dict]:
    return [resumen(p) for p in prods if sistema is None or norm(p.get(SISTEMA)) == norm(sistema)]


def ficha(p: dict) -> dict:
    """Todos los campos de la fila; si hay campos inventados, agrega el aviso."""
    out = {"fila_excel": p["_fila"], "campos": {k: v for k, v in p.items() if k != "_fila"}}
    inv = campos_inventados(p)
    if inv:
        out["aviso"] = "DATOS DE PRUEBA: " + ", ".join(inv)
    return out


def ver(prods: list[dict], referencia) -> list[dict]:
    return [p for p in prods if norm(p.get(REF)) == norm(referencia)]


def buscar(prods: list[dict], texto) -> list[dict]:
    t = norm(texto)
    if not t:
        return []
    return [{**resumen(p), "nombre_en_odoo": p.get(ODOO)} for p in prods
            if any(t in norm(p.get(c)) for c in (REF, CORTO, ODOO))]


def validar(prods: list[dict], encabezados: list[str]) -> dict:
    por_ref = defaultdict(list)
    for p in prods:
        r = p.get(REF)
        if not es_vacio(r) and norm(r) != norm(SIN_REF):
            por_ref[str(r).strip()].append(p["_fila"])
    repetidas = {k: v for k, v in por_ref.items() if len(v) > 1}
    detalle = []
    for p in prods:
        problemas = []
        r = p.get(REF)
        if es_vacio(r):
            problemas.append("referencia vacia")
        elif norm(r) == norm(SIN_REF):
            problemas.append(SIN_REF)
        elif str(r).strip() in repetidas:
            problemas.append("referencia repetida en filas " + ", ".join(map(str, repetidas[str(r).strip()])))
        vacios = [h for h in encabezados if h != INVENTADOS and es_vacio(p.get(h))]
        inv = campos_inventados(p)
        if problemas or vacios or inv:
            detalle.append({"fila_excel": p["_fila"], "referencia": r, "nombre_corto": p.get(CORTO),
                            "problemas": problemas, "campos_vacios": vacios, "campos_inventados": inv})
    return {
        "total_productos": len(prods),
        "productos_con_hallazgos": len(detalle),
        "productos_sin_hallazgos": len(prods) - len(detalle),
        "sin_referencia": sum(1 for p in prods if not es_vacio(p.get(REF)) and norm(p.get(REF)) == norm(SIN_REF)),
        "referencias_repetidas": repetidas,
        "nota": "'N/A' se considera un valor valido, no un campo vacio.",
        "detalle": detalle,
    }
