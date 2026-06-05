"""
Splash Screen — progress bar reale collegata agli step di avvio.
File: gui/splash_screen.py

La versione viene passata da main.py (APP_VERSION) invece di essere
hardcoded qui. Il progresso viene aggiornato tramite update_progress()
chiamato da main.py per ogni step di inizializzazione.
"""
from PyQt6.QtWidgets import QSplashScreen, QApplication
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont

from utils.translations import tr

# Layout costanti (coordinate px su pixmap 600×400)
_BAR_Y      = 328   # y della progress bar
_BAR_H      = 7     # altezza progress bar
_MSG_Y      = 300   # y riga messaggio
_MSG_H      = 22    # altezza area messaggio

_ACCENT     = QColor(0x3c, 0xc1, 0xe0)   # ciano brand
_BAR_BG     = QColor(62, 62, 66)
_MSG_COLOR  = QColor(175, 178, 188)


class SplashScreen(QSplashScreen):

    def __init__(self, version: str = ""):
        pixmap = QPixmap(600, 400)
        pixmap.fill(QColor(45, 45, 48))

        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Titolo
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Arial", 32, QFont.Weight.Bold))
        p.drawText(
            pixmap.rect().adjusted(0, 30, 0, -300),
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop,
            "Transcriber Pro",
        )

        # Icona
        p.setFont(QFont("Arial", 80))
        p.setPen(QColor(100, 150, 255))
        p.drawText(
            pixmap.rect().adjusted(0, -30, 0, -80),
            Qt.AlignmentFlag.AlignCenter,
            "\U0001f3ac",
        )

        # Sottotitolo
        p.setFont(QFont("Arial", 14))
        p.setPen(QColor(200, 200, 200))
        p.drawText(
            pixmap.rect().adjusted(0, 120, 0, 0),
            Qt.AlignmentFlag.AlignCenter,
            tr('splash_subtitle'),
        )

        # Versione (letta da main.py via parametro)
        ver_str = f"v{version}" if version and not version.startswith('v') else version
        p.setFont(QFont("Arial", 10))
        p.setPen(QColor(140, 140, 148))
        p.drawText(
            pixmap.rect().adjusted(0, 0, -10, -10),
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
            ver_str,
        )

        # Credits
        p.drawText(
            pixmap.rect().adjusted(10, 0, 0, -10),
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
            tr('splash_credits'),
        )

        p.end()

        super().__init__(pixmap)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        self._pct: int = 0
        self._message: str = tr('init_message')

    # ── API pubblica ──────────────────────────────────────────────────────────

    def update_progress(self, pct: int, message: str = "") -> None:
        """Aggiorna progress bar e messaggio; ridisegna immediatamente."""
        self._pct     = max(0, min(100, pct))
        self._message = message
        self.repaint()
        QApplication.processEvents()

    # ── Rendering dinamico ────────────────────────────────────────────────────

    def drawContents(self, painter: QPainter) -> None:
        """Disegna progress bar e messaggio sovrapposti al pixmap statico."""
        w = self.width()

        # Messaggio
        if self._message:
            painter.setFont(QFont("Arial", 10))
            painter.setPen(_MSG_COLOR)
            painter.drawText(
                QRect(20, _MSG_Y, w - 40, _MSG_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self._message,
            )

        # Sfondo barra
        painter.fillRect(0, _BAR_Y, w, _BAR_H, _BAR_BG)

        # Riempimento barra
        filled = int(w * self._pct / 100)
        if filled > 0:
            painter.fillRect(0, _BAR_Y, filled, _BAR_H, _ACCENT)
