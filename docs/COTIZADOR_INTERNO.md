# Cotizador interno BARÓN

## Selección de aprobados y presentación comercial

Despiece muestra un listado buscable de todos los presupuestos aprobados y
permite seleccionar cuál consultar, sin crear nuevas reservas. Un pedido ya
aprobado muestra esa condición y no permite reconfirmar el mismo estado. Las
consultas son de solo lectura mientras hay reservas; para editar se vuelve a
Presupuesto. El borrador que está en edición también puede preparar su despiece.

El tilde «Mentirita» agrega 10 cm al ancho y alto solo en filas comerciales del
presupuesto cliente (vista, PDF, imagen y XLSX), con una nota explícita de margen
de referencia. No altera medidas ingresadas, precio por área, corte, despiece,
reservas ni consumo. La preferencia se guarda por presupuesto.

Al guardar aparece un diálogo 😊/😢. La feliz aplica el porcentaje de venta
configurado (inicialmente 10%); la triste conserva/restaura el precio normal.
Se recalculan precios unitarios, total y medios de pago desde los importes base:
repetir la feliz no acumula el incremento. El porcentaje se guarda con el pedido
y se informa como ajuste comercial incluido en la salida del cliente. Los
pedidos aprobados requieren volver a Presupuesto antes de cambiar su precio.

«Agregar grupo» está debajo del último grupo y lleva al inicio del nuevo grupo
al agregarlo, para facilitar la carga en celular.

Configuración se edita mediante formularios: precios y pagos, medidas y stock,
caños/sistemas, telas y colores, adicionales y datos del comercio. No se expone
un editor JSON. Los identificadores, fotos y metadatos existentes se preservan;
los precios especiales por color pueden dejarse vacíos para heredar la tela.

## Actualización: flujo de dos estados y stock de prueba

El despiece presenta una sola ficha por cortina con todos sus insumos editables,
subtotal por pieza y costo total por cortina. Agregar un insumo desde esa ficha
lo asigna a la cortina correspondiente. Los datos y exportaciones conservan
el detalle individual de cada material para cálculos, auditoría y reservas.

Por indicación del dueño, el único flujo de estados vigente es **Presupuesto ↔
Aprobado**. Aprobar reserva tela; volver a presupuesto libera la reserva. No hay
estado Fabricación/Instalado/Cancelado ni consumo físico automático.

Solo el servicio de prueba habilita `BARON_DEMO_STOCK=1`. Al arrancar se agregan
dos rollos de 50 m y tres retazos de distintas medidas por tela/color Roller,
marcados DEMO y STOCK FICTICIO. Se conservan pedidos y existencias anteriores,
y se guarda una copia privada del estado anterior en `before_demo_stock_v1`.
La carga queda registrada y no se repite ni repone material al reiniciar. Las
telas sin colores reciben colores explícitamente DEMO en esta base de prueba.
No habilitar esta variable en producción.

Los estados históricos ajenos a los dos nuevos se normalizan únicamente en
esta preparación de la base de prueba, conservando `legacy_status`, auditoría,
precios, consumos y reservas previos. Un pedido histórico consumido no devuelve
stock automáticamente ni se reabre para reutilizar material.

## Arquitectura revisada

Base revisada: `76b1ed907f9c5c4a579d785e67a174e39f9832a3` de main.
La aplicación Flask conserva `app.py`, los blueprints de fabricación y marketing,
las recetas, el catálogo JSON, imágenes y configuración existentes. `storage.py`
continúa usando GitHub Contents API para el catálogo anterior. Antes no existían
pedidos persistidos: el carrito vivía en el navegador y la salida era WhatsApp.

El nuevo blueprint `internal.py` vive en `/admin/interno`. `quoting.py` separa
herencia de grupos, cálculo, filas comerciales y movimientos de inventario.
`quote_exports.py` usa la misma copia guardada del pedido para PDF, PNG/JPG y
XLSX. La interfaz nueva usa JavaScript externo compatible con la CSP existente.

