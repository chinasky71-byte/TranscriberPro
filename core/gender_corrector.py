# -*- coding: utf-8 -*-
"""
Gender Correction Engine - LLM post-traduzione
File: core/gender_corrector.py

Corregge errori di genere grammaticale nei sottotitoli italiani
usando un LLM locale (Qwen2.5-7B GGUF via llama-cpp-python).

Il modulo si inserisce come STEP 6.5 nella pipeline, tra traduzione e salvataggio.
"""
import gc
import re
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Callable

logger = logging.getLogger(__name__)

# Type alias (stesso pattern di BaseTranslator)
SRT_SUBTITLE = Tuple[int, str, str, str]  # (index, start_time, end_time, text)

# Check disponibilità llama-cpp-python
LLAMA_CPP_AVAILABLE = False
try:
    from utils.cuda_dll_path import ensure_torch_lib_on_path
    ensure_torch_lib_on_path()
except Exception:
    pass
try:
    from llama_cpp import Llama
    LLAMA_CPP_AVAILABLE = True
except Exception:   # anche RuntimeError (DLL CUDA non trovata)
    pass


# ============================================================================
# Funzioni helper
# ============================================================================

# Pattern regex per rilevare testo sensibile al genere in italiano
_GENDER_PATTERNS = [
    # Participi passati singolari
    r'\b\w+[aeiou]t[oa]\b',        # -ato/-ata, -uto/-uta, -ito/-ita
    # Participi passati plurali
    r'\b\w+[aeiou]t[ie]\b',        # -ati/-ate, -uti/-ute, -iti/-ite
    # Aggettivi in -oso/-osa e plurali
    r'\b\w+os[oa]\b',              # -oso/-osa
    r'\b\w+os[ie]\b',              # -osi/-ose
    # Aggettivi comuni singolari
    r'\bbell[oa]\b', r'\bbrutt[oa]\b', r'\bstanc[oa]\b',
    r'\bsol[oa]\b', r'\bsicur[oa]\b', r'\bcontent[oa]\b',
    r'\bpront[oa]\b', r'\bmort[oa]\b', r'\bviv[oa]\b',
    r'\bspaventat[oa]\b', r'\binnamorat[oa]\b', r'\bpreoccupat[oa]\b',
    r'\bgelos[oa]\b', r'\bnervos[oa]\b', r'\bfurios[oa]\b',
    r'\barrabbiat[oa]\b', r'\bferit[oa]\b', r'\bsposat[oa]\b',
    r'\bdivorziat[oa]\b', r'\bmalat[oa]\b', r'\bstat[oa]\b',
    # Aggettivi plurali
    r'\bbell[ie]\b', r'\bstanch[ie]\b', r'\bsicur[ie]\b',
    r'\bcontent[ie]\b', r'\bpront[ie]\b', r'\bmort[ie]\b',
    # Dimostrativi
    r'\bquest[oa]\b', r'\bquell[oa]\b',
    r'\bquest[ie]\b', r'\bquell[ie]\b',
    # Indefiniti
    r'\btutt[oa]\b', r'\bmolt[oa]\b', r'\bpoc[oa]\b', r'\btropp[oa]\b',
    r'\btutt[ie]\b', r'\bmolt[ie]\b', r'\bpoc[hi]e?\b', r'\btropp[ie]\b',
    # Possessivi standalone
    r'\b(?:mio|mia|tuo|tua|suo|sua)\b',
    # Pronomi soggetto
    r'\b(?:lui|lei)\b',
    # Possessivi con articolo
    r'\b(?:il suo|la sua|i suoi|le sue)\b',
    r'\b(?:il mio|la mia|i miei|le mie)\b',
    r'\b(?:il tuo|la tua|i tuoi|le tue)\b',
    # Articoli indeterminativi
    r'\b(?:un|uno|una)\s+\w+',
    # Nomi con articolo determinativo
    r'\b(?:il|lo|la|l\'|gli|le)\s+\w+',
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _GENDER_PATTERNS]


def needs_gender_fix(text: str) -> bool:
    """Pre-filtro: il testo contiene pattern sensibili al genere italiano?"""
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            return True
    return False


