"""Importa SIMBOLOS (definiciones de bloque) de un dibujo ORIGEN a un dibujo DESTINO. Proceso aparte.

- ORIGEN: solo lectura. Se lee la geometria de los bloques pedidos y la escala con que se insertan. No se devuelve
  ningun texto ni nombre de archivo del origen (solo tipos de entidad y medidas).
- DESTINO: solo se AGREGA (una definicion de bloque nueva por simbolo). Nunca se pisa un bloque existente.
  Si algo falla a mitad de un bloque, se borra SOLO la definicion vacia que se acaba de crear en esa llamada.
- Los simbolos copiados se escalan a las unidades del destino segun la escala tipica de insercion en el origen,
  para que despues se inserten a escala 1.
Argumento (JSON en argv[1]): {"origen_contiene", "destino_contiene" | null, "nombres": [...], "ejecutar": bool,
                              "max_objetos": n, "limite_objetos": n}
"""
import collections
import json
import re
import sys

# metros por unidad (INSUNITS)
UNIDAD_M = {1: 0.0254, 2: 0.3048, 3: 1609.344, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 14: 0.1}


def mk_variant(x, y, z=0.0):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(x), float(y), float(z)))


def mk_objetos(objs):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, tuple(objs))


def existe(coleccion, nombre) -> bool:
    try:
        coleccion.Item(nombre)
        return True
    except Exception:
        return False


def elegir_doc(docs, contiene, excluir=None):
    """(doc, None) si hay exactamente uno cuyo nombre contiene el texto; (None, mensaje) si no. No revela nombres."""
    t = re.sub(r"[^a-z0-9]", "", str(contiene).casefold())
    hallados = [d for d in docs if t in re.sub(r"[^a-z0-9]", "", str(d.Name).casefold()) and d is not excluir]
    if len(hallados) == 1:
        return hallados[0], None
    return None, f"{len(hallados)} documentos abiertos coinciden con '{contiene}' (se necesita exactamente 1)."


def escalas_en_origen(origen, nombres, limite=20000):
    """{nombre: Counter(escala)} recorriendo el modelo del origen (solo lectura)."""
    buscados = {n.casefold(): n for n in nombres}
    cuentas = {n: collections.Counter() for n in nombres}
    k = 0
    for obj in origen.ModelSpace:
        k += 1
        if k > limite:
            break
        try:
            if obj.ObjectName != "AcDbBlockReference":
                continue
            nombre = buscados.get(str(obj.EffectiveName).casefold())
            if nombre:
                cuentas[nombre][round(abs(float(obj.XScaleFactor)), 6)] += 1
        except Exception:
            continue
    return cuentas


