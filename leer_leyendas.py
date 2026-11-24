"""Lee las LEYENDAS/TABLAS de los planos (a partir de lo ya extraido) y las cruza con Odoo. Solo lectura de archivos.

Uso: python -I leer_leyendas.py <carpeta_extraccion> <excel_odoo>
Entradas: bloques_por_dibujo.json y textos_<dibujo>.json (extraer_todos.py / extraer_textos.py)
Salidas : leyenda_dibujo4.csv, tablas_referencia_espacio.csv
No copia precios ni datos comerciales de Odoo: solo referencia y nombre.
"""
import csv
import json
import re
import sys
from pathlib import Path

import openpyxl

base = Path(sys.argv[1])
norm = lambda s: re.sub(r"[^A-Z0-9]", "", str(s).upper())

# ---- Odoo: referencia -> nombre (sin precios) ----
rows = list(openpyxl.load_workbook(sys.argv[2], read_only=True, data_only=True).active.iter_rows(values_only=True))
h = rows[0]
iN, iR = h.index("Nombre"), h.index("Referencia interna")
odoo = {}
for r in rows[1:]:
    if r[iN] and r[iR]:
        odoo.setdefault(norm(r[iR]), []).append((str(r[iR]).strip(), str(r[iN]).strip()))

PAT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{4,}")


def buscar_ref(texto):
    """Primer token del texto que sea una referencia de Odoo. Devuelve (ref_texto, [(ref_odoo, nombre)])."""
    for tok in PAT_REF.findall(texto):
        if norm(tok) in odoo and any(c.isdigit() for c in tok):
            return tok, odoo[norm(tok)]
    return "", []


instancias = json.load(open(base / "bloques_por_dibujo.json", encoding="utf-8"))["instancias"]


def textos(n):
    d = json.load(open(base / f"textos_extraccionbloques{n}.dwg.json", encoding="utf-8"))
    return [t for t in d["textos"] if t["x"] is not None]


def bloques(n, x0, x1, y, tol):
    return sorted({i["bloque"] for i in instancias if i["dibujo"] == f"extraccionbloques{n}.dwg" and i["x"] is not None
                   and x0 <= i["x"] <= x1 and abs(i["y"] - y) <= tol})


# ---------------- Leyenda del dibujo 4 ----------------
ts = textos(4)
columnas = {"TARGETTI": 8334.8, "DAVIDE GROPPI": 8361.6, "FLOS/KEF": 8386.0}
limites_simbolo = {"TARGETTI": (8337.5, 8361.0), "DAVIDE GROPPI": (8363.8, 8385.4), "FLOS/KEF": (8388.3, 8400.0)}
sal4 = []
import statistics


def instancias_en(n, x0, x1, y0, y1):
    return [i for i in instancias if i["dibujo"] == f"extraccionbloques{n}.dwg" and i["x"] is not None
            and x0 <= i["x"] <= x1 and y0 <= i["y"] <= y1]


def asignar_simbolos(filas, simbolos, tol, offset=None):
    """Cada simbolo va a UNA sola fila (la mas cercana tras corregir el desfase tipico simbolo-texto)."""
    if offset is None:
        dif = [s["y"] - f["y"] for f in filas for s in simbolos
               if len(norm(f["texto"])) >= 3 and norm(f["texto"]) in norm(s["bloque"]) and abs(s["y"] - f["y"]) < 1.2]
        offset = statistics.median(dif) if dif else -0.2
    res = {id(f): [] for f in filas}
    for s in simbolos:
        f = min(filas, key=lambda f: abs(s["y"] - (f["y"] + offset)), default=None)
        if f is not None and abs(s["y"] - (f["y"] + offset)) <= tol:
            res[id(f)].append(s["bloque"])
    return res, offset


for marca, nx in columnas.items():
    nombres = [t for t in ts if nx + 0.2 < t["x"] < nx + 1.4 and -6245 < t["y"] < -6207.5 and not re.fullmatch(r"[\d.]+", t["texto"])
               and t["texto"] != marca]
    numeros = [t for t in ts if abs(t["x"] - nx) < 0.3 and re.fullmatch(r"\d+", t["texto"])]
    x0s, x1s = limites_simbolo[marca]
    nombres = sorted(nombres, key=lambda t: -t["y"])
    asign, _off = asignar_simbolos(nombres, instancias_en(4, x0s, x1s, -6245, -6207.5), tol=0.3)
    for nm in nombres:
        num = min((n for n in numeros if abs(n["y"] - nm["y"]) < 0.3), key=lambda n: abs(n["y"] - nm["y"]), default=None)
        fila = [t for t in ts if abs(t["y"] - nm["y"]) < 0.3 and nm["x"] + 2 < t["x"] < nx + 36 and not t["texto"].isdigit()
                and (marca != "TARGETTI" or t["x"] < 8355)]
        extra = " | ".join(t["texto"] for t in sorted(fila, key=lambda t: t["x"]))
        ref_txt, ref_odoo = buscar_ref(extra)
        x0, x1 = limites_simbolo[marca]
        sal4.append({"marca_columna": marca, "numero": num["texto"] if num else "", "nombre_leyenda": nm["texto"],
                     "texto_fila": extra, "referencia_en_leyenda": ref_txt,
                     "odoo": "; ".join(f"{r} = {n}" for r, n in ref_odoo),
                     "bloques_simbolo": ", ".join(sorted(set(asign[id(nm)])))})

