from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)

BLOCKED_IMPORTS = frozenset({"os", "subprocess", "sys", "shutil", "socket", "ctypes"})
BLOCKED_BUILTINS = frozenset({"eval", "exec", "__import__", "compile", "open"})


class ScriptValidationError(Exception):
    pass


def validate_cadquery_script(script: str) -> bool:
    try:
        tree = ast.parse(script)
    except SyntaxError as e:
        raise ScriptValidationError(f"構文エラー: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in BLOCKED_IMPORTS:
                    raise ScriptValidationError(
                        f"ブロックされたモジュール: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split(".")[0]
                if mod in BLOCKED_IMPORTS:
                    raise ScriptValidationError(
                        f"ブロックされたモジュール: {node.module}"
                    )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_BUILTINS:
                raise ScriptValidationError(
                    f"ブロックされた関数: {node.func.id}"
                )

    logger.info("CadQuery script validation passed (%d nodes)", len(list(ast.walk(tree))))
    return True
