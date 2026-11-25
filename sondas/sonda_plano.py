"""Lectura ESTRUCTURADA de un plano (SOLO LECTURA). Proceso aparte.

Devuelve: unidades (con aviso si no cuadran con el tamano de los bloques), espacios detectados (poligonos cerrados con un texto
dentro: nombre, limites, medidas), bloques colocados (por espacio) y conteos. No modifica nada, no guarda, no usa AutoLISP.
Argumento (JSON en argv[1]): {"destino_contiene": s | null, "limite_objetos": n, "max_espacios": n}
Nunca devuelve el nombre del archivo.
"""
import collections
import json
import math
import re
import statistics
import sys
import time

UNIDADES = {0: "sin unidad", 1: "pulgadas", 2: "pies", 3: "millas", 4: "milimetros", 5: "centimetros", 6: "metros",
            7: "kilometros", 14: "decimetros"}
OCUPADO = (-2147418111, -2147417846, -2147023170)  # llamada rechazada / aplicacion ocupada / fallo RPC


def reintentar(f, veces=6, espera=1.5):
    """AutoCAD rechaza llamadas mientras esta ocupado (regenerando, abriendo un dialogo...). Reintenta unas veces."""
    ultimo = None
    for _ in range(veces):
        try:
            return f()
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if getattr(e, "hresult", None) not in OCUPADO and "rechazada" not in str(e).lower():
                raise
            time.sleep(espera)
    raise ultimo


def limpiar_texto(s) -> str:
    """Quita codigos de formato de MText (\\P, \\A1;, {\\f...;}) y decodifica \\U+00D3."""
    s = str(s or "")
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"\\[Pp]", " ", s)
    s = re.sub(r"\\[A-Za-z][^;\\]*;", "", s)
    s = s.replace("{", "").replace("}", "")
    return " ".join(s.split())


def area(pts) -> float:
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2


