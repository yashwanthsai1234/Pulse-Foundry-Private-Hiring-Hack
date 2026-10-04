"""Importing this package registers every parser with the auction (sot.core.registry).

Sources:
- https://docs.python.org/3/library/pkgutil.html#pkgutil.walk_packages (finds every parser module)
- https://docs.python.org/3/library/importlib.html#importlib.import_module
"""
import importlib
import pkgutil

for _m in pkgutil.walk_packages(__path__, __name__ + "."):
    importlib.import_module(_m.name)
