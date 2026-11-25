"""Motor de Extraccion de Patrones de Diseno (Schaller Pattern Miner).

Analiza planos terminados para extraer el "ADN de diseno":
En lugar de guardar coordenadas absolutas (X, Y) que cambian en cada casa, extrae
relaciones relativas (Vectores de Intencion):
1. Elemento anfitrion o referencia (Mesa, Cama, Muro, Isla, Lavamanos).
2. Distancia relativa (al centro del mueble o al muro mas cercano).
3. Interdistancia ritmica (separacion entre luminarias o parlantes repetidos).
4. Orientacion y alineacion (paralelo, perpendicular, angulo de haz).
5. Intencion arquitectonica inferida:
   - "audio_comensales": parlantes enfrentados sobre mesa de comedor.
   - "audio_individual": parlante centrado en bano o espacio privado.
   - "cabecera_ambiente": tira rasante en espaldar + spots laterales.
   - "perimetro_rasante": tiras continuas bordeando cielorraso/muros.
   - "acento_arte": luminarias orientadas hacia paramentos verticales.
   - "tarea_isla": luminarias suspendidas/embutidas sobre mesadas de trabajo.
"""
import collections
import json
import math
import sys

def distancia_punto_segmento(px, py, x1, y1, x2, y2) -> float:
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)

def clasificar_intencion(nombre_producto: str, anfitrion: dict | None, dist_anfitrion: float, dist_muro: float) -> str:
    prod_low = nombre_producto.lower()
    
    if "ci160" in prod_low or "kef" in prod_low or "parlante" in prod_low:
        if anfitrion and anfitrion.get("tipo") == "mesa_comedor" and dist_anfitrion <= 1.5:
            return "audio_comensales"
        elif anfitrion and anfitrion.get("tipo") == "sanitario" and dist_anfitrion <= 2.5:
            return "audio_bano"
        return "audio_ambiente"
        
    elif "durastrip" in prod_low or "tira" in prod_low:
        if anfitrion and anfitrion.get("tipo") == "cama" and dist_anfitrion <= 1.2:
            return "cabecera_ambiente"
        if anfitrion and anfitrion.get("tipo") == "cocina" and dist_anfitrion <= 3.0:
            return "perimetro_foseado_cocina"
        return "perimetro_rasante"
        
    elif "cctevo" in prod_low or "targetti" in prod_low or "spot" in prod_low:
        if anfitrion and anfitrion.get("tipo") == "cama" and dist_anfitrion <= 2.0:
            return "spots_dormitorio_perimetral"
        if dist_muro < 0.65:
            return "acento_muro_arte"
        return "downlight_general"
        
    elif "moon" in prod_low:
        return "suspension_ambiente"
        
    return "general"

def extraer_patrones_desde_elementos(productos_instalados: list[dict], mobiliario: list[dict], muros_segmentos: list[tuple]) -> list[dict]:
    """Extrae las reglas relativas de colocacion de cada producto instalado."""
    patrones = []
    
    for idx, prod in enumerate(productos_instalados):
        px, py = prod["x"], prod["y"]
        pnombre = prod["nombre"]
        
        # 1. Distancia al muro mas cercano
        min_dist_muro = 999.0
        for seg in muros_segmentos:
            d = distancia_punto_segmento(px, py, seg[0], seg[1], seg[2], seg[3])
            if d < min_dist_muro:
                min_dist_muro = d
                
        # 2. Mueble anfitrion mas cercano
        anfitrion_cercano = None
        min_dist_mob = 999.0
        for mob in mobiliario:
            d = math.hypot(px - mob["cx"], py - mob["cy"])
            if d < min_dist_mob:
                min_dist_mob = d
                anfitrion_cercano = mob
                
        # 3. Interdistancia con producto identico mas proximo
        min_interdist = 999.0
        for j, otro in enumerate(productos_instalados):
            if j != idx and otro["nombre"] == pnombre:
                d = math.hypot(px - otro["x"], py - otro["y"])
                if d < min_interdist:
                    min_interdist = d
                    
        # 4. Clasificar la intencion
        intencion = clasificar_intencion(pnombre, anfitrion_cercano, min_dist_mob, min_dist_muro)
        
        # 5. Generar regla de patron
        patron = {
            "producto": pnombre,
            "intencion": intencion,
            "anfitrion": {
                "tipo": anfitrion_cercano["tipo"] if anfitrion_cercano else "espacio_abierto",
                "nombre_bloque": anfitrion_cercano["nombre_bloque"] if anfitrion_cercano else None,
                "distancia_al_centro": round(min_dist_mob, 3) if min_dist_mob < 900 else None,
                "offset_relativo": [round(px - anfitrion_cercano["cx"], 3), round(py - anfitrion_cercano["cy"], 3)] if anfitrion_cercano else None
            },
            "distancia_muro_minima": round(min_dist_muro, 3) if min_dist_muro < 900 else None,
            "interdistancia_par": round(min_interdist, 3) if min_interdist < 900 else None,
            "capa": prod.get("capa", "SCH_DISENO")
        }
        patrones.append(patron)
        
    return patrones


