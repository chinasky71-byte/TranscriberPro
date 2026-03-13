"""
System resource monitoring
File: utils/resource_monitor.py
"""
import gc
import sys
import ctypes
import ctypes.util
import psutil
import logging
try:
    import pynvml
    NVML_AVAILABLE = True
except:
    NVML_AVAILABLE = False


def release_ram_to_os() -> None:
    """Forza il rilascio della RAM Python all'OS nel modo più aggressivo possibile.

    Sequenza:
    1. gc.collect() × 3 — raccoglie tutte e 3 le generazioni, inclusi cicli
       inter-generazionali che una singola passata non rompe.
    2. PyTorch CPU allocator reset — libera i pool di tensor allocati su CPU.
    3. OS-specific trim:
       - Win32: SetProcessWorkingSetSize + EmptyWorkingSet (pagina fuori tutto
         ciò che non è bloccato, Task Manager lo vede subito)
       - Linux/macOS: malloc_trim(0) restituisce heap libero al kernel.
    """
    # --- 1. Garbage collection completa (tutte le generazioni) ---
    for _ in range(3):
        gc.collect()

    # --- 2. OS-specific memory trim ---
    try:
        if sys.platform == 'win32':
            kernel32 = ctypes.windll.kernel32
            # SetProcessWorkingSetSize(-1, -1): rimuove limiti e trim al minimo
            kernel32.SetProcessWorkingSetSize(
                ctypes.c_void_p(-1),
                ctypes.c_size_t(-1),
                ctypes.c_size_t(-1),
            )
            # EmptyWorkingSet: svuota tutte le pagine non bloccate (più aggressivo)
            kernel32.EmptyWorkingSet(ctypes.c_void_p(-1))
        else:
            _libc_name = ctypes.util.find_library('c') or 'libc.so.6'
            _libc = ctypes.CDLL(_libc_name)
            _libc.malloc_trim.argtypes = [ctypes.c_size_t]
            _libc.malloc_trim.restype = ctypes.c_int
            _libc.malloc_trim(ctypes.c_size_t(0))
    except Exception:
        pass  # silenzioso — non critico


class ResourceMonitor:
    def __init__(self, max_ram_gb=30, max_vram_gb=12):
        self.logger = logging.getLogger(__name__)
        self.max_ram_gb = max_ram_gb
        self.max_vram_gb = max_vram_gb
        
        self.gpu_available = False
        if NVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self.gpu_available = True
            except:
                pass
    
    def check_resources(self):
        """
        Check if system resources are within limits
        Returns: (within_limits, message)
        """
        # Check RAM
        ram = psutil.virtual_memory()
        ram_used_gb = ram.used / (1024**3)
        
        if ram_used_gb > self.max_ram_gb:
            return False, f"RAM usage ({ram_used_gb:.1f} GB) exceeds limit ({self.max_ram_gb} GB)"
        
        # Check VRAM
        if self.gpu_available:
            try:
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
                vram_used_gb = mem_info.used / (1024**3)
                
                if vram_used_gb > self.max_vram_gb:
                    return False, f"VRAM usage ({vram_used_gb:.1f} GB) exceeds limit ({self.max_vram_gb} GB)"
            except:
                pass
        
        return True, "Resources within limits"
    
    def get_stats(self):
        """Get current resource statistics"""
        stats = {
            'cpu_percent': psutil.cpu_percent(interval=None),
            'ram_used_gb': psutil.virtual_memory().used / (1024**3),
            'ram_percent': psutil.virtual_memory().percent,
        }
        
        if self.gpu_available:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(self.gpu_handle)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
                
                stats['gpu_percent'] = util.gpu
                stats['vram_used_gb'] = mem_info.used / (1024**3)
                stats['vram_percent'] = (mem_info.used / mem_info.total) * 100
            except:
                stats['gpu_percent'] = 0
                stats['vram_used_gb'] = 0
                stats['vram_percent'] = 0
        else:
            stats['gpu_percent'] = 0
            stats['vram_used_gb'] = 0
            stats['vram_percent'] = 0
        
        return stats
    
    def __del__(self):
        if self.gpu_available:
            try:
                pynvml.nvmlShutdown()
            except:
                pass
