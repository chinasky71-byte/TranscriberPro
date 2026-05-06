"""SVG icon renderer per Transcriber Pro.
Paths estratti da interface revamp/app-v2.jsx (viewBox 0 0 24 24, stroke-width 1.5).
"""
from __future__ import annotations
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter

try:
    from PyQt6.QtSvg import QSvgRenderer
    _SVG_AVAILABLE = True
except ImportError:
    _SVG_AVAILABLE = False

# Contenuto SVG per ogni icona (elementi interni, viewBox 0 0 24 24).
# "currentColor" nelle sub-path fill viene sostituito con il colore passato.
_SVG_CONTENT: dict[str, str] = {
    'play':      '<path d="M7 5l12 7-12 7V5z"/>',
    'stop':      '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    'plus':      '<path d="M12 5v14M5 12h14"/>',
    'folder':    '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>',
    'trash':     '<path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-7 0v13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V7"/>',
    'settings':  '<path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    'globe':     '<path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0 0c2.5-2.5 4-6 4-9s-1.5-6.5-4-9m0 18c-2.5-2.5-4-6-4-9s1.5-6.5 4-9M3 12h18"/>',
    'target':    '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/>',
    'wrench':    '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.7 2.7-2-2 2.7-2.7z"/>',
    'upload':    '<path d="M12 19V5m0 0l-6 6m6-6l6 6"/>',
    'download':  '<path d="M12 5v14m0 0l-6-6m6 6l6-6"/>',
    'film':      '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 8h18M3 16h18M8 4v16M16 4v16"/>',
    'search':    '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    'power':     '<path d="M12 3v8M5.6 6.6a8 8 0 1 0 12.8 0"/>',
    'cpu':       '<rect x="5" y="5" width="14" height="14" rx="1.5"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>',
    'chip':      '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/>',
    'gpu':       '<rect x="2" y="6" width="20" height="12" rx="1.5"/><circle cx="8" cy="12" r="2.5"/><circle cx="16" cy="12" r="2.5"/>',
    'hardDrive': '<path d="M3 12h18"/><path d="M5 12V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v6M5 12v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/><circle cx="7" cy="16" r="0.5" fill="currentColor"/>',
    'arrowDown': '<path d="M12 5v14m-6-6l6 6 6-6"/>',
    'arrowUp':   '<path d="M12 19V5m6 6l-6-6-6 6"/>',
    'check':     '<path d="M5 12l4 4L19 7"/>',
    'x':         '<path d="M6 6l12 12M18 6L6 18"/>',
    'chevDown':  '<path d="M6 9l6 6 6-6"/>',
    'chevRight': '<path d="M9 6l6 6-6 6"/>',
    'list':      '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    'clock':     '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'alert':     '<path d="M12 9v4m0 4h.01M10.3 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z"/>',
    'sparkle':   '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 17l.9 2.1L22 20l-2.1.9L19 23l-.9-2.1L16 20l2.1-.9L19 17z"/>',
    'mic':       '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8"/>',
    'language':  '<path d="M5 8h12M9 4v4M11 18l4-9 4 9M12 16h6M3 20s2-1 3-3M7 4l3 3"/>',
    'caption':   '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 11h2M7 15h4M13 11h4M13 15h2"/>',
    'history':   '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
    'external':  '<path d="M14 4h6v6M10 14L20 4M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6"/>',
    'cloud':     '<path d="M7 18a5 5 0 1 1 .8-9.94 6 6 0 0 1 11.4 2.5A4.5 4.5 0 0 1 18 18z"/>',
    'female':    '<circle cx="12" cy="9" r="5"/><path d="M12 14v7M9 18h6"/>',
    'volume':    '<path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14"/>',
}

_icon_cache: dict[tuple, QIcon] = {}


def svg_icon(name: str, size: int = 16, color: str = '#9095a0') -> QIcon:
    """Renderizza un'icona SVG come QIcon.

    Args:
        name:  chiave in _SVG_CONTENT (es. 'play', 'settings', 'mic')
        size:  dimensione in pixel (quadrata)
        color: colore stroke/fill in formato HEX
    """
    key = (name, size, color)
    if key in _icon_cache:
        return _icon_cache[key]

    if not _SVG_AVAILABLE or name not in _SVG_CONTENT:
        icon = QIcon()
        _icon_cache[key] = icon
        return icon

    content = _SVG_CONTENT[name].replace('currentColor', color)
    svg_str = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
        f'{content}'
        f'</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg_str.encode('utf-8')))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    icon = QIcon(pixmap)
    _icon_cache[key] = icon
    return icon
