"""Sonda de LECTURA CRUDA del plano activo para el escaner de zonas (SOLO LECTURA; proceso aparte).

Devuelve datos, no conclusiones: unidades, textos, poligonos cerrados y bloques con su caja. Toda la inteligencia (vocabulario,
roles, tipologia) vive en zonas_motor.py, que se prueba sin AutoCAD. Aqui no hay nombres ni coordenadas de ningun proyecto.

Usa filtros nativos de AutoCAD (seleccion global por tipo) y no la seleccion por ventana (que solo ve la vista actual).
Tambien entra un nivel en bloques "contenedor" (base, arq, planta...) porque muchos planos traen la arquitectura dentro de un bloque.
Argumento (JSON en argv[1], opcional): {"tiempo_max_s": n}
"""
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # -I no incluye la raiz del proyecto

import zonas_motor  # noqa: E402

UNIDAD_A_METROS = {1: 0.0254, 2: 0.3048, 3: 1609.344, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 10: 0.9144, 14: 0.1, 15: 10.0, 16: 100.0}
CAPAS_PROPIAS = ("SCH_ILUMINACION", "SCH_AUDIO", "SCH_REVISION")           # lo que colocamos nosotros no es mobiliario NI arquitectura del proyecto:
# los contornos de revision (SCH_REVISION) se releian como poligonos y textos del plano y contaminaban el escaneo siguiente (bucle de retroalimentacion)
MAX_TEXTOS, MAX_POLI, MAX_BLOQUES, MAX_VERTICES = 8000, 6000, 8000, 200
MAX_LINEAS, PRESUPUESTO_CONTENEDORES_S, MAX_ENTIDADES_CONTENEDOR = 15000, 40.0, 9000   # lineas y trazos de bloques contenedor (la arquitectura suele ir dentro de uno)
MAX_LINEAS_MODELO, PRESUPUESTO_LINEAS_MODELO_S = 8000, 12.0   # lineas y lados de polilineas del ESPACIO MODELO (planos sin capas de muros ni bloque contenedor)
PRESUPUESTO_TEXTOS_S = 20.0                      # los textos son lo mas caro de leer (varias llamadas COM cada uno)
MAX_MUROS, PRESUPUESTO_MUROS_S = 8000, 12.0     # entidades de capas de muros que se leen, con tope de tiempo
MAX_DEFINICIONES, MAX_ENTIDADES_DEFINICION, PRESUPUESTO_DEFINICIONES_S = 25, 300, 10.0     # definiciones sin rol que se abren, con tope de tiempo
TIPO_ENTIDAD = {"AcDbCircle": "circulos", "AcDbArc": "arcos", "AcDbLine": "lineas", "AcDbPolyline": "poli", "AcDb2dPolyline": "poli",
                "AcDbBlockReference": "bloques", "AcDbHatch": "rellenos", "AcDbText": "textos", "AcDbMText": "textos"}


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


def _seleccion(doc, nombre, dxf, capas=None):
    nombre = f"{nombre}_{os.getpid()}"       # unico por proceso: varios procesos a la vez no se pisan
    try:
        doc.SelectionSets.Item(nombre).Delete()
    except Exception:
        pass
    ss = doc.SelectionSets.Add(nombre)
    ft, fd = _filtro([0, 8], [dxf, capas]) if capas else _filtro([0], [dxf])
    ss.Select(5, None, None, ft, fd)
    return ss


