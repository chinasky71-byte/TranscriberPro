# -*- coding: utf-8 -*-
"""
Fallback Translate CLI - Serbatoio di traduzione (L3), entrypoint subprocess isolato
File: core/fallback_translate_cli.py

Ultimo livello di ripiego della traduzione sottotitoli (vedi core/translator.py,
BaseTranslator._reservoir_translate): traduce con un LLM chat-tuned (Qwen, via
llama-cpp-python) le poche righe che sopravvivono a unmask tollerante e a un
retry senza mascheramento sul motore primario (NLLB o TranslateGemma).

Gira in un processo separato per lo stesso motivo del gender corrector
(core/gender_corrector_cli.py): llama-cpp-python alloca la VRAM fuori
dall'allocatore PyTorch usato da transformers/bitsandbytes — su 12 GB i due
non convivono in modo affidabile in-process, e il subprocess muore
restituendo tutta la VRAM all'OS per costruzione, senza bisogno di sapere se
lo scarico del modello primario ha lasciato residui.

Traduce UNA riga per chiamata (mai un batch numerato): il volume qui è
sempre piccolo (poche decine di righe nel caso peggiore osservato), e un
batch in un unico prompt rischia il disallineamento id/testo che ha già
motivato la rimozione del percorso "adapt" altrove nel progetto (vedi
core/llm_subtitle_translator/prompt_builder.py). Una riga per chiamata è
immune per costruzione: non c'è nessun id da sbagliare.

Uso (chiamato da core/translator.py, non manuale):
    python -m core.fallback_translate_cli <args.json>

Formato args.json:
    {
      "lines": [{"id": "<chiave>", "text": "riga inglese"}, ...],
      "glossary": {"termine": "resa italiana", ...},   # può essere {}
      "output_json": "path/al/risultato.json",
      "model_path": "path/al/modello.gguf"
    }

Formato output.json:
    {"translations": {"<chiave>": "riga italiana", ...}}
    Una chiave assente = quella riga non è stata risolta (il chiamante
    decide cosa fare: L4, inglese ma con log visibile).

Exit code:
    0 = terminato (anche con traduzioni parziali/mancanti — vedi output.json)
    1 = errore fatale (modello non caricabile, eccezione non gestita)
    2 = argomenti CLI invalidi

Stdout: log leggibili dall'utente, riemessi dal parent via self.log.
"""
import json
import re
import sys
import traceback
from pathlib import Path


def _emit(msg: str) -> None:
    """Stampa una riga su stdout con flush immediato (line-buffered)."""
    print(msg, flush=True)


_LEADING_LABEL = re.compile(
    r'^\s*(?:ITALIANO|IT|TRADUZIONE|TRANSLATION)\s*[:\-]\s*', re.IGNORECASE)
_WRAPPING_QUOTES = re.compile(r'^["\'«»](.*)["\'«»]$', re.DOTALL)


def _clean_output(text: str) -> str:
    """Ripulisce l'output del modello da label/virgolette che un chat model
    aggiunge nonostante l'istruzione di non farlo — non è un fallimento di
    traduzione, è formattazione da togliere."""
    out = text.strip()
    # Un chat model a volte risponde su più righe (spiegazioni non richieste):
    # si tiene solo la prima riga non vuota, è quasi sempre la traduzione.
    #
    # È sicuro SOLO perché la riga sorgente viaggia appiattita su una riga
    # sola (vedi `_flatten` in main): con un input a due righe — la forma
    # più comune di una battuta di sottotitolo — il modello risponde su due
    # righe e questo taglio ne buttava metà. Il risultato non era né vuoto né
    # identico al sorgente, quindi superava ogni controllo del chiamante e
    # finiva a schermo dimezzato: una perdita di contenuto silenziosa, il
    # difetto esatto che questo modulo esiste per impedire.
    for line in out.split('\n'):
        line = line.strip()
        if line:
            out = line
            break
    out = _LEADING_LABEL.sub('', out).strip()
    m = _WRAPPING_QUOTES.match(out)
    if m:
        out = m.group(1).strip()
    return out


def _flatten(text: str) -> str:
    """Una battuta di sottotitolo su due righe diventa una riga sola."""
    return re.sub(r'\s*\n\s*', ' ', text).strip()


def _build_messages(text: str, glossary_hint: str) -> list:
    system = (
        "Sei un traduttore professionista inglese-italiano per sottotitoli. "
        "Traduci SOLO la frase data, senza spiegazioni, note o virgolette. "
        "Rispondi con una sola riga: la traduzione italiana e basta."
    )
    if glossary_hint:
        system += f" {glossary_hint}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


def _glossary_hint(text: str, glossary: dict) -> str:
    """Solo i termini di glossario presenti in QUESTA riga — un'istruzione
    corta e mirata è più affidabile di un elenco lungo per lo più
    irrilevante. Funziona perché Qwen è chat-tuned e segue istruzioni in
    linguaggio naturale — a differenza di NLLB (encoder-decoder puro,
    misurato: un'istruzione in prompt viene TRADOTTA, non eseguita — vedi
    core/translator.py, _run_translation), qui l'istruzione è eseguibile."""
    low = text.lower()
    rules = [(t, r) for t, r in glossary.items() if t.lower() in low]
    if not rules:
        return ""
    parts = []
    for term, rendering in rules:
        if term.lower() == rendering.lower():
            parts.append(f'lascia "{term}" invariato')
        else:
            parts.append(f'rendi sempre "{term}" con "{rendering}"')
    return "Regole di glossario: " + "; ".join(parts) + "."


