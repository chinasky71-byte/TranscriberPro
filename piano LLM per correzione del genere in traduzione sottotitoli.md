# Piano: Gender Correction Engine (LLM post-traduzione)

## Contesto

NLLB e i traduttori MT producono spesso errori di genere grammaticale nei sottotitoli italiani (es. "Sei stato brava" → una donna che dice "stato" maschile + "brava" femminile). Il motivo: i modelli non conoscono il genere dei personaggi. Serve una correzione post-traduzione che usi un LLM locale (Qwen2.5-7B GGUF) con contesto cast da TMDB.

**Vincoli chiave:**
- RTX 3060 12GB VRAM — dopo cleanup traduttore, ~10-11 GB liberi
- Qwen2.5-7B Q4_K_M GGUF: ~5-6 GB VRAM — fits safely
- `llama-cpp-python` = nuova dipendenza (wheel pre-built con CUDA)
- Solo per target italiano, opzionale via config

## Posizionamento nella pipeline

```
STEP 6: Traduzione ──► STEP 6.5: Gender Correction (NEW) ──► STEP 7: Salvataggio
                         ↑ cleanup translator prima di caricare LLM
                         ↑ solo se: target=it AND config flag AND GGUF exists
```

---

## Modifiche

### 1. `core/gender_corrector.py` (NUOVO — file principale)

Struttura del modulo:

```python
# Costanti
LLAMA_CPP_AVAILABLE: bool  # try/except import llama_cpp.Llama
SRT_SUBTITLE = Tuple[int, str, str, str]

# Funzioni
needs_gender_fix(text: str) -> bool
split_into_chunks(entries: List[SRT_SUBTITLE], chunk_size=5) -> List[dict]
_parse_srt(path: Path) -> List[SRT_SUBTITLE]        # copia pattern da BaseTranslator
_generate_srt(subtitles: List[SRT_SUBTITLE]) -> str  # idem

# Classi
LocalLLMCorrector     # load/unload modello GGUF, correct_chunk()
GenderCorrectionEngine  # orchestratore: is_available(), correct_file(), cleanup()
```

#### `needs_gender_fix(text: str) -> bool`

Pre-filtro regex per pattern italiani sensibili al genere:
- Participi passati: `-ato/-ata/-uto/-uta/-ito/-ita`
- Aggettivi: `-oso/-osa`, pattern comuni (`stanc[oa]`, `bell[oa]`, ecc.)
- Pronomi: `lui/lei`, `il suo/la sua`
- Articoli determinativi + nome

Se nessun pattern matcha → skip chunk (non inviato al LLM). Filtro *broad* intenzionalmente — meglio false positive che miss.

#### `split_into_chunks(entries, chunk_size=5)`

Ritorna lista di dict:
```python
{
    'entries': List[SRT_SUBTITLE],  # i 5 sottotitoli da correggere
    'prev_context': Optional[str],  # testo entry precedente
    'next_context': Optional[str],  # testo entry successiva
    'start_index': int,
    'end_index': int,
}
```

#### `LocalLLMCorrector`

```python
class LocalLLMCorrector:
    def __init__(self, model_path: str, log_callback=None)
    def load_model(self) -> bool
        # Llama(model_path, n_gpu_layers=-1, n_ctx=4096, n_batch=512, verbose=False)
    def unload_model(self)
        # del self.model + gc + empty_cache
    def correct_chunk(self, chunk: dict, character_context: Dict[str,str]) -> List[Tuple[int,str,str]]
        # Costruisce prompt → inferenza → parse output patch
```

**Parametri inferenza:** `temperature=0.1`, `top_p=0.9`, `max_tokens=256`

**Formato prompt:**

System:
```
Sei un correttore di genere grammaticale per sottotitoli italiani.
REGOLE:
1. Correggi SOLO errori di genere (maschile↔femminile)
2. NON modificare significato, punteggiatura, stile
3. Output SOLO nel formato: [NUM] parola_errata → parola_corretta
4. Se non servono correzioni: NESSUNA CORREZIONE
```

User (dinamico per chunk):
```
PERSONAGGI:
- Meredith Grey: F
- Derek Shepherd: M

CONTESTO PRECEDENTE: <prev text>

SOTTOTITOLI:
[1] Sono stanco di aspettare.
[2] Lei è arrivato tardi.

CONTESTO SUCCESSIVO: <next text>

Correzioni di genere:
```

