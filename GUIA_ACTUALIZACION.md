# BARÓN · Actualización: portadas reales y precios por opciones

## Qué incorpora

- **Administración → Fotos y videos de la colección** (`/admin/portadas`): fotografía JPG/PNG/WEBP por modelo (hasta 1,5 MB), video MP4 corto por modelo (hasta 8 MB), o URL HTTPS directa a MP4 alojado externamente. Permite volver a la ilustración original. Los videos se reproducen en silencio, en bucle y en línea en el celular.
- **Administración → Insumos y precios** (`/admin/componentes`): catálogo de insumos y costos individuales (función existente).
- **Administración → Recetas por modelo** (`/admin/recetas`): UNA receta base por modelo (función existente).
- **Administración → Costos por opción elegida** (`/admin/opciones`): nuevas reglas que agregan insumos según instalación (pared/techo), caída (delante/detrás), mando (izquierda/derecha), cadena (plástica/con contrapeso/metálica) y, en cortina tradicional, tipo de confección.
- **Administración → Simulador** (`/admin/simulador`): probar ancho, alto y cada opción; ver los insumos y el precio recalculado.

## Instalar en GitHub y Render

1. Antes de instalar, entrá a `/admin/exportar` y guardá una copia del catálogo actual.
2. Descomprimí el ZIP. **Subí los archivos sueltos y las carpetas a la raíz del repositorio `tomasddv/baroncortinas`**, conservando las rutas `templates/` y `static/`. No subas el ZIP sin descomprimir como un único archivo.
3. Reemplazá los archivos existentes que figuran en el ZIP y agregá los nuevos `marketing.py`, `templates/portadas.html` y `templates/option_rules.html`.
4. Confirmá los cambios en la rama `main`. Render hará el deploy automático. Comprobá que el estado sea `Live`.
5. **No reemplaces `data/catalog.json`**: este paquete NO incluye ese archivo, para conservar los materiales, colores, precios y configuración actuales.
6. No reemplaces `templates/base.html`: se conserva la navegación sin el botón Administrar. El panel seguirá disponible escribiendo `/admin` en la URL.
7. En `/admin`, verificá que el almacenamiento indique GitHub antes de cargar fotos o cambiar precios. Requiere `GITHUB_REPO` y `GITHUB_TOKEN` en Render.

## Cómo calcular los costos sin multiplicar las recetas

**Precio de venta = (costo de tela + insumos de receta base + insumos activados por las opciones) × (1 + recargo de venta / 100)**.

Ejemplo de estructura para Roller Blackout (los importes se cargan en Insumos y precios):

- **Receta base**: tubo (metros según ancho), mecanismo estándar, contrapeso de tela, terminales comunes. No incluir soportes ni cadena si se configurarán como condicionales.
- **Pared**: 2 soportes de pared, regla «Cantidad fija», factor 2.
- **Techo**: 2 soportes de techo, regla «Cantidad fija», factor 2.
- **Cadena plástica**: 1 cadena plástica (si tiene costo propio).
- **Cadena plástica con contrapeso**: 1 cadena plástica + 1 contrapeso.
- **Cadena metálica**: 1 cadena metálica.
- **Caída delante/detrás**: solo agregar una regla si cambia algún insumo o trabajo.
- **Mando izquierda/derecha**: solo agregar una regla si cambia algún insumo o trabajo.

Podés agregar varias filas a una misma opción (ejemplo: cadena + contrapeso). El costo del material seleccionado se calcula aparte según m² o metros lineales y el color.

**Evitar doble conteo:** no pongas en la receta base un insumo que luego asignarás a todas las alternativas condicionales. Cuando agregues al menos una regla condicional para **cadena** en un modelo, el sistema deja de usar los viejos adicionales fijos `chain_costs` **para todas las cadenas de ese modelo**. Por eso, si activás las reglas condicionales de cadena, configurá todas sus variantes, incluida la plástica.

## Notas sobre videos

Los MP4 deben usar preferentemente H.264 para compatibilidad con celulares. La subida directa a GitHub está limitada a 8 MB por video. Para videos más largos o mayor tráfico, usá un enlace directo a MP4 en un proveedor de archivos/CDN. No sirve pegar el enlace a una página de YouTube. Guardar fotos y videos en GitHub puede activar un redeploy automático de Render.

## Verificaciones

Se comprobó la sintaxis de Python y JavaScript, la compilación de las plantillas Jinja2 y la lógica del cálculo condicional con diferentes combinaciones. No fue posible ejecutar la aplicación Flask completa en este entorno por falta de la dependencia Flask; verificá el deploy y las operaciones de guardado en Render antes de utilizar precios reales con clientes.
