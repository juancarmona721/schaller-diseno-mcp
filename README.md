# Schaller MCP Diseno

Servidor MCP **interno** (uso exclusivo del equipo, no publicar fuera de la organizacion) para ubicar productos en
planos de AutoCAD y armar fichas. Independiente del servidor `autocad-mcp`.

## Instalacion para cualquier persona del equipo
Requisitos: Windows, AutoCAD completo (no LT) y Claude Desktop. Python 3.11+ (el instalador intenta instalarlo con winget).

1. Obtener la carpeta del proyecto (por el canal interno aprobado) y hacer **doble clic en `instalar_equipo.bat`**
   (o `powershell -ExecutionPolicy Bypass -File instalar.ps1`).
2. **Cerrar Claude Desktop por completo** (icono de la bandeja > Quit) y abrirlo de nuevo.
3. En **Settings > Developer** aparece `schaller-diseno` con su interruptor; en el chat, el icono de herramientas.
4. Abrir AutoCAD con `bloques_schaller.dwg` y el plano de trabajo.

El instalador crea `%USERPROFILE%\.schaller-diseno`, su entorno virtual, verifica que el servidor arranca y agrega el MCP a
`claude_desktop_config.json` **sin tocar tus otros servidores** (hace copia `.bak`; detecta tambien Claude Desktop de la
Microsoft Store). Volver a ejecutarlo actualiza la instalacion. Variables opcionales: `SCHALLER_DIR`, `SCHALLER_REPO`,
`SCHALLER_CLAUDE_CONFIG`.

Desarrollo: `python -m venv .venv`, `.venv\Scripts\python.exe -m pip install -r requirements.txt`, `pytest`.
Estructura: `server.py` y `acad.py` (servidor y puente COM), `sondas/` (scripts COM que ejecuta `acad.py`, se versionan),
`scratch_agente/` (pruebas de un solo uso, no se versionan). Ver `HISTORIAL_CAMBIOS.txt`.

## Ubicacion por anfitrion (recomendada)
Flujo: `listar_anfitriones` (o seleccionar el mueble en AutoCAD) -> `ubicar_en_anfitrion(receta, ...)` en **ensayo** -> revisar
posiciones y avisos -> repetir con `ejecutar=True`. Calcula desde la geometria real del mueble y, si hay muros, con rayos al
primer muro. Es idempotente, rotula solo lo que no trae su referencia, calibra la escala midiendo el bloque y se detiene si
el plano no trae muros en vez de adivinar. Recetas: `cama`, `pared_frente`, `centro`, `mesa_4x`, `tira_borde`, `linea`
(`catalogo_ubicacion` las lista). Requiere `bloques_schaller.dwg` abierto para importar los bloques que falten.

## Herramientas
| Herramienta | Fase | Que hace |
|---|---|---|
| `ping()` | 0 | Devuelve "ok" |
| `estado_autocad()` | 0 | Version, dibujo abierto, unidades, si es version completa con COM |
| `listar_productos(sistema=None)` | 1 | Referencia, nombre corto, marca y sistema (filtro sin tildes ni mayusculas) |
| `ver_producto(referencia)` | 1 | Todos los campos; avisa "DATOS DE PRUEBA: <campos>" si hay campos inventados; si la referencia se repite devuelve todas las filas |
| `buscar_producto(texto)` | 1 | Busca en referencia, nombre corto y nombre en Odoo |
| `validar_hoja()` | 1 | Referencias repetidas / "SIN REFERENCIA", campos vacios y campos inventados, por producto |

| `bloques_en_dibujo(limite_objetos=5000)` | 2 | Bloques insertados en el modelo del dibujo abierto: nombre, cantidad y capas (solo lectura) |
| `ubicar_producto(referencia, fila_excel=None)` | 2 | Busca en el dibujo los bloques de un producto (columna "Bloque en CAD") y devuelve X, Y, rotacion y capa de cada copia (solo lectura) |

| `crear_bloque_producto(referencia, tamano=100, ejecutar=False)` | 3 | **MODIFICA el dibujo (solo agrega).** Crea la definicion de bloque PROVISIONAL (circulo + nombre) con el nombre de la columna "Bloque en CAD" |
| `insertar_producto(referencia, puntos, rotacion_grados=0, ejecutar=False)` | 3 | **MODIFICA el dibujo (solo agrega).** Inserta copias del bloque en los puntos `[[x, y], ...]`, en la capa `DL-TEST-<SISTEMA>` |

| `insertar_productos(items, ejecutar=False)` | 3 | **MODIFICA el dibujo (solo agrega).** Inserta VARIOS productos de una vez: `items = [{referencia, x, y, rotacion_grados?, fila_excel?}]`. Todo o nada: si un item es invalido o falta un bloque, no inserta nada y lista cada problema |
| `importar_simbolos(origen_contiene, destino_contiene=None, referencias=None, ejecutar=False)` | 3 | **MODIFICA el dibujo destino (solo agrega).** Copia los SIMBOLOS reales (definiciones de bloque) de un plano abierto (solo lectura) al destino. Escala cada copia a las unidades del destino segun la escala tipica de insercion en el origen. Centra cada copia en su punto base (el punto de insercion queda en el centro del simbolo; algunos bloques del plano tienen el punto base a kilometros de su dibujo). No pisa bloques existentes; usar un dibujo destino NUEVO |
| `zoom_extents()` | 3 | Acerca la vista a todo el contenido (Zoom Extents). Solo mueve la vista; no cambia objetos |
| `ver_ficha(referencia, fila_excel=None)` | 4 | Contenido de la ficha de UN producto por secciones (identificacion, datos tecnicos, especificaciones adicionales, accesorios, CAD, fuente). Lo inventado va marcado `inventado=true` |
| `generar_fichas(referencias=None, filas_excel=None)` | 4 | Escribe las fichas en HTML (una pagina por producto + `indice.html`) SOLO en `[fichas].carpeta`. Sin argumentos genera todas. No modifica AutoCAD ni la hoja |

