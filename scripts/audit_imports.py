"""AST import audit for the product debrief path."""

import ast


def get_imports(source_path):
    """Return all top-level import names from a Python file."""
    source = open(source_path, "r", encoding="utf-8").read()
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


for module in ("deterministic_debrief.py", "deterministic_debrief_main.py"):
    imports = get_imports(module)
    print(f"{module} imports: {sorted(imports)}")
    backend_hits = [i for i in imports if i.startswith("llm_analysis")]
    print(f"  Backend imports: {backend_hits}")
    print()
