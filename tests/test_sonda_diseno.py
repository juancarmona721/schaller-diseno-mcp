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


def test_si_el_bloque_no_esta_en_ningun_lado_se_crea_la_definicion_interna():
    plano = Doc("plano.dwg")
    faltan, origenes, errores = sd._asegurar_bloques(Acad(plano, Doc("bloques_schaller.dwg", ["otro"])), plano, ["SIMBIOSI"])
    assert faltan == [] and origenes == {"SIMBIOSI": "definicion_interna"} and errores == {}
    assert len(plano.Blocks.Item("SIMBIOSI").circulos) == 9


def test_un_bloque_sin_definicion_interna_ni_origen_se_reporta_como_faltante():
    plano = Doc("plano.dwg")
    faltan, origenes, _ = sd._asegurar_bloques(Acad(plano), plano, ["BloqueDesconocido"])
    assert faltan == ["BloqueDesconocido"] and origenes == {}


def test_lo_que_ya_esta_en_el_plano_no_se_toca():
    plano = Doc("plano.dwg", ["SIMBIOSI"])
    faltan, origenes, _ = sd._asegurar_bloques(Acad(plano), plano, ["SIMBIOSI"])
    assert faltan == [] and origenes == {} and plano.Blocks.Item("SIMBIOSI").circulos == []
