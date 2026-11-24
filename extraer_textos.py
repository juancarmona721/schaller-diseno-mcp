"""Extrae TABLAS y TEXTOS (con posicion) de dibujos abiertos en AutoCAD (SOLO LECTURA).

Uso: python -I extraer_textos.py <carpeta_salida> <dibujo1.dwg> [<dibujo2.dwg> ...]
Escribe <carpeta_salida>/textos_<dibujo>.json con tablas (celdas) y textos (texto, x, y, capa).
No modifica ni activa dibujos, no guarda, no usa AutoLISP.
"""
import json
import re
import sys
import time
from pathlib import Path

BUSY = (-2147418111, -2147417846)


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


def limpiar(t):
    t = re.sub(r"\\[A-Za-z][^;]*;", "", t or "")      # codigos de formato MText
    return t.replace("\\P", " ").replace("{", "").replace("}", "").strip()


def analizar(doc):
    modelo = leer(lambda: doc.ModelSpace)
    total = leer(lambda: modelo.Count, 0)
    tablas, textos = [], []
    for idx in range(total):
        obj = None
        for _ in range(30):
            obj = leer(lambda: modelo.Item(idx))
            if obj is not None:
                break
            time.sleep(1)
        if obj is None:
            continue
        tipo = leer(lambda: obj.ObjectName, "")
        if tipo == "AcDbTable":
            filas, cols = leer(lambda: obj.Rows, 0), leer(lambda: obj.Columns, 0)
            p = leer(lambda: obj.InsertionPoint, (None, None, None))
            celdas = []
            for r in range(filas):
                celdas.append([limpiar(leer(lambda: obj.GetText(r, c), "")) for c in range(cols)])
            tablas.append({"x": p[0], "y": p[1], "capa": leer(lambda: obj.Layer, "?"), "filas": filas, "cols": cols,
                           "celdas": celdas})
        elif tipo in ("AcDbText", "AcDbMText"):
            t = limpiar(leer(lambda: obj.TextString, ""))
            if t:
                p = leer(lambda: obj.InsertionPoint, (None, None, None))
                if tipo == "AcDbText" and leer(lambda: obj.Alignment, 0):
                    p = leer(lambda: obj.TextAlignmentPoint, p)  # texto centrado/derecha: el ancla real
                textos.append({"texto": t, "x": round(p[0], 2) if p[0] is not None else None,
                               "y": round(p[1], 2) if p[1] is not None else None,
                               "capa": leer(lambda: obj.Layer, "?"), "tipo": tipo})
    return {"objetos": total, "tablas": tablas, "textos": textos}


def main():
    salida = Path(sys.argv[1])
    salida.mkdir(parents=True, exist_ok=True)
    pedidos = {n.lower() for n in sys.argv[2:]}
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = win32com.client.GetActiveObject("AutoCAD.Application")
    for i in range(app.Documents.Count):
        doc = app.Documents.Item(i)
        nombre = leer(lambda: doc.Name, "")
        if nombre.lower() not in pedidos:
            continue
        r = analizar(doc)
        (salida / f"textos_{nombre}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{nombre}: {len(r['tablas'])} tablas, {len(r['textos'])} textos", file=sys.stderr)
    print(json.dumps({"ok": True}))


if __name__ == "__main__":
    main()