**Parser patch:** `re.compile(r'\[(\d+)\]\s*(\S+)\s*[→\->]+\s*(\S+)')` → `(line_num, wrong, correct)`

**Applier patch:** per ogni patch, `str.replace(wrong, correct, 1)` nell'entry corrispondente. Safety check: se `wrong` non trovato nel testo, skip con warning.

#### `GenderCorrectionEngine`

```python
class GenderCorrectionEngine:
    def __init__(self, log_callback=None)
    def is_available(self) -> bool  # LLAMA_CPP_AVAILABLE + model file exists
    def correct_file(self, srt_path: Path, output_path: Path, character_context: Dict[str,str]) -> bool
    def cleanup(self)  # unload + gc + empty_cache
```

Flow `correct_file()`:
1. Parse SRT → `entries`
2. Pre-filter: contare quanti `needs_gender_fix()`. Se zero → copia file, return True
3. Chunk entries (size 5)
4. Load modello LLM
5. Per ogni chunk con almeno un entry gender-sensitive: `correct_chunk()`
6. Applicare patch agli entries
7. Generare SRT output e scrivere
8. Log statistiche: N correzioni applicate, N chunks processati, N chunks skippati
9. Unload modello

**Error handling:** qualsiasi eccezione in un chunk → keep testo originale per quel chunk. Qualsiasi eccezione globale → return False (pipeline usa traduzione originale).

---

### 2. `utils/tmdb_client.py` — Aggiungere `get_cast_info()`

**Dove:** dopo `search_tv()` (circa linea 756), prima di `download_poster`.

```python
def get_cast_info(self, tmdb_id: int, media_type: str,
                  season: int = None, episode: int = None,
                  max_cast: int = 15) -> Dict[str, str]:
    """
    Ritorna {character_name: "M"|"F"} dai credits TMDB.
    TMDB gender: 0=unknown, 1=Female, 2=Male
    """
```

Endpoint API:
- Movie: `GET /movie/{id}/credits?api_key=...`
- TV episode: `GET /tv/{id}/season/{s}/episode/{e}/credits?api_key=...`
- TV senza ep: `GET /tv/{id}/aggregate_credits?api_key=...`

Parsing: itero `response['cast']`, mappo `gender: 1→"F", 2→"M"`, skip 0/3. Ritorno top N con genere noto.

---

### 3. `utils/config.py` — Nuove chiavi config

**Dove:** nel dict `DEFAULTS` (linea ~125), prima della chiusura `}`:

```python
# Gender Correction (LLM post-traduzione)
'gender_correction_enabled': False,
'gender_correction_model_path': '',  # Path al file GGUF
```

**Metodo helper** (dopo blocco Adaptive Batch):
```python
def is_gender_correction_available(self) -> bool:
    if not self.get('gender_correction_enabled', False):
        return False
    p = self.get('gender_correction_model_path', '')
    return bool(p) and Path(p).exists()
```

---

### 4. `gui/main_window.py` — Checkbox

**Dove:** dopo linea 237 (`options_layout.addLayout(os_row)`), prima di linea 238 (`options_layout.addLayout(lang_row)`):

```python
self.gender_correction_checkbox = QCheckBox(tr('gender_correction_checkbox'))
self.gender_correction_checkbox.setObjectName("modernCheckbox")
self.gender_correction_checkbox.setChecked(self.config.get('gender_correction_enabled', False))
self.gender_correction_checkbox.stateChanged.connect(self.on_gender_correction_changed)
options_layout.addWidget(self.gender_correction_checkbox)
```

**Handler** (dopo `on_opensubtitles_checkbox_changed`, linea ~575):
```python
def on_gender_correction_changed(self, state):
    self.config.set('gender_correction_enabled', state == Qt.CheckState.Checked.value)
```

---

### 5. `utils/translations.py` — Chiave i18n

Dict `'it'`:
```python
'gender_correction_checkbox': 'Correzione genere avanzata (LLM)',
```
Dict `'en'`:
```python
'gender_correction_checkbox': 'Advanced gender correction (LLM)',
```

---

### 6. `core/pipeline.py` — STEP 6.5

**Dove:** dopo linea 500 (cancellation check), prima di linea 502 (STEP 7).