def _leer_muros(doc, palabras, t0, limite, avisos):
    """Segmentos de las capas de MUROS (lineas y polilineas), por nombre de capa del vocabulario (editable). Es la materia prima para reconstruir
    recintos aunque el plano no traiga rotulos ni polilineas de habitacion. Acotado en entidades y en tiempo; lo que no cabe se avisa."""
    if not palabras:
        return {"segmentos": [], "capas": {}, "entidades": 0, "truncado": False}
    filtro = ",".join(f"*{w}*" for w in palabras)
    segmentos, capas = [], {}
    try:
        ss = _seleccion(doc, "SS_ZONAS_MUR", "LINE,LWPOLYLINE,POLYLINE", filtro)
    except Exception:
        return {"segmentos": [], "capas": {}, "entidades": 0, "truncado": False}
    t_m = time.time()
    try:
        n = ss.Count
        leidas = 0
        for i in range(min(n, MAX_MUROS)):
            if time.time() - t_m > PRESUPUESTO_MUROS_S or time.time() - t0 > limite:
                avisos.append("Tiempo agotado leyendo muros: la reconstruccion de recintos usa solo parte de ellos.")
                break
            try:
                e = ss.Item(i)
                on = str(e.ObjectName)
                if on == "AcDbLine":
                    a, b = e.StartPoint, e.EndPoint
                    segmentos.append([round(float(a[0]), 4), round(float(a[1]), 4), round(float(b[0]), 4), round(float(b[1]), 4)])
                else:
                    c = list(e.Coordinates)
                    paso = 3 if on == "AcDb2dPolyline" else 2
                    pts = [(c[k], c[k + 1]) for k in range(0, len(c) - paso + 1, paso)]
                    if getattr(e, "Closed", False) and len(pts) > 2:
                        pts.append(pts[0])
                    for k in range(len(pts) - 1):
                        segmentos.append([round(pts[k][0], 4), round(pts[k][1], 4), round(pts[k + 1][0], 4), round(pts[k + 1][1], 4)])
                if leidas < 400:                                    # el desglose por capa se toma de una muestra (cada lectura de capa es una llamada COM)
                    capas[str(e.Layer)] = capas.get(str(e.Layer), 0) + 1
                leidas += 1
            except Exception:
                pass
        if n > MAX_MUROS:
            avisos.append(f"Hay {n} entidades en capas de muros: solo se leyeron las primeras {MAX_MUROS}.")
        return {"segmentos": segmentos, "capas": capas, "entidades": int(n), "truncado": n > MAX_MUROS}
    finally:
        ss.Delete()


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


def _leer_definicion(doc, nombre):
    """Contenido de UNA definicion de bloque (no de cada instancia): nombres de bloques anidados, capas internas y conteo por tipo de entidad.
    Es lo que permite reconocer un mueble anonimo (p. ej. un bloque con nombre generico que por dentro contiene el dibujo de una cama). Acotado en entidades."""
    try:
        defn = doc.Blocks.Item(nombre)
        total = int(defn.Count)
    except Exception:
        return None
    anidados, capas, n, textos = set(), set(), {}, []
    leidas = min(total, MAX_ENTIDADES_DEFINICION)
    for j in range(leidas):
        try:
            sub = defn.Item(j)
            on = str(sub.ObjectName)
            tipo = TIPO_ENTIDAD.get(on, "otros")
            n[tipo] = n.get(tipo, 0) + 1
            capas.add(str(sub.Layer))
            if on == "AcDbBlockReference":
                anidados.add(str(sub.EffectiveName))
            elif on in ("AcDbText", "AcDbMText") and len(textos) < 6:
                s = " ".join(str(sub.TextString).split())[:60]          # textos dentro del bloque: a menudo traen el nombre del mueble o del equipo
                if s:
                    textos.append(s)
        except Exception:
            pass
    return {"anidados": sorted(anidados)[:20], "capas": sorted(capas)[:20], "textos": textos, "n": n, "total": total, "leidas": leidas}


RELACION_TRAZO = 8.0       # un rectangulo cuyo largo es >= 8 veces su ancho es un TRAZO (lineas de un PDF importado: cada linea es un rectangulo finisimo)


