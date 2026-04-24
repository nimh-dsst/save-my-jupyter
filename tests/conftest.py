import sys
from types import ModuleType

sys.modules.setdefault("labapi", ModuleType("labapi"))
