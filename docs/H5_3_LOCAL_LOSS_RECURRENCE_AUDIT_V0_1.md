# H5.3i — Local-loss recurrence audit v0.1

## Objetivo

Separar una recurrencia independiente de la misma zona de una similitud de canales
observada en zonas diferentes. El auditor consume exclusivamente candidatos H5.3h
validados y no genera acciones.

## Identidad de recurrencia

Una recurrencia exacta exige coincidencia de:

- circuito y layout;
- variante de vehículo;
- ubicación nominal exacta;
- dirección de velocidad, acelerador y freno;
- al menos dos fuentes independientes.

El auto concreto se conserva en cada ocurrencia, pero la agrupación se realiza por
variante compatible. Coincidencias en curvas distintas quedan marcadas
`CROSS_ZONE_PATTERN_ONLY`.

## Resultado v5

La revisión v5 incorporó dos sesiones nuevas de Interlagos LMP2_ELMS y quedó
completa en 23/23 casos. H5.3h produjo tres candidatos no autorizados:

- T12 — Junção;
- T8 — Pinheirinho;
- sector entre T9 y T10.

H5.3i encontró:

- 0 recurrencias exactas de zona;
- 1 patrón transversal entre T8 y T12: menor velocidad, menor acelerador y más
  freno, proveniente de dos fuentes independientes;
- 0 acciones autorizadas.

La tendencia transversal es útil para orientar futuras sesiones, pero no confirma
que Junção o Pinheirinho requieran una instrucción concreta.
