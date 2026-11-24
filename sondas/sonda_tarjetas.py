"""Dibuja TARJETAS de producto (como la referencia) en un dibujo de AutoCAD. Solo AGREGA. Proceso aparte.

Agrega: capas DL-TEST-FICHAS*, un estilo de texto, lineas/polilineas, textos multilinea y una copia del simbolo (bloque ya
existente en el dibujo) por tarjeta. Nunca borra ni modifica lo existente; no usa AutoLISP; no guarda ni cierra.
Con "ejecutar": false solo calcula y dice que haria.
Argumento (JSON en argv[1]): ver crear().
"""
import json
import math
import sys

CAPA_LINEAS, CAPA_TEXTO, CAPA_SIMBOLO = "DL-TEST-FICHAS", "DL-TEST-FICHAS-TEXTO", "DL-TEST-FICHAS-SIMBOLO"
ESTILO = "DL-TEST-FICHA"
AZUL, GRIS, NARANJA = 5, 8, 30
# alto de cada fila, en unidades para una tarjeta de 1800 de ancho (se escala proporcionalmente)
FILAS = [("nombre", 240), ("inst", 240), ("sim", 1000), ("ref", 240), ("desc", 420), ("cant", 240), ("con", 620)]
ANCHO_BASE, ALTO_TEXTO_BASE, GAP_BASE = 1800.0, 100.0, 120.0
MAX_ESCALA_SIMBOLO = 20.0


def mk_variant(x, y, z=0.0):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(x), float(y), float(z)))


def mk_plano(valores):
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(float(v) for v in valores))


def existe(coleccion, nombre) -> bool:
    try:
        coleccion.Item(nombre)
        return True
    except Exception:
        return False


def esc(t) -> str:
    """Escapa lo que MText interpreta como formato."""
    return str(t).replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ").replace("\r", " ")


def recortar(t, max_chars) -> str:
    t = str(t)
    return t if len(t) <= max_chars else t[: max(max_chars - 1, 1)].rstrip() + "…"


def valor(campo, defecto="sin dato") -> str:
    """Valor en azul; inventado en naranja inclinado; vacio en gris."""
    v = campo.get("v") if isinstance(campo, dict) else campo
    if v in (None, ""):
        return f"\\C{GRIS};{defecto}"
    if isinstance(campo, dict) and campo.get("inv"):
        return f"\\C{NARANJA};\\Q15;{esc(v)}"
    return f"\\C{AZUL};{esc(v)}"


def caja_simbolo(bloque):
    """(ancho, alto) de la caja de un bloque (solo entidades con caja); None si no hay."""
    xs, ys = [], []
    for e in bloque:
        try:
            mn, mx = e.GetBoundingBox()
            xs += [mn[0], mx[0]]
            ys += [mn[1], mx[1]]
        except Exception:
            pass
    return (max(xs) - min(xs), max(ys) - min(ys)) if xs else None


