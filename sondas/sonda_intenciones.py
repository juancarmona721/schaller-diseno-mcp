"""Sonda para ejecutar la ubicacion de productos basada en INTENCIONES DE DISENO en AutoCAD.

Soporta intenciones:
- "audio_comedor_4x": 4 parlantes KEF enfrentados 2 y 2 sobre mesa de comedor.
- "audio_bano_individual": 1 parlante KEF en centro de bano.
- "perimetro_cocina_durastrip": tira LED estanca perimetral IP68 con linetype EWC modular.
- "combo_cama_iluminacion": tira LED en cabecera + 6 spots CCTEvo perimetrales.
- "moon_ambiente": 1 luminaria de suspension Moon 60 centrada en sala/estar.

Argumento (JSON en argv[1]):
{"intencion": s, "zona_x": float, "zona_y": float, "ejecutar": bool}
o para seleccion activa:
{"intencion": s, "usar_seleccion": true, "ejecutar": bool}
"""
import json
import math
import sys
import time

def mk_variant(x, y, z=0.0):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(x), float(y), float(z)))

def mk_doubles(valores):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(float(v) for v in valores))

def asegurar_capa(doc, nombre, color=None):
    try:
        lay = doc.Layers.Item(nombre)
    except:
        lay = doc.Layers.Add(nombre)
    if color is not None:
        try:
            lay.color = int(color)
        except:
            pass
    return lay

