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
            "foundry_local_sdk",
            "openai",
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
_SQL_WRITE_PREFIXES = (
    "ALTER TABLE ",
    "CREATE TABLE ",
    "DELETE FROM ",
    "DROP TABLE ",
    "INSERT INTO ",
    "REPLACE INTO ",
    "UPDATE ",
)
_PATH_WRITE_METHODS = {"write_bytes", "write_text"}
_SHUTIL_WRITE_FUNCTIONS = {"copy", "copyfile"}
_WRITE_OPEN_MODE_CHARACTERS = frozenset("wax+")


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


def _application_write_violations(tree: ast.AST) -> list[str]:
    violations: list[str] = []
    shutil_module_names = {"shutil"}
    shutil_function_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlite3":
                    violations.append("direct sqlite3 import")
                if alias.name == "shutil":
                    shutil_module_names.add(alias.asname or alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module == "sqlite3":
                violations.append("direct sqlite3 import")
            if node.module == "shutil":
                for alias in node.names:
                    if alias.name in _SHUTIL_WRITE_FUNCTIONS:
                        shutil_function_names.add(alias.asname or alias.name)

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            normalized = " ".join(node.value.split()).upper()
            if normalized.startswith(_SQL_WRITE_PREFIXES):
                violations.append("raw SQL write")

        elif isinstance(node, ast.Call):
            violation = _application_write_call_violation(
                node,
                shutil_module_names,
                shutil_function_names,
            )
            if violation is not None:
                violations.append(violation)

    return violations


def _application_write_call_violation(
    node: ast.Call,
    shutil_module_names: set[str],
    shutil_function_names: set[str],
) -> str | None:
    if _is_write_mode_open(node):
        return "write-mode open"

    if isinstance(node.func, ast.Attribute):
        if node.func.attr in _PATH_WRITE_METHODS:
            return f"Path.{node.func.attr}"
        if (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id in shutil_module_names
            and node.func.attr in _SHUTIL_WRITE_FUNCTIONS
        ):
            return f"shutil.{node.func.attr}"

    if (
        isinstance(node.func, ast.Name)
        and node.func.id in shutil_function_names
    ):
        return f"shutil.{node.func.id}"

    return None


def _is_write_mode_open(node: ast.Call) -> bool:
    is_open = isinstance(node.func, ast.Name) and node.func.id == "open"
    is_builtins_open = (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "builtins"
        and node.func.attr == "open"
    )
    if not is_open and not is_builtins_open:
        return False

    mode_node: ast.expr | None = node.args[1] if len(node.args) > 1 else None
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value

    return (
        isinstance(mode_node, ast.Constant)
        and isinstance(mode_node.value, str)
        and any(character in mode_node.value for character in _WRITE_OPEN_MODE_CHARACTERS)
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


def test_application_has_no_direct_persistence_writes() -> None:
    violations: list[str] = []

    for path in _iter_python_files("application"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_path = path.relative_to(_PROJECT_ROOT)
        for violation in _application_write_violations(tree):
            violations.append(f"{relative_path}: {violation}")

    assert not violations, (
        "Application direct-write violations:\n"
        + "\n".join(sorted(violations))
    )


@pytest.mark.parametrize(
    ("source", "expected_violation"),
    [
        ("import sqlite3", "direct sqlite3 import"),
        ('query = "UPDATE records SET value = ?"', "raw SQL write"),
        ('open("source.bin", "wb")', "write-mode open"),
        ('Path("source.bin").write_bytes(b"data")', "Path.write_bytes"),
        ('Path("source.txt").write_text("data")', "Path.write_text"),
        ('shutil.copy("source", "target")', "shutil.copy"),
        ('shutil.copyfile("source", "target")', "shutil.copyfile"),
    ],
)
def test_application_write_guard_rejects_representative_bypasses(
    source: str,
    expected_violation: str,
) -> None:
    tree = ast.parse(source)

    assert expected_violation in _application_write_violations(tree)


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path",
        'Path("source.txt").read_text()',
        'open("source.txt")',
        'open("source.txt", "rb")',
        'query = "SELECT value FROM records"',
    ],
)
def test_application_write_guard_allows_read_only_operations(source: str) -> None:
    tree = ast.parse(source)

    assert _application_write_violations(tree) == []

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
