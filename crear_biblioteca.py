"""Construye el DWG de la BIBLIOTECA de bloques: cada bloque tal cual esta dibujado, con atributos para llenar.

Uso: python crear_biblioteca.py <catalogo_bloques.csv> <bloques_por_dibujo.json> <carpeta_planos> <salida.dwg> [--prueba N]

- Los planos de origen se abren en SOLO LECTURA (los que no estaban abiertos se cierran sin guardar) y solo se copian
  definiciones de bloque. Nunca se modifica ni se guarda un plano de origen.
- Solo se escribe en un dibujo NUEVO. Si <salida.dwg> ya existe, NO se pisa (se detiene).
- Cada bloque lleva atributos NOMBRE_GENERICO, REFERENCIA, DESCRIPCION, ESTADO. Lo que no se sabe queda VACIO.
- Con --prueba N procesa solo N bloques y no guarda (el dibujo queda abierto para revisarlo).
"""
import collections
import csv
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _probe_simbolos as sim  # noqa: E402

BUSY = (-2147418111, -2147417846)
CELDA_W, CELDA_H, COLS, TAM_VISTA = 1100.0, 800.0, 6, 350.0


def reintentar(fn, veces=8):
    for i in range(veces):
        try:
            return fn()
        except Exception as e:
            code = e.args[0] if getattr(e, "args", None) else None
            if code in BUSY and i < veces - 1:
                time.sleep(1.5)
                continue
            raise


def existe_r(coleccion, nombre):
    """Como sim.existe, pero un 'AutoCAD ocupado' se reintenta en vez de contarse como 'no existe'."""
    for _ in range(6):
        try:
            coleccion.Item(nombre)
            return True
        except Exception as e:
            code = e.args[0] if getattr(e, "args", None) else None
            if code in BUSY:
                time.sleep(2)
                continue
            return False
    return False


def doc_por_nombre(app, nombre, espera=120):
    fin = time.time() + espera
    while time.time() < fin:
        try:
            for i in range(app.Documents.Count):
                d = app.Documents.Item(i)
                if d.Name == nombre:
                    return d
        except Exception:
            pass
        time.sleep(2)
    return None


def abrir_plano(app, ruta):
    """Abre en SOLO LECTURA y vuelve a buscar el documento por nombre (el valor devuelto por Open no es fiable)."""
    for _ in range(3):
        try:
            app.Documents.Open(str(ruta), True)
        except Exception:
            pass
        d = doc_por_nombre(app, Path(ruta).name, espera=180)
        if d is not None:
            return d
    return None


def linea_origen(f):
    """Texto de revision: en que planos aparece el bloque, de cual se copio el simbolo y de donde salen los datos."""
    pares = re.findall(r"(extraccionbloques\d+\.dwg)\((\d+)\)", f.get("dibujos") or "")
    pares.sort(key=lambda p: int(re.search(r"\d+", p[0]).group()))
    archivos = ", ".join(f"{nombre} ({c})" for nombre, c in pares) or "sin dato"
    sim_de = elegir_origen(f, set()) or "?"
    # los datos citan "dib4/dib9/dib6": se dicen con el nombre real del archivo
    fuentes = (f.get("fuentes") or "").strip() or "sin datos aun"
    fuentes = re.sub(r"\bdib(\d+)\b", lambda m: f"extraccionbloques{m.group(1)}.dwg", fuentes)
    return (f"ORIGEN: aparece en {archivos} (entre parentesis: copias) · simbolo copiado de {sim_de} · "
            f"datos tomados de: {fuentes}")


def escala_tipica(instancias, dibujo, bloque):
    c = collections.Counter(round(abs(i["escala_x"]), 6) for i in instancias
                            if i["dibujo"] == dibujo and i["bloque"] == bloque and i.get("escala_x"))
    return c.most_common(1)[0][0] if c else 1.0


def elegir_origen(fila, abiertos):
    """Dibujo del que copiar: el de la leyenda (4) si esta, si no el que mas copias del bloque tiene."""
    cuentas = {m.group(1): int(m.group(2)) for m in re.finditer(r"(extraccionbloques\d+\.dwg)\((\d+)\)", fila["dibujos"])}
    if "extraccionbloques4.dwg" in cuentas:
        return "extraccionbloques4.dwg"
    ab = [d for d in cuentas if d in abiertos]
    return max(ab or cuentas, key=lambda d: cuentas[d]) if cuentas else None