def dentro(x, y, pts) -> bool:
    """Punto dentro de poligono (rayos). Los bordes cuentan como dentro con una tolerancia minima."""
    c = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi, xj, yj = pts[i][0], pts[i][1], pts[j][0], pts[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            c = not c
        j = i
    return c


def es_rectangulo(pts) -> bool:
    if len(pts) != 4:
        return False
    xs, ys = sorted({round(p[0], 6) for p in pts}), sorted({round(p[1], 6) for p in pts})
    return len(xs) == 2 and len(ys) == 2


def analizar(doc, limite=20000, max_espacios=60, r=lambda f: f()) -> dict:
    ms = r(lambda: doc.ModelSpace)
    total = r(lambda: ms.Count)
    tipos, polis, textos, bloques = collections.Counter(), [], [], []
    for i in range(min(total, limite)):
        try:
            e = r(lambda: ms.Item(i))
            on = str(e.ObjectName)
            tipos[on.replace("AcDb", "")] += 1
            if on == "AcDbPolyline":
                if bool(e.Closed):
                    c = list(e.Coordinates)
                    pts = [(c[k], c[k + 1]) for k in range(0, len(c) - 1, 2)]
                    if len(pts) >= 3 and area(pts) > 1e-9:
                        polis.append({"pts": pts, "capa": str(e.Layer), "area": area(pts)})
            elif on in ("AcDbText", "AcDbMText"):
                p = e.InsertionPoint
                if on == "AcDbText":
                    try:  # en un Text centrado/alineado, InsertionPoint es el extremo izquierdo: la posicion real es la de alineacion
                        if int(e.Alignment) != 0:
                            p = e.TextAlignmentPoint
                    except Exception:  # noqa: BLE001
                        pass
                txt = limpiar_texto(e.TextString)
                if txt:
                    textos.append({"t": txt, "x": p[0], "y": p[1], "h": float(e.Height)})
            elif on == "AcDbBlockReference":
                p = e.InsertionPoint
                b = {"n": str(e.EffectiveName), "x": p[0], "y": p[1], "rot": round(math.degrees(float(e.Rotation)), 2),
                     "esc": [round(float(e.XScaleFactor), 4), round(float(e.YScaleFactor), 4)], "capa": str(e.Layer)}
                try:
                    a, z = e.GetBoundingBox()
                    b.update(cx=(a[0] + z[0]) / 2, cy=(a[1] + z[1]) / 2, w=z[0] - a[0], h=z[1] - a[1])
                except Exception:  # noqa: BLE001
                    b.update(cx=p[0], cy=p[1], w=None, h=None)
                bloques.append(b)
        except Exception as ex:  # noqa: BLE001
            if getattr(ex, "hresult", None) in OCUPADO:
                raise
    # ---- espacios: poligono cerrado MAS PEQUENO que contiene al texto; el nombre es el texto de mayor altura
    asignado = collections.defaultdict(list)
    for t in textos:
        cont = [k for k, pl in enumerate(polis) if dentro(t["x"], t["y"], pl["pts"])]
        if cont:
            asignado[min(cont, key=lambda k: polis[k]["area"])].append(t)
    espacios = []
    for k, ts in asignado.items():
        pl = polis[k]
        xs, ys = [p[0] for p in pl["pts"]], [p[1] for p in pl["pts"]]
        nombre = max(ts, key=lambda t: t["h"])["t"]
        espacios.append({"nombre": nombre, "capa": pl["capa"], "x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys),
                         "ancho": max(xs) - min(xs), "alto": max(ys) - min(ys), "area": pl["area"],
                         "forma": "rectangulo" if es_rectangulo(pl["pts"]) else "poligono", "_pts": pl["pts"], "_k": k})
    espacios.sort(key=lambda s: (-s["y0"] // 1, s["x0"]))
    # ---- bloques por espacio (por el centro de su caja); el espacio mas pequeno que lo contiene
    fuera = collections.Counter()
    for s in espacios:
        s["productos"] = collections.Counter()
    for b in bloques:
        cont = [s for s in espacios if dentro(b["cx"], b["cy"], s["_pts"])]
        if cont:
            min(cont, key=lambda s: s["area"])["productos"][b["n"]] += 1
        else:
            fuera[b["n"]] += 1
    # ---- unidades y sanidad
    ins = r(lambda: doc.GetVariable("INSUNITS"))
    tam = [max(b["w"], b["h"]) for b in bloques if b["w"] is not None and max(b["w"], b["h"]) > 0]
    aviso = None
    if tam:
        med = statistics.median(tam)
        if ins == 4 and med < 5:
            aviso = (f"El dibujo dice milimetros pero los bloques miden ~{med:.2f}: las medidas parecen estar en METROS. "
                     "Confirma las unidades antes de ubicar o adaptar productos.")
        elif ins == 6 and med > 100:
            aviso = (f"El dibujo dice metros pero los bloques miden ~{med:.0f}: las medidas parecen estar en MILIMETROS. "
                     "Confirma las unidades antes de ubicar o adaptar productos.")
    xs = [b["cx"] for b in bloques] + [s[k] for s in espacios for k in ("x0", "x1")]
    ys = [b["cy"] for b in bloques] + [s[k] for s in espacios for k in ("y0", "y1")]
    out_esp = []
    for s in espacios[:max_espacios]:
        d = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items() if not k.startswith("_") and k != "productos"}
        d["productos"] = dict(s["productos"].most_common(15))
        out_esp.append(d)
    por_nombre = collections.Counter(b["n"] for b in bloques)
    return {
        "ok": True, "solo_lectura": True,
        "unidades": {"insunits": ins, "nombre": UNIDADES.get(ins, str(ins)), "aviso": aviso},
        "objetos": total, "leidos": min(total, limite), "truncado": total > limite, "tipos": dict(tipos.most_common(10)),
        "extension": [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)] if xs else None,
        "espacios_total": len(espacios), "espacios": out_esp, "espacios_omitidos": max(0, len(espacios) - max_espacios),
        "poligonos_cerrados_sin_texto": len(polis) - len(asignado),
        "bloques_total": len(bloques), "bloques_por_nombre": dict(por_nombre.most_common(60)),
        "bloques_fuera_de_espacios": dict(fuera.most_common(30)),
        "nota": "Los espacios se detectan como poligonos cerrados con un texto dentro (plantas simples). En planos reales con "
                "paredes sueltas puede no detectarse ninguno: en ese caso hay que confirmar los espacios con la persona. "
                "Los nombres pueden ser datos del cliente: no mostrarlos en el chat si el plano es real.",
    }


def elegir_doc(docs, contiene, activo):
    if not contiene:
        return activo, None
    t = re.sub(r"[^a-z0-9]", "", str(contiene).casefold())
    hallados = [d for d in docs if t in re.sub(r"[^a-z0-9]", "", str(d.Name).casefold())]
    if len(hallados) == 1:
        return hallados[0], None
    return None, f"{len(hallados)} documentos abiertos coinciden con '{contiene}' (se necesita exactamente 1)."


def main():
    args = json.loads(sys.argv[1])
    try:
        import pythoncom
        import win32com.client
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "sin_pywin32", "detalle": str(e)}
    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
        docs = reintentar(lambda: list(app.Documents))
        activo = reintentar(lambda: app.ActiveDocument)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto con un dibujo activo."}
    doc, err = elegir_doc(docs, args.get("destino_contiene"), activo)
    if err:
        return {"ok": False, "error": "destino_no_valido", "detalle": err}
    try:
        return analizar(doc, int(args.get("limite_objetos", 20000)), int(args.get("max_espacios", 60)), reintentar)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "fallo_al_leer", "detalle": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, default=str))
