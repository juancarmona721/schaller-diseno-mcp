"""Fase 1A (modulo puro): identidad logica, deduplicacion, diario y reconciliacion tras un fallo."""
import json

import operaciones as op


def col(producto, x, y, bloque=None, rot=0.0):
    return {"producto": producto, "bloque": bloque or producto.upper(), "x": x, "y": y, "rot": rot, "capa": "SCH_ILUMINACION"}


# ------------------------------------------------------------------------------------------------ identidad
def test_los_ids_de_operacion_son_distintos_y_el_doc_no_guarda_el_nombre():
    assert op.nuevo_operation_id() != op.nuevo_operation_id()
    d = op.doc_id("Plano Cliente X.dwg")
    assert d == op.doc_id("plano cliente x.DWG") and "cliente" not in d.lower() and len(d) == 12


def test_plan_hash_cambia_con_el_contenido_y_no_con_el_formato():
    a = [col("cctevo58", 1.0, 2.0)]
    assert op.plan_hash(a) == op.plan_hash([col("cctevo58", 1.00001, 2.0)])         # redondeo a mm
    assert op.plan_hash(a) != op.plan_hash([col("cctevo58", 1.5, 2.0)])


def test_los_ids_logicos_no_incluyen_el_producto_y_son_estables():
    plan = [col("cctevo58", 0, 0), col("cctevo58", 1, 0), col("durastrip", 0, 1)]
    ids = op.asignar_ids(plan, "d1", "8A21", "cama")
    assert [c["slot"] for c in ids] == ["cctevo58_1", "cctevo58_2", "durastrip_1"]
    assert ids[0]["item_id"] == "d1|8A21|cama|cctevo58_1"
    assert [c["item_id"] for c in op.asignar_ids(plan, "d1", "8A21", "cama")] == [c["item_id"] for c in ids]
    assert all(len(c["item_id"]) < 200 for c in ids)                             # cabe en un campo XData (255)


# ------------------------------------------------------------------------------------------------ deduplicacion
def test_reintentar_la_misma_operacion_no_duplica():
    plan = op.asignar_ids([col("a", 0, 0), col("a", 1, 0)], "d", "H1", "linea")
    existentes = [{"item_id": c["item_id"], "bloque": c["bloque"], "x": c["x"], "y": c["y"]} for c in plan]
    nuevas, ya, cambiadas = op.sin_duplicados_logico(plan, existentes)
    assert nuevas == [] and len(ya) == 2 and cambiadas == []


def test_dos_piezas_legitimas_a_15_cm_ya_no_se_descartan_por_cercania():
    existentes = [{"item_id": "d|H|r|a_1", "bloque": "A", "x": 0.0, "y": 0.0}]
    nuevo = op.asignar_ids([col("a", 0.15, 0.0)], "d", "H", "r")
    nuevo[0]["item_id"] = "d|H|r|a_2"                                             # otra posicion funcional
    nuevas, ya, _ = op.sin_duplicados_logico(nuevo, existentes)
    assert len(nuevas) == 1 and ya == []


def test_la_pieza_antigua_sin_marca_se_sigue_reconociendo_por_proximidad():
    nuevo = op.asignar_ids([col("a", 0.1, 0.0)], "d", "H", "r")
    nuevas, ya, _ = op.sin_duplicados_logico(nuevo, [{"bloque": "A", "x": 0.0, "y": 0.0}])
    assert nuevas == [] and len(ya) == 1


def test_misma_posicion_con_otro_producto_o_lejos_se_reporta_como_cambiada_y_no_se_duplica():
    plan = op.asignar_ids([col("a", 2.0, 0.0, bloque="NUEVO")], "d", "H", "r")
    previo = [{"item_id": plan[0]["item_id"], "bloque": "VIEJO", "x": 0.0, "y": 0.0}]
    nuevas, ya, cambiadas = op.sin_duplicados_logico(plan, previo)
    assert nuevas == [] and len(ya) == 1 and cambiadas[0]["bloque_existente"] == "VIEJO" and cambiadas[0]["distancia_m"] == 2.0


# ------------------------------------------------------------------------------------------------ diario
def test_el_diario_guarda_la_intencion_antes_de_escribir_y_se_cierra(tmp_path):
    d = op.Diario(tmp_path)
    items = op.asignar_ids([col("a", 0, 0), col("a", 1, 0)], "d", "H", "r")
    d.iniciar("op_1", "docA", "hash1", items, previos=["77"])
    g = d.cargar("op_1")
    assert g["estado"] == "pendiente" and len(g["items"]) == 2 and g["previos"] == ["77"] and "x" in g["items"][0]
    d.finalizar("op_1", "aplicada", {"insertados": 2})
    assert d.cargar("op_1")["estado"] == "aplicada" and d.pendientes("docA") == []


