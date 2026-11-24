"""Sonda para extraer y minar patrones de diseno arquitectonico en AutoCAD (SOLO LECTURA).

Uso: python -I _probe_patrones.py [destino_contiene]
Imprime un JSON con la coleccion de patrones e intenciones inferidas de los planos terminados.
"""
import json
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -I no incluye rutas; patrones_diseno vive en la raiz
import patrones_diseno

def analizar_dibujo(doc):
    ms = doc.ModelSpace
    total = ms.Count
    
    productos = []
    mobiliario = []
    muros_segmentos = []
    
    for i in range(min(total, 15000)):
        try:
            e = ms.Item(i)
            on = str(e.ObjectName)
            layer = str(e.Layer)
            layer_low = layer.lower()
            
            # 1. Detectar productos de audio o iluminacion colocados (SCH_*, DL-*, etc.)
            if on == "AcDbBlockReference" and ("sch_" in layer_low or "iluminacion" in layer_low or "audio" in layer_low):
                p = e.InsertionPoint
                productos.append({
                    "nombre": str(e.EffectiveName),
                    "x": p[0],
                    "y": p[1],
                    "capa": layer
                })
            # 2. Detectar mobiliario clave
            elif on == "AcDbBlockReference":
                bname = str(e.EffectiveName).lower()
                tipo_mob = None
                if any(k in bname for k in ["lise", "ata11", "mesa", "dining"]):
                    tipo_mob = "mesa_comedor"
                elif any(k in bname for k in ["cama", "bed", "gruppo", "d.847"]):
                    tipo_mob = "cama"
                elif any(k in bname or k in layer_low for k in ["wc", "toilet", "inodoro", "lavamanos", "aparatos"]):
                    tipo_mob = "sanitario"
                elif any(k in bname or k in layer_low for k in ["mastercool", "ovens", "sink", "kitchen", "cocina"]):
                    tipo_mob = "cocina"
                
                if tipo_mob:
                    p = e.InsertionPoint
                    try:
                        bb0, bb1 = e.GetBoundingBox()
                        cx, cy = (bb0[0] + bb1[0]) / 2, (bb0[1] + bb1[1]) / 2
                    except:
                        cx, cy = p[0], p[1]
                    mobiliario.append({
                        "nombre_bloque": str(e.EffectiveName),
                        "tipo": tipo_mob,
                        "cx": cx,
                        "cy": cy
                    })
            # 3. Detectar muros para calcular distancias relativas
            elif on == "AcDbLine" and any(k in layer_low for k in ["wall", "muro", "tabique", "pared", "a-wall"]):
                p1, p2 = e.StartPoint, e.EndPoint
                muros_segmentos.append((p1[0], p1[1], p2[0], p2[1]))
            elif on == "AcDbPolyline" and any(k in layer_low for k in ["wall", "muro", "tabique", "pared", "a-wall"]):
                c = list(e.Coordinates)
                for k in range(0, len(c) - 3, 2):
                    muros_segmentos.append((c[k], c[k+1], c[k+2], c[k+3]))
        except Exception:
            pass
            
    patrones = patrones_diseno.extraer_patrones_desde_elementos(productos, mobiliario, muros_segmentos)
    
    # Resumen agrupado por intencion
    resumen_intenciones = {}
    for p in patrones:
        inte = p["intencion"]
        resumen_intenciones[inte] = resumen_intenciones.get(inte, 0) + 1
        
    return {
        "ok": True,
        "total_productos_analizados": len(productos),
        "total_mobiliario_referencia": len(mobiliario),
        "total_segmentos_muro": len(muros_segmentos),
        "resumen_intenciones": resumen_intenciones,
        "patrones": patrones
    }

def main():
    try:
        import pythoncom
        import win32com.client
    except Exception as e:
        print(json.dumps({"ok": False, "error": "sin_pywin32", "detalle": str(e)}))
        return

    try:
        import win32service, win32con
        hwinsta = win32service.OpenWindowStation('WinSta0', False, win32con.MAXIMUM_ALLOWED)
        hwinsta.SetProcessWindowStation()
        hdesk = win32service.OpenDesktop('Default', 0, False, win32con.MAXIMUM_ALLOWED)
        hdesk.SetThreadDesktop()
    except Exception:
        pass

    pythoncom.CoInitialize()
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        doc = acad.ActiveDocument
        res = analizar_dibujo(doc)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": type(e).__name__, "detalle": str(e)}))
    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    main()
