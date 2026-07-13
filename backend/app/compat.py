"""Compatibility shims for third-party packages.

Currently one shim: faiss-cpu's aarch64 loader probes for ARM SVE support
via `numpy.distutils.cpuinfo`, but numpy does not ship numpy.distutils on
Python 3.12 (stdlib distutils was removed), so importing faiss crashes on
the Raspberry Pi. The stub below satisfies the probe and reports no SVE —
which is factually correct for the CM5's Cortex-A76 cores, so faiss loads
its standard NEON build exactly as it would with a real probe.
"""

import sys
import types

from app.logging_setup import get_logger

logger = get_logger("compat")


def install_numpy_distutils_stub() -> None:
    """Provide a minimal numpy.distutils.cpuinfo if numpy no longer ships it.

    Must be called before the first `import faiss`.
    """
    try:
        import numpy.distutils.cpuinfo  # noqa: F401  (real module exists: nothing to do)
        return
    except ImportError:
        pass

    import numpy

    cpuinfo = types.ModuleType("numpy.distutils.cpuinfo")
    # faiss reads: cpuinfo.cpu.info[0].get("Features", "") — report no features.
    cpuinfo.cpu = types.SimpleNamespace(info=[{}])  # type: ignore[attr-defined]

    distutils_mod = types.ModuleType("numpy.distutils")
    distutils_mod.cpuinfo = cpuinfo  # type: ignore[attr-defined]

    sys.modules["numpy.distutils"] = distutils_mod
    sys.modules["numpy.distutils.cpuinfo"] = cpuinfo
    # `import numpy.distutils.cpuinfo` alone does not bind the attribute on the
    # parent package when sys.modules is pre-populated, so bind it explicitly.
    numpy.distutils = distutils_mod  # type: ignore[attr-defined]

    logger.info("Installed numpy.distutils stub for faiss (Python 3.12 compatibility)")
