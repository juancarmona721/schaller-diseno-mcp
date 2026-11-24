"""Sonda de VISTA: hace Zoom Extents. SOLO mueve la vista; no crea, borra ni cambia objetos. Proceso aparte."""
import json


def zoom_extents(app, doc):
    def vista():
        c = doc.GetVariable("VIEWCTR")
        return {"centro": [round(c[0], 3), round(c[1], 3)], "alto_visible": round(float(doc.GetVariable("VIEWSIZE")), 3)}

    antes = vista()
    app.ZoomExtents()
    return {"ok": True, "pestana": doc.GetVariable("CTAB"), "objetos_en_modelo": doc.ModelSpace.Count,
            "vista_antes": antes, "vista_despues": vista()}


def main():
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
        return {"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto con un dibujo activo."}
    try:
        return zoom_extents(app, doc)
    except Exception as e:
        return {"ok": False, "error": "fallo_zoom", "detalle": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, default=str))
