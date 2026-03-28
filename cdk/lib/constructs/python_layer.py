"""Helper for building Python Lambda Layers with the correct directory structure.

Lambda Layers for Python require modules to be under a ``python/`` subdirectory
inside the zip file so that the Lambda runtime can find them at /opt/python/.
CDK's Code.from_asset() does NOT add this prefix automatically.

This module prepares a temporary build directory with the correct layout
before CDK synthesises the asset, avoiding Docker or JSII bundler complexity.
"""
from __future__ import annotations

import os
import shutil


def prepare_common_layer_dir(backend_dir: str) -> str:
    """Copy backend/common into a python/ sub-directory and return the path.

    The generated layout is::

        <backend_dir>/.layer_build/
            python/
                common/   <- copy of backend/common/

    This directory is used as the CDK asset source for the Lambda Layer so
    that the runtime finds modules at /opt/python/common.

    Args:
        backend_dir: Absolute path to the backend/ directory.

    Returns:
        Absolute path to the prepared layer directory.
    """
    layer_dir = os.path.join(backend_dir, ".layer_build")
    python_dir = os.path.join(layer_dir, "python")
    dest = os.path.join(python_dir, "common")

    if os.path.exists(layer_dir):
        shutil.rmtree(layer_dir)
    os.makedirs(python_dir, exist_ok=True)
    shutil.copytree(os.path.join(backend_dir, "common"), dest)

    return layer_dir
