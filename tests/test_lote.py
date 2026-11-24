import pytest

import sonda_escribir as pe
import productos
import server
from test_fase3 import Doc, MK


def varios(doc, grupos, ejecutar=True, max_objetos=300):
    return pe.ejecutar_op(doc, {"op": "insertar_varios", "grupos": grupos, "ejecutar": ejecutar, "max_objetos": max_objetos}, mk=MK)


G = lambda n, c, pts: {"nombre": n, "capa": c, "puntos": pts}  # noqa: E731


# ---------- sonda ----------
def test_varios_inserta_cada_grupo_con_su_capa_y_rotacion():
    d = Doc(bloques=["58a", "kp"])
    r = varios(d, [G("58a", "DL-TEST-ILUMINACION", [[0, 0, 0], [10, 0, 90]]), G("kp", "DL-TEST-CONTROL", [[5, 5, 180]])])
    assert r["ok"] and r["total_insertados"] == 3
    capas = [(n, ref.Layer) for (_, n, _, ref) in d.ModelSpace.insertados]
    assert capas == [("58a", "DL-TEST-ILUMINACION"), ("58a", "DL-TEST-ILUMINACION"), ("kp", "DL-TEST-CONTROL")]
    assert {"DL-TEST-ILUMINACION", "DL-TEST-CONTROL"} <= d.Layers.nombres


def test_varios_ensayo_no_escribe():
    d = Doc(bloques=["58a"])
    r = varios(d, [G("58a", "DL-TEST-X", [[0, 0, 0]])], ejecutar=False)
    assert r["ok"] and r["ejecutado"] is False and r["total_insertados"] == 1
    assert d.ModelSpace.insertados == [] and d.Layers.agregados == []


def test_varios_todo_o_nada_si_falta_un_bloque():
    d = Doc(bloques=["58a"])
    r = varios(d, [G("58a", "DL-TEST-X", [[0, 0, 0]]), G("noexiste", "DL-TEST-Y", [[1, 1, 0]])])
    assert r["error"] == "bloque_no_existe" and r["faltan"] == ["noexiste"]
    assert d.ModelSpace.insertados == [] and d.Layers.agregados == []   # ni siquiera el valido


def test_varios_se_niega_en_dibujo_grande():
    d = Doc(objetos=5000, bloques=["58a"])
    r = varios(d, [G("58a", "DL-TEST-X", [[0, 0, 0]])])
    assert r["error"] == "dibujo_grande_requiere_confirmacion" and d.ModelSpace.insertados == []


def test_insertar_simple_sigue_funcionando_con_el_ayudante():
    d = Doc(bloques=["58a"])
    r = pe.ejecutar_op(d, {"op": "insertar", "nombre": "58a", "capa": "DL-TEST-X", "puntos": [[1, 2]],
                           "rotacion_grados": 90, "ejecutar": True, "max_objetos": 300}, mk=MK)
    assert r["cantidad"] == 1 and r["insertados"] == [(1.0, 2.0)] and r["handles"] == ["ABC"]


# ---------- servidor ----------
@pytest.fixture
def hoja_falsa(monkeypatch):
    prods = [
        {"_fila": 2, productos.REF: "AAA1", productos.CORTO: "Downlight", productos.SISTEMA: "Iluminación", productos.BLOQUE: "58a"},
        {"_fila": 3, productos.REF: "KP1", productos.CORTO: "Keypad", productos.SISTEMA: "Control", productos.BLOQUE: "kp"},
        {"_fila": 4, productos.REF: "NOBLK", productos.CORTO: "Sin bloque", productos.SISTEMA: "Audio", productos.BLOQUE: None},
        {"_fila": 5, productos.REF: "SIN REFERENCIA", productos.CORTO: "Uno", productos.SISTEMA: "Audio", productos.BLOQUE: "a1"},
        {"_fila": 6, productos.REF: "SIN REFERENCIA", productos.CORTO: "Dos", productos.SISTEMA: "Audio", productos.BLOQUE: "a2"},
    ]
    monkeypatch.setattr(server, "_hoja", lambda: ([], prods))
    llamadas = []
    monkeypatch.setattr(server.acad, "escribir",
                        lambda args, timeout_s=10.0, timeout_escritura_s=30.0: llamadas.append(args) or {"ok": True, "ejecutado": args["ejecutar"]})
    return llamadas


