"""Arma el UNICO Excel del catalogo: simbolo (imagen) + bloque + nombre + referencia + descripcion + stock + ...

Uso: python -I armar_excel.py <catalogo_bloques.csv> <carpeta_png> <salida.xlsx>
"""
import csv
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

csv_path, png_dir, salida = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
filas = list(csv.DictReader(open(csv_path, encoding="utf-8-sig"), delimiter=";"))
indice = json.load(open(png_dir / "indice.json", encoding="utf-8"))

orden_estado = {"propuesto": 0, "pendiente": 1}
filas.sort(key=lambda r: (orden_estado.get(r["estado"], 2), -int(r["total_en_planos"] or 0)))

cols = [("Simbolo", 16), ("Bloque en CAD", 34), ("Nombre generico", 30), ("Marca", 16), ("Sistema", 14),
        ("Referencia", 20), ("Descripcion (Odoo)", 44), ("Stock Odoo", 11), ("Estado", 12), ("Total en planos", 10),
        ("Dibujos", 30), ("Fuentes", 24), ("Observaciones", 50), ("Confirmado por", 16), ("Fecha confirmacion", 14)]
claves = [None, "bloque", "nombre_generico", "marca", "sistema", "referencia", "descripcion_odoo", "stock_odoo", "estado",
          "total_en_planos", "dibujos", "fuentes", "observaciones", "confirmado_por", "fecha_confirmacion"]

wb = Workbook()
ws = wb.active
ws.title = "Catalogo"
ws.append([c for c, _ in cols])
for i, (_, ancho) in enumerate(cols, 1):
    ws.column_dimensions[ws.cell(1, i).column_letter].width = ancho
    c = ws.cell(1, i)
    c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2A4A72")
    c.alignment = Alignment(vertical="center", wrap_text=True)
ws.freeze_panes = "C2"

relleno = {"propuesto": "FFF4D6", "pendiente": "F2F2F2", "confirmado": "DFF2DF"}
for n, r in enumerate(filas, 2):
    ws.append([None] + [r.get(k, "") for k in claves[1:]])
    ws.row_dimensions[n].height = 62
    for i in range(1, len(cols) + 1):
        ws.cell(n, i).alignment = Alignment(vertical="center", wrap_text=True)
    ws.cell(n, 9).fill = PatternFill("solid", fgColor=relleno.get(r["estado"], "FFFFFF"))
    for k in (8, 10):                       # numeros como numeros
        v = ws.cell(n, k).value
        if v not in ("", None):
            try:
                ws.cell(n, k).value = float(v)
            except ValueError:
                pass
    png = indice.get(r["bloque"])
    if png and (png_dir / png).exists():
        img = XLImage(str(png_dir / png))
        img.width = img.height = 80
        ws.add_image(img, f"A{n}")
    else:
        ws.cell(n, 1).value = "(sin simbolo)"
        ws.cell(n, 1).font = Font(italic=True, color="999999")

dv = DataValidation(type="list", formula1='"propuesto,confirmado,pendiente,descartado"', allow_blank=True)
ws.add_data_validation(dv)
dv.add(f"I2:I{len(filas) + 1}")
ws.auto_filter.ref = f"A1:{ws.cell(1, len(cols)).column_letter}{len(filas) + 1}"
wb.save(salida)
print(json.dumps({"ok": True, "filas": len(filas), "con_simbolo": sum(1 for r in filas if indice.get(r["bloque"])),
                  "archivo": str(salida)}, ensure_ascii=False))
