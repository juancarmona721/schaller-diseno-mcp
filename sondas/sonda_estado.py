"""Sonda de SOLO LECTURA a AutoCAD. Se ejecuta como proceso aparte (ver acad.py).

Se conecta con GetActiveObject: nunca inicia AutoCAD. Imprime UN objeto JSON por stdout.
Si AutoCAD se queda colgado, el proceso padre lo corta por tiempo; por eso vive aparte.
"""
import json

INSUNITS = {0: "sin unidad", 1: "pulgadas", 2: "pies", 3: "millas", 4: "milimetros", 5: "centimetros",
            6: "metros", 7: "kilometros", 14: "decimetros"}


def leer(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def main():
    try:
        import pythoncom
        import win32com.client
    except Exception as e:  # pywin32 no instalado
        return {"ok": False, "error": "sin_pywin32", "detalle": str(e)}
    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception:
        return {"ok": False, "error": "autocad_no_abierto",
                "detalle": "No encontre una instancia de AutoCAD abierta (o no tiene COM, como AutoCAD LT)."}
    nombre = leer(lambda: app.Name, "")
    version = leer(lambda: app.Version, "")
    out = {"ok": True, "producto": nombre, "version_interna": version}
    major = leer(lambda: int(str(version).split(".")[0]))
    out["anio_aproximado"] = 2000 + major if major else None
    out["documentos_abiertos"] = leer(lambda: app.Documents.Count)
    doc = leer(lambda: app.ActiveDocument)
    if doc is None:
        out["dibujo_activo"] = None
    else:
        out["dibujo_activo"] = leer(lambda: doc.Name)
        u = leer(lambda: doc.GetVariable("INSUNITS"))
        out["unidades"] = INSUNITS.get(u, str(u))
        out["pestana_actual"] = leer(lambda: doc.GetVariable("CTAB"))
        out["objetos_en_modelo"] = leer(lambda: doc.ModelSpace.Count)

        def propios():
            """Objetos que coloco ESTE MCP (capas SCH_ILUMINACION/SCH_AUDIO): no cuentan para saber si el plano cambio, porque el escaner ni los lee."""
            from win32com.client import VARIANT
            nombre_ss = f"SS_ESTADO_{__import__('os').getpid()}"
            try:
                doc.SelectionSets.Item(nombre_ss).Delete()
            except Exception:
                pass
            ss = doc.SelectionSets.Add(nombre_ss)
            try:
                ss.Select(5, None, None, VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_I2, (8,)), VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, ("SCH_ILUMINACION,SCH_AUDIO,SCH_REVISION",)))
                return int(ss.Count)
            finally:
                ss.Delete()
        out["objetos_propios"] = leer(propios, 0)
    # AutoCAD LT no expone COM: si llegamos hasta aqui por COM, es la version completa.
    out["es_version_completa_con_com"] = ("LT" not in str(nombre).upper()) and bool(version)
    return out


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, default=str))
