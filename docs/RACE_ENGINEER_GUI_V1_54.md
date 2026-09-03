# Race Engineer GUI v1.54

Los atajos `Ctrl+1..7` aparecen junto al nombre de cada workspace en la barra
lateral, por lo que ya no dependen de documentación externa para descubrirse.

La aplicación recuerda el último workspace principal y lo restaura al iniciar.
La preferencia se guarda atómicamente en `data/local/gui_preferences.json`, conserva
las claves existentes de orden del catálogo y falla cerrada a `Resumen` ante datos
faltantes, corruptos o desconocidos.

La preferencia afecta únicamente presentación y navegación local. No selecciona una
sesión, ejecuta análisis ni cambia History, H3 o autoridad de coaching.
