"""Tests for script_validator."""
from __future__ import annotations

import pytest

import sys
sys.path.insert(0, "/workspaces/2Dto3D/backend")

from common.script_validator import validate_cadquery_script, ScriptValidationError


def test_valid_cadquery_script():
    """Valid CadQuery script passes validation."""
    script = """import cadquery as cq
result = cq.Workplane("XY").box(10, 20, 30)
"""
    assert validate_cadquery_script(script) is True


def test_blocked_import_os():
    """Script importing os is rejected."""
    script = """import os
import cadquery as cq
result = cq.Workplane("XY").box(10, 20, 30)
"""
    with pytest.raises(ScriptValidationError, match="os"):
        validate_cadquery_script(script)


def test_blocked_import_subprocess():
    """Script importing subprocess is rejected."""
    script = """import subprocess
"""
    with pytest.raises(ScriptValidationError, match="subprocess"):
        validate_cadquery_script(script)


def test_blocked_from_import():
    """from-style blocked import is rejected."""
    script = """from os.path import join
"""
    with pytest.raises(ScriptValidationError, match="os"):
        validate_cadquery_script(script)


def test_blocked_builtin_eval():
    """Script using eval() is rejected."""
    script = """x = eval("1+1")
"""
    with pytest.raises(ScriptValidationError, match="eval"):
        validate_cadquery_script(script)


def test_blocked_builtin_exec():
    """Script using exec() is rejected."""
    script = """exec("print(1)")
"""
    with pytest.raises(ScriptValidationError, match="exec"):
        validate_cadquery_script(script)


def test_blocked_builtin_open():
    """Script using open() is rejected."""
    script = """f = open("/etc/passwd")
"""
    with pytest.raises(ScriptValidationError, match="open"):
        validate_cadquery_script(script)


def test_syntax_error():
    """Script with syntax errors raises validation error."""
    script = """def foo(
"""
    with pytest.raises(ScriptValidationError, match="構文エラー"):
        validate_cadquery_script(script)


def test_complex_valid_script():
    """Complex but safe CadQuery script passes."""
    script = """import cadquery as cq

BASE_W = 100.0
BASE_H = 50.0
BASE_D = 20.0

base = cq.Workplane("XY").box(BASE_W, BASE_H, BASE_D)

holes = base.faces(">Z").workplane()
for x_pos in range(-40, 41, 20):
    holes = holes.center(x_pos, 0).hole(6.0).center(-x_pos, 0)

result = holes.edges("|Z").fillet(2.0)
"""
    assert validate_cadquery_script(script) is True


def test_allowed_imports():
    """math and cadquery imports are allowed."""
    script = """import math
import cadquery as cq
r = math.sqrt(2) * 10
result = cq.Workplane("XY").circle(r).extrude(5)
"""
    assert validate_cadquery_script(script) is True
