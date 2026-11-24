"""Extraccion de bloques de TODOS los dibujos abiertos en AutoCAD (SOLO LECTURA).

Uso: python -I extraer_todos.py <carpeta_salida>
No modifica ni activa dibujos, no guarda, no usa AutoLISP.
Escribe en <carpeta_salida>: bloques_por_dibujo.json, instancias.csv, bloques_unicos.csv
"""
import csv
import json
import math
import re
import sys
import time
from pathlib import Path

BUSY = (-2147418111, -2147417846)
# Referencias tipo Davide Groppi (1A202XX00), Ubiquiti (EAP610), 07U302410IN, 1T8447DATR, etc.
PATRON_REF = re.compile(r"\b(\d[A-Z]\d{3,}[A-Z0-9.]*|\d{2}U\d{5,}[A-Z]*|[A-Z]{2,}\d{2,}[A-Z0-9-]*)\b", re.I)


def leer(fn, default=None):
    for _ in range(4):
        try:
            return fn()
        except Exception as e:
            code = e.args[0] if getattr(e, "args", None) else None
            if code in BUSY:
                time.sleep(1)
                continue
            return default
    return default


def es_anonimo(nombre):
    return nombre.startswith("*") or nombre.startswith("A$C")


def analizar(doc):
    modelo = leer(lambda: doc.ModelSpace)
    total = leer(lambda: modelo.Count, 0)
    instancias = []
    for idx in range(total):
        obj = None
        for _ in range(30):  # AutoCAD ocupado: reintenta en vez de abortar
            obj = leer(lambda: modelo.Item(idx))
            if obj is not None:
                break
            time.sleep(1)
        if obj is None:
            continue
        if leer(lambda: obj.ObjectName, "") != "AcDbBlockReference":
            continue
        nombre = leer(lambda: obj.EffectiveName) or leer(lambda: obj.Name, "?")
        p = leer(lambda: obj.InsertionPoint, (None, None, None))
        attrs = {}
        if leer(lambda: obj.HasAttributes, False):
            for a in leer(lambda: obj.GetAttributes(), ()) or ():
                tag = leer(lambda: a.TagString, "")
                val = leer(lambda: a.TextString, "")
                if tag:
                    attrs[tag] = val
        instancias.append({
            "bloque": nombre,
            "capa": leer(lambda: obj.Layer, "?"),
            "x": round(p[0], 3) if p[0] is not None else None,
            "y": round(p[1], 3) if p[1] is not None else None,
            "rotacion_grados": round(math.degrees(leer(lambda: obj.Rotation, 0.0) or 0.0), 2),
            "escala_x": leer(lambda: round(float(obj.XScaleFactor), 4)),
            "atributos": attrs,
        })
    return total, instancias


def main():
    salida = Path(sys.argv[1])
    salida.mkdir(parents=True, exist_ok=True)
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = win32com.client.GetActiveObject("AutoCAD.Application")
    docs = app.Documents
    resultado, todas = {}, []
    solo = {n.lower() for n in sys.argv[2:]}  # opcional: solo estos dibujos, se funden con el JSON existente
    previo = salida / "bloques_por_dibujo.json"
    if solo and previo.exists():
        d = json.loads(previo.read_text(encoding="utf-8"))
        resultado = {k: v for k, v in d["resumen"].items() if k.lower() not in solo}
        todas = [it for it in d["instancias"] if it["dibujo"].lower() not in solo]
    for i in range(docs.Count):
        doc = docs.Item(i)
        nombre_dwg = leer(lambda: doc.Name, f"doc{i}")
        if not nombre_dwg.lower().startswith("extraccionbloques"):
            continue
        if solo and nombre_dwg.lower() not in solo:
            continue
        total, inst = analizar(doc)
        resultado[nombre_dwg] = {"objetos_en_modelo": total, "inserciones": len(inst)}
        for it in inst:
            it["dibujo"] = nombre_dwg
            todas.append(it)
        print(f"{nombre_dwg}: {total} objetos, {len(inst)} inserciones", file=sys.stderr)

    (salida / "bloques_por_dibujo.json").write_text(
        json.dumps({"resumen": resultado, "instancias": todas}, ensure_ascii=False, indent=1), encoding="utf-8")

    with open(salida / "instancias.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["dibujo", "bloque", "capa", "x", "y", "rotacion", "escala_x", "atributos"])
        for it in todas:
            w.writerow([it["dibujo"], it["bloque"], it["capa"], it["x"], it["y"], it["rotacion_grados"],
                        it["escala_x"], json.dumps(it["atributos"], ensure_ascii=False) if it["atributos"] else ""])

    unicos = {}
    for it in todas:
        u = unicos.setdefault(it["bloque"], {"total": 0, "dibujos": {}, "capas": {}, "attrs": {}})
        u["total"] += 1
        u["dibujos"][it["dibujo"]] = u["dibujos"].get(it["dibujo"], 0) + 1
        u["capas"][it["capa"]] = u["capas"].get(it["capa"], 0) + 1
        for k, v in it["atributos"].items():
            if v:
                u["attrs"].setdefault(k, set()).add(v)

    with open(salida / "bloques_unicos.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["bloque", "total", "dibujos", "capas", "referencia_detectada", "atributos",
                    "nombre_generico", "referencia", "descripcion", "estado"])
        for nombre, u in sorted(unicos.items(), key=lambda kv: -kv[1]["total"]):
            refs = sorted({m.group(1) for m in PATRON_REF.finditer(nombre)})
            w.writerow([
                nombre, u["total"],
                ", ".join(f"{d}({n})" for d, n in sorted(u["dibujos"].items())),
                ", ".join(f"{c}({n})" for c, n in sorted(u["capas"].items())),
                ", ".join(refs),
                "; ".join(f"{k}={'|'.join(sorted(v))}" for k, v in u["attrs"].items()),
                "", "", "", "pendiente",
            ])
    print(json.dumps({"ok": True, "dibujos": len(resultado), "inserciones": len(todas), "bloques_unicos": len(unicos),
                      "carpeta": str(salida)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
