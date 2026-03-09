"""
Splash Screen - Layout ottimizzato senza sovrapposizioni
File: gui/splash_screen.py
VERSIONE: 1.0.2
"""
from PyQt6.QtWidgets import QSplashScreen, QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont

class SplashScreen(QSplashScreen):
    def __init__(self):
        # Crea un pixmap con sfondo personalizzato
        pixmap = QPixmap(600, 400)
        pixmap.fill(QColor(45, 45, 48))  # Sfondo scuro
        
        # Disegna il contenuto
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Titolo in alto (senza sovrapposizioni)
        painter.setPen(QColor(255, 255, 255))
        title_font = QFont("Arial", 32, QFont.Weight.Bold)
        painter.setFont(title_font)
        title_rect = pixmap.rect().adjusted(0, 30, 0, -300)  # Solo parte alta
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop, 
                        "Transcriber Pro")
        
        # Logo/Icona al centro (spostato più in alto)
        icon_font = QFont("Arial", 80)  # Icona più grande e visibile
        painter.setFont(icon_font)
        painter.setPen(QColor(100, 150, 255))
        icon_rect = pixmap.rect().adjusted(0, -30, 0, -80)  # Centrato ma più in alto
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, "🎬")
        
        # Sottotitolo sotto l'icona
        subtitle_font = QFont("Arial", 14)
        painter.setFont(subtitle_font)
        painter.setPen(QColor(200, 200, 200))
        subtitle_rect = pixmap.rect().adjusted(0, 120, 0, 0)  # Posizionato sotto l'icona
        painter.drawText(subtitle_rect, Qt.AlignmentFlag.AlignCenter, 
                        "AI-Powered Video Transcription")
        
        # ✅ VERSIONE AGGIORNATA: 1.0.2
        version_font = QFont("Arial", 10)
        painter.setFont(version_font)
        painter.setPen(QColor(150, 150, 150))
        painter.drawText(pixmap.rect().adjusted(0, 0, -10, -10), 
                        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, 
                        "v1.0.3.1")
        
        # Credits in basso a sinistra (aggiornato con NLLB e TMDB)
        painter.drawText(pixmap.rect().adjusted(10, 0, 0, -10), 
                        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, 
                        "Powered by Whisper • NLLB • TMDB")
        
        painter.end()
        
        # Inizializza lo splash screen
        super().__init__(pixmap)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        
        # Messaggio di caricamento
        self.showMessage(
            "Inizializzazione...",
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
            QColor(255, 255, 255)
        )
    
    def update_message(self, message):
        """Aggiorna il messaggio dello splash screen"""
        self.showMessage(
            message,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
            QColor(255, 255, 255)
        )
        QApplication.processEvents()


def show_splash(duration=2500):
    """Mostra lo splash screen per una durata specificata"""
    splash = SplashScreen()
    splash.show()
    
    # Simula caricamento con messaggi
    messages = [
        ("Inizializzazione...", 0),
        ("Caricamento librerie AI...", 500),
        ("Verifica GPU...", 1000),
        ("Pronto!", 1500)
    ]
    
    for message, delay in messages:
        QTimer.singleShot(delay, lambda m=message: splash.update_message(m))
    
    # Chiudi lo splash dopo la durata specificata
    QTimer.singleShot(duration, splash.close)
    
    return splash
