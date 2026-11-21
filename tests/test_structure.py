"""Checks for the shape the refactor is moving toward."""
import ast

from tests.testenv import ROOT


def test_app_py_defines_no_classes():
    """BE2-5: tables live in models/, API shapes in schemas/."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    assert [n.name for n in tree.body if isinstance(n, ast.ClassDef)] == []
