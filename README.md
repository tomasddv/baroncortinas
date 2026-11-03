# BARÓN — Cotizador de cortinas a medida

Aplicación web responsive (computadora + celular) con catálogo editable, motor de cotización, carrito de presupuesto y panel administrativo.

**Estado:** MVP funcional preparado para subir a un repositorio de GitHub y desplegar en Render. No hay pagos online ni venta confirmada automáticamente: el pedido se envía por WhatsApp para su verificación comercial. No se ha desplegado una instancia pública en este paquete.

## Características

### Tienda pública
- Landing de BARÓN con identidad visual editable.
- Catálogo de Roller Blackout, Roller Sun Screen, Roller Doble (dos telas), y cortinas tradicionales de tela.
- Selector de línea/material y de colores; fotografía del material (si se cargó).
- Ancho y alto, colocación en pared o techo, caída del rollo, lado del mando, tipo de cadena, confección y cantidad según el producto.
- Recálculo del precio desde **el servidor** al cambiar opciones.
- Carrito en el navegador y confirmación de cotizaciones firmadas por el servidor al generar un pedido hacia WhatsApp.
- Diseño adaptable a pantallas de teléfono y PC.

### Panel privado
- Acceso con contraseña mediante variable de entorno `ADMIN_PASSWORD`.
- Subir **logo oficial de BARÓN**, cambiar nombre, eslogan y paleta cromática (principal / acento / fondo).
- Crear, editar, pausar y borrar materiales. Cada material incluye: nombre, familia, descripción, precio de compra, unidad (m² / metro lineal), ancho del rollo, merma específica, foto y lista de colores con muestras HEX.
- Ajustar costes de mecanismos, cadenas, recargo comercial y mínimos facturables.
- Definir **merma porcentual global**, **merma porcentual particular por material**, **extra de ancho de corte en cm**, **extra de alto en cm** y diferencia soporte/tela roller.
- Descargar copia del catálogo como JSON.

## Cómo instalar localmente

Requiere Python 3.11+.

### Windows (PowerShell)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = 'pon-aqui-una-clave-aleatoria-larga'
$env:ADMIN_PASSWORD = 'una-contrasena-segura'
python app.py
```

Abrí `http://127.0.0.1:5000`. El panel está en `http://127.0.0.1:5000/admin`.

