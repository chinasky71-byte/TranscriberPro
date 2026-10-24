"""
Motore GGUF (llama.cpp) per TranslateGemma — stessa interfaccia del motore transformers
========================================================================================
Per le schede da 8-12 GB di VRAM, dove NF4 (picco misurato 10,1 GB) non entra o non regge, e per AMD/Vulkan, dove
bitsandbytes non c'e'. Eseguito con llama-cpp-python (stessa ruota del glossario Qwen, pin 0.3.34).

E' una sottoclasse di `SubtitleLLMEngine`: `mt_messages` (regole di sottotitolo, budget di caratteri, codice lingua
sorgente), `log` e lo `spec` sono QUELLI del motore transformers, ereditati e non copiati, quindi il prompt costruito
e' identico per costruzione. Cambiano solo `load`, `generate` e `unload`. Chi lo usa (`SubtitleLLMTranslator`) vede
la stessa interfaccia: `spec.max_batch`, `mt_messages()`, `generate(conversations, max_new_tokens)`.

Scelte di esecuzione:

- Decodifica greedy (come `do_sample=False, num_beams=1` del motore storico). Gli override di campionamento passati a
  `generate()` vengono ignorati di proposito: il traduttore non ne passa e un percorso con altro decoding non sarebbe
  quello misurato.
- Il prompt non passa dal template Jinja del GGUF: e' reso da `render_prompt()`, che riproduce il chat template di
  TranslateGemma (la forma su cui il modello e' addestrato). Il template incorporato in un GGUF convertito puo' essere
  quello generico di Gemma3 (senza i codici lingua), e in quel caso il modello riceverebbe un prompt diverso da quello
  del training senza alcun errore.
- Il batching di `generate()` di transformers non esiste: llama.cpp decodifica piu' SEQUENZE nello stesso `llama_decode`
  (n_seq_max, cache KV unificata). `generate()` riceve fino a `max_batch` conversazioni, le spezza in gruppi di
  `n_parallel` sequenze e le fa avanzare in lockstep. La KV cache costa n_parallel x ctx_per_seq token: e' il
  regolatore del picco di VRAM, come il batch lo e' per transformers.
- Una conversazione che non sta nel contesto per sequenza esce VUOTA (il traduttore la manda ai livelli L2/L3):
  mai troncata in silenzio.
"""

from __future__ import annotations

import ctypes
import dataclasses
import gc
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional

from utils.logger import setup_logger
from utils.translations import tr

from .engine import DEFAULT_MODEL_KEY, MODEL_SPECS, SubtitleLLMEngine

logger = setup_logger(__name__)

# Il motore e' valido solo per questa architettura: caricare un altro GGUF con il prompt di TranslateGemma darebbe
# testo senza senso e nessun errore.
EXPECTED_ARCH = "gemma3"

# Dopo la risposta del modello. <end_of_turn> e' di norma gia' un token EOG per llama.cpp; qui lo si cerca comunque.
END_OF_TURN = "<end_of_turn>"
BOS = "<bos>"

