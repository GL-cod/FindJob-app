"""Keep the long-running app in step with code pulled from GitHub.

Streamlit re-runs app/dashboard.py when it changes, but modules it imports (src.*) stay
in memory. After a git pull that touched src/, reload all of them, dependencies first.
"""
import importlib
import sys
from pathlib import Path

# dependencies before the modules that use them
ORDER = [
    "src.lang", "src.metrics", "src.store", "src.telegram", "src.gemini_handler", "src.feedback",
    "src.sources.common", "src.sources.hellowork", "src.sources.linkedin", "src.sources.apec", "src.sources.francetravail", "src.sources",
    "src.dedupe", "src.relevance", "src.cdi_relevance", "src.sheets", "src.stats", "src.gitsync",
    "src.tracking", "src.cdi_main", "src.reseau", "src.reseau_ui",
]
_STATE = {"stamp": None}


def _stamp(src_dir):
    return max((p.stat().st_mtime_ns for p in Path(src_dir).rglob("*.py")), default=0)


def reload_if_changed(src_dir):
    """Returns True when modules were reloaded."""
    stamp = _stamp(src_dir)
    previous, _STATE["stamp"] = _STATE["stamp"], stamp
    if previous is None or stamp == previous:
        return False
    for name in ORDER + sorted(n for n in sys.modules if n.startswith("src.") and n not in ORDER):
        module = sys.modules.get(name)
        if module is not None:
            try:
                importlib.reload(module)
            except Exception:
                pass  # a module removed upstream: the next import will tell
    return True