def _eje_de_trazo(pts):
    """Si los 4 vertices forman un rectangulo fino (un trazo), devuelve su EJE ((x1,y1),(x2,y2)); si no, None. Los trazos de un PDF vectorizado traen dos lados
    largos y dos diminutos: tratarlos como 4 segmentos hunde la mediana de longitudes y esconde los muros; como UN eje conservan su longitud real."""
    if len(pts) != 4:
        return None
    l = [math.hypot(pts[(i + 1) % 4][0] - pts[i][0], pts[(i + 1) % 4][1] - pts[i][1]) for i in range(4)]
    a, b = l[0], l[1]
    if min(a, b) <= 1e-9 or abs(a - l[2]) > 0.2 * max(a, l[2], 1e-9) or abs(b - l[3]) > 0.2 * max(b, l[3], 1e-9):
        return None
    if max(a, b) < RELACION_TRAZO * min(a, b):
        return None
    if a < b:                                       # lados cortos: p0-p1 y p2-p3
        m1 = ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
        m2 = ((pts[2][0] + pts[3][0]) / 2, (pts[2][1] + pts[3][1]) / 2)
    else:                                           # lados cortos: p1-p2 y p3-p0
        m1 = ((pts[1][0] + pts[2][0]) / 2, (pts[1][1] + pts[2][1]) / 2)
        m2 = ((pts[3][0] + pts[0][0]) / 2, (pts[3][1] + pts[0][1]) / 2)
    return m1, m2


def _procesar_polilinea(e, on, tr):
    """UNA sola lectura COM de una polilinea (capa, coordenadas, si es cerrada) -> (poligono|None, segmentos, capa). Antes se leia dos veces (poligono y
    segmentos): con miles de trazos de un PDF eso duplicaba el tiempo. Los trazos finos devuelven UN segmento (su eje); el resto, sus lados."""
    capa = str(e.Layer)
    c = list(e.Coordinates)
    paso = 3 if on == "AcDb2dPolyline" else 2
    pts = [(c[i], c[i + 1]) for i in range(0, len(c) - paso + 1, paso)]
    if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) < 1e-9 and abs(pts[0][1] - pts[-1][1]) < 1e-9:
        pts, cerrada = pts[:-1], True
    elif len(pts) == 4:
        cerrada = True if _eje_de_trazo(pts) else bool(getattr(e, "Closed", False))      # un rectangulo fino de 4 vertices es un trazo cerrado: se evita leer Closed
    else:
        cerrada = bool(getattr(e, "Closed", False))
    tp = [tr.punto(x, y) for x, y in pts]
    segs = []
    eje = _eje_de_trazo(pts) if cerrada else None
    if eje:
        a, b = tr.punto(*eje[0]), tr.punto(*eje[1])
        segs.append([round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4), capa])
    else:
        cerr = tp + [tp[0]] if cerrada and len(tp) > 2 else tp
        for k in range(len(cerr) - 1):
            segs.append([round(cerr[k][0], 4), round(cerr[k][1], 4), round(cerr[k + 1][0], 4), round(cerr[k + 1][1], 4), capa])
    poligono = None
    if cerrada and len(tp) >= 3:
        if len(tp) > MAX_VERTICES:
            xs, ys = [q[0] for q in tp], [q[1] for q in tp]
            tp = [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]
        poligono = [[round(x, 3), round(y, 3)] for x, y in tp]
    return poligono, segs, capa


def _ruta_cache_contenedor(cache_dir, doc, ref, defn):
    """Archivo de cache de UN bloque contenedor: depende del dibujo, de la instancia (su handle) y de cuantas entidades tiene la definicion (si cambia, vale otra)."""
    if not cache_dir:
        return None
    try:
        clave = hashlib.sha1(f"{doc.Name}|{ref.Handle}|{int(defn.Count)}".encode("utf-8")).hexdigest()[:16]
        return Path(cache_dir) / f"cont_{clave}.json"
    except Exception:
        return None


HUELLA_MUESTRAS, HUELLA_ULTIMAS = 80, 20


