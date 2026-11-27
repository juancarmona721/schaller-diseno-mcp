"""Sonda de ESCRITURA acotada: solo AGREGA (definiciones de bloque, capas, inserciones). Proceso aparte.

Nunca borra, mueve ni cambia objetos existentes; no usa AutoLISP; no guarda ni cierra el dibujo.
Argumento (JSON en argv[1]):
  {"op": "crear_bloque", "nombres": [...], "tamano": n, "ejecutar": bool, "max_objetos": n}
  {"op": "insertar", "nombre": s, "capa": s, "puntos": [[x, y], ...], "rotacion_grados": n, "ejecutar": bool, "max_objetos": n}
Con "ejecutar": false solo revisa y dice que haria (no modifica nada).
"""
import json
import math
import sys


def mk_variant(x, y, z=0.0):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(x), float(y), float(z)))


def capas_de(doc, intentos: int = 6, pausa_s: float = 0.4):
    """doc.Layers con reintentos: si AutoCAD esta ocupado un instante, el atributo no se resuelve ('<unknown>.Layers') y el primer intento falla."""
    import time
    for i in range(intentos):
        try:
            return doc.Layers
        except Exception:
            if i == intentos - 1:
                raise
            time.sleep(pausa_s)


def existe(coleccion, nombre) -> bool:
    try:
        coleccion.Item(nombre)
        return True
    except Exception:
        return False


def ancho_de_bloque(bloque):
    """Ancho (eje X local) de la geometria de una definicion, sin contar textos ni atributos. None si no se puede medir."""
    xs = []
    for e in bloque:
        if str(getattr(e, "ObjectName", "")) in ("AcDbText", "AcDbMText", "AcDbAttributeDefinition"):
            continue
        try:
            a, z = e.GetBoundingBox()
            xs += [a[0], z[0]]
        except Exception:
            pass
    return (max(xs) - min(xs)) if xs and max(xs) > min(xs) else None


def escala_del_grupo(doc, g):
    """(escala_x, escala_y, error). `largo` = largo deseado sobre el eje X del bloque (se estira el bloque, su nombre no cambia)."""
    ex, ey = float(g.get("escala_x") or 1.0), float(g.get("escala_y") or 1.0)
    if g.get("largo"):
        ancho = ancho_de_bloque(doc.Blocks.Item(g["nombre"]))
        if not ancho:
            return None, None, f"No pude medir el ancho del bloque '{g['nombre']}' para adaptarlo a un largo."
        ex = float(g["largo"]) / ancho
    return ex, ey, None


def _insertar_grupo(doc, g, ejecutar, mk):
    """Inserta copias de un bloque en [[x, y, rotacion_grados], ...] sobre una capa. Solo agrega.

    Opcional: g["largo"] (estira en X hasta ese largo), o g["escala_x"] / g["escala_y"].
    """
    capa_existia = existe(capas_de(doc), g["capa"])
    ex, ey, err = escala_del_grupo(doc, g)
    if err:
        return {"capa_existia": capa_existia, "cantidad": 0, "error_escala": err}
    res = {"capa_existia": capa_existia, "cantidad": len(g["puntos"])}
    if ex != 1.0 or ey != 1.0:
        res["escala"] = [round(ex, 4), round(ey, 4)]
    if not ejecutar:
        return res
    if not capa_existia:
        capas_de(doc).Add(g["capa"])
    handles = []
    for x, y, rot in g["puntos"]:
        ref = doc.ModelSpace.InsertBlock(mk(float(x), float(y), 0), g["nombre"], ex, ey, ex, math.radians(float(rot)))
        ref.Layer = g["capa"]
        handles.append(ref.Handle)
    return {**res, "handles": handles}


def codigo_dibujo(doc) -> str:
    """4 caracteres fijos por dibujo (de su ruta). Se muestra SOLO en la linea de comandos de AutoCAD, no en el chat."""
    import hashlib
    try:
        clave = str(doc.FullName or doc.Name)
    except Exception:
        clave = str(getattr(doc, "Name", "?"))
    return hashlib.sha1(clave.casefold().encode("utf-8")).hexdigest()[:4].upper()


