"""Fichas de producto: arma el contenido y lo dibuja en HTML (una pagina por producto + un indice).

Convencion (la misma de la hoja de PRUEBA): lo INVENTADO se muestra en naranja cursiva y la ficha lleva un aviso de PRUEBA.
Nunca se inventan referencias ni nombres de bloque: si falta, se escribe "sin dato".
Solo escribe dentro de la carpeta configurada ([fichas].carpeta).
"""
import datetime
import html
import re
import zlib
from pathlib import Path

import productos as P

SIN_DATO = "sin dato"
CAMPOS_TECNICOS = ["Instalación", "Voltaje", "W por unidad", "Tipo de conexión", "Driver"]


def _elige(opciones, ref, sal):
    """Eleccion estable (siempre la misma para el mismo producto): los datos inventados no cambian entre corridas."""
    return opciones[zlib.crc32(f"{ref}|{sal}".encode()) % len(opciones)]


def extras_inventados(p: dict) -> list[tuple[str, str]]:
    """Especificaciones adicionales INVENTADAS (solo para probar el formato), segun el tipo de producto."""
    ref, nom = str(p.get(P.REF)), P.norm(p.get(P.CORTO))
    sis, ext = P.norm(p.get(P.SISTEMA)), ("outdoor" in nom or "exterior" in nom)
    negro = "negro" in nom
    if sis == "iluminacion":
        return [
            ("Descripción", "Luminaria LED de diseño para " + ("uso exterior." if ext else "uso interior.")),
            ("Dimensiones", _elige(["Ø 58 mm", "Ø 80 mm", "Ø 120 mm", "250 × 40 mm"], ref, "dim")),
            ("Acabado", "Negro mate" if negro else _elige(["Blanco mate", "Latón cepillado", "Aluminio anodizado"], ref, "acab")),
            ("Grado de protección", "IP65" if ext else "IP20"),
            ("Temperatura de color", _elige(["2700 K", "3000 K", "4000 K"], ref, "k")),
            ("Índice de reproducción cromática", "CRI ≥ 90"),
            ("Ángulo de haz", _elige(["24°", "36°", "60°"], ref, "haz")),
            ("Vida útil", "50.000 h (L80)"),
            ("Garantía", "5 años"),
        ]
    if sis == "cinta led":
        return [
            ("Descripción", "Cinta LED flexible para iluminación indirecta."),
            ("Ancho de la cinta", "10 mm"),
            ("LEDs por metro", _elige(["120", "168", "240"], ref, "leds")),
            ("Corte mínimo", "50 mm"),
            ("Temperatura de color", _elige(["2700 K", "3000 K", "4000 K"], ref, "k")),
            ("Índice de reproducción cromática", "CRI ≥ 90"),
            ("Garantía", "3 años"),
        ]
    if sis == "audio":
        sub = "subwoofer" in nom
        return [
            ("Descripción", "Subwoofer de alto rendimiento para sistemas residenciales." if sub else "Parlante de alta fidelidad para instalación arquitectónica."),
            ("Montaje", "Sobreponer" if sub else _elige(["Empotrado en cielo", "Empotrado en pared", "Sobreponer"], ref, "mont")),
            ("Impedancia nominal", "8 Ω"),
            ("Respuesta en frecuencia", "28 Hz – 140 Hz" if sub else _elige(["50 Hz – 20 kHz", "60 Hz – 28 kHz"], ref, "resp")),
            ("Sensibilidad", "88 dB"),
            ("Potencia máxima", _elige(["100 W", "150 W", "200 W"], ref, "pot")),
            ("Acabado", "Blanco"),
            ("Garantía", "5 años"),
        ]
    if sis == "control":
        return [
            ("Descripción", "Teclado de control de escenas para pared."),
            ("Número de botones", _elige(["6", "8"], ref, "bot")),
            ("Retroiluminación", "LED ajustable"),
            ("Acabado", "Negro" if negro else "Blanco"),
            ("Garantía", "3 años"),
        ]
    if sis == "redes":
        return [
            ("Descripción", "Punto de acceso inalámbrico" + (" para exterior." if ext else " para techo.")),
            ("Estándar Wi-Fi", "Wi-Fi 6 (802.11ax)"),
            ("Bandas", "2,4 GHz + 5 GHz"),
            ("Alimentación", "PoE 802.3at"),
            ("Grado de protección", "IP67" if ext else "IP20"),
            ("Garantía", "2 años"),
        ]
    return [("Descripción", "Producto de prueba.")]


