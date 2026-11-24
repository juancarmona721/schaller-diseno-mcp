"""Flujo acordado para las REFERENCIAS de las fichas (regla del equipo de diseno, 2026-11-10).

1. Durante el diseno, las fichas del DWG llevan SOLO nombre y descripcion.
2. La referencia (REF) queda vacia / "POR DEFINIR". Nunca se inventa ni se deduce.
3. La referencia real se llena al final: plano terminado + cotizacion disponible.
Sin dependencias de AutoCAD ni de la hoja: solo texto y un archivo JSON local con las referencias confirmadas.
"""
import json
from datetime import date
from pathlib import Path

MARCADOR = "POR DEFINIR (cotizacion)"

REGLA = (
    "Las fichas del DWG llevan SOLO nombre y descripcion mientras se disena. La referencia (REF) queda vacia o como "
    f"'{MARCADOR}': no se inventa ni se deduce de la hoja de prueba. Cuando el plano este TERMINADO y exista la "
    "COTIZACION, se pide la cotizacion (o la lista de referencias exactas) al usuario y solo entonces se llenan las REF."
)


def _norm(t: str) -> str:
    return " ".join(str(t).split()).casefold()


def cargar(ruta: Path) -> dict:
    """Referencias confirmadas {producto_normalizado: {producto, referencia, fuente, fecha}}."""
    if not Path(ruta).exists():
        return {}
    with open(ruta, encoding="utf-8") as fh:
        return json.load(fh)


def pendientes(productos: list[str], confirmadas: dict) -> tuple[list[str], list[dict]]:
    sin = [p for p in productos if _norm(p) not in confirmadas]
    con = [confirmadas[_norm(p)] for p in productos if _norm(p) in confirmadas]
    return sin, con


def guardar(ruta: Path, items: list[dict], fuente: str) -> dict:
    """Guarda referencias confirmadas. Cada item: {producto, referencia}. Referencia vacia o con el marcador: error."""
    actuales = cargar(ruta)
    for it in items:
        prod = str(it.get("producto", "")).strip()
        ref = str(it.get("referencia", "")).strip()
        if not prod or not ref or ref.casefold().startswith("por definir"):
            raise ValueError(f"item invalido (falta producto o referencia real): {it!r}")
    for it in items:
        prod, ref = it["producto"].strip(), it["referencia"].strip()
        actuales[_norm(prod)] = {"producto": prod, "referencia": ref, "fuente": fuente, "fecha": date.today().isoformat()}
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(actuales, fh, ensure_ascii=False, indent=2)
    return actuales


def solicitud(sin_referencia: list[str]) -> str:
    """Texto que el asistente debe mostrar al usuario cuando el plano este terminado."""
    lista = "\n".join(f"  - {p}" for p in sin_referencia) or "  (ninguno)"
    return (
        "El plano esta terminado? Para completar las fichas necesito las referencias reales.\n"
        "Por favor entregame UNA de estas dos cosas:\n"
        "  1) la cotizacion final (indica donde esta el archivo; yo pediria tu permiso antes de abrirlo), o\n"
        "  2) la lista de referencias exactas, producto por producto.\n"
        f"Productos que aun NO tienen referencia confirmada:\n{lista}\n"
        "No voy a inventar ni deducir ninguna referencia: hasta entonces seguiran como "
        f"'{MARCADOR}'."
    )
