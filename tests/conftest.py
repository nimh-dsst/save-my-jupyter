import sys
from types import ModuleType

try:
    import labapi  # noqa: F401
except ImportError:
    sys.modules.setdefault("labapi", ModuleType("labapi"))