def _vacio(v):
    return P.es_vacio(v)


def armar_ficha(p: dict, accesorios: list[dict], capa_sugerida: str) -> dict:
    inv = set(P.campos_inventados(p))
    campo = lambda nombre, valor, inventado=False: {"nombre": nombre, "valor": SIN_DATO if _vacio(valor) else str(valor),  # noqa: E731
                                                    "inventado": bool(inventado) and not _vacio(valor), "vacio": _vacio(valor)}
    ident = [campo("Referencia (Odoo)", p.get(P.REF)), campo("Nombre en Odoo", p.get(P.ODOO)),
             campo("Marca (sigla)", p.get(P.MARCA), P.MARCA in inv), campo("Sistema", p.get(P.SISTEMA))]
    tecnicos = [campo(c, p.get(c), c in inv) for c in CAMPOS_TECNICOS]
    adicionales = [{**campo(n, v, True)} for n, v in extras_inventados(p)]
    bloques = P.bloques_cad(p)
    cad = {"bloques": bloques, "capa_sugerida": capa_sugerida, "por_confirmar": True}
    asoc = [{"referencia": a.get("referencia"), "nombre_corto": a.get("nombre_corto"), "tipo": a.get("tipo"), "marca": a.get("marca")}
            for a in P.accesorios_de(p, accesorios)]
    n_inv = sum(c["inventado"] for c in ident + tecnicos + adicionales)
    return {
        "fila_excel": p["_fila"], "referencia": p.get(P.REF), "nombre_corto": p.get(P.CORTO), "sistema": p.get(P.SISTEMA),
        "marca": p.get(P.MARCA), "identificacion": ident, "tecnicos": tecnicos, "adicionales": adicionales,
        "accesorios": asoc, "cad": cad, "fuente": p.get("Fuente de los datos"), "notas": p.get("Notas / por confirmar"),
        "campos_inventados_hoja": sorted(inv), "total_campos_inventados": n_inv, "es_prueba": n_inv > 0,
    }


# ---------------------------------------------------------------- HTML
CSS = """
:root{--fondo:#f4f2ee;--papel:#fff;--tinta:#1d1b19;--suave:#6b665f;--linea:#e2ded7;--acento:#2f4b45;--inv:#b9500a;--invfondo:#fff3e8;--aviso:#fff3e8}
*{box-sizing:border-box}body{margin:0;background:var(--fondo);color:var(--tinta);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
.pagina{max-width:860px;margin:24px auto;background:var(--papel);border:1px solid var(--linea);padding:36px 40px}
.banner{background:var(--aviso);border:1px solid #f0c9a6;color:var(--inv);padding:8px 14px;font-weight:600;font-size:13px;letter-spacing:.02em;margin:0 0 22px}
.marca{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--suave)}
h1{font-size:30px;line-height:1.15;margin:4px 0 6px;color:var(--acento)}.ref{font:600 14px ui-monospace,Consolas,monospace;color:var(--suave)}
h2{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--acento);border-bottom:2px solid var(--acento);padding-bottom:4px;margin:28px 0 10px}
dl{display:grid;grid-template-columns:210px 1fr;gap:0;margin:0}dt,dd{margin:0;padding:6px 0;border-bottom:1px solid var(--linea)}dt{color:var(--suave);font-size:13px}
.inv{color:var(--inv);font-style:italic;background:var(--invfondo);padding:0 4px}.sd{color:#9a958d}
table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;font-size:12px;color:var(--suave);font-weight:600;padding:6px 8px 6px 0;border-bottom:1px solid var(--linea)}td{padding:6px 8px 6px 0;border-bottom:1px solid var(--linea)}
.idx{table-layout:fixed}.idx th:nth-child(1){width:38%}.idx th:nth-child(2){width:24%}.idx th:nth-child(3){width:10%}.idx th:nth-child(4){width:12%}
.idx td{overflow-wrap:anywhere}
.leyenda{margin-top:30px;font-size:12px;color:var(--suave);border-top:1px solid var(--linea);padding-top:10px}
a{color:var(--acento)}.vacio{color:#9a958d}
@media(max-width:620px){.pagina{padding:22px 18px;margin:0}dl{grid-template-columns:1fr}dt{border-bottom:0;padding-bottom:0}}
@media print{body{background:#fff}.pagina{border:0;margin:0;max-width:none;padding:0}}
"""


