import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "rimex"

FORBIDDEN_IMPORTS = {
    "domain": ["aiohttp", "fastapi", "pydantic", "rimex.clients", "rimex.services", "rimex.presentation"],
    "clients": ["fastapi", "rimex.services", "rimex.presentation"],
    "services": ["fastapi", "rimex.presentation"],
}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def layer_files(layer: str) -> list[Path]:
    return sorted((PACKAGE / layer).rglob("*.py"))


@pytest.mark.parametrize("layer", sorted(FORBIDDEN_IMPORTS))
def test_layer_does_not_depend_on_outer_layers(layer):
    violations = []
    for path in layer_files(layer):
        for module in imported_modules(path):
            for forbidden in FORBIDDEN_IMPORTS[layer]:
                if module == forbidden or module.startswith(forbidden + "."):
                    violations.append(f"{path.relative_to(PACKAGE)} imports {module}")

    assert violations == []


def test_every_layer_has_modules():
    for layer in FORBIDDEN_IMPORTS:
        assert layer_files(layer), f"rimex/{layer} is empty"