def test_los_checkpoints_se_escriben_cada_n_piezas_y_no_por_pieza(tmp_path):
    d = op.Diario(tmp_path, checkpoint_cada=50)
    d.iniciar("op_1", "docA", "h", [])
    escrituras = sum(d.checkpoint("op_1", n) for n in range(1, 201))
    assert escrituras == 4 and d.cargar("op_1")["aplicados"] == 200


def test_una_operacion_sin_cerrar_aparece_como_pendiente_solo_para_su_documento(tmp_path):
    d = op.Diario(tmp_path)
    d.iniciar("op_1", "docA", "h", [])
    d.iniciar("op_2", "docB", "h", [])
    d.finalizar("op_2", "aplicada")
    assert [x["op_id"] for x in d.pendientes("docA")] == ["op_1"] and d.pendientes("docB") == []
    d.finalizar("op_1", "incierta")
    assert d.pendientes("docA")[0]["estado"] == "incierta"


def test_la_escritura_es_atomica_sin_temporales_sobrantes(tmp_path):
    d = op.Diario(tmp_path)
    d.iniciar("op_1", "docA", "h", [])
    d.finalizar("op_1", "fallida")
    assert [p.name for p in tmp_path.iterdir()] == ["op_1.json"]
    (tmp_path / "op_9.json").write_text("{roto", encoding="utf-8")                 # un archivo danado no tumba la busqueda
    assert d.pendientes("docA") == []


def test_estado_invalido_se_rechaza(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        op.Diario(tmp_path).finalizar("op_1", "terminada")


# ------------------------------------------------------------------------------------------------ reconciliacion
ESP = [{"item_id": "i1", "bloque": "A", "x": 0.0, "y": 0.0}, {"item_id": "i2", "bloque": "A", "x": 1.0, "y": 0.0}]


def test_todo_marcado_es_aplicada():
    r = op.reconciliar(ESP, [{"item_id": "i1", "handle": "1"}, {"item_id": "i2", "handle": "2"}], [], [])
    assert r["estado"] == "aplicada" and r["aplicados"] == 2 and not r["adoptables"] and not r["requiere_reconciliacion"]


def test_la_entidad_sin_marca_del_hueco_se_adopta_solo_si_es_la_unica_candidata():
    r = op.reconciliar(ESP, [{"item_id": "i1", "handle": "1"}], [{"handle": "9", "bloque": "A", "x": 1.01, "y": 0.0}], previos=[])
    assert r["estado"] == "parcial" and r["adoptables"] == [{"item_id": "i2", "handle": "9"}] and r["pendientes"] == []


def test_lo_que_ya_existia_antes_de_la_operacion_nunca_se_adopta():
    r = op.reconciliar(ESP, [{"item_id": "i1", "handle": "1"}], [{"handle": "9", "bloque": "A", "x": 1.0, "y": 0.0}], previos=["9"])
    assert r["adoptables"] == [] and r["pendientes"] == ["i2"]


def test_dos_candidatos_o_un_candidato_para_dos_piezas_es_ambiguo_y_pide_reconciliacion():
    dos = op.reconciliar(ESP[1:], [], [{"handle": "8", "bloque": "A", "x": 1.0, "y": 0.0}, {"handle": "9", "bloque": "A", "x": 1.01, "y": 0.0}], [])
    assert dos["adoptables"] == [] and dos["ambiguas"][0]["candidatos"] == ["8", "9"] and dos["requiere_reconciliacion"]
    cerca = [{"item_id": "i1", "bloque": "A", "x": 0.0, "y": 0.0}, {"item_id": "i2", "bloque": "A", "x": 0.03, "y": 0.0}]
    uno = op.reconciliar(cerca, [], [{"handle": "5", "bloque": "A", "x": 0.015, "y": 0.0}], [])
    assert uno["adoptables"] == [] and len(uno["ambiguas"]) == 2


def test_otro_producto_o_fuera_de_tolerancia_no_se_adopta():
    r = op.reconciliar(ESP[1:], [], [{"handle": "9", "bloque": "B", "x": 1.0, "y": 0.0}, {"handle": "8", "bloque": "A", "x": 1.2, "y": 0.0}], [])
    assert r["adoptables"] == [] and r["pendientes"] == ["i2"]