def _v(c: dict) -> str:
    t = html.escape(c["valor"])
    if c["inventado"]:
        return f'<span class="inv" title="Dato inventado (PRUEBA)">{t}</span>'
    return f'<span class="sd">{t}</span>' if c.get("vacio") else t


def _dl(campos) -> str:
    return "<dl>" + "".join(f"<dt>{html.escape(c['nombre'])}</dt><dd>{_v(c)}</dd>" for c in campos) + "</dl>"


def html_ficha(f: dict) -> str:
    e = html.escape
    banner = (f'<p class="banner">FICHA DE PRUEBA — contiene {f["total_campos_inventados"]} datos inventados (en naranja cursiva). '
              "No usar en cotizaciones, fichas finales ni planos reales.</p>") if f["es_prueba"] else ""
    if f["accesorios"]:
        filas = "".join(f"<tr><td>{e(str(a['tipo'] or SIN_DATO))}</td><td>{e(str(a['nombre_corto'] or SIN_DATO))}</td>"
                        f"<td>{e(str(a['marca'] or SIN_DATO))}</td><td class=\"ref\">{e(str(a['referencia'] or SIN_DATO))}</td></tr>"
                        for a in f["accesorios"])
        acc = f"<table><tr><th>Tipo</th><th>Nombre</th><th>Marca</th><th>Referencia</th></tr>{filas}</table>"
    else:
        acc = '<p class="vacio">Sin drivers ni accesorios asociados en la hoja.</p>'
    cad = f["cad"]
    bl = ", ".join(e(b) for b in cad["bloques"]) if cad["bloques"] else '<span class="sd">sin bloque asignado</span>'
    cad_html = (f"<dl><dt>Bloque en CAD</dt><dd>{bl} <span class=\"sd\">(por confirmar)</span></dd>"
                f"<dt>Capa sugerida</dt><dd>{e(cad['capa_sugerida'])}</dd></dl>")
    notas_html = e(str(f["notas"])) if not P.es_vacio(f["notas"]) else '<span class="sd">sin notas</span>'
    fuente_html = (f"<dl><dt>Fuente de los datos</dt><dd>{e(str(f['fuente'] or SIN_DATO))}</dd>"
                   f"<dt>Notas / por confirmar</dt><dd>{notas_html}</dd></dl>")
    inv_hoja = ", ".join(e(c) for c in f["campos_inventados_hoja"]) or "ninguno"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ficha — {e(str(f['nombre_corto']))}</title><style>{CSS}</style></head><body><main class="pagina">
{banner}<div class="marca">{e(str(f['marca'] or SIN_DATO))} · {e(str(f['sistema'] or SIN_DATO))}</div>
<h1>{e(str(f['nombre_corto']))}</h1><div class="ref">{e(str(f['referencia']))}</div>
<h2>Identificación</h2>{_dl(f['identificacion'])}
<h2>Datos técnicos (hoja de productos)</h2>{_dl(f['tecnicos'])}
<h2>Especificaciones adicionales</h2>{_dl(f['adicionales'])}
<h2>Drivers y accesorios asociados</h2>{acc}
<h2>En CAD</h2>{cad_html}
<h2>Fuente y pendientes</h2>{fuente_html}
<p class="leyenda"><span class="inv">naranja cursiva</span> = dato inventado (PRUEBA). Campos inventados en la hoja: {inv_hoja}.
Fila {f['fila_excel']} de la hoja · generada el {datetime.date.today().isoformat()} · <a href="indice.html">volver al índice</a></p>
</main></body></html>"""


def nombre_archivo(f: dict) -> str:
    return f"fila{int(f['fila_excel']):02d}_{re.sub(r'[^A-Za-z0-9._-]+', '-', str(f['referencia']))}.html"


def html_indice(fichas: list[dict]) -> str:
    e = html.escape
    grupos = {}
    for f in fichas:
        grupos.setdefault(f["sistema"] or SIN_DATO, []).append(f)
    cuerpo = ""
    for sis, lst in grupos.items():
        filas = ""
        for f in lst:
            n_inv = '<span class="inv">' + str(f["total_campos_inventados"]) + "</span>" if f["es_prueba"] else "0"
            filas += (f'<tr><td><a href="{e(nombre_archivo(f))}">{e(str(f["nombre_corto"]))}</a></td>'
                      f'<td class="ref">{e(str(f["referencia"]))}</td><td>{e(str(f["marca"] or SIN_DATO))}</td>'
                      f'<td>{len(f["accesorios"])}</td><td>{n_inv}</td></tr>')
        cuerpo += (f'<h2>{e(str(sis))} ({len(lst)})</h2><table class="idx"><tr><th>Producto</th><th>Referencia</th><th>Marca</th>'
                   f"<th>Accesorios</th><th>Datos inventados</th></tr>{filas}</table>")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fichas de producto — índice</title><style>{CSS}</style></head><body><main class="pagina">
<p class="banner">FICHAS DE PRUEBA — generadas desde la hoja de productos de PRUEBA con datos inventados.</p>
<h1>Fichas de producto</h1><div class="ref">{len(fichas)} fichas · {datetime.date.today().isoformat()}</div>{cuerpo}
<p class="leyenda"><span class="inv">naranja cursiva</span> = dato inventado (PRUEBA).</p></main></body></html>"""


