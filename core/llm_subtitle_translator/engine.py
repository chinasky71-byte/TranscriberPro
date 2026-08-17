"""
Motore LLM per la traduzione di sottotitoli — caricamento e generazione
=======================================================================
Unico punto del package che conosce i pesi. Il resto della pipeline lavora su
messaggi in formato chat e non sa quale modello ci sia dietro: cambiare
occupante dello slot è una riga in MODEL_SPECS.

Quattro difetti del ramo LLM storico sono corretti qui, e vale la pena
tenerli a mente prima di aggiungere un modello nuovo:

1. Il prompt passa da `tokenizer.apply_chat_template()`. Ogni modello ha il
   proprio formato di turno; usarlo in raw completion mode significa
   valutarlo fuori distribuzione.
2. `padding_side = "left"`. Con il padding a destra (default del tokenizer) e
   batch > 1, lo slice `outputs[:, input_len:]` cade in mezzo al padding e
   restituisce testo corrotto per ogni sequenza più corta della più lunga del
   batch.
3. Decoding deterministico e nessuna `repetition_penalty`: quel parametro
   agisce sull'identità dei token e in traduzione forza sinonimi innaturali,
   perché non distingue una ripetizione legittima (un nome che ricorre) da un
   loop degenerato.
4. Quantizzazione NF4 invece di LLM.int8(), che è la modalità bitsandbytes più
   lenta e lascia meno VRAM per il contesto.

I parametri di generazione sono PER MODELLO e vengono dai rispettivi vendor:
non vanno trasferiti da un modello all'altro (Hunyuan-MT è calibrato su
sampling, Tower+ su temperature 0, TranslateGemma su greedy).
"""

from __future__ import annotations

import gc
import os
import re
import sys
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

from utils.logger import setup_logger

logger = setup_logger(__name__)

# L'allocatore di PyTorch riserva blocchi di dimensione fissa e, quando il
# batch cambia da una chiamata all'altra, li frammenta: su una scheda da 12 GB
# occupata per tre quarti dai soli pesi di un 12B quantizzato, la frammentazione
# basta a far sconfinare l'allocazione successiva nella RAM di sistema. I
# segmenti espandibili riusano lo stesso blocco invece di chiederne uno nuovo.
#
# MISURATO: su Windows non è disponibile — PyTorch lo ignora con
# "expandable_segments not supported on this platform" (CUDAAllocatorConfig.h).
# Resta impostato per il ramo Docker headless, che gira su Linux; su Windows
# l'unico regolatore del picco è quindi il tetto al batch, non l'allocatore.
if sys.platform != "win32":
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


@dataclass(frozen=True)
class ModelSpec:
    """Tutto ciò che distingue un occupante dello slot dagli altri."""

    model_id: str
    label: str
    # Parametri passati a model.generate(). Fonte: model card del vendor.
    generation: Dict[str, Any] = field(default_factory=dict)
    # Come si interroga il modello:
    #   "adapt" — un prompt di sistema con le regole del sottotitolo e un
    #             batch di blocchi in JSON. Richiede un modello che segua
    #             istruzioni complesse.
    #   "mt"    — il prompt nativo di traduzione del vendor, una battuta per
    #             chiamata. È il modo in cui un modello MT specializzato è
    #             stato addestrato, e forzarlo nello schema "adapt" ne spreca
    #             il vantaggio.
    prompt_style: str = "adapt"
    # Come si carica il modello:
    #   "causal"  — AutoModelForCausalLM + AutoTokenizer, il caso normale.
    #   "gemma3"  — AutoModelForImageTextToText + AutoProcessor. I modelli
    #               TranslateGemma sono Gemma3ForConditionalGeneration e il
    #               loro chat template NON sta nel tokenizer ma nel processor;
    #               vuole inoltre un `content` strutturato con i campi
    #               source_lang_code / target_lang_code.
    loader: str = "causal"
    # Finestra di contesto utile (token). Tower+ si ferma a 8K.
    context_window: int = 8192
    # VRAM libera (GB) sotto la quale conviene NF4 invece di bf16.
    bf16_min_free_gb: float = 20.0
    # Quante conversazioni al massimo nella stessa `generate()`. È il vero
    # regolatore del picco di VRAM: i pesi sono una costante, mentre la KV
    # cache e le attivazioni crescono in proporzione al batch. Su WDDM
    # superare la memoria dedicata non produce un OOM ma uno sconfinamento
    # silenzioso nella RAM di sistema — nessun errore, solo un rallentamento
    # di 4-5 volte — quindi il tetto va messo per modello, misurato con
    # `mt_eval/vram_probe.py`, non lasciato a un valore unico per tutti.
    max_batch: int = 12
    # Istruzioni da anteporre al testo dentro il prompt nativo (solo
    # prompt_style="mt"). Serve ai modelli MT il cui chat template non prevede
    # un ruolo di sistema: l'unico canale per dargli una regola è il campo del
    # testo da tradurre. Vuoto = prompt del vendore intatto.
    mt_prefix: str = ""
    # Quando applicare `mt_prefix`. Se resta None il prefisso va su ogni
    # battuta; con un pattern, solo su quelle che lo contengono. Serve perché
    # un'istruzione può essere un guadagno su una classe di battute e un danno
    # su tutte le altre — vedi la tabella su MT_PREFIX_TRIGGER.
    mt_prefix_when: Optional[Any] = None
    # Istruzione sul budget di caratteri, con un segnaposto `{budget}`. Va
    # tenuta separata da `mt_prefix` perché ha una condizione diversa: il
    # registro serve solo dove c'è del turpiloquio, il budget vale sempre —
    # è autolimitante, su una battuta corta non chiede di tagliare niente.
    mt_budget_rule: str = ""
    gated: bool = False
    notes: str = ""


