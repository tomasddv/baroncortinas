# Fuentes y comprobación de cálculos

Se inspeccionaron directamente todas las hojas, celdas con datos, fórmulas y
nombres definidos de los dos libros adjuntos. No se copiaron cálculos de la demo.
No se agregan los Excel ni los datos de clientes al repositorio público.

## cotizador baron rollers.xlsx

Hoja1 D5=0,53 y D6=2,2: ANCHO/ALTO en metros (nombres definidos).
Hoja2 y Hoja3 vacías. Precios fuente:

|Celdas Hoja1|Concepto|Valor usado|Unidad inferida de la fórmula|
|---|---|---:|---|
|B7 / B8 / B9|Screen / Blackout / Traslúcida|23650 / 23650 / 16000|ARS/m²|
|B10 / B11|Sistema 32 / 41|36000 / 42000|ARS por cortina|
|B12 / B13 / B14 / B15|Caño 32 / 41 / 45 / 58|37400 / 41800 / 49280 / 62900|ARS/m|
|B16 / D16|Guías|25000|ARS/m de alto, sin multiplicar por dos|

B19:D22 usan las mismas reglas para las tres telas:
`ancho_m × (alto_m + extra_m) × tarifa_tela + sistema + ancho_m × tarifa_caño`.
Extras: fila 19=0,20; fila 20=0,30; fila 21=0,35; fila 22=0,40 m.
C19 es SCREEN: `=ANCHO*(ALTO+0.2)*TELAS_SCREEN+SISTEMA_32+ANCHO*CAÑO_32`.
Filas 20/21/22 utilizan SISTEMA_41; el rótulo A20 dice SISTEMA DE 42, pero los
nombres y precios dicen 41. La UI usa **42** y documenta esa equivalencia.

Ejemplo independiente, Screen 150×180 cm: caño 32 → tela 3 m²×23650=70950;
sistema=36000; caño 1,5m×37400=56100; total **163050**. Tres iguales=489150.
Caño 42 → 179197,50; 45 → 192191,25; 58 → 214395.
Las fórmulas originales no incluyen mínimo, reducción de ancho ni merma general.
Esos parámetros se inicializan en cero, de forma explícita y editable.

H18=C19×1,33 y H19=C19×0,95 son factores aislados sin etiqueta de pago:
**no se aplican** automáticamente. F19/F20 multiplican F5, que está vacío:
no se interpreta como una cantidad o un total comercial válido.

## PRECIOS Y COTIZADOR ●● MR SEPTIEMBRE 2026.xlsx

Hojas: PRECIOS, Cotiz. ZEBRA, Cotiz. Paneles, Cotiz. B. Verticales.
No existe hoja de cotización Roller simple equivalente a BARÓN.
PRECIOS tiene un área formateada hasta 512×789 pero los datos relevantes están
en A:G. G1=3,5%; muchas filas G=F+F×G1, C=G y D=C+C×21%.
Otras filas tienen C o D constantes que no siguen esas fórmulas: no se fuerza
una reconciliación ni se mezclan indiscriminadamente con el libro BARÓN.

Los sistemas Roller PRECIOS A5:A20 se expresan M/L, a diferencia del sistema
fijo del Excel BARÓN. Caños A45:A48 M/L. Telas Screen A115:A117 metro2;
Blackout A119:A122 y Traslúcidas A124:A131 metro2. Los anchos/color varían por
producto (1,83/2,50/3,00 m): no confundir con el rollo nominal interno 2,80 m.
La app conserva anchos de materiales anteriores y permite editar cada lote.

Cotiz. ZEBRA H1/I1 declara mínimo 1m/l sistema y 1m² tela, pero L7=
`IFNA((E7*F7*J7)+(H7*K7),0)` no aplica MAX; M7=L7×I7 y N7=M7+21%.
No corresponde trasladar ese mínimo a Roller BARÓN sin validación. Paneles
T6 suma sistema, tela, zócalo y soportes; U6 multiplica cantidad y V6 IVA.
Verticales L5 suma tela/sistema/soportes y M5/N5 cantidad e IVA. Son referencias
de arquitectura extensible, no fórmulas activadas para productos nuevos.

## Reglas iniciales y límites

Se adopta la fórmula específica BARÓN como fuente inicial de Roller, dejando
el catálogo previo intacto y seleccionable. No se activan las fórmulas de otros
productos ni los recargos de proveedor. El importe del Excel se trata como
base comercial sin markup ni impuesto adicional; se conserva separado del
despiece interno editable. Los colores iniciales provienen del catálogo
existente, no del ejemplo gráfico ni de supuestos. Los datos de contacto se
toman de configuración; si están vacíos el exportador no inventa números.