def _huella_contenedor(defn, total):
    """Huella barata (~1 s) del INTERIOR de un bloque: capa y coordenadas de 80 entidades repartidas y de las 20 ultimas. La cache se invalida si cambia. Es una
    red de seguridad, no una garantia: una edicion de pocas lineas puede no estar en la muestra; por eso forzar_recarga=True RELEE el bloque entero."""
    h = hashlib.sha1()
    n = min(HUELLA_MUESTRAS, total)
    indices = sorted({(k * total) // n for k in range(n)} | set(range(max(0, total - HUELLA_ULTIMAS), total)))
    for j in indices:
        try:
            sub = defn.Item(j)
            on = str(sub.ObjectName)
            h.update(f"{j}|{on}|{sub.Layer}".encode("utf-8"))
            if on in ("AcDbPolyline", "AcDb2dPolyline"):
                h.update(repr([round(float(v), 3) for v in sub.Coordinates]).encode())
            elif on == "AcDbLine":
                h.update(repr([round(float(v), 3) for v in list(sub.StartPoint) + list(sub.EndPoint)]).encode())
        except Exception:
            h.update(b"?")
    return h.hexdigest()[:16]


def _cargar_cache_contenedor(ruta):
    try:
        if ruta is not None and ruta.is_file():
            d = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(d, dict) and "leidas" in d:
                return d
    except (OSError, ValueError):
        pass
    return None


def _guardar_cache_contenedor(ruta, datos):
    """Escritura atomica. Un fallo de disco no rompe el escaneo (solo se pierde el avance)."""
    if ruta is None:
        return
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos), encoding="utf-8")
        os.replace(tmp, ruta)
    except OSError:
        pass


