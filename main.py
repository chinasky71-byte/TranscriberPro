"""
Main Application Entry Point
File: main.py
"""
import sys
import warnings
import logging
from pathlib import Path

warnings.filterwarnings("ignore", message="In 2.9, this function's implementation")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from gui.splash_screen import show_splash
from gui.main_window import MainWindow
from utils.logger import setup_logger

def main():
    """Main application entry point"""
    
    # Configura logging
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info("Transcriber Pro - Avvio applicazione")
    logger.info("=" * 60)
    
    # Crea applicazione Qt
    app = QApplication(sys.argv)
    app.setApplicationName("Transcriber Pro")
    app.setOrganizationName("TranscriberPro")
    
    # High DPI scaling è abilitato di default in PyQt6
    # Non serve più impostare AA_EnableHighDpiScaling
    
    # Mostra splash screen
    splash = show_splash(duration=2500)
    
    # Crea finestra principale (ma non mostrarla subito)
    main_window = MainWindow()
    
    # Funzione per mostrare la finestra principale dopo lo splash
    def show_main_window():
        main_window.show()
        if splash:
            splash.close()
    
    # Mostra la finestra principale dopo 2.5 secondi (quando lo splash si chiude)
    QTimer.singleShot(2500, show_main_window)
    
    logger.info("Interfaccia grafica inizializzata")
    
    # Avvia event loop
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
