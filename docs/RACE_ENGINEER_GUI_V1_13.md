# Race Engineer desktop GUI v1.13

GUI v1.13 agrega dos mejoras de lectura sobre el catálogo y la comparación
histórica, sin cambiar ninguna autoridad del pipeline.

## B. Badges de estado en el catálogo

La columna `Estado` de la lista de sesiones ahora colorea el texto según el
estado real de la sesión:

- `DEBRIEF_READY` verde;
- `DEBRIEF_UNVALIDATED` dorado;
- `HISTORY_READY` amarillo;
- `ANALYZED` azul;
- `CHANGED_REVIEW_REQUIRED` violeta;
- `FAILED` rojo;
- `PENDING_STABILITY` / `INCOMPLETE` gris.

Al pasar el mouse sobre una fila, un tooltip explica brevemente qué significa ese
estado y qué acción sigue. Los colores y tooltips están centralizados en
`SESSION_STATUS_COLORS` y `SESSION_STATUS_TOOLTIPS`, y la columna sigue mostrando
el mismo `status_detail` de siempre.

## C. Comparación histórica lado a lado

La pestaña `Historial → Comparación` reemplaza el texto plano por una vista
estructurada:

- una línea de resumen con el delta `actual − histórica`;
- dos paneles lado a lado con la vuelta histórica y la vuelta actual (`History #`,
  número de vuelta y tiempo formateado);
- debajo, un panel de detalle con las zonas de mayor impacto deterministas
  (top 3 ordenadas por `|delta_change|`) y, si existe, la lectura histórica
  validada por el LLM con su backend/modelo.

Si la sesión no tiene H5.2, la pestaña muestra el estado de la etapa y el fallback
explicativo en el panel de detalle.

La vista se calcula en `race_engineer_ui_model.py`
(`SessionDetail.historical_comparison_view`) a partir de los artefactos H5.2 ya
validados; la GUI sólo la presenta.

## Autoridad

Cambios de presentación únicamente: no alteran H4, H5.1, H5.2, H5.3 ni el coaching
de la sesión. La comparación sigue siendo observacional y no reemplaza
`session_reference`.