def _agregar_segmentos(e, on, tr, salida):
    """Segmentos [x1, y1, x2, y2, capa] de una LINEA o de una polilinea (abierta o cerrada), llevados a coordenadas del plano. Para planos sin capas de muros."""
    capa = str(e.Layer)
    if on == "AcDbLine":
        a, b = e.StartPoint, e.EndPoint
        p1, p2 = tr.punto(float(a[0]), float(a[1])), tr.punto(float(b[0]), float(b[1]))
        salida.append([round(p1[0], 4), round(p1[1], 4), round(p2[0], 4), round(p2[1], 4), capa])
        return
    c = list(e.Coordinates)
    paso = 3 if on == "AcDb2dPolyline" else 2
    pts = [tr.punto(c[k], c[k + 1]) for k in range(0, len(c) - paso + 1, paso)]
    if getattr(e, "Closed", False) and len(pts) > 2:
        pts.append(pts[0])
    for k in range(len(pts) - 1):
        salida.append([round(pts[k][0], 4), round(pts[k][1], 4), round(pts[k + 1][0], 4), round(pts[k + 1][1], 4), capa])


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
        if len(textos) >= MAX_TEXTOS or str(e.Layer) in CAPAS_PROPIAS:
            return
        s = zonas_motor.limpiar_texto(e.TextString)
        if s:
            x, y = _posicion_texto(e)
            x, y = tr.punto(x, y)
            textos.append({"t": s, "x": round(x, 3), "y": round(y, 3), "capa": str(e.Layer)})

    def agregar_poligono(e, tr):
        if len(poligonos) >= MAX_POLI or str(e.Layer) in CAPAS_PROPIAS:
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
    t_txt = time.time()
    try:
        for i in range(ss.Count):
            if time.time() - t_txt > PRESUPUESTO_TEXTOS_S or time.time() - t0 > limite:
                avisos.append(f"Tiempo agotado leyendo textos ({i} de {ss.Count}): los nombres de espacios pueden estar incompletos.")
                break
            try:
                agregar_texto(ss.Item(i), id_ident)
            except Exception:
                pass
    finally:
        ss.Delete()
    lineas_modelo = []
    ss = _seleccion(doc, "SS_ZONAS_POLI", "LWPOLYLINE,POLYLINE")
    try:
        for i in range(ss.Count):
            if time.time() - t0 > limite:
                avisos.append("Tiempo agotado leyendo polilineas: lectura parcial.")
                break
            try:
                e = ss.Item(i)
                on = str(e.ObjectName)
                if on not in ("AcDbPolyline", "AcDb2dPolyline"):
                    continue
                poli, segs_p, capa_p = _procesar_polilinea(e, on, id_ident)        # una sola lectura: poligono Y lados (con su capa)
                if capa_p in CAPAS_PROPIAS:
                    continue
                if poli and len(poligonos) < MAX_POLI:
                    poligonos.append({"capa": capa_p, "pts": [[round(x, 3), round(y, 3)] for x, y in poli]})
                if len(lineas_modelo) < MAX_LINEAS_MODELO:
                    lineas_modelo.extend(segs_p)
            except Exception:
                pass
    finally:
        ss.Delete()
    ss = _seleccion(doc, "SS_ZONAS_LIN", "LINE")                     # lineas sueltas del modelo (muros dibujados como lineas en cualquier capa)
    t_lin = time.time()
    try:
        for i in range(ss.Count):
            if time.time() - t_lin > PRESUPUESTO_LINEAS_MODELO_S or time.time() - t0 > limite or len(lineas_modelo) >= MAX_LINEAS_MODELO:
                avisos.append(f"Lineas del modelo: lectura parcial ({i} de {ss.Count}).")
                break
            try:
                e = ss.Item(i)
                if str(e.Layer) in CAPAS_PROPIAS:
                    continue
                _agregar_segmentos(e, "AcDbLine", id_ident, lineas_modelo)
            except Exception:
                pass
    finally:
        ss.Delete()
    candidatos_cont = []
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
                if vocab.contenedores.search(nombre) and str(e.Layer) not in CAPAS_PROPIAS and len(candidatos_cont) < 60:
                    candidatos_cont.append((e, nombre))        # NO se decide aqui: "Architectural" (luminarias) tambien casa con el vocabulario
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

    # contenedores: de los bloques cuyo nombre casa con el vocabulario, los de MAS entidades (el plano es el bloque grande; una luminaria llamada
    # "Architectural" tiene 7). Antes se tomaban los 3 primeros por orden y unas piezas colocadas ocupaban los cupos y dejaban el plano sin leer.
    pesos = {}
    for e_, n_ in candidatos_cont:
        if n_ not in pesos:
            try:
                pesos[n_] = int(reintentar(lambda: doc.Blocks.Item(n_).Count))
            except Exception:
                pesos[n_] = 0
    candidatos_cont.sort(key=lambda c: -pesos.get(c[1], 0))
    contenedores = [e_ for e_, n_ in candidatos_cont if pesos.get(n_, 0) >= 30][:3]
    # ---- un nivel dentro de bloques contenedor (arquitectura dentro de un bloque). Ademas de textos, poligonos y bloques se leen las LINEAS y trazos (abiertos
    # o cerrados) con su capa: son la materia prima de los muros cuando el plano no los trae en el espacio modelo.
    dentro, lineas, trunc_lineas, leidas_cont = 0, [], False, 0
    cont_completos, cont_incompletos, cont_errores = 0, 0, 0
    t_cont = time.time()
    for ref in contenedores:
        nombre_ref = "?"
        try:
            nombre_ref = str(reintentar(lambda: ref.EffectiveName))
            defn = reintentar(lambda: doc.Blocks.Item(nombre_ref))
            n_defn = int(reintentar(lambda: defn.Count))
            if n_defn < 30:
                avisos.append(f"Bloque contenedor '{nombre_ref}' omitido: tiene solo {n_defn} entidades (menos de 30).")
                continue
            tr = Transformacion(ref)
            total_def = min(n_defn, MAX_ENTIDADES_CONTENEDOR)
            ruta_cache = _ruta_cache_contenedor(args.get("cache_dir"), doc, ref, defn)
            previo = _cargar_cache_contenedor(ruta_cache)           # lectura PROGRESIVA: lo ya leido en un escaneo anterior no se vuelve a leer
            huella = _huella_contenedor(defn, total_def)
            if previo and previo.get("huella") != huella:
                previo = None                                       # el interior cambio (o la cache es de una version sin huella): se relee completo
                avisos.append(f"El interior del bloque '{nombre_ref}' cambio desde el ultimo escaneo: se lee de nuevo completo.")
            elif previo and args.get("ignorar_cache_bloque") and previo.get("completo"):
                previo = None                                       # forzar_recarga: se vuelve a medir TODO (una lectura incompleta si se continua, para no reiniciar siempre)
            j0 = 0
            if previo:
                textos.extend(previo.get("textos", []))
                poligonos.extend(previo.get("poligonos", []))
                bloques.extend(previo.get("bloques", []))
                lineas.extend(previo.get("lineas", []))
                dentro += int(previo.get("dentro", 0))
                j0 = int(previo.get("leidas", 0))
                leidas_cont += j0
                if previo.get("completo") or j0 >= total_def:
                    cont_completos += 1
                    continue
            marca = (len(textos), len(poligonos), len(bloques), len(lineas))
            dentro0, procesadas = dentro, j0
            for j in range(j0, total_def):
                if time.time() - t0 > limite or time.time() - t_cont > PRESUPUESTO_CONTENEDORES_S:
                    break
                try:
                    sub = defn.Item(j)
                    on = str(sub.ObjectName)
                    leidas_cont += 1
                    if on in ("AcDbText", "AcDbMText"):
                        agregar_texto(sub, tr)
                    elif on in ("AcDbPolyline", "AcDb2dPolyline"):
                        poli, segs_p, capa_p = _procesar_polilinea(sub, on, tr)       # una sola lectura: poligono Y segmentos
                        if poli and len(poligonos) < MAX_POLI:
                            poligonos.append({"capa": capa_p, "pts": poli})
                        lineas.extend(segs_p)
                    elif on == "AcDbLine":
                        _agregar_segmentos(sub, on, tr, lineas)
                    elif on == "AcDbBlockReference":
                        agregar_bloque(sub, tr)
                    else:
                        procesadas = j + 1
                        continue
                    dentro += 1
                except Exception:
                    pass
                procesadas = j + 1
                if len(lineas) >= MAX_LINEAS:
                    trunc_lineas = True
                    avisos.append(f"Mas de {MAX_LINEAS} lineas dentro del bloque contenedor: solo se usan las primeras.")
                    break
            completo = procesadas >= total_def or trunc_lineas
            if completo:
                cont_completos += 1
            else:
                cont_incompletos += 1
                avisos.append(f"Lectura PARCIAL del interior de un bloque contenedor ({procesadas} de {defn.Count} entidades). Repite el escaneo con "
                              "forzar_recarga=True: continua donde quedo y lo completa.")
            _guardar_cache_contenedor(ruta_cache, {
                "leidas": procesadas, "completo": completo, "dentro": dentro, "huella": huella,
                "textos": (previo or {}).get("textos", []) + textos[marca[0]:], "poligonos": (previo or {}).get("poligonos", []) + poligonos[marca[1]:],
                "bloques": (previo or {}).get("bloques", []) + bloques[marca[2]:], "lineas": (previo or {}).get("lineas", []) + lineas[marca[3]:]})
        except Exception as ex:
            # nunca en silencio: un contenedor que no se pudo leer deja el plano SIN muros y el resultado parece valido
            cont_errores += 1
            avisos.append(f"ERROR leyendo el bloque contenedor '{nombre_ref}': {type(ex).__name__}: {str(ex)[:140]}. El plano puede quedar sin muros: repite con forzar_recarga=True.")
    # ---- muros (capas con nombre de muro/tabique/pared/columna...): materia prima de los recintos por geometria
    muros = _leer_muros(doc, list(vocab.datos.get("capas_muros") or []), t0, limite, avisos)

    # ---- definiciones de los bloques SIN rol conocido (por vocabulario): una lectura por definicion, las mas grandes primero, con presupuesto de tiempo
    candidatas = {}
    for b in bloques:
        n = b["n"]
        if n in candidatas or n.startswith("*"):
            continue
        w, h = (b["x1"] - b["x0"]) * unidad_m, (b["y1"] - b["y0"]) * unidad_m
        if min(w, h) < 0.4 or vocab.contenedores.search(n):
            continue                                    # demasiado pequeno, o es el propio bloque contenedor (el plano), no un mueble
        rol, ign = zonas_motor.rol_de_bloque(n, b["capa"], vocab, {})
        if rol or ign:
            continue
        candidatas[n] = w * h
    definiciones, t_def = {}, time.time()
    orden = sorted(candidatas, key=lambda k: -candidatas[k])
    for n in orden[:MAX_DEFINICIONES]:
        if time.time() - t_def > PRESUPUESTO_DEFINICIONES_S or time.time() - t0 > limite:
            avisos.append("Tiempo agotado leyendo definiciones de bloques: clasificacion parcial.")
            break
        info = _leer_definicion(doc, n)
        if info:
            definiciones[n] = info
    if len(orden) > MAX_DEFINICIONES:
        avisos.append(f"Solo se abrieron las {MAX_DEFINICIONES} definiciones mas grandes de {len(orden)} bloques sin rol conocido.")
    return {"ok": True, "plano": str(doc.Name), "unidad_m": unidad_m, "insunits": ins, "n_objetos": int(doc.ModelSpace.Count),
            "textos": textos, "poligonos": poligonos, "bloques": bloques, "definiciones": definiciones, "muros": muros, "lineas": {"segmentos": lineas + lineas_modelo, "truncado": trunc_lineas, "entidades_leidas": leidas_cont, "del_modelo": len(lineas_modelo)},
            "lectura": {"contenedores_completos": cont_completos, "contenedores_incompletos": cont_incompletos, "contenedores_con_error": cont_errores}, "contenedores_leidos": len(contenedores),
            "elementos_en_contenedores": dentro, "avisos": avisos, "tiempo_lectura_s": round(time.time() - t0, 2)}


