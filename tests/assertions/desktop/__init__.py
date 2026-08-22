"""Desktop evidence-oracle API, grouped by the behavior being proven."""

from .accounts import *
from .applications import *
from .catalog import *
from .events import *
from .session import *
from .shell import *
from .system import *


__all__ = tuple(name for name in globals() if name.startswith("_"))
