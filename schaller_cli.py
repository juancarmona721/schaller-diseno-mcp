"""Comandos de terminal para las acciones del MCP que conviene lanzar a mano (sin pasar por Claude).

Uso (desde la carpeta de instalacion, con su Python):
    .venv\\Scripts\\python.exe schaller_cli.py estado
    .venv\\Scripts\\python.exe schaller_cli.py quitar                          # ENSAYO: cuenta lo que se borraria
    .venv\\Scripts\\python.exe schaller_cli.py quitar --ejecutar --codigo ABCD  # borra (el codigo sale en la linea de comandos de AutoCAD)

`quitar` solo borra las capas SCH_ILUMINACION y SCH_AUDIO (lo que coloco el MCP). Ctrl+Z en AutoCAD lo deshace.
"""
import argparse
import json
import sys


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="schaller_cli", description="Comandos de terminal del MCP de Diseno Schaller.")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("estado", help="Muestra el dibujo activo de AutoCAD.")
    sub.add_parser("diagnostico", help="Comprueba que AutoCAD responde y que bloques_schaller_corregido.dwg esta abierto, con consejos.")
    sub.add_parser("autoprueba", help="Comprueba la instalacion (nivel 1): Python, dependencias, rutas, configuracion. No abre ni toca ningun dibujo.")
    q = sub.add_parser("quitar", help="Borra lo colocado por el MCP (capas SCH_ILUMINACION y SCH_AUDIO). Sin --ejecutar solo cuenta.")
    q.add_argument("--ejecutar", action="store_true", help="Borra de verdad (sin esto es un ensayo).")
    q.add_argument("--codigo", default=None, help="Codigo de 4 caracteres que AutoCAD muestra en su linea de comandos (planos grandes).")
    return p


def ejecutar(args) -> dict:
    import server                      # se importa aqui: cargar el servidor tarda un instante y --help no lo necesita
    if args.comando == "estado":
        return server.acad.estado(timeout_s=10)
    if args.comando == "diagnostico":
        return server.acad.diseno({"op": "diagnostico"}, timeout_s=10, timeout_op_s=30)
    return server.quitar_colocaciones(ejecutar=args.ejecutar, confirmacion=args.codigo)


def informe_diagnostico(res: dict) -> list[str]:
    """Lineas legibles para una persona (no JSON): que esta bien y que falta."""
    if not res.get("ok"):
        if res.get("error") in ("autocad_no_abierto", "sin_dibujo") or "AutoCAD" in str(res.get("detalle", "")):
            return ["[ ] AutoCAD no esta abierto (o no tiene ningun dibujo). Abre AutoCAD completo con un dibujo y repite este comando."]
        return [f"[X] No pude hablar con AutoCAD: {res.get('detalle') or res.get('error')}"]
    lineas = ["[OK] AutoCAD responde. Dibujo activo: " + res["dibujo_activo"]]
    if res.get("biblioteca_corregida_abierta"):
        lineas.append("[OK] bloques_schaller_corregido.dwg esta abierto: todo listo para usar Claude.")
    elif res.get("biblioteca_abierta"):
        lineas.append("[ ] Tienes abierta la biblioteca ANTIGUA. Desde ahora se usa bloques_schaller_corregido.dwg: abrela (y cierra la antigua) y repite.")
    else:
        lineas.append("[ ] Falta abrir bloques_schaller_corregido.dwg en esta sesion de AutoCAD (de ahi se copian los bloques). Abrela y repite.")
    return lineas


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    if args.comando == "autoprueba":
        import autoprueba
        import server
        res = autoprueba.ejecutar(server.AQUI, server.CARPETA_PERFILES)
        print("\n".join(autoprueba.informe(res)))
        return 0 if res["ok"] else 1
    if args.comando == "diagnostico":
        res = ejecutar(args)
        print("\n".join(informe_diagnostico(res)))
        return 0 if res.get("ok") and res.get("biblioteca_corregida_abierta") else 1
    if args.comando == "quitar" and args.codigo and not args.ejecutar:
        print("Aviso: --codigo solo se usa con --ejecutar; esto es un ensayo.", file=sys.stderr)
    res = ejecutar(args)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res.get("error") == "dibujo_grande_requiere_confirmacion":
        print("\nEl plano es grande: lee el codigo de 4 caracteres en la linea de comandos de AutoCAD y repite con --ejecutar --codigo XXXX",
              file=sys.stderr)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
