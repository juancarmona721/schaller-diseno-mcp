"""Sonda de SOLO LECTURA: bloques insertados en el espacio Modelo. Se ejecuta como proceso aparte.

Argumento (JSON en argv[1]): {"nombres": [..] | null, "limite": int, "max_posiciones": int}
No modifica nada, no crea selecciones, no usa AutoLISP. No devuelve el nombre del dibujo.
"""
import json
import math
import sys
import time

BUSY = (-2147418111, -2147417846)  # RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER
INSUNITS = {0: "sin unidad", 1: "pulgadas", 2: "pies", 3: "millas", 4: "milimetros", 5: "centimetros",
            6: "metros", 7: "kilometros", 14: "decimetros"}


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


def analizar(doc, nombres=None, limite=5000, max_posiciones=200):
    """Recorre el modelo (hasta `limite` objetos). Funciona con cualquier objeto tipo COM de AutoCAD."""
    buscados = {str(n).casefold() for n in (nombres or [])}
    modelo = leer(lambda: doc.ModelSpace)
    total = leer(lambda: modelo.Count, 0)
    cuentas, capas, posiciones = {}, {}, {}
    revisados = 0
    for obj in modelo:
        if revisados >= limite:
            break
        revisados += 1
        if leer(lambda: obj.ObjectName, "") != "AcDbBlockReference":
            continue
        nombre = leer(lambda: obj.EffectiveName) or leer(lambda: obj.Name, "?")
        capa = leer(lambda: obj.Layer, "?")
        cuentas[nombre] = cuentas.get(nombre, 0) + 1
        c = capas.setdefault(nombre, {})
        c[capa] = c.get(capa, 0) + 1
        if nombre.casefold() in buscados:
            lista = posiciones.setdefault(nombre, [])
            if len(lista) < max_posiciones:
                p = leer(lambda: obj.InsertionPoint, (None, None, None))
                rot = leer(lambda: obj.Rotation, 0.0) or 0.0
                lista.append({"x": round(p[0], 4) if p[0] is not None else None,
                              "y": round(p[1], 4) if p[1] is not None else None,
                              "rotacion_grados": round(math.degrees(rot), 3), "capa": capa,
                              "escala_x": leer(lambda: round(float(obj.XScaleFactor), 6))})
    unidades = leer(lambda: INSUNITS.get(doc.GetVariable("INSUNITS"), str(doc.GetVariable("INSUNITS"))))
    return {
        "ok": True, "unidades": unidades, "objetos_en_modelo": total, "objetos_revisados": revisados,
        "truncado": revisados < total,
        "bloques": sorted(({"nombre": n, "cantidad": q, "capas": capas[n]} for n, q in cuentas.items()),
                          key=lambda b: -b["cantidad"]),
        "posiciones": posiciones,
    }


def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    try:
        import pythoncom
        import win32com.client
    except Exception as e:
        return {"ok": False, "error": "sin_pywin32", "detalle": str(e)}
    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
        doc = app.ActiveDocument
    except Exception:
        return {"ok": False, "error": "autocad_no_abierto",
                "detalle": "No encontre AutoCAD abierto con un dibujo activo."}
    return analizar(doc, args.get("nombres"), int(args.get("limite", 5000)), int(args.get("max_posiciones", 200)))


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, default=str))
