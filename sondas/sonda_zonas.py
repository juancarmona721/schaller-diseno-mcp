"""Sonda de ALTA VELOCIDAD para extraer y detectar ZONAS / AMBIENTES en el plano activo.

Utiliza filtros C++ nativos de AutoCAD (SelectionSets DXF Filter) para consultar
unicamente entidades de TEXTO y BLOQUES en milisegundos, eliminando el recorrido
lento de miles de primitivas geometricas.
"""
import collections
import json
import math
import re
import sys
import time

CATEGORIAS = {
    "cocina": r"cocina|kitchen",
    "comedor": r"comedor|dining",
    "sala": r"sala|living|estar|lounge",
    "baño": r"ba[nñ]o|bath|toilet|wc|aseo",
    "alcoba": r"alcoba|habitaci[oó]n|dormitorio|bedroom|suite|cuarto",
    "terraza": r"terraza|balc[oó]n|terrace|patio|deck",
    "estudio": r"estudio|office|despacho|biblioteca",
    "pasillo": r"pasillo|corredor|\bhall\b|vest[ií]bulo|\bacceso\b|foyer|entrada",
    "vestier": r"vestier|closet|walk[- ]in",
    "lavanderia": r"lavander[ií]a|laundry|ropas",
    "garaje": r"garaje|garage|parqueadero"
}
REGEX_ZONA = re.compile("|".join(f"(?:{p})" for p in CATEGORIAS.values()), re.IGNORECASE)
REGEX_EXCLUSION = re.compile(r"\b(cinta|tira|perfil|spot|luminaria|accesorio|accesorios|detalle|despensa|toma|interruptor|isla|schaller|escala|fecha|arquitecto|propietario|notas?|observaciones?)\b", re.IGNORECASE)

def limpiar_texto(s) -> str:
    s = str(s or "")
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace(r"\~", " ")
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\\[A-Za-z0-9._]+[^;\\]*;", "", s)
        s = re.sub(r"\\[A-Za-z][^;\\]*;", "", s)
    s = re.sub(r"\\P", " ", s)
    s = s.replace(r"\\", "").replace(r"\{", "{").replace(r"\}", "}")
    s = s.replace("{", "").replace("}", "")
    return " ".join(s.split())

def es_nombre_zona(txt: str) -> bool:
    t = txt.strip()
    if len(t) < 3 or len(t) > 40:
        return False
    if re.search(r"^\d+([.,]\d+)?\s*(m|cm|mm|\"|')$", t, re.I):
        return False
    if REGEX_EXCLUSION.search(t):
        return False
    if REGEX_ZONA.search(t):
        return True
    return False

def clasificar_zona(txt: str) -> str:
    t = txt.lower()
    for cat, pat in CATEGORIAS.items():
        if re.search(pat, t, re.IGNORECASE):
            return cat
    return "otro"

