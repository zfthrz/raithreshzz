# Race Engineer desktop GUI v1.6

GUI v1.6 presenta el estado del mantenimiento automático H5.3 sin convertir
evidencia shadow en coaching.

## Indicador H5.3 shadow

El indicador aparece junto al contador de sesiones y se actualiza con `Actualizar`:

- verde: cola al día o migración exacta completa;
- ámbar: existen casos nuevos pendientes de revisión;
- rojo: el estado local es inválido o el mantenimiento falló;
- gris: todavía no existe estado o evidencia H5.3.

El texto incluye la revisión numerada cuando está disponible. Al pulsarlo, su detalle
—incluido el path del archivo de labels pendiente— se muestra en el pie de la GUI.

## Fuente y seguridad

La GUI lee exclusivamente:

```text
data/local/h5_3_review_maintenance.json
```

La proyección rechaza cualquier documento que declare
`historical_actions_authorized` distinto de `false`. No abre el labeler, no escribe
labels, no ejecuta modelos y no muestra candidatos shadow como instrucciones para el
piloto. Todo el comportamiento anterior de GUI v1.5 se conserva.