| `exportar_simbolos(destino_contiene=None, referencias=None, filas_excel=None)` | 4 | Lee (solo lectura) las definiciones de bloque de un dibujo abierto y las guarda como imagen SVG en `[fichas].carpeta\simbolos`. Dibuja lineas, polilineas, circulos, arcos y bloques anidados (3 niveles); rellenos, textos y solidos se cuentan como omitidos |
| `generar_tarjetas(sistemas=None, referencias=None, filas_excel=None)` | 4 | Tarjetas en el formato de la referencia (INSTALACION, simbolo, REF (marca), DESCRIPTION, CANTIDAD, TIPO DE CONEXION) + leyenda de convenciones. Sin filtro: `tarjetas.html`; con filtro: `tarjetas_<filtro>.html` |

| `crear_tarjetas_cad(destino_contiene=None, sistemas=None, columnas=8, x0, y0, ancho_tarjeta=1800, incluir_leyenda=True, incluir_sin_simbolo=False, ejecutar=False)` | 4 | **MODIFICA el dibujo (solo agrega).** Dibuja en AutoCAD las tarjetas del formato de referencia (marco, textos con color, simbolo real escalado) + leyenda. Solo para productos cuyo simbolo YA esta en el dibujo. Ensayo por defecto; se niega en dibujos grandes o si superaria el maximo de objetos. Capas `DL-TEST-FICHAS*` |

### Tarjetas (formato de referenciafichas.jpg)
- En AutoCAD: valores en azul, lo inventado en naranja inclinado, vacio en gris. Cada tarjeta = 1 marco + 5 divisiones + 5 textos + 1 simbolo (~12 objetos), por eso el tope de 300 objetos limita a ~20 tarjetas por dibujo.
- CANTIDAD = copias del bloque en el plano de diseno (extraccion, `[fichas].extraccion`); `*` si varios productos comparten el bloque; "sin dato" si el producto no tiene bloque.
- El simbolo sale de `exportar_simbolos` (primero importar los simbolos al dibujo con `importar_simbolos`). Sin imagen: "sin simbolo".
- Lo inventado va en naranja cursiva.

### Fichas (Fase 4)
- Lo INVENTADO (PRUEBA) sale en naranja cursiva, igual que la hoja, y cada ficha lleva un aviso de PRUEBA con la cuenta de campos inventados.
- Nunca se inventan referencias ni nombres de bloque: si falta, se escribe "sin dato".
- Los drivers y accesorios salen de la hoja "Drivers y accesorios" (columna "Aparece junto a"), enlazados por nombre.
- Las especificaciones adicionales (dimensiones, acabado, IP, etc.) son inventadas y estables: el mismo producto da siempre los mismos valores.
- El diseno de la ficha es una propuesta; el formato definitivo (el de Nicole) esta por confirmar.

### Seguridad de las herramientas que escriben (Fase 3)
- Por defecto hacen un **ensayo** (dicen que harian); solo dibujan con `ejecutar=True`.
- Solo **agregan**: nunca borran ni cambian objetos existentes, no guardan ni cierran el dibujo, sin AutoLISP.
- **No pisan**: si el bloque ya existe, no se toca.
- Se **niegan a escribir** si el dibujo tiene mas de `[escritura].max_objetos_dibujo` (300) objetos: protege los planos reales.
- Todo va en capas `DL-TEST-...`. Se apagan con `[escritura].habilitada = false`.
- El insertar de ensayo exige que el bloque ya exista (si no, dice `bloque_no_existe`).
- Deshacer: `Ctrl+Z` en AutoCAD, o cerrar el dibujo de prueba sin guardar.

Limites de tiempo (`config.toml`, `[autocad]`): `timeout_s = 10` (AutoCAD responde) y `timeout_lectura_s = 60`
(recorrer bloques). Si se pasan, devuelven un error claro. Usar solo con dibujos de prueba, no con planos de clientes.

La hoja se configura en `config.toml` (`[productos].ruta_hoja` y `hoja`). Se lee siempre en vivo, asi que
si cambias el Excel no hay que reiniciar. `N/A` es un valor valido, no un vacio.

## Probar
```
.venv\Scripts\python.exe -m pytest              # pruebas sin AutoCAD
.venv\Scripts\python.exe -m pytest -m autocad   # con AutoCAD abierto
```

## Notas de diseno
- Las llamadas a AutoCAD corren en un proceso aparte con limite de tiempo (`[autocad].timeout_s`, 10 s):
  si AutoCAD no responde, se devuelve un error claro y el servidor no se bloquea.
- Nunca se inicia AutoCAD; solo se conecta a uno ya abierto.
- Sin AutoLISP. No usar planos ni datos reales de clientes en pruebas.
