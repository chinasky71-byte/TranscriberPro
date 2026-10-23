"""
Punctuation Restorer
File: core/punctuation_restorer.py

Ripristina la punteggiatura sulle parole allineate quando l'ASR la
restituisce assente (v. piano_fix_pipeline_trascrizione punto D). Lavora
sulla lista di parole con timestamp, non sul testo: la corrispondenza
parola↔timestamp è garantita per costruzione dai word_ids() del tokenizer
(is_split_into_words=True + predizione del primo sub-token per parola),
non da un confronto testuale a posteriori — il numero di parole in
ingresso e uscita è identico per costruzione.

Modello: oliverguhr/fullstop-punctuation-multilang-large (token
classification, XLM-RoBERTa-large). Gira su CPU per default: non deve
competere con ASR+aligner residenti in VRAM proprio nel momento peggiore,
e il costo su CPU (finestre di poche centinaia di parole) è trascurabile
rispetto ai tempi di STEP 3/4.
"""
from __future__ import annotations
import re
import unicodedata
from typing import Callable, List, Optional
from utils.translations import tr

logger_name = __name__

# Finestratura: XLM-R ha limite 512 sub-token. 150 parole italiane restano
# ampiamente sotto quel limite anche con parole spezzate in più sub-token;
# 30 parole di overlap danno contesto sufficiente ai bordi, dove la
# predizione è meno affidabile.
WINDOW_WORDS = 150
WINDOW_OVERLAP = 30

# Etichette che chiudono una frase: la parola successiva va maiuscolizzata.
# Il modello non prevede '!' fra le sue classi (0, '.', ',', '?', '-', ':').
_SENTENCE_END_LABELS = {'.', '?'}

# Whitelist delle etichette di punteggiatura valide (model card: fullstop-
# punctuation-multilang-large produce esattamente questi segni oltre a
# nessuna punteggiatura). Qualunque altra cosa viene scartata (v. bug-check
# Opus, piano_fix_pipeline_trascrizione punto D).
_VALID_LABELS = {'.', ',', '?', ':', '-'}

_WORD_RE = re.compile(r'\w+', re.UNICODE)


def normalize_words_for_guard(text: str) -> List[str]:
    """Sequenza di parole confrontabile: NFKC, minuscole, sola classe \\w.

    Condivisa con la guardia della via LLM (opzione D.3) e con
    SubtitleFormatter._normalize_for_dedup — stessa forma normale in tutto
    il progetto per confronti "stesse parole, punteggiatura ignorata".
    """
    return _WORD_RE.findall(unicodedata.normalize('NFKC', text).lower())