# ==============================================================================
# ESTÁNDARES DE COLOCACIÓN Y ROTULACIÓN (MCP DISEÑO)
# ==============================================================================

ESCALAS_BLOQUES_SCHALLER = {
    # Bloques modelados en milímetros (requieren escala 0.001 en planos en metros):
    "CCTEvo Architectural_58_Targetti": 0.001,
    "CCTEvo Architectural_160_Targetti": 0.001,
    "FORTYEIGHT Label_7_Targetti": 0.001,
    "Ci200QS Pared_KEF": 0.001,
    "Simbiosis_Davide Groppi": 0.001,
    "Moon_60_Davide Groppi": 0.001,
    "Ci160CRDS_KEF": 0.001,
    "Ci200QR_KEF": 0.001,
    "Durastrip IP68_45W_Targetti": 0.001,
    "Durastrip IP20_75W_Targetti": 0.001,
    # La biblioteca bloques_schaller_corregido esta TODA en milimetros. Esto es solo el valor de reserva: al insertar, la escala se
    # calibra midiendo el bloque (si ya existia en el plano con otras unidades, p. ej. convertido a metros, se detecta).
    # Nombres anteriores (planos hechos con la biblioteca vieja):
    "SIMBIOSI": 1.0,
    "CI200QR_": 1.0,
}

BLOQUES_CON_REFERENCIA_ESTAMPADA = {
    # Bloques que ya dibujan internamente su texto de referencia en la geometría:
    "CCTEvo Architectural_58_Targetti": "58A",
    "CCTEvo Architectural_160_Targetti": "160A",
    "FORTYEIGHT Label_7_Targetti": "L7",
}

REFERENCIAS_TECNICAS_OBLIGATORIAS = {
    # Bloques sin texto interno que requieren etiqueta de referencia técnica (H=0.035m):
    "Ci160CRDS_KEF": ("Ci160CRDS", "SCH_AUDIO", 6),
    "Ci200QS Pared_KEF": ("Ci200QS", "SCH_AUDIO", 6),
    "CI200QR_": ("Ci200QR", "SCH_AUDIO", 6),
    "Ci200QR_KEF": ("Ci200QR", "SCH_AUDIO", 6),
    "Simbiosis_Davide Groppi": ("SIMBIOSIS", "SCH_ILUMINACION", 7),
    "SIMBIOSI": ("SIMBIOSIS", "SCH_ILUMINACION", 7),   # el BLOQUE se llama SIMBIOSI; el producto/rotulo es SIMBIOSIS
    "Durastrip IP68_45W_Targetti": ("Durastrip IP68", "SCH_ILUMINACION", 5),
    "Durastrip IP20_75W_Targetti": ("Durastrip IP20", "SCH_ILUMINACION", 6),
}

def obtener_escala_bloque(nombre_bloque: str) -> float:
    """Devuelve la escala correcta de inserción según las unidades del bloque."""
    return ESCALAS_BLOQUES_SCHALLER.get(nombre_bloque, 1.0)

def requiere_texto_referencia(nombre_bloque: str) -> tuple[bool, str, str, int]:
    """Determina si un bloque necesita etiqueta externa o ya trae su referencia integrada."""
    if nombre_bloque in BLOQUES_CON_REFERENCIA_ESTAMPADA:
        return False, "", "", 0
    if nombre_bloque in REFERENCIAS_TECNICAS_OBLIGATORIAS:
        ref, capa, color = REFERENCIAS_TECNICAS_OBLIGATORIAS[nombre_bloque]
        return True, ref, capa, color
    return False, "", "", 0
