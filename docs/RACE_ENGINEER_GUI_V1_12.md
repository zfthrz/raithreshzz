# Race Engineer desktop GUI v1.12

GUI v1.12 reorganiza la navegación principal en cuatro secciones y corrige el área
de Telemetría.

## Navegación

- **Resumen**: Debrief, Próxima tanda, Vueltas.
- **Telemetría**: Mapa y canales.
- **Historial**: Referencia, Comparación.
- **Diagnóstico**: Pipeline, Ejecución.

Cada sección principal agrupa sub-vistas técnicas para reducir la cantidad de
pestañas a nivel raíz.

## Tarjetas compactas

La sesión seleccionada muestra cuatro tarjetas:

- vuelta de referencia;
- cantidad de vueltas válidas;
- disponibilidad de comparación histórica (`Comparación lista` / `Referencia
  disponible` / `Sin compatible`);
- estado de la sesión (`Debrief listo`, `History listo`, `Fallida`, etc.).

## Área de Telemetría

- Mapa y canales viven dentro de un `Panedwindow` vertical con separador
  arrastrable.
- El gráfico de canales tiene mayor altura inicial y se expande con su panel.
- Velocidad, acelerador y freno ocupan tres carriles.
- Si el tamaño real es menor a 180×120 px, no se dibujan líneas con dimensiones
  ficticias; se muestra el mensaje `Ampliá el panel de canales para ver
  velocidad, acelerador y freno`.
- El canvas se redibuja junto con su panel.

## Autoridad

Cambios de presentación únicamente: no alteran H5.1, H5.2, H5.3 ni el coaching
de la sesión.