class PunctuationRestorer:
    """Ripristina la punteggiatura su parole allineate prive di essa.

    Uso tipico (dentro un engine ASR, dopo _attach_punct_words e prima di
    _words_to_segments):

        if PunctuationRestorer.needs_restoration(text):
            restorer = self._get_punctuation_restorer()  # lazy, cached
            words = restorer.restore_words(words, language)
    """

    SUPPORTED_LANGS = {'en', 'de', 'fr', 'it'}  # lingue del modello multilang

    def __init__(self, model_id: str = 'oliverguhr/fullstop-punctuation-multilang-large',
                 device: str = 'cpu', log_callback: Optional[Callable] = None):
        self.model_id = model_id
        self.device = device
        self.log = log_callback or (lambda _msg: None)
        self._tokenizer = None
        self._model = None
        self._load_failed = False
        self._warned_unexpected_label = False

    # ------------------------------------------------------------------
    # Diagnosi
    # ------------------------------------------------------------------
    @staticmethod
    def needs_restoration(text: str, min_density: float = 0.0) -> bool:
        """True se il testo va ripunteggiato.

        min_density=0.0 (default) replica esattamente la diagnostica già
        in produzione: SOLO i testi del tutto privi di punteggiatura.
        Un min_density > 0 estende ai testi quasi-nudi (densità = numero
        di segni di punteggiatura forte/debole ogni parola).
        """
        text = text.strip()
        if not text:
            return False
        has_any_punct = any(ch in '.,!?;:…' for ch in text)
        if min_density <= 0.0:
            return not has_any_punct
        n_words = max(1, len(text.split()))
        # Gruppi di punteggiatura, non caratteri: "..." e "…" devono contare
        # come UNA pausa ciascuno, non 3 vs 1 (gonfierebbe la densità del
        # primo triplicandola rispetto al secondo per la stessa pausa).
        n_punct = len(re.findall(r'[.,!?;:…]+', text))
        return (n_punct / n_words) < min_density

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load(self) -> bool:
        """Carica tokenizer + modello. Lazy, idempotente.

        Fallimento (modello non scaricabile, offline, ecc.) = passthrough:
        restore_words tornerà l'input invariato, mai un'eccezione che
        faccia fallire la trascrizione.
        """
        if self._model is not None:
            return True
        if self._load_failed:
            return False
        try:
            from transformers import AutoTokenizer, AutoModelForTokenClassification
            import torch

            self.log(tr('pr_loading_punctuation_model').format(model_id=self.model_id))
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
            self._model = AutoModelForTokenClassification.from_pretrained(self.model_id)
            self._model.to(self.device)
            self._model.eval()
            self._torch = torch

            # Self-test: word_ids() richiede un tokenizer "fast" (backend
            # Rust). Senza, _predict_window fallirebbe silenziosamente su
            # OGNI finestra per l'intero film (un warning per chunk invece
            # di un errore chiaro una volta sola) — meglio scoprirlo qui.
            test_encoding = self._tokenizer(['prova'], is_split_into_words=True,
                                             return_tensors='pt')
            word_ids = test_encoding.word_ids(batch_index=0)
            if word_ids is None or all(w is None for w in word_ids):
                raise RuntimeError(
                    tr('pr_tokenizer_does_not_expose_word').format(model_id=self.model_id))

            self.log(tr('pr_punctuation_model_loaded_on').format(device=self.device.upper()))
            return True
        except Exception as e:
            self._load_failed = True
            self._model = None
            self._tokenizer = None
            self.log(tr('pr_punctuation_model_not_available_restoration').format(e=e))
            return False

    def unload(self) -> None:
        """Scarica tokenizer + modello. Stesso pattern di Diarizer.unload()
        e Qwen3AsrEngine.unload(): guardia is not None, mai eccezione."""
        try:
            if self._model is not None:
                del self._model
                self._model = None
            if self._tokenizer is not None:
                del self._tokenizer
                self._tokenizer = None
            import gc
            gc.collect()
            if self.device != 'cpu':
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Ripristino
    # ------------------------------------------------------------------
    def restore_words(self, words: List[dict], language: str) -> List[dict]:
        """Restituisce una NUOVA lista con gli stessi start/end e le stesse
        parole, arricchite di punteggiatura. len() invariata, garantito:
        si modifica solo la stringa 'word' di ciascun dict, mai la lista.

        Passthrough silenzioso (lista invariata, copiata) se: lingua non
        supportata, modello non caricato/caricabile, lista vuota.
        """
        if not words:
            return words
        if language not in self.SUPPORTED_LANGS:
            return list(words)
        if not self.load():
            return list(words)

        raw_words = [w.get('word', '').strip() for w in words]
        n = len(raw_words)

        # best[i] = (distanza dal bordo finestra, etichetta) — vince la
        # finestra in cui la parola i è più centrale: ai bordi il contesto
        # è monco proprio dove la decisione conta.
        best_dist = [-1] * n
        best_label = ['0'] * n

        stride = max(1, WINDOW_WORDS - WINDOW_OVERLAP)
        starts = list(range(0, max(1, n - WINDOW_OVERLAP), stride))
        if not starts or starts[-1] + WINDOW_WORDS < n:
            starts.append(max(0, n - WINDOW_WORDS))

        for w_start in sorted(set(starts)):
            w_end = min(n, w_start + WINDOW_WORDS)
            window_words = raw_words[w_start:w_end]
            if not window_words:
                continue
            labels = self._predict_window(window_words)
            if labels is None:
                continue
            for local_idx, label in enumerate(labels):
                dist = min(local_idx, len(window_words) - 1 - local_idx)
                global_idx = w_start + local_idx
                if dist > best_dist[global_idx]:
                    best_dist[global_idx] = dist
                    best_label[global_idx] = label

        result = []
        capitalize_next = True
        for i, w in enumerate(words):
            new_w = dict(w)
            # Rimuove punteggiatura già presente (_attach_punct_words può
            # averla riagganciata anche su testo parzialmente punteggiato,
            # es. mode='all' o min_density>0): altrimenti si concatena la
            # nuova etichetta a quella esistente ("stai?" + "?" → "stai??").
            token = raw_words[i].rstrip('.,;:!?…-')
            label = best_label[i]
            if capitalize_next and token:
                token = token[0].upper() + token[1:]
                capitalize_next = False
            if label and label != '0':
                token = token + label
                if label in _SENTENCE_END_LABELS:
                    capitalize_next = True
            new_w['word'] = token
            result.append(new_w)
        return result

    def _predict_window(self, window_words: List[str]) -> Optional[List[str]]:
        """Predice un'etichetta per parola su UNA finestra.

        is_split_into_words=True + word_ids(): la predizione del primo
        sub-token di ogni parola è per costruzione una sola etichetta per
        parola — non serve verificare l'allineamento, non può romperlo.
        """
        try:
            encoding = self._tokenizer(
                window_words, is_split_into_words=True,
                truncation=True, max_length=512, return_tensors='pt',
            )
            with self._torch.no_grad():
                logits = self._model(**{k: v.to(self.device) for k, v in encoding.items()}).logits
            pred_ids = logits.argmax(dim=-1)[0].tolist()
            id2label = self._model.config.id2label

            word_ids = encoding.word_ids(batch_index=0)
            labels = ['0'] * len(window_words)
            seen = set()
            for tok_idx, w_idx in enumerate(word_ids):
                if w_idx is None or w_idx in seen:
                    continue
                seen.add(w_idx)
                raw_label = id2label.get(pred_ids[tok_idx], '0')
                # Whitelist, non blacklist: se il modello (o un fork/
                # riaddestramento futuro) restituisce etichette diverse dai
                # segni letterali attesi, si scarta invece di iniettare
                # testo spurio nelle parole ("parolaLABEL_3").
                if raw_label not in _VALID_LABELS:
                    if raw_label not in ('O', 'o', '0', 0) and not self._warned_unexpected_label:
                        self._warned_unexpected_label = True
                        self.log(tr('pr_unexpected_punctuation_label_from_the').format(raw_label=raw_label))
                    raw_label = '0'
                labels[w_idx] = raw_label
            return labels
        except Exception as e:
            self.log(tr('pr_punctuation_prediction_failed_on_a').format(e=e))
            return None