# ---------------------------------------------------------------- TARJETAS (formato de la referencia)
CSS_TARJ = """
:root{--tinta:#111;--azul:#1b3fa0;--inv:#b9500a;--invfondo:#fff3e8;--linea:#222}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--tinta);font:12px/1.25 "Arial Narrow","Segoe UI Semibold",Arial,sans-serif}
.hoja{max-width:1500px;margin:14px auto;padding:0 14px}
.banner{background:#fff3e8;border:1px solid #f0c9a6;color:var(--inv);padding:6px 10px;font-weight:700;font-size:12px;margin-bottom:14px}
h2{font:700 13px "Segoe UI",Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;margin:18px 0 8px}
.fila{display:flex;gap:14px;align-items:flex-start}.grid{display:flex;flex-wrap:wrap;gap:10px;flex:1}
.t{width:178px;border:1px solid var(--linea);background:#fff;break-inside:avoid}
.t .c{border-bottom:1px solid var(--linea);padding:3px 5px;min-height:22px}.t .c:last-child{border-bottom:0}
.t b{font-weight:700;text-transform:uppercase}.v{color:var(--azul)}.inv{color:var(--inv);font-style:italic;background:var(--invfondo)}.sd{color:#8a8a8a}
.sim{height:92px;display:flex;align-items:center;justify-content:center;padding:6px}.sim svg{max-width:100%;max-height:80px;width:auto;height:auto}
.sim .nosim{border:1px dashed #aaa;color:#8a8a8a;font-size:11px;padding:18px 10px;text-align:center}
.t .cx{min-height:46px}
.ley{width:210px;border:1px solid var(--linea);padding:6px 8px;flex:none}.ley div{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #ddd}.ley div:last-child{border-bottom:0}
.ley svg{width:46px;height:18px;flex:none}
.pie{margin-top:16px;font-size:11px;color:#666}
@page{size:A4 landscape;margin:8mm}@media print{.hoja{max-width:none;margin:0}}
"""

