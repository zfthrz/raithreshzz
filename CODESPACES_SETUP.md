# Subir este proyecto a GitHub y abrirlo en Codespaces

## Opción recomendada desde una PC sin Python

### 1. Crear un repositorio privado

En GitHub:

1. `New repository`
2. Nombre sugerido: `race-engineer`
3. Elegir `Private`
4. Crear el repositorio.

### 2. Subir los archivos

Descomprimí `race-engineer-codespaces.zip` con el soporte ZIP de Windows.

En el repositorio de GitHub:

1. `Add file`
2. `Upload files`
3. Arrastrá el contenido de la carpeta `race-engineer-codespaces`
4. Commit.

Es importante que `.devcontainer`, `.github` y `.vscode` queden en la raíz.

### 3. Crear el Codespace

En el repositorio:

1. `Code`
2. pestaña `Codespaces`
3. `Create codespace on main`

El primer arranque instalará automáticamente las dependencias.

### 4. Verificar

En la terminal del Codespace:

```bash
python scripts/check_project.py
pytest -q
python scripts/smoke_portable.py
```

Mientras falten los cuatro módulos base, `check_project.py` lo informará como
warning esperado. Las herramientas portables deberían funcionar.

## Copiar los cuatro módulos base más adelante

Cuando vuelvas a tu PC de casa, agregar a la raíz:

```text
telemetry.py
laps.py
delta_comparison.py
sector_analysis.py
```

Después:

```bash
git add telemetry.py laps.py delta_comparison.py sector_analysis.py
git commit -m "Add telemetry core modules"
git push
```

El Codespace verá el cambio al actualizar el repo.

## Ollama

No intentes instalar el modelo local grande dentro de Codespaces como parte de
este setup. La arquitectura actual mantiene:

- Python determinista: portable / Codespaces
- Ollama + `ingenierov2`: PC local

Más adelante podemos diseñar un modo opcional de endpoint remoto sin romper el
modo local.