def _medidas(entidades):
    """(ancho, alto, centro_x, centro_y) de la caja que envuelve las entidades; (None,)*4 si ninguna tiene caja."""
    xs, ys = [], []
    for e in entidades:
        try:
            mn, mx = e.GetBoundingBox()
            xs += [mn[0], mx[0]]
            ys += [mn[1], mx[1]]
        except Exception:
            pass
    if not xs:
        return None, None, None, None
    return max(xs) - min(xs), max(ys) - min(ys), (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2


def codigo_dibujo(doc) -> str:
    """4 caracteres fijos por dibujo (de su ruta). Se muestra SOLO en la linea de comandos de AutoCAD, no en el chat."""
    import hashlib
    try:
        clave = str(doc.FullName or doc.Name)
    except Exception:
        clave = str(getattr(doc, "Name", "?"))
    return hashlib.sha1(clave.casefold().encode("utf-8")).hexdigest()[:4].upper()


def candado(doc, confirmacion, total, ejecutar, max_objetos):
    """None = puede seguir. Ensayo siempre vale; escribir en un dibujo grande exige el codigo que sale en AutoCAD."""
    if total <= max_objetos:
        return None
    codigo = codigo_dibujo(doc)
    try:
        doc.Utility.Prompt(f"\ndiseno-mcp: codigo de confirmacion para escribir en ESTE dibujo: {codigo}\n")
    except Exception:
        pass
    if not ejecutar or str(confirmacion or "").strip().upper() == codigo:
        return None
    return {"ok": False, "error": "dibujo_grande_requiere_confirmacion", "objetos_en_destino": total,
            "detalle": f"El dibujo destino tiene {total} objetos (plano grande). No se escribio nada. Para escribir, la persona "
                       "debe leer el codigo de confirmacion en la linea de comandos de AutoCAD y pasarlo como `confirmacion`."}


def nombres_de_biblioteca(origen):
    """Nombres de todas las definiciones de bloque 'de usuario' (sin anonimos, layouts ni xrefs)."""
    out = []
    for b in origen.Blocks:
        try:
            n = str(b.Name)
            if b.IsLayout or b.IsXRef or n.startswith("*") or n.upper().startswith("A$C"):
                continue
            out.append(n)
        except Exception:
            continue
    return sorted(out, key=str.casefold)


def _firma(bloque, factor=1.0):
    """(tipos de entidad, ancho, alto) de una definicion; medidas multiplicadas por `factor` y redondeadas al 1 %."""
    ents = list(bloque)
    tipos = tuple(sorted(collections.Counter(str(e.ObjectName) for e in ents).items()))
    # el tamano ignora textos y atributos: su ancho depende de la fuente de cada dibujo y no es la forma del producto
    w, h, _, _ = _medidas([e for e in ents if str(e.ObjectName) not in ("AcDbText", "AcDbMText", "AcDbAttributeDefinition")])
    r = lambda v: None if v is None else float(f"{v * factor:.3g}")  # noqa: E731  (3 cifras significativas)
    return tipos, r(w), r(h)


def comparar(origen, destino, mostrar_solo_en_plano=False):
    """SOLO LECTURA. Compara la biblioteca (origen) con un plano (destino), por nombre de bloque y por forma."""
    if origen is destino:
        return {"ok": False, "error": "origen_igual_destino", "detalle": "La biblioteca y el plano son el mismo dibujo."}
    u_o, u_d = origen.GetVariable("INSUNITS"), destino.GetVariable("INSUNITS")
    avisos, relacion = [], 1.0
    if u_o in UNIDAD_M and u_d in UNIDAD_M:
        relacion = UNIDAD_M[u_o] / UNIDAD_M[u_d]
    else:
        avisos.append("Alguno de los dibujos no tiene unidades definidas: se comparo sin convertir (relacion 1).")
    lib = nombres_con_ficha(origen) or nombres_de_biblioteca(origen)   # solo productos con ficha (si no hay fichas, todo)
    plano = nombres_de_biblioteca(destino)
    plano_cf = {n.casefold(): n for n in plano}
    lib_cf = {n.casefold() for n in lib}
    faltan, iguales, distintos = [], [], []
    for n in lib:
        if n.casefold() not in plano_cf:
            faltan.append(n)
            continue
        a = _firma(origen.Blocks.Item(n), relacion)
        b = _firma(destino.Blocks.Item(plano_cf[n.casefold()]))
        ok = a[0] == b[0] and all((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= 0.02 * max(abs(x), abs(y), 1e-9))
                                  for x, y in zip(a[1:], b[1:]))
        (iguales if ok else distintos).append(n)
    solo = [n for n in plano if n.casefold() not in lib_cf]
    out = {"ok": True, "solo_lectura": True, "en_biblioteca": len(lib), "en_plano": len(plano), "iguales": len(iguales),
           "faltan_en_plano": faltan, "posiblemente_desactualizados": distintos, "solo_en_plano_cantidad": len(solo),
           "avisos": avisos,
           "nota": "Comparacion por tipos de entidad y tamano (tolerancia 2 %). 'solo_en_plano' son bloques del plano que no "
                   "estan en la biblioteca (otros bloques, o un nombre cambiado); sus nombres se ocultan por privacidad."}
    if mostrar_solo_en_plano:
        out["solo_en_plano"] = solo
    return out


def nombres_con_ficha(origen):
    """Nombres de los bloques que estan COLOCADOS en el modelo del origen (en la biblioteca: uno por ficha de producto).

    Deja fuera las definiciones sueltas (sin ficha), que pueden ser restos de otros planos. Los sub-bloques internos de un
    producto no se listan: llegan solos con su bloque padre.
    """
    vistos, orden = set(), []
    for e in origen.ModelSpace:
        try:
            if e.ObjectName != "AcDbBlockReference":
                continue
            n = str(e.EffectiveName)
            if n.casefold() not in vistos:
                vistos.add(n.casefold())
                orden.append(n)
        except Exception:
            continue
    return sorted(orden, key=str.casefold)


def padres_primero(origen, nombres):
    """Reordena para copiar PRIMERO los bloques que contienen a otros y DESPUES los bloques anidados.

    Al copiar un padre, AutoCAD trae solo su sub-bloque (sin escalar) y el padre se escala entero una vez. Si el sub-bloque se
    importara antes por su cuenta, se escalaria dos veces (una por si mismo y otra a traves del padre).
    """
    anidados = set()
    for n in nombres:
        try:
            for e in origen.Blocks.Item(n):
                if str(getattr(e, "ObjectName", "")) == "AcDbBlockReference":
                    anidados.add(str(e.Name).casefold())
        except Exception:
            continue
    return [n for n in nombres if n.casefold() not in anidados] + [n for n in nombres if n.casefold() in anidados]


def importar(origen, destino, nombres, ejecutar, max_objetos=300, limite_objetos=20000, mk=mk_variant, mkobj=mk_objetos,
             confirmacion=None, como_esta=False, solo_con_ficha=True):
    """como_esta=True: copia las definiciones SIN escala de insercion ni recentrado (solo conversion de unidades);
    nombres=None: todas las de la biblioteca del origen."""
    if origen is destino:
        return {"ok": False, "error": "origen_igual_destino", "detalle": "El origen y el destino son el mismo dibujo."}
    total_dest = destino.ModelSpace.Count
    if (bloqueo := candado(destino, confirmacion, total_dest, ejecutar, max_objetos)):
        return bloqueo
    if nombres is None:  # biblioteca completa: por defecto SOLO los bloques con ficha (no restos de otros planos)
        nombres = nombres_con_ficha(origen) if solo_con_ficha else nombres_de_biblioteca(origen)
    nombres = padres_primero(origen, list(nombres))
    u_o, u_d = origen.GetVariable("INSUNITS"), destino.GetVariable("INSUNITS")
    avisos, relacion = [], 1.0
    if u_o in UNIDAD_M and u_d in UNIDAD_M:
        relacion = UNIDAD_M[u_o] / UNIDAD_M[u_d]
    else:
        avisos.append("Alguno de los dibujos no tiene unidades definidas: no se convirtio entre unidades (relacion 1).")
    presentes = [n for n in nombres if existe(origen.Blocks, n)]
    escalas = ({n: collections.Counter() for n in presentes} if como_esta
               else escalas_en_origen(origen, presentes, limite_objetos))
    resultados = {}
    for nombre in nombres:
        if nombre not in presentes:
            resultados[nombre] = {"estado": "no_existe_en_origen"}
            continue
        src = origen.Blocks.Item(nombre)
        ents = list(src)
        tipos = dict(collections.Counter(str(e.ObjectName).replace("AcDb", "") for e in ents))
        usos = escalas[nombre]
        tipica = usos.most_common(1)[0][0] if usos else 1.0
        factor = tipica * relacion
        w, h, cx, cy = _medidas(ents)
        ox, oy = tuple(src.Origin)[:2]
        # cuanto se movera el dibujo para que su centro quede en el punto base (unidades del destino)
        desp = [round((cx - ox) * factor, 3), round((cy - oy) * factor, 3)] if cx is not None and not como_esta else None
        info = {"entidades": tipos, "escala_tipica_en_origen": tipica, "usos_en_origen": sum(usos.values()),
                "factor_aplicado": round(factor, 6),
                "tamano_en_unidades_destino": [round(w * factor, 3), round(h * factor, 3)] if w is not None else None,
                "centrado_desde": desp}
        if desp is not None and w is not None and (desp[0] ** 2 + desp[1] ** 2) ** 0.5 > 20 * max(w * factor, h * factor, 1.0):
            info["aviso_base"] = ("La geometria esta MUY lejos del punto base en el origen (bloque mal definido); "
                                  "se recentra en la copia para que el punto de insercion quede en el centro del simbolo.")
        if len(usos) > 1:
            info["aviso"] = f"Escalas de insercion variables en el origen ({len(usos)} distintas): se uso la mas frecuente."
        if not usos and not como_esta:
            info["aviso"] = "No hay copias de este bloque en el modelo del origen: se uso escala 1 sobre sus unidades."
        if existe(destino.Blocks, nombre):
            resultados[nombre] = {**info, "estado": "ya_existia_en_destino (no se toca)"}
        elif not ejecutar:
            resultados[nombre] = {**info, "estado": "se_importaria"}
        else:
            nb = destino.Blocks.Add(mk(0, 0, 0), nombre)
            try:
                if ents:
                    try:
                        origen.CopyObjects(mkobj(ents), nb)
                    except Exception:  # algunas versiones exigen el 3er argumento (IDPairs) por referencia
                        import pythoncom
                        from win32com.client import VARIANT
                        origen.CopyObjects(mkobj(ents), nb, VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None))
                copias = list(nb)
                if abs(factor - 1.0) > 1e-9:
                    for e in copias:
                        e.ScaleEntity(mk(*tuple(src.Origin)), factor)
                        try:  # ScaleEntity NO escala el patron de los tipos de linea (guiones, puntos): sin esto una linea
                            e.LinetypeScale = float(e.LinetypeScale) * factor  # a trazos de un plano en mm se ve continua en metros
                        except Exception:
                            pass
                _, _, ccx, ccy = _medidas(copias)
                if ccx is not None and not como_esta:  # centrar: el centro del dibujo pasa al punto base (0, 0) del bloque nuevo
                    for e in copias:
                        e.Move(mk(ccx, ccy, 0), mk(0, 0, 0))
                resultados[nombre] = {**info, "estado": "importado", "entidades_copiadas": len(copias)}
            except Exception as ex:
                try:
                    nb.Delete()  # solo la definicion que se acaba de crear aqui
                    limpio = "se elimino la definicion incompleta recien creada"
                except Exception:
                    limpio = "NO se pudo eliminar la definicion incompleta; puede quedar un bloque vacio con ese nombre"
                resultados[nombre] = {**info, "estado": "fallo", "detalle": f"{type(ex).__name__}: {ex}", "limpieza": limpio}
    return {"ok": True, "ejecutado": bool(ejecutar), "objetos_en_destino": total_dest,
            "dibujo_grande": total_dest > max_objetos, "simbolos": resultados, "avisos": avisos}


