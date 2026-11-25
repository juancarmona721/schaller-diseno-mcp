"""Logica de la sonda de diseno con un AutoCAD simulado (sin COM real)."""
import sonda_diseno as sd


class Bloque:
    def __init__(self):
        self.circulos = []

    def AddCircle(self, centro, radio):
        self.circulos.append((centro, radio))


class Coleccion:
    def __init__(self, nombres=()):
        self.items = {n: Bloque() for n in nombres}

    def Item(self, nombre):
        if nombre not in self.items:
            raise KeyError(nombre)
        return self.items[nombre]

    def Add(self, punto, nombre):
        self.items[nombre] = Bloque()
        return self.items[nombre]


class Doc:
    def __init__(self, nombre, bloques=()):
        self.Name, self.Blocks = nombre, Coleccion(bloques)


class Acad:
    def __init__(self, *docs):
        self.Documents = list(docs)


def test_si_el_bloque_no_esta_en_ningun_lado_se_crea_la_definicion_interna(monkeypatch):
    # El mecanismo se conserva aunque hoy no haya definiciones propias (la biblioteca corregida trae todo).
    monkeypatch.setattr(sd.motor_ubicacion, "DEFINICIONES_INTERNAS", {"BloqueDePrueba": {"circulos": [[0, 0, 0.1]] * 9}})
    plano = Doc("plano.dwg")
    faltan, origenes, errores = sd._asegurar_bloques(Acad(plano, Doc("bloques_schaller_corregido.dwg", ["otro"])), plano, ["BloqueDePrueba"])
    assert faltan == [] and origenes == {"BloqueDePrueba": "definicion_interna"} and errores == {}
    assert len(plano.Blocks.Item("BloqueDePrueba").circulos) == 9


def test_la_biblioteca_corregida_tiene_prioridad_aunque_su_nombre_lleve_espacio(monkeypatch):
    plano = Doc("plano.dwg")
    antigua = Doc("bloques_schaller.dwg", ["Simbiosis_Davide Groppi"])
    corregida = Doc("bloques schaller_corregido.dwg", ["Simbiosis_Davide Groppi"])         # nombre real: con ESPACIO
    otro = Doc("otro_plano.dwg", ["Simbiosis_Davide Groppi"])
    # Se copia del primero que lo tenga segun la prioridad; sin Add real, se comprueba que el origen declarado es la corregida.
    copiado = []
    monkeypatch.setattr(sd, "_copiar_definicion", lambda origen, destino, nombre: (copiado.append(origen.Name), destino.Blocks.Add(None, nombre)))
    faltan, origenes, _ = sd._asegurar_bloques(Acad(plano, otro, antigua, corregida), plano, ["Simbiosis_Davide Groppi"])
    assert copiado == ["bloques schaller_corregido.dwg"] and origenes == {"Simbiosis_Davide Groppi": "biblioteca_corregida"} and faltan == []


def test_sin_corregida_usa_la_antigua_y_luego_cualquier_dibujo(monkeypatch):
    plano = Doc("plano.dwg")
    copiado = []
    monkeypatch.setattr(sd, "_copiar_definicion", lambda origen, destino, nombre: (copiado.append(origen.Name), destino.Blocks.Add(None, nombre)))
    _, origenes, _ = sd._asegurar_bloques(Acad(plano, Doc("otro.dwg", ["B"]), Doc("bloques_schaller.dwg", ["B"])), plano, ["B"])
    assert copiado == ["bloques_schaller.dwg"] and origenes == {"B": "biblioteca_antigua"}
    plano2 = Doc("plano2.dwg")
    _, origenes2, _ = sd._asegurar_bloques(Acad(plano2, Doc("otro.dwg", ["B"])), plano2, ["B"])
    assert origenes2 == {"B": "otro_dibujo_abierto"}


def test_diagnostico_distingue_biblioteca_corregida_de_la_antigua():
    nueva = Acad(Doc("plano.dwg"), Doc("bloques schaller_corregido.dwg"))
    d = sd.op_diagnostico(nueva, nueva.Documents[0])
    assert d["biblioteca_corregida_abierta"] is True and d["bibliotecas_abiertas"] == ["bloques schaller_corregido.dwg"]
    vieja = Acad(Doc("plano.dwg"), Doc("bloques_schaller.dwg"))
    d = sd.op_diagnostico(vieja, vieja.Documents[0])
    assert d["biblioteca_abierta"] is True and d["biblioteca_corregida_abierta"] is False
    assert sd.op_diagnostico(Acad(Doc("plano.dwg")), Doc("plano.dwg"))["biblioteca_abierta"] is False


def test_un_bloque_sin_definicion_interna_ni_origen_se_reporta_como_faltante():
    plano = Doc("plano.dwg")
    faltan, origenes, _ = sd._asegurar_bloques(Acad(plano), plano, ["BloqueDesconocido"])
    assert faltan == ["BloqueDesconocido"] and origenes == {}


def test_lo_que_ya_esta_en_el_plano_no_se_toca():
    plano = Doc("plano.dwg", ["SIMBIOSI"])
    faltan, origenes, _ = sd._asegurar_bloques(Acad(plano), plano, ["SIMBIOSI"])
    assert faltan == [] and origenes == {} and plano.Blocks.Item("SIMBIOSI").circulos == []



def test_reintenta_ante_autocad_ocupado_o_com_sin_respuesta_pero_no_ante_errores_reales():
    assert sd._rechazada(Exception("(-2147418111, 'La llamada fue rechazada por el destinatario.')"))
    assert sd._rechazada(AttributeError("Add.Count")) and sd._rechazada(AttributeError("<unknown>.Item"))   # COM dinamico sin respuesta
    assert not sd._rechazada(AttributeError("'NoneType' object has no attribute 'x'"))                       # un error de programa no se reintenta
    assert not sd._rechazada(KeyError("x")) and not sd._rechazada(ValueError("fallo real"))


def test_reintentar_se_recupera_de_un_fallo_pasajero(monkeypatch):
    monkeypatch.setattr(sd.time, "sleep", lambda s: None)
    llamadas = []

    def inestable():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise AttributeError("Add.Count")
        return "ok"
    assert sd.reintentar(inestable) == "ok" and len(llamadas) == 3
    with __import__("pytest").raises(ValueError):
        sd.reintentar(lambda: (_ for _ in ()).throw(ValueError("real")))
