import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
_PACKAGE_ROOT = _SRC_ROOT / "lexlocal"

_LAYER_RULES = (
    (
        "domain",
        (
            "lexlocal.application",
            "lexlocal.infrastructure",
            "lexlocal.presentation",
            "lexlocal.bootstrap",
        ),
    ),
    (
        "application",
        (
            "lexlocal.infrastructure",
            "lexlocal.presentation",
            "lexlocal.bootstrap",
        ),
    ),
    (
        "presentation",
        (
            "lexlocal.infrastructure",
            "lexlocal.bootstrap",
        ),
    ),
    (
        "infrastructure",
        (
            "lexlocal.presentation",
            "lexlocal.bootstrap",
        ),
    ),
)

_FORBIDDEN_DOMAIN_STDLIB = {"sqlite3"}


def _iter_python_files(layer: str) -> Iterator[Path]:
    yield from (_PACKAGE_ROOT / layer).rglob("*.py")


def _iter_imported_modules(path: Path) -> Iterator[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    package_parts = list(path.parent.relative_to(_SRC_ROOT).parts)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name

        elif isinstance(node, ast.ImportFrom):
            yield from _resolve_from_import(node, package_parts)


def _resolve_from_import(
    node: ast.ImportFrom,
    package_parts: list[str],
) -> Iterator[str]:
    if node.level == 0:
        if node.module is None:
            return

        yield node.module

        for alias in node.names:
            if alias.name != "*":
                yield f"{node.module}.{alias.name}"

        return

    parent_count = node.level - 1
    base_parts = package_parts[: len(package_parts) - parent_count]

    if node.module is not None:
        base_parts.extend(node.module.split("."))

    base_module = ".".join(base_parts)

    if base_module:
        yield base_module

    for alias in node.names:
        if alias.name != "*":
            yield ".".join((*base_parts, alias.name))


def _matches_forbidden_prefix(
    module: str,
    forbidden_prefixes: tuple[str, ...],
) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in forbidden_prefixes
    )


@pytest.mark.parametrize(
    ("layer", "forbidden_prefixes"),
    _LAYER_RULES,
)
def test_layer_import_boundaries(
    layer: str,
    forbidden_prefixes: tuple[str, ...],
) -> None:
    violations: list[str] = []

    for path in _iter_python_files(layer):
        for imported_module in _iter_imported_modules(path):
            if _matches_forbidden_prefix(
                imported_module,
                forbidden_prefixes,
            ):
                relative_path = path.relative_to(_PROJECT_ROOT)
                violations.append(
                    f"{relative_path} imports {imported_module}"
                )

    assert not violations, (
        "Architecture boundary violations:\n"
        + "\n".join(sorted(violations))
    )

def test_domain_imports_only_standard_library_or_domain_modules() -> None:
    violations: list[str] = []

    for path in _iter_python_files("domain"):
        for imported_module in _iter_imported_modules(path):
            root_module = imported_module.split(".", 1)[0]

            is_domain_module = (
                imported_module == "lexlocal.domain"
                or imported_module.startswith("lexlocal.domain.")
            )

            is_allowed_stdlib = (
                root_module in sys.stdlib_module_names
                and root_module not in _FORBIDDEN_DOMAIN_STDLIB
            )

            if not is_domain_module and not is_allowed_stdlib:
                relative_path = path.relative_to(_PROJECT_ROOT)
                violations.append(
                    f"{relative_path} imports forbidden dependency "
                    f"{imported_module}"
                )

            if root_module in _FORBIDDEN_DOMAIN_STDLIB:
                relative_path = path.relative_to(_PROJECT_ROOT)
                violations.append(
                    f"{relative_path} imports forbidden dependency "
                    f"{imported_module}"
                )

    assert not violations, (
        "Forbidden domain dependencies:\n"
        + "\n".join(sorted(set(violations)))
    )

def test_domain_modules_do_not_import_from_domain_package_root() -> None:
    violations: list[str] = []

    for path in _iter_python_files("domain"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module == "lexlocal.domain"
            ):
                relative_path = path.relative_to(_PROJECT_ROOT)
                violations.append(
                    f"{relative_path} imports from lexlocal.domain package root"
                )

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "lexlocal.domain":
                        relative_path = path.relative_to(_PROJECT_ROOT)
                        violations.append(
                            f"{relative_path} imports lexlocal.domain package root"
                        )

    assert not violations, (
        "Domain package-root imports are forbidden:\n"
        + "\n".join(sorted(violations))
    )