def inventario(doc, args) -> dict:
    """SOLO LECTURA: que hay en el espacio modelo, por capa y tipo de objeto, y como estan dibujados los posibles MUROS (rellenos/achurados, solidos, polilineas con
    grosor, lineas). Sirve para decidir como leer la arquitectura de un plano nuevo."""
    t0 = time.time()
    limite = float(args.get("tiempo_max_s") or 40)
    maximo = int(args.get("max_entidades") or 20000)
    ms = doc.ModelSpace
    total = int(reintentar(lambda: ms.Count))
    capas, rellenos, anchas = {}, [], {}
    leidas = 0
    for i in range(min(total, maximo)):
        if time.time() - t0 > limite:
            break
        try:
            e = ms.Item(i)
            on = str(e.ObjectName).replace("AcDb", "")
            capa = str(e.Layer)
        except Exception:
            continue
        leidas += 1
        d = capas.setdefault(capa, {})
        d[on] = d.get(on, 0) + 1
        try:
            if on == "Hatch":
                a, b = e.GetBoundingBox()
                rellenos.append({"capa": capa, "patron": str(e.PatternName), "area": round(float(e.Area), 3), "caja": [round(float(a[0]), 2), round(float(a[1]), 2),
                                                                                                                     round(float(b[0]), 2), round(float(b[1]), 2)],
                                 "bucles": int(e.NumberOfLoops), "asociativo": bool(e.AssociativeHatch)})
            elif on in ("Polyline", "2dPolyline"):
                w = float(e.ConstantWidth)
                if w > 0:
                    anchas.setdefault(capa, []).append(round(w, 3))
        except Exception:
            pass
    rellenos.sort(key=lambda r: -r["area"])
    return {"ok": True, "plano": str(doc.Name), "unidad_m": UNIDAD_A_METROS.get(int(reintentar(lambda: doc.GetVariable("INSUNITS"))), 1.0),
            "entidades_modelo": total, "entidades_leidas": leidas, "completo": leidas >= total, "capas": capas,
            "rellenos": {"total": len(rellenos), "por_capa_y_patron": _agrupar(rellenos), "mayores": rellenos[:12]},
            "polilineas_con_grosor": {c: {"n": len(v), "grosor_tipico": sorted(v)[len(v) // 2]} for c, v in anchas.items()},
            "tiempo_s": round(time.time() - t0, 2)}


def _agrupar(rellenos):
    g = {}
    for r in rellenos:
        k = f"{r['capa']} | {r['patron']}"
        d = g.setdefault(k, {"n": 0, "area_total": 0.0, "asociativos": 0})
        d["n"] += 1
        d["area_total"] = round(d["area_total"] + r["area"], 2)
        d["asociativos"] += 1 if r["asociativo"] else 0
    return g


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
        return reintentar(lambda: (inventario if args.get("modo") == "inventario" else leer)(doc, args))
    except Exception as e:
        return {"ok": False, "error": "fallo_lectura", "detalle": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=True, default=str))