def split_into_chunks(entries: List[SRT_SUBTITLE],
                      chunk_size: int = 5) -> List[dict]:
    """
    Divide i sottotitoli in chunk con contesto prev/next.

    Returns:
        Lista di dict con chiavi: entries, prev_context, next_context,
        start_index, end_index
    """
    chunks = []
    for i in range(0, len(entries), chunk_size):
        chunk_entries = entries[i:i + chunk_size]

        prev_context = None
        if i > 0:
            prev_context = entries[i - 1][3]

        next_idx = i + chunk_size
        next_context = None
        if next_idx < len(entries):
            next_context = entries[next_idx][3]

        chunks.append({
            'entries': chunk_entries,
            'prev_context': prev_context,
            'next_context': next_context,
            'start_index': i,
            'end_index': i + len(chunk_entries) - 1,
        })

    return chunks


def _parse_srt(srt_path: Path) -> List[SRT_SUBTITLE]:
    """Parsing file SRT (replica del pattern BaseTranslator._parse_srt)."""
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        subtitles = []
        pattern = r'(\d+)\s*\n([\d:,]+)\s*-->\s*([\d:,]+)\s*\n((?:.*\n?)+?)(?=\n\d+\s*\n|$)'

        for match in re.finditer(pattern, content, re.MULTILINE):
            index = int(match.group(1))
            start_time = match.group(2).strip()
            end_time = match.group(3).strip()
            text = match.group(4).strip()
            if text:
                subtitles.append((index, start_time, end_time, text))

        return subtitles
    except Exception as e:
        logger.error(f"Errore parsing SRT: {e}")
        return []


def _generate_srt(subtitles: List[SRT_SUBTITLE]) -> str:
    """Genera contenuto SRT da lista sottotitoli."""
    srt_content = []
    for index, start, end, text in subtitles:
        srt_content.append(f"{index}")
        srt_content.append(f"{start} --> {end}")
        srt_content.append(text)
        srt_content.append("")
    return "\n".join(srt_content)


# ============================================================================
# LocalLLMCorrector — carica modello GGUF e corregge chunk
# ============================================================================

# Regex per trovare una freccia di patch (solo arrow espliciti, no single dash
# per non confondere col marker di dialogo "- ").
_ARROW_RE = re.compile(r'\s*(?:\u2192|->|=>)\s*')
# Regex per pulire [NUM] residui dentro wrong/correct
_LEADING_NUM_RE = re.compile(r'^\s*\[\d+\]\s*')
# Regex per strip marker di dialogo "- " a inizio stringa
_LEADING_DASH_RE = re.compile(r'^[-\u2013\u2014]\s*')


def _parse_patches(output_text: str) -> List[Tuple[int, str, str]]:
    """
    Parse robusto dell'output LLM. Accetta output malformato e filtra:
    - [NUM] residui dentro wrong/correct
    - marker di dialogo "- " residui
    - placeholder "parola_errata" / "parola_corretta"
    - patch vuote o identiche
    - patch troppo lunghe (>60 char)
    """
    patches = []
    for raw_line in output_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Trova primo [NUM]
        m = re.match(r'\[(\d+)\]\s*(.+)', line)
        if not m:
            continue
        line_num = int(m.group(1))
        rest = m.group(2)
        # Trova freccia
        arrow = _ARROW_RE.search(rest)
        if not arrow:
            continue
        wrong = rest[:arrow.start()].strip()
        correct = rest[arrow.end():].strip()
        # Strip [NUM] residui
        wrong = _LEADING_NUM_RE.sub('', wrong).strip()
        correct = _LEADING_NUM_RE.sub('', correct).strip()
        # Strip marker dialogo "- "
        wrong = _LEADING_DASH_RE.sub('', wrong).strip()
        correct = _LEADING_DASH_RE.sub('', correct).strip()
        # Filtri qualit\u00e0
        if not wrong or not correct:
            continue
        if wrong == correct:
            continue
        if 'parola_errata' in wrong.lower() or 'parola_corretta' in correct.lower():
            continue
        # Una patch di genere italiana raramente supera 3-4 parole
        # ("il suo vecchio amico" -> "la sua vecchia amica" = 20 char).
        # Cap a 40 char scarta ricostruzioni di intere frasi.
        if len(wrong) > 40 or len(correct) > 40:
            continue
        patches.append((line_num, wrong, correct))
    return patches


