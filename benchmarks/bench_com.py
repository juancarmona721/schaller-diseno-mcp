"""Medicion de costos COM en un dibujo temporal (se cierra sin guardar). Solo mide; no usa el MCP ni toca otros dibujos."""
import json
import threading
import time

res = {}


def reint(f, n=10):
    for i in range(n):
        try:
            return f()
        except Exception:
            if i == n - 1:
                raise
            time.sleep(1.0)


def run():
    import win32service, win32con, pythoncom, win32com.client
    try:
        hw = win32service.OpenWindowStation("WinSta0", False, win32con.MAXIMUM_ALLOWED); hw.SetProcessWindowStation()
        hd = win32service.OpenDesktop("Default", 0, False, win32con.MAXIMUM_ALLOWED); hd.SetThreadDesktop()
    except Exception:
        pass
    pythoncom.CoInitialize()
    V = win32com.client.VARIANT
    P = lambda x, y: V(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(x), float(y), 0.0])
    D = lambda v: V(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(a) for a in v])
    acad = win32com.client.GetActiveObject("AutoCAD.Application")
    temp = None
    previo = None
    try:
        previo = reint(lambda: acad.ActiveDocument.Name)
        res["autocad_version"] = str(acad.Version)
        antes = {d.Name for d in acad.Documents}
        reint(lambda: acad.Documents.Add()); time.sleep(3)
        temp = reint(lambda: acad.ActiveDocument)       # el documento nuevo queda activo; no se identifica por nombre (AutoCAD puede repetir Drawing5)
        reint(lambda: temp.Activate()); time.sleep(1)
        temp.SetVariable("INSUNITS", 6)
        ms = temp.ModelSpace
        b = temp.Blocks.Add(P(0, 0), "BLK")
        b.AddLightWeightPolyline(D([0, 0, .3, 0, .3, .3, 0, .3])).Closed = True
        b.AddCircle(P(.15, .15), .1)
        temp.Layers.Add("SCH_T")
        temp.RegisteredApplications.Add("SCHALLER")
        tipos = V(pythoncom.VT_ARRAY | pythoncom.VT_I2, [1001, 1000, 1070])

        def insertar(n, y0, con_xdata, con_handle=True):
            t = time.perf_counter()
            hs = []
            for i in range(n):
                ref = ms.InsertBlock(P((i % 50) * 1.0, y0 + (i // 50) * 1.0), "BLK", 1, 1, 1, 0.0)
                ref.Layer = "SCH_T"
                a, c = ref.GetBoundingBox()
                _ = float(a[0]), float(c[0])
                hs.append(str(ref.Handle))
                if con_xdata:
                    ref.SetXData(tipos, V(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, ["SCHALLER", "op_0001", i]))
            return (time.perf_counter() - t) * 1000, hs

        res["insercion_ms"] = {}
        y = 10
        todos = {}
        for n in (15, 200, 400):
            base, hs0 = insertar(n, y, False); y += 20
            xd, hs1 = insertar(n, y, True); y += 20
            todos[n] = hs1
            res["insercion_ms"][str(n)] = {"como_hoy": round(base), "con_xdata": round(xd), "extra_xdata_por_entidad": round((xd - base) / n, 2),
                                           "por_entidad_hoy": round(base / n, 2)}
        # lectura por handle (revalidacion de anfitriones)
        hs = todos[200][:20]
        t = time.perf_counter()
        for h in hs:
            o = temp.HandleToObject(h)
            _ = o.Rotation, o.InsertionPoint, o.XScaleFactor, o.EffectiveName
        res["revalidar_20_anfitriones_ms"] = round((time.perf_counter() - t) * 1000, 1)
        # GetXData
        try:
            o = temp.HandleToObject(hs[0])
            t = time.perf_counter()
            xt, xv = o.GetXData("SCHALLER")
            res["getxdata_ms"] = round((time.perf_counter() - t) * 1000, 2)
            res["getxdata_valor"] = [str(v) for v in xv]
        except Exception as e:
            res["getxdata_error"] = str(e)[:100]
        # seleccion filtrada por XData
        try:
            ft = V(pythoncom.VT_ARRAY | pythoncom.VT_I2, [1001])
            fd = V(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, ["SCHALLER"])
            try:
                temp.SelectionSets.Item("SS_B").Delete()
            except Exception:
                pass
            ss = temp.SelectionSets.Add("SS_B")
            t = time.perf_counter()
            ss.Select(5, None, None, ft, fd)
            res["seleccion_por_xdata"] = {"encontradas": ss.Count, "esperadas": 15 + 200 + 400, "ms": round((time.perf_counter() - t) * 1000, 1)}
            ss.Delete()
        except Exception as e:
            res["seleccion_xdata_error"] = str(e)[:100]
        # seleccion por cruce: capas apagadas / congeladas / bloqueadas y fuera del zoom
        try:
            for nom in ("L_ON", "L_OFF", "L_FRZ", "L_LCK"):
                temp.Layers.Add(nom)
            temp.Layers.Item("L_OFF").LayerOn = False
            temp.Layers.Item("L_FRZ").Freeze = True
            temp.Layers.Item("L_LCK").Lock = True
            for nom in ("L_ON", "L_OFF", "L_FRZ", "L_LCK"):
                ln = ms.AddLine(P(500, 500), P(505, 500))
                ln.Layer = nom
            lejos = ms.AddLine(P(100000, 100000), P(100005, 100000))
            lejos.Layer = "L_ON"
            try:
                acad.ZoomWindow(P(0, 0), P(10, 10))
            except Exception:
                pass

            def contar(modo, p1, p2):
                try:
                    temp.SelectionSets.Item("SS_C").Delete()
                except Exception:
                    pass
                s = temp.SelectionSets.Add("SS_C")
                s.Select(modo, p1, p2) if p1 is not None else s.Select(modo)
                capas = sorted(str(s.Item(i).Layer) for i in range(s.Count))
                s.Delete()
                return capas

            res["cruce_fuera_del_zoom"] = contar(1, P(499, 499), P(506, 501))
            res["cruce_lejano"] = contar(1, P(99999, 99999), P(100006, 100001))
            res["todo_en_la_zona_500"] = [c for c in contar(5, None, None) if c.startswith("L_")]
        except Exception as e:
            res["cruce_error"] = str(e)[:120]
        # marcas de deshacer
        try:
            temp.StartUndoMark(); temp.EndUndoMark()
            res["undo_mark"] = "disponible"
        except Exception as e:
            res["undo_mark"] = "no: " + str(e)[:60]
    except Exception as e:
        res["EXCEPCION"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            if temp is not None:
                reint(lambda: temp.Close(False))
        except Exception as e:
            res["cierre"] = str(e)[:60]
        try:
            for d in acad.Documents:
                if d.Name == previo and d.FullName != '':
                    reint(lambda d=d: d.Activate()); break
        except Exception:
            pass
        try:
            res["dibujos_al_final"] = reint(lambda: [d.Name for d in acad.Documents])
        except Exception:
            pass


t = threading.Thread(target=run); t.start(); t.join()
print(json.dumps(res, ensure_ascii=True, indent=1))