En local, si no se proporcionan variables de GitHub, los materiales se guardan en `data/catalog.json` y las fotos en `static/uploads/`.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY='pon-aqui-una-clave-aleatoria-larga'
export ADMIN_PASSWORD='una-contrasena-segura'
python app.py
```

## Subirlo a GitHub

1. Crear un repositorio nuevo **privado**, por ejemplo `baron-cotizador`.
2. Subir **el contenido descomprimido** de esta carpeta a la raíz del repositorio (debe quedar `app.py` en la raíz).
3. Es importante que exista inicialmente `data/catalog.json` en la rama `main`.
4. Crear un **Fine-grained personal access token** desde GitHub > Settings > Developer settings > Personal access tokens. Limitar el token **solo** a ese repositorio y permiso `Contents: Read and write`. No pegar el token en código, issues ni archivos.
5. Guardar el token como variable secreta `GITHUB_TOKEN` en Render (ver apartado siguiente).

GitHub actúa como almacenamiento de **catálogo e imágenes**, no como base de datos de pedidos o clientes. Evitar guardar teléfonos, nombres de compradores o datos personales en commits.

## Desplegar en Render

1. En Render elegir **New > Blueprint** y conectar el repo GitHub de BARÓN (usa el archivo `render.yaml`). Como alternativa, crear un servicio web Python con `pip install -r requirements.txt` y `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`.
2. Configurar estas variables privadas de entorno:

| Variable | Ejemplo | Notas |
|---|---|---|
| `SECRET_KEY` | generada automáticamente | Debe ser secreta y estable entre reinicios. El Blueprint genera una. |
| `ADMIN_PASSWORD` | contraseña segura | Obligatoria para entrar al panel. |
| `GITHUB_REPO` | `usuario/baron-cotizador` | Identificador **exacto** del repo que creaste. |
| `GITHUB_BRANCH` | `main` | Rama donde se guardan catálogo y fotos. |
| `GITHUB_TOKEN` | token de GitHub | Guardado **solo** como secreto en Render. |
| `PYTHON_VERSION` | `3.13.5` | Ya configurada en el Blueprint. |

3. Cuando Render indique `Live`, visitar la URL asignada y entrar a `/admin`.
4. Abrir **Identidad de marca** en `/admin`, subir el archivo oficial del logo BARÓN y, si hace falta, ajustar los colores con los selectores.
5. Configurar **WhatsApp** en formato internacional: Argentina 54 + 9 + código de área + número celular (sin `+`, guiones ni `0` inicial). Probar con un chat propio.
6. Sustituir los **precios ficticios de demostración** de `data/catalog.json` por costos reales de la empresa, así como mecanismos, márgenes, desperdicio y medidas máximas.
7. Realizar una cotización de prueba y verificar el pedido que se abre en WhatsApp.

**Persistencia:** Render tiene disco efímero por defecto. Por eso el código usa la API de contenidos de GitHub para escribir `data/catalog.json` y `static/uploads/*`. Cada cambio de material y marca crea un commit en el mismo repo. La configuración `buildFilter.ignoredPaths` evita que esos commits de datos disparen un redeploy en Render; la aplicación lee los archivos actualizados directamente de GitHub. **No guardes pedidos de clientes en GitHub**.

**Precaución:** en Render gratuito puede haber suspensión por inactividad; el primer acceso puede demorar. Para una tienda con publicidad activa, evaluar un plan pago.

## Fórmula de cotización

El precio del material se define **como costo de compra** por m² o metro lineal de rollo.

1. Para roller: ancho de corte = ancho del soporte − diferencia de tela roller + extra de ancho; alto de corte = alto pedido + extra de alto.
2. Para cortinas de tela: ancho de corte = ancho pedido × factor de confección + extra de ancho; alto de corte = alto + extra de alto.
3. Merma aplicada al consumo = `% global` + `% particular de la tela`.
4. Si el costo es por m²: m² facturables = máx(m² mínimos, área de corte × (1 + merma/100)).
5. Si el costo es por metro lineal: metros facturables = máx(0,5, alto de corte en metros × número de paños × (1 + merma/100)).
6. Se suman mecanismo, cadena si corresponde, y un porcentaje de recargo sobre costo. El importe se multiplica por la cantidad.

**Importante:** el motor calcula una **estimación de materiales**, no una optimización industrial de corte de múltiples pedidos. La distribución exacta de piezas en el rollo, uniones, sobrantes reutilizables, stock físico, costos de instalación, flete e impuestos deben validarse antes de vender. No se garantizan valores reales hasta cargar precios y reglas reales del negocio.

## Limitaciones de esta primera versión

- Checkout por **solicitud de presupuesto en WhatsApp**; no hay Mercado Pago, tarjetas, facturación ni sistema de pedidos de backoffice.
- El carrito se guarda en el navegador del cliente; el sitio no almacena pedidos.
- El logo oficial debe cargarse desde el administrador como imagen PNG, JPG o WEBP (hasta 1,5 MB). Hay una marca tipográfica BARÓN como alternativa inicial.
- Los archivos `data/catalog.json` y las fotos viven en GitHub. Los cambios no son transaccionales a nivel de múltiples archivos; si un paso falla, puede quedar una foto sin usar.
- El alta simultánea de múltiples administradores podría producir conflictos de escritura en GitHub; esta versión se diseñó para un administrador a la vez.
- Los precios de ejemplo son ficticios; nunca deben utilizarse para facturación real sin validación.

## Estructura de archivos

```text
app.py                  # servidor Flask y cotización
storage.py              # integración de GitHub Contents API
render.yaml             # configuración de Render + filtros de despliegue
requirements.txt        # dependencias
static/style.css        # diseño responsive BARÓN
static/app.js           # configurador y carrito
static/uploads/         # fotos locales; en producción se leen desde GitHub
templates/              # tienda, catálogo, cotizador y panel
data/catalog.json       # catálogo inicial editable desde panel
```

## Seguridad

- Los secretos se mantienen fuera del repositorio.
- Los cambios del panel requieren sesión de administrador y token CSRF.
- Tipos y tamaños de fotos validados; contenido HTML escapado por plantillas.
- La cotización se calcula en el servidor y cada precio se firma; al armar un pedido se verifican las firmas y se recalculan los valores con el catálogo actual.
- Es recomendable activar MFA en GitHub y rotar los tokens si se exponen.
- Para producción con varias personas, agregar un proveedor de autenticación, monitoreo, backups y auditoría de cambios.

## Nuevo: fotos por color y despiece de fabricación

En `/admin` aparecen tres accesos adicionales:

1. **Insumos y precios** (`/admin/componentes`): cargar nombre, unidad de compra (unidad, metro o m²), costo de compra y estado activo.
2. **Recetas por modelo** (`/admin/recetas`): seleccionar los insumos de cada tipo de cortina, la regla de consumo, un factor y la merma particular de cada componente. Hay recetas independientes para Blackout, Sun Screen, Doble y cortina de tela.
3. **Simulador** (`/admin/simulador`): revisar el despiece para un ancho y alto determinados, el subtotal de telas, componentes y el precio orientativo final. La vista toma el primer material activo de cada familia, solo como referencia de control.

En **Editar material** (`/admin/material/<id>`) aparece una sección **Fotografías por color**. Después de guardar el nombre y HEX de un color, se puede subir su foto JPG/PNG/WEBP (máximo 1,5 MB), borrar la anterior o definir un costo particular de esa variante. El cliente verá la foto de la variante elegida en el configurador; si no existe, se utiliza la foto general del material. Al editar la lista de colores se conservan las fotos y costos de colores cuyos nombres/IDs no cambiaron.

### Reglas de consumo

- `fijo`: cantidad fija de unidades por cortina, multiplicada por el factor.
- `ancho_m`: ancho solicitado en metros × factor.
- `alto_m`: alto solicitado en metros × factor.
- `perimetro_m`: dos veces la suma de ancho y alto, en metros × factor.
- `area_m2`: superficie solicitada en m² × factor.
- `cada_50cm_ancho` y `cada_100cm_ancho`: cantidad de tramos de ancho redondeada hacia arriba × factor.
- La merma específica del insumo incrementa la cantidad. Para insumos comprados por `unidad`, la cantidad resultante se redondea hacia arriba.

**Compatibilidad:** hasta configurar una receta no vacía, el cotizador conserva el costo fijo de mecanismos anterior de ese modelo. Una receta activa **reemplaza** ese costo fijo para evitar sumarlo dos veces. El adicional por cadena de la configuración anterior continúa aplicándose por separado en cortinas roller, por lo que no debe duplicarse en la receta. El costo de la tela ya se calcula desde el material y no debe cargarse nuevamente como componente. El recargo comercial se aplica al total de telas más componentes.

**Persistencia en Render:** las fotos, precios y recetas necesitan `GITHUB_REPO` y `GITHUB_TOKEN` (Contents: read/write) configurados como variables de entorno del servicio; `SECRET_KEY` por sí sola solo permite iniciar la aplicación. Las claves nunca se cargan en el repositorio.
