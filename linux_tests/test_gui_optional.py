# -*- coding: utf-8 -*-
"""Guard: the desktop GUI (PyQt6) is optional, the WebUI is the product.

ADR-002 replaces the Qt interface; Step 7 of docs/webui/PLAN.md moves Qt to
`requirements-gui.txt`. These checks keep the pins from creeping back into the
default install and keep `main.py` failing with a message instead of a
traceback when Qt is missing.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIREMENTS = ("requirements.txt", "requirements-rocm.txt",
                        "requirements-web.txt", "requirements-dev.txt")


def _requirement_lines(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        yield stripped


def test_default_requirements_do_not_pin_qt():
    offenders = {}
    for name in DEFAULT_REQUIREMENTS:
        path = ROOT / name
        if not path.is_file():
            continue
        hits = [line for line in _requirement_lines(path)
                if line.lower().startswith(("pyqt", "pyside"))]
        if hits:
            offenders[name] = hits
    assert offenders == {}, f"Qt is optional now (requirements-gui.txt): {offenders}"


def test_gui_requirements_pin_qt():
    lines = list(_requirement_lines(ROOT / "requirements-gui.txt"))
    assert any(line.startswith("PyQt6==") for line in lines)
    assert any(line.startswith("PyQt6-Qt6==") or line.startswith("PyQt6_sip==")
               for line in lines)


def test_install_script_can_add_the_gui():
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "--with-gui" in script
    assert "requirements-gui.txt" in script


def _pyqt_imports(tree):
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PyQt6")]


def test_main_imports_qt_behind_a_guard():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))

    unguarded = [node for node in tree.body if isinstance(node, ast.ImportFrom)
                 and (node.module or "").startswith("PyQt6")]
    assert unguarded == [], "PyQt6 must not be imported at module level unguarded"

    guards = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        imports_qt = any((getattr(sub, "module", "") or "").startswith("PyQt6")
                         for sub in ast.walk(node))
        catches_import_error = any(
            isinstance(handler.type, ast.Name) and handler.type.id == "ImportError"
            for handler in node.handlers)
        if imports_qt and catches_import_error:
            guards.append(node)
    assert guards, "main.py must catch ImportError around the PyQt6 import"

    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "requirements-gui.txt" in source, "the error message must say where Qt lives"
    assert "web.main" in source, "the error message must point at the WebUI"
