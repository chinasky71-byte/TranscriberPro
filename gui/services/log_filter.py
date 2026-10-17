# -*- coding: utf-8 -*-
"""
LogFilter: parte DECISIONALE di MainWindow.log_message, senza Qt.

Dato un messaggio dice cosa farne (scartarlo, aggiornare una barra, accodarlo) e
quale nome di modello di trascrizione contiene; la vista esegue la scrittura.
L'ordine dei controlli e' quello storico di log_message e va preservato:

  1. '[DIAG-RAM]' sul testo GREZZO (prima del fix mojibake): solo sul logger, mai a schermo
  2. fix_mojibake
  3. estrazione di 'Modello trascrizione: X' (vale anche se la riga poi e' rumore)
  4. rumore di fondo (_FILE_ONLY_RE) scartato, SALVO se contiene ❌ o ⚠
  5. (la vista calcola timestamp e HTML: avviene anche per le righe che la modalita'
     compatta scarta subito dopo)
  6. barra aggiornabile / riga normale / scartata dalla modalita' compatta
"""
import re
from dataclasses import dataclass
from typing import Optional

# Righe che la pipeline aggiorna sul posto (barre di avanzamento / stato).
UPDATABLE_PATTERNS = ["Progresso:", "Demucs: [", "Traduzione: [", "Trascrizione: [", "Warm-up: [", "Correzione genere: [", "⚙️ OCR"]

# Righe che NON compaiono a schermo (rumore di fondo): restano nel file di log, perche'
# la pipeline le scrive anche con logger.info (v. core/pipeline.py::_log e engines/base_engine.py::log).
# NON mettere qui i "📦 Caricamento modello ..." (l'utente li vuole a schermo) ne' le barre.
FILE_ONLY_RE = re.compile("|".join([
    r"AdaptiveBatchManager avviato",
    r"Parametri profilo caricati",
    r"⚙️ Profilo: ", r"Profilo: .*Workers:", r"👷 Workers:",
    r"VAD \(Voice Activity Detection\) disponibile", r"VAD test successful",
    r"BatchedInferencePipeline attivo", r"BatchedInferencePipeline — file unico",
    r"📊 VRAM", r"🧮 Safe batch", r"📊 Batch size: adaptive",
    r"🛡️ Pipeline: ROBUST PATH", r"🛡️ Chunking robusto", r"📏 Overlap",
    r"🔗 Merge chunks", r"📂 Caricamento audio", r"🎬 Audio: ",
    r"\w+Engine unload completato",
    r"Batch LLM \d+ → \d+", r"Recupero senza mascheramento",
    r"Modello trascrizione:",
]))

# In modalita' compatta passano solo le righe che contengono uno di questi marcatori.
COMPACT_KEEP_MARKERS = ['✅', '⚙️', '🎉', '❌', '➕', '🎬', '📥']

MODEL_LINE_MARKER = 'Modello trascrizione:'


def fix_mojibake(text):
    """Ripara le emoji e rimuove caratteri sporchi residui"""
    if not text: return text
    try:
        # Tenta riparazione encoding
        if any(c in text for c in ['ð', 'â', 'ï', 'œ', '™']):
            text = text.encode('cp1252').decode('utf-8')
    except:
        try:
            text = text.encode('latin-1').decode('utf-8')
        except:
            pass
    # Rimuove glifi corrotti residui mantenendo le emoji buone
    text = re.sub(r'[ðâïœ™\x9d]+', '', text)   # \x9d: carattere di controllo invisibile presente nell'originale
    return text.strip()


@dataclass(frozen=True)
class LogDecision:
    """Esito di LogFilter.decide().

    action:
      'drop_ram'     riga [DIAG-RAM]: la vista la scrive SOLO sul logger (text = messaggio grezzo)
      'drop_noise'   rumore di fondo: non va a schermo (model_name puo' comunque essere valorizzato)
      'drop_compact' scartata dalla modalita' compatta (la vista ha gia' preso il timestamp)
      'progress'     barra aggiornabile: `progress_key` e' la chiave della barra
      'append'       riga normale da accodare
    text: messaggio dopo fix_mojibake (grezzo per 'drop_ram').
    model_name: nome non vuoto dopo 'Modello trascrizione:' (da mostrare nella tessera Modello).
    """
    action: str
    text: str
    progress_key: Optional[str] = None
    model_name: Optional[str] = None


class LogFilter:
    UPDATABLE_PATTERNS = UPDATABLE_PATTERNS
    FILE_ONLY_RE = FILE_ONLY_RE
    COMPACT_KEEP_MARKERS = COMPACT_KEEP_MARKERS

    @staticmethod
    def fix_mojibake(text):
        return fix_mojibake(text)

    @staticmethod
    def model_name_of(message: str) -> Optional[str]:
        """Nome del modello in 'Modello trascrizione: X', None se assente o vuoto."""
        if MODEL_LINE_MARKER not in message:
            return None
        name = message.split(MODEL_LINE_MARKER, 1)[1].strip()
        return name or None

    def decide(self, message: str, compact: bool = False) -> LogDecision:
        if '[DIAG-RAM]' in message:
            return LogDecision('drop_ram', message)
        message = fix_mojibake(message)
        model_name = self.model_name_of(message)
        if '❌' not in message and '⚠' not in message and FILE_ONLY_RE.search(message):
            return LogDecision('drop_noise', message, model_name=model_name)
        progress_key = next((p for p in UPDATABLE_PATTERNS if p in message), None)
        if progress_key is not None:
            return LogDecision('progress', message, progress_key=progress_key, model_name=model_name)
        if not compact or any(k in message for k in COMPACT_KEEP_MARKERS):
            return LogDecision('append', message, model_name=model_name)
        return LogDecision('drop_compact', message, model_name=model_name)