def normalizar_codigo(dado, esperado: str) -> str:
    """El codigo llega de un asistente que puede enviarlo como NUMERO (3457), con comillas, con espacios, en minusculas o como 3457.0, y un numero pierde
    los ceros iniciales (0457 -> 457). Se normaliza todo eso: la seguridad esta en que el codigo solo se ve en AutoCAD, no en como se escribe."""
    import re
    t = str(dado if dado is not None else "").strip().strip("\"'`").strip().upper()
    if re.fullmatch(r"\d+\.0+", t):
        t = t.split(".")[0]
    if t.isdigit() and esperado.isdigit():
        t = t.zfill(len(esperado))
    return t


def candado(doc, args, total, ejecutar):
    """Candado de dibujos grandes (planos reales). None = puede seguir; si no, el dict de error.

    El ensayo siempre vale. Para ESCRIBIR en un dibujo con mas de max_objetos objetos hace falta `confirmacion` = el codigo
    que este programa escribe en la linea de comandos de AutoCAD: lo ve la persona frente a la pantalla, no el chat.
    """
    if total <= int(args.get("max_objetos", 300)):
        return None
    codigo = codigo_dibujo(doc)
    try:
        doc.Utility.Prompt(f"\ndiseno-mcp: codigo de confirmacion para escribir en ESTE dibujo: {codigo}\n")
    except Exception:
        pass
    if not ejecutar or normalizar_codigo(args.get("confirmacion"), codigo) == codigo:
        return None
    return {"ok": False, "error": "dibujo_grande_requiere_confirmacion", "objetos_en_modelo": total,
            "detalle": f"El dibujo activo tiene {total} objetos (plano grande). No se escribio nada. Para escribir, la persona "
                       "debe leer el codigo de confirmacion en la linea de comandos de AutoCAD y pasarlo como `confirmacion`."}


