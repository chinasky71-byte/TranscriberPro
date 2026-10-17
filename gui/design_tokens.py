"""Design tokens di Transcriber Pro: UNICA fonte dei colori, spaziature, raggi e font.

Uso:
    from gui.design_tokens import T
    label.setStyleSheet(f"color: {T.success};")      # QSS dinamico
    QColor(T.bg_2)                                   # QColor/QPainter
    T.rgba(T.accent, 0.15)                           # 'rgba(60, 193, 224, 0.15)'

I valori sono ESATTAMENTE quelli usati dal tema (gui/theme.qss) e dai widget
al momento della migrazione (v1.31, fase pixel-neutrale). `gui/theme.qss.tpl`
usa i segnaposto {{nome}} = attributi di T (vedi gui/theme.py).

Gruppi:
  * palette principale (bg_0..bg_4, fg_0..fg_4, line, accent, success, danger, warn, purple);
  * stati derivati (hover/press, on_accent), alpha pre-calcolate (accent_a15 ...);
  * colori "legacy" ereditati da dialoghi non ancora uniformati (grigi/blu/verdi
    material, ecc.): tenuti per sostituzione esatta, da riallineare in una fase
    successiva (non pixel-neutrale) alla palette principale;
  * spaziature (SP_*), raggi (R_*), font (FONT_*), dimensioni testo (FS_*).
"""
from __future__ import annotations


def rgba(color, alpha) -> str:
    """'#rrggbb' + alpha (float 0..1 o int 0..255) -> 'rgba(r, g, b, a)'."""
    c = str(color).lstrip('#')
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def hex_to_rgb(color) -> tuple:
    c = str(color).lstrip('#')
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