# ---------------------------------------------------------------------------
# Chat template di TranslateGemma, riprodotto per i messaggi che `mt_messages` produce: un solo turno `user` con
# content = [{type: text, source_lang_code, target_lang_code, text}]. Fonte: chat_template.jinja del modello
# google/translategemma-12b-it. Dizionario delle lingue: i soli codici di base (160) del template originale; un codice
# con regione ('pt-BR', 'pt_BR') si risolve sulla lingua di base (il template ne elenca solo alcuni), quindi accetta
# qualcosa in piu' dell'originale e mai qualcosa di meno. Per tutti i codici di
# `LLMSubtitleTranslator.LANGUAGE_CODES` il risultato e' identico (test: linux_tests/test_gguf_engine.py).
# ---------------------------------------------------------------------------
LANGUAGES: Dict[str, str] = {
    "aa": "Afar", "ab": "Abkhazian", "af": "Afrikaans", "ak": "Akan", "am": "Amharic", "an": "Aragonese",
    "ar": "Arabic", "as": "Assamese", "az": "Azerbaijani", "ba": "Bashkir", "be": "Belarusian",
    "bg": "Bulgarian", "bm": "Bambara", "bn": "Bengali", "bo": "Tibetan", "br": "Breton", "bs": "Bosnian",
    "ca": "Catalan", "ce": "Chechen", "co": "Corsican", "cs": "Czech", "cv": "Chuvash", "cy": "Welsh",
    "da": "Danish", "de": "German", "dv": "Divehi", "dz": "Dzongkha", "ee": "Ewe", "el": "Greek",
    "en": "English", "eo": "Esperanto", "es": "Spanish", "et": "Estonian", "eu": "Basque", "fa": "Persian",
    "ff": "Fulah", "fi": "Finnish", "fo": "Faroese", "fr": "French", "fy": "Western Frisian", "ga": "Irish",
    "gd": "Scottish Gaelic", "gl": "Galician", "gn": "Guarani", "gu": "Gujarati", "gv": "Manx", "ha": "Hausa",
    "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "ht": "Haitian", "hu": "Hungarian", "hy": "Armenian",
    "ia": "Interlingua", "id": "Indonesian", "ie": "Interlingue", "ig": "Igbo", "ii": "Sichuan Yi",
    "ik": "Inupiaq", "io": "Ido", "is": "Icelandic", "it": "Italian", "iu": "Inuktitut", "ja": "Japanese",
    "jv": "Javanese", "ka": "Georgian", "ki": "Kikuyu", "kk": "Kazakh", "kl": "Kalaallisut",
    "km": "Central Khmer", "kn": "Kannada", "ko": "Korean", "ks": "Kashmiri", "ku": "Kurdish", "kw": "Cornish",
    "ky": "Kyrgyz", "la": "Latin", "lb": "Luxembourgish", "lg": "Ganda", "ln": "Lingala", "lo": "Lao",
    "lt": "Lithuanian", "lu": "Luba-Katanga", "lv": "Latvian", "mg": "Malagasy", "mi": "Maori",
    "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi", "ms": "Malay", "mt": "Maltese",
    "my": "Burmese", "nb": "Norwegian Bokmål", "nd": "North Ndebele", "ne": "Nepali", "nl": "Dutch",
    "nn": "Norwegian Nynorsk", "no": "Norwegian", "nr": "South Ndebele", "nv": "Navajo", "ny": "Chichewa",
    "oc": "Occitan", "om": "Oromo", "or": "Oriya", "os": "Ossetian", "pa": "Punjabi", "pl": "Polish",
    "ps": "Pashto", "pt": "Portuguese", "qu": "Quechua", "rm": "Romansh", "rn": "Rundi", "ro": "Romanian",
    "ru": "Russian", "rw": "Kinyarwanda", "sa": "Sanskrit", "sc": "Sardinian", "sd": "Sindhi",
    "se": "Northern Sami", "sg": "Sango", "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "sn": "Shona",
    "so": "Somali", "sq": "Albanian", "sr": "Serbian", "ss": "Swati", "st": "Southern Sotho", "su": "Sundanese",
    "sv": "Swedish", "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "tg": "Tajik", "th": "Thai",
    "ti": "Tigrinya", "tk": "Turkmen", "tl": "Tagalog", "tn": "Tswana", "to": "Tonga", "tr": "Turkish",
    "ts": "Tsonga", "tt": "Tatar", "ug": "Uyghur", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek",
    "ve": "Venda", "vi": "Vietnamese", "vo": "Volapük", "wa": "Walloon", "wo": "Wolof", "xh": "Xhosa",
    "yi": "Yiddish", "yo": "Yoruba", "za": "Zhuang", "zh": "Chinese", "zu": "Zulu",
}


def _template_error_base():
    """Eccezione del codice lingua sconosciuto: la stessa famiglia di quella del template Jinja del motore storico.

    `SubtitleLLMTranslator._translate_mt` risolleva i `jinja2.TemplateError` invece di svuotare in silenzio ogni
    batch: un codice lingua assente e' deterministico, e ripeterlo su tutti i blocchi non lo aggiusterebbe."""
    try:
        import jinja2
        return jinja2.TemplateError
    except Exception:
        return ValueError


class GGUFCancelled(RuntimeError):
    """Il motore GGUF e' stato fermato dall'utente (Stop): non e' un caricamento fallito e non si ripiega su altri motori."""


class UnknownLanguageError(_template_error_base()):
    pass


