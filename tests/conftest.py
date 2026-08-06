"""Test bootstrap: make the repo root importable.

The integration is imported as ``custom_components.bambu_costs.*`` — a PEP 420
namespace package, so no ``__init__.py`` is needed at the ``custom_components``
level. Modules that import Home Assistant are skipped when it is not installed
(see the ``importorskip`` at the top of the files that need it), so the pure
ones still run anywhere.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
