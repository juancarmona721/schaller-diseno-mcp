"""Une leyendas + tablas + Odoo en un catalogo de bloques. Todo entra como 'propuesto' (lo confirma una persona).

Duplicados en Odoo (misma referencia o varias variantes posibles): se toma la de MAYOR STOCK; las demas quedan en observaciones.
Uso: python -I crear_catalogo.py <carpeta_extraccion> <excel_odoo>
Salida: catalogo_bloques.csv  (referencia, nombre, stock; sin precios)
"""
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

base = Path(sys.argv[1])
norm = lambda s: re.sub(r"[^A-Z0-9]", "", str(s).upper())
leer = lambda n: list(csv.DictReader(open(base / n, encoding="utf-8-sig"), delimiter=";"))

# Odoo: referencia normalizada -> [(ref, nombre, stock)] ordenado por stock descendente (el primero es el elegido)
rows = list(openpyxl.load_workbook(sys.argv[2], read_only=True, data_only=True).active.iter_rows(values_only=True))
h = rows[0]
iN, iR, iS = h.index("Nombre"), h.index("Referencia interna"), h.index("Cantidad a la mano")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


odoo = defaultdict(list)
for r in rows[1:]:
    if r[iN] and r[iR]:
        odoo[norm(r[iR])].append((str(r[iR]).strip(), str(r[iN]).strip(), num(r[iS])))
for v in odoo.values():
    v.sort(key=lambda t: -t[2])


def elegir(opciones):
    """Mayor stock. Devuelve (elegida, nota). Si hay empate en 0, avisa."""
    opciones = sorted(opciones, key=lambda t: -t[2])
    e = opciones[0]
    resto = opciones[1:]
    nota = ""
    if resto:
        nota = f"elegida por mayor stock ({e[0]}: {e[2]:g}); otras: " + ", ".join(f"{r[0]}: {r[2]:g}" for r in resto)
        if e[2] == 0:
            nota += " [TODAS CON STOCK 0: revisar]"
    return e, nota


unicos = {r["bloque"]: r for r in leer("bloques_unicos.csv")}
cat = defaultdict(lambda: {"nombre_generico": "", "marca": "", "ref": "", "desc": "", "stock": "", "fuentes": [], "obs": []})


def poner_ref(c, ref):
    """Asigna referencia + descripcion + stock desde Odoo (mayor stock si esta repetida)."""
    ops = odoo.get(norm(ref))
    if not ops:
        c["ref"] = c["ref"] or ref
        return
    e, nota = elegir(ops)
    c["ref"], c["desc"], c["stock"] = e[0], e[1], e[2]
    if nota:
        c["obs"].append(nota)


# 1) Leyenda del dibujo 4
for r in leer("leyenda_dibujo4.csv"):
    bl = [b.strip() for b in r["bloques_simbolo"].split(",") if b.strip()]
    for b in bl:
        c = cat[b]
        nuevo = f'{r["nombre_leyenda"]} (#{r["numero"]})'
        if c["nombre_generico"] and nuevo not in c["nombre_generico"]:
            c["obs"].append(f"tambien aparece en la leyenda como {nuevo}")
        else:
            c["nombre_generico"], c["marca"] = nuevo, r["marca_columna"]
        c["fuentes"].append("leyenda dib4")
        if len(bl) > 1:
            c["obs"].append(f'variante de {r["nombre_leyenda"]} ({len(bl)} simbolos en la fila)')
        if r["referencia_en_leyenda"] and not c["ref"]:
            poner_ref(c, r["referencia_en_leyenda"])

# 2) Tablas REFERENCIA/ESPACIO/CANTIDAD (dib 9 y 6)
for r in leer("tablas_referencia_espacio.csv"):
    for b in [b.strip() for b in r["bloques_icono"].split(",") if b.strip()]:
        c = cat[b]
        m = re.match(r"[0-9][A-Za-z0-9]{6,}(?:\.\d+)*", r["texto_referencia"].strip())
        ref = r["referencia"] or (m.group(0) if m else r["texto_referencia"].split()[0])
        if c["ref"] and norm(c["ref"]) != norm(ref):
            c["obs"].append(f'tabla dib{r["dibujo"]} indica {ref}')
        elif not c["ref"]:
            poner_ref(c, ref)
        c["fuentes"].append(f'tabla dib{r["dibujo"]}')

# 3) Codigo Davide Groppi con comodin XX en el nombre del bloque: varias variantes -> mayor stock
for b in unicos:
    for m in re.finditer(r"(1A\d{3})XX(\d{2})", b):
        pat = re.compile("^" + m.group(1) + r"\d\d" + m.group(2))
        ops = [o for k, v in odoo.items() if pat.match(k) for o in v]
        c = cat[b]
        c["marca"] = c["marca"] or "DAVIDE GROPPI"
        c["fuentes"].append("codigo en nombre")
        if ops and not c["ref"]:
            e, nota = elegir(ops)
            c["ref"], c["desc"], c["stock"] = e[0], e[1], e[2]
            if nota:
                c["obs"].append("variante " + nota)

# 4) El nombre del bloque ES una referencia de Odoo (p. ej. CI200ER, 1T8836DATR)
for b in unicos:
    k = norm(b.split()[0]) if b.split() else ""
    if k in odoo and len(k) >= 5 and any(ch.isdigit() for ch in k):
        c = cat[b]
        c["fuentes"].append("nombre = ref Odoo")
        if not c["ref"]:
            poner_ref(c, odoo[k][0][0])

# 5) Candidatos del filtro (sin datos todavia) para que queden en el mismo lugar
for r in leer("productos_candidatos.csv"):
    cat[r["bloque"]]

# Sistema segun la capa donde esta el bloque
def sistema(capas):
    s = capas.upper()
    if "ILUMIN" in s or "DAVIDE GROPPI" in s:
        return "Iluminacion"
    if "KEYPAD" in s or "CONTROL" in s:
        return "Control"
    if "CAMARA" in s or "CÁMARA" in s or "C�MARAS" in s:
        return "Camaras"
    if "SCH_AV" in s:
        return "Audio / Video"
    if "RACK" in s:
        return "Rack"
    return ""


with open(base / "catalogo_bloques.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["bloque", "nombre_generico", "marca", "sistema", "referencia", "descripcion_odoo", "stock_odoo",
                "estado", "total_en_planos", "dibujos", "capas", "fuentes", "observaciones", "confirmado_por", "fecha_confirmacion"])
    for b, c in sorted(cat.items(), key=lambda kv: -int((unicos.get(kv[0]) or {"total": 0})["total"] or 0)):
        u = unicos.get(b, {})
        estado = "propuesto" if (c["ref"] or c["nombre_generico"]) else "pendiente"
        w.writerow([b, c["nombre_generico"], c["marca"], sistema(u.get("capas", "")), c["ref"], c["desc"],
                    "" if c["stock"] == "" else f'{c["stock"]:g}', estado, u.get("total", ""), u.get("dibujos", ""),
                    u.get("capas", ""), ", ".join(sorted(set(c["fuentes"]))), " | ".join(dict.fromkeys(c["obs"])), "", ""])
print(f"bloques en catalogo: {len(cat)}; con referencia: {sum(1 for c in cat.values() if c['ref'])}; "
      f"con nombre generico: {sum(1 for c in cat.values() if c['nombre_generico'])}")