def disenar(tarjetas, ancho, x0, y0, columnas):
    """Posicion (esquina superior izquierda) de cada tarjeta y alto total de una tarjeta."""
    k = ancho / ANCHO_BASE
    alto = sum(h for _, h in FILAS) * k
    gap = GAP_BASE * k
    pos = [(x0 + (i % columnas) * (ancho + gap), y0 - (i // columnas) * (alto + gap)) for i in range(len(tarjetas))]
    return pos, alto, gap, k


def crear(doc, args, mk=mk_variant, mkplano=mk_plano):
    ejecutar = bool(args.get("ejecutar"))
    ms = doc.ModelSpace
    existentes = ms.Count
    max_obj = int(args.get("max_objetos", 300))
    if existentes > max_obj:
        return {"ok": False, "error": "dibujo_demasiado_grande_para_escribir",
                "detalle": f"El dibujo tiene {existentes} objetos (maximo para escribir: {max_obj}). Usa un dibujo de prueba."}
    ancho = float(args.get("ancho", ANCHO_BASE))
    columnas = max(int(args.get("columnas", 8)), 1)
    x0, y0 = float(args.get("x0", 0.0)), float(args.get("y0", 0.0))
    incluir_sin = bool(args.get("incluir_sin_simbolo"))

    # 1) que tarjetas se dibujan: las que tienen un bloque ya presente en el dibujo (o todas si incluir_sin_simbolo)
    elegidas, omitidas = [], []
    for t in args["tarjetas"]:
        bloque = next((b for b in t.get("bloques", []) if existe(doc.Blocks, b)), None)
        if bloque or incluir_sin:
            elegidas.append({**t, "bloque_usado": bloque})
        else:
            omitidas.append({"referencia": t.get("referencia"), "motivo": "sin simbolo en el dibujo"})
    if not elegidas:
        return {"ok": False, "error": "sin_tarjetas", "detalle": "Ningun producto tiene su simbolo en el dibujo.", "omitidas": omitidas}

    pos, alto, gap, k = disenar(elegidas, ancho, x0, y0, columnas)
    leyenda = bool(args.get("leyenda", True))
    por_tarjeta = 1 + (len(FILAS) - 1) + 6 + 1       # marco + divisiones + textos (NOMBRE, INSTALACION, REF, DESCRIPTION, CANTIDAD, CONEXION) + simbolo
    a_agregar = len(elegidas) * por_tarjeta + (22 if leyenda else 0)
    filas_usadas = math.ceil(len(elegidas) / columnas)
    ancho_total = min(len(elegidas), columnas) * (ancho + gap) - gap
    ext = [x0, y0 - filas_usadas * (alto + gap) + gap, x0 + ancho_total + (ancho * 1.2 + gap if leyenda else 0), y0]
    base = {"ok": True, "ejecutado": ejecutar, "tarjetas": len(elegidas), "omitidas_sin_simbolo": omitidas,
            "objetos_existentes": existentes, "objetos_a_agregar_aprox": a_agregar, "extension_xy": [round(v, 1) for v in ext],
            "tamano_tarjeta": [round(ancho, 1), round(alto, 1)]}
    if existentes + a_agregar > max_obj:
        return {"ok": False, "error": "superaria_el_maximo", **base, "ejecutado": False,
                "detalle": f"El dibujo quedaria con ~{existentes + a_agregar} objetos (maximo para escribir: {max_obj}). "
                           "Usa menos tarjetas (filtro) o un dibujo vacio."}
    if not ejecutar:
        return base

    # 2) capas y estilo de texto (solo se agregan si no existen)
    for capa in (CAPA_LINEAS, CAPA_TEXTO, CAPA_SIMBOLO):
        if not existe(doc.Layers, capa):
            doc.Layers.Add(capa)
    estilo_ok = existe(doc.TextStyles, ESTILO)
    if not estilo_ok:
        try:
            st = doc.TextStyles.Add(ESTILO)
            for fuente in ("Arial Narrow", "Arial"):
                try:
                    st.SetFont(fuente, False, False, 0, 34)
                    break
                except Exception:
                    continue
            estilo_ok = True
        except Exception:
            estilo_ok = False

    th = ALTO_TEXTO_BASE * k
    pad = 50 * k
    cpl = max(int((ancho - 2 * pad) / (th * 0.5)), 8)   # caracteres por linea (aprox.)
    escalas = {}

    def linea(a, b, capa=CAPA_LINEAS, color=None):
        e = ms.AddLine(mk(a[0], a[1], 0), mk(b[0], b[1], 0))
        e.Layer = capa
        if color is not None:
            e.color = color
        return e

    def poli(pts, cerrada=True, capa=CAPA_LINEAS, color=None):
        plano = [v for p in pts for v in p]
        e = ms.AddLightWeightPolyline(mkplano(plano))
        e.Closed = cerrada
        e.Layer = capa
        if color is not None:
            e.color = color
        return e

    def texto(x, y, contenido, ancho_txt, altura=None):
        e = ms.AddMText(mk(x, y, 0), ancho_txt, contenido)
        e.Height = altura or th
        e.Layer = CAPA_TEXTO
        if estilo_ok:
            e.StyleName = ESTILO
        return e

    for t, (x, y) in zip(elegidas, pos):
        poli([(x, y), (x + ancho, y), (x + ancho, y - alto), (x, y - alto)])
        tops, acum = {}, 0.0
        for nombre, h in FILAS:
            tops[nombre] = y - acum
            acum += h * k
            if nombre != FILAS[-1][0]:
                linea((x, y - acum), (x + ancho, y - acum))
        w_txt = ancho - 2 * pad
        etiqueta = lambda s: f"\\C7;{s} "  # noqa: E731
        texto(x + pad, tops["nombre"] - pad, etiqueta("NOMBRE:") + valor(t.get("nombre")), w_txt)
        texto(x + pad, tops["inst"] - pad, etiqueta("INSTALACIÓN:") + valor(t.get("instalacion")), w_txt)
        marca = t.get("marca")
        marca_txt = f" \\C{AZUL};({esc(marca)})" if marca not in (None, "", "—") else ""
        texto(x + pad, tops["ref"] - pad, etiqueta("REF:") + valor(recortar(t.get("referencia"), cpl - 8)) + marca_txt, w_txt)
        desc = t.get("descripcion")
        texto(x + pad, tops["desc"] - pad, etiqueta("DESCRIPTION:") + valor(recortar(desc, 2 * cpl - 14)), w_txt)
        q = t.get("cantidad")
        texto(x + pad, tops["cant"] - pad, etiqueta("CANTIDAD:") + (f"\\C{AZUL};{esc(q)}" if q not in (None, "") else f"\\C{GRIS};sin dato"), w_txt)
        con = t.get("conexion") or {}
        con_v = {**con, "v": recortar(con.get("v"), 3 * cpl - 4)} if con.get("v") else con
        texto(x + pad, tops["con"] - pad, etiqueta("TIPO DE CONEXIÓN:") + "\\P" + valor(con_v), w_txt)
        # simbolo: copia del bloque escalada para caber en su recuadro
        b = t["bloque_usado"]
        alto_sim = dict(FILAS)["sim"]          # por nombre, no por posicion: las filas pueden cambiar de orden
        cx, cy = x + ancho / 2, tops["sim"] - (alto_sim * k) / 2
        if b:
            tam = caja_simbolo(doc.Blocks.Item(b))
            if tam and tam[0] > 0 and tam[1] > 0:
                s = min(MAX_ESCALA_SIMBOLO, 0.8 * (ancho - 2 * pad) / tam[0], 0.8 * alto_sim * k / tam[1])
            else:
                s = 1.0
            ref = ms.InsertBlock(mk(cx, cy, 0), b, s, s, s, 0.0)
            ref.Layer = CAPA_SIMBOLO
            escalas[b] = round(s, 4)
        else:
            texto(x + pad, cy + th, f"\\C{GRIS};sin símbolo", w_txt)

    # 3) leyenda de convenciones (a la derecha de la ultima columna)
    if leyenda:
        lx = x0 + ancho_total + gap
        lw = ancho * 1.2
        alto_item = 300 * k
        items = 6
        poli([(lx, y0), (lx + lw, y0), (lx + lw, y0 - items * alto_item), (lx, y0 - items * alto_item)])
        etiquetas = ["RACK", 'Tubería Ø3/4"', 'Tubería Ø1"', 'Tubería Ø1/2"', "Punto eléctrico", "Punto de datos"]
        for i, nombre in enumerate(etiquetas):
            ty = y0 - i * alto_item
            if i:
                linea((lx, ty), (lx + lw, ty))
            cy = ty - alto_item / 2
            ix0, ix1 = lx + 80 * k, lx + 520 * k
            if i == 0:
                poli([(ix0 + 140 * k, cy + 70 * k), (ix1 - 140 * k, cy + 70 * k), (ix1 - 140 * k, cy - 70 * k), (ix0 + 140 * k, cy - 70 * k)], color=3)
            elif i in (1, 2, 3):
                linea((ix0, cy), (ix1, cy), color={1: 5, 2: 4, 3: 1}[i])
            elif i == 4:
                c = ms.AddCircle(mk((ix0 + ix1) / 2, cy, 0), 55 * k)
                c.Layer, c.color = CAPA_LINEAS, 5
                linea(((ix0 + ix1) / 2, cy + 55 * k), ((ix0 + ix1) / 2, cy + 120 * k), color=5)
            else:
                mx = (ix0 + ix1) / 2
                poli([(mx, cy + 90 * k), (mx + 80 * k, cy - 70 * k), (mx - 80 * k, cy - 70 * k)], color=3)
            texto(lx + 600 * k, ty - alto_item / 2 + th * 0.9, "\\C7;" + esc(nombre), lw - 640 * k)

    return {**base, "dibujado": True, "escalas_simbolo": escalas}


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
        if args.get("destino_contiene"):
            t = str(args["destino_contiene"]).casefold()
            hall = [d for d in docs if t in str(d.Name).casefold()]
            if len(hall) != 1:
                return {"ok": False, "error": "destino_no_valido", "detalle": f"{len(hall)} documentos coinciden con '{args['destino_contiene']}' (se necesita 1)."}
            doc = hall[0]
        else:
            doc = app.ActiveDocument
    except Exception:
        return {"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto."}
    try:
        return crear(doc, args)
    except Exception as e:
        return {"ok": False, "error": "fallo_al_dibujar", "detalle": f"{type(e).__name__}: {e}",
                "aviso": "Puede haber quedado algo a medias en el dibujo: Ctrl+Z en AutoCAD lo deshace."}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, default=str))