def _apply_patch(text: str, wrong: str, correct: str) -> Optional[str]:
    """
    Applica una patch al testo preservando il case del match originale.

    1. Prima tenta match esatto case-sensitive (caso normale).
    2. Fallback case-insensitive: se trova il wrong ignorando il case,
       applica la correzione preservando la capitalizzazione iniziale
       (es. "Stanco" con patch "stanco -> stanca" diventa "Stanca").
    3. Se neanche il fallback trova match, ritorna None.
    """
    # Match esatto
    if wrong in text:
        return text.replace(wrong, correct, 1)
    # Fallback case-insensitive
    idx = text.lower().find(wrong.lower())
    if idx == -1:
        return None
    original_match = text[idx:idx + len(wrong)]
    # Preserva il case del match originale:
    # - tutto maiuscolo (es. "STANCO" per un urlo) -> correzione in UPPER
    # - prima lettera maiuscola -> Capitalize
    # - altrimenti -> lowercase come il modello ha prodotto
    if original_match.isupper():
        adjusted = correct.upper()
    elif original_match and original_match[0].isupper() and correct:
        adjusted = correct[0].upper() + correct[1:]
    else:
        adjusted = correct
    return text[:idx] + adjusted + text[idx + len(wrong):]


SYSTEM_PROMPT = (
    "Sei un correttore esperto di genere grammaticale per sottotitoli italiani tradotti.\n"
    "\n"
    "PROCEDURA per ogni riga:\n"
    "1. Identifica CHI parla e DI CHI si parla (usa il testo originale inglese come riferimento)\n"
    "2. Cerca il genere del soggetto nella lista PERSONAGGI E GENERE\n"
    "3. Verifica che aggettivi, participi e pronomi concordino col genere del soggetto\n"
    "4. Se trovi un errore, produci la correzione\n"
    "\n"
    "REGOLA D'ORO: Se un personaggio \u00e8 FEMMINA, TUTTI gli aggettivi e participi riferiti\n"
    "a lei devono essere al femminile. Stesso per MASCHIO. Se in una stessa frase pi\u00f9\n"
    "parole sono sbagliate, emetti una patch per ciascuna.\n"
    "\n"
    "PRINCIPIO DI PRUDENZA (importantissimo):\n"
    "- In caso di AMBIGUIT\u00c0 (il soggetto non \u00e8 chiaramente identificabile dal contesto,\n"
    "  dalla lista personaggi o dal testo originale), NON toccare la riga. Mantieni il\n"
    "  testo italiano ORIGINALE.\n"
    "- NON presumere il genere. Se il testo italiano \u00e8 al maschile e l'inglese non\n"
    "  specifica il sesso del soggetto, NON forzare il femminile (e viceversa).\n"
    "- Se la riga italiana \u00e8 gi\u00e0 grammaticalmente sensata e non hai PROVE di un errore\n"
    "  di concordanza, lasciala com'\u00e8. Nel dubbio, non correggere.\n"
    "- Meglio 0 correzioni corrette che 10 correzioni sbagliate.\n"
    "\n"
    "VINCOLI CRITICI:\n"
    "- Correggi SOLO parole italiane nella sezione SOTTOTITOLI DA CORREGGERE.\n"
    "- Il TESTO ORIGINALE in inglese \u00e8 SOLO per capire il contesto e il soggetto.\n"
    "  NON correggere parole inglesi. NON mettere MAI parole inglesi nelle patch.\n"
    "- La parola a sinistra della freccia deve essere copiata ESATTAMENTE come appare\n"
    "  nel sottotitolo italiano indicato da [NUM], con le STESSE maiuscole/minuscole.\n"
    "- Max 3 parole per patch. Non riscrivere intere frasi.\n"
    "- NON includere \"[NUM]\" dentro le parole della patch (solo a inizio riga).\n"
    "- NON includere il marker \"-\" dei dialoghi dentro le parole della patch.\n"
    "- NON usare mai le stringhe letterali \"parola_errata\" o \"parola_corretta\":\n"
    "  usa SOLO le parole reali copiate dal sottotitolo.\n"
    "\n"
    "FORMATO OUTPUT (ogni patch su una riga):\n"
    "    [NUM] <parola sbagliata> \u2192 <parola corretta>\n"
    "\n"
    "Esempio di output corretto (Meredith \u00e8 FEMMINA):\n"
    "    [1] arrivato \u2192 arrivata\n"
    "    [1] stanco \u2192 stanca\n"
    "    [3] il suo \u2192 la sua\n"
    "\n"
    "REGOLE FINALI:\n"
    "- Correggi SOLO errori di concordanza di genere.\n"
    "- NON modificare significato, punteggiatura, stile, tempi verbali.\n"
    "- Se non servono correzioni rispondi ESATTAMENTE: NESSUNA CORREZIONE\n"
    "- NON aggiungere spiegazioni o ragionamenti."
)