```python
            # ============================================================
            # STEP 6.5: Correzione Genere (solo italiano, opzionale)
            # ============================================================
            if (final_language_639_1 == 'it'
                    and self.config.get('gender_correction_enabled', False)):
                self._log("\n6.5. Correzione genere grammaticale (LLM)...")
                try:
                    from core.gender_corrector import GenderCorrectionEngine, LLAMA_CPP_AVAILABLE
                    if not LLAMA_CPP_AVAILABLE:
                        self._log("⚠️ llama-cpp-python non installato. Salto.")
                    else:
                        engine = GenderCorrectionEngine(log_callback=self._log_callback)
                        if engine.is_available():
                            # Cleanup translator VRAM prima di caricare LLM
                            if self._translator:
                                self._translator.cleanup()
                                self._translator = None
                            gc.collect()
                            if torch.cuda.is_available():
                                torch.cuda.synchronize()
                                torch.cuda.empty_cache()
                            release_ram_to_os()

                            # Cast da TMDB
                            character_context = {}
                            if self.metadata and self.metadata.get('id'):
                                character_context = self.tmdb_client.get_cast_info(
                                    self.metadata['id'],
                                    'tv' if self.metadata.get('season') else 'movie',
                                    season=self.metadata.get('season'),
                                    episode=self.metadata.get('episode'))
                                if character_context:
                                    self._log(f"✅ Cast: {len(character_context)} personaggi")

                            corrected_path = self.file_handler.get_temp_path(
                                self.video_path, f"gender_corrected_{target_language}.srt")
                            if engine.correct_file(subtitle_path, corrected_path, character_context):
                                subtitle_path = corrected_path
                                self._log("✅ Correzione genere completata.")
                            else:
                                self._log("⚠️ Correzione genere fallita. Uso originale.")
                            engine.cleanup()
                        else:
                            self._log("⚠️ Modello GGUF non trovato. Salto.")
                except Exception as e:
                    self._log(f"⚠️ Errore correzione genere: {e}")
                    logger.error(f"Gender correction error: {e}", exc_info=True)
```

---

### 7. `core/__init__.py` — Export

Aggiungere:
```python
from .gender_corrector import GenderCorrectionEngine
```
e `'GenderCorrectionEngine'` in `__all__`.

---

### 8. `requirements.txt` — Nuova dipendenza

```
# Gender Correction (LLM) — richiede wheel CUDA
# pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu126
llama-cpp-python
```

---

## Sequenza implementazione

| Fase | File | Dipendenze |
|------|------|-----------|
| 1 | `utils/config.py` — chiavi DEFAULTS | nessuna |
| 2 | `utils/translations.py` — stringhe i18n | nessuna |
| 3 | `utils/tmdb_client.py` — `get_cast_info()` | nessuna |
| 4 | `gui/main_window.py` — checkbox | fase 1+2 |
| 5 | `core/gender_corrector.py` — modulo completo | fase 1 |
| 6 | `core/__init__.py` — export | fase 5 |
| 7 | `core/pipeline.py` — STEP 6.5 | fase 3+5 |
| 8 | `requirements.txt` — llama-cpp-python | nessuna |

Fasi 1-3 sono indipendenti (parallelizzabili). Fase 5 è il bulk del lavoro.

## Decisioni di design

1. **Modello caricato/scaricato per-file** — non residente. Coerente col pattern esistente (Whisper, NLLB, Aya: load → use → unload).
2. **llama-cpp-python diretto, NON Ollama** — zero dipendenze esterne, controllo diretto VRAM, nessun server.
3. **Fallback sicuro** — qualsiasi errore → testo tradotto originale. Mai bloccare la pipeline.
4. **Chunk size 5** — ~200-300 token input, ~50 token output, ~0.5s/chunk. Per SRT 600 righe: ~120 call, ~60s totali.
5. **Patch format** — il LLM produce solo `[N] wrong → correct`, non riscritture intere. Riduce allucinazioni e permette validazione.

## Verifica

1. **Unit test `needs_gender_fix()`**: verificare che "Sono stanco" → True, "1234" → False
2. **Test TMDB credits**: `get_cast_info(tmdb_id=1416, media_type='tv', season=1, episode=1)` per Grey's Anatomy → cast con generi
3. **Test pipeline completo**: tradurre un video con sottotitoli noti (personaggio femminile), verificare correzioni genere nel SRT finale
4. **Test VRAM**: dopo cleanup traduttore, caricare GGUF, verificare peak < 12 GB
5. **Test fallback**: disabilitare/rimuovere GGUF, verificare che pipeline prosegue senza errori
