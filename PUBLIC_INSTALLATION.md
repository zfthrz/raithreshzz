# Race Engineer — Public installation

## English

### Install

1. Extract the complete `RaceEngineer` folder to a location you can write to.
2. Keep every file and subfolder together.
3. Start `RaceEngineer.exe` and complete the first-run language and telemetry-folder
   choices.

Race Engineer is portable and includes its Python runtime. You do not need to install
Python or run `pip`.

### Update

1. Close Race Engineer and wait for any running analysis to finish.
2. Extract the new release into a new empty folder.
3. Start `RaceEngineer.exe` from the new folder.
4. After confirming that the new version opens normally, you may remove the previous
   application folder.

Do not copy a new release over an existing application folder. User settings,
generated reports, History and statistics remain under
`%LOCALAPPDATA%\RaceEngineer` and are reused by the new version. LMU telemetry stays
in the folder selected by the user and is never part of the application installation.

### Uninstall

Close Race Engineer and remove only the extracted application folder. This keeps
settings, generated reports, History, statistics and LMU telemetry.

To also erase Race Engineer's local user data, remove
`%LOCALAPPDATA%\RaceEngineer` separately after making any backup you want. Race
Engineer never deletes the LMU telemetry folder selected by the user.

## Español

### Instalar

1. Extraé la carpeta `RaceEngineer` completa en una ubicación donde puedas escribir.
2. Conservá juntos todos los archivos y subdirectorios.
3. Abrí `RaceEngineer.exe` y completá la elección inicial de idioma y carpeta de
   telemetría.

Race Engineer es portable e incluye su entorno de Python. No necesitás instalar
Python ni ejecutar `pip`.

### Actualizar

1. Cerrá Race Engineer y esperá a que termine cualquier análisis en ejecución.
2. Extraé la nueva versión en una carpeta nueva y vacía.
3. Abrí `RaceEngineer.exe` desde la carpeta nueva.
4. Después de comprobar que la versión nueva abre normalmente, podés eliminar la
   carpeta de la aplicación anterior.

No copies una versión nueva sobre una carpeta de aplicación existente. Las
preferencias, los reportes generados, History y las estadísticas permanecen en
`%LOCALAPPDATA%\RaceEngineer` y la versión nueva los reutiliza. La telemetría de LMU
permanece en la carpeta elegida por el usuario y nunca forma parte de la instalación.

### Desinstalar

Cerrá Race Engineer y eliminá solamente la carpeta donde extrajiste la aplicación.
Esto conserva las preferencias, los reportes generados, History, las estadísticas y
la telemetría de LMU.

Si además querés borrar los datos locales de Race Engineer, eliminá por separado
`%LOCALAPPDATA%\RaceEngineer` después de realizar la copia de seguridad que quieras.
Race Engineer nunca elimina la carpeta de telemetría de LMU elegida por el usuario.
