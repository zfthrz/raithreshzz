"""Transitive import audit for the product debrief path.

Walks the AST of every module reachable from the neutral entrypoint,
resolving imports recursively, and reports any hits on llm_analysis*
modules.  This covers the full transitive closure, not just the top-level
file.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# The entrypoint module for the product debrief.
ENTRYPOINT = ROOT / "deterministic_debrief.py"


def _get_imports(source_path: Path) -> set[str]:
    """Return all top-level import names from a Python file."""
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def _resolve_module(name: str, root: Path) -> Path | None:
    """Try to locate the file behind an import name."""
    candidate = root / f"{name}.py"
    if candidate.is_file():
        return candidate
    # Package import: name/submodule.py
    pkg = root / name
    if pkg.is_dir():
        return pkg
    return None


def _audit_transitive(entry: Path, root: Path):
    """Walk the transitive import closure from *entry*."""
    visited: set[Path] = set()
    all_imports: set[str] = set()
    queue: list[Path] = [entry]

    while queue:
        mod_path = queue.pop(0)
        if mod_path in visited:
            continue
        visited.add(mod_path)

        imports = _get_imports(mod_path)
        all_imports.update(imports)

        for imp in list(imports):
            resolved = _resolve_module(imp, root)
            if resolved and resolved.is_file():
                queue.append(resolved)

    return visited, all_imports


def main():
    visited, all_imports = _audit_transitive(ENTRYPOINT, ROOT)

    print(f"Modules visited (transitive closure): {sorted(p.relative_to(ROOT) for p in visited)}")
    print(f"\nAll imports in closure: {sorted(all_imports)}")

    backend_hits = [i for i in all_imports if i.startswith("llm_analysis")]
    print(f"\nBackend imports in closure: {backend_hits}")

    if backend_hits:
        print("\nFAIL: llm_analysis* modules found in transitive closure!")
        sys.exit(1)
    else:
        print("\nPASS: zero llm_analysis* imports in transitive closure.")


if __name__ == "__main__":
    main()
