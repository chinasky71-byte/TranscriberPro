# -*- coding: utf-8 -*-
"""Lingua dell'interfaccia (senza Qt). La scelta dell'utente vale sempre; con «auto» la pagina segue la lingua del browser e il
server (che scrive i log) quella del sistema, come fa la GUI Qt con QLocale."""
import os
from typing import Optional


def _from_tag(tag: str) -> Optional[str]:
    tag = (tag or '').strip().lower()
    return 'it' if tag.startswith('it') else ('en' if tag else None)


def system_language() -> str:
    """'it' se il sistema e' in italiano, altrimenti 'en'. Windows: lingua dell'interfaccia utente; altrove: variabili LANG."""
    if os.name == 'nt':
        try:
            import ctypes
            return 'it' if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3ff) == 0x10 else 'en'
        except Exception:
            pass
    for var in ('LC_ALL', 'LC_MESSAGES', 'LANGUAGE', 'LANG'):
        v = _from_tag(os.environ.get(var, ''))
        if v:
            return v
    return 'en'


def resolve(pref: str, accept_language: str = '') -> str:
    """'it' | 'en': la preferenza se e' una lingua nostra, altrimenti Accept-Language (se dato), altrimenti la lingua del sistema."""
    if pref in ('it', 'en'):
        return pref
    return _from_tag(accept_language) or system_language()


def apply_to_process(config) -> str:
    """Imposta la lingua dei testi scritti dal server (log, messaggi del motore) secondo la configurazione."""
    from utils.translations import get_translations
    lang = resolve(config.get('language', 'auto') if config is not None else 'auto')
    get_translations().set_language(lang)
    return lang