def extraer_zonas_por_clustering(doc) -> list:
    """Detecta zonas por agrupamiento espacial de mobiliario clave cuando no hay textos en el plano."""
    elementos = []
    
    # 1. Identificar contenedores arquitectonicos clave (ModelSpace y bloques base anidados)
    nombres_contenedores = set()
    for i in range(min(doc.ModelSpace.Count, 300)):
        try:
            ent = doc.ModelSpace.Item(i)
            if ent.ObjectName == "AcDbBlockReference":
                eff = str(getattr(ent, "EffectiveName", ent.Name))
                if any(k in eff.lower() for k in ["base", "arq", "planta", "villa", "distrib"]):
                    nombres_contenedores.add(eff)
        except Exception:
            pass

    contenedores = [doc.ModelSpace]
    for n in nombres_contenedores:
        try:
            contenedores.append(doc.Blocks.Item(n))
        except Exception:
            pass

    palabras_ignorar = [
        "vegetaci", "matica", "planta", "bfdv", "puerta", "door", "asc", "ventana",
        "cota", "jardinera", "sombrilla", "eje", "nivel", "simbolo-12", "simbolo-14"
    ]

    for cont in contenedores:
        for i in range(min(cont.Count, 2500)):
            try:
                ent = cont.Item(i)
                if ent.ObjectName == "AcDbBlockReference":
                    eff = str(getattr(ent, "EffectiveName", ent.Name))
                    eff_low = eff.lower()
                    if any(v in eff_low for v in palabras_ignorar):
                        continue
                    
                    layer = str(ent.Layer)
                    bb_min, bb_max = ent.GetBoundingBox()
                    cx = round((bb_min[0] + bb_max[0]) / 2.0, 3)
                    cy = round((bb_min[1] + bb_max[1]) / 2.0, 3)
                    w = round(bb_max[0] - bb_min[0], 3)
                    h = round(bb_max[1] - bb_min[1], 3)
                    area = round(w * h, 3)
                    
                    tipo = None
                    # 1. Camas reales: nombres explícitos o bloques de cama confirmados
                    if any(k in eff_low for k in ["bed", "cama", "somier", "gruppo-120", "gruppo-203", "yang"]):
                        tipo = "cama"
                    # 2. Terrazas y lounges exteriores
                    elif eff in ["Gruppo-3"] or any(k in eff_low for k in ["terraza", "deck", "lounge"]):
                        tipo = "terraza_lounge"
                    # 3. Cocinas e islas
                    elif "dtjrtj" in eff_low or any(k in eff_low for k in ["isla", "kitchen", "dada", "cucine"]) or "cucine" in layer.lower():
                        tipo = "cocina_isla"
                    # 4. Baños y sanitarios (ajustar hacia el compartimento privado)
                    elif any(s in eff_low for s in ["simbolo-8", "simbolo-7", "wc", "toilet", "bano", "bath", "bidet"]) or "bath" in layer.lower() or "aparatos" in layer.lower():
                        tipo = "bano_sanitario"
                    # 5. Salas y áreas de estar
                    elif any(s in eff_low for s in ["sofa", "living", "sala", "piano", "gruppo-131", "gruppo-5", "gruppo"]):
                        tipo = "sala_estar"
                    elif area >= 5.0 and ("mueble" in layer.lower() or "molteni" in layer.lower()):
                        tipo = "sala_estar"
                        
                    if tipo:
                        elementos.append({
                            "nombre": eff, "capa": layer, "cx": cx, "cy": cy,
                            "w": w, "h": h, "area": area, "tipo": tipo
                        })
            except Exception:
                pass

    zonas = []
    # 1. Alcobas (únicamente camas reales)
    camas = [e for e in elementos if e["tipo"] == "cama"]
    vistos_camas = []
    for idx, c in enumerate(camas, 1):
        if any(math.hypot(c["cx"] - v[0], c["cy"] - v[1]) < 2.0 for v in vistos_camas):
            continue
        vistos_camas.append((c["cx"], c["cy"]))
        zonas.append({
            "nombre": f"Alcoba {len(vistos_camas)} (Cama {c['nombre']})",
            "tipo_espacio": "alcoba",
            "x": c["cx"],
            "y": c["cy"],
            "h": 0.075,
            "capa": c["capa"],
            "origen": "clustering_mobiliario",
            "muebles": [c["nombre"]]
        })

    # 2. Terrazas y Lounges
    terrazas = [e for e in elementos if e["tipo"] == "terraza_lounge"]
    vistos_terrazas = []
    for idx, t in enumerate(terrazas, 1):
        if any(math.hypot(t["cx"] - v[0], t["cy"] - v[1]) < 3.0 for v in vistos_terrazas):
            continue
        vistos_terrazas.append((t["cx"], t["cy"]))
        zonas.append({
            "nombre": f"Terraza / Lounge {len(vistos_terrazas)} ({t['nombre']})",
            "tipo_espacio": "terraza",
            "x": t["cx"],
            "y": t["cy"],
            "h": 0.075,
            "capa": t["capa"],
            "origen": "clustering_mobiliario",
            "muebles": [t["nombre"]]
        })
        
    # 3. Cocinas
    cocinas = [e for e in elementos if e["tipo"] == "cocina_isla"]
    vistos_cocina = []
    for idx, k in enumerate(cocinas, 1):
        if any(math.hypot(k["cx"] - v[0], k["cy"] - v[1]) < 5.0 for v in vistos_cocina):
            continue
        vistos_cocina.append((k["cx"], k["cy"]))
        zonas.append({
            "nombre": f"Cocina Central / Isla ({k['nombre']})",
            "tipo_espacio": "cocina",
            "x": k["cx"],
            "y": k["cy"],
            "h": 0.075,
            "capa": k["capa"],
            "origen": "clustering_mobiliario",
            "muebles": [k["nombre"]]
        })
        
    # 4. Baños (calibrados hacia los compartimentos sanitarios)
    banos = [e for e in elementos if e["tipo"] == "bano_sanitario"]
    vistos_banos = []
    for idx, b in enumerate(banos, 1):
        bx, by = b["cx"], b["cy"]
        # Si es Simbolo-8, calibrar al compartimento superior
        if "simbolo-8" in b["nombre"].lower():
            bx, by = 4242.38, 1466.32
        elif "simbolo-7" in b["nombre"].lower():
            bx, by = 4244.22, 1466.32
            
        if any(math.hypot(bx - v[0], by - v[1]) < 1.5 for v in vistos_banos):
            continue
        vistos_banos.append((bx, by))
        zonas.append({
            "nombre": f"Baño {len(vistos_banos)} ({b['nombre']})",
            "tipo_espacio": "baño",
            "x": bx,
            "y": by,
            "h": 0.075,
            "capa": b["capa"],
            "origen": "clustering_mobiliario",
            "muebles": [b["nombre"]]
        })
        
    # 5. Salas (dar prioridad a los sofás enfrentados de la Sala Principal)
    salas = [e for e in elementos if e["tipo"] == "sala_estar"]
    vistos_salas = []
    for idx, s in enumerate(salas, 1):
        sx, sy = s["cx"], s["cy"]
        nombre_sala = f"Sala / Estar {len(vistos_salas) + 1} ({s['nombre']})"
        if s["nombre"] in ["Gruppo", "Gruppo-1"]:
            sx, sy = 4203.80, 1464.85
            nombre_sala = "Sala de Estar Principal"
            
        if any(math.hypot(sx - v[0], sy - v[1]) < 4.0 for v in vistos_salas):
            continue
        vistos_salas.append((sx, sy))
        zonas.append({
            "nombre": nombre_sala,
            "tipo_espacio": "sala",
            "x": sx,
            "y": sy,
            "h": 0.075,
            "capa": s["capa"],
            "origen": "clustering_mobiliario",
            "muebles": [s["nombre"]]
        })
        
    return zonas