Los pedidos, clientes, stock, auditoría y preferencias **no se escriben en
GitHub ni localStorage**. `private_store.py` usa SQLAlchemy con PostgreSQL en
Render y SQLite para desarrollo. La tabla aditiva `baron_private_v1` mantiene
un documento privado; un bloqueo de fila PostgreSQL / BEGIN IMMEDIATE SQLite
serializa las transacciones. Es una decisión para el volumen de un equipo
pequeño: no es una arquitectura para miles de operaciones concurrentes.
Las revisiones del pedido rechazan ediciones desactualizadas con HTTP 409.

## Conservación y migración reversible

Esta rama no modifica `data/catalog.json`, imágenes, recetas ni `storage.py`.
La configuración interna se inicializa una sola vez con las telas anteriores
y tres entradas separadas provenientes del Excel BARÓN. No cambia sus precios
anteriores ni los vincula silenciosamente. Los nuevos rollos y retazos arrancan
vacíos: cargar existencias reales. Traslúcida no tiene colores confirmados en el
Excel: agregarlos explícitamente en Configuración antes de usarla.

Antes de habilitar la nueva versión:

1. Descargar `/admin/exportar` y respaldar las imágenes y el commit actual.
2. Crear una base PostgreSQL **privada** persistente para el entorno de revisión.
   Configurar `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD`. No usar la base
   productiva para pruebas. Render Free no conserva el SQLite local: la app
   rechaza operaciones internas si falta DATABASE_URL en Render.
3. Instalar `pip install -r requirements.txt`. El primer acceso autenticado al
   módulo crea la tabla nueva de forma aditiva; no hay UPDATE/DELETE de tablas
   previas. El catálogo remoto conserva sus variables GITHUB existentes.
4. Revisar precios/reglas, cargar stock real y probar aprobación/corte antes de
   dar acceso al personal. No hay importación automática de un carrito local.
5. Respaldar el estado privado antes de cualquier actualización posterior:
   `python manage_private.py backup /ruta/privada/baron-fecha.json`.
   También existe descarga autenticada, solo para dueño, desde Configuración.
6. Para rollback, detener escrituras, hacer otro backup y volver al commit
   anterior. Conservar la tabla nueva: el código anterior la ignora. Para
   restaurar un backup privado: `python manage_private.py restore ARCHIVO
   --confirm-replace`. No subir los respaldos a este repositorio público.

No se fusiona ni se despliega esta rama automáticamente. Render puede seguir
desplegando main: el PR es el punto de revisión. El `render.yaml` solo incorpora
variables nuevas, sin crear servicios ni cambiar la rama de producción.

## Acceso y rutas anteriores

El dueño usa ADMIN_PASSWORD. Cada empleado usa un nombre distinto y un hash
Werkzeug configurado mediante `STAFF_USERS_JSON`, por ejemplo:
`{"ana":{"password_hash":"<hash generado fuera del repositorio>"}}`.
Generar hashes con `werkzeug.security.generate_password_hash`; no guardar
contraseñas ni valores reales en GitHub. Las preferencias se guardan por ese
usuario. El dueño tiene la identidad fija `dueño`.

Personal puede cotizar, guardar pedidos, operar stock/despiece y exportar; solo
el dueño configura precios, accede al administrador anterior y descarga todo
el respaldo. Operaciones mutantes requieren CSRF, también los antiguos endpoints
JSON. Cookies HTTPOnly/SameSite y Secure en Render; respuestas admin no-store.

`/` dirige al acceso o al cotizador interno. Se mantienen las rutas antiguas
`/cotizar/*`, `/carrito` y `/api/*` para compatibilidad autenticada; dejan de ser
comerciales públicas. Se conserva `/health`, logos y medios. La eliminación de
una tela anterior ahora la desactiva, conservando el registro.

## Flujo y decisiones explícitas