_WORD_RE = re.compile(r'[A-Za-zÀ-ÿ]+')


def _is_degenerate_or_english(candidate: str, source: str) -> bool:
    """Stesso segnale forte usato dall'audit del chiamante (identità
    normalizzata), più un controllo di vuoto: basta per decidere se vale la
    pena di un secondo tentativo, la validazione fine la fa il chiamante.

    Le due soglie replicano `BaseTranslator._is_untranslated` (≥5 caratteri
    normalizzati E ≥2 parole): con la vecchia soglia unica di 12 caratteri
    questo controllo non scattava proprio sulle frasi corte che hanno
    motivato il serbatoio ("Oh, God." normalizza a 5 caratteri), quindi il
    secondo tentativo non partiva mai dove serviva di più.
    """
    if not candidate:
        return True
    norm = lambda s: re.sub(r'[^0-9a-zàèéìòóù]', '', s.lower())
    src_norm = norm(source)
    if len(src_norm) < 5 or len(_WORD_RE.findall(source)) < 2:
        return False
    return norm(candidate) == src_norm


def main(argv: list) -> int:
    if len(argv) < 2:
        _emit("ERRORE CLI: argomento args.json mancante")
        return 2

    args_path = Path(argv[1])
    if not args_path.exists():
        _emit(f"ERRORE CLI: args.json non trovato: {args_path}")
        return 2

    try:
        args = json.loads(args_path.read_text(encoding='utf-8'))
    except Exception as e:
        _emit(f"ERRORE CLI: parsing args.json fallito: {e}")
        return 2

    lines = args.get('lines') or []
    glossary = args.get('glossary') or {}
    output_json = args.get('output_json')
    model_path = args.get('model_path')

    if not lines or not output_json or not model_path:
        _emit("ERRORE CLI: 'lines', 'output_json' e 'model_path' sono obbligatori")
        return 2

    if not Path(model_path).exists():
        _emit(f"ERRORE CLI: modello non trovato: {model_path}")
        return 1

    try:
        from utils.cuda_dll_path import ensure_torch_lib_on_path
        ensure_torch_lib_on_path()
    except Exception:
        pass
    try:
        from llama_cpp import Llama
    except Exception as e:
        _emit(f"ERRORE CLI: import llama_cpp fallito: {e}")
        traceback.print_exc(file=sys.stderr)
        return 1

    try:
        _emit(f"📦 Caricamento modello di ripiego ({Path(model_path).name})...")
        model = Llama(model_path=model_path, n_gpu_layers=-1, n_ctx=4096,
                     n_batch=512, verbose=False)
    except Exception as e:
        _emit(f"ERRORE CLI: caricamento modello fallito: {e}")
        traceback.print_exc(file=sys.stderr)
        return 1

    translations = {}
    total = len(lines)
    _emit(f"🌐 Traduzione di {total} frasi distinte...")

    try:
        for i, item in enumerate(lines, 1):
            key = str(item.get('id'))
            raw_text = (item.get('text') or '').strip()
            if not raw_text:
                continue
            # Una riga in, una riga out: appiattire l'a capo del sottotitolo
            # rende vero il contratto che il system prompt dichiara e che
            # `_clean_output` assume. Il chiamante confronta per identità
            # normalizzata, che ignora gli a capo, quindi l'appiattimento non
            # altera nessun controllo a valle; il ri-avvolgimento tipografico
            # lo fa il post-processing come per ogni altra battuta.
            text = _flatten(raw_text)

            hint = _glossary_hint(text, glossary)
            best = ""
            for attempt in range(2):
                messages = _build_messages(text, hint)
                try:
                    resp = model.create_chat_completion(
                        messages=messages, temperature=0.2 if attempt == 0 else 0.5,
                        top_p=0.9, max_tokens=200)
                    candidate = _clean_output(
                        resp['choices'][0]['message']['content'])
                except Exception as e:
                    _emit(f"   riga {key}: errore generazione ({e})")
                    candidate = ""
                if candidate and not _is_degenerate_or_english(candidate, text):
                    best = candidate
                    break
                best = ""
            # Non si consegna un candidato che sappiamo già inservibile
            # (vuoto o indistinguibile dall'inglese): la chiave assente dice
            # al chiamante "non risolto", che ripiega su L4 — inglese, ma con
            # log visibile. Restituirlo invece lo avrebbe fatto passare per
            # una traduzione riuscita.
            if best:
                translations[key] = best

            if i % 5 == 0 or i == total:
                _emit(f"   {i}/{total}")

    finally:
        try:
            del model
        except Exception:
            pass
        import gc
        gc.collect()

    try:
        Path(output_json).write_text(
            json.dumps({"translations": translations}, ensure_ascii=False),
            encoding='utf-8')
    except Exception as e:
        _emit(f"ERRORE CLI: scrittura output_json fallita: {e}")
        return 1

    _emit(f"✅ Serbatoio completato: {len(translations)}/{total} frasi risolte")
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    try:
        from core.pipeline_cli import _suppress_subprocess_windows
        _suppress_subprocess_windows()
    except Exception:
        pass

    sys.exit(main(sys.argv))