def ejecutar_intencion(doc, args):
    intencion = args.get("intencion", "")
    ejecutar = bool(args.get("ejecutar", True))
    ms = doc.ModelSpace
    
    # Resolver punto de referencia (zona_x, zona_y) o seleccion activa
    ref_x = args.get("zona_x")
    ref_y = args.get("zona_y")
    
    if args.get("usar_seleccion") or (ref_x is None and ref_y is None):
        try:
            ss = doc.ActiveSelectionSet
            if ss.Count > 0:
                ent = ss.Item(0)
                try:
                    bb0, bb1 = ent.GetBoundingBox()
                    ref_x = (bb0[0] + bb1[0]) / 2
                    ref_y = (bb0[1] + bb1[1]) / 2
                except:
                    p = getattr(ent, "InsertionPoint", getattr(ent, "Center", None))
                    if p:
                        ref_x, ref_y = p[0], p[1]
        except:
            pass
            
    if ref_x is None or ref_y is None:
        return {"ok": False, "error": "sin_coordenadas", "detalle": "No se indico punto de zona ni habia seleccion activa en AutoCAD."}

    # -------------------------------------------------------------
    # 1. AUDIO COMEDOR (4x parlantes paralelos enfrentados)
    # -------------------------------------------------------------
    if intencion in ("audio_comedor_4x", "audio_comedor"):
        # Buscar mesa cercana al punto
        mesa_cx, mesa_cy = ref_x, ref_y
        for i in range(ms.Count):
            try:
                e = ms.Item(i)
                on = str(e.ObjectName)
                if on == "AcDbCircle":
                    c = e.Center
                    if math.hypot(c[0] - ref_x, c[1] - ref_y) < 2.5:
                        mesa_cx, mesa_cy = c[0], c[1]
                        break
                elif on == "AcDbBlockReference":
                    bname = str(e.EffectiveName).lower()
                    if any(k in bname for k in ["lise", "ata11", "mesa", "dining"]):
                        p = e.InsertionPoint
                        if math.hypot(p[0] - ref_x, p[1] - ref_y) < 2.5:
                            try:
                                bb0, bb1 = e.GetBoundingBox()
                                mesa_cx, mesa_cy = (bb0[0] + bb1[0]) / 2, (bb0[1] + bb1[1]) / 2
                            except:
                                mesa_cx, mesa_cy = p[0], p[1]
                            break
            except:
                pass
                
        # 4 Parlantes en paralelo enfrentados 2 y 2
        offsets = [
            (-0.45,  0.45),
            ( 0.45,  0.45),
            (-0.45, -0.45),
            ( 0.45, -0.45)
        ]
        
        posiciones = [(round(mesa_cx + dx, 3), round(mesa_cy + dy, 3)) for dx, dy in offsets]
        if not ejecutar:
            return {"ok": True, "intencion": intencion, "ensayo": True, "posiciones": posiciones, "producto": "Ci160CRDS_KEF"}
            
        asegurar_capa(doc, "SCH_AUDIO", color=6) # Magenta
        for px, py in posiciones:
            pt = mk_variant(px, py, 0)
            b = ms.InsertBlock(pt, "Ci160CRDS_KEF", 1.0, 1.0, 1.0, 0.0)
            b.Layer = "SCH_AUDIO"
            
            t_pt = mk_variant(px - 0.07, py - 0.16, 0)
            t = ms.AddText("Ci160CRDS", t_pt, 0.035)
            t.Layer = "SCH_AUDIO"
            t.Color = 6
            
        return {"ok": True, "intencion": intencion, "instalados": 4, "centro_mesa": [mesa_cx, mesa_cy], "posiciones": posiciones}

    # -------------------------------------------------------------
    # 2. AUDIO BANO (1x parlante KEF individual)
    # -------------------------------------------------------------
    elif intencion in ("audio_bano_individual", "audio_bano"):
        if not ejecutar:
            return {"ok": True, "intencion": intencion, "ensayo": True, "posicion": [ref_x, ref_y], "producto": "Ci160CRDS_KEF"}
            
        asegurar_capa(doc, "SCH_AUDIO", color=6)
        pt = mk_variant(ref_x, ref_y, 0)
        b = ms.InsertBlock(pt, "Ci160CRDS_KEF", 1.0, 1.0, 1.0, 0.0)
        b.Layer = "SCH_AUDIO"
        
        t_pt = mk_variant(ref_x - 0.07, ref_y - 0.16, 0)
        t = ms.AddText("Ci160CRDS", t_pt, 0.035)
        t.Layer = "SCH_AUDIO"
        t.Color = 6
        return {"ok": True, "intencion": intencion, "instalados": 1, "posicion": [ref_x, ref_y]}

    # -------------------------------------------------------------
    # 3. MOON 60 (1x luminaria suspension ambiental)
    # -------------------------------------------------------------
    elif intencion in ("moon_ambiente", "moon_60"):
        if not ejecutar:
            return {"ok": True, "intencion": intencion, "ensayo": True, "posicion": [ref_x, ref_y], "producto": "Moon_60_Davide Groppi"}
            
        asegurar_capa(doc, "SCH_ILUMINACION", color=4) # Cyan
        pt = mk_variant(ref_x, ref_y, 0)
        b = ms.InsertBlock(pt, "Moon_60_Davide Groppi", 1.0, 1.0, 1.0, 0.0)
        b.Layer = "SCH_ILUMINACION"
        return {"ok": True, "intencion": intencion, "instalados": 1, "posicion": [ref_x, ref_y]}

    # -------------------------------------------------------------
    # 4. PERIMETRO COCINA (Durastrip IP68 modular EWC)
    # -------------------------------------------------------------
    elif intencion in ("perimetro_cocina_durastrip", "durastrip_ip68"):
        ancho = float(args.get("ancho", 8.0))
        alto = float(args.get("alto", 4.4))
        x0, y0 = ref_x - ancho / 2, ref_y - alto / 2
        x1, y1 = ref_x + ancho / 2, ref_y + alto / 2
        
        pts = [x0, y0, x1, y0, x1, y1, x0, y1]
        if not ejecutar:
            return {"ok": True, "intencion": intencion, "ensayo": True, "bounds": [x0, y0, x1, y1], "producto": "Durastrip IP68_45W_Targetti"}
            
        asegurar_capa(doc, "SCH_ILUMINACION", color=5) # Azul
        pl = ms.AddLightWeightPolyline(mk_doubles(pts))
        pl.Closed = True
        pl.Layer = "SCH_ILUMINACION"
        try:
            pl.Linetype = "EWC"
            pl.LinetypeScale = 0.5
            pl.ConstantWidth = 0.04
        except Exception:
            pass
            
        t_pt = mk_variant(x0 + 0.2, y1 + 0.1, 0)
        t = ms.AddText("Durastrip IP68-45W", t_pt, 0.12)
        t.Layer = "SCH_ILUMINACION"
        t.Color = 5
        return {"ok": True, "intencion": intencion, "instalados": 1, "bounds": [x0, y0, x1, y1]}

    return {"ok": False, "error": "intencion_no_reconocida", "detalle": f"Intencion '{intencion}' no soportada."}

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "sin_argumentos"}))
        return
    args = json.loads(sys.argv[1])

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
        res = ejecutar_intencion(doc, args)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": type(e).__name__, "detalle": str(e)}))
    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    main()
