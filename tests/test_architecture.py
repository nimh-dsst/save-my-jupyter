"""Architecture guard: the pure layers must not import IO libraries, and ports
may import only the domain. Backs the import rules in docs/development.md."""

from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "save_my_jupyter"
_FORBIDDEN_IO_LIBS = frozenset(
    {"tornado", "dulwich", "labapi", "sqlite3", "keyring", "requests"}
)


def _python_files(subpackage: str) -> list[Path]:
    return sorted((_PACKAGE_ROOT / subpackage).rglob("*.py"))


def _module_dotted_name(path: Path) -> str:
    relative = path.relative_to(_PACKAGE_ROOT.parent).with_suffix("")
    return ".".join(relative.parts)


def _is_type_checking_block(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _top_level_imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Module-body imports only, excluding `if TYPE_CHECKING:` blocks and any
    imports nested inside functions or classes."""
    imports: list[ast.Import | ast.ImportFrom] = []
    for node in tree.body:
        if _is_type_checking_block(node):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
    return imports


def _imported_library_roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if node.level == 0 and node.module is not None:
        return [node.module.split(".")[0]]
    return []  # relative imports are internal to the package


def _resolved_from_module(node: ast.ImportFrom, module_dotted: str) -> str | None:
    if node.level == 0:
        return node.module
    parts = module_dotted.split(".")
    base = parts[: len(parts) - node.level]
    if node.module is not None:
        base = base + node.module.split(".")
    return ".".join(base)


def _io_library_violations(subpackage: str) -> list[str]:
    violations: list[str] = []
    for path in _python_files(subpackage):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _module_dotted_name(path)
        for node in _top_level_imports(tree):
            for root in _imported_library_roots(node):
                if root in _FORBIDDEN_IO_LIBS:
                    violations.append(
                        f"{module}:{node.lineno} imports forbidden IO library '{root}'"
                    )
    return violations


def test_domain_has_no_io_library_imports() -> None:
    assert _io_library_violations("domain") == []


def test_ports_have_no_io_library_imports() -> None:
    assert _io_library_violations("ports") == []


def test_application_has_no_io_library_imports() -> None:
    assert _io_library_violations("application") == []


def test_ports_only_import_domain_from_project() -> None:
    violations: list[str] = []
    for path in _python_files("ports"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _module_dotted_name(path)
        for node in _top_level_imports(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                resolved = _resolved_from_module(node, module)
                if resolved is not None:
                    targets.append(resolved)
            else:
                targets.extend(alias.name for alias in node.names)
            for target in targets:
                if target.startswith("save_my_jupyter") and not target.startswith(
                    ("save_my_jupyter.domain", "save_my_jupyter.ports")
                ):
                    violations.append(
                        f"{module}:{node.lineno} imports project module "
                        f"'{target}' (ports may import only save_my_jupyter.domain)"
                    )
    assert violations == []