# Le regole che TranslateGemma può ricevere, e l'unico posto da cui può
# riceverle. Il suo chat template costruisce da sé l'istruzione di traduzione
# a partire dai codici lingua e non prevede un ruolo di sistema: il campo
# `text` è l'unico canale aperto.
#
# MISURATO su 40 blocchi di Deadpool 2 (mt_eval/probe_tg_prompt.py), metà con
# turpiloquio. Senza queste righe il modello conservava 3 volgarità su 20 e
# rendeva "pumpkin fucker" con "idiota"; con queste, 14 su 20 — quanto il
# sottotitolo professionale della pellicola, che ne conserva 15. Il rapporto di
# lunghezza scende da 1,15 a 1,10 volte l'inglese. Costo: due secondi ogni
# quaranta blocchi.
#
# Restano corte di proposito: il testo finisce dentro un'istruzione di
# traduzione, e più righe si aggiungono più cresce il rischio che il modello le
# traduca invece di applicarle. Una terza variante che scavalcava del tutto il
# template per dettare regole più lunghe conservava ancora più volgarità (18 su
# 20) ma, uscendo dalla forma su cui il modello è addestrato, produceva parole
# inesistenti ("indemaniato") e concordanze sbagliate: guadagno sul registro,
# perdita sulla lingua. Scartata.
#
# NOTA: la stringa misurata comprendeva anche "più breve dell'originale, senza
# riempitivi", che il giudizio ha poi mostrato dannosa sui blocchi normali. Quel
# pezzo è stato sostituito da MT_BUDGET_RULE, che dice un numero invece di un
# aggettivo. Qui resta la sola clausola sul registro.
TRANSLATEGEMMA_SUBTITLE_RULES = (
    "Conserva le parolacce con parolacce italiane "
    "(fuck→cazzo, shit→merda, asshole→stronzo)."
)

# Su QUALI battute mettere la clausola sul registro.
#
# MISURATO col giudizio testa a testa fra le due varianti dello STESSO motore
# (mt_eval/gemba_ftg_vs_ftgr.jsonl, 400 blocchi di Deadpool 2), che è l'unico
# confronto valido: le due rese finiscono nella stessa chiamata al giudice.
#
#                          nativo   con regole   preferenza
#   blocchi volgari (36)     5,97      3,89       25% / 69%
#   blocchi normali (364)    2,23      2,12       27% / 31%
#   totale (400)             2,57      2,28       27% / 35%
#
# ATTENZIONE ALLA TRAPPOLA: confrontando invece DUE RUN SEPARATE contro NLLB il
# risultato sembrava opposto (le regole apparivano dannose sui blocchi normali).
# Era un artefatto: fra una run e l'altra la calibrazione del giudice slitta —
# NLLB stesso, sugli stessi identici segmenti, è passato da 2,15 a 1,84. I
# punteggi assoluti di run diverse NON si confrontano; solo i confronti interni
# a una run valgono.
#
# La clausola sul registro resta comunque condizionata, ma per un'altra ragione:
# su una battuta senza parolacce non ha niente da fare, e toglierla accorcia il
# preambolo — meno testo che il modello possa tradurre invece di applicare. Il
# guadagno sui blocchi normali veniva dalla parte sulla lunghezza, che ora è
# MT_BUDGET_RULE e si applica sempre.
MT_PREFIX_TRIGGER = re.compile(
    r"\b(fuck\w*|shit\w*|bullshit|asshole|bitch\w*|cunt|dick|prick|"
    r"motherfuck\w*|goddamn|bastard|cock|pussy|balls|piss\w*|whore|slut|"
    r"douche\w*|jackass|dumbass|screw you|son of a bitch)\b", re.I)