# Mappa label genere per il prompt
_GENDER_LABEL = {"M": "MASCHIO", "F": "FEMMINA"}


class LocalLLMCorrector:
    """Gestisce il modello GGUF locale per la correzione di genere."""

    def __init__(self, model_path: str, log_callback: Callable = None, n_gpu_layers: int = -1):
        self.model_path = model_path
        self.n_gpu_layers = n_gpu_layers
        self.model = None
        self._log_callback = log_callback

    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)
        logger.info(msg)

    def load_model(self) -> bool:
        """Carica il modello GGUF in VRAM."""
        if not LLAMA_CPP_AVAILABLE:
            self._log("llama-cpp-python non disponibile")
            return False

        if not Path(self.model_path).exists():
            self._log(f"Modello non trovato: {self.model_path}")
            return False

        try:
            self._log("Caricamento modello LLM per correzione genere...")
            self.model = Llama(
                model_path=self.model_path,
                n_gpu_layers=self.n_gpu_layers,
                n_ctx=4096,
                n_batch=512,
                verbose=False,
            )
            self._log("Modello LLM caricato.")
            return True
        except Exception as e:
            logger.error(f"Errore caricamento modello LLM: {e}", exc_info=True)
            self._log(f"Errore caricamento LLM: {e}")
            return False

    def unload_model(self):
        """Scarica il modello dalla VRAM."""
        if self.model is not None:
            del self.model
            self.model = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def correct_chunk(self, chunk: dict,
                      character_context: Dict[str, str],
                      original_entries: Optional[List[SRT_SUBTITLE]] = None
                      ) -> List[Tuple[int, str, str]]:
        """
        Corregge un chunk di sottotitoli.

        Args:
            chunk: dict da split_into_chunks()
            character_context: {nome_personaggio: "M"|"F"}
            original_entries: lista entry SRT originali (inglese), allineate
                              per indice con quelle italiane. Opzionale.

        Returns:
            Lista di (line_num, parola_errata, parola_corretta)
        """
        if self.model is None:
            return []

        # Costruisce la sezione personaggi con label espliciti
        char_lines = []
        if character_context:
            for name, gender in character_context.items():
                label = _GENDER_LABEL.get(gender, gender)
                char_lines.append(f"- {name}: {label}")

        # Costruisce il prompt utente
        user_parts = []

        if char_lines:
            user_parts.append("PERSONAGGI E GENERE:")
            user_parts.extend(char_lines)
            user_parts.append("")

        if chunk.get('prev_context'):
            user_parts.append(f"CONTESTO PRECEDENTE: {chunk['prev_context']}")
            user_parts.append("")

        user_parts.append("SOTTOTITOLI DA CORREGGERE:")
        for i, (idx, _start, _end, text) in enumerate(chunk['entries'], 1):
            user_parts.append(f"[{i}] {text}")

        # Sezione testo originale inglese (se fornito)
        if original_entries:
            start_idx = chunk['start_index']
            end_idx = chunk['end_index']
            if end_idx < len(original_entries):
                user_parts.append("")
                user_parts.append("TESTO ORIGINALE (per riferimento soggetto):")
                for i, orig_entry in enumerate(
                        original_entries[start_idx:end_idx + 1], 1):
                    orig_text = orig_entry[3]
                    user_parts.append(f"[{i}] {orig_text}")

        if chunk.get('next_context'):
            user_parts.append("")
            user_parts.append(f"CONTESTO SUCCESSIVO: {chunk['next_context']}")

        user_parts.append("")
        user_parts.append("Correzioni di genere:")

        user_prompt = "\n".join(user_parts)

        # max_tokens adattivo: ~64 token per entry + margine base.
        # Con chunk_size=5 -> 512 tokens; con 10 -> 768; con 15 -> 1088.
        # Evita troncamenti quando una frase richiede piu' patch concordate.
        n_entries = len(chunk['entries'])
        adaptive_max_tokens = max(512, 64 * n_entries + 128)

        try:
            response = self.model.create_chat_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                top_p=0.1,
                repeat_penalty=1.1,
                max_tokens=adaptive_max_tokens,
            )

            output_text = response['choices'][0]['message']['content'].strip()

            if 'NESSUNA CORREZIONE' in output_text.upper():
                return []

            return _parse_patches(output_text)

        except Exception as e:
            logger.warning(f"Errore inferenza LLM su chunk: {e}")
            return []