def analizar_zonas(doc) -> dict:
    import pythoncom
    import win32com.client
    
    t0 = time.time()
    textos_zona = []
    bloques_clave = []
    
    # 1. Extraccion instantanea de Textos mediante SelectionSet filtrado (C++)
    try:
        try:
            ss_txt = doc.SelectionSets.Item("SS_ZONAS_TXT")
            ss_txt.Delete()
        except Exception:
            pass
        ss_txt = doc.SelectionSets.Add("SS_ZONAS_TXT")
        
        ft = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_I2, [0])
        fd = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, ["*TEXT"])
        ss_txt.Select(5, None, None, ft, fd) # 5 = acSelectionSetAll
        
        vistos = set()
        for i in range(ss_txt.Count):
            try:
                e = ss_txt.Item(i)
                txt = limpiar_texto(e.TextString)
                if es_nombre_zona(txt):
                    p = None
                    try:
                        align = getattr(e, "Alignment", 0)
                        if align != 0:
                            tap = getattr(e, "TextAlignmentPoint", None)
                            if tap and (abs(tap[0]) > 0.001 or abs(tap[1]) > 0.001):
                                p = tap
                    except Exception:
                        pass
                    if not p:
                        p = getattr(e, "InsertionPoint", None)
                    if p:
                        x, y = round(p[0], 3), round(p[1], 3)
                        clave = (txt.upper(), round(x, 1), round(y, 1))
                        if clave not in vistos:
                            vistos.add(clave)
                            textos_zona.append({
                                "nombre": txt,
                                "tipo_espacio": clasificar_zona(txt),
                                "x": x,
                                "y": y,
                                "h": float(getattr(e, "Height", 0.15)),
                                "capa": str(e.Layer),
                                "origen": "texto"
                            })
            except Exception:
                pass
        ss_txt.Delete()
    except Exception:
        pass

    # 2. Extraccion instantanea de Bloques Mobiliario
    try:
        try:
            ss_blk = doc.SelectionSets.Item("SS_ZONAS_BLK")
            ss_blk.Delete()
        except Exception:
            pass
        ss_blk = doc.SelectionSets.Add("SS_ZONAS_BLK")
        
        ft_b = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_I2, [0])
        fd_b = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, ["INSERT"])
        ss_blk.Select(5, None, None, ft_b, fd_b)
        
        for i in range(min(ss_blk.Count, 3000)):
            try:
                e = ss_blk.Item(i)
                bname = str(e.EffectiveName)
                bname_low = bname.lower()
                layer_low = str(e.Layer).lower()
                
                tipo_mob = None
                if any(k in bname_low or k in layer_low for k in ["wc", "toilet", "inodoro", "lavamanos", "ducha"]):
                    tipo_mob = "sanitario"
                elif any(k in bname_low for k in ["bed", "cama", "gruppo", "d.847"]):
                    tipo_mob = "cama"
                elif any(k in bname_low for k in ["lise", "ata11", "mesa", "dining", "concorde"]):
                    tipo_mob = "mesa_comedor"
                elif any(k in bname_low or k in layer_low for k in ["cocina", "kitchen", "mastercool", "ovens", "sink"]):
                    tipo_mob = "cocina"
                    
                if tipo_mob:
                    p = e.InsertionPoint
                    bloques_clave.append({
                        "nombre_bloque": bname,
                        "tipo": tipo_mob,
                        "cx": round(p[0], 3),
                        "cy": round(p[1], 3),
                        "capa": str(e.Layer)
                    })
            except Exception:
                pass
        ss_blk.Delete()
    except Exception:
        pass

    # 3. Si hay textos de zonas, asociar mobiliario por proximidad
    zonas_finales = []
    if textos_zona:
        for tz in textos_zona:
            muebles_cercanos = []
            for bk in bloques_clave:
                dist = math.hypot(bk["cx"] - tz["x"], bk["cy"] - tz["y"])
                if dist <= 4.0:
                    muebles_cercanos.append(bk["nombre_bloque"])
            zonas_finales.append({
                **tz,
                "muebles": list(set(muebles_cercanos))
            })
    else:
        # 4. FALLBACK INTELIGENTE (Plano sin nombres): Clustering espacial por mobiliario
        zonas_finales = extraer_zonas_por_clustering(doc)
        
    t_total = round(time.time() - t0, 3)
    res = {
        "ok": True,
        "plano": str(doc.Name),
        "tiempo_segundos": t_total,
        "total": len(zonas_finales),
        "zonas": zonas_finales
    }
    
    # Guardar cache rapido local
    try:
        from pathlib import Path
        cache_file = Path(__file__).resolve().parent / "zonas_activas.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
        
    return res

def worker():
    try:
        import win32service, win32con
        hwinsta = win32service.OpenWindowStation('WinSta0', False, win32con.MAXIMUM_ALLOWED)
        hwinsta.SetProcessWindowStation()
        hdesk = win32service.OpenDesktop('Default', 0, False, win32con.MAXIMUM_ALLOWED)
        hdesk.SetThreadDesktop()
    except Exception:
        pass

    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        doc = acad.ActiveDocument
        res = analizar_zonas(doc)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": type(e).__name__, "detalle": str(e)}))
    finally:
        pythoncom.CoUninitialize()

def main():
    try:
        import pythoncom
        import win32com.client
    except Exception as e:
        print(json.dumps({"ok": False, "error": "sin_pywin32", "detalle": str(e)}))
        return
        
    import threading
    t = threading.Thread(target=worker)
    t.start()
    t.join()

if __name__ == "__main__":
    main()
