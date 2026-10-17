"""
Custom Widgets for Transcriber Pro
Include ResourceMonitor per monitoraggio risorse sistema
File: gui/widgets.py - FIXED: Barre allineate perfettamente
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QFrame, QSizePolicy
from PyQt6.QtCore import QTimer, Qt, QSize
import psutil
import time

from utils.translations import tr
from gui.icons import svg_icon
from gui.design_tokens import T

try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False


class ElideLabel(QLabel):
    """QLabel che elide il testo quando lo spazio è insufficiente invece di imporre un minimum width.

    Sovrascrive minimumSizeHint() → (0, h) così il layout può rimpicciolire liberamente.
    Sovrascrive sizeHint() → larghezza del testo completo così il layout espande quando ha spazio.
    In resizeEvent applica elidedText() al testo corrente.
    """

    def __init__(self, text: str = '', parent=None, elide_mode=Qt.TextElideMode.ElideRight):
        super().__init__(parent)
        self._full_text = text
        self._elide_mode = elide_mode
        super().setText(text)

    def setText(self, text: str):
        self._full_text = text
        self._apply_elision()

    def sizeHint(self) -> QSize:
        h = super().sizeHint().height()
        w = self.fontMetrics().horizontalAdvance(self._full_text)
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self):
        available = self.width()
        if available <= 0:
            super().setText(self._full_text)
            return
        elided = self.fontMetrics().elidedText(self._full_text, self._elide_mode, available)
        super().setText(elided)


class ResourceMonitor(QWidget):
    """Widget per monitoraggio risorse sistema (CPU, RAM, GPU, VRAM, Network)"""
    
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
        # Nessun minimum width imposto: il pannello può essere stretto liberamente
        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header: titolo + uptime — ElideLabel per non imporre minimum width
        hdr = QHBoxLayout()
        title = ElideLabel(tr('monitor_title'))
        title.setObjectName("resourceTitle")
        self._uptime_label = ElideLabel("UPTIME  00h 00m 00s")
        self._uptime_label.setObjectName("uptimeLabel")
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self._uptime_label)
        layout.addLayout(hdr)

        # Riga 1: CPU | RAM
        cpu_card, self.cpu_value_label, self.cpu_bar = self._make_metric_card(
            "CPU", "cpuBar", T.accent, 'cpu')
        ram_card, self.ram_value_label, self.ram_bar = self._make_metric_card(
            "RAM", "ramBar", T.success, 'chip')
        row0 = QHBoxLayout()
        row0.setSpacing(8)
        row0.addWidget(cpu_card)
        row0.addWidget(ram_card)
        layout.addLayout(row0)

        # Riga 2: GPU | VRAM (solo se disponibile)
        if self.gpu_initialized:
            gpu_card, self.gpu_value_label, self.gpu_bar = self._make_metric_card(
                "GPU", "gpuBar", T.purple, 'gpu')
            vram_card, self.vram_value_label, self.vram_bar = self._make_metric_card(
                "VRAM", "vramBar", T.warn, 'hardDrive')
            row1 = QHBoxLayout()
            row1.setSpacing(8)
            row1.addWidget(gpu_card)
            row1.addWidget(vram_card)
            layout.addLayout(row1)

        # Riga rete: Download | Upload
        dl_card, self.download_label = self._make_net_card('arrowDown', T.accent, "Download")
        ul_card, self.upload_label   = self._make_net_card('arrowUp',   T.warn, "Upload")
        row_net = QHBoxLayout()
        row_net.setSpacing(8)
        row_net.addWidget(dl_card)
        row_net.addWidget(ul_card)
        layout.addLayout(row_net)

        layout.addStretch()

        # Uptime timer
        self._uptime_seconds = 0
        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._tick_uptime)
        self._uptime_timer.start(1000)
    
    def apply_styles(self):
        pass  # Stili gestiti da theme.qss

    # ------------------------------------------------------------------
    # Metric card helpers
    # ------------------------------------------------------------------

    def _make_metric_card(self, name: str, bar_id: str, color: str, icon: str = ''):
        card = QFrame()
        card.setObjectName("metricCard")
        card.setMinimumWidth(0)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(5)
        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(svg_icon(icon, 13, color).pixmap(13, 13))
            icon_lbl.setFixedSize(13, 13)
            top.addWidget(icon_lbl)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("metricName")
        name_lbl.setMinimumWidth(0)
        # ElideLabel e NON QLabel: il valore cambia durante l'elaborazione ("5.0%" -> "100.0%", "9.7GB" ->
        # "10.66GB") e una QLabel semplice ha minimumSizeHint = larghezza del testo: allargava il minimo del
        # pannello della locandina e lo splitter ridistribuiva le colonne (la locandina cambiava larghezza,
        # il nome file sotto si ri-elideva). v. feedback_qlabel_resize_gotcha.
        val_lbl = ElideLabel("–")
        val_lbl.setObjectName("metricValue")
        val_lbl.setMinimumWidth(0)
        top.addWidget(name_lbl)
        top.addStretch()
        top.addWidget(val_lbl)
        lay.addLayout(top)

        bar = QProgressBar()
        bar.setObjectName(bar_id)
        bar.setMaximum(100)
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setStyleSheet(
            f"QProgressBar {{ background: {T.bg_3}; border: none; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
        )
        lay.addWidget(bar)

        return card, val_lbl, bar

    def _make_net_card(self, icon: str, icon_color: str, name: str):
        card = QFrame()
        card.setObjectName("netCard")
        card.setMinimumWidth(0)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setObjectName("netIcon")
        icon_lbl.setPixmap(svg_icon(icon, 14, icon_color).pixmap(14, 14))
        icon_lbl.setFixedSize(14, 14)
        name_lbl = ElideLabel(name)
        name_lbl.setObjectName("metricName")
        val_lbl = ElideLabel("0.0 KB/s")
        val_lbl.setObjectName("netSpeedLabel")

        lay.addWidget(icon_lbl)
        lay.addWidget(name_lbl)
        lay.addStretch()
        lay.addWidget(val_lbl)

        return card, val_lbl

    @staticmethod
    def _set_speed_color(label, color):
        """Colore del valore di velocita' (il tema fissa l'objectName: serve override locale)."""
        label.setStyleSheet(f"color: {color};")

    def _tick_uptime(self):
        self._uptime_seconds += 1
        h, r = divmod(self._uptime_seconds, 3600)
        m, s = divmod(r, 60)
        self._uptime_label.setText(f"UPTIME  {h:02d}h {m:02d}m {s:02d}s")
    
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
                        self._set_speed_color(self.download_label, T.success)
                    elif download_speed_kbs > 0.1:
                        self.download_label.setText(f"{download_speed_kbs:.1f} KB/s")
                        self._set_speed_color(self.download_label, T.success)
                    else:
                        self.download_label.setText("0.0 KB/s")
                        self._set_speed_color(self.download_label, T.fg_4)

                    if upload_speed_kbs >= 1024:
                        self.upload_label.setText(f"{upload_speed_kbs / 1024:.2f} MB/s")
                        self._set_speed_color(self.upload_label, T.warn)
                    elif upload_speed_kbs > 0.1:
                        self.upload_label.setText(f"{upload_speed_kbs:.1f} KB/s")
                        self._set_speed_color(self.upload_label, T.warn)
                    else:
                        self.upload_label.setText("0.0 KB/s")
                        self._set_speed_color(self.upload_label, T.fg_4)
            
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