LEYENDA_SVG = [
    ('<svg viewBox="0 0 46 18"><rect x="14" y="2" width="18" height="14" fill="none" stroke="#1e9e3a" stroke-width="2"/>'
     '<text x="23" y="13" font-size="9" text-anchor="middle" fill="#1e9e3a" font-family="Arial">RK</text></svg>', "RACK"),
    ('<svg viewBox="0 0 46 18"><line x1="2" y1="9" x2="44" y2="9" stroke="#1d3fd0" stroke-width="2.5"/></svg>', 'Tubería Ø3/4"'),
    ('<svg viewBox="0 0 46 18"><line x1="2" y1="9" x2="44" y2="9" stroke="#18c6d6" stroke-width="2.5"/></svg>', 'Tubería Ø1"'),
    ('<svg viewBox="0 0 46 18"><line x1="2" y1="9" x2="44" y2="9" stroke="#d62020" stroke-width="2.5"/></svg>', 'Tubería Ø1/2"'),
    ('<svg viewBox="0 0 46 18"><ellipse cx="23" cy="9" rx="5" ry="6" fill="none" stroke="#1d3fd0" stroke-width="1.6"/>'
     '<line x1="23" y1="0" x2="23" y2="4" stroke="#1d3fd0" stroke-width="1.6"/></svg>', "Punto eléctrico"),
    ('<svg viewBox="0 0 46 18"><polygon points="23,2 31,16 15,16" fill="#22c24a"/></svg>', "Punto de datos"),
]


def cantidades_desde_csv(ruta) -> dict:
    """{nombre_de_bloque: copias} desde productos_posiciones.csv (extraccion del plano). {} si no existe."""
    import csv
    from collections import Counter
    if not ruta or not Path(ruta).is_file():
        return {}
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        return dict(Counter(r["bloque"] for r in csv.DictReader(fh)))


def calcular_cantidades(todos: list[dict], elegidos: list[dict], por_bloque: dict) -> tuple[dict, set]:
    """(fila -> cantidad, filas con bloque compartido). Sin bloque o sin copias en el plano -> sin dato (no aparece)."""
    usos = {}
    for p in todos:
        for b in P.bloques_cad(p):
            usos.setdefault(b, set()).add(p["_fila"])
    cant, compartidos = {}, set()
    for p in elegidos:
        bl = P.bloques_cad(p)
        if bl and any(b in por_bloque for b in bl):
            cant[p["_fila"]] = sum(por_bloque.get(b, 0) for b in bl)
            if any(len(usos[b]) > 1 for b in bl):
                compartidos.add(p["_fila"])
    return cant, compartidos


def slug(nombre) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(nombre)).strip("-") or "simbolo"


def _svg_o_vacio(f: dict, svgs: dict) -> str:
    for b in f["cad"]["bloques"]:
        s = svgs.get(b)
        if s and s.lstrip().startswith("<svg") and "<script" not in s.lower():
            return s
    return '<div class="nosim">sin símbolo</div>'


def _t(f: dict, nombre: str) -> dict:
    return next(c for c in f["tecnicos"] if c["nombre"] == nombre)


def _val(c: dict) -> str:
    t = html.escape(c["valor"])
    if c["inventado"]:
        return f'<span class="inv" title="Dato inventado (PRUEBA)">{t}</span>'
    return f'<span class="sd">{t}</span>' if c.get("vacio") else f'<span class="v">{t}</span>'


