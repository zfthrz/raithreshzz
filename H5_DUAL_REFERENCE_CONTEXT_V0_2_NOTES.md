# H5.1 Dual Reference Context v0.2

Hotfix de compatibilidad de schema.

H4 v0.1/v0.2 real emite:
- `target_session.session_reference`;
- `selection_status`;
- `selected_historical_reference.lap`;
- `selected_historical_reference.duration_s`.

H5.1 v0.1 esperaba nombres de un draft anterior (`target.reference`, `status`, etc.).
Eso causó `selection.target ausente/inválido` con una salida H4 válida.

v0.2 consume el schema real y mantiene aliases de backward compatibility.
También corrige la lectura del contexto de `analyze_telemetry`:
`vehicle_identity.variant` es el campo canónico.

No cambia ninguna política H4/H5:
- session_reference sigue siendo la autoridad de coaching;
- historical_reference sigue siendo benchmark observacional;
- no se generan acciones históricas sin telemetría raw cross-session.