def _lang(code: str) -> str:
    code = str(code).replace("_", "-")
    name = LANGUAGES.get(code) or LANGUAGES.get(code.split("-")[0])
    if name is None:
        raise UnknownLanguageError(f"Codice lingua sconosciuto per TranslateGemma: {code!r}")
    return name


def render_prompt(messages: List[Dict[str, Any]], add_generation_prompt: bool = True,
                  bos: str = BOS) -> str:
    """Testo del prompt: identico a quello del chat template ufficiale per i messaggi di `mt_messages`."""
    if not messages or messages[0].get("role") != "user":
        raise ValueError("Conversations must start with a user prompt.")
    out = [bos]
    for i, m in enumerate(messages):
        role = m.get("role")
        if (role == "user") != (i % 2 == 0):
            raise ValueError("Conversation roles must alternate user/assistant/user/assistant/...")
        if role == "assistant":
            content = m.get("content")
            if not isinstance(content, str):
                raise ValueError("Assistant role must provide content as a string")
            out.append("<start_of_turn>model\n" + content.strip())
        elif role == "user":
            content = m.get("content")
            if not isinstance(content, list) or len(content) != 1:
                raise ValueError("User role must provide `content` as an iterable with exactly one item.")
            c = content[0]
            if c.get("type") != "text":
                raise ValueError("User role `content` can contain only `text` data.")
            src_code = str(c["source_lang_code"]).replace("_", "-")
            tgt_code = str(c["target_lang_code"]).replace("_", "-")
            src, tgt = _lang(src_code), _lang(tgt_code)
            out.append(
                "<start_of_turn>user\nYou are a professional " + src + " (" + src_code + ") to " + tgt + " ("
                + tgt_code + ") translator. Your goal is to accurately convey the meaning and nuances of the "
                "original " + src + " text while adhering to " + tgt + " grammar, vocabulary, and cultural "
                "sensitivities.\n"
                "Produce only the " + tgt + " translation, without any additional explanations or commentary. "
                "Please translate the following " + src + " text into " + tgt + ":\n\n\n" + str(c["text"]).strip())
        else:
            raise ValueError("Conversations must only contain user or assistant roles.")
        out.append("<end_of_turn>\n")
    if add_generation_prompt:
        out.append("<start_of_turn>model\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# llama.cpp: log muto (come verbose=False dell'API alta) e accesso ai simboli
# ---------------------------------------------------------------------------
_NOOP_LOG = None


def _silence_llama_log(ll) -> None:
    """Installa un callback di log che scarta tutto. Il riferimento resta in una globale: se il garbage collector
    liberasse il callback mentre llama.cpp lo chiama, il processo andrebbe in crash."""
    global _NOOP_LOG
    try:
        _NOOP_LOG = ll.llama_log_callback(lambda level, text, user_data: None)
        ll.llama_log_set(_NOOP_LOG, ctypes.c_void_p(0))
    except Exception as exc:
        logger.debug(f"llama_log_set: {exc}")


def _meta_str(ll, model, key: str) -> Optional[str]:
    buf = ctypes.create_string_buffer(256)
    n = ll.llama_model_meta_val_str(model, key.encode("utf-8"), buf, len(buf))
    return buf.value.decode("utf-8", errors="replace") if n >= 0 else None


class GGUFEngine(SubtitleLLMEngine):
    """Carica un GGUF di TranslateGemma con llama.cpp e genera completamenti da messaggi chat."""

    def __init__(self, gguf_path: str, quant: str,
                 model_key: str = DEFAULT_MODEL_KEY,
                 log_callback: Optional[Callable] = None,
                 n_parallel: int = 4, ctx_per_seq: int = 512,
                 n_gpu_layers: int = -1, expected_arch: Optional[str] = EXPECTED_ARCH):
        super().__init__(model_key, log_callback, adapter=None, model_path=str(gguf_path))
        self.quant = quant
        self.gguf_path = str(gguf_path)
        self.n_parallel = max(1, int(n_parallel))
        self.ctx_per_seq = max(64, int(ctx_per_seq))
        self.n_gpu_layers = n_gpu_layers
        self.expected_arch = expected_arch
        # Il tetto del batch e' il parallelismo di sequenze: l'etichetta dice che pesi sono in uso.
        self.spec = dataclasses.replace(
            MODEL_SPECS[model_key],
            label=f"{MODEL_SPECS[model_key].label} (GGUF {quant})",
            max_batch=self.n_parallel)
        self._ll = None
        self._llm_model = None
        self._ctx = None
        self._vocab = None
        self._batch = None
        self._sampler = None
        self._n_batch = 512
        self._stop_ids: set = set()
        # generate() e unload() non devono mai sovrapporsi (neppure da thread diversi: annullo dalla GUI, cleanup):
        # liberare contesto e batch mentre llama_decode li usa chiude l'intero processo.
        self._run_lock = RLock()

    # -- caricamento ------------------------------------------------------
    def load(self) -> None:
        if self._ctx is not None:
            return
        try:
            # Come gli altri import in-process di llama.cpp del progetto: su Windows le DLL di torch devono essere nel PATH.
            from utils.cuda_dll_path import ensure_torch_lib_on_path
            ensure_torch_lib_on_path()
        except Exception as exc:
            logger.debug(f"ensure_torch_lib_on_path: {exc}")
        try:
            import llama_cpp as ll
        except Exception as exc:
            raise RuntimeError(tr('gg_err_llama').format(exc=exc)) from exc
        if not Path(self.gguf_path).is_file():
            raise RuntimeError(tr('gg_err_file_missing').format(path=self.gguf_path))
        try:
            # Windows (ruote CUDA/Vulkan con backend caricati dinamicamente): llama_supports_gpu_offload() PRIMA di qualunque Llama()
            # legge un registro dei backend ancora vuoto e va in access violation. llama_backend_init() e' quello che fa Llama() alla
            # prima istanza (idempotente): lo si chiama prima del controllo.
            ll.llama_backend_init()
        except Exception as exc:
            logger.debug(f"llama_backend_init: {exc}")
        if self.n_gpu_layers != 0 and not ll.llama_supports_gpu_offload():
            # Una ruota solo-CPU eseguirebbe un 12B sulla CPU: piu' lento di NLLB e senza averlo detto.
            raise RuntimeError(tr('gg_err_no_gpu_offload'))
        self._ll = ll
        self.log(tr('le_loading_model').format(label=self.spec.label))
        _silence_llama_log(ll)
        ll.llama_backend_init()

        mp = ll.llama_model_default_params()
        mp.n_gpu_layers = 0x7FFFFFFF if self.n_gpu_layers == -1 else int(self.n_gpu_layers)
        mp.use_mmap = True
        model = ll.llama_model_load_from_file(self.gguf_path.encode("utf-8"), mp)
        if not model:
            raise RuntimeError(tr('gg_err_load').format(path=self.gguf_path))
        self._llm_model = model
        try:
            arch = _meta_str(ll, model, "general.architecture")
            if self.expected_arch and arch != self.expected_arch:
                raise RuntimeError(tr('gg_err_arch').format(arch=arch, expected=self.expected_arch))

            n_ctx = self.n_parallel * self.ctx_per_seq
            cp = ll.llama_context_default_params()
            cp.n_ctx = n_ctx
            cp.n_batch = self._n_batch
            cp.n_ubatch = self._n_batch
            cp.n_seq_max = self.n_parallel
            # Una sola cache KV condivisa: n_ctx e' il totale per tutte le sequenze, non per ciascuna.
            cp.kv_unified = True
            self._ctx = ll.llama_init_from_model(model, cp)
            if not self._ctx:
                self._ctx = None
                raise RuntimeError(tr('gg_err_no_context'))
            self._vocab = ll.llama_model_get_vocab(model)
            self._batch = ll.llama_batch_init(self._n_batch, 0, self.n_parallel)
            chain = ll.llama_sampler_chain_init(ll.llama_sampler_chain_default_params())
            ll.llama_sampler_chain_add(chain, ll.llama_sampler_init_greedy())
            self._sampler = chain
            eot = self._tokenize(END_OF_TURN)
            self._stop_ids = {eot[0]} if len(eot) == 1 else set()
        except Exception:
            self.unload(quiet=True)
            raise
        self.log(tr('gg_ready').format(
            label=self.spec.label, n=self.n_parallel, ctx=self.ctx_per_seq))

    # -- tokenizzazione ---------------------------------------------------
    def _tokenize(self, text: str) -> List[int]:
        """Il testo e' gia' il prompt completo (BOS compreso): add_special=False, parse_special=True."""
        ll = self._ll
        data = text.encode("utf-8")
        cap = len(data) + 16
        buf = (ll.llama_token * cap)()
        n = ll.llama_tokenize(self._vocab, data, len(data), buf, cap, False, True)
        if n < 0:
            cap = -n
            buf = (ll.llama_token * cap)()
            n = ll.llama_tokenize(self._vocab, data, len(data), buf, cap, False, True)
        if n < 0:
            raise RuntimeError("llama_tokenize ha fallito")
        return list(buf[:n])

    def _piece(self, token: int) -> bytes:
        ll = self._ll
        buf = ctypes.create_string_buffer(256)
        n = ll.llama_token_to_piece(self._vocab, token, buf, len(buf), 0, False)
        return buf.raw[:n] if n > 0 else b""

    # -- generazione ------------------------------------------------------
    def generate(self, conversations: List[List[Dict[str, Any]]],
                 max_new_tokens: int = 512,
                 **overrides: Any) -> List[str]:
        """Una risposta per conversazione, nell'ordine di input. Gli override di campionamento sono ignorati
        (decodifica greedy, vedi il commento in testa al modulo)."""
        with self._run_lock:
            if self._ctx is None:
                self.load()
            results: List[str] = []
            for i in range(0, len(conversations), self.n_parallel):
                results.extend(self._generate_group(conversations[i:i + self.n_parallel], max_new_tokens))
            return results

    def _generate_group(self, group: List[List[Dict[str, Any]]], max_new_tokens: int) -> List[str]:
        ll = self._ll
        prompts: List[Optional[List[int]]] = []
        budgets: List[int] = []
        for conv in group:
            toks = self._tokenize(render_prompt(conv))
            room = self.ctx_per_seq - len(toks)
            if room < 16:
                logger.warning(f"Prompt di {len(toks)} token oltre il contesto per sequenza "
                               f"({self.ctx_per_seq}): blocco lasciato vuoto")
                prompts.append(None)
                budgets.append(0)
            else:
                prompts.append(toks)
                budgets.append(min(max_new_tokens, room))
                if room < max_new_tokens:
                    logger.info(f"Risposta limitata a {room} token dal contesto per sequenza ({self.ctx_per_seq})")
        live = [i for i, p in enumerate(prompts) if p is not None]
        outs: Dict[int, bytearray] = {i: bytearray() for i in live}
        if not live:
            return [""] * len(group)

        mem = ll.llama_get_memory(self._ctx)
        ll.llama_memory_clear(mem, True)
        batch = self._batch
        try:
            # --- prefill: i prompt a pezzi da n_batch token, logits solo sull'ultimo token di ciascuna sequenza
            next_tok: Dict[int, int] = {}
            fill = 0
            last_here: Dict[int, int] = {}      # sequenza -> indice nel batch del suo ultimo token

            def flush():
                nonlocal fill, last_here
                if fill == 0:
                    return
                batch.n_tokens = fill
                rc = ll.llama_decode(self._ctx, batch)
                if rc != 0:
                    raise RuntimeError(f"llama_decode ha restituito {rc} (prefill)")
                for s, idx in last_here.items():
                    next_tok[s] = ll.llama_sampler_sample(self._sampler, self._ctx, idx)
                fill, last_here = 0, {}

            for s in live:
                toks = prompts[s]
                for pos, t in enumerate(toks):
                    if fill == self._n_batch:
                        flush()
                    batch.token[fill] = t
                    batch.pos[fill] = pos
                    batch.n_seq_id[fill] = 1
                    batch.seq_id[fill][0] = s
                    is_last = pos == len(toks) - 1
                    batch.logits[fill] = is_last
                    if is_last:
                        last_here[s] = fill
                    fill += 1
            flush()

            # --- generazione in lockstep: un token per sequenza attiva a ogni llama_decode
            active = list(live)
            n_gen = {s: 0 for s in live}
            while active:
                still: List[int] = []
                for s in active:
                    tok = next_tok[s]
                    if ll.llama_vocab_is_eog(self._vocab, tok) or tok in self._stop_ids:
                        continue
                    outs[s] += self._piece(tok)
                    n_gen[s] += 1
                    if n_gen[s] < budgets[s]:
                        still.append(s)
                active = still
                if not active:
                    break
                for k, s in enumerate(active):
                    batch.token[k] = next_tok[s]
                    batch.pos[k] = len(prompts[s]) + n_gen[s] - 1
                    batch.n_seq_id[k] = 1
                    batch.seq_id[k][0] = s
                    batch.logits[k] = True
                batch.n_tokens = len(active)
                rc = ll.llama_decode(self._ctx, batch)
                if rc != 0:
                    raise RuntimeError(f"llama_decode ha restituito {rc}")
                for k, s in enumerate(active):
                    next_tok[s] = ll.llama_sampler_sample(self._sampler, self._ctx, k)
        finally:
            ll.llama_memory_clear(mem, True)
        return [bytes(outs[i]).decode("utf-8", errors="replace").strip() if i in outs else ""
                for i in range(len(group))]

    # -- scarico ----------------------------------------------------------
    def unload(self, quiet: bool = False) -> None:
        """Libera contesto e pesi (anche la VRAM: llama.cpp alloca fuori dall'allocatore di PyTorch)."""
        with self._run_lock:
            self._unload_locked(quiet)

    def _unload_locked(self, quiet: bool) -> None:
        if self._ctx is None and self._llm_model is None:
            return
        if not quiet:
            self.log(tr('le_unloading_from_vram').format(label=self.spec.label))
        ll = self._ll
        for name, free in (("_sampler", "llama_sampler_free"), ("_batch", "llama_batch_free"),
                           ("_ctx", "llama_free"), ("_llm_model", "llama_model_free")):
            obj = getattr(self, name)
            if obj is not None:
                try:
                    getattr(ll, free)(obj)
                except Exception as exc:
                    logger.debug(f"{free}: {exc}")
            setattr(self, name, None)
        self._vocab = None
        self._stop_ids = set()
        gc.collect()


# --------------------------------------------------------------------------
# Singleton di processo, come per il motore transformers
# --------------------------------------------------------------------------
_gguf_lock = Lock()
_gguf_engine: Optional[GGUFEngine] = None


def get_gguf_engine(gguf_path: str, quant: str,
                    model_key: str = DEFAULT_MODEL_KEY,
                    log_callback: Optional[Callable] = None,
                    n_parallel: int = 4, ctx_per_seq: int = 512, in_process: bool = False) -> GGUFEngine:
    """Restituisce il motore GGUF per questo file e questi parametri, caricandolo se serve.

    Di norma e' un `GGUFSubprocessEngine` (processo di lavoro pulito: su Windows `llama_cpp` importato dopo `utils`/PyQt6
    manda in crash `llama_supports_gpu_offload`). `in_process=True` carica in questo processo: solo per chi sa che
    `llama_cpp` e' il primo import nativo (il processo di lavoro stesso, il banco) e per i test."""
    global _gguf_engine
    with _gguf_lock:
        if _gguf_engine is not None and (
                _gguf_engine.gguf_path != str(gguf_path)
                or _gguf_engine.n_parallel != max(1, int(n_parallel))
                or _gguf_engine.ctx_per_seq != max(64, int(ctx_per_seq))
                or _gguf_engine.model_key != model_key
                or (type(_gguf_engine) is GGUFEngine) != in_process):
            _gguf_engine.unload()
            _gguf_engine = None
        if _gguf_engine is None:
            if in_process:
                _gguf_engine = GGUFEngine(gguf_path, quant, model_key, log_callback, n_parallel, ctx_per_seq)
            else:
                from .gguf_subprocess import GGUFSubprocessEngine
                _gguf_engine = GGUFSubprocessEngine(gguf_path, quant, model_key, log_callback, n_parallel, ctx_per_seq)
        elif log_callback:
            _gguf_engine.log_callback = log_callback
        try:
            _gguf_engine.load()
        except Exception:
            _gguf_engine = None
            raise
        return _gguf_engine


def unload_gguf_engine() -> None:
    global _gguf_engine
    # Stop dell'utente durante un caricamento o una generazione: il motore a sottoprocesso si chiude PRIMA di prendere il
    # lock (che get_gguf_engine tiene per tutta la durata del caricamento).
    abort = getattr(_gguf_engine, 'abort', None)
    if abort is not None:
        abort()
    with _gguf_lock:
        if _gguf_engine is not None:
            _gguf_engine.unload()
            _gguf_engine = None


def current_gguf_engine() -> Optional[GGUFEngine]:
    """Il motore GGUF caricato adesso, se c'e' (non ne carica uno)."""
    return _gguf_engine
