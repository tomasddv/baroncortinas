# Actualización: usuarios, operaciones y presupuestos oficiales

## Arquitectura y compatibilidad

Se amplía Flask y el estado privado transaccional existente; no se reemplaza la
aplicación ni su catálogo. SQLAlchemy serializa la fila `baron_private_v1` con
`SELECT FOR UPDATE` en PostgreSQL y `BEGIN IMMEDIATE` en SQLite. Se conservan
fórmulas Excel de Roller, snapshots comerciales, numeración BAR, vencimientos,
reservas, retazos y todos los identificadores existentes. Openpyxl, ReportLab y
PyMuPDF siguen siendo las dependencias de exportación; no se agrega un servicio.

La rama `feature/baron-usuarios-permisos-presupuestos` parte de
`codex/cotizador-interno-baron` (PR #1). El nuevo PR apunta a esa rama para revisar
solo esta ampliación. Producción y el servicio de prueba actual no se modifican
por crear o publicar esta rama; no activar despliegue automático ni fusionar hasta
aprobar los cambios.

## Migración y respaldo

La primera transacción crea de forma aditiva `baron_state_backups` y copia en ella
el payload completo previo a migrar. La copia y el cambio de esquema previo a 3 se
confirman juntos. Se agregan `users` y `stock_history`, sin reescribir pedidos,
precios, lotes ni reservas. DDL protegido por advisory lock PostgreSQL para evitar
carreras entre workers. No hay borrados de tablas o columnas ni cargas de ejemplo.
Los estados existentes sin nuevas propiedades conservan su comportamiento.

Antes de un despliegue aprobado, descargar además el respaldo privado desde
Configuración y tomar un respaldo PostgreSQL por las herramientas de Render.
La tabla de respaldo es privada: no se publica por ninguna API del colaborador.
Las pruebas ejecutan migraciones exclusivamente sobre bases temporales/locales y
el PostgreSQL de CI, no sobre la base del servicio existente.

Para consultar los respaldos desde una conexión de administración:
`SELECT id, payload FROM baron_state_backups ORDER BY id DESC;`.
Restaurar solo durante mantenimiento, tras respaldar el estado actual: reemplazar
el payload de la fila 1 por la copia elegida dentro de una transacción. Restaurar
un respaldo revierte todos los cambios posteriores de datos; un rollback de código
no necesita restaurar datos, ya que la migración es aditiva.

## Primer dueño y variables

Se conserva `ADMIN_PASSWORD` como credencial de inicialización. Variable opcional
nueva: `ADMIN_USERNAME` (por defecto `LUCAS`). Abrir `/admin/login`, ingresar ese
usuario y la contraseña ya configurada. Si todavía no existe un dueño persistido,
se crea una cuenta con hash scrypt de Werkzeug. Por compatibilidad se admite
usuario vacío únicamente durante esa inicialización. Después, usar siempre el
usuario persistido. Cambiar `ADMIN_PASSWORD` posteriormente no reemplaza la
contraseña persistida: restablecer desde Usuarios y permisos con una sesión de
dueño habilitada. No se guardan contraseñas en texto plano ni en GitHub.

`STAFF_USERS_JSON` se importa una vez solo si contiene hashes existentes, con los
permisos operativos predeterminados. En adelante administrar cuentas desde el
panel. No cambiar `SECRET_KEY` ni `DATABASE_URL`: siguen siendo los existentes.
La autenticación requiere la base persistente; nunca usa el disco temporal de
Render como almacenamiento único. La versión de sesión se comprueba en cada
solicitud; cambiar permisos, contraseña o habilitación revoca sesiones anteriores,
incluida la propia si el dueño modifica su cuenta.

## Uso del dueño

- Usuarios y permisos: alta de colaboradores, contraseña inicial/restablecimiento,
  habilitación, revocación y once permisos independientes. No permite dar acceso
  económico a colaboradores. Auditorías paginadas con búsqueda por usuario,
  artículo, fecha, color y motivo.
- Artículo personalizado / Carga manual: renglón con detalle y precio obligatorios,
  cantidad entera, medidas/tela/color opcionales, duplicación y eliminación.
  Convive con Roller y otros modelos; no crea catálogo, receta ni movimientos.
- Organismo gubernamental: importe final explícito; se distribuye proporcionalmente
  en centavos sobre las unidades. Los subtotales suman exactamente ese importe.
  Se omiten medios de pago, descuento y caritas en ese presupuesto. Desmarcarlo
  vuelve a calcular con las reglas comerciales habituales.
- Observaciones comerciales multilínea: se guardan y exportan debajo de totales.
  Indicaciones para fabricación es un campo separado: únicamente este se comparte
  con colaboradores, para evitar filtrar importes escritos en observaciones.
- Tablero operativo: el dueño también puede acceder a él desde su navegación.

## Uso del colaborador

Acceso independiente en `/admin/operativo/`. Solo devuelve pedidos aprobados y los
campos técnicos de una lista positiva. Las APIs comerciales/legadas, configuración,
respaldos, catálogo, usuarios y exportaciones comerciales están bloqueadas en el
servidor. No se envían snapshots, costos, precios o márgenes ocultos.

Entradas y ajustes se aplican a artículos/telas/colores ya existentes. No admiten
negativos, códigos desconocidos ni existencias menores a reservas vigentes. El
historial guarda usuario, hora UTC, artículo/tela/color, antes, delta, después,
unidad, tipo y motivo. Los cambios operativos del despiece aprobado conservan el
precio comercial y reasignan reservas atómicamente; si falta stock se revierte
todo. Los estados de fabricación son independientes de la aprobación comercial:
pendiente, en fabricación, listo y entregado. Permiso de contacto solo habilita el
campo Contacto, no información comercial.

El Excel operativo se construye desde cero con campos técnicos en dos hojas
visibles, sin reutilizar hojas de costos ni metadatos económicos. Exige permisos de
pedidos, despiece y exportación. El buscador de retazos permanece en el despiece y
el módulo de retazos, nunca dentro del cotizador comercial.

## Plantilla oficial

Se buscaron los recursos del repositorio: el logo existente es una variante
cuadrada diferente. Se recuperaron de la imagen adjunta únicamente cabecera,
logo/marca superior y pie con marca inferior, conservando sus píxeles. Las regiones
con números, fechas, tabla y totales de ejemplo no forman parte del fondo.
`static/brand/presupuesto-oficial.png` contiene exclusivamente gráficos fijos.
No se empleó IA para redibujar la identidad. Fuente de referencia: imagen adjunta
por el dueño el 24/11/2026, 1086 × 1536 píxeles. No contiene datos reales de clientes.

El contenido dinámico usa Helvetica (equivalente disponible en PDF a la familia
sans de referencia), A4 vertical, tabla gris, márgenes, cabecera y pie repetidos.
No se dispone de fuente original ni de logos vectoriales. Para impresión con
nitidez original solicitar SVG/PDF/PNG originales de logos, fondo y fuente/licencia:
exportar JPG a 300 dpi no aumenta el detalle de los gráficos recuperados.

Vista previa muestra páginas rasterizadas del mismo PDF, con idéntica composición.
JPG/PNG se generan del mismo PDF a 300 dpi; multipágina se entrega en ZIP. Las
columnas seleccionadas se respetan en PDF/JPG/PNG/Excel. Filas y encabezados se
repiten por página y el margen inferior reserva pie y marca de agua. Observaciones
vacías no generan bloque; el texto largo continúa sin invadir el pie.

## Despliegue en Render después de aprobación

1. Revisar y aprobar PR #1 y esta ampliación; integrar en la rama elegida.
2. Mantener el mismo servicio y PostgreSQL. Respaldar antes del despliegue.
3. Conservar build `pip install -r requirements.txt`, arranque
   `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2` y salud `/health`.
4. Conservar `DATABASE_URL` privada, `SECRET_KEY` y `ADMIN_PASSWORD`. Opcionalmente
   definir `ADMIN_USERNAME` antes de crear el primer dueño. No abrir redes de DB.
5. Desplegar manualmente el commit aprobado. La migración toma respaldo atómico.
6. Verificar `/health`, ingreso de dueño, conteos de pedidos/lotes, creación de
   colaborador, permisos y exportaciones; confirmar datos tras un reinicio.
7. En datos reales, no activar `BARON_DEMO_STOCK`. No se elimina stock ficticio
   existente automáticamente, para no afectar pruebas ni reservas anteriores.

## Verificación

`python -m pytest -q`, `node --check` en scripts y dos pruebas Playwright:
`tests/browser_smoke.py` y `tests/browser_upgrade.py`. Localmente usar
`BROWSER_CHANNEL=chrome`; CI instala Chromium. GitHub Actions agrega PostgreSQL 16.
La prueba PostgreSQL se omite localmente si no existe `TEST_POSTGRES_URL`.

Cobertura: fórmulas existentes, permisos positivos/negativos, URLs directas,
contraseñas, revocación, filtrado de importes y contactos, Excel operativo seguro,
auditoría, stock inválido, reserva atómica, artículos mixtos, total gubernamental,
condiciones particulares, observaciones, exportaciones, geometría multipágina,
respaldo antes de migración, persistencia y móvil/escritorio.


## Archivos de esta ampliación

- Autenticación, autorización y operaciones: `app.py`, `access.py`, `operational.py`,
  `internal.py`, `private_store.py`, `stock_audit.py`.
- Cálculos, presupuestos y exportaciones: `quoting.py`, `quote_exports.py`.
- Interfaces: `templates/login.html`, `templates/internal.html`,
  `templates/operational.html`, `static/internal.js`, `static/internal.css`,
  `static/users.js`, `static/operational.js`, `static/official-preview.css`.
- Gráficos: `static/brand/presupuesto-oficial.png`.
- Verificación: `tests/test_internal.py`, `tests/test_upgrade.py`,
  `tests/browser_smoke.py`, `tests/browser_upgrade.py`, `.github/workflows/tests.yml`.
- Documentación: este archivo.

Resultado local: 50 pruebas aprobadas y una prueba PostgreSQL omitida por falta de
servicio local; dos recorridos Chrome de interfaz aprobados. La CI ejecuta también
PostgreSQL 16 y ambos recorridos Chromium. No hay variables nuevas obligatorias ni
cambios de dependencias. Si `dueno` ya existe como colaborador heredado, elegir
otro `ADMIN_USERNAME` para inicializar al dueño sin sobrescribir esa cuenta.


## Ajuste operativo: selección y realización por cortina

El dueño heredado `dueno` se renombra a `LUCAS`, conservando ID, hash de contraseña,
permisos y datos. Se revocan las sesiones del nombre anterior. La migración de
esquema 2 a 3 vuelve a respaldar el payload antes de cambios. No se sobrescribe una
cuenta LUCAS existente si hay conflicto; debe resolverse conservando ambas cuentas.

Las solapas del tablero operativo son paneles independientes, no anclas a una
página larga. Pedidos y Despiece tienen desplegables de presupuesto aprobado y
cortina, compartiendo la selección. Inicialmente no se selecciona ningún pedido;
solo se muestra una cortina y su despiece. Excel desde ese panel exporta únicamente
la cortina elegida; la URL sin selector mantiene la exportación completa.

Realizada guarda usuario, fecha y una revisión individual por cortina. Repetir la
marca no genera movimientos ni duplica reservas. Desmarcar exige confirmación.
Una cortina realizada no admite cambios técnicos ni en el panel operativo ni en el
editor del dueño, hasta reabrirla. Las modificaciones comerciales no la borran y
una duplicación comienza sin marcas de realización. Al terminar todas, el pedido
pasa a listo; no se puede marcar listo/entregado si falta una cortina.

`tests/browser_operational.py` prueba dos pedidos, un borrador oculto, selección de
una sola cortina, persistencia de Realizada, cancelación de reapertura, Excel
individual y ausencia de otras solapas al hacer scroll, en móvil y escritorio.

La dirección principal redirige al tablero correspondiente al rol. Una sesión
revocada o un formulario de ingreso vencido vuelve al acceso con un token nuevo,
sin ejecutar ni reenviar la solicitud anterior. Las APIs comerciales siguen
bloqueadas para colaboradores.

## Eliminar y recuperar presupuestos

En Historial, Eliminar requiere confirmación y mueve el presupuesto a Papelera. Solo LUCAS/propietario puede hacerlo. La eliminación conserva número, precios, despiece, auditoría y marcas de cortinas realizadas; no borra registros ni descuenta stock físico. Si estaba aprobado, libera reservas en la misma transacción. Un presupuesto con consumo histórico no permite esta operación. Los eliminados no aparecen en fabricación ni permiten exportar por URL directa.

Activar Papelera y pulsar Restaurar recupera el mismo número como Presupuesto. Para reservar materiales debe aprobarse nuevamente. Las revisiones evitan eliminar una versión modificada por otro usuario.

## Despiece operativo de consulta

El tablero operativo muestra piezas, cantidades físicas y medidas técnicas de corte como texto. No permite editar ni guardar el despiece, incluso con permisos antiguos; POST operativo de despiece responde 403 sin modificar reservas ni precios. Se retiró el permiso de edición del formulario de usuarios. Las correcciones se realizan desde el cotizador del propietario.

Buscar retazos compatibles muestra una lista vertical por tela de la cortina seleccionada, con código, ancho, largo disponible y ubicación. Repetir la búsqueda reemplaza el resultado anterior. Es una consulta: no asigna ni consume el retazo.