def main():
    args = json.loads(sys.argv[1])
    try:
        import pythoncom
        import win32com.client
    except Exception as e:
        return {"ok": False, "error": "sin_pywin32", "detalle": str(e)}
    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
        docs = list(app.Documents)
        activo = app.ActiveDocument
    except Exception:
        return {"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto."}
    if args.get("destino_contiene"):
        destino, err = elegir_doc(docs, args["destino_contiene"])
    else:
        destino, err = activo, None
    if err:
        return {"ok": False, "error": "destino_no_valido", "detalle": err}
    origen, err = elegir_doc(docs, args["origen_contiene"], excluir=destino)
    if err:
        return {"ok": False, "error": "origen_no_valido", "detalle": err}
    try:
        if args.get("comparar"):
            return comparar(origen, destino, bool(args.get("mostrar_solo_en_plano")))
        return importar(origen, destino, args.get("nombres"), bool(args.get("ejecutar")), int(args.get("max_objetos", 300)),
                        int(args.get("limite_objetos", 20000)), confirmacion=args.get("confirmacion"),
                        como_esta=bool(args.get("como_esta")), solo_con_ficha=bool(args.get("solo_con_ficha", True)))
    except Exception as e:
        return {"ok": False, "error": "fallo_al_importar", "detalle": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, default=str))