- Un grupo conserva cantidad, medidas y opciones base. Personalización apagada
  no muestra atributos ni tarjetas. Encendida sin atributos tampoco muestra
  unidades. Solo los atributos marcados pueden sobrescribir la base, incluso
  si alguien envía otros campos mediante la API. La UI pide confirmación antes
  de borrar excepciones. Se agrupan filas comerciales idénticas; se separan por
  color/tela/precio, ambiente, opciones y medidas.
- Guardar un presupuesto no reserva ni consume. Aprobar exige disponibilidad
  y reserva en una sola transacción; si no alcanza se revierte todo. Cotizar
  muestra advertencias y permite guardar aunque falte stock. Fabricación es la
  confirmación de corte y consume las reservas una sola vez. Repetir el mismo
  estado no repite movimientos. Volver de aprobado a presupuesto o cancelar
  antes del corte libera reservas. Cancelar después del corte no devuelve tela.
  Un pedido consumido no se reabre para volver a descontar: se duplica.
- Los rollos usan consumo lineal conservador por cortina, sin optimización de
  anidado lateral. El ancho real del lote debe alcanzar el corte. No se reparte
  una cortina entre varios rollos. No se generan retazos supuestos: registrar
  los sobrantes reales con el pedido de origen y ubicación.
- Los retazos no giran; misma tela/color, ancho y largo suficientes. Se ordenan
  por desperdicio. Solo se asignan desde Despiece; elegir y guardar no reserva.
  Al aprobar quedan reservados y al cortar se consume el retazo completo como
  pieza disponible. Si quedó material aprovechable, registrarlo como un nuevo
  retazo real con origen en el anterior. El remanente no reaparece solo.
- El despiece admite reemplazo de insumos, agregado, eliminación y cambios de
  cantidades/costos, con copia anterior/posterior en auditoría. Conserva una
  línea física de tela por cortina para impedir eludir las reservas. Permite
  editar sus dimensiones de corte. El costo no cambia la venta guardada.
- Los precios/reglas aplicados se copian al pedido. Guardar solo datos del
  encabezado conserva esa copia aunque cambie el catálogo. Cambiar grupos o
  descuentos recalcula con reglas actuales; duplicar conserva precios y quita
  asignaciones de retazos. El despiece y las exportaciones usan el snapshot.
- Las exportaciones cliente solo admiten la lista blanca de columnas
  comerciales; medidas en cm de la cortina solicitada. PDF A4 con logo, banda
  azul, vigencia, totales por pago, marca de agua y pie de contacto configurado.
  Las tablas repiten encabezados y continúan en varias páginas. PNG/JPG se
  generan del mismo PDF; si hay varias páginas, se entrega un ZIP completo.
  XLSX real con valores numéricos y protección frente a fórmulas en textos.
  Despiece incluye Despiece/Cortinas/Resumen y Reservas cuando existan.

## Validación

`pip install -r requirements-dev.txt` y `python -m pytest -q`.
La suite cubre los cuatro diámetros y tres telas, herencia de tres unidades con
variante solo de color, precios históricos, revisiones, reservas/liberaciones,
consumo idempotente, falta de stock atómica, compatibilidad de retazos sin giro,
despiece independiente, permisos/CSRF, exportaciones y concurrencia SQLite.
GitHub Actions agrega PostgreSQL 16 y una prueba de bloqueo concurrente real.
La prueba PostgreSQL se omite localmente si falta `TEST_POSTGRES_URL`.

Revisar en navegador 390×844 y 1440×1000: grupo de tres sin tarjetas, activar
solo Color (tres selectores), cambiar color de unidad 2, dos filas cliente,
desmarcar con confirmación, despiece independiente y ausencia de desbordamiento.

## Pendientes de validación comercial

Ver `FUENTES_EXCEL.md`. Validar equivalencia 41/42, colores Traslúcida, ancho
real por tela/lote, mínimos, descuentos/impuestos/pagos, accesorios adicionales,
criterio de guías y numeración BAR-000001 antes de emitir presupuestos reales.
Ningún porcentaje de IVA o pago se toma del libro proveedor automáticamente.
La casilla de reglas revisadas informa validación comercial; no bloquea trabajo.
