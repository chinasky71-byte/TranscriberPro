"""
Custom Widgets for Transcriber Pro
Include ResourceMonitor per monitoraggio risorse sistema
File: gui/widgets.py - FIXED: Barre allineate perfettamente
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QFrame
from PyQt6.QtCore import QTimer, Qt
import psutil
import time

from utils.translations import tr

try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False


class ResourceMonitor(QWidget):
    """Widget per monitoraggio risorse sistema (CPU, RAM, GPU, VRAM, Network)"""
    
    # Costanti per larghezze fisse (garantisce allineamento perfetto)
    LABEL_WIDTH = 75
    VALUE_WIDTH = 65
    
    def __init__(self):
        super().__init__()
        self.timer = None
        self.gpu_initialized = False
        self.gpu_handle = None
        
        # Network monitoring
        self.last_net_io = None
        self.last_update_time = None
        
        # Inizializza GPU monitoring se disponibile
        if NVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self.gpu_initialized = True
            except:
                self.gpu_initialized = False
        
        self.init_ui()
    
    def init_ui(self):
        """Inizializza interfaccia"""
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title = QLabel(tr('monitor_title'))
        title.setObjectName("resourceTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("separator")
        layout.addWidget(separator)
        
        # CPU
        cpu_layout = QHBoxLayout()
        cpu_layout.setSpacing(5)
        self.cpu_label = QLabel(tr('cpu_label'))
        self.cpu_label.setObjectName("metricLabel")
        self.cpu_label.setFixedWidth(self.LABEL_WIDTH)
        self.cpu_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setObjectName("cpuBar")
        self.cpu_bar.setMaximum(100)
        self.cpu_value_label = QLabel("0%")
        self.cpu_value_label.setObjectName("valueLabel")
        self.cpu_value_label.setFixedWidth(self.VALUE_WIDTH)
        self.cpu_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cpu_layout.addWidget(self.cpu_label)
        cpu_layout.addWidget(self.cpu_bar, 1)  # stretch factor = 1
        cpu_layout.addWidget(self.cpu_value_label)
        layout.addLayout(cpu_layout)
        
        # RAM
        ram_layout = QHBoxLayout()
        ram_layout.setSpacing(5)
        self.ram_label = QLabel(tr('ram_label'))
        self.ram_label.setObjectName("metricLabel")
        self.ram_label.setFixedWidth(self.LABEL_WIDTH)
        self.ram_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ram_bar = QProgressBar()
        self.ram_bar.setObjectName("ramBar")
        self.ram_bar.setMaximum(100)
        self.ram_value_label = QLabel("0%")
        self.ram_value_label.setObjectName("valueLabel")
        self.ram_value_label.setFixedWidth(self.VALUE_WIDTH)
        self.ram_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ram_layout.addWidget(self.ram_label)
        ram_layout.addWidget(self.ram_bar, 1)  # stretch factor = 1
        ram_layout.addWidget(self.ram_value_label)
        layout.addLayout(ram_layout)
        
        # GPU (solo se disponibile)
        if self.gpu_initialized:
            gpu_layout = QHBoxLayout()
            gpu_layout.setSpacing(5)
            self.gpu_label = QLabel(tr('gpu_label'))
            self.gpu_label.setObjectName("metricLabel")
            self.gpu_label.setFixedWidth(self.LABEL_WIDTH)
            self.gpu_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.gpu_bar = QProgressBar()
            self.gpu_bar.setObjectName("gpuBar")
            self.gpu_bar.setMaximum(100)
            self.gpu_value_label = QLabel("0%")
            self.gpu_value_label.setObjectName("valueLabel")
            self.gpu_value_label.setFixedWidth(self.VALUE_WIDTH)
            self.gpu_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            gpu_layout.addWidget(self.gpu_label)
            gpu_layout.addWidget(self.gpu_bar, 1)  # stretch factor = 1
            gpu_layout.addWidget(self.gpu_value_label)
            layout.addLayout(gpu_layout)
            
            # VRAM
            vram_layout = QHBoxLayout()
            vram_layout.setSpacing(5)
            self.vram_label = QLabel(tr('vram_label'))
            self.vram_label.setObjectName("metricLabel")
            self.vram_label.setFixedWidth(self.LABEL_WIDTH)
            self.vram_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.vram_bar = QProgressBar()
            self.vram_bar.setObjectName("vramBar")
            self.vram_bar.setMaximum(100)
            self.vram_value_label = QLabel("0 GB")
            self.vram_value_label.setObjectName("valueLabel")
            self.vram_value_label.setFixedWidth(self.VALUE_WIDTH)
            self.vram_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            vram_layout.addWidget(self.vram_label)
            vram_layout.addWidget(self.vram_bar, 1)  # stretch factor = 1
            vram_layout.addWidget(self.vram_value_label)
            layout.addLayout(vram_layout)
        
        # Separator per Network
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setObjectName("separator")
        layout.addWidget(separator2)
        
        # Network header
        net_label = QLabel(tr('network_label'))
        net_label.setObjectName("sectionLabel")
        net_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(net_label)
        
        # Download
        dl_layout = QHBoxLayout()
        dl_icon = QLabel("📥")
        dl_icon.setObjectName("netIcon")
        dl_icon.setFixedWidth(25)
        self.download_label = QLabel("0.0 KB/s")
        self.download_label.setObjectName("netSpeedLabel")
        dl_layout.addWidget(dl_icon)
        dl_layout.addWidget(self.download_label)
        dl_layout.addStretch()
        layout.addLayout(dl_layout)
        
        # Upload
        ul_layout = QHBoxLayout()
        ul_icon = QLabel("📤")
        ul_icon.setObjectName("netIcon")
        ul_icon.setFixedWidth(25)
        self.upload_label = QLabel("0.0 KB/s")
        self.upload_label.setObjectName("netSpeedLabel")
        ul_layout.addWidget(ul_icon)
        ul_layout.addWidget(self.upload_label)
        ul_layout.addStretch()
        layout.addLayout(ul_layout)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Apply styles
        self.apply_styles()
    
    def apply_styles(self):
        """Applica stili moderni"""
        self.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
            
            QLabel#resourceTitle {
                color: #ffffff;
                font-size: 11pt;
                font-weight: bold;
                padding: 5px;
            }
            
            QLabel#sectionLabel {
                color: #ffffff;
                font-size: 10pt;
                font-weight: bold;
                padding: 3px;
            }
            
            QLabel#metricLabel {
                color: #cccccc;
                font-size: 9pt;
                font-weight: bold;
            }
            
            QLabel#valueLabel {
                color: #ffffff;
                font-size: 9pt;
                font-family: 'Consolas', monospace;
            }
            
            QLabel#netIcon {
                font-size: 12pt;
            }
            
            QLabel#netSpeedLabel {
                color: #ffffff;
                font-size: 10pt;
                font-family: 'Consolas', monospace;
                font-weight: bold;
            }
            
            QFrame#separator {
                background-color: rgba(255, 255, 255, 0.1);
                max-height: 1px;
            }
            
            QProgressBar {
                background-color: rgba(40, 40, 40, 180);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                height: 20px;
                text-align: center;
            }
            
            QProgressBar::chunk {
                border-radius: 3px;
            }
            
            QProgressBar#cpuBar::chunk {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(0, 120, 212, 180),
                    stop: 1 rgba(0, 180, 255, 200)
                );
            }
            
            QProgressBar#ramBar::chunk {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(16, 124, 16, 180),
                    stop: 1 rgba(50, 200, 50, 200)
                );
            }
            
            QProgressBar#gpuBar::chunk {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(156, 39, 176, 180),
                    stop: 1 rgba(200, 100, 255, 200)
                );
            }
            
            QProgressBar#vramBar::chunk {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(255, 152, 0, 180),
                    stop: 1 rgba(255, 200, 100, 200)
                );
            }
        """)
    
    def start_monitoring(self):
        """Avvia monitoraggio"""
        if not self.timer:
            self.timer = QTimer()
            self.timer.timeout.connect(self.update_resources)
            self.last_net_io = psutil.net_io_counters()
            self.last_update_time = time.time()
            self.timer.start(1000)  # Aggiorna ogni secondo
    
    def stop_monitoring(self):
        """Ferma monitoraggio"""
        if self.timer:
            self.timer.stop()
            self.timer = None
    
    def update_resources(self):
        """Aggiorna valori risorse"""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_bar.setValue(int(cpu_percent))
            self.cpu_value_label.setText(f"{cpu_percent:.1f}%")
            
            # RAM
            ram = psutil.virtual_memory()
            ram_percent = ram.percent
            self.ram_bar.setValue(int(ram_percent))
            self.ram_value_label.setText(f"{ram_percent:.1f}%")
            
            # GPU e VRAM (se disponibile)
            if self.gpu_initialized and self.gpu_handle:
                try:
                    # GPU utilization
                    gpu_util = pynvml.nvmlDeviceGetUtilizationRates(self.gpu_handle)
                    gpu_percent = gpu_util.gpu
                    self.gpu_bar.setValue(int(gpu_percent))
                    self.gpu_value_label.setText(f"{gpu_percent}%")
                    
                    # VRAM
                    vram_info = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
                    vram_percent = (vram_info.used / vram_info.total) * 100
                    self.vram_bar.setValue(int(vram_percent))
                    vram_used_gb = vram_info.used / (1024**3)
                    vram_total_gb = vram_info.total / (1024**3)
                    self.vram_value_label.setText(f"{vram_used_gb:.1f}GB")
                    
                except Exception as e:
                    pass
            
            # Network speed
            self._update_network_speed()
        
        except Exception as e:
            pass
    
    def _update_network_speed(self):
        """Aggiorna velocità rete"""
        try:
            current_net_io = psutil.net_io_counters()
            current_time = time.time()
            
            if self.last_net_io is not None and self.last_update_time is not None:
                # Calcola tempo trascorso
                time_delta = current_time - self.last_update_time
                
                if time_delta > 0:
                    # Calcola bytes trasferiti
                    bytes_sent = current_net_io.bytes_sent - self.last_net_io.bytes_sent
                    bytes_recv = current_net_io.bytes_recv - self.last_net_io.bytes_recv
                    
                    # Converti in KB/s o MB/s
                    upload_speed_kbs = (bytes_sent / time_delta) / 1024
                    download_speed_kbs = (bytes_recv / time_delta) / 1024
                    
                    # Format e aggiorna labels
                    if download_speed_kbs >= 1024:
                        self.download_label.setText(f"{download_speed_kbs / 1024:.2f} MB/s")
                        self.download_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                    elif download_speed_kbs > 0.1:
                        self.download_label.setText(f"{download_speed_kbs:.1f} KB/s")
                        self.download_label.setStyleSheet("color: #8BC34A; font-weight: bold;")
                    else:
                        self.download_label.setText("0.0 KB/s")
                        self.download_label.setStyleSheet("color: #888888;")
                    
                    if upload_speed_kbs >= 1024:
                        self.upload_label.setText(f"{upload_speed_kbs / 1024:.2f} MB/s")
                        self.upload_label.setStyleSheet("color: #FF9800; font-weight: bold;")
                    elif upload_speed_kbs > 0.1:
                        self.upload_label.setText(f"{upload_speed_kbs:.1f} KB/s")
                        self.upload_label.setStyleSheet("color: #FFC107; font-weight: bold;")
                    else:
                        self.upload_label.setText("0.0 KB/s")
                        self.upload_label.setStyleSheet("color: #888888;")
            
            # Aggiorna valori per prossimo ciclo
            self.last_net_io = current_net_io
            self.last_update_time = current_time
            
        except Exception as e:
            pass
    
    def __del__(self):
        """Cleanup"""
        if self.gpu_initialized:
            try:
                pynvml.nvmlShutdown()
            except:
                pass


# Alias per compatibilità
ResourceMonitorWidget = ResourceMonitor
