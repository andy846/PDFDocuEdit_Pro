"""Peak memory counters without a new runtime dependency."""
from __future__ import annotations

import os


def peak_memory(process=None) -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        handle = wintypes.HANDLE(int(process._handle)) if process else kernel.GetCurrentProcess()
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        if query(handle, ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize
        return 0
    import resource
    import sys
    stats = resource.getrusage(resource.RUSAGE_CHILDREN if process else resource.RUSAGE_SELF)
    return int(stats.ru_maxrss * (1 if sys.platform == "darwin" else 1024))