# ============================================================================
# GenderCorrectionEngine — orchestratore
# ============================================================================

class GenderCorrectionEngine:
    """Motore di correzione genere: coordina pre-filtro, LLM e applicazione patch."""

    def __init__(self, log_callback: Callable = None):
        self._log_callback = log_callback
        self._corrector: Optional[LocalLLMCorrector] = None

    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)
        logger.info(msg)

    def is_available(self) -> bool:
        """Verifica se llama-cpp-python e il modello GGUF sono disponibili."""
        if not LLAMA_CPP_AVAILABLE:
            return False
        from utils.config import get_config
        return get_config().is_gender_correction_available()

    def correct_file(self, srt_path: Path, output_path: Path,
                     character_context: Dict[str, str] = None,
                     original_srt_path: Optional[Path] = None) -> bool:
        """
        Corregge un file SRT per errori di genere.

        Args:
            srt_path: file SRT tradotto
            output_path: dove salvare il file corretto
            character_context: {nome_personaggio: "M"|"F"} da TMDB
            original_srt_path: file SRT nella lingua originale (opzionale).
                               Se fornito e allineato, viene passato al LLM
                               come riferimento per identificare il soggetto.

        Returns:
            True se completato (anche con 0 correzioni), False su errore fatale
        """
        if character_context is None:
            character_context = {}

        try:
            # 1. Parse SRT tradotto
            entries = _parse_srt(srt_path)
            if not entries:
                self._log("Nessun sottotitolo trovato. Salto correzione genere.")
                return True

            # 1b. Parse SRT originale (opzionale)
            original_entries = None
            if original_srt_path and Path(original_srt_path).exists():
                parsed_original = _parse_srt(Path(original_srt_path))
                if parsed_original and len(parsed_original) == len(entries):
                    original_entries = parsed_original
                    self._log(f"   Testo originale caricato: {len(original_entries)} entry")
                elif parsed_original:
                    self._log(
                        f"   Disallineamento SRT originale "
                        f"({len(parsed_original)} vs {len(entries)}). Ignoro.")

            # 2. Pre-filtro: conta quanti entry hanno pattern di genere
            gender_sensitive_count = sum(1 for _, _, _, t in entries if needs_gender_fix(t))
            self._log(f"   Pre-filtro: {gender_sensitive_count}/{len(entries)} sottotitoli con pattern di genere")

            if gender_sensitive_count == 0:
                # Nessun pattern trovato, copia originale
                import shutil
                shutil.copy(srt_path, output_path)
                self._log("   Nessun pattern di genere trovato. File copiato senza modifiche.")
                return True

            # 3. Chunk
            chunks = split_into_chunks(entries, chunk_size=10)

            # 4. Load modello LLM
            from utils.config import get_config
            model_path, n_gpu_layers = get_config().resolve_llm_model(
                'gender_correction_model_path', getattr(self, 'llm_model_preference', None))
            self._corrector = LocalLLMCorrector(model_path, log_callback=self._log_callback,
                                                n_gpu_layers=n_gpu_layers)

            if not self._corrector.load_model():
                self._log("Impossibile caricare modello LLM. Salto correzione genere.")
                return False

            # 5. Correggi chunk per chunk
            total_patches = 0
            skipped_patches = 0
            out_of_range_patches = 0
            chunks_processed = 0
            chunks_skipped = 0
            total_chunks = len(chunks)
            chunks_with_gender = sum(
                1 for c in chunks if any(needs_gender_fix(e[3]) for e in c['entries'])
            )
            import time as _time
            t0 = _time.time()
            self._log(f"   Correzione genere: [\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591]   0% (0/{chunks_with_gender})")
            last_progress = -1

            for ci, chunk in enumerate(chunks):
                # Skip chunk senza entry gender-sensitive
                has_gender = any(needs_gender_fix(e[3]) for e in chunk['entries'])
                if not has_gender:
                    chunks_skipped += 1
                    continue

                patches = self._corrector.correct_chunk(
                    chunk, character_context, original_entries)
                chunks_processed += 1

                progress = int((chunks_processed / chunks_with_gender) * 100) if chunks_with_gender else 100
                if progress != last_progress:
                    bars = int(progress / 10)
                    bar = '\u2588' * bars + '\u2591' * (10 - bars)
                    elapsed = _time.time() - t0
                    eta_s = None
                    if chunks_processed > 0 and progress < 100:
                        eta = elapsed / chunks_processed * (chunks_with_gender - chunks_processed)
                        eta_s = int(eta)
                        eta_str = f"{eta_s}s"
                    else:
                        eta_str = "-"
                    from utils.events import emit as _tp_emit
                    _tp_emit('bar', phase='gender', pct=progress, eta_s=eta_s)   # ETA del motore (la stessa del log)
                    self._log(
                        f"   Correzione genere: [{bar}] {progress:3d}% "
                        f"({chunks_processed}/{chunks_with_gender}) "
                        f"\u2502 ETA:{eta_str}"
                    )
                    last_progress = progress

                # 6. Applica patch
                for line_num, wrong, correct in patches:
                    # line_num e' 1-based relativo al chunk
                    entry_idx = chunk['start_index'] + line_num - 1
                    if not (0 <= entry_idx < len(entries)):
                        out_of_range_patches += 1
                        continue
                    idx, start, end, text = entries[entry_idx]
                    new_text = _apply_patch(text, wrong, correct)
                    if new_text is not None:
                        entries[entry_idx] = (idx, start, end, new_text)
                        total_patches += 1
                        logger.debug(f"Patch [{entry_idx+1}]: '{wrong}' -> '{correct}'")
                    else:
                        skipped_patches += 1
                        logger.debug(f"Patch skip: '{wrong}' non trovato in entry {entry_idx+1}")

            elapsed_total = _time.time() - t0
            mins, secs = divmod(int(elapsed_total), 60)
            time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
            self._log(
                f"   \u2705 Correzione genere: [\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588] 100% "
                f"({chunks_processed}/{chunks_with_gender}) \u2502 {time_str}"
            )

            # 7. Genera SRT output
            srt_content = _generate_srt(entries)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            # 8. Log statistiche
            self._log(f"   Correzioni applicate: {total_patches}")
            self._log(f"   Chunk processati: {chunks_processed}, skippati: {chunks_skipped}")
            if skipped_patches or out_of_range_patches:
                self._log(
                    f"   Patch scartate: {skipped_patches} non trovate nel testo, "
                    f"{out_of_range_patches} fuori range")

            return True

        except Exception as e:
            logger.error(f"Errore fatale correzione genere: {e}", exc_info=True)
            self._log(f"Errore correzione genere: {e}")
            return False

    def cleanup(self):
        """Rilascia risorse LLM."""
        if self._corrector:
            self._corrector.unload_model()
            self._corrector = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
