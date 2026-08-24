# Race Engineer desktop GUI v1.15

GUI v1.15 agrega la sincronización **plan ↔ mapa ↔ telemetría** (Phase A):

- Nuevo selector `Elegir zona del plan…` junto al selector de curvas en
  Telemetría, con las zonas del `next_stint_plan` validado (foco P11 con
  prefijo `FOCO`).
- Al elegir una zona: se resalta el overlay de prioridad correspondiente en el
  mapa GPS, el canvas hace zoom/fit al intervalo de la zona, el punto blanco se
  mueve al centro de la zona y el gráfico de canales enfoca exactamente el tramo
  inicio-fin con su lectura (cues) en la barra de estado.
- Replica el mecanismo del selector de curvas, pero sobre las zonas del plan
  determinista (no sobre el perfil de curvas).

## Autoridad

Presentación únicamente: no modifica plan, prioridades ni coaching.