# Il budget di caratteri della battuta, detto al modello come NUMERO.
#
# Il giudizio su un film senza turpiloquio (A Man Called Otto) isola quello che
# resta a TranslateGemma dopo il turpiloquio: capisce quanto NLLB e sbaglia
# meno gravemente (7 errori critici contro 11), ma perde su `style` di 13 punti
# su 100 segmenti. Scrive battute troppo lunghe, e basta.
#
# MISURATO (mt_eval/probe_tg_budget.py) su 60 blocchi stretti, cioè quelli in
# cui l'inglese già affolla lo spazio disponibile:
#
#                          caratteri   x EN   >42 car   oltre budget
#   professionista             43,9    0,83       0%         27%
#   nessuna regola             59,0    1,11      65%         67%
#   regola generica            54,5    1,03      55%         57%
#   budget esplicito           51,6    0,97      52%         53%
#
# Un aggettivo ("più breve") sposta poco; un numero sposta il triplo, e porta
# il rapporto sotto 1,0 per la prima volta. La regola è anche AUTOLIMITANTE: su
# una battuta che nel budget ci sta già, un tetto non chiede di tagliare
# niente, mentre "più breve dell'originale" lo chiede sempre.
MT_BUDGET_RULE = ("Rendi come sottotitolo italiano in non più di {budget} "
                  "caratteri, tagliando i riempitivi.")

# I due modelli Aya sono stati RIMOSSI il 2026-08-18. Non è una preferenza:
# hanno perso entrambi i confronti su film reale (Deadpool 2 MQM 2,85 contro
# 2,06 di NLLB, A Man Called Otto 2,38 contro 1,66) e soprattutto il loro
# percorso "adapt" — un solo prompt con dentro tutti i blocchi, identificati
# per id — può DISALLINEARE battute e tempi: su blocchi consecutivi il modello
# fonde due sottotitoli la cui frase prosegue e poi scrive le rese successive
# sotto gli id sbagliati. Il percorso "mt" di TranslateGemma è immune per
# costruzione (una conversazione per battuta, nessun id da sbagliare).
# Dettagli in memory/pipeline_path_defects_2026_08.md.
MODEL_SPECS: Dict[str, ModelSpec] = {
    "hunyuan-mt-7b": ModelSpec(
        model_id="tencent/Hunyuan-MT-7B",
        label="Hunyuan-MT-7B",
        # Raccomandati dalla model card: il modello è RL-tunato su queste.
        generation=dict(do_sample=True, top_k=20, top_p=0.6, temperature=0.7,
                        repetition_penalty=1.05),
        prompt_style="mt",
        notes="Vincitore traccia constrained WMT25; miglior en-it sotto 20B.",
    ),
    "tower-plus-9b": ModelSpec(
        model_id="Unbabel/Tower-Plus-9B",
        label="Tower+ 9B",
        generation=dict(do_sample=False, num_beams=1),
        notes="Specializzato MT. Licenza CC-BY-NC.",
    ),
    "translategemma-12b": ModelSpec(
        model_id="google/translategemma-12b-it",
        label="TranslateGemma 12B",
        generation=dict(do_sample=False, num_beams=1),
        prompt_style="mt",
        mt_prefix=TRANSLATEGEMMA_SUBTITLE_RULES,
        mt_prefix_when=MT_PREFIX_TRIGGER,
        mt_budget_rule=MT_BUDGET_RULE,
        loader="gemma3",
        gated=True,
        context_window=131072,
        # MISURATO (mt_eval/vram_probe.py, scheda da 12.288 MiB). I soli pesi
        # in NF4 occupano 8.401 MiB: restano meno di 4 GB per tutto il resto.
        # Picco di una singola generate() sui 48 blocchi più lunghi del film,
        # e tempo per blocco:
        #   batch  4 ->  8.877 MiB (72%)  8,88 s/blocco
        #   batch  8 ->  9.449 MiB (77%)  4,54 s/blocco
        #   batch 12 -> 10.133 MiB (82%)  3,20 s/blocco   <- scelto
        #   batch 16 -> 10.817 MiB (88%)  2,54 s/blocco
        # Su questo percorso ("mt", una conversazione per battuta in parallelo)
        # il batch conta davvero: da 4 a 16 il tempo per blocco scende di 3,5
        # volte. Dodici è il compromesso: 2 GB di margine sulla scheda e il 30%
        # di tempo in meno rispetto a otto. Oltre non si sale senza rimisurare
        # su una run intera — il gestore adattivo scende comunque da solo se la
        # memoria supera il 90%.
        max_batch=12,
        notes="Addestrato con RL contro la letteralità (MetricX-QE, AutoMQM). "
              "La variante 4B era stata bocciata a luglio; il 12B è la taglia "
              "che nei benchmark supera il baseline Gemma 3 27B.",
    ),
}