def ejecutar_op(doc, args, mk=mk_variant, mkd=None):
    mkd = mkd or mk_doubles
    op, ejecutar = args.get("op"), bool(args.get("ejecutar"))
    total = doc.ModelSpace.Count
    if (bloqueo := candado(doc, args, total, ejecutar)):
        return bloqueo
    base = {"ok": True, "ejecutado": ejecutar, "objetos_en_modelo": total,
            "dibujo_grande": total > int(args.get("max_objetos", 300))}
    if op == "crear_bloque":
        tam = float(args["tamano"])
        resultados = {}
        for nombre in args["nombres"]:
            if existe(doc.Blocks, nombre):
                resultados[nombre] = "ya_existia (no se toca)"
            elif not ejecutar:
                resultados[nombre] = "se_crearia"
            else:
                blk = doc.Blocks.Add(mk(0, 0, 0), nombre)
                blk.AddCircle(mk(0, 0, 0), tam / 2)
                blk.AddText(nombre, mk(-tam * 0.4, -tam / 8, 0), tam / 4)
                resultados[nombre] = "creado"
        return {**base, "bloques": resultados, "forma": f"circulo de diametro {tam:g} con el nombre del bloque (simbolo PROVISIONAL)"}
    if op == "insertar":
        nombre, capa = args["nombre"], args["capa"]
        if not existe(doc.Blocks, nombre):
            return {"ok": False, "error": "bloque_no_existe",
                    "detalle": f"El bloque '{nombre}' no existe en este dibujo. Crealo primero con crear_bloque_producto."}
        rot = float(args.get("rotacion_grados", 0))
        g = {"nombre": nombre, "capa": capa, "puntos": [[x, y, rot] for x, y in args["puntos"]]}
        res = _insertar_grupo(doc, g, ejecutar, mk)
        out = {**base, "bloque": nombre, "capa": capa, "capa_existia": res["capa_existia"], "cantidad": res["cantidad"]}
        if not ejecutar:
            return {**out, "se_insertarian_en": [(float(x), float(y)) for x, y in args["puntos"]]}
        return {**out, "insertados": [(float(x), float(y)) for x, y in args["puntos"]], "handles": res["handles"]}
    if op == "insertar_varios":
        grupos = args["grupos"]
        faltan = sorted({g["nombre"] for g in grupos if not existe(doc.Blocks, g["nombre"])})
        if faltan:  # todo o nada: no se escribe nada si falta alguno
            return {"ok": False, "error": "bloque_no_existe", "faltan": faltan,
                    "detalle": "Estos bloques no existen en el dibujo (no se inserto nada): " + ", ".join(faltan)
                               + ". Crealos primero con crear_bloque_producto."}
        errores = [escala_del_grupo(doc, g)[2] for g in grupos]
        if any(errores):  # tambien todo o nada: no se escribe nada si no se puede adaptar algun bloque
            return {"ok": False, "error": "no_se_pudo_adaptar_bloque", "detalle": "No se inserto nada. " + " ".join(e for e in errores if e)}
        res = [{"bloque": g["nombre"], "capa": g["capa"], **_insertar_grupo(doc, g, ejecutar, mk)} for g in grupos]
        return {**base, "grupos": res, "total_insertados": sum(r["cantidad"] for r in res)}
    if op == "textos":
        capa = args["capa"]
        capa_existia = existe(capas_de(doc), capa)
        res = {"capa": capa, "capa_existia": capa_existia, "textos": len(args["textos"])}
        if not ejecutar:
            return {**base, **res}
        if not capa_existia:
            capas_de(doc).Add(capa)
        handles = []
        for t in args["textos"]:
            x, y = float(t["x"]), float(t["y"])
            obj = doc.ModelSpace.AddText(str(t["texto"]), mk(x, y, 0), float(t["altura"]))
            obj.Layer = capa
            try:
                obj.Alignment = 10  # centro medio
                obj.TextAlignmentPoint = mk(x, y, 0)
                obj.Rotation = math.radians(float(t.get("rotacion_grados", 0) or 0))
            except Exception:
                pass
            handles.append(obj.Handle)
        return {**base, **res, "handles": handles}
    if op == "lineas":
        capa = args["capa"]
        capa_existia = existe(capas_de(doc), capa)
        res = {"capa": capa, "capa_existia": capa_existia, "lineas": len(args["segmentos"])}
        if not ejecutar:
            return {**base, **res}
        if not capa_existia:
            lay = capas_de(doc).Add(capa)
            try:
                lay.color = int(args.get("color", 1))  # ACI: 1 = rojo
            except Exception:
                pass
        handles = []
        for x0, y0, x1, y1 in args["segmentos"]:
            ln = doc.ModelSpace.AddLine(mk(x0, y0, 0), mk(x1, y1, 0))
            ln.Layer = capa
            handles.append(ln.Handle)
        return {**base, **res, "handles": handles}
    if op == "espacios":
        return {**base, **_dibujar_espacios(doc, args, ejecutar, mk, mkd)}
    if op == "contornos":
        return {**base, **_dibujar_contornos(doc, args, ejecutar, mk, mkd)}
    if op == "quitar_capa_revision":
        capa = str(args["capa"])
        if not capa.upper().startswith("SCH_REVISION"):                 # SOLO la capa de revision: nunca otra
            return {"ok": False, "error": "capa_no_permitida", "detalle": "Solo se pueden quitar capas SCH_REVISION*."}
        existia = existe(capas_de(doc), capa)
        quitados = _borrar_capa_propia(doc, capa) if (existia and ejecutar) else 0
        return {**base, "capa": capa, "capa_existia": existia, "quitados": quitados}
    return {"ok": False, "error": "operacion_desconocida", "detalle": str(op)}


def mk_doubles(valores):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(float(v) for v in valores))


