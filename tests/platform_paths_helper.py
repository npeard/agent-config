"""Re-export the seam for tests, which do not run with scripts/ on sys.path."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "platform_paths",
    Path(__file__).resolve().parent.parent / "scripts" / "platform_paths.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

link_dir = _mod.link_dir
is_link = _mod.is_link
link_target = _mod.link_target
verify_link = _mod.verify_link
interpreter = _mod.interpreter
