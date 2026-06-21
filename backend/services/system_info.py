"""
Hardware detection for Phase 3 performance profiles.

On first run (and from Settings) the app inspects the machine and *suggests* a
profile — Lite for the 8 GB / no-GPU lab PC, Power for the 16 GB + GPU desktop.
The suggestion is advisory: the user always makes the final call in Settings.

Everything here is best-effort and dependency-free where possible:
- RAM uses `psutil` if it happens to be installed, otherwise a stdlib path
  (ctypes on Windows, `os.sysconf` on POSIX).
- GPU detection avoids importing heavy libraries (torch) — it shells out to
  `nvidia-smi` if present, which covers the NVIDIA case (the RTX 3060 dev box).

No function here raises: detection failure degrades to "unknown" and a safe
Lite suggestion, never a crash.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Optional

import config


def _total_ram_gb() -> Optional[float]:
    """Total physical RAM in GB, or None if it can't be determined."""
    # 1) psutil — most reliable, cross-platform (optional dependency).
    try:
        import psutil  # type: ignore
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        pass

    # 2) POSIX — sysconf pages × page size.
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            return round(total / (1024 ** 3), 1)
    except Exception:
        pass

    # 3) Windows — GlobalMemoryStatusEx via ctypes.
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MemStatus()
        stat.dwLength = ctypes.sizeof(_MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
            return round(stat.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        pass

    return None


def _detect_gpu() -> Optional[str]:
    """
    Best-effort GPU name, or None. Uses `nvidia-smi` (no heavy imports). Returns
    the first GPU's name on success; None if no NVIDIA GPU / tool is present.
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        name = (out.stdout or "").strip().splitlines()
        if name and name[0].strip():
            return name[0].strip()
    except Exception:
        pass
    # nvidia-smi exists but the query failed — still signal "an NVIDIA GPU".
    return "NVIDIA GPU"


def _suggest_mode(ram_gb: Optional[float], has_gpu: bool) -> str:
    """
    Map detected hardware to a profile name. Conservative when RAM is unknown
    (suggest Lite) so we never push a heavy default onto a weak machine.
    """
    if ram_gb is None:
        return "lite"
    if has_gpu and ram_gb >= 14:
        return "power"
    if ram_gb >= 12:
        return "balanced"
    return "lite"


def detect_system() -> dict[str, Any]:
    """
    Inspect the machine and recommend a profile. Shape:
        {
          "ram_gb": 15.9 | None,
          "cpu_count": 8 | None,
          "gpu": "NVIDIA GeForce RTX 3060" | None,
          "has_gpu": true,
          "suggested_mode": "power",
          "current_mode": "lite",
          "profiles": { ...MODE_PROFILES... },
        }
    """
    ram_gb = _total_ram_gb()
    gpu = _detect_gpu()
    return {
        "ram_gb": ram_gb,
        "cpu_count": os.cpu_count(),
        "gpu": gpu,
        "has_gpu": gpu is not None,
        "suggested_mode": _suggest_mode(ram_gb, gpu is not None),
        "current_mode": config.active_mode(),
        "profiles": config.MODE_PROFILES,
    }
