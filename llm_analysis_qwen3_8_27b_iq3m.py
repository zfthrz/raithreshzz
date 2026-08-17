"""Entry point aislado para evaluar Qwen3.8 27B IQ3_M con Ollama.

El analizador canónico conserva toda la lógica, contratos y validadores.
Este archivo sólo selecciona un alias Ollama distinto para que la prueba no
reemplace ni mezcle los resultados del modelo local ``ingenierov3``.
"""

from __future__ import annotations

import llm_analysis as implementation


MODEL_NAME = "qwen38-27b-iq3m"


def main() -> None:
    implementation.MODEL_NAME = MODEL_NAME
    implementation.main()


if __name__ == "__main__":
    main()
