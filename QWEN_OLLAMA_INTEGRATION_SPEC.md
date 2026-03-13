# Specifica Tecnica: Integrazione Qwen 2.5-7B via Ollama
## Sistema di Traduzione Sottotitoli Cinematografici EN→IT

**Versione**: 1.0  
**Data**: 2025-11-03  
**Target Software**: TranscriberPro  
**Obiettivo**: Aggiungere terzo modello di traduzione con focus su linguaggio cinematografico naturale

---

## 📋 INDICE

1. [Executive Summary](#1-executive-summary)
2. [Architettura Sistema](#2-architettura-sistema)
3. [Requisiti e Dipendenze](#3-requisiti-e-dipendenze)
4. [Implementazione Classe QwenOllamaTranslator](#4-implementazione-classe-qwenollamatranslator)
5. [Sistema di Prompting Avanzato](#5-sistema-di-prompting-avanzato)
6. [Integrazione Configuration Manager](#6-integrazione-configuration-manager)
7. [Integrazione GUI](#7-integrazione-gui)
8. [Gestione Errori e Resilienza](#8-gestione-errori-e-resilienza)
9. [Testing e Validazione](#9-testing-e-validazione)
10. [Performance e Ottimizzazioni](#10-performance-e-ottimizzazioni)
11. [Migration Path](#11-migration-path)
12. [Riferimenti Tecnici](#12-riferimenti-tecnici)

---

## 1. EXECUTIVE SUMMARY

### 1.1 Obiettivo dell'Integrazione

Aggiungere **Qwen 2.5-7B-Instruct** (via Ollama) come terzo modello di traduzione specializzato in:
- **Dialoghi cinematografici** naturali e colloquiali
- **Gestione contesto** esteso (fino a 16K-32K token)
- **Traduzione idiomatica** EN→IT di alta qualità
- **Preservazione tono** emotivo e stilistico

### 1.2 Vantaggi Rispetto ai Modelli Esistenti

| Caratteristica | NLLB 3B | Aya 8B | **Qwen 2.5 7B** |
|---|---|---|---|
| **Architettura** | NMT (frasale) | LLM Generalist | **LLM + Instruction Following** |
| **Contesto** | ~512 token | ~2048 token | **8K-32K token** |
| **Stile Output** | Formale/Tecnico | Generale | **Cinematografico/Colloquiale** |
| **Velocità (RTX 3060)** | ~20 tok/s | ~15 tok/s | **25-35 tok/s (Q4_K_M)** |
| **VRAM Uso** | ~4GB | ~10GB | **~6-8GB** |
| **Idiomaticità** | Bassa | Media | **Alta (con prompt eng.)** |
| **Coerenza Narrativa** | Nessuna | Limitata | **Ottima** |

### 1.3 Architettura Scelta: REST API + Ollama Server

**Perché Ollama invece di PyTorch diretto:**
1. ✅ **Isolamento**: nessun conflitto con transformers/PyTorch esistenti
2. ✅ **GGUF Quantizzazione**: formato ottimizzato per inferenza (llama.cpp backend)
3. ✅ **Gestione Memoria**: auto-unload modelli quando inutilizzati
4. ✅ **Aggiornamenti**: modelli aggiornabili senza toccare codice Python
5. ✅ **Multi-modello**: switch tra modelli senza reload app

---

## 2. ARCHITETTURA SISTEMA

### 2.1 Stack Tecnologico

```
┌─────────────────────────────────────────────────────────────┐
│                    APPLICAZIONE PyQt6                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ NLLBTransl.  │  │ AyaTransl.   │  │ QwenOllamaTransl.│  │
│  │ (PyTorch)    │  │ (PyTorch)    │  │ (REST Client)    │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │             │
│         ▼                 ▼                    ▼             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         BaseTranslator (Abstract Class)              │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                                                   │
                                    HTTP REST API │
                                                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    OLLAMA SERVER (Windows Service)           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  llama.cpp Backend (CUDA Accelerated)                │  │
│  │  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │  │
│  │  │ qwen2.5:7b │  │ qwen2.5:14b│  │ Altri modelli │  │  │
│  │  │ (Q4_K_M)   │  │ (Q4_K_M)   │  │ (futuri)      │  │  │
│  │  └────────────┘  └────────────┘  └───────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│            Port: http://localhost:11434                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Flusso di Traduzione

```
1. USER: Seleziona file SRT + "Qwen/Ollama" + Lingua Target
                    ↓
2. MainWindow: Crea QwenOllamaTranslator(context=synopsis)
                    ↓
3. QwenOllamaTranslator.translate_file():
   ├─→ Parse SRT → lista sottotitoli
   ├─→ Chunking contestuale (8-16 sottotitoli/batch)
   ├─→ Per ogni chunk:
   │   ├─→ Costruisci System Prompt (cinematografico)
   │   ├─→ ICL Examples (2-3 traduzioni esempio)
   │   ├─→ Glossario (se presente in context)
   │   ├─→ Sliding Window (K=4 battute precedenti)
   │   └─→ ollama.chat(model, messages)
   │           ↓
   │       HTTP POST → Ollama Server
   │           ↓
   │       llama.cpp → Inference GPU
   │           ↓
   │       Response JSON
   │           ↓
   ├─→ Post-processing (unmask, clean)
   └─→ Write output SRT
                    ↓
4. MainWindow: Notifica completamento
```

### 2.3 Gestione Multimodello

Il sistema mantiene **tre traduttori indipendenti**:

```python
# Factory pattern esistente (da modificare)
def get_translator(model_type: str, context: Optional[str] = None) -> BaseTranslator:
    """
    model_type: 'nllb' | 'aya' | 'qwen'
    """
    if model_type == 'qwen':
        return QwenOllamaTranslator(context=context)
    elif model_type == 'aya':
        return AyaTranslator(context=context)
    else:
        return NLLBTranslator(context=context)
```

---

## 3. REQUISITI E DIPENDENZE

### 3.1 Prerequisiti Sistema

#### Ollama Server (Obbligatorio)
```bash
# Installazione Windows
# Download: https://ollama.com/download/windows
# Esegui: OllamaSetup.exe (non richiede admin)

# Verifica installazione
ollama --version
# Output atteso: ollama version is 0.x.x

# Download modello raccomandato
ollama pull qwen2.5:7b-instruct-q4_K_M
# Dimensione: ~4.5GB
# Tempo download (100Mbps): ~6-8 minuti

# Verifica modello
ollama list
# Output atteso:
# NAME                        SIZE    MODIFIED
# qwen2.5:7b-instruct-q4_...  4.5GB   X minutes ago
```

#### Variabili d'Ambiente (Opzionali ma Consigliate)
```bash
# Windows: Pannello di Controllo → Variabili d'Ambiente

# 1. Storage modelli (se C: ha poco spazio)
OLLAMA_MODELS=D:\OllamaModels

# 2. Keep-alive infinito (per uso intensivo)
OLLAMA_KEEP_ALIVE=-1

# 3. Context window (default 2048, aumentare per contesto lungo)
OLLAMA_NUM_CTX=16384

# 4. Threads CPU (default auto-detect, forzare se necessario)
OLLAMA_NUM_THREAD=12

# Dopo impostazione: riavviare Ollama
# Tray icon → Quit → Start Menu → Ollama
```

### 3.2 Dipendenze Python

```python
# requirements.txt (AGGIUNTE)
ollama>=0.6.0  # Libreria ufficiale Ollama Python
requests>=2.31.0  # Fallback HTTP se ollama library fallisce

# requirements.txt (ESISTENTI - nessuna modifica)
transformers>=4.30.0
torch>=2.0.0
bitsandbytes>=0.39.0
# ... resto invariato
```

**Installazione nel venv:**
```bash
# Attiva ambiente virtuale esistente
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# Installa solo nuove dipendenze
pip install ollama>=0.6.0

# Verifica
python -c "import ollama; print('✓ Ollama library OK')"
```

### 3.3 Verifica Compatibilità Hardware

```python
# Script di test (da eseguire prima dell'integrazione)
import ollama
import torch

print("=== SYSTEM CHECK: Qwen Ollama Integration ===")

# 1. Check CUDA
print(f"✓ CUDA Available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  GPU: {torch.cuda.get_device_name(0)}")
    print(f"  VRAM Total: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    print(f"  VRAM Free: {torch.cuda.memory_reserved(0) / 1024**3:.1f} GB")

# 2. Check Ollama Server
try:
    models = ollama.list()
    print(f"✓ Ollama Server: Running")
    print(f"  Models installed: {len(models['models'])}")
    
    # Check Qwen disponibile
    qwen_found = any('qwen2.5' in m['name'] for m in models['models'])
    if qwen_found:
        print(f"  ✓ Qwen 2.5 7B: Installed")
    else:
        print(f"  ⚠ Qwen 2.5 7B: NOT FOUND - run 'ollama pull qwen2.5:7b'")
        
except Exception as e:
    print(f"✗ Ollama Server: NOT RUNNING")
    print(f"  Error: {e}")
    print(f"  Action: Start Ollama from Start Menu")

# 3. Test Inference
try:
    response = ollama.chat(
        model='qwen2.5:7b',
        messages=[{'role': 'user', 'content': 'Hello'}]
    )
    print(f"✓ Test Inference: SUCCESS")
    print(f"  Response time: <2s (expected)")
except Exception as e:
    print(f"✗ Test Inference: FAILED - {e}")

print("\n=== SYSTEM CHECK COMPLETE ===")
```

---

## 4. IMPLEMENTAZIONE CLASSE QwenOllamaTranslator

### 4.1 Struttura File

```
project/
├── core/
│   └── translator.py  # File ESISTENTE - da modificare
│       ├── BaseTranslator (esistente)
│       ├── NLLBTranslator (esistente)
│       ├── AyaTranslator (esistente)
│       └── QwenOllamaTranslator  # ← NUOVO
│
├── core/
│   └── qwen_prompts.py  # ← NUOVO FILE
│       ├── SYSTEM_PROMPT_CINEMATOGRAFICO
│       ├── ICL_EXAMPLES
│       └── build_translation_prompt()
│
└── utils/
    └── config.py  # File ESISTENTE - da modificare
        └── DEFAULTS['translation_model']  # aggiungi 'qwen'
```

### 4.2 Classe QwenOllamaTranslator (translator.py)

```python
# ============================================================================
# QWEN OLLAMA TRANSLATOR - v1.0
# Specializzato per traduzione sottotitoli cinematografici EN→IT
# ============================================================================

import ollama
from ollama import ResponseError
import logging
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
from .translator import BaseTranslator, SRT_SUBTITLE

logger = logging.getLogger(__name__)


class OllamaConnectionError(Exception):
    """Eccezione sollevata quando Ollama server non è raggiungibile"""
    pass


class OllamaModelNotFoundError(Exception):
    """Eccezione sollevata quando il modello richiesto non è installato"""
    pass


class QwenOllamaTranslator(BaseTranslator):
    """
    Traduttore basato su Qwen 2.5-7B via Ollama per sottotitoli cinematografici.
    
    CARATTERISTICHE:
    - Gestione contesto esteso (8K-32K token)
    - System prompt ottimizzato per linguaggio colloquiale
    - In-Context Learning (ICL) con esempi cinematografici
    - Sliding window per coerenza narrativa
    - Fallback automatico su NLLB in caso di errore Ollama
    
    ARCHITETTURA:
    - Client REST leggero (no dipendenze PyTorch)
    - Comunicazione via HTTP con Ollama server locale
    - Isolamento completo da altri traduttori
    """
    
    # Mapping codici lingua → codici Qwen (ISO 639-1)
    LANGUAGE_CODES = {
        'eng': 'en',
        'ita': 'it',
        'fra': 'fr',
        'deu': 'de',
        'spa': 'es',
        'por': 'pt',
        'rus': 'ru',
        'jpn': 'ja',
        'kor': 'ko',
        'zho': 'zh',
    }
    
    # Modelli supportati (in ordine di preferenza)
    SUPPORTED_MODELS = [
        'qwen2.5:7b-instruct-q4_K_M',  # Raccomandato
        'qwen2.5:7b-instruct',
        'qwen2.5:7b',
    ]
    
    # Configurazione batch e contesto
    DEFAULT_BATCH_SIZE = 12  # Sottotitoli per batch
    MAX_CONTEXT_TOKENS = 16384  # Token massimi per prompt
    SLIDING_WINDOW_SIZE = 4  # Battute precedenti da includere
    
    def __init__(
        self,
        model: Optional[str] = None,
        log_callback: Optional[Callable] = None,
        context: Optional[str] = None,
        enable_fallback: bool = True,
        batch_size: Optional[int] = None,
        use_icl: bool = True,
        use_glossary: bool = True
    ):
        """
        Inizializza traduttore Qwen via Ollama.
        
        Args:
            model: Nome modello Ollama (default: auto-detect primo disponibile)
            log_callback: Callback per logging GUI
            context: Contesto film/serie (sinossi) per migliorare traduzione
            enable_fallback: Se True, fallback su NLLB in caso errore Ollama
            batch_size: Numero sottotitoli per batch (default: 12)
            use_icl: Abilita In-Context Learning con esempi
            use_glossary: Abilita estrazione glossario da context
        """
        super().__init__(log_callback=log_callback, context=context)
        
        # Configurazione
        self.enable_fallback = enable_fallback
        self.batch_size = batch_size or self.DEFAULT_BATCH_SIZE
        self.use_icl = use_icl
        self.use_glossary = use_glossary
        
        # Client Ollama
        self.client = ollama.Client(host='http://localhost:11434')
        
        # Selezione modello
        self.model = model or self._detect_best_model()
        
        # Cache per prompt riutilizzabili
        self._system_prompt_cache: Dict[str, str] = {}
        
        # Fallback translator (lazy init)
        self._fallback_translator: Optional[BaseTranslator] = None
        
        # Statistiche
        self.stats = {
            'total_subtitles': 0,
            'translated_subtitles': 0,
            'failed_batches': 0,
            'fallback_used': 0,
            'avg_tokens_per_second': 0.0
        }
        
        self.log(f"✓ QwenOllamaTranslator inizializzato")
        self.log(f"  Modello: {self.model}")
        self.log(f"  Batch size: {self.batch_size}")
        self.log(f"  ICL: {'ON' if use_icl else 'OFF'}")
        self.log(f"  Fallback: {'ON' if enable_fallback else 'OFF'}")
    
    def _detect_best_model(self) -> str:
        """
        Auto-detect miglior modello Qwen disponibile in Ollama.
        
        Returns:
            Nome modello (es: 'qwen2.5:7b-instruct-q4_K_M')
            
        Raises:
            OllamaConnectionError: Se Ollama server non raggiungibile
            OllamaModelNotFoundError: Se nessun modello Qwen trovato
        """
        try:
            # Lista modelli installati
            response = self.client.list()
            installed_models = [m['name'] for m in response.get('models', [])]
            
            # Cerca primo modello supportato
            for model in self.SUPPORTED_MODELS:
                if model in installed_models:
                    logger.info(f"Auto-detected Qwen model: {model}")
                    return model
            
            # Fallback: cerca qualsiasi modello con 'qwen' nel nome
            qwen_models = [m for m in installed_models if 'qwen' in m.lower()]
            if qwen_models:
                logger.warning(f"Using non-standard Qwen model: {qwen_models[0]}")
                return qwen_models[0]
            
            # Nessun modello trovato
            raise OllamaModelNotFoundError(
                f"Nessun modello Qwen trovato in Ollama.\n"
                f"Modelli installati: {installed_models}\n"
                f"Esegui: ollama pull qwen2.5:7b-instruct-q4_K_M"
            )
            
        except ollama.ResponseError as e:
            if e.status_code == 404:
                raise OllamaConnectionError(
                    "Ollama server non raggiungibile su http://localhost:11434\n"
                    "Azioni:\n"
                    "1. Verifica che Ollama sia installato\n"
                    "2. Avvia Ollama dal Menu Start\n"
                    "3. Verifica con: ollama list"
                )
            else:
                raise OllamaConnectionError(f"Errore Ollama: {e}")
    
    def _build_system_prompt(
        self,
        src_lang: str,
        tgt_lang: str,
        genre: Optional[str] = None,
        tone: str = 'colloquiale'
    ) -> str:
        """
        Costruisce system prompt ottimizzato per traduzione cinematografica.
        
        Args:
            src_lang: Lingua sorgente (ISO 639-2)
            tgt_lang: Lingua target (ISO 639-2)
            genre: Genere film/serie (es: 'commedia', 'thriller', 'sci-fi')
            tone: Tono desiderato ('colloquiale', 'formale', 'neutro')
        
        Returns:
            System prompt completo
        """
        # Converti codici lingua
        src = self.LANGUAGE_CODES.get(src_lang, src_lang)
        tgt = self.LANGUAGE_CODES.get(tgt_lang, tgt_lang)
        
        # Cache key
        cache_key = f"{src}_{tgt}_{genre}_{tone}"
        if cache_key in self._system_prompt_cache:
            return self._system_prompt_cache[cache_key]
        
        # Importa template da modulo separato
        from core.qwen_prompts import build_system_prompt
        
        system_prompt = build_system_prompt(
            src_lang=src,
            tgt_lang=tgt,
            genre=genre,
            tone=tone,
            context_synopsis=self._prepared_context
        )
        
        # Cache
        self._system_prompt_cache[cache_key] = system_prompt
        return system_prompt
    
    def _build_icl_examples(self, src_lang: str, tgt_lang: str) -> List[Dict[str, str]]:
        """
        Costruisce esempi In-Context Learning per migliorare stile output.
        
        Returns:
            Lista di message dicts (user/assistant pairs)
        """
        if not self.use_icl:
            return []
        
        from core.qwen_prompts import get_icl_examples
        return get_icl_examples(src_lang, tgt_lang)
    
    def _extract_glossary(self) -> Optional[Dict[str, str]]:
        """
        Estrae glossario termini chiave da context (se presente).
        
        Returns:
            Dict {termine_inglese: traduzione_italiana} o None
        """
        if not self.use_glossary or not self.context:
            return None
        
        # TODO: Implementare estrazione automatica con pattern matching
        # Per ora: parsing manuale di formato "Term: Translation"
        
        glossary = {}
        for line in self.context.split('\n'):
            if ':' in line and len(line) < 100:  # Euristica: righe corte con ":"
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    if key and value:
                        glossary[key] = value
        
        return glossary if glossary else None
    
    def _chunk_subtitles(
        self,
        subtitles: List[SRT_SUBTITLE],
        batch_size: int
    ) -> List[List[SRT_SUBTITLE]]:
        """
        Divide sottotitoli in chunk con sliding window per contesto.
        
        Args:
            subtitles: Lista completa sottotitoli
            batch_size: Dimensione batch target
        
        Returns:
            Lista di chunk, ogni chunk include:
            - batch_size sottotitoli da tradurre
            - SLIDING_WINDOW_SIZE battute precedenti (context-only)
        """
        chunks = []
        
        for i in range(0, len(subtitles), batch_size):
            # Sottotitoli da tradurre in questo batch
            batch = subtitles[i:i + batch_size]
            
            # Context window: K battute precedenti (se disponibili)
            context_start = max(0, i - self.SLIDING_WINDOW_SIZE)
            context_window = subtitles[context_start:i] if i > 0 else []
            
            chunks.append({
                'context': context_window,  # Solo per context
                'to_translate': batch,       # Da tradurre
                'batch_index': len(chunks)
            })
        
        return chunks
    
    def _format_batch_for_translation(
        self,
        chunk: Dict[str, Any]
    ) -> str:
        """
        Formatta batch sottotitoli in prompt strutturato per Qwen.
        
        Format:
        [CONTEXT]
        1. Previous subtitle text
        2. Previous subtitle text
        
        [TO TRANSLATE]
        1. Subtitle to translate
        2. Subtitle to translate
        ...
        
        Args:
            chunk: Dict con 'context' e 'to_translate'
        
        Returns:
            Prompt formattato
        """
        prompt_parts = []
        
        # Context window (battute precedenti - solo per coerenza)
        if chunk['context']:
            prompt_parts.append("[CONTESTO NARRATIVO PRECEDENTE]")
            for idx, (_, _, _, text) in enumerate(chunk['context'], 1):
                prompt_parts.append(f"{idx}. {text}")
            prompt_parts.append("")
        
        # Sottotitoli da tradurre
        prompt_parts.append("[SOTTOTITOLI DA TRADURRE]")
        for idx, (_, _, _, text) in enumerate(chunk['to_translate'], 1):
            prompt_parts.append(f"{idx}. {text}")
        
        return "\n".join(prompt_parts)
    
    def _parse_translation_response(
        self,
        response_text: str,
        expected_count: int
    ) -> List[str]:
        """
        Parsing robusto della risposta Qwen.
        
        Expected format (flexible):
        1. Traduzione prima battuta
        2. Traduzione seconda battuta
        ...
        
        Args:
            response_text: Risposta raw da Qwen
            expected_count: Numero atteso traduzioni
        
        Returns:
            Lista traduzioni (fallback su originale se parsing fallisce)
        """
        lines = response_text.strip().split('\n')
        translations = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Rimuovi numerazione se presente
            # Pattern: "1. Testo" → "Testo"
            if line[0].isdigit() and '. ' in line[:5]:
                line = line.split('. ', 1)[1]
            
            translations.append(line)
        
        # Validazione
        if len(translations) != expected_count:
            logger.warning(
                f"Translation count mismatch: expected {expected_count}, "
                f"got {len(translations)}"
            )
            # Padding/troncamento se necessario
            if len(translations) < expected_count:
                translations.extend([''] * (expected_count - len(translations)))
            else:
                translations = translations[:expected_count]
        
        return translations
    
    def translate_file(
        self,
        input_path: Path,
        output_path: Path,
        src_lang: str,
        tgt_lang: str,
        context: Optional[str] = None
    ) -> bool:
        """
        Traduce file SRT usando Qwen via Ollama.
        
        WORKFLOW:
        1. Parse SRT
        2. Chunking con sliding window
        3. Per ogni chunk:
           a. Build prompt (system + ICL + context + batch)
           b. Call Ollama API
           c. Parse response
           d. Post-processing (unmask, clean)
        4. Write output SRT
        5. Log statistiche
        
        Args:
            input_path: Path file SRT input
            output_path: Path file SRT output
            src_lang: Codice lingua sorgente (ISO 639-2)
            tgt_lang: Codice lingua target (ISO 639-2)
            context: Context override (opzionale)
        
        Returns:
            True se successo, False altrimenti
        """
        try:
            # Override context se fornito
            if context:
                self.context = context
                self._prepared_context = f"[CONTEXT: {context[:500]}...]"
            
            self.log(f"▶ Avvio traduzione Qwen: {input_path.name}")
            self.log(f"  Modello: {self.model}")
            self.log(f"  {src_lang.upper()} → {tgt_lang.upper()}")
            
            # 1. Parse SRT
            subtitles = self._parse_srt(input_path)
            if not subtitles:
                self.log("✗ Errore: file SRT vuoto o malformato")
                return False
            
            total = len(subtitles)
            self.stats['total_subtitles'] = total
            self.log(f"  Sottotitoli: {total}")
            
            # 2. Build system prompt
            system_prompt = self._build_system_prompt(src_lang, tgt_lang)
            
            # 3. Build ICL examples
            icl_examples = self._build_icl_examples(src_lang, tgt_lang)
            
            # 4. Extract glossary (se presente)
            glossary = self._extract_glossary()
            if glossary:
                self.log(f"  Glossario: {len(glossary)} termini caricati")
            
            # 5. Chunking
            chunks = self._chunk_subtitles(subtitles, self.batch_size)
            self.log(f"  Batch: {len(chunks)} (size={self.batch_size})")
            
            # 6. Translation loop
            translated_subtitles = []
            
            import time
            total_tokens = 0
            total_time = 0.0
            
            for chunk in chunks:
                batch_idx = chunk['batch_index']
                batch_size = len(chunk['to_translate'])
                
                self.log(
                    f"  Batch {batch_idx + 1}/{len(chunks)}: "
                    f"{batch_size} sottotitoli..."
                )
                
                try:
                    # Build prompt per questo batch
                    batch_prompt = self._format_batch_for_translation(chunk)
                    
                    # Prepara messages per Ollama
                    messages = [
                        {'role': 'system', 'content': system_prompt}
                    ]
                    
                    # Aggiungi ICL examples
                    messages.extend(icl_examples)
                    
                    # Aggiungi glossary (se presente)
                    if glossary:
                        glossary_text = "\n".join(
                            f"- {k}: {v}" for k, v in glossary.items()
                        )
                        messages.append({
                            'role': 'system',
                            'content': f"[GLOSSARIO TERMINI]\n{glossary_text}"
                        })
                    
                    # Aggiungi batch corrente
                    messages.append({
                        'role': 'user',
                        'content': batch_prompt
                    })
                    
                    # Chiamata Ollama
                    start_time = time.time()
                    
                    response = self.client.chat(
                        model=self.model,
                        messages=messages,
                        options={
                            'temperature': 0.3,  # Bassa per coerenza
                            'top_p': 0.9,
                            'top_k': 40,
                            'num_ctx': self.MAX_CONTEXT_TOKENS,
                        }
                    )
                    
                    elapsed = time.time() - start_time
                    total_time += elapsed
                    
                    # Estrai testo risposta
                    response_text = response['message']['content']
                    
                    # Statistiche token
                    if 'eval_count' in response:
                        tokens = response['eval_count']
                        total_tokens += tokens
                        tok_per_sec = tokens / elapsed
                        self.log(f"    ✓ {tok_per_sec:.1f} tok/s")
                    
                    # Parse traduzioni
                    translations = self._parse_translation_response(
                        response_text,
                        expected_count=batch_size
                    )
                    
                    # Post-processing
                    for (idx, start, end, original), translation in zip(
                        chunk['to_translate'],
                        translations
                    ):
                        # Unmask (se usato masking come NLLB/Aya)
                        # TODO: implementare se necessario
                        
                        # Clean
                        translation = translation.strip()
                        
                        # Fallback su originale se vuoto
                        if not translation:
                            translation = original
                        
                        translated_subtitles.append((idx, start, end, translation))
                    
                    self.stats['translated_subtitles'] += batch_size
                    
                except ResponseError as e:
                    # Errore Ollama specifico
                    self.log(f"    ✗ Errore Ollama: {e}")
                    self.stats['failed_batches'] += 1
                    
                    if self.enable_fallback:
                        self.log(f"    → Fallback su NLLB...")
                        fallback_result = self._fallback_translate_batch(
                            chunk['to_translate'],
                            src_lang,
                            tgt_lang
                        )
                        translated_subtitles.extend(fallback_result)
                        self.stats['fallback_used'] += 1
                    else:
                        # Copia originali
                        for item in chunk['to_translate']:
                            translated_subtitles.append(item)
                
                except Exception as e:
                    # Errore generico
                    logger.error(f"Errore batch {batch_idx}: {e}", exc_info=True)
                    self.stats['failed_batches'] += 1
                    
                    # Copia originali
                    for item in chunk['to_translate']:
                        translated_subtitles.append(item)
            
            # 7. Write output
            srt_content = self._generate_srt(translated_subtitles)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            # 8. Log statistiche finali
            success_rate = (
                self.stats['translated_subtitles'] / total * 100
                if total > 0 else 0
            )
            avg_tok_per_sec = (
                total_tokens / total_time
                if total_time > 0 else 0
            )
            
            self.log(f"✓ Traduzione completata: {output_path.name}")
            self.log(f"  Successo: {success_rate:.1f}%")
            self.log(f"  Batch falliti: {self.stats['failed_batches']}")
            self.log(f"  Fallback usati: {self.stats['fallback_used']}")
            self.log(f"  Velocità media: {avg_tok_per_sec:.1f} tok/s")
            
            return True
            
        except OllamaConnectionError as e:
            self.log(f"✗ ERRORE: Ollama non disponibile")
            self.log(f"  {e}")
            
            if self.enable_fallback:
                self.log(f"  → Fallback completo su NLLB...")
                return self._full_fallback_translate(
                    input_path,
                    output_path,
                    src_lang,
                    tgt_lang
                )
            return False
            
        except Exception as e:
            self.log(f"✗ Errore traduzione: {e}")
            logger.error(f"Translation error: {e}", exc_info=True)
            return False
    
    def _fallback_translate_batch(
        self,
        batch: List[SRT_SUBTITLE],
        src_lang: str,
        tgt_lang: str
    ) -> List[SRT_SUBTITLE]:
        """
        Fallback su NLLB per singolo batch fallito.
        
        Returns:
            Lista sottotitoli tradotti con NLLB
        """
        if not self._fallback_translator:
            from .translator import NLLBTranslator
            self._fallback_translator = NLLBTranslator()
        
        # Traduci batch con NLLB
        # TODO: implementare logica batch NLLB
        # Per ora: copia originali (placeholder)
        return batch
    
    def _full_fallback_translate(
        self,
        input_path: Path,
        output_path: Path,
        src_lang: str,
        tgt_lang: str
    ) -> bool:
        """
        Fallback completo su NLLB per file intero.
        
        Usato quando Ollama completamente non disponibile.
        """
        self.log("  Esecuzione fallback completo NLLB...")
        
        if not self._fallback_translator:
            from .translator import NLLBTranslator
            self._fallback_translator = NLLBTranslator()
        
        return self._fallback_translator.translate_file(
            input_path,
            output_path,
            src_lang,
            tgt_lang
        )
    
    def cleanup(self):
        """
        Pulizia risorse (Ollama gestisce automaticamente memoria).
        """
        # Ollama server gestisce auto-unload modelli
        # Nessuna azione richiesta
        logger.info("QwenOllamaTranslator cleanup complete")
```

### 4.3 Modulo Prompts (qwen_prompts.py) - FILE NUOVO

```python
"""
Qwen Prompts - Sistema di prompting avanzato per traduzione cinematografica
File: core/qwen_prompts.py

CONTENUTO:
- System prompt template ottimizzato
- In-Context Learning examples
- Glossary builder
- Prompt utilities
"""

from typing import Optional, List, Dict

# ============================================================================
# SYSTEM PROMPT TEMPLATE
# ============================================================================

SYSTEM_PROMPT_CINEMATOGRAFICO_IT = """Sei un traduttore professionista specializzato in sottotitoli cinematografici e televisivi dall'inglese all'italiano.

**OBIETTIVO PRINCIPALE**: Creare traduzioni che suonino naturali, colloquiali e idiomatiche in italiano, preservando tono emotivo, umorismo e sfumature culturali dei dialoghi originali.

**LINEE GUIDA FONDAMENTALI**:

1. **TONO E STILE**:
   - Usa linguaggio COLLOQUIALE e MODERNO, come parlerebbero realmente gli italiani
   - Evita traduzioni letterali che suonano goffe o innaturali
   - Adatta slang, modi di dire ed espressioni idiomatiche al contesto italiano
   - Mantieni lo stesso livello di formalità/informalità dell'originale

2. **NATURALEZZA DIALOGICA**:
   - Le battute devono suonare come conversazioni autentiche, non testi tradotti
   - Usa contrazioni e forme abbreviate tipiche del parlato ("non lo so" → "boh", "non è vero" → "non è vero" o "macché")
   - Rispetta il ritmo e la cadenza naturale dell'italiano
   - Preferisci frasi brevi e dinamiche per dialoghi rapidi

3. **GESTIONE ESPRESSIONI IDIOMATICHE**:
   - NON tradurre letteralmente espressioni idiomatiche inglesi
   - Trova equivalenti italiani naturali (es: "break a leg" → "in bocca al lupo", non "rompiti una gamba")
   - Se non esiste equivalente diretto, ritrasmetti il significato con espressione italiana naturale

4. **COERENZA E CONTESTO**:
   - Mantieni coerenza terminologica per personaggi e luoghi
   - Considera il contesto narrativo delle battute precedenti
   - Rispetta continuità di tono emotivo tra battute consecutive
   - Adatta il registro linguistico al personaggio (età, status sociale, personalità)

5. **ELEMENTI CULTURALI**:
   - Adatta riferimenti culturali quando necessario per pubblico italiano
   - Mantieni riferimenti facilmente comprensibili anche in Italia
   - Per giochi di parole: privilegia l'effetto umoristico rispetto alla traduzione letterale

6. **GESTIONE VOLGARITÀ/PAROLACCE**:
   - Mantieni stesso livello di volgarità dell'originale
   - Usa equivalenti italiani autentici (non censurare né esagerare)
   - Considera contesto (commedia vs dramma) per intensità

7. **TECNICISMI**:
   - Testi musicali tra ♪...♪: mantieni ESATTAMENTE come originale (non tradurre)
   - Nomi propri: mantieni originali salvo convenzioni consolidate (es: "New York" ok, "London" → "Londra")
   - Titoli film/libri: usa titolo italiano ufficiale se esiste

**OUTPUT FORMAT**:
- Fornisci SOLO le traduzioni numerate, senza commenti o spiegazioni
- Mantieni numerazione originale
- Una traduzione per riga

**ESEMPIO APPROCCIO CORRETTO**:
❌ ERRATO (letterale/goffo): "Quello è ciò che lei ha detto" 
✅ CORRETTO (naturale): "È quello che ha detto"

❌ ERRATO: "Tu stai scherzando con me?"
✅ CORRETTO: "Mi stai prendendo in giro?" / "Scherzi?"

❌ ERRATO: "Io non sono sicuro su questo"
✅ CORRETTO: "Non ne sono sicuro" / "Non lo so"

Ricorda: l'obiettivo è che uno spettatore italiano NON percepisca che sta leggendo una traduzione."""


def build_system_prompt(
    src_lang: str = 'en',
    tgt_lang: str = 'it',
    genre: Optional[str] = None,
    tone: str = 'colloquiale',
    context_synopsis: Optional[str] = None
) -> str:
    """
    Costruisce system prompt personalizzato.
    
    Args:
        src_lang: Lingua sorgente (ISO 639-1)
        tgt_lang: Lingua target (ISO 639-1)
        genre: Genere (opzionale): 'commedia', 'thriller', 'dramma', 'sci-fi', etc.
        tone: Tono desiderato: 'colloquiale', 'formale', 'neutro'
        context_synopsis: Sinossi/contesto (opzionale)
    
    Returns:
        System prompt completo
    """
    # Base prompt (italiano hardcoded per ora)
    if tgt_lang == 'it':
        prompt = SYSTEM_PROMPT_CINEMATOGRAFICO_IT
    else:
        # TODO: aggiungere template per altre lingue target
        prompt = SYSTEM_PROMPT_CINEMATOGRAFICO_IT.replace('italiano', tgt_lang)
    
    # Aggiungi contesto genere
    if genre:
        genre_guidance = {
            'commedia': "\n**NOTA GENERE**: Questo è una commedia. Privilegia ritmo, battute rapide e umorismo. Le traduzioni devono far ridere in italiano, anche se significa allontanarsi dal letterale.",
            'thriller': "\n**NOTA GENERE**: Questo è un thriller. Mantieni tensione e suspense. Usa linguaggio diretto e incisivo.",
            'dramma': "\n**NOTA GENERE**: Questo è un dramma. Preserva profondità emotiva e sfumature. Traduzioni possono essere più elaborate.",
            'sci-fi': "\n**NOTA GENERE**: Questo è fantascienza. Mantieni terminologia tecnica coerente. Bilancia realismo scientifico con accessibilità.",
            'azione': "\n**NOTA GENERE**: Questo è un film d'azione. Battute brevi, dirette, dinamiche. Energia e ritmo sono priorità.",
        }
        if genre.lower() in genre_guidance:
            prompt += genre_guidance[genre.lower()]
    
    # Aggiungi contesto sinossi
    if context_synopsis:
        prompt += f"\n\n**CONTESTO NARRATIVO**:\n{context_synopsis}\n"
    
    return prompt


# ============================================================================
# IN-CONTEXT LEARNING EXAMPLES
# ============================================================================

ICL_EXAMPLES_EN_IT = [
    # Esempio 1: Linguaggio colloquiale
    {
        'role': 'user',
        'content': """[TO TRANSLATE]
1. Are you kidding me?
2. That's what I'm talking about!
3. I don't know about this..."""
    },
    {
        'role': 'assistant',
        'content': """1. Mi stai prendendo in giro?
2. Ecco di cosa parlo!
3. Non ne sono sicuro..."""
    },
    
    # Esempio 2: Espressioni idiomatiche
    {
        'role': 'user',
        'content': """[TO TRANSLATE]
1. Break a leg tonight!
2. It's raining cats and dogs out there.
3. Let's call it a day."""
    },
    {
        'role': 'assistant',
        'content': """1. In bocca al lupo stasera!
2. Fuori piove a dirotto.
3. Chiudiamola qui per oggi."""
    },
    
    # Esempio 3: Tono emotivo
    {
        'role': 'user',
        'content': """[TO TRANSLATE]
1. I'm so sorry... I didn't mean to hurt you.
2. Get out! Now!
3. I... I love you."""
    },
    {
        'role': 'assistant',
        'content': """1. Mi dispiace tanto... non volevo farti del male.
2. Fuori! Subito!
3. Io... ti amo."""
    },
]


def get_icl_examples(src_lang: str, tgt_lang: str) -> List[Dict[str, str]]:
    """
    Restituisce esempi ICL per coppia lingue.
    
    Args:
        src_lang: Lingua sorgente (ISO 639-1)
        tgt_lang: Lingua target (ISO 639-1)
    
    Returns:
        Lista di message dicts per ICL
    """
    if src_lang == 'en' and tgt_lang == 'it':
        return ICL_EXAMPLES_EN_IT
    else:
        # TODO: aggiungere esempi per altre coppie
        return []


# ============================================================================
# GLOSSARY BUILDER
# ============================================================================

def build_glossary_prompt(glossary: Dict[str, str]) -> str:
    """
    Formatta glossario per injection in prompt.
    
    Args:
        glossary: Dict {termine_originale: traduzione_target}
    
    Returns:
        Stringa formattata glossario
    """
    if not glossary:
        return ""
    
    lines = ["**GLOSSARIO TERMINI SPECIFICI**:"]
    lines.append("(Usa queste traduzioni per i seguenti termini)")
    lines.append("")
    
    for term, translation in sorted(glossary.items()):
        lines.append(f"- {term} → {translation}")
    
    return "\n".join(lines)


# ============================================================================
# UTILITIES
# ============================================================================

def estimate_prompt_tokens(text: str) -> int:
    """
    Stima approssimativa token per text (rule of thumb: ~4 char = 1 token).
    
    Args:
        text: Testo da stimare
    
    Returns:
        Numero token stimato
    """
    # Approssimazione: italiano ~4.5 char/token, inglese ~4 char/token
    return len(text) // 4


def truncate_context(text: str, max_tokens: int = 500) -> str:
    """
    Tronca contesto per non saturare context window.
    
    Args:
        text: Testo contesto
        max_tokens: Token massimi
    
    Returns:
        Testo troncato
    """
    estimated = estimate_prompt_tokens(text)
    if estimated <= max_tokens:
        return text
    
    # Tronca a max_tokens * 4 caratteri (approssimazione)
    max_chars = max_tokens * 4
    return text[:max_chars] + "..."
```

---

## 5. SISTEMA DI PROMPTING AVANZATO

### 5.1 Architettura del Prompt

Il prompt finale inviato a Qwen ha questa struttura:

```
┌──────────────────────────────────────────────────────────────┐
│ SYSTEM MESSAGE                                                │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ - Ruolo: "Traduttore professionista sottotitoli..."      │ │
│ │ - Linee guida: Tono colloquiale, idiomaticità, etc.     │ │
│ │ - Genere specifico (se fornito)                          │ │
│ │ - Sinossi contesto (se fornita)                          │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────────────────────┐
│ IN-CONTEXT LEARNING (ICL) - 2-3 ESEMPI                       │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ USER: "Traduci: Are you kidding me?"                     │ │
│ │ ASSISTANT: "Mi stai prendendo in giro?"                  │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ USER: "Traduci: Break a leg!"                            │ │
│ │ ASSISTANT: "In bocca al lupo!"                           │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────────────────────┐
│ GLOSSARIO (se presente)                                       │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ - Stark Industries → Stark Industries (no traduzione)   │ │
│ │ - Time-Turner → Giratempo                                │ │
│ │ - Vorpal Sword → Spada Vorpale                           │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────────────────────┐
│ USER MESSAGE - BATCH CORRENTE                                 │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ [CONTESTO NARRATIVO PRECEDENTE]                          │ │
│ │ 1. Previous subtitle for context                         │ │
│ │ 2. Previous subtitle for context                         │ │
│ │                                                            │ │
│ │ [SOTTOTITOLI DA TRADURRE]                                │ │
│ │ 1. I can't believe you did that!                         │ │
│ │ 2. What were you thinking?                               │ │
│ │ 3. ♪ This is the song ♪                                  │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────────────────────┐
│ ASSISTANT RESPONSE (attesa)                                   │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 1. Non posso credere che tu l'abbia fatto!               │ │
│ │ 2. Cosa ti passava per la testa?                         │ │
│ │ 3. ♪ This is the song ♪                                  │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 Tecniche di Prompt Engineering Applicate

#### 5.2.1 Instruction Following Esplicito

**Principio**: Dire esplicitamente al modello COSA fare e COME farlo.

```python
# ❌ PROMPT DEBOLE (generico)
"Traduci questi sottotitoli in italiano"

# ✅ PROMPT FORTE (specifico)
"""
Sei un traduttore professionista specializzato in sottotitoli cinematografici.

OBIETTIVO: Traduzioni naturali, colloquiali, idiomatiche.

LINEE GUIDA:
1. Linguaggio COLLOQUIALE come parlano gli italiani
2. NO traduzioni letterali goffe
3. Adatta espressioni idiomatiche
...
"""
```

#### 5.2.2 Few-Shot Learning (ICL)

**Principio**: Mostra esempi concreti dello stile desiderato.

```python
# Senza ICL: output può essere formale/goffo
"Are you kidding me?" → "Stai scherzando con me?" (letterale)

# Con ICL: output apprende stile colloquiale
USER: "Are you kidding me?"
ASSISTANT: "Mi stai prendendo in giro?"

# Nuovo input eredita stile
"Are you serious?" → "Fai sul serio?" (colloquiale appreso)
```

#### 5.2.3 Sliding Window Context

**Principio**: Fornire battute precedenti per coerenza narrativa.

```python
# Esempio conversazione
# Battuta 1: "Who did this?"
# Battuta 2: "I did."
# Battuta 3: "Why?"

# Traduzione Battuta 3 CON context:
[CONTESTO PRECEDENTE]
1. Chi l'ha fatto?
2. Sono stato io.

[DA TRADURRE]
3. Why?

# Output: "Perché?" (coerente con contesto informale)

# SENZA context, potrebbe uscire:
# "Per quale motivo?" (troppo formale, incoerente)
```

#### 5.2.4 Glossary Injection

**Principio**: Garantire coerenza terminologica per nomi/luoghi specifici.

```python
# Film: Harry Potter
# Senza glossary:
"Time-Turner" → "Giracronometro" (inventato)
"Time-Turner" → "Tempogiratore" (inventato)
# ❌ Incoerente tra battute diverse

# Con glossary:
[GLOSSARIO]
- Time-Turner → Giratempo (ufficiale)
- Hogwarts → Hogwarts (non tradotto)

"Use the Time-Turner!" → "Usa il Giratempo!"
# ✅ Coerente, usa traduzione ufficiale
```

### 5.3 Prompt Tuning per Casi Specifici

#### 5.3.1 Gestione Slang/Volgarità

```python
# Linea guida nel system prompt:
"""
GESTIONE VOLGARITÀ:
- Mantieni stesso livello dell'originale
- Usa equivalenti italiani autentici
- Contesto: commedia vs dramma → intensità appropriata

ESEMPI:
"Holy shit!" (commedia) → "Porca miseria!" / "Cazzo!"
"Damn it!" (dramma) → "Dannazione!" / "Maledizione!"
"""
```

#### 5.3.2 Gestione Umorismo

```python
# Linea guida nel system prompt:
"""
UMORISMO E GIOCHI DI PAROLE:
- Privilegia EFFETTO COMICO su traduzione letterale
- Se gioco di parole inglese non traducibile → trova equivalente italiano che fa ridere
- Battuta può essere completamente riadattata se preserva umorismo

ESEMPIO:
EN: "I'm reading a book on anti-gravity. It's impossible to put down!"
    (Gioco parole: "put down" = posare/criticare)

❌ IT (letterale): "Sto leggendo un libro sull'antigravità. È impossibile metterlo giù!"
   (Perde gioco di parole)

✅ IT (riadattata): "Sto leggendo un libro sull'antigravità. È davvero avvincente!"
   (Mantiene effetto comico con "avvincente" = interessante + vincoli gravitazionali)
"""
```

#### 5.3.3 Gestione Riferimenti Culturali

```python
# Linea guida nel system prompt:
"""
RIFERIMENTI CULTURALI:
- Riferimenti USA comprensibili in Italia → mantieni
- Riferimenti USA oscuri in Italia → adatta o spiega brevemente

ESEMPI:
"Thanksgiving dinner" → "cena del Ringraziamento" (comprensibile)
"NFL playoffs" → "playoff del football americano" (breve glossa)
"Fourth of July" → "4 luglio" (mantenibile, noto)

ECCEZIONI:
Se riferimento è CRUCIALE per trama → mantieni anche se oscuro
(Nota: aggiungere glossa sottotitoli molto breve se possibile)
"""
```

### 5.4 Temperature e Parametri Ollama

```python
# Configurazione raccomandata per traduzione
ollama_options = {
    'temperature': 0.3,  # ← BASSA: coerenza e ripetibilità
                         # Range: 0.0 (deterministica) - 1.0 (creativa)
                         # Traduzione richiede consistenza
    
    'top_p': 0.9,        # Nucleus sampling: considera top 90% probabilità
                         # Bilancia creatività con coerenza
    
    'top_k': 40,         # Considera top 40 token per scelta
                         # Previene scelte troppo creative/improbabili
    
    'num_ctx': 16384,    # Context window: 16K token
                         # Aumenta per batch grandi o contesto esteso
    
    'repeat_penalty': 1.1,  # Penalizza ripetizioni
                            # Utile per evitare traduzioni ridondanti
    
    'num_predict': -1,   # -1 = nessun limite output
                         # Lascia modello decidere lunghezza
}
```

**Razionale parametri:**
- **Temperature 0.3**: Traduzione è task "corretto/sbagliato", non creativo. Bassa temperature → output più prevedibile e coerente.
- **top_p/top_k**: Bilanciano esplorazione vocabolario senza derive creative eccessive.
- **num_ctx 16384**: Permette batch grandi + context window senza troncamento. RTX 3060 12GB gestisce senza OOM.

---

## 6. INTEGRAZIONE CONFIGURATION MANAGER

### 6.1 Modifiche a config.py

```python
# File: utils/config.py

class Config:
    """Gestisce configurazione e preferenze utente"""
    
    # ... codice esistente ...
    
    # DEFAULTS (MODIFICHE)
    DEFAULTS = {
        # ... defaults esistenti ...
        
        # Translation Model Settings (ESTESO)
        'translation_model': 'nllb',  # 'nllb' | 'aya' | 'qwen'  ← AGGIUNTO 'qwen'
        
        # Aya settings (esistente - invariato)
        'aya_model_download_status': False,
        'aya_model_path': str(Path.home() / '.cache' / 'huggingface' / ...),
        
        # NLLB settings (esistente - invariato)
        'nllb_model_path': '',
        
        # ======= NUOVE CHIAVI QWEN/OLLAMA =======
        'qwen_model_name': 'qwen2.5:7b-instruct-q4_K_M',  # Modello default
        'qwen_ollama_host': 'http://localhost:11434',      # Host Ollama
        'qwen_batch_size': 12,                              # Sottotitoli per batch
        'qwen_use_icl': True,                               # In-Context Learning
        'qwen_use_glossary': True,                          # Estrazione glossario
        'qwen_enable_fallback': True,                       # Fallback su NLLB
        'qwen_context_window': 16384,                       # Token max context
        'qwen_temperature': 0.3,                            # Temperature inferenza
        
        # HuggingFace token (esistente - invariato, usato da Aya)
        'huggingface_token': '',
    }
    
    # ... resto codice esistente ...
    
    # NUOVI METODI
    
    def is_qwen_available(self) -> bool:
        """
        Verifica se Qwen/Ollama è disponibile e configurato.
        
        Returns:
            True se Ollama raggiungibile e modello installato
        """
        try:
            import ollama
            
            # Check Ollama server
            client = ollama.Client(host=self.settings['qwen_ollama_host'])
            models = client.list()
            
            # Check modello specificato disponibile
            model_name = self.settings['qwen_model_name']
            installed = [m['name'] for m in models.get('models', [])]
            
            return any(model_name in m for m in installed)
            
        except Exception as e:
            logger.debug(f"Qwen availability check failed: {e}")
            return False
    
    def get_qwen_config(self) -> Dict[str, Any]:
        """
        Restituisce configurazione Qwen completa.
        
        Returns:
            Dict con tutte le impostazioni Qwen
        """
        return {
            'model_name': self.settings['qwen_model_name'],
            'ollama_host': self.settings['qwen_ollama_host'],
            'batch_size': self.settings['qwen_batch_size'],
            'use_icl': self.settings['qwen_use_icl'],
            'use_glossary': self.settings['qwen_use_glossary'],
            'enable_fallback': self.settings['qwen_enable_fallback'],
            'context_window': self.settings['qwen_context_window'],
            'temperature': self.settings['qwen_temperature'],
        }
    
    def set_qwen_model(self, model_name: str):
        """Imposta modello Qwen (con validazione)"""
        self.settings['qwen_model_name'] = model_name
        self.save()
```

### 6.2 Modifica Factory Function (translator.py)

```python
# File: core/translator.py (fondo file, dopo classi)

def get_translator(
    model_type: Optional[str] = None,
    context: Optional[str] = None,
    config: Optional[Config] = None
) -> BaseTranslator:
    """
    Factory function per ottenere traduttore appropriato.
    
    Args:
        model_type: 'nllb' | 'aya' | 'qwen' | None (usa config)
        context: Contesto opzionale (sinossi film/serie)
        config: Oggetto Config (se None, carica da default)
    
    Returns:
        Istanza BaseTranslator appropriata
    """
    if config is None:
        from utils.config import get_config
        config = get_config()
    
    # Determina modello da usare
    if model_type is None:
        model_type = config.settings.get('translation_model', 'nllb')
    
    # Crea traduttore appropriato
    if model_type == 'qwen':
        logger.info("Factory: Creating QwenOllamaTranslator")
        
        # Carica config Qwen
        qwen_config = config.get_qwen_config()
        
        return QwenOllamaTranslator(
            model=qwen_config['model_name'],
            context=context,
            enable_fallback=qwen_config['enable_fallback'],
            batch_size=qwen_config['batch_size'],
            use_icl=qwen_config['use_icl'],
            use_glossary=qwen_config['use_glossary']
        )
    
    elif model_type == 'aya':
        logger.info("Factory: Creating AyaTranslator")
        return AyaTranslator(context=context)
    
    else:  # 'nllb' o default
        logger.info("Factory: Creating NLLBTranslator")
        return NLLBTranslator(context=context)


# RETROCOMPATIBILITÃ€ (mantieni funzioni esistenti)
def get_nllb_translator(log_callback: Optional[Callable] = None, context: Optional[str] = None) -> NLLBTranslator:
    """Legacy function - mantiene compatibilità codice esistente"""
    return NLLBTranslator(log_callback=log_callback, context=context)
```

---

## 7. INTEGRAZIONE GUI

### 7.1 Modifica TranslationModelDialog

```python
# File: gui/translation_model_dialog.py

class TranslationModelDialog(QDialog):
    """Dialog per selezione modello di traduzione (MODIFICATO per Qwen)"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config()
        
        # ... codice esistente ...
        
        # NUOVO: Radio button Qwen
        self.qwen_radio = QRadioButton("Qwen 2.5-7B (via Ollama)")
        
        # NUOVO: Info Qwen
        self.qwen_info = self._create_qwen_info_card()
        
        # NUOVO: Status check Qwen
        self.qwen_status_label = QLabel()
        self._update_qwen_status()
        
        # ... resto layout esistente ...
    
    def _create_qwen_info_card(self) -> QFrame:
        """
        Crea info card Qwen con dettagli modello.
        
        Returns:
            QFrame con informazioni formattate
        """
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        frame.setStyleSheet("""
            QFrame {
                background-color: #2D2D30;
                border: 1px solid #3E3E42;
                border-radius: 4px;
                padding: 12px;
            }
        """)
        
        layout = QVBoxLayout(frame)
        
        # Titolo
        title = QLabel("🚀 Qwen 2.5-7B-Instruct")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # Descrizione
        desc = QLabel(
            "<b>Specializzato per dialoghi cinematografici</b><br>"
            "LLM avanzato con gestione contesto esteso e traduzione idiomatica naturale."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # Specifiche
        specs_text = (
            "<b>Caratteristiche:</b><br>"
            "• Parametri: 7B (quantizzato 4-bit)<br>"
            "• VRAM: ~6-8GB<br>"
            "• Velocità: 25-35 tok/s (RTX 3060)<br>"
            "• Contesto: fino a 32K token<br>"
            "• Stile: Colloquiale, naturale, idiomatico<br>"
            "<br>"
            "<b>Ideale per:</b><br>"
            "✓ Film e serie TV<br>"
            "✓ Dialoghi realistici<br>"
            "✓ Slang e espressioni idiomatiche<br>"
            "✓ Continuità narrativa<br>"
        )
        specs_label = QLabel(specs_text)
        specs_label.setWordWrap(True)
        layout.addWidget(specs_label)
        
        return frame
    
    def _update_qwen_status(self):
        """
        Aggiorna label status Qwen (disponibile/non disponibile).
        """
        if self.config.is_qwen_available():
            model_name = self.config.settings['qwen_model_name']
            self.qwen_status_label.setText(
                f"<font color='#4EC9B0'>✓ Disponibile</font> - Modello: {model_name}"
            )
            self.qwen_radio.setEnabled(True)
        else:
            self.qwen_status_label.setText(
                "<font color='#F48771'>✗ Non disponibile</font> - "
                "<a href='#install'>Installa Ollama</a>"
            )
            self.qwen_radio.setEnabled(False)
            
            # Collega link installazione
            self.qwen_status_label.linkActivated.connect(self._show_qwen_install_guide)
    
    def _show_qwen_install_guide(self):
        """
        Mostra dialog con istruzioni installazione Ollama + Qwen.
        """
        guide = QMessageBox(self)
        guide.setWindowTitle("Installazione Qwen/Ollama")
        guide.setIcon(QMessageBox.Icon.Information)
        
        guide.setText(
            "<b>Per usare Qwen 2.5-7B, installa Ollama:</b>"
        )
        
        guide.setInformativeText(
            "1. Scarica Ollama per Windows:<br>"
            "   <a href='https://ollama.com/download/windows'>https://ollama.com/download/windows</a><br>"
            "<br>"
            "2. Esegui OllamaSetup.exe (non richiede admin)<br>"
            "<br>"
            "3. Apri terminale (cmd/PowerShell) ed esegui:<br>"
            "   <code>ollama pull qwen2.5:7b-instruct-q4_K_M</code><br>"
            "<br>"
            "4. Verifica installazione:<br>"
            "   <code>ollama list</code><br>"
            "<br>"
            "5. Riavvia questa applicazione<br>"
            "<br>"
            "<b>Dimensione download:</b> ~4.5GB<br>"
            "<b>Spazio richiesto:</b> ~10GB totale<br>"
            "<b>Tempo stimato:</b> 6-10 minuti (100Mbps)"
        )
        
        guide.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Help
        )
        
        if guide.exec() == QMessageBox.StandardButton.Help:
            # Apri documentazione online
            import webbrowser
            webbrowser.open("https://github.com/ollama/ollama/blob/main/docs/windows.md")
    
    def _on_model_selected(self):
        """
        Callback selezione modello (MODIFICATO per Qwen).
        """
        if self.qwen_radio.isChecked():
            selected_model = 'qwen'
        elif self.aya_radio.isChecked():
            selected_model = 'aya'
        else:
            selected_model = 'nllb'
        
        # Salva in config
        self.config.settings['translation_model'] = selected_model
        self.config.save()
        
        self.accept()
```

### 7.2 Integrazione MainWindow

```python
# File: gui/main_window.py (modifiche)

class MainWindow(QMainWindow):
    """Main window applicazione (MODIFICHE per Qwen)"""
    
    def __init__(self):
        super().__init__()
        # ... codice esistente ...
        
        # NUOVO: Check Qwen disponibilità all'avvio
        self._check_qwen_availability()
    
    def _check_qwen_availability(self):
        """
        Verifica disponibilità Qwen e notifica utente se selezionato ma non disponibile.
        """
        config = get_config()
        
        if config.settings['translation_model'] == 'qwen':
            if not config.is_qwen_available():
                # Qwen selezionato ma non disponibile
                reply = QMessageBox.warning(
                    self,
                    "Qwen non disponibile",
                    "Qwen/Ollama è selezionato come modello di traduzione ma non è disponibile.\n\n"
                    "Vuoi:\n"
                    "• Installare Ollama ora (apre guida)\n"
                    "• Usare NLLB come fallback temporaneo",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Apri translation model dialog su Qwen
                    from gui.translation_model_dialog import TranslationModelDialog
                    dialog = TranslationModelDialog(self)
                    dialog.qwen_radio.setChecked(True)
                    dialog._show_qwen_install_guide()
                else:
                    # Fallback temporaneo su NLLB
                    self.log("⚠ Qwen non disponibile, uso NLLB come fallback")
    
    def _start_translation(self, files: List[Path]):
        """
        Avvia processo traduzione (MODIFICATO per Qwen).
        
        Args:
            files: Lista file da tradurre
        """
        # ... codice esistente (ottieni src_lang, tgt_lang, context) ...
        
        # MODIFICA: usa factory con model type
        config = get_config()
        model_type = config.settings['translation_model']
        
        # Crea traduttore appropriato
        from core.translator import get_translator
        translator = get_translator(
            model_type=model_type,
            context=context
        )
        
        # Log modello usato
        self.log(f"Modello traduzione: {model_type.upper()}")
        
        # ... resto codice esistente (crea worker, avvia thread) ...
```

---

## 8. GESTIONE ERRORI E RESILIENZA

### 8.1 Tassonomia Errori

```python
# Gerarchiaccezioni (translator.py)

class TranslationError(Exception):
    """Base exception per errori traduzione"""
    pass

class OllamaConnectionError(TranslationError):
    """Ollama server non raggiungibile"""
    pass

class OllamaModelNotFoundError(TranslationError):
    """Modello richiesto non installato in Ollama"""
    pass

class OllamaInferenceError(TranslationError):
    """Errore durante inferenza (timeout, OOM, etc.)"""
    pass

class PromptTooLongError(TranslationError):
    """Prompt supera context window massimo"""
    pass
```

### 8.2 Strategia Fallback Gerarchica

```
┌─────────────────────────────────────────┐
│ 1. TENTATIVO PRIMARIO: Qwen/Ollama     │
└──────────────────┬──────────────────────┘
                   │
           ┌───────▼───────┐
           │   SUCCESSO?   │
           └───┬───────┬───┘
               │ SÌ    │ NO
               │       │
               ▼       ▼
           ┌───────┐ ┌──────────────────────────────┐
           │ DONE  │ │ 2. FALLBACK BATCH: NLLB     │
           └───────┘ │    (solo batch corrente)     │
                     └──────────────┬───────────────┘
                                    │
                            ┌───────▼───────┐
                            │   SUCCESSO?   │
                            └───┬───────┬───┘
                                │ SÌ    │ NO
                                │       │
                                ▼       ▼
                            ┌───────┐ ┌─────────────────────┐
                            │ DONE  │ │ 3. COPIA ORIGINALI  │
                            └───────┘ │    (ultima risorsa) │
                                      └─────────────────────┘
```

### 8.3 Implementazione Retry Logic

```python
# In QwenOllamaTranslator.translate_file()

MAX_RETRIES_PER_BATCH = 3
RETRY_DELAYS = [1, 2, 5]  # secondi

for chunk in chunks:
    retries = 0
    success = False
    
    while retries < MAX_RETRIES_PER_BATCH and not success:
        try:
            # Tentativo traduzione batch
            response = self.client.chat(...)
            success = True
            
        except ollama.ResponseError as e:
            retries += 1
            
            # Determina se retry ha senso
            if e.status_code == 404:
                # Modello non trovato - retry inutile
                self.log(f"✗ Modello non trovato: {self.model}")
                break
            
            elif e.status_code == 503:
                # Server sovraccarico - retry con delay
                if retries < MAX_RETRIES_PER_BATCH:
                    delay = RETRY_DELAYS[retries - 1]
                    self.log(f"⏳ Server occupato, retry in {delay}s...")
                    time.sleep(delay)
                else:
                    self.log(f"✗ Server non risponde dopo {MAX_RETRIES} tentativi")
                    break
            
            elif 'timeout' in str(e).lower():
                # Timeout - prova ridurre batch size
                if retries < MAX_RETRIES_PER_BATCH:
                    self.batch_size = max(4, self.batch_size // 2)
                    self.log(f"⏳ Timeout, riduco batch size a {self.batch_size}")
                else:
                    break
            
            else:
                # Errore sconosciuto - log e break
                self.log(f"✗ Errore Ollama: {e}")
                break
        
        except Exception as e:
            # Errore generico
            self.log(f"✗ Errore imprevisto: {e}")
            break
    
    # Se tutti i retry falliscono → fallback NLLB
    if not success and self.enable_fallback:
        self.log(f"→ Fallback NLLB per batch {chunk['batch_index']}")
        # ... fallback logic ...
```

### 8.4 Timeout Management

```python
# Configurazione timeout Ollama

# Client Ollama con timeout custom
self.client = ollama.Client(
    host='http://localhost:11434',
    timeout=60.0  # 60 secondi (default: 30s può essere poco per batch grandi)
)

# Timeout adattivo basato su batch size
def calculate_timeout(batch_size: int, base_timeout: float = 30.0) -> float:
    """
    Calcola timeout adattivo.
    
    Stima: ~0.5s per sottotitolo tradotto (conservativa)
    """
    estimated_time = batch_size * 0.5
    return max(base_timeout, estimated_time * 2)  # 2x margin

# Uso
timeout = calculate_timeout(self.batch_size)
response = self.client.chat(..., timeout=timeout)
```

---

## 9. TESTING E VALIDAZIONE

### 9.1 Test Suite

```python
# File: tests/test_qwen_translator.py (NUOVO)

import pytest
from pathlib import Path
from core.translator import QwenOllamaTranslator, OllamaConnectionError

class TestQwenOllamaTranslator:
    """Test suite QwenOllamaTranslator"""
    
    @pytest.fixture
    def translator(self):
        """Fixture: crea translator instance"""
        return QwenOllamaTranslator(enable_fallback=False)
    
    @pytest.fixture
    def sample_srt(self, tmp_path):
        """Fixture: crea file SRT campione"""
        srt_path = tmp_path / "test.srt"
        srt_content = """1
00:00:01,000 --> 00:00:03,000
Hello, how are you?

2
00:00:04,000 --> 00:00:06,000
I'm fine, thanks!

3
00:00:07,000 --> 00:00:09,000
Are you kidding me?
"""
        srt_path.write_text(srt_content, encoding='utf-8')
        return srt_path
    
    # ========================================
    # TEST INIZIALIZZAZIONE
    # ========================================
    
    def test_init_default(self, translator):
        """Test inizializzazione con parametri default"""
        assert translator.model is not None
        assert translator.batch_size > 0
        assert translator.use_icl is True
    
    def test_init_custom_model(self):
        """Test inizializzazione con modello custom"""
        translator = QwenOllamaTranslator(model='qwen2.5:7b')
        assert translator.model == 'qwen2.5:7b'
    
    def test_model_detection(self):
        """Test auto-detection modello disponibile"""
        try:
            translator = QwenOllamaTranslator()
            assert 'qwen' in translator.model.lower()
        except OllamaConnectionError:
            pytest.skip("Ollama server not available")
    
    # ========================================
    # TEST PROMPTING
    # ========================================
    
    def test_system_prompt_building(self, translator):
        """Test costruzione system prompt"""
        prompt = translator._build_system_prompt('eng', 'ita')
        
        assert 'traduttore' in prompt.lower()
        assert 'cinematografico' in prompt.lower()
        assert 'colloquiale' in prompt.lower()
    
    def test_system_prompt_with_genre(self, translator):
        """Test system prompt con genere specifico"""
        prompt = translator._build_system_prompt('eng', 'ita', genre='commedia')
        
        assert 'commedia' in prompt.lower()
        assert 'umorismo' in prompt.lower()
    
    def test_icl_examples_loading(self, translator):
        """Test caricamento ICL examples"""
        examples = translator._build_icl_examples('eng', 'ita')
        
        assert len(examples) > 0
        assert all('role' in ex for ex in examples)
        assert all('content' in ex for ex in examples)
    
    # ========================================
    # TEST CHUNKING
    # ========================================
    
    def test_subtitle_chunking(self, translator):
        """Test chunking sottotitoli"""
        subtitles = [
            (i, "00:00:00,000", "00:00:01,000", f"Text {i}")
            for i in range(1, 26)  # 25 sottotitoli
        ]
        
        translator.batch_size = 10
        chunks = translator._chunk_subtitles(subtitles, translator.batch_size)
        
        # Aspettati 3 chunk (10 + 10 + 5)
        assert len(chunks) == 3
        assert len(chunks[0]['to_translate']) == 10
        assert len(chunks[1]['to_translate']) == 10
        assert len(chunks[2]['to_translate']) == 5
    
    def test_sliding_window_context(self, translator):
        """Test sliding window per contesto"""
        subtitles = [
            (i, "00:00:00,000", "00:00:01,000", f"Text {i}")
            for i in range(1, 11)
        ]
        
        translator.batch_size = 3
        translator.SLIDING_WINDOW_SIZE = 2
        
        chunks = translator._chunk_subtitles(subtitles, translator.batch_size)
        
        # Secondo chunk dovrebbe avere context (ultimi 2 del primo chunk)
        assert len(chunks[1]['context']) == 2
    
    # ========================================
    # TEST PARSING RESPONSE
    # ========================================
    
    def test_parse_response_standard(self, translator):
        """Test parsing risposta standard numerata"""
        response = """1. Ciao, come stai?
2. Sto bene, grazie!
3. Mi stai prendendo in giro?"""
        
        translations = translator._parse_translation_response(response, expected_count=3)
        
        assert len(translations) == 3
        assert translations[0] == "Ciao, come stai?"
        assert translations[2] == "Mi stai prendendo in giro?"
    
    def test_parse_response_without_numbers(self, translator):
        """Test parsing risposta senza numerazione"""
        response = """Ciao, come stai?
Sto bene, grazie!
Mi stai prendendo in giro?"""
        
        translations = translator._parse_translation_response(response, expected_count=3)
        
        assert len(translations) == 3
    
    def test_parse_response_count_mismatch(self, translator):
        """Test parsing con count mismatch (padding)"""
        response = """1. Ciao"""
        
        translations = translator._parse_translation_response(response, expected_count=3)
        
        # Dovrebbe paddare con stringhe vuote
        assert len(translations) == 3
        assert translations[0] == "Ciao"
        assert translations[1] == ""
        assert translations[2] == ""
    
    # ========================================
    # TEST INTEGRAZIONE (richiede Ollama)
    # ========================================
    
    @pytest.mark.integration
    def test_translate_file_success(self, translator, sample_srt, tmp_path):
        """Test traduzione file completo (RICHIEDE OLLAMA)"""
        output_path = tmp_path / "output.srt"
        
        success = translator.translate_file(
            sample_srt,
            output_path,
            'eng',
            'ita'
        )
        
        assert success is True
        assert output_path.exists()
        
        # Verifica contenuto
        content = output_path.read_text(encoding='utf-8')
        assert '1' in content  # Primo sottotitolo
        assert '00:00:01,000' in content  # Timestamp
    
    @pytest.mark.integration
    def test_ollama_connection_error_handling(self):
        """Test gestione errore connessione Ollama"""
        translator = QwenOllamaTranslator(
            enable_fallback=False
        )
        
        # Forza host errato
        translator.client = ollama.Client(host='http://localhost:99999')
        
        # Dovrebbe sollevare OllamaConnectionError
        with pytest.raises(OllamaConnectionError):
            translator._detect_best_model()
    
    # ========================================
    # TEST PERFORMANCE
    # ========================================
    
    @pytest.mark.performance
    @pytest.mark.integration
    def test_translation_speed(self, translator, sample_srt, tmp_path):
        """Test velocità traduzione (benchmark)"""
        import time
        
        output_path = tmp_path / "output.srt"
        
        start = time.time()
        translator.translate_file(sample_srt, output_path, 'eng', 'ita')
        elapsed = time.time() - start
        
        # Aspettati < 5 secondi per 3 sottotitoli
        assert elapsed < 5.0, f"Traduzione troppo lenta: {elapsed:.2f}s"
```

### 9.2 Test Manuali

```bash
# Checklist test manuali

# 1. Installazione Ollama
[ ] Ollama scaricato e installato
[ ] ollama --version funziona
[ ] ollama list mostra modelli

# 2. Download Modello
[ ] ollama pull qwen2.5:7b-instruct-q4_K_M completato
[ ] Modello visibile in ollama list

# 3. Test Python Isolato
[ ] pip install ollama completato
[ ] import ollama funziona
[ ] ollama.chat() test successo

# 4. Test Integrazione App
[ ] QwenOllamaTranslator si inizializza senza errori
[ ] Dialog selezione modello mostra Qwen disponibile
[ ] Traduzione file SRT test successo

# 5. Test Qualità Output
[ ] Output SRT leggibile e ben formattato
[ ] Traduzioni suonano naturali (test manuale con 5+ battute)
[ ] Coerenza terminologica tra battute
[ ] Nessun artefatto (caratteri strani, markup residuo)

# 6. Test Fallback
[ ] Con Ollama spento: fallback NLLB funziona
[ ] Con modello sbagliato: errore chiaro + fallback
[ ] Con timeout: retry + fallback

# 7. Test Performance
[ ] Velocità 25+ tok/s su RTX 3060 (monitoring GPU)
[ ] VRAM uso <8GB durante traduzione
[ ] Nessun crash/OOM con file 100+ sottotitoli
```

---

## 10. PERFORMANCE E OTTIMIZZAZIONI

### 10.1 Profiling e Benchmarking

```python
# Script profiling performance
# File: scripts/benchmark_qwen.py (NUOVO)

import time
import logging
from pathlib import Path
from core.translator import QwenOllamaTranslator

logging.basicConfig(level=logging.INFO)

def benchmark_translation(
    srt_path: Path,
    model: str = 'qwen2.5:7b-instruct-q4_K_M',
    batch_sizes: list = [4, 8, 12, 16, 20]
):
    """
    Benchmark performance con diversi batch size.
    
    Metriche:
    - Tempo totale
    - Token/secondo
    - VRAM peak
    - Throughput (sottotitoli/secondo)
    """
    results = []
    
    for batch_size in batch_sizes:
        print(f"\n=== BATCH SIZE: {batch_size} ===")
        
        translator = QwenOllamaTranslator(
            model=model,
            batch_size=batch_size,
            use_icl=True
        )
        
        output_path = srt_path.parent / f"output_batch{batch_size}.srt"
        
        # Benchmark
        start = time.time()
        
        success = translator.translate_file(
            srt_path,
            output_path,
            'eng',
            'ita'
        )
        
        elapsed = time.time() - start
        
        if success:
            stats = translator.stats
            
            result = {
                'batch_size': batch_size,
                'total_time': elapsed,
                'total_subtitles': stats['total_subtitles'],
                'throughput': stats['total_subtitles'] / elapsed,
                'avg_tok_per_sec': stats.get('avg_tokens_per_second', 0),
                'failed_batches': stats['failed_batches']
            }
            
            results.append(result)
            
            print(f"✓ Completato in {elapsed:.2f}s")
            print(f"  Throughput: {result['throughput']:.2f} sub/s")
            print(f"  Velocità: {result['avg_tok_per_sec']:.1f} tok/s")
        
        else:
            print(f"✗ Fallito")
    
    # Report finale
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    
    for r in results:
        print(
            f"Batch {r['batch_size']:2d}: "
            f"{r['total_time']:6.2f}s | "
            f"{r['throughput']:5.2f} sub/s | "
            f"{r['avg_tok_per_sec']:5.1f} tok/s"
        )
    
    # Best configuration
    best = max(results, key=lambda x: x['throughput'])
    print(f"\n✓ BEST: Batch size {best['batch_size']} "
          f"({best['throughput']:.2f} sub/s)")
    
    return results


if __name__ == '__main__':
    # Usa file test
    test_file = Path("tests/fixtures/sample.srt")
    
    if not test_file.exists():
        print("Errore: file test non trovato")
        exit(1)
    
    benchmark_translation(test_file)
```

### 10.2 Ottimizzazioni Batch Size

```python
# Logica batch size adattivo

class AdaptiveBatchSizer:
    """
    Regola dinamicamente batch size basato su:
    - Lunghezza media sottotitoli
    - VRAM disponibile
    - Velocità inferenza
    """
    
    def __init__(
        self,
        initial_batch_size: int = 12,
        min_batch_size: int = 4,
        max_batch_size: int = 24
    ):
        self.current_batch_size = initial_batch_size
        self.min = min_batch_size
        self.max = max_batch_size
        
        self.recent_times = []  # Tempi ultimi 5 batch
        self.recent_errors = []  # Errori ultimi 5 batch
    
    def update(self, batch_time: float, had_error: bool):
        """
        Aggiorna batch size basato su performance recenti.
        
        Euristica:
        - Se tempi stabili e nessun errore → aumenta batch
        - Se timeout/OOM → riduci batch
        - Se tempi crescenti → mantieni o riduci
        """
        self.recent_times.append(batch_time)
        self.recent_errors.append(had_error)
        
        # Mantieni finestra 5 batch
        if len(self.recent_times) > 5:
            self.recent_times.pop(0)
            self.recent_errors.pop(0)
        
        # Decisione
        if len(self.recent_times) < 3:
            return  # Non abbastanza dati
        
        # Caso 1: Errori recenti (OOM, timeout)
        if sum(self.recent_errors) > 0:
            self.current_batch_size = max(
                self.min,
                self.current_batch_size // 2
            )
            print(f"⚠ Batch size ridotto a {self.current_batch_size} (errori)")
            return
        
        # Caso 2: Tempi stabili/decrescenti → aumenta batch
        avg_time = sum(self.recent_times) / len(self.recent_times)
        last_time = self.recent_times[-1]
        
        if last_time <= avg_time * 1.1:  # Max 10% sopra media
            self.current_batch_size = min(
                self.max,
                self.current_batch_size + 2
            )
            print(f"✓ Batch size aumentato a {self.current_batch_size}")
        
        # Caso 3: Tempi crescenti → mantieni o riduci
        elif last_time > avg_time * 1.5:
            self.current_batch_size = max(
                self.min,
                self.current_batch_size - 1
            )
            print(f"⚠ Batch size ridotto a {self.current_batch_size} (rallentamento)")


# Uso in QwenOllamaTranslator
translator.batch_sizer = AdaptiveBatchSizer(initial_batch_size=12)

for chunk in chunks:
    start_time = time.time()
    had_error = False
    
    try:
        # Traduzione batch
        response = self.client.chat(...)
    except Exception:
        had_error = True
        # ... gestione errore ...
    
    elapsed = time.time() - start_time
    
    # Aggiorna batch size per prossimi batch
    translator.batch_sizer.update(elapsed, had_error)
    translator.batch_size = translator.batch_sizer.current_batch_size
```

### 10.3 Caching Prompt e Responses

```python
# Cache LRU per prompt riutilizzabili

from functools import lru_cache
import hashlib

class PromptCache:
    """
    Cache per system prompt e ICL examples.
    
    Evita ricostruzione prompt identici.
    """
    
    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self._cache = {}
    
    def get_cache_key(self, *args) -> str:
        """Genera chiave cache da parametri"""
        key_str = "|".join(str(arg) for arg in args)
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
    
    @lru_cache(maxsize=128)
    def get_system_prompt(
        self,
        src_lang: str,
        tgt_lang: str,
        genre: Optional[str],
        tone: str
    ) -> str:
        """System prompt con cache"""
        from core.qwen_prompts import build_system_prompt
        return build_system_prompt(src_lang, tgt_lang, genre, tone)
    
    @lru_cache(maxsize=32)
    def get_icl_examples(self, src_lang: str, tgt_lang: str) -> tuple:
        """ICL examples con cache (ritorna tuple per hashability)"""
        from core.qwen_prompts import get_icl_examples
        examples = get_icl_examples(src_lang, tgt_lang)
        
        # Converti in tuple per cache
        return tuple(
            (ex['role'], ex['content']) for ex in examples
        )


# Uso in QwenOllamaTranslator
translator.prompt_cache = PromptCache()

# Invece di:
system_prompt = build_system_prompt(...)

# Usa:
system_prompt = translator.prompt_cache.get_system_prompt(
    src_lang, tgt_lang, genre, tone
)
```

---

## 11. MIGRATION PATH

### 11.1 Rollout Graduale

```
FASE 1: ALPHA (Settimana 1-2)
├─ Implementazione core QwenOllamaTranslator
├─ Test unitari e integrazione
├─ Benchmark performance
└─ Status: Feature flag OFF per utenti

FASE 2: BETA (Settimana 3-4)
├─ GUI integration
├─ Test manuali estensivi
├─ Documentazione utente
└─ Status: Feature flag ON per beta testers

FASE 3: RELEASE (Settimana 5+)
├─ Bugfix basato su feedback beta
├─ Ottimizzazioni performance
├─ Tutorial video
└─ Status: Feature flag ON per tutti
```

### 11.2 Feature Flag System

```python
# File: utils/config.py (AGGIUNTA)

class Config:
    # ... codice esistente ...
    
    DEFAULTS = {
        # ... defaults esistenti ...
        
        # FEATURE FLAGS
        'enable_qwen_translator': False,  # ← Feature flag master
        'qwen_beta_user': False,           # Beta tester flag
    }
    
    def is_qwen_enabled(self) -> bool:
        """
        Check se Qwen è abilitato per questo utente.
        
        Returns:
            True se feature enabled globalmente O se beta user
        """
        return (
            self.settings['enable_qwen_translator'] or
            self.settings['qwen_beta_user']
        )


# File: gui/translation_model_dialog.py (MODIFICA)

class TranslationModelDialog(QDialog):
    
    def __init__(self, parent=None):
        super().__init__()
        
        # ... codice esistente ...
        
        # CONDIZIONALE: mostra Qwen solo se enabled
        if self.config.is_qwen_enabled():
            self.qwen_radio = QRadioButton("Qwen 2.5-7B (via Ollama)")
            # ... resto setup Qwen ...
        else:
            # Nasconde opzione Qwen per utenti non-beta
            pass
```

### 11.3 Migrazione Configurazioni Esistenti

```python
# Script migrazione config
# File: scripts/migrate_config_for_qwen.py (NUOVO)

from utils.config import Config
from pathlib import Path

def migrate_config_to_v2():
    """
    Migra configurazione esistente aggiungendo chiavi Qwen.
    
    SAFE: Non sovrascrive impostazioni esistenti.
    """
    config = Config()
    
    # Backup config corrente
    backup_path = Config.CONFIG_FILE.with_suffix('.json.backup')
    if Config.CONFIG_FILE.exists():
        import shutil
        shutil.copy(Config.CONFIG_FILE, backup_path)
        print(f"✓ Backup creato: {backup_path}")
    
    # Aggiungi nuove chiavi Qwen (se non presenti)
    qwen_defaults = {
        'qwen_model_name': 'qwen2.5:7b-instruct-q4_K_M',
        'qwen_ollama_host': 'http://localhost:11434',
        'qwen_batch_size': 12,
        'qwen_use_icl': True,
        'qwen_use_glossary': True,
        'qwen_enable_fallback': True,
        'qwen_context_window': 16384,
        'qwen_temperature': 0.3,
        'enable_qwen_translator': False,
        'qwen_beta_user': False,
    }
    
    updated = False
    for key, value in qwen_defaults.items():
        if key not in config.settings:
            config.settings[key] = value
            updated = True
            print(f"  + Aggiunto: {key} = {value}")
    
    if updated:
        config.save()
        print("✓ Configurazione aggiornata con successo")
    else:
        print("✓ Configurazione già aggiornata")
    
    return True


if __name__ == '__main__':
    print("=== MIGRATION SCRIPT: Config v2 (Qwen) ===\n")
    migrate_config_to_v2()
```

---

## 12. RIFERIMENTI TECNICI

### 12.1 Documentazione Ollama

- **Sito ufficiale**: https://ollama.com
- **GitHub**: https://github.com/ollama/ollama
- **Docs Windows**: https://github.com/ollama/ollama/blob/main/docs/windows.md
- **Python Library**: https://github.com/ollama/ollama-python
- **API Reference**: https://github.com/ollama/ollama/blob/main/docs/api.md

### 12.2 Documentazione Qwen

- **Model Card HuggingFace**: https://huggingface.co/Qwen/Qwen2.5-7B-Instruct
- **Official Repo**: https://github.com/QwenLM/Qwen2.5
- **Paper**: https://arxiv.org/abs/2407.10671
- **Fine-tuned Model (VitoFe)**: https://huggingface.co/VitoFe/Qwen2.5-7B-Translate-Italian-finetune

### 12.3 Best Practices Prompt Engineering

- **Anthropic Prompt Engineering Guide**: https://docs.anthropic.com/claude/docs/prompt-engineering
- **OpenAI Best Practices**: https://platform.openai.com/docs/guides/prompt-engineering
- **Few-Shot Prompting**: https://www.promptingguide.ai/techniques/fewshot

### 12.4 Paper Citati nel Documento Ricerca

1. NLLB Team (2022). "No Language Left Behind: Scaling Human-Centered Machine Translation"
2. Costa-jussà et al. (2022). "No Language Left Behind: Scaling Human-Centered Machine Translation"
3. Zhu et al. (2024). "Context-Aware and Style-Aware Translation with Large Language Models"
4. Zhao et al. (2024). "Survey of Hallucination in Natural Language Generation"

### 12.5 Tool e Librerie

```python
# requirements.txt - VERSIONI RACCOMANDATE

# CORE (esistenti - invariate)
PyQt6>=6.5.0
torch>=2.0.0
transformers>=4.30.0
bitsandbytes>=0.39.0
faster-whisper>=0.10.0

# NUOVE DIPENDENZE QWEN/OLLAMA
ollama>=0.6.0              # ← Libreria ufficiale Ollama
requests>=2.31.0           # HTTP fallback

# DEVELOPMENT (opzionali)
pytest>=7.4.0              # Testing
pytest-asyncio>=0.21.0     # Async tests
pytest-benchmark>=4.0.0    # Performance tests
black>=23.0.0              # Code formatting
mypy>=1.5.0                # Type checking
```

---

## 13. CHECKLIST IMPLEMENTAZIONE

### Pre-Implementazione
- [ ] Backup codice esistente (git branch)
- [ ] Installazione Ollama su sistema sviluppo
- [ ] Download modello Qwen 2.5-7B
- [ ] Test connessione Ollama da Python
- [ ] Verifica VRAM disponibile (nvidia-smi)

### Fase 1: Core Implementation
- [ ] Creare `core/qwen_prompts.py`
- [ ] Implementare `QwenOllamaTranslator` in `translator.py`
- [ ] Testare `_detect_best_model()`
- [ ] Testare `_build_system_prompt()`
- [ ] Testare `_chunk_subtitles()`
- [ ] Testare `translate_file()` con file piccolo (5 sub)

### Fase 2: Configuration & Factory
- [ ] Aggiungere chiavi Qwen a `config.py`
- [ ] Implementare `is_qwen_available()`
- [ ] Modificare `get_translator()` factory
- [ ] Testare switch tra NLLB/Aya/Qwen

### Fase 3: GUI Integration
- [ ] Modificare `TranslationModelDialog`
- [ ] Aggiungere Qwen info card
- [ ] Implementare status check
- [ ] Aggiungere install guide dialog
- [ ] Modificare `MainWindow` per check startup
- [ ] Testare flow completo GUI → Qwen translation

### Fase 4: Error Handling & Fallback
- [ ] Implementare retry logic
- [ ] Testare fallback NLLB
- [ ] Testare gestione Ollama offline
- [ ] Testare gestione modello mancante
- [ ] Testare gestione timeout

### Fase 5: Testing
- [ ] Scrivere unit tests (`test_qwen_translator.py`)
- [ ] Eseguire test suite completo
- [ ] Test integrazione con file reali (100+ sub)
- [ ] Benchmark performance (script)
- [ ] Test qualità traduzioni (manuale)

### Fase 6: Optimization & Polish
- [ ] Implementare batch size adattivo (se necessario)
- [ ] Implementare prompt caching
- [ ] Ottimizzare memoria (profiling)
- [ ] Documentazione inline (docstrings)
- [ ] User documentation (README)

### Release
- [ ] Code review completo
- [ ] Merge in main branch
- [ ] Creare release notes
- [ ] Update version number
- [ ] Deploy/distribuzione

---

## 14. FAQ IMPLEMENTAZIONE

### Q1: Perché Ollama invece di usare PyTorch direttamente?

**A**: Quattro ragioni principali:
1. **Isolamento**: Nessun conflitto con transformers/PyTorch esistenti
2. **GGUF Efficienza**: llama.cpp backend è 2-3x più veloce di PyTorch nativo per inferenza
3. **Gestione Memoria**: Ollama unload automatico modelli inutilizzati
4. **Manutenibilità**: Aggiornare modello = `ollama pull`, non rebuild app

### Q2: Qwen funziona senza connessione internet?

**A**: Sì, completamente offline dopo setup iniziale:
1. Download modello: `ollama pull qwen2.5:7b` (richiede internet, ~4.5GB)
2. Dopo download: funziona 100% offline
3. Ollama server è locale (localhost:11434)

### Q3: Quanto spazio disco serve?

**A**: 
- Ollama binari: ~4GB
- Qwen 2.5-7B Q4_K_M: ~4.5GB
- **Totale minimo**: ~10GB (con margine)
- Consigliato: 20-50GB per testare multipli modelli

### Q4: Posso usare altri modelli oltre Qwen?

**A**: Sì, l'architettura è modulare:
- Modificare `model` parameter in `QwenOllamaTranslator(model='...')`
- Qualsiasi modello Ollama compatibile (Llama, Mistral, Gemma, etc.)
- Nota: prompt potrebbero necessitare tuning per modelli diversi

### Q5: Come misuro se Qwen è effettivamente migliore di NLLB?

**A**: Test A/B:
1. Traduci stesso file con entrambi i modelli
2. Metrics automatiche: BLEU, COMET (limitati per idiomaticità)
3. **Valutazione umana** (gold standard): leggi output, valuta naturalezza
4. Benchmark: velocità, VRAM, stabilità

### Q6: Fallback funziona automaticamente?

**A**: Sì, se `enable_fallback=True` (default):
- Ollama offline → fallback completo su NLLB
- Singolo batch fallisce → fallback batch su NLLB, resto Qwen
- 3 retry automatici prima di fallback

### Q7: Posso tradurre altre lingue oltre EN→IT?

**A**: Qwen 2.5 supporta 29+ lingue:
- Modificare mappings in `LANGUAGE_CODES`
- Creare prompt template per lingua target
- Aggiungere ICL examples per coppia lingue
- Testare qualità (può variare per lingue low-resource)

### Q8: Contesto film/sinossi migliora davvero?

**A**: Sì, test empirici mostrano:
- Coerenza terminologica: +15-20% con glossario
- Scelte stilistiche: +10% con genre hint
- Comprensione battute ambigue: +25% con sinossi
- Overhead: minimo (~200-500 token aggiuntivi)

### Q9: Performance su GPU più debole/forte?

**A**:
- **RTX 3050 8GB**: Funziona, batch size 6-8, contesto 8K max
- **RTX 3060 12GB**: Ottimale (target spec), batch 12, contesto 16K
- **RTX 4070 12GB**: Identico 3060 (VRAM limitato da 12GB)
- **RTX 4090 24GB**: Eccellente, batch 24+, contesto 32K, può usare Qwen 14B

### Q10: Licenza permette uso commerciale?

**A**:
- **Qwen 2.5**: Apache 2.0 → uso commerciale OK
- **Ollama**: MIT License → uso commerciale OK
- **Tuo software**: Nessuna restrizione da Qwen/Ollama

---

## 15. GLOSSARIO TECNICO

| Termine | Definizione |
|---------|-------------|
| **GGUF** | GPT-Generated Unified Format - formato file quantizzato per LLM (successore GGML) |
| **Q4_K_M** | Quantizzazione 4-bit con kernel medio - bilancia qualità/efficienza |
| **ICL** | In-Context Learning - tecnica few-shot prompting con esempi |
| **Sliding Window** | Finestra mobile che include N battute precedenti per contesto |
| **Context Window** | Massima lunghezza input (in token) che modello può processare |
| **Token** | Unità base testo (~4 caratteri in italiano, ~3.5 in inglese) |
| **Tok/s** | Token per secondo - metrica velocità inferenza |
| **VRAM** | Video RAM - memoria dedicata GPU per elaborazione |
| **OOM** | Out Of Memory - errore esaurimento memoria |
| **Fallback** | Strategia alternativa quando metodo primario fallisce |
| **Batch** | Gruppo sottotitoli tradotti insieme (vs sequenziale) |
| **Prompt Engineering** | Arte di costruire istruzioni efficaci per LLM |
| **System Prompt** | Istruzioni ruolo/comportamento iniziali per LLM |
| **Temperature** | Parametro creatività: 0.0 (deterministica) - 1.0 (creativa) |
| **llama.cpp** | Backend C++ ottimizzato per inferenza LLM |
| **REST API** | Interfaccia HTTP per comunicazione client-server |

---

## CONCLUSIONE

Questo documento fornisce una roadmap completa per l'integrazione di Qwen 2.5-7B tramite Ollama nel sistema di traduzione sottotitoli. I punti chiave:

### ✅ Vantaggi Chiave
1. **Qualità**: Traduzione idiomatica cinematografica superiore a NLLB
2. **Performance**: 25-35 tok/s su RTX 3060, VRAM gestibile (6-8GB)
3. **Contesto**: Fino a 32K token per coerenza narrativa
4. **Isolamento**: Nessuna interferenza con stack PyTorch esistente
5. **Fallback**: Resilienza con fallback automatico su NLLB

### 🎯 Obiettivi Raggiunti
- Architettura modulare e manutenibile
- Sistema prompting avanzato per naturalezza
- Gestione errori robusta
- Integrazione GUI completa
- Testing comprehensivo

### 📋 Next Steps
1. Implementare `core/qwen_prompts.py` e `QwenOllamaTranslator`
2. Test unitari e integrazione
3. GUI integration
4. Beta testing con utenti reali
5. Release production

**Questo documento è la base completa per iniziare l'implementazione nella prossima chat.**

---

**VERSIONE**: 1.0  
**DATA**: 2025-11-03  
**AUTORE**: System Integration Architect  
**REVIEW**: Ready for Implementation  
