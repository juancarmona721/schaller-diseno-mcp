import math
import pytest
import patrones_diseno

def test_distancia_punto_segmento():
    # Punto (0, 1) frente a segmento de (0, 0) a (10, 0) -> distancia 1.0
    d = patrones_diseno.distancia_punto_segmento(0, 1, 0, 0, 10, 0)
    assert math.isclose(d, 1.0, rel_tol=1e-5)
    
    # Punto (5, 3) frente a segmento de (0, 0) a (10, 0) -> distancia 3.0
    d = patrones_diseno.distancia_punto_segmento(5, 3, 0, 0, 10, 0)
    assert math.isclose(d, 3.0, rel_tol=1e-5)

def test_clasificar_intencion():
    # Parlante KEF cerca de mesa de comedor -> audio_comensales
    anfitrion = {"tipo": "mesa_comedor", "nombre_bloque": "ATA11"}
    inte = patrones_diseno.clasificar_intencion("Ci160CRDS_KEF", anfitrion, dist_anfitrion=0.45, dist_muro=2.0)
    assert inte == "audio_comensales"

    # Durastrip cerca de cama -> cabecera_ambiente
    anfitrion_cama = {"tipo": "cama", "nombre_bloque": "Gruppo-120"}
    inte_cama = patrones_diseno.clasificar_intencion("Durastrip IP20_45W_Targetti", anfitrion_cama, dist_anfitrion=0.3, dist_muro=1.0)
    assert inte_cama == "cabecera_ambiente"

    # Spot CCTEvo cerca de muro -> acento_muro_arte
    inte_spot = patrones_diseno.clasificar_intencion("CCTEvo Architectural_105_Targetti", None, dist_anfitrion=999, dist_muro=0.5)
    assert inte_spot == "acento_muro_arte"

def test_extraer_patrones_desde_elementos():
    productos = [
        {"nombre": "Ci160CRDS_KEF", "x": 10.45, "y": 10.45, "capa": "SCH_AUDIO"},
        {"nombre": "Ci160CRDS_KEF", "x": 9.55, "y": 10.45, "capa": "SCH_AUDIO"}
    ]
    mobiliario = [
        {"nombre_bloque": "LISE", "tipo": "mesa_comedor", "cx": 10.0, "cy": 10.0}
    ]
    muros = [
        (0.0, 0.0, 20.0, 0.0),
        (0.0, 20.0, 20.0, 20.0)
    ]
    
    patrones = patrones_diseno.extraer_patrones_desde_elementos(productos, mobiliario, muros)
    assert len(patrones) == 2
    assert patrones[0]["intencion"] == "audio_comensales"
    assert patrones[0]["anfitrion"]["tipo"] == "mesa_comedor"
    assert math.isclose(patrones[0]["interdistancia_par"], 0.90, rel_tol=1e-3)
