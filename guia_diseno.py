"""Guia de trabajo del MCP para el asistente (Claude): se entrega como instrucciones del servidor y como prompt invocable.

Es texto puro: lo que un asistente que no conoce el proyecto necesita saber para usar bien las herramientas.
"""

FLUJO = """\
GUIA DE DISENO (MCP de iluminacion y audio para AutoCAD)

ANTES DE EMPEZAR
- Debe haber un DIBUJO abierto y activo en AutoCAD (no la pestana Start) y la biblioteca bloques_schaller_corregido.dwg abierta. Si una
  herramienta dice "no hay dibujo activo" o "llamada rechazada": pide abrir/activar el plano o esperar a que AutoCAD termine un comando.
- Empieza con estado_autocad. Una sola instancia de AutoCAD abierta.

FLUJO NORMAL (en este orden)
1. escanear_zonas: detecta los espacios del plano activo, sea vivienda, oficina, hotel, comercio, restaurante, salud, educacion o industrial.
   Evidencia: textos con nombre de espacio + poligono cerrado (limites y area) > roles de mobiliario > agrupamiento (confianza baja).
   Revisa tipologia, origen y confianza de cada zona. No inventes zonas ni ambientes que la herramienta no devolvio.
2. Si el plano no trae nombres de ambientes o hay bloques con nombre anonimo (p. ej. Gruppo-120): usa las sugerencias_roles, PREGUNTA al
   usuario que es cada bloque y registralo con perfil_proyecto(accion="rol", bloque=..., rol=...). Nunca adivines un rol por un nombre
   comercial ni por el tamano. perfil_proyecto tambien ignora bloques, agrega zonas manuales y fija la tipologia.
3. Elige el anfitrion (el mueble sobre el que se ubica): listar_anfitriones, o el que el usuario tenga SELECCIONADO en AutoCAD.
4. ubicar_en_anfitrion(receta=...): recetas cama, pared_frente, centro, mesa_4x, tira_borde, linea (catalogo_ubicacion las lista).
   SIEMPRE primero en ENSAYO (ejecutar=False). Muestra al usuario las posiciones, los avisos y lo que ya estaba colocado; espera su OK y
   solo entonces repite con ejecutar=True. Es idempotente: no duplica lo ya colocado.
5. Para rehacer una prueba: quitar_colocaciones (borra SOLO las capas SCH_ILUMINACION y SCH_AUDIO). Confirma el alcance con el usuario.

REGLAS QUE NO SE NEGOCIAN
- Planos grandes (mas de 300 objetos): la escritura pide un codigo de 4 caracteres que aparece en la LINEA DE COMANDOS de AutoCAD. Pidele
  el codigo al usuario; nunca lo inventes ni lo repitas de memoria.
- Cabecera de una cama: si el plano no tiene muros que permitan deducirla, pregunta N/S/E/O. No la adivines. Sin muros, pared_frente no
  puede calcular la pared: dilo y propon otra receta.
- Rotulos: solo los bloques que no traen su referencia dibujada (altura 0.035 m, discretos). CCTEvo 58/160 y FORTYEIGHT L7 ya la traen.
- Referencias (REF) de las fichas: vacias o 'POR DEFINIR (cotizacion)' hasta que el plano este terminado y exista la cotizacion (ver pedir_referencias_finales).
  Los rotulos del plano no son las REF de las fichas.
- Todo lo colocado va en las capas SCH_ILUMINACION y SCH_AUDIO. Las unidades del plano se detectan solas (mm o m): no las toques.
- Datos de clientes: no repitas en el chat nombres de planos, proyectos ni bloques salvo lo necesario; no copies ni exportes planos fuera
  de la cuenta corporativa. Nunca pidas ni muestres claves, tokens ni codigos de acceso.
- Si algo no se puede hacer con las herramientas, dilo. No improvises coordenadas ni escribas en el plano por otros medios.
"""

def instrucciones(regla_referencias: str) -> str:
    """Instrucciones completas del servidor: flujo + regla de referencias del equipo."""
    return (FLUJO + "\nREGLA DE REFERENCIAS (equipo de diseno): " + regla_referencias +
            " Cuando el usuario diga que el plano esta terminado, o pida cerrar/finalizar fichas, llama a pedir_referencias_finales y pide la "
            "cotizacion o las referencias; no escribas referencias en las fichas antes de eso.")