class T:
    # ------------------------------------------------------------------
    # Palette principale (dark slate + accent ciano)
    # ------------------------------------------------------------------
    bg_0 = '#1f2126'      # sfondo finestra
    bg_1 = '#25272d'      # pannelli, tile, pill
    bg_2 = '#2c2e36'      # card, tooltip, input
    bg_3 = '#353841'      # hover, barre di fondo
    bg_4 = '#404450'      # pressed / bordi forti
    fg_0 = '#f5f6f8'      # testo primario
    fg_1 = '#d1d5db'      # testo secondario
    fg_2 = '#9095a0'      # testo mutato
    fg_3 = '#6a6f7a'      # testo debole / icone / disabilitato
    fg_4 = '#6b7280'      # grigio slate (in coda, sottotitoli, uptime)
    fg_row = '#e8eaf0'    # testo riga lista (file_row_delegate)
    line = '#3a3d47'      # bordi

    accent = '#3cc1e0'    # ciano brand
    accent_hover = '#54cce8'
    accent_press = '#2faec9'
    on_accent = '#0d1418'  # testo su sfondo accent
    success = '#3fcf8e'
    danger = '#ef5a5a'
    danger_hover = '#f37272'
    danger_press = '#d54545'
    warn = '#f5b450'
    purple = '#a855f7'    # barra GPU
    white = '#ffffff'

    # ------------------------------------------------------------------
    # Alpha pre-calcolate (stringhe QSS 'rgba(...)', stessa forma del tema)
    # ------------------------------------------------------------------
    accent_a12 = 'rgba(60, 193, 224, 0.12)'
    accent_a14 = 'rgba(60, 193, 224, 0.14)'
    accent_a15 = 'rgba(60, 193, 224, 0.15)'
    accent_a16 = 'rgba(60, 193, 224, 0.16)'
    accent_a18 = 'rgba(60, 193, 224, 0.18)'
    accent_a30 = 'rgba(60, 193, 224, 0.30)'
    accent_a35 = 'rgba(60, 193, 224, 0.35)'
    accent_a45 = 'rgba(60, 193, 224, 0.45)'
    white_a03 = 'rgba(255,255,255,0.03)'
    # nuove (solo per i ruoli "badge": tinta 15% + bordo 35% come overlayLangPill)
    success_a15 = 'rgba(63, 207, 142, 0.15)'
    success_a35 = 'rgba(63, 207, 142, 0.35)'
    danger_a15 = 'rgba(239, 90, 90, 0.15)'
    danger_a35 = 'rgba(239, 90, 90, 0.35)'
    warn_a15 = 'rgba(245, 180, 80, 0.15)'
    warn_a35 = 'rgba(245, 180, 80, 0.35)'
    purple_a15 = 'rgba(168, 85, 247, 0.15)'
    purple_a35 = 'rgba(168, 85, 247, 0.35)'

    # ------------------------------------------------------------------
    # Colori "sezione" di translation_model_dialog (bordo delle card)
    # ------------------------------------------------------------------
    section_neutral = line
    section_green = success
    section_blue = accent
    section_orange = warn
    section_purple = '#9b6bc7'
    section_red_orange = '#ef8a5a'
    purple_title = '#b78ee0'      # titolo della sezione viola

    # ------------------------------------------------------------------
    # LEGACY: valori letterali dei dialoghi non ancora allineati alla palette.
    # Esistono per sostituire 1:1 i #rrggbb scritti a mano senza cambiare un pixel.
    # ------------------------------------------------------------------
    legacy_grey_888 = '#888888'     # testo mutato "vecchio" (diverso da fg_2!)
    legacy_grey_aaa = '#aaaaaa'
    legacy_grey_b0 = '#b0b0b0'
    legacy_grey_ccc = '#cccccc'
    legacy_grey_d0 = '#d0d0d0'
    legacy_black = '#000000'
    legacy_bg_2a = '#2a2a2a'        # popup combo scanner
    legacy_bg_1e = '#1e1e1e'        # profile_dialog
    legacy_bg_dialog = '#1e1e2e'    # ocr_review / sync_dialog
    legacy_bg_ocr = '#0f0f19'
    legacy_on_accent_ocr = '#10222a'
    legacy_accent_ocr_hover = '#54cfe9'
    legacy_red_soft = '#e07070'     # errori testo (general_settings)
    legacy_red_deep = '#d32f2f'
    legacy_pink = '#e94560'         # badge/giorni scanner
    legacy_mat_green = '#4caf50'    # Material green 500 (connesso)
    legacy_mat_green_deep = '#2e7d32'
    legacy_mat_red = '#f44336'      # Material red 500 (disconnesso)
    legacy_mat_amber = '#ffc107'
    legacy_orange_deep = '#e65100'
    legacy_orange_hover = '#fb8c00'
    legacy_yellow = '#ffcc00'
    legacy_orange_soft = '#ffaa44'
    legacy_blue_link = '#82aaff'
    legacy_blue_soft = '#88ccff'
    legacy_green_soft = '#88ff88'
    legacy_violet = '#6a0dad'
    legacy_violet_hover = '#8b2fc9'
    # nomi colore CSS usati dallo stato di translation_model_dialog
    # (volutamente NON mappati a success/warn/danger: cambierebbe il colore)
    css_green = 'green'
    css_orange = 'orange'
    css_red = 'red'
    css_grey_555 = '#555'

    # tuple RGBA per QColor(*...) (RoundedLabel poster)
    poster_bg = (32, 32, 32, 180)
    poster_border = (255, 255, 255, 26)

    # colori QColor del file_row_delegate / log HTML (mappe di stato)
    STATUS_COLORS = {
        'queued': fg_4,
        'processing': accent,
        'completed': success,
        'failed': danger,
    }
    LOG_COLORS = {
        'success': success,
        'danger': danger,
        'warn': warn,
        'info': accent,
        'muted': fg_2,
    }

    # ------------------------------------------------------------------
    # Spaziature, raggi, dimensioni (valori gia' ricorrenti nel tema)
    # ------------------------------------------------------------------
    SP_XS = 4
    SP_SM = 6
    SP_MD = 8
    SP_LG = 12
    SP_XL = 14
    R_XS = 2
    R_SM = 4
    R_MD = 6
    R_LG = 8
    R_XL = 10
    R_PANEL = 14
    R_PILL = 999

    FONT_SANS = '"Inter Tight", "Segoe UI", sans-serif'
    FONT_MONO = "'JetBrains Mono', monospace"
    FONT_MONO_BASE = '"JetBrains Mono", "Consolas", monospace'
    FAMILY_SANS = 'Inter Tight'
    FAMILY_MONO = 'JetBrains Mono'
    FS_BASE_PT = 10
    FS_CAPTION = 11   # px
    FS_BODY = 12      # px
    FS_LEAD = 13      # px
    FS_H2 = 16        # px
    FS_H1 = 20        # px

    rgba = staticmethod(rgba)


# Colori per i ruoli semantici (QLabel[role="..."], vedi theme.qss.tpl sezione Ruoli).
ROLE_COLORS = {
    'primary': T.fg_0,
    'text': T.fg_1,
    'muted': T.fg_2,
    'subtle': T.fg_3,
    'dim': T.fg_4,
    'accent': T.accent,
    'success': T.success,
    'danger': T.danger,
    'warn': T.warn,
    'purple': T.purple,
}

# Toni dei badge/dot (stesso insieme dei colori di stato)
TONES = ('accent', 'success', 'danger', 'warn', 'purple')


def token_map() -> dict:
    """Tutti i token stringa di T come {nome: valore} (per il rendering del template)."""
    out = {}
    for k, v in vars(T).items():
        if k.startswith('_') or not isinstance(v, str):
            continue
        out[k] = v
    return out