def _dibujar_espacios(doc, args, ejecutar, mk, mkd):
    """Rectangulos (muros esquematicos) + nombre centrado. Solo agrega, en dos capas propias."""
    capas = {"muros": args["capa_muros"], "espacios": args["capa_espacios"]}
    existian = {k: existe(capas_de(doc), v) for k, v in capas.items()}
    res = {"espacios": len(args["espacios"]), "capas": capas, "capas_existian": existian}
    if not ejecutar:
        return res
    for k, v in capas.items():
        if not existian[k]:
            capas_de(doc).Add(v)
    alto = float(args.get("altura_texto", 200))
    handles = []
    for e in args["espacios"]:
        x0, y0, x1, y1 = (float(e[k]) for k in ("x0", "y0", "x1", "y1"))
        pl = doc.ModelSpace.AddLightWeightPolyline(mkd([x0, y0, x1, y0, x1, y1, x0, y1]))
        pl.Closed = True
        pl.Layer = capas["muros"]
        t = doc.ModelSpace.AddText(str(e["nombre"]), mk((x0 + x1) / 2, (y0 + y1) / 2, 0), alto)
        t.Layer = capas["espacios"]
        try:
            t.Alignment = 10  # centro medio
            t.TextAlignmentPoint = mk((x0 + x1) / 2, (y0 + y1) / 2, 0)
        except Exception:
            pass
        handles += [pl.Handle, t.Handle]
    return {**res, "handles": handles}


def _borrar_capa_propia(doc, capa):
    """Borra SOLO las entidades de la capa de revision (propia del MCP) para poder repetir el dibujo sin duplicar. Devuelve cuantas."""
    import pythoncom
    from win32com.client import VARIANT
    nombre = "SCH_REV_TMP"
    try:
        doc.SelectionSets.Item(nombre).Delete()
    except Exception:
        pass
    ss = doc.SelectionSets.Add(nombre)
    try:
        ss.Select(5, None, None, VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_I2, (8,)), VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, (capa,)))
        n = ss.Count
        for i in range(n - 1, -1, -1):
            ss.Item(i).Delete()
        return n
    finally:
        try:
            ss.Delete()
        except Exception:
            pass


def _dibujar_contornos(doc, args, ejecutar, mk, mkd):
    """Contornos REALES (polilineas cerradas) de los recintos medidos, con su numero y area, en una capa propia de revision. Solo agrega
    (y, si `reemplazar`, quita antes lo que haya en ESA capa)."""
    capa = args["capa"]
    existia = existe(capas_de(doc), capa)
    res = {"capa": capa, "capa_existia": existia, "contornos": len(args["contornos"])}
    if not ejecutar:
        return res
    if not existia:
        lay = capas_de(doc).Add(capa)
        try:
            lay.color = int(args.get("color", 1))
        except Exception:
            pass
    quitados = _borrar_capa_propia(doc, capa) if existia and args.get("reemplazar", True) else 0
    alto = float(args["altura_texto"])
    handles = []
    for c in args["contornos"]:
        pts = c["pts"]
        plano = []
        for x, y in pts:
            plano += [float(x), float(y)]
        cx, cy = float(c["cx"]), float(c["cy"])
        if args.get("sin_contorno"):                                 # solo el numero de la zona: sin lineas
            t = doc.ModelSpace.AddText(str(c["etiqueta"]), mk(cx, cy, 0), alto)
            t.Layer = capa
            try:
                t.Alignment = 10
                t.TextAlignmentPoint = mk(cx, cy, 0)
            except Exception:
                pass
            handles.append(t.Handle)
            continue
        pl = doc.ModelSpace.AddLightWeightPolyline(mkd(plano))
        pl.Closed = True
        pl.Layer = capa
        t = doc.ModelSpace.AddText(str(c["etiqueta"]), mk(cx, cy, 0), alto)
        t.Layer = capa
        try:
            t.Alignment = 10
            t.TextAlignmentPoint = mk(cx, cy, 0)
        except Exception:
            pass
        handles += [pl.Handle, t.Handle]
    return {**res, "reemplazados": quitados, "handles": handles}


def main():
    args = json.loads(sys.argv[1])
    try:
        import pythoncom
        import win32com.client
    except Exception as e:
        return {"ok": False, "error": "sin_pywin32", "detalle": str(e)}
    pythoncom.CoInitialize()
    try:
        doc = win32com.client.GetActiveObject("AutoCAD.Application").ActiveDocument
    except Exception:
        return {"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto con un dibujo activo."}
    try:
        return ejecutar_op(doc, args)
    except Exception as e:
        return {"ok": False, "error": "fallo_al_escribir", "detalle": f"{type(e).__name__}: {e}",
                "aviso": "Revisa el dibujo: puede haber quedado algo a medias. Ctrl+Z en AutoCAD lo deshace."}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, default=str))
