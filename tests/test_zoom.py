import _probe_vista as pv
import acad
import server


class Modelo:
    Count = 3


class Doc:
    ModelSpace = Modelo()

    def __init__(self):
        self.centro = (-5000.0, 40.0, 0.0)

    def GetVariable(self, n):
        return {"VIEWCTR": self.centro, "VIEWSIZE": 12.0, "CTAB": "Model"}[n]


class App:
    def __init__(self, doc):
        self.doc, self.zooms = doc, 0

    def ZoomExtents(self):
        self.zooms += 1
        self.doc.centro = (1000.0, 250.0, 0.0)


def test_zoom_solo_cambia_la_vista():
    d = Doc()
    a = App(d)
    r = pv.zoom_extents(a, d)
    assert a.zooms == 1 and r["ok"] and r["objetos_en_modelo"] == 3
    assert r["vista_antes"]["centro"] == [-5000.0, 40.0] and r["vista_despues"]["centro"] == [1000.0, 250.0]


def test_zoom_no_llama_a_autocad_si_no_responde(monkeypatch):
    llamado = []
    monkeypatch.setattr(acad, "estado", lambda t=10: {"ok": False, "error": "autocad_no_responde", "detalle": "x"})
    monkeypatch.setattr(acad, "_correr", lambda *a, **k: llamado.append(1))
    assert acad.zoom_extents()["error"] == "autocad_no_responde" and not llamado


def test_zoom_sin_dibujo(monkeypatch):
    monkeypatch.setattr(acad, "estado", lambda t=10: {"ok": True, "dibujo_activo": None})
    assert acad.zoom_extents()["error"] == "sin_dibujo"


def test_herramienta_del_servidor(monkeypatch):
    monkeypatch.setattr(server.acad, "zoom_extents", lambda timeout_s: {"ok": True, "t": timeout_s})
    assert server.zoom_extents() == {"ok": True, "t": 10.0}