def copiar_bloque(origen, destino, nombre, esc, mk, mkobj):
    """Copia la definicion al destino: escala tipica de insercion + unidades, y centra en el punto base. Devuelve (w, h)."""
    u_o, u_d = origen.GetVariable("INSUNITS"), destino.GetVariable("INSUNITS")
    relacion = sim.UNIDAD_M[u_o] / sim.UNIDAD_M[u_d] if u_o in sim.UNIDAD_M and u_d in sim.UNIDAD_M else 1.0
    factor = esc * relacion
    src = origen.Blocks.Item(nombre)
    ents = list(src)
    nb = destino.Blocks.Add(mk(0, 0, 0), nombre)
    try:
        if ents:
            origen.CopyObjects(mkobj(ents), nb)
        copias = list(nb)
        for e in list(copias):  # fuera atributos propios del plano (MARCA, KEYPAD...): no deben verse dentro de la ficha
            try:
                if e.ObjectName == "AcDbAttributeDefinition":
                    e.Delete()
            except Exception:
                pass
        copias = [nb.Item(i) for i in range(nb.Count)]   # por indice: el enumerador falla tras borrar entidades
        if abs(factor - 1.0) > 1e-9:
            for e in copias:
                e.ScaleEntity(mk(*tuple(src.Origin)), factor)
        w, h, cx, cy = sim._medidas(copias)
        if cx is not None:
            for e in copias:
                e.Move(mk(cx, cy, 0), mk(0, 0, 0))
        return (w or 0.0), (h or 0.0), len(copias)
    except Exception:
        try:
            nb.Delete()
        except Exception:
            pass
        raise


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prueba = int(sys.argv[sys.argv.index("--prueba") + 1]) if "--prueba" in sys.argv else 0
    continuar = sys.argv[sys.argv.index("--continuar") + 1] if "--continuar" in sys.argv else None
    if prueba:
        args = [a for a in args if a != str(prueba)]
    if continuar:   # retoma un dibujo nuevo que ya tiene las definiciones copiadas: salta la copia y dibuja las fichas
        args = [a for a in args if a != continuar]
    csv_path, json_path, carpeta, salida = args[0], args[1], Path(args[2]), Path(args[3])
    if salida.exists() and not prueba and not continuar:
        print(json.dumps({"ok": False, "error": "ya_existe", "detalle": f"{salida.name} ya existe; no se pisa."}))
        return
    filas = list(csv.DictReader(open(csv_path, encoding="utf-8-sig"), delimiter=";"))
    filas.sort(key=lambda r: (0 if r["estado"] == "propuesto" else 1, -int(r["total_en_planos"] or 0)))
    if prueba:
        filas = filas[:prueba]
    instancias = json.load(open(json_path, encoding="utf-8"))["instancias"]

    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = win32com.client.GetActiveObject("AutoCAD.Application")
    docs = {app.Documents.Item(i).Name: app.Documents.Item(i) for i in range(app.Documents.Count)}
    ya_abiertos = set(docs)
    if continuar:
        destino = doc_por_nombre(app, continuar, 60)
        if destino is None:
            print(json.dumps({"ok": False, "error": "destino_no_encontrado", "detalle": f"No hay un dibujo abierto llamado {continuar}."}))
            return
        nombre_destino = continuar
        # redibujar las fichas: se borra SOLO lo dibujado antes por este script (capas DL-*); las definiciones de bloque se conservan
        ms0 = destino.ModelSpace
        capas0 = {ms0.Item(i).Layer for i in range(ms0.Count)}
        if capas0 and not all(c.startswith("DL-") for c in capas0):
            print(json.dumps({"ok": False, "error": "capas_ajenas", "detalle": f"El dibujo tiene objetos fuera de las capas DL-*: {sorted(capas0)}. No borro nada."}))
            return
        for i in range(ms0.Count - 1, -1, -1):
            ms0.Item(i).Delete()
    else:
        destino = reintentar(lambda: app.Documents.Add())
        nombre_destino = destino.Name
        destino.SetVariable("INSUNITS", 4)
    mk, mkobj = sim.mk_variant, sim.mk_objetos

    # --- 1) copiar las definiciones, agrupadas por plano de origen ---
    por_origen = collections.defaultdict(list)
    for f in ([] if continuar else filas):
        por_origen[elegir_origen(f, ya_abiertos)].append(f)
    medidas, resultado = {}, {"copiados": 0, "sin_origen": [], "fallos": {}}
    for dib, grupo in por_origen.items():
        if not dib:
            resultado["sin_origen"] += [g["bloque"] for g in grupo]
            continue
        origen = docs.get(dib)
        if origen is None:
            origen = abrir_plano(app, carpeta / dib)  # solo lectura
            if origen is None:
                resultado["fallos"][dib] = "no se pudo abrir el plano"
                continue
            docs[dib] = origen
        for f in grupo:
            n = f["bloque"]
            ultimo = ""
            for intento in range(4):   # AutoCAD a veces rechaza llamadas ('ocupado'): se reintenta el bloque completo
                try:
                    if not existe_r(origen.Blocks, n):
                        ultimo = "no existe en el plano de origen"
                        break
                    if existe_r(destino.Blocks, n):   # un intento anterior dejo la definicion a medias
                        try:
                            destino.Blocks.Item(n).Delete()
                        except Exception:
                            pass
                    medidas[n] = copiar_bloque(origen, destino, n, escala_tipica(instancias, dib, n), mk, mkobj)
                    resultado["copiados"] += 1
                    ultimo = ""
                    break
                except Exception as e:
                    ultimo = f"{type(e).__name__}: {str(e)[:120]}"
                    time.sleep(3)
            if ultimo:
                resultado["fallos"][n] = ultimo
        if dib not in ya_abiertos:
            try:
                origen.Close(False)  # sin guardar
            except Exception as e:
                print(f"AVISO: no pude cerrar {dib}: {e}", file=sys.stderr)
            docs.pop(dib, None)
        try:
            destino.Activate()
        except Exception:
            pass

    print(f"copiados {resultado['copiados']} bloques; fallos: {json.dumps(resultado['fallos'], ensure_ascii=False)}", file=sys.stderr)
    # el dibujo nuevo puede perder su referencia COM tras abrir/cerrar otros planos: se vuelve a buscar por nombre
    destino = doc_por_nombre(app, nombre_destino, 90) or destino
    try:
        destino.Activate()
    except Exception:
        pass
    # --- 2) fichas (el mismo formato de las tarjetas de producto), con el simbolo real dentro ---
    import _probe_tarjetas as tarj
    tarj.MAX_ESCALA_SIMBOLO = 1e9   # los simbolos vienen en unidades distintas: que la ficha los ajuste al recuadro
    presentes = [f for f in filas if f["bloque"] in medidas or (continuar and existe_r(destino.Blocks, f["bloque"]))]
    resultado["copiados"] = resultado["copiados"] or len(presentes)
    # REGLA: la ficha solo lleva datos CONFIRMADOS por una persona; lo propuesto o deducido NO se escribe (queda "sin dato")
    conf = lambda f: f["estado"] == "confirmado"  # noqa: E731
    tarjetas = [{"nombre": None, "referencia": (f["referencia"] or None) if conf(f) else None,
                 "marca": (f["marca"] or None) if conf(f) else None,
                 "descripcion": (f["descripcion_odoo"] or None) if conf(f) else None,
                 "instalacion": None, "cantidad": None, "conexion": {},
                 "bloques": [f["bloque"]]} for f in presentes]
    tarj.GAP_BASE = 300.0           # espacio entre fichas (sin rotulos ya no hace falta tanto)
    r = tarj.crear(destino, {"ejecutar": True, "tarjetas": tarjetas, "ancho": 1800, "columnas": COLS, "x0": 0, "y0": 0,
                             "leyenda": False, "incluir_sin_simbolo": True, "max_objetos": 100000})
    resultado["fichas"] = r.get("tarjetas")
    if not r.get("ok"):
        resultado["error_fichas"] = r
    # sin rotulos sobre las fichas: solo el titulo de la biblioteca
    ms = destino.ModelSpace
    pos, alto, gap, k = tarj.disenar(tarjetas, 1800.0, 0.0, 0.0, COLS)
    capa_rot = "DL-FICHAS-ROTULO"
    try:
        destino.Layers.Add(capa_rot)
    except Exception:
        pass
    titulo = ms.AddText("BIBLIOTECA DE BLOQUES - fichas por completar. Gris = sin dato. Solo se escribe lo confirmado por una persona.",
                        mk(0, 300, 0), 90)
    titulo.Layer = capa_rot
    try:
        destino.SendCommand("_ZOOM _E ")
    except Exception:
        pass

    guardado = ""
    if not prueba:
        if continuar:
            destino.Save()      # ya es el archivo de la biblioteca: se guarda en su sitio
        else:
            destino.SaveAs(str(salida))
        guardado = str(salida)
    print(json.dumps({"ok": True, "bloques_en_biblioteca": resultado["copiados"], "sin_origen": resultado["sin_origen"],
                      "fallos": resultado["fallos"], "guardado": guardado, "prueba": bool(prueba)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
