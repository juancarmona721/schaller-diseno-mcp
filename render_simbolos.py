"""Dibuja como PNG el simbolo de cada bloque del catalogo, leyendo su definicion en los dibujos abiertos (SOLO LECTURA).

Uso: python render_simbolos.py <catalogo_bloques.csv> <carpeta_png>
Reutiliza la lectura de geometria de _probe_svg.py (lineas, polilineas, circulos, arcos, bloques anidados).
Escribe <carpeta_png>/<n>.png y indice.json (bloque -> archivo | null). No modifica AutoCAD.
"""
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _probe_svg as svg  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

TAM = 120


def dibujar(prims, ruta):
    prims = prims[: svg.MAX_PRIMITIVAS]
    caja = svg._caja(prims)
    if not caja:
        return False
    x0, y0, x1, y1 = caja
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    esc = (TAM - 12) / max(w, h)
    ox, oy = (TAM - w * esc) / 2, (TAM - h * esc) / 2
    P = lambda x, y: (ox + (x - x0) * esc, TAM - (oy + (y - y0) * esc))  # noqa: E731
    img = Image.new("RGB", (TAM, TAM), "white")
    d = ImageDraw.Draw(img)
    col, ancho = (42, 74, 114), 1
    for p in prims:
        if p[0] == "l":
            d.line([P(p[1], p[2]), P(p[3], p[4])], fill=col, width=ancho)
        elif p[0] == "c":
            a, b = P(p[1] - p[3], p[2] + p[3]), P(p[1] + p[3], p[2] - p[3])
            d.ellipse([a, b], outline=col, width=ancho)
        elif p[0] == "a":
            cx, cy, r, a0, a1 = p[1:]
            barrido = (a1 - a0) % (2 * math.pi) or 2 * math.pi
            pts = [P(cx + r * math.cos(a0 + barrido * k / 24), cy + r * math.sin(a0 + barrido * k / 24)) for k in range(25)]
            d.line(pts, fill=col, width=ancho)
        else:
            pts = [P(x, y) for x, y in p[1]]
            if p[2]:
                pts.append(pts[0])
            d.line(pts, fill=col, width=ancho)
    img.save(ruta)
    return True


def main():
    nombres = [r["bloque"] for r in csv.DictReader(open(sys.argv[1], encoding="utf-8-sig"), delimiter=";")]
    salida = Path(sys.argv[2])
    salida.mkdir(parents=True, exist_ok=True)
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = win32com.client.GetActiveObject("AutoCAD.Application")
    docs = [app.Documents.Item(i) for i in range(app.Documents.Count)]
    indice = {}
    for n, nombre in enumerate(nombres):
        indice[nombre] = None
        for doc in docs:
            try:
                if not svg.existe(doc.Blocks, nombre):
                    continue

                def resolver(ref, doc=doc):
                    try:
                        b = doc.Blocks.Item(ref.Name)
                        return list(b), tuple(b.Origin)[:2]
                    except Exception:
                        return None, (0.0, 0.0)
                prims = svg.primitivas(list(doc.Blocks.Item(nombre)), resolver, 0, {})
                if prims and dibujar(prims, salida / f"{n}.png"):
                    indice[nombre] = f"{n}.png"
                    break
            except Exception:
                continue
    (salida / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "con_simbolo": sum(1 for v in indice.values() if v), "total": len(indice)}))


if __name__ == "__main__":
    main()
