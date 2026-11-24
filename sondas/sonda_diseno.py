"""Sonda de DISENO por anfitrion: lee el contexto (anfitrion, muros, lo ya colocado) y inserta las colocaciones calculadas.

Argumento (JSON en argv[1]):
  {"op": "anfitriones", "filtro": s|null, "cerca_de": [x,y]|null, "radio": n, "limite": n}
  {"op": "contexto", "anfitrion": s|null, "usar_seleccion": bool, "cerca_de": [x,y]|null, "radio_muros": n,
   "bloques_bbox": [nombres con ancla bbox]}
  {"op": "insertar", "colocaciones": [...], "ejecutar": bool, "confirmacion": s|null, "max_objetos": n}
Solo AGREGA (capas, bloques importados de la biblioteca, inserciones, rotulos). Nunca borra ni mueve lo existente
(solo mueve el bloque que ella misma acaba de insertar, para centrar su geometria). El candado de planos grandes es el mismo
de sonda_escribir.
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I no incluye la carpeta del script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ni la raiz del proyecto

import motor_ubicacion  # noqa: E402

CAPAS_SCH = ("SCH_ILUMINACION", "SCH_AUDIO")
FILTRO_MUROS = "*MURO*,*WALL*,*TABIQUE*,*PARED*"
MAX_SEGMENTOS = 3000
DESVIACION_AVISO = 0.75       # m: un bloque cuyo dibujo queda mas lejos que esto de su punto de insercion esta "desplazado"


def _rechazada(ex) -> bool:
    t = str(ex).lower()
    return "-2147418111" in t or "rechazada" in t or "rejected" in t


def reintentar(fn, intentos=10, espera=1.0):
    """AutoCAD responde 'llamada rechazada' si esta ocupado (comando activo, regenerando...): se espera y se reintenta."""
    for i in range(intentos):
        try:
            return fn()
        except Exception as ex:
            if not _rechazada(ex) or i == intentos - 1:
                raise
            time.sleep(espera)


def pt(x, y, z=0.0):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(x), float(y), float(z)))


def _filtro(tipos_dxf, valores):
    import pythoncom
    from win32com.client import VARIANT
    return (VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_I2, tuple(tipos_dxf)),
            VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, tuple(valores)))


def _conjunto(doc, nombre, modo, p1, p2, tipos, valores):
    """Conjunto de seleccion temporal (se borra al terminar). modo 5 = todo el dibujo, 1 = cruzando la ventana p1-p2."""
    try:
        doc.SelectionSets.Item(nombre).Delete()
    except Exception:
        pass
    ss = doc.SelectionSets.Add(nombre)
    ft, fd = _filtro(tipos, valores)
    if modo == 5:
        ss.Select(5, None, None, ft, fd)
    else:
        ss.Select(modo, p1, p2, ft, fd)
    return ss


def _bbox(e):
    a, b = e.GetBoundingBox()
    return float(a[0]), float(a[1]), float(b[0]), float(b[1])


def _host_dict(e):
    x0, y0, x1, y1 = _bbox(e)
    return {"nombre": str(e.EffectiveName), "capa": str(e.Layer), "x0": round(x0, 3), "y0": round(y0, 3),
            "x1": round(x1, 3), "y1": round(y1, 3), "w": round(x1 - x0, 3), "h": round(y1 - y0, 3),
            "rotacion_grados": round(math.degrees(float(e.Rotation)), 2), "handle": str(e.Handle)}


def _inserts(doc):
    """Todos los INSERT del modelo (rapido, filtro nativo). Devuelve (conjunto, lista de entidades)."""
    ss = _conjunto(doc, "SS_DISENO_INS", 5, None, None, [0], ["INSERT"])
    return ss, [ss.Item(i) for i in range(ss.Count)]


def op_anfitriones(doc, args):
    filtro = (args.get("filtro") or "").lower()
    centro = args.get("cerca_de")
    radio = float(args.get("radio") or 15.0)
    limite = int(args.get("limite") or 40)
    ss, ents = _inserts(doc)
    res = []
    try:
        for e in ents:
            try:
                if str(e.Layer) in CAPAS_SCH:
                    continue
                h = _host_dict(e)
            except Exception:
                continue
            if filtro and filtro not in h["nombre"].lower() and filtro not in h["capa"].lower():
                continue
            if abs(h["x1"] - h["x0"]) > 500 or abs(h["y1"] - h["y0"]) > 500:
                continue                                    # definiciones lejanas / basura
            if centro:
                cx, cy = (h["x0"] + h["x1"]) / 2, (h["y0"] + h["y1"]) / 2
                h["distancia"] = round(math.hypot(cx - centro[0], cy - centro[1]), 2)
                if h["distancia"] > radio:
                    continue
            res.append(h)
    finally:
        ss.Delete()
    res.sort(key=lambda h: h.get("distancia", 0))
    return {"ok": True, "total": len(res), "anfitriones": res[:limite]}


def _resolver_anfitrion(doc, args):
    """(entidad, None) o (None, error)."""
    if args.get("usar_seleccion"):
        try:
            sel = doc.ActiveSelectionSet
            for i in range(sel.Count):
                e = sel.Item(i)
                if str(e.ObjectName) == "AcDbBlockReference":
                    return e, None
        except Exception:
            pass
        return None, {"ok": False, "error": "sin_seleccion", "detalle": "No hay un bloque (cama, mesa, isla...) seleccionado en AutoCAD. Selecciona el mueble y repite."}
    nombre = (args.get("anfitrion") or "").strip().lower()
    if not nombre:
        return None, {"ok": False, "error": "falta_anfitrion", "detalle": "Indica el nombre del bloque anfitrion, usar_seleccion=true, o cerca_de."}
    ss, ents = _inserts(doc)
    try:
        cand = []
        for e in ents:
            try:
                if str(e.EffectiveName).lower() == nombre and str(e.Layer) not in CAPAS_SCH:
                    cand.append(e)
            except Exception:
                pass
        centro = args.get("cerca_de")
        if not cand:
            return None, {"ok": False, "error": "anfitrion_no_encontrado", "detalle": f"No hay ningun bloque llamado '{args.get('anfitrion')}'. Usa listar_anfitriones."}
        if len(cand) > 1:
            if not centro:
                return None, {"ok": False, "error": "anfitrion_ambiguo",
                              "detalle": f"Hay {len(cand)} bloques '{args.get('anfitrion')}'. Repite con cerca_de=[x, y] o usar_seleccion.",
                              "candidatos": [_host_dict(c) for c in cand[:8]]}
            cand.sort(key=lambda c: math.hypot((_bbox(c)[0] + _bbox(c)[2]) / 2 - centro[0], (_bbox(c)[1] + _bbox(c)[3]) / 2 - centro[1]))
        return cand[0], None
    finally:
        ss.Delete()


def _segmentos(e):
    """Segmentos (x1,y1,x2,y2) de una linea o polilinea."""
    on = str(e.ObjectName)
    if on == "AcDbLine":
        a, b = e.StartPoint, e.EndPoint
        return [(a[0], a[1], b[0], b[1])]
    try:
        c = list(e.Coordinates)
    except Exception:
        return []
    paso = 3 if on in ("AcDb2dPolyline", "AcDb3dPolyline") else 2
    pts = [(c[i], c[i + 1]) for i in range(0, len(c) - paso + 1, paso)]
    segs = [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(len(pts) - 1)]
    try:
        if getattr(e, "Closed", False) and len(pts) > 2:
            segs.append((pts[-1][0], pts[-1][1], pts[0][0], pts[0][1]))
    except Exception:
        pass
    return segs


def op_contexto(doc, args):
    host_ent, err = _resolver_anfitrion(doc, args)
    if err:
        return err
    host = _host_dict(host_ent)
    r = float(args.get("radio_muros") or 8.0)
    muros = []
    # OJO: la seleccion por ventana de AutoCAD solo ve lo que esta en la VISTA ACTUAL (da 0 si el muro esta fuera de pantalla).
    # Por eso: seleccion global con filtro nativo de tipo+capa (rapida) y recorte por distancia aqui.
    ss = _conjunto(doc, "SS_DISENO_MUR", 5, None, None, [0, 8], ["LINE,LWPOLYLINE,POLYLINE", FILTRO_MUROS])
    vx0, vy0, vx1, vy1 = host["x0"] - r, host["y0"] - r, host["x1"] + r, host["y1"] + r
    try:
        for i in range(ss.Count):
            if len(muros) >= MAX_SEGMENTOS:
                break
            try:
                e = ss.Item(i)
                a = _bbox(e)
                if a[2] < vx0 or a[0] > vx1 or a[3] < vy0 or a[1] > vy1:
                    continue
                muros += [[round(v, 4) for v in s] for s in _segmentos(e)]
            except Exception:
                pass
    finally:
        ss.Delete()
    bbox_blk = set(args.get("bloques_bbox") or [])
    existentes = []
    ss, ents = _inserts(doc)
    try:
        for e in ents:
            try:
                if str(e.Layer) not in CAPAS_SCH:
                    continue
                n = str(e.EffectiveName)
                if n in bbox_blk:
                    a = _bbox(e)
                    x, y = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
                else:
                    p = e.InsertionPoint
                    x, y = p[0], p[1]
                existentes.append({"bloque": n, "x": round(x, 3), "y": round(y, 3)})
            except Exception:
                pass
    finally:
        ss.Delete()
    return {"ok": True, "anfitrion": host, "muros": muros[:MAX_SEGMENTOS], "n_muros": len(muros), "existentes": existentes,
            "objetos_en_modelo": int(doc.ModelSpace.Count)}


def _copiar_definicion(origen, destino, nombre):
    """Crea `nombre` en destino (mismo punto base) y le copia las entidades de la definicion de origen. Tal cual, sin reescalar."""
    import pythoncom
    from win32com.client import VARIANT
    src = origen.Blocks.Item(nombre)
    nb = destino.Blocks.Add(pt(*tuple(src.Origin)[:2]), nombre)
    try:
        ents = [e for e in src]
        arr = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, tuple(ents))
        try:
            origen.CopyObjects(arr, nb)
        except Exception:      # algunas versiones exigen el 3er argumento (IDPairs) por referencia
            origen.CopyObjects(arr, nb, VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None))
    except Exception:
        try:
            nb.Delete()        # solo la definicion vacia que se acaba de crear aqui
        except Exception:
            pass
        raise


def _asegurar_bloques(acad, doc, nombres):
    """Importa los bloques que falten: primero de bloques_schaller.dwg, luego de otro dibujo abierto. (faltan, origenes, errores)."""
    from sonda_escribir import existe
    faltan = [n for n in nombres if not existe(doc.Blocks, n)]
    origenes, errores = {}, {}
    otros = [d for d in acad.Documents if d.Name != doc.Name]
    otros.sort(key=lambda d: 0 if "bloques_schaller" in d.Name.lower() else 1)     # la biblioteca primero
    for n in list(faltan):
        for d in otros:
            if not existe(d.Blocks, n):
                continue
            try:
                _copiar_definicion(d, doc, n)
                origenes[n] = "biblioteca" if "bloques_schaller" in d.Name.lower() else "otro_dibujo_abierto"
                break
            except Exception as e:
                errores[n] = f"{type(e).__name__}: {e}"
    for n in [n for n in faltan if not existe(doc.Blocks, n)]:       # ultimo recurso: definicion interna del MCP
        d = motor_ubicacion.DEFINICIONES_INTERNAS.get(n)
        if not d:
            continue
        try:
            nb = doc.Blocks.Add(pt(0, 0), n)
            for dx, dy, r in d["circulos"]:
                nb.AddCircle(pt(dx, dy), r)
            origenes[n] = "definicion_interna"
        except Exception as e:
            errores[n] = f"{type(e).__name__}: {e}"
    return [n for n in faltan if not existe(doc.Blocks, n)], origenes, errores


UNIDAD_A_METROS = {1: 0.0254, 2: 0.3048, 3: 1609.344, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 8: 1e-9, 9: 2.54e-8, 10: 0.9144,
                   11: 1e-10, 12: 1e-9, 13: 1e-6, 14: 0.1, 15: 10.0, 16: 100.0}


def unidad_plano_m(doc):
    """(metros por unidad de dibujo, aviso|None). INSUNITS 0 (sin unidad) se trata como metros con aviso."""
    try:
        u = int(doc.GetVariable("INSUNITS"))
    except Exception:
        u = 0
    if u in UNIDAD_A_METROS:
        return UNIDAD_A_METROS[u], None
    return 1.0, "El dibujo no tiene unidades (INSUNITS=0): se asumen metros. Revisa el tamano de lo insertado."


def op_insertar(acad, doc, args):
    from sonda_escribir import candado, existe
    cols = args.get("colocaciones") or []
    ejecutar = bool(args.get("ejecutar"))
    total = int(doc.ModelSpace.Count)
    if (bloqueo := candado(doc, args, total, ejecutar)):
        return bloqueo
    nombres = sorted({c["bloque"] for c in cols})
    faltan = [n for n in nombres if not existe(doc.Blocks, n)]
    origenes, errores = {}, {}
    if ejecutar:
        faltan, origenes, errores = _asegurar_bloques(acad, doc, nombres)
    elif faltan:
        # ensayo: dice si se podrian importar de algun dibujo abierto
        otros = [d for d in acad.Documents if d.Name != doc.Name]
        faltan = [n for n in faltan if not any(existe(d.Blocks, n) for d in otros) and n not in motor_ubicacion.DEFINICIONES_INTERNAS]
    if faltan:
        return {"ok": False, "error": "bloques_no_disponibles", "faltan": faltan, "errores_importacion": errores,
                "detalle": "Esos bloques no estan en el plano ni en bloques_schaller.dwg (debe estar abierto) ni en otro dibujo abierto. "
                           "No se inserto nada (todo o nada)."}
    if not ejecutar:
        return {"ok": True, "ejecutado": False, "colocaciones": len(cols), "objetos_en_modelo": total}
    for capa, color in (("SCH_ILUMINACION", 4), ("SCH_AUDIO", 6)):
        if not existe(doc.Layers, capa):
            doc.Layers.Add(capa).color = color
    ms = doc.ModelSpace
    handles, avisos, desv_max = [], [], 0.0
    unidad_m, aviso_u = unidad_plano_m(doc)
    if aviso_u:
        avisos.append(aviso_u)
    escalas = {}    # bloque -> (escala, como). La primera copia de cada bloque se inserta a 1 y se MIDE: lo que se ve es lo que cuenta.
    for c in cols:
        nombre = c["bloque"]
        e = escalas[nombre][0] if nombre in escalas else 1.0
        ref = ms.InsertBlock(pt(c["x"], c["y"]), nombre, e, e, e, float(c["rot"]))
        ref.Layer = c["capa"]
        if nombre not in escalas:
            a0 = _bbox(ref)
            esc, como = motor_ubicacion.escala_por_medida(max(a0[2] - a0[0], a0[3] - a0[1]), c.get("tam_m"), unidad_m, float(c["escala"]))
            if esc != 1.0:
                ref.XScaleFactor = esc
                ref.YScaleFactor = esc
                ref.ZScaleFactor = esc
            escalas[nombre] = (esc, como)
            e = esc
        a = _bbox(ref)
        cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
        desv = math.hypot(cx - c["x"], cy - c["y"])
        if c.get("ancla") == "bbox":
            ref.Move(pt(cx, cy), pt(c["x"], c["y"]))      # el dibujo queda centrado en el punto pedido
        elif desv * unidad_m > DESVIACION_AVISO:
            avisos.append(f"{c['bloque']}: su dibujo queda a {desv * unidad_m:.2f} m del punto de insercion (punto base lejano). "
                          "Revisa; si es esperado, marca ancla 'bbox' en el catalogo.")
        real = max(a[2] - a[0], a[3] - a[1]) * unidad_m           # tamano real en metros, tras insertar
        if c.get("tam_m") and not 0.6 <= real / c["tam_m"] <= 1.7:
            avisos.append(f"{c['bloque']}: mide {real:.3g} m y se esperaban ~{c['tam_m']} m (escala {e:g}, {escalas[c['bloque']][1]}). Revisa en pantalla.")
        if c.get("ancla") != "bbox":
            desv_max = max(desv_max, desv * unidad_m)
        handles.append(str(ref.Handle))
        et = c.get("etiqueta")
        if et:
            t = ms.AddText(et["texto"], pt(et["x"], et["y"]), float(et["altura"]))
            t.Layer = et["capa"]
            t.Color = int(et["color"])
            handles.append(str(t.Handle))
    return {"ok": True, "ejecutado": True, "insertados": len(cols), "handles": handles, "avisos": avisos,
            "bloques_importados": origenes, "escalas_aplicadas": {k: v[0] for k, v in escalas.items()},
            "desviacion_max_m": round(desv_max, 3), "objetos_en_modelo": total}


def op_quitar(doc, args):
    """BORRA solo lo que colocamos: entidades de las capas SCH_ILUMINACION y SCH_AUDIO (nunca otras capas, nunca las capas en si)."""
    import collections
    from sonda_escribir import candado
    ejecutar = bool(args.get("ejecutar"))
    total = int(doc.ModelSpace.Count)
    if (bloqueo := candado(doc, args, total, ejecutar)):
        return bloqueo
    ss = _conjunto(doc, "SS_DISENO_QUITAR", 5, None, None, [8], [",".join(CAPAS_SCH)])
    try:
        ents = [ss.Item(i) for i in range(ss.Count)]
        cuenta = collections.Counter()
        for e in ents:
            try:
                nombre = str(e.EffectiveName) if str(e.ObjectName) == "AcDbBlockReference" else str(e.ObjectName)
                cuenta[f"{nombre} ({e.Layer})"] += 1
            except Exception:
                pass
        resumen = dict(sorted(cuenta.items()))
        if not ejecutar:
            return {"ok": True, "ejecutado": False, "a_borrar": len(ents), "detalle": resumen, "objetos_en_modelo": total}
        borrados, fallos = 0, 0
        for e in ents:
            try:
                if str(e.Layer) not in CAPAS_SCH:            # ultima barrera: jamas una capa del proyecto
                    continue
                e.Delete()
                borrados += 1
            except Exception:
                fallos += 1
    finally:
        ss.Delete()
    ss2 = _conjunto(doc, "SS_DISENO_QUITAR", 5, None, None, [8], [",".join(CAPAS_SCH)])
    try:
        quedan = int(ss2.Count)
    finally:
        ss2.Delete()
    return {"ok": fallos == 0 and quedan == 0, "ejecutado": True, "borrados": borrados, "fallos": fallos, "quedan_en_capas_sch": quedan,
            "detalle": resumen, "objetos_en_modelo_antes": total, "objetos_en_modelo_ahora": int(doc.ModelSpace.Count),
            "aviso": "Ctrl+Z en AutoCAD deshace el borrado si fue un error."}


def main():
    args = json.loads(sys.argv[1])
    try:
        import win32service, win32con
        hw = win32service.OpenWindowStation("WinSta0", False, win32con.MAXIMUM_ALLOWED)
        hw.SetProcessWindowStation()
        hd = win32service.OpenDesktop("Default", 0, False, win32con.MAXIMUM_ALLOWED)
        hd.SetThreadDesktop()
    except Exception:
        pass
    try:
        import pythoncom
        import win32com.client
    except Exception as e:
        return {"ok": False, "error": "sin_pywin32", "detalle": str(e)}
    pythoncom.CoInitialize()
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        doc = reintentar(lambda: acad.ActiveDocument)
        reintentar(lambda: doc.ModelSpace.Count)
    except Exception:
        return {"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto con un dibujo activo."}
    try:
        op = args.get("op")
        if op == "anfitriones":
            return reintentar(lambda: op_anfitriones(doc, args))     # lecturas: se pueden repetir sin riesgo
        if op == "contexto":
            return reintentar(lambda: op_contexto(doc, args))
        if op == "insertar":
            return op_insertar(acad, doc, args)
        if op == "quitar":
            return op_quitar(doc, args)
        return {"ok": False, "error": "op_desconocida", "detalle": str(op)}
    except Exception as e:
        return {"ok": False, "error": "fallo_diseno", "detalle": f"{type(e).__name__}: {e}",
                "aviso": "Si era una insercion, revisa el dibujo: puede haber quedado algo a medias (Ctrl+Z lo deshace)."}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=True, default=str))