def test_lote_agrupa_por_bloque_y_capa(hoja_falsa):
    r = server.insertar_productos([
        {"referencia": "aaa1", "x": 0, "y": 0}, {"referencia": "AAA1", "x": 100, "y": 0, "rotacion_grados": 45},
        {"referencia": "KP1", "x": 5, "y": 5}], ejecutar=True)
    g = {(x["nombre"], x["capa"]): x["puntos"] for x in hoja_falsa[0]["grupos"]}
    assert g == {("58a", "DL-TEST-ILUMINACION"): [[0.0, 0.0, 0.0], [100.0, 0.0, 45.0]], ("kp", "DL-TEST-CONTROL"): [[5.0, 5.0, 0.0]]}
    assert hoja_falsa[0]["op"] == "insertar_varios" and hoja_falsa[0]["max_objetos"] == 300 and len(r["items"]) == 3


def test_lote_por_defecto_es_ensayo(hoja_falsa):
    r = server.insertar_productos([{"referencia": "AAA1", "x": 0, "y": 0}])
    assert hoja_falsa[0]["ejecutar"] is False and "ENSAYO" in r["aviso"]


def test_lote_todo_o_nada_lista_todos_los_problemas_y_no_llama_a_autocad(hoja_falsa):
    r = server.insertar_productos([
        {"referencia": "AAA1", "x": 0, "y": 0},            # valido
        {"referencia": "NOEXISTE", "x": 1, "y": 1},
        {"referencia": "NOBLK", "x": 2, "y": 2},
        {"referencia": "SIN REFERENCIA", "x": 3, "y": 3},
        {"referencia": "AAA1", "x": "a", "y": 1},
        {"referencia": "AAA1", "y": 1}], ejecutar=True)
    assert r["error"] == "items_con_problemas" and hoja_falsa == []
    errores = {p["item"]: p["error"] for p in r["problemas"]}
    assert errores == {2: "no_encontrado", 3: "sin_bloque_asignado", 4: "referencia_ambigua", 5: "coordenadas_invalidas", 6: "coordenadas_invalidas"}


def test_lote_repetida_se_resuelve_con_fila_excel(hoja_falsa):
    r = server.insertar_productos([{"referencia": "SIN REFERENCIA", "fila_excel": 5, "x": 0, "y": 0}], ejecutar=True)
    assert r["ok"] and hoja_falsa[0]["grupos"][0]["nombre"] == "a1"


@pytest.mark.parametrize("items", [[], "x", None, [{"referencia": "AAA1", "x": 0, "y": 0}] * 101])
def test_lote_tamano_invalido(hoja_falsa, items):
    assert server.insertar_productos(items, ejecutar=True)["error"] == "items_invalidos" and hoja_falsa == []


def test_lote_desactivado_no_llama_a_autocad(hoja_falsa, monkeypatch):
    monkeypatch.setitem(server.CFG, "escritura", {"habilitada": False})
    assert server.insertar_productos([{"referencia": "AAA1", "x": 0, "y": 0}], ejecutar=True)["error"] == "escritura_desactivada"
    assert hoja_falsa == []


def test_lote_error_de_autocad_se_propaga(hoja_falsa, monkeypatch):
    monkeypatch.setattr(server.acad, "escribir", lambda *a, **k: {"ok": False, "error": "bloque_no_existe", "faltan": ["58a"], "detalle": "x"})
    r = server.insertar_productos([{"referencia": "AAA1", "x": 0, "y": 0}], ejecutar=True)
    assert r["error"] == "bloque_no_existe" and r["faltan"] == ["58a"]
