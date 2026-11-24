"""Convierte la geometria de definiciones de bloque en SVG (vista previa). SOLO LECTURA. Proceso aparte.

Dibuja lineas, polilineas (sin arcos de bulge), circulos y arcos; entra en bloques anidados (1 nivel). Lo demas (rellenos, textos,
solidos, regiones, elipses) se cuenta como 'omitidas'. No modifica nada y no devuelve nombres de archivo ni textos del dibujo.
Argumento (JSON en argv[1]): {"destino_contiene": str | null, "nombres": [...]}
"""
import json
import math
import sys

MAX_PRIMITIVAS = 3000
MAX_NIVELES = 3  # niveles de bloques anidados que se recorren


def primitivas(entidades, resolver_bloque=None, nivel=0, omitidas=None, t=None):
    """Lista de ('l',x1,y1,x2,y2) | ('c',x,y,r) | ('a',x,y,r,a0,a1) | ('p',[(x,y)..],cerrada) en coordenadas del bloque."""
    omitidas = omitidas if omitidas is not None else {}
    t = t or (lambda x, y: (x, y))
    out = []
    for e in entidades:
        try:
            tipo = str(e.ObjectName).replace("AcDb", "")
            if tipo == "Line":
                a, b = e.StartPoint, e.EndPoint
                out.append(("l", *t(a[0], a[1]), *t(b[0], b[1])))
            elif tipo == "Circle":
                c = e.Center
                out.append(("c", *t(c[0], c[1]), float(e.Radius) * getattr(t, "escala", 1.0)))
            elif tipo == "Arc":
                c = e.Center
                rot = getattr(t, "rotacion", 0.0)
                out.append(("a", *t(c[0], c[1]), float(e.Radius) * getattr(t, "escala", 1.0),
                            float(e.StartAngle) + rot, float(e.EndAngle) + rot))
            elif tipo in ("Polyline", "2dPolyline", "3dPolyline"):
                n = 2 if tipo == "Polyline" else 3
                co = list(e.Coordinates)
                pts = [t(co[i], co[i + 1]) for i in range(0, len(co) - n + 1, n)]
                if len(pts) >= 2:
                    out.append(("p", pts, bool(getattr(e, "Closed", False))))
            elif tipo == "BlockReference" and resolver_bloque and nivel < MAX_NIVELES:
                ip, esc, rot = e.InsertionPoint, float(e.XScaleFactor), float(e.Rotation)
                co, si = math.cos(rot), math.sin(rot)
                hijo = resolver_bloque(e)
                ents, base = hijo if isinstance(hijo, tuple) else (hijo, (0.0, 0.0))

                def t2(x, y, ip=ip, esc=esc, co=co, si=si, t=t, base=base):
                    x, y = x - base[0], y - base[1]          # el punto base del bloque anidado va al punto de insercion
                    return t(ip[0] + esc * (x * co - y * si), ip[1] + esc * (x * si + y * co))
                t2.escala, t2.rotacion = esc * getattr(t, "escala", 1.0), rot + getattr(t, "rotacion", 0.0)
                if ents is not None:
                    out += primitivas(ents, resolver_bloque, nivel + 1, omitidas, t2)
            elif tipo == "BlockReference":
                omitidas[tipo] = omitidas.get(tipo, 0) + 1
            else:
                omitidas[tipo] = omitidas.get(tipo, 0) + 1
        except Exception:
            omitidas["error_de_lectura"] = omitidas.get("error_de_lectura", 0) + 1
    return out


def _caja(prims):
    xs, ys = [], []
    for p in prims:
        if p[0] == "l":
            xs += [p[1], p[3]]; ys += [p[2], p[4]]
        elif p[0] == "c":
            xs += [p[1] - p[3], p[1] + p[3]]; ys += [p[2] - p[3], p[2] + p[3]]
        elif p[0] == "a":  # solo el tramo del arco: extremos + los puntos cardinales que caen dentro del barrido
            cx, cy, r, a0, a1 = p[1:]
            barrido = (a1 - a0) % (2 * math.pi) or 2 * math.pi
            angulos = [a0, a0 + barrido] + [k * math.pi / 2 for k in range(-8, 9) if 0 < (k * math.pi / 2 - a0) % (2 * math.pi) < barrido]
            xs += [cx + r * math.cos(a) for a in angulos]; ys += [cy + r * math.sin(a) for a in angulos]
        else:
            xs += [q[0] for q in p[1]]; ys += [q[1] for q in p[1]]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def a_svg(prims, color="#2a4a72"):
    """SVG autonomo (viewBox ajustado, eje Y invertido para que 'arriba' sea arriba) o None si no hay geometria."""
    prims = prims[:MAX_PRIMITIVAS]
    caja = _caja(prims)
    if not caja:
        return None
    x0, y0, x1, y1 = caja
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    pad = max(w, h) * 0.06
    trazo = max(w, h) / 90
    f = lambda v: f"{v:.4g}"  # noqa: E731
    d = []
    for p in prims:
        if p[0] == "l":
            d.append(f'<line x1="{f(p[1])}" y1="{f(-p[2])}" x2="{f(p[3])}" y2="{f(-p[4])}"/>')
        elif p[0] == "c":
            d.append(f'<circle cx="{f(p[1])}" cy="{f(-p[2])}" r="{f(p[3])}"/>')
        elif p[0] == "a":
            cx, cy, r, a0, a1 = p[1:]
            barrido = (a1 - a0) % (2 * math.pi)
            sx, sy, ex, ey = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
            d.append(f'<path d="M{f(sx)} {f(-sy)}A{f(r)} {f(r)} 0 {1 if barrido > math.pi else 0} 0 {f(ex)} {f(-ey)}"/>')
        else:
            pts = " ".join(f"{f(x)},{f(-y)}" for x, y in p[1])
            d.append(f'<{"polygon" if p[2] else "polyline"} points="{pts}"/>')
    vb = f"{f(x0 - pad)} {f(-(y1 + pad))} {f(w + 2 * pad)} {f(h + 2 * pad)}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" fill="none" stroke="{color}" stroke-width="{f(trazo)}" '
            f'stroke-linejoin="round" stroke-linecap="round">{"".join(d)}</svg>')


def existe(coleccion, nombre):
    try:
        coleccion.Item(nombre)
        return True
    except Exception:
        return False


def exportar(doc, nombres):
    def resolver(ref):
        try:
            b = doc.Blocks.Item(ref.Name)
            return list(b), tuple(b.Origin)[:2]
        except Exception:
            return None, (0.0, 0.0)

    res = {}
    for n in nombres:
        if not existe(doc.Blocks, n):
            res[n] = {"error": "no_existe_en_el_dibujo"}
            continue
        omit = {}
        prims = primitivas(list(doc.Blocks.Item(n)), resolver, 0, omit)
        svg = a_svg(prims)
        res[n] = {"svg": svg, "primitivas": len(prims), "omitidas": omit} if svg else {"svg": None, "primitivas": 0, "omitidas": omit}
    return {"ok": True, "simbolos": res}


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
                return {"ok": False, "error": "dibujo_no_valido", "detalle": f"{len(hall)} documentos coinciden con '{args['destino_contiene']}' (se necesita 1)."}
            doc = hall[0]
        else:
            doc = app.ActiveDocument
    except Exception:
        return {"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto."}
    try:
        return exportar(doc, args["nombres"])
    except Exception as e:
        return {"ok": False, "error": "fallo_al_exportar", "detalle": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, default=str))