def html_tarjetas(fichas: list[dict], svgs: dict, cantidades: dict, compartidos=()) -> str:
    """Tira de tarjetas (una por producto) agrupadas por sistema, con la leyenda de convenciones. svgs: bloque -> svg."""
    e = html.escape
    grupos = {}
    for f in fichas:
        grupos.setdefault(f["sistema"] or SIN_DATO, []).append(f)
    cuerpo = ""
    for sis, lst in grupos.items():
        tarjetas = ""
        for f in lst:
            marca = f' <span class="v">({e(str(f["marca"]))})</span>' if not P.es_vacio(f["marca"]) and f["marca"] != "—" else ""
            q = cantidades.get(f["fila_excel"])
            if q is None:
                cant = '<span class="sd">sin dato</span>'
            elif f["fila_excel"] in compartidos:
                cant = f'<span class="v" title="Varios productos comparten este bloque: es la cantidad del bloque">{q}*</span>'
            else:
                cant = f'<span class="v">{q}</span>'
            tarjetas += (
                f'<div class="t"><div class="c"><b>Instalación:</b> {_val(_t(f, "Instalación"))}</div>'
                f'<div class="c sim">{_svg_o_vacio(f, svgs)}</div>'
                f'<div class="c"><b>Ref:</b> <span class="v">{e(str(f["referencia"]))}</span>{marca}</div>'
                f'<div class="c"><b>Description:</b> <span class="v">{e(str(f["nombre_corto"]))}</span></div>'
                f'<div class="c"><b>Cantidad:</b> {cant}</div>'
                f'<div class="c cx"><b>Tipo de conexión:</b><br>{_val(_t(f, "Tipo de conexión"))}</div></div>')
        cuerpo += f"<h2>{e(str(sis))} ({len(lst)})</h2><div class=\"grid\">{tarjetas}</div>"
    ley = "".join(f"<div>{svg}<span>{e(txt)}</span></div>" for svg, txt in LEYENDA_SVG)
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tarjetas de producto</title><style>{CSS_TARJ}</style></head><body><main class="hoja">
<p class="banner">TARJETAS DE PRUEBA — datos inventados en naranja cursiva. Cantidad = copias del bloque en el plano de diseño (extracción); "sin dato" si el producto no tiene bloque; "*" = varios productos comparten el bloque, la cantidad es la del bloque.</p>
<div class="fila"><div style="flex:1">{cuerpo}</div><aside class="ley"><h2 style="margin-top:0">Convenciones</h2>{ley}</aside></div>
<p class="pie">Generado el {datetime.date.today().isoformat()} · <a href="indice.html">índice de fichas</a></p></main></body></html>"""


def generar_tarjetas(fichas: list[dict], svgs: dict, cantidades: dict, carpeta, compartidos=(), nombre="tarjetas.html") -> dict:
    base = Path(carpeta).resolve()
    base.mkdir(parents=True, exist_ok=True)
    destino = (base / nombre).resolve()
    if destino.parent != base or destino.suffix != ".html":  # solo un .html dentro de la carpeta
        raise ValueError(f"Nombre de archivo no valido: {nombre}")
    destino.write_text(html_tarjetas(fichas, svgs, cantidades, compartidos), encoding="utf-8")
    con_simbolo = sum(any(svgs.get(b) for b in f["cad"]["bloques"]) for f in fichas)
    return {"archivo": str(destino), "tarjetas": len(fichas), "con_simbolo": con_simbolo,
            "con_cantidad": sum(cantidades.get(f["fila_excel"]) is not None for f in fichas)}


def generar(fichas: list[dict], carpeta) -> dict:
    """Escribe una pagina por ficha + indice.html SOLO dentro de `carpeta`. Devuelve lo escrito."""
    base = Path(carpeta).resolve()
    base.mkdir(parents=True, exist_ok=True)
    escritos = []
    for f in fichas:
        destino = (base / nombre_archivo(f)).resolve()
        if destino.parent != base:  # nunca fuera de la carpeta
            raise ValueError(f"Ruta fuera de la carpeta de fichas: {destino}")
        destino.write_text(html_ficha(f), encoding="utf-8")
        escritos.append({"fila_excel": f["fila_excel"], "archivo": destino.name, "datos_inventados": f["total_campos_inventados"]})
    (base / "indice.html").write_text(html_indice(fichas), encoding="utf-8")
    return {"carpeta": str(base), "indice": str(base / "indice.html"), "fichas": escritos}
