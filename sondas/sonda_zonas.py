"""Sonda de LECTURA CRUDA del plano activo para el escaner de zonas (SOLO LECTURA; proceso aparte).

Devuelve datos, no conclusiones: unidades, textos, poligonos cerrados y bloques con su caja. Toda la inteligencia (vocabulario,
roles, tipologia) vive en zonas_motor.py, que se prueba sin AutoCAD. Aqui no hay nombres ni coordenadas de ningun proyecto.

Usa filtros nativos de AutoCAD (seleccion global por tipo) y no la seleccion por ventana (que solo ve la vista actual).
Tambien entra un nivel en bloques "contenedor" (base, arq, planta...) porque muchos planos traen la arquitectura dentro de un bloque.
Argumento (JSON en argv[1], opcional): {"tiempo_max_s": n}
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # -I no incluye la raiz del proyecto

import zonas_motor  # noqa: E402

UNIDAD_A_METROS = {1: 0.0254, 2: 0.3048, 3: 1609.344, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 10: 0.9144, 14: 0.1, 15: 10.0, 16: 100.0}
CAPAS_PROPIAS = ("SCH_ILUMINACION", "SCH_AUDIO")           # lo que colocamos nosotros no es mobiliario del proyecto
MAX_TEXTOS, MAX_POLI, MAX_BLOQUES, MAX_VERTICES = 8000, 6000, 8000, 200


def _rechazada(ex) -> bool:
    """AutoCAD ocupado: 'llamada rechazada', o un AttributeError de COM ('Add.Count', '<unknown>.Item') cuando devuelve un objeto sin respuesta."""
    t = str(ex).lower()
    if "-2147418111" in t or "rechazada" in t or "rejected" in t:
        return True
    return isinstance(ex, AttributeError) and "has no attribute" not in t and " " not in t.strip()


def reintentar(fn, intentos=8, espera=1.0):
    for i in range(intentos):
        try:
            return fn()
        except Exception as ex:
            if not _rechazada(ex) or i == intentos - 1:
                raise
            time.sleep(espera)


def _filtro(tipos, valores):
    import pythoncom
    from win32com.client import VARIANT
    return (VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_I2, tuple(tipos)),
            VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, tuple(valores)))


def _seleccion(doc, nombre, dxf):
    nombre = f"{nombre}_{os.getpid()}"       # unico por proceso: varios procesos a la vez no se pisan
    try:
        doc.SelectionSets.Item(nombre).Delete()
    except Exception:
        pass
    ss = doc.SelectionSets.Add(nombre)
    ft, fd = _filtro([0], [dxf])
    ss.Select(5, None, None, ft, fd)
    return ss


class Transformacion:
    """Lleva puntos de un bloque contenedor a coordenadas del plano (traslacion + rotacion + escala uniforme)."""

    def __init__(self, ref=None):
        if ref is None:
            self.ox = self.oy = 0.0
            self.c, self.s, self.k = 1.0, 0.0, 1.0
        else:
            ip = ref.InsertionPoint
            self.ox, self.oy = float(ip[0]), float(ip[1])
            r = float(ref.Rotation)
            self.c, self.s = math.cos(r), math.sin(r)
            try:
                self.k = float(ref.XScaleFactor)
            except Exception:
                self.k = 1.0

    def punto(self, x, y):
        return (self.ox + self.k * (self.c * x - self.s * y), self.oy + self.k * (self.s * x + self.c * y))

    def caja(self, a, b):
        pts = [self.punto(x, y) for x in (a[0], b[0]) for y in (a[1], b[1])]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def _posicion_texto(e):
    try:
        if getattr(e, "Alignment", 0) != 0:
            tap = getattr(e, "TextAlignmentPoint", None)
            if tap and (abs(tap[0]) > 0.001 or abs(tap[1]) > 0.001):
                return float(tap[0]), float(tap[1])
    except Exception:
        pass
    p = e.InsertionPoint
    return float(p[0]), float(p[1])


def _poligono(e, tr):
    """Lista de vertices si la polilinea es cerrada (o su ultimo punto repite el primero); None si no."""
    on = str(e.ObjectName)
    if on not in ("AcDbPolyline", "AcDb2dPolyline"):
        return None
    c = list(e.Coordinates)
    paso = 3 if on == "AcDb2dPolyline" else 2
    pts = [(c[i], c[i + 1]) for i in range(0, len(c) - paso + 1, paso)]
    if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) < 1e-9 and abs(pts[0][1] - pts[-1][1]) < 1e-9:
        pts = pts[:-1]
        cerrada = True
    else:
        cerrada = bool(getattr(e, "Closed", False))
    if not cerrada or len(pts) < 3:
        return None
    if len(pts) > MAX_VERTICES:                       # recintos con curvas muy densas: se resumen por su caja
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        pts = [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]
    return [tr.punto(x, y) for x, y in pts]


def leer(doc, args) -> dict:
    t0 = time.time()
    limite = float(args.get("tiempo_max_s") or 40)
    vocab = zonas_motor.cargar_vocabulario()
    try:
        ins = int(reintentar(lambda: doc.GetVariable("INSUNITS")))
    except Exception:
        ins = 0
    unidad_m = UNIDAD_A_METROS.get(ins, 1.0)
    aviso_unidades = None if ins in UNIDAD_A_METROS else "El dibujo no tiene unidades (INSUNITS=0): se asumen metros."
    textos, poligonos, bloques, contenedores, avisos = [], [], [], [], []
    if aviso_unidades:
        avisos.append(aviso_unidades)
    id_ident = Transformacion()

    def agregar_texto(e, tr):
        if len(textos) >= MAX_TEXTOS:
            return
        s = zonas_motor.limpiar_texto(e.TextString)
        if s:
            x, y = _posicion_texto(e)
            x, y = tr.punto(x, y)
            textos.append({"t": s, "x": round(x, 3), "y": round(y, 3), "capa": str(e.Layer)})

    def agregar_poligono(e, tr):
        if len(poligonos) >= MAX_POLI:
            return
        pts = _poligono(e, tr)
        if pts:
            poligonos.append({"capa": str(e.Layer), "pts": [[round(x, 3), round(y, 3)] for x, y in pts]})

    def agregar_bloque(e, tr):
        if len(bloques) >= MAX_BLOQUES or str(e.Layer) in CAPAS_PROPIAS:
            return
        a, b = e.GetBoundingBox()
        x0, y0, x1, y1 = tr.caja(a, b)
        if (x1 - x0) * unidad_m > 200 or (y1 - y0) * unidad_m > 200:
            return                                        # contenedores enormes o geometria lejana: no son mobiliario
        bloques.append({"n": str(e.EffectiveName), "capa": str(e.Layer), "x0": round(x0, 3), "y0": round(y0, 3),
                        "x1": round(x1, 3), "y1": round(y1, 3)})

    # ---- espacio modelo
    ss = _seleccion(doc, "SS_ZONAS_TXT", "TEXT,MTEXT")
    try:
        for i in range(ss.Count):
            try:
                agregar_texto(ss.Item(i), id_ident)
            except Exception:
                pass
    finally:
        ss.Delete()
    ss = _seleccion(doc, "SS_ZONAS_POLI", "LWPOLYLINE,POLYLINE")
    try:
        for i in range(ss.Count):
            if time.time() - t0 > limite:
                avisos.append("Tiempo agotado leyendo polilineas: lectura parcial.")
                break
            try:
                agregar_poligono(ss.Item(i), id_ident)
            except Exception:
                pass
    finally:
        ss.Delete()
    ss = _seleccion(doc, "SS_ZONAS_BLK", "INSERT")
    try:
        n_inserts = ss.Count
        for i in range(n_inserts):
            if time.time() - t0 > limite:
                avisos.append("Tiempo agotado leyendo bloques: lectura parcial.")
                break
            try:
                e = ss.Item(i)
                nombre = str(e.EffectiveName)
                if vocab.contenedores.search(nombre) and len(contenedores) < 3:
                    contenedores.append(e)
                agregar_bloque(e, id_ident)
                if vocab.capas_rotulos.search(str(e.Layer)) and getattr(e, "HasAttributes", False):
                    for at in e.GetAttributes():           # rotulos de ambiente guardados como atributos
                        s = zonas_motor.limpiar_texto(at.TextString)
                        if s and len(textos) < MAX_TEXTOS:
                            ip = at.InsertionPoint
                            textos.append({"t": s, "x": round(float(ip[0]), 3), "y": round(float(ip[1]), 3), "capa": str(e.Layer)})
            except Exception:
                pass
    finally:
        ss.Delete()

    # ---- un nivel dentro de bloques contenedor (arquitectura dentro de un bloque)
    dentro = 0
    for ref in contenedores:
        try:
            defn = doc.Blocks.Item(str(ref.EffectiveName))
            if defn.Count < 30:
                continue
            tr = Transformacion(ref)
            for j in range(min(defn.Count, 3000)):
                if time.time() - t0 > limite:
                    break
                try:
                    sub = defn.Item(j)
                    on = str(sub.ObjectName)
                    if on in ("AcDbText", "AcDbMText"):
                        agregar_texto(sub, tr)
                    elif on in ("AcDbPolyline", "AcDb2dPolyline"):
                        agregar_poligono(sub, tr)
                    elif on == "AcDbBlockReference":
                        agregar_bloque(sub, tr)
                    else:
                        continue
                    dentro += 1
                except Exception:
                    pass
        except Exception:
            pass
    return {"ok": True, "plano": str(doc.Name), "unidad_m": unidad_m, "insunits": ins, "n_objetos": int(doc.ModelSpace.Count),
            "textos": textos, "poligonos": poligonos, "bloques": bloques, "contenedores_leidos": len(contenedores),
            "elementos_en_contenedores": dentro, "avisos": avisos, "tiempo_lectura_s": round(time.time() - t0, 2)}


def main() -> dict:
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
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
    except Exception:
        return {"ok": False, "error": "autocad_no_abierto", "detalle": "No encontre AutoCAD abierto con un dibujo activo."}
    try:
        return reintentar(lambda: leer(doc, args))
    except Exception as e:
        return {"ok": False, "error": "fallo_lectura", "detalle": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=True, default=str))