DEFAULT_MODEL_KEY = "translategemma-12b"


# --------------------------------------------------------------------------
# Singleton di processo: il modello resta caricato tra un file e l'altro della
# coda, come già fa il ramo NLLB.
# --------------------------------------------------------------------------
_engine_lock = Lock()
_engine: Optional["SubtitleLLMEngine"] = None


def get_engine(model_key: str = DEFAULT_MODEL_KEY,
               log_callback: Optional[Callable] = None) -> "SubtitleLLMEngine":
    """Restituisce il motore per `model_key`, caricandolo se serve.

    Cambiare modello scarica il precedente: due 8B non stanno in 12 GB.
    """
    global _engine
    with _engine_lock:
        if _engine is not None and _engine.model_key != model_key:
            _engine.unload()
            _engine = None
        if _engine is None:
            _engine = SubtitleLLMEngine(model_key, log_callback)
        elif log_callback:
            _engine.log_callback = log_callback
        _engine.load()
        return _engine


def unload_engine() -> None:
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.unload()
            _engine = None


def _free_vram_gb() -> float:
    try:
        import torch
        if torch.cuda.is_available():
            free_b, _ = torch.cuda.mem_get_info()
            return free_b / 1024 ** 3
    except Exception:
        pass
    return 0.0


class SubtitleLLMEngine:
    """Carica un LLM open-weight e genera completamenti da messaggi chat."""

    def __init__(self, model_key: str = DEFAULT_MODEL_KEY,
                 log_callback: Optional[Callable] = None):
        if model_key not in MODEL_SPECS:
            raise ValueError(
                f"Modello '{model_key}' sconosciuto. "
                f"Disponibili: {', '.join(MODEL_SPECS)}"
            )
        self.model_key = model_key
        self.spec = MODEL_SPECS[model_key]
        self.log_callback = log_callback
        self.model = None
        self.tokenizer = None
        self.processor = None      # solo per i modelli con loader "gemma3"
        self.device = None
        self._quantized = False

    # -- logging ----------------------------------------------------------
    def log(self, message: str) -> None:
        logger.info(message)
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass

    # -- caricamento ------------------------------------------------------
    def load(self) -> None:
        if self.model is not None:
            return

        import torch
        from transformers import AutoTokenizer

        use_gpu = torch.cuda.is_available()
        self.device = torch.device("cuda" if use_gpu else "cpu")

        # Il token si passa sempre: sui repo pubblici è innocuo, e capire quali
        # siano gated non è affidabile — TranslateGemma lo è, e senza token il
        # processor tenta comunque una richiesta anonima all'hub per il chat
        # template e riceve un 401.
        token = self._hf_token()
        is_gemma3 = self.spec.loader == "gemma3"

        self.log(f"📦 Caricamento modello {self.spec.label}...")

        if is_gemma3:
            # Il chat template di TranslateGemma sta nel processor, non nel
            # tokenizer: caricare solo quest'ultimo darebbe chat_template=None.
            from transformers import AutoProcessor
            self.processor = AutoProcessor.from_pretrained(
                self.spec.model_id, token=token,
            )
            self.tokenizer = getattr(self.processor, "tokenizer", None)
        else:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.spec.model_id, trust_remote_code=True, token=token,
            )

        if self.tokenizer is not None:
            # CRITICO: con padding a destra e batch > 1 la generazione parte
            # dopo il padding e lo slice dei token nuovi restituisce spazzatura.
            self.tokenizer.padding_side = "left"
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

        if not is_gemma3 and self.tokenizer.chat_template is None:
            raise RuntimeError(
                f"{self.spec.label} non espone un chat template: "
                f"il motore lo richiede per costruire i prompt."
            )

        free_gb = _free_vram_gb()
        kwargs: Dict[str, Any] = dict(
            trust_remote_code=True, low_cpu_mem_usage=True, token=token,
        )

        if not use_gpu:
            self.log("  GPU non disponibile: caricamento su CPU (lento)")
        elif free_gb >= self.spec.bf16_min_free_gb:
            self.log(f"  VRAM libera {free_gb:.1f} GB -> bfloat16")
            kwargs.update(dtype=torch.bfloat16, device_map="auto")
        else:
            self.log(f"  VRAM libera {free_gb:.1f} GB -> NF4")
            from transformers import BitsAndBytesConfig
            kwargs.update(
                # `dtype` NON è ridondante con `bnb_4bit_compute_dtype`, ed è
                # il parametro decisivo: senza, bitsandbytes FORZA float16 su
                # tutto il modello, sovrascrivendo il bfloat16 dichiarato nel
                # config (transformers, quantizer_bnb_4bit.py: "We force the
                # dtype to be float16"). `bnb_4bit_compute_dtype` copre solo i
                # layer quantizzati; norm, embedding e testa di output restano
                # in float16.
                #
                # Per Gemma3 è fatale: l'output degli embedding è scalato per
                # sqrt(hidden_size) — 3840 sul 12B — e supera il massimo di
                # float16 (65504). Le attivazioni vanno a infinito, i logit
                # diventano NaN, argmax su NaN restituisce l'indice 0 che è
                # <pad>: il modello genera solo padding senza sollevare alcun
                # errore. Vedi transformers#36822.
                dtype=torch.bfloat16,
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                ),
                device_map="auto",
            )
            self._quantized = True

        if is_gemma3:
            from transformers import AutoModelForImageTextToText
            self.model = AutoModelForImageTextToText.from_pretrained(
                self.spec.model_id, **kwargs
            )
        else:
            from transformers import AutoModelForCausalLM
            self.model = AutoModelForCausalLM.from_pretrained(
                self.spec.model_id, **kwargs
            )
        if not use_gpu:
            self.model.to(self.device)
        self.model.eval()

        if self.model.config.pad_token_id is None:
            self.model.config.pad_token_id = self.tokenizer.pad_token_id

        self.log(f"  {self.spec.label} pronto su {self.device}")

    def _hf_token(self) -> Optional[str]:
        try:
            from utils.config import get_config
            return get_config().get_huggingface_token() or None
        except Exception as exc:
            logger.warning(f"Token HuggingFace non recuperato: {exc}")
            return None

    # -- prompt di traduzione ---------------------------------------------
    def mt_messages(self, text: str, src_lang: str = "en",
                    tgt_lang: str = "it",
                    budget: int = 0) -> List[Dict[str, Any]]:
        """Il prompt di traduzione nativo di QUESTO modello.

        Vive qui e non in `prompt_builder` perché è una caratteristica dei
        pesi, non dello stile che vogliamo ottenere: TranslateGemma vuole un
        `content` strutturato con i codici lingua, gli altri una frase in
        linguaggio naturale. Il resto della pipeline non deve saperlo.

        Se il modello dichiara un `mt_prefix`, le regole del sottotitolo
        entrano qui — dentro il testo — perché è l'unico varco che il suo chat
        template lascia aperto.
        """
        # Una riga sola, composta: due istruzioni su due righe allungano il
        # preambolo e aumentano la probabilità che il modello le traduca
        # invece di applicarle.
        regole: List[str] = []
        if self.spec.mt_budget_rule and budget > 0:
            regole.append(self.spec.mt_budget_rule.format(budget=budget))
        if self.spec.mt_prefix and (
                self.spec.mt_prefix_when is None
                or self.spec.mt_prefix_when.search(text)):
            regole.append(self.spec.mt_prefix)
        if regole:
            regole.append("Traduci solo la battuta:")
            text = " ".join(regole) + "\n" + text

        if self.spec.loader == "gemma3":
            return [{
                "role": "user",
                "content": [{
                    "type": "text",
                    "source_lang_code": src_lang,
                    "target_lang_code": tgt_lang,
                    "text": text,
                }],
            }]

        target = {"it": "Italian", "en": "English"}.get(tgt_lang, tgt_lang)
        return [{
            "role": "user",
            "content": (
                f"Translate the following segment into {target}, "
                f"without additional explanation.\n\n{text}"
            ),
        }]

    # -- generazione ------------------------------------------------------
    def generate(self, conversations: List[List[Dict[str, str]]],
                 max_new_tokens: int = 512,
                 **overrides: Any) -> List[str]:
        """Genera una risposta per ogni conversazione.

        `conversations` è una lista di liste di messaggi in formato chat
        ({"role": "system"|"user"|"assistant", "content": str}). Restituisce
        il solo testo generato, nell'ordine di input.
        """
        if self.model is None:
            self.load()

        import torch

        if self.processor is not None:
            # Percorso Gemma3: il template vive nel processor e i messaggi
            # portano un `content` strutturato, quindi la tokenizzazione va
            # fatta in un colpo solo invece che in due passaggi.
            inputs = self.processor.apply_chat_template(
                conversations,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
                padding=True,
            ).to(self.model.device)
        else:
            prompts = [
                self.tokenizer.apply_chat_template(
                    conv, tokenize=False, add_generation_prompt=True
                )
                for conv in conversations
            ]
            # add_special_tokens=False: il chat template ha già messo il BOS.
            inputs = self.tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self.spec.context_window - max_new_tokens,
                add_special_tokens=False,
            ).to(self.model.device)

        # Alcuni tokenizer (Hunyuan-MT fra questi) restituiscono anche
        # `token_type_ids`, che i modelli decoder-only non accettano: passarlo
        # a generate() solleva "model_kwargs are not used by the model" e fa
        # fallire l'intero batch.
        #
        # Per Gemma3 vale l'opposto: lì `token_type_ids` distingue i token di
        # testo da quelli immagine ed è parte dell'input atteso. Filtrarlo non
        # dà errore — il modello genera silenziosamente solo token di padding.
        if self.spec.loader != "gemma3":
            inputs = {k: v for k, v in inputs.items()
                      if k in ("input_ids", "attention_mask")}
        else:
            inputs = dict(inputs)

        gen_kwargs: Dict[str, Any] = dict(self.spec.generation)
        gen_kwargs.update(overrides)
        gen_kwargs.update(
            max_new_tokens=max_new_tokens,
            pad_token_id=self.tokenizer.pad_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
        )

        with torch.no_grad():
            outputs = self.model.generate(**inputs, **gen_kwargs)

        # Con padding a sinistra tutti i prompt finiscono allo stesso indice,
        # quindi questo slice è corretto per ogni riga del batch.
        new_tokens = outputs[:, inputs["input_ids"].shape[1]:]
        return [
            text.strip()
            for text in self.tokenizer.batch_decode(
                new_tokens, skip_special_tokens=True
            )
        ]

    # -- scarico ----------------------------------------------------------
    def unload(self) -> None:
        """Libera la VRAM. Senza `remove_hook_from_module` gli hook di
        accelerate trattengono i tensori e il modello resta in memoria anche
        dopo il `del` — è il difetto che il ramo LLM storico aveva rispetto a
        quello NLLB."""
        if self.model is None and self.tokenizer is None:
            return

        self.log(f"  Scarico {self.spec.label} dalla VRAM...")
        try:
            import torch
            if self.model is not None:
                try:
                    from accelerate.hooks import remove_hook_from_module
                    remove_hook_from_module(self.model, recurse=True)
                except Exception as exc:
                    logger.debug(f"remove_hook_from_module: {exc}")
                if not self._quantized:
                    # I moduli quantizzati bitsandbytes non tornano su CPU.
                    try:
                        self.model.to("cpu")
                    except Exception as exc:
                        logger.debug(f"model.to(cpu): {exc}")

            self.model = None
            self.tokenizer = None
            gc.collect()

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                try:
                    torch._C._cuda_clearCublasWorkspaces()
                except Exception:
                    pass
                torch.cuda.empty_cache()
        except Exception as exc:
            logger.warning(f"Errore durante l'unload: {exc}")
        finally:
            self.model = None
            self.tokenizer = None
            self._quantized = False
