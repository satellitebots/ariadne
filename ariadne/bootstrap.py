"""One call that makes the overlay real, for every entry point that can import Hermes.

`overlay.install()` fixes the import order; `overlay.apply()` prepends each overlaid package's path. Call `install()`
before the first `import run_agent` (or any other Hermes module), and nothing else has to know about the submodule.
"""
from .overlay import apply, install  # noqa: F401


def start():
    """Install the order and apply the declared overlays; returns the packages that were overlaid."""
    return apply()