with open(base / "leyenda_dibujo4.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(sal4[0]), delimiter=";")
    w.writeheader()
    w.writerows(sal4)

# ---------------- Tablas ICONO / REFERENCIA / ESPACIO / CANTIDAD (dibujos 9 y 6) ----------------
sal_t = []
for n in (9, 6):
    ts = textos(n)
    cab = [t for t in ts if t["texto"].strip().upper() == "REFERENCIA"]
    for hr in cab:
        mismo_y = [t for t in ts if abs(t["y"] - hr["y"]) < 0.4]
        esp = min((t for t in mismo_y if t["texto"].strip().upper() == "ESPACIO" and hr["x"] < t["x"] < hr["x"] + 8),
                  key=lambda t: t["x"], default=None)
        can = min((t for t in mismo_y if t["texto"].strip().upper() == "CANTIDAD" and hr["x"] < t["x"] < hr["x"] + 12),
                  key=lambda t: t["x"], default=None)
        ico = max((t for t in mismo_y if t["texto"].strip().upper() == "ICONO" and hr["x"] - 4 < t["x"] < hr["x"]),
                  key=lambda t: t["x"], default=None)
        if not can or not esp:
            continue  # tabla sin columna ESPACIO (p. ej. la de drivers del dibujo 9): se trata aparte
        # el limite inferior es la siguiente cabecera en la misma columna
        siguientes = [c["y"] for c in cab if c is not hr and abs(c["x"] - hr["x"]) < 1.5 and c["y"] < hr["y"] - 1]
        ymin = max(siguientes) if siguientes else hr["y"] - 70
        esc = hr["x"] - 0.7, hr["x"] + 1.2
        refs = [t for t in ts if esc[0] <= t["x"] <= esc[1] and ymin < t["y"] < hr["y"] - 0.2
                and t["texto"].strip().upper() != "REFERENCIA"]
        en_col = lambda c, ancho: [u for u in ts if c["x"] - 0.7 <= u["x"] <= c["x"] + ancho and ymin < u["y"] < hr["y"] - 0.2]
        cand_esp, cand_can = en_col(esp, 1.6), en_col(can, 0.9)

        def cercano(cands, y, tol=0.3):
            u = min(cands, key=lambda u: abs(u["y"] - y), default=None)
            return u["texto"] if u is not None and abs(u["y"] - y) <= tol else ""
        iconos = instancias_en(n, ico["x"] - 1.5, ico["x"] + 1.2, ymin, hr["y"]) if ico else []
        asign_i, _ = asignar_simbolos(refs, iconos, tol=0.6, offset=0.0)
        for t in refs:
            ref_txt, ref_odoo = buscar_ref(t["texto"])
            sal_t.append({
                "dibujo": n, "texto_referencia": t["texto"], "referencia": ref_txt,
                "odoo": "; ".join(f"{r} = {nn}" for r, nn in ref_odoo),
                "espacio": cercano(cand_esp, t["y"]), "cantidad": cercano(cand_can, t["y"]),
                "bloques_icono": ", ".join(sorted(set(asign_i[id(t)]))),
                "x": round(t["x"], 1), "y": round(t["y"], 1)})

with open(base / "tablas_referencia_espacio.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(sal_t[0]), delimiter=";")
    w.writeheader()
    w.writerows(sal_t)

print(json.dumps({"leyenda4_filas": len(sal4), "leyenda4_con_bloque": sum(1 for s in sal4 if s["bloques_simbolo"]),
                  "leyenda4_con_ref_odoo": sum(1 for s in sal4 if s["odoo"]),
                  "tablas_filas": len(sal_t), "tablas_con_ref_odoo": sum(1 for s in sal_t if s["odoo"]),
                  "tablas_con_icono": sum(1 for s in sal_t if s["bloques_icono"])}))
