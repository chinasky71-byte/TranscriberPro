"""
Professional Subtitle Formatter
File: core/subtitle_formatter.py

Formatta segmenti diarizzati + allineati in SRT di qualità broadcast/cinema.

Regole implementate:
1. Trattino stile Netflix (STRETTO):
     - Trattino SOLO quando due parlanti condividono lo stesso blocco SRT
       (una battuta per riga, entrambe con "- ")
     - Blocchi con un solo parlante → MAI trattino, anche in contesto dialogo
2. Raggruppamento dialogo:
     - 2 speaker consecutivi con gap ≤ GAP_GROUP s e testo ≤ CPL_MAX
       → singolo blocco SRT con 2 righe e trattino su entrambe
3. CPL (Characters Per Line):
     - Max CPL_MAX caratteri per riga
     - Testi lunghi spezzati al confine di parola più vicino alla metà
     - Solo la prima riga del turno riceve il trattino (le continuazioni no)
4. Durata minima (anti-flash):
     - Nessun blocco dura meno di MIN_DURATION secondi
     - L'end viene espanso senza toccare il blocco successivo (gap minimo 50ms)
5. Cleanup:
     - Tag HTML, spazi multipli, trattini preesistenti rimossi prima
       del reformatting
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import List, Dict, Optional, Callable


CPL_MAX       = 42    # Characters Per Line massimo
MIN_DURATION  = 1.0   # Durata minima blocco (s) — anti-flash
GAP_GROUP     = 1.0   # Gap max (s) per raggruppare 2 speaker in un blocco
DIALOGUE_WIN  = 4.0   # Finestra (s) per rilevare contesto dialogo
MERGE_GAP     = 0.3   # Gap max (s) per unire frammenti della stessa frase (stesso speaker)
MERGE_GAP_TINY = 0.05  # Gap max (s) per unire ignorando lo speaker (artefatto aligner)

# Gate di confidenza per il trattino a due voci (v. piano_fix_pipeline_trascrizione):
# la diarization su film con crosstalk/interiezioni brevi produce spesso
# attribuzioni deboli — meglio un blocco singolo senza trattino che un
# trattino con la battuta sulla riga del personaggio sbagliato.
DASH_CONFIDENCE_MIN = 0.55  # confidenza minima speaker richiesta su ENTRAMBI i segmenti
DASH_MIN_GAP        = 0.20  # gap minimo (s) accettato senza punteggiatura forte a fine riga


class SubtitleFormatter:
    """Formatta segmenti diarizzati in SRT professionale."""

    def __init__(
        self,
        cpl_max: int = CPL_MAX,
        min_duration: float = MIN_DURATION,
        gap_group: float = GAP_GROUP,
        dialogue_window: float = DIALOGUE_WIN,
        dash_confidence_min: float = DASH_CONFIDENCE_MIN,
        dash_min_gap: float = DASH_MIN_GAP,
        log_callback: Optional[Callable] = None,
    ):
        self.cpl_max             = cpl_max
        self.min_duration        = min_duration
        self.gap_group           = gap_group
        self.dialogue_window     = dialogue_window
        self.dash_confidence_min = dash_confidence_min
        self.dash_min_gap        = dash_min_gap
        self.log = log_callback or (lambda _: None)
        self._dash_rejected_low_confidence = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def format_srt(self, segments: List[Dict]) -> str:
        """Converte segmenti in stringa SRT professionale."""
        if not segments:
            return ""

        segs = self._clean(segments)
        if not segs:
            return ""

        segs = self._dedup_overlapping(segs)
        segs = self._merge_short_segments(segs)

        if not any(s.get('speaker') for s in segs):
            # Nessuna diarization: CPL + durata minima, nessun trattino
            blocks = self._segments_to_blocks(segs)
            blocks = self._fix_overlaps(blocks)
            blocks = self._enforce_min_duration(blocks)
            blocks = self._drop_invalid_blocks(blocks)
            return self._render(blocks)

        self._mark_dialogue(segs)
        blocks = self._build_blocks(segs)
        blocks = self._fix_overlaps(blocks)
        blocks = self._enforce_min_duration(blocks)
        blocks = self._drop_invalid_blocks(blocks)
        srt = self._render(blocks)
        self.log(f"  📄 SRT formattato: {len(blocks)} blocchi, "
                 f"{sum(1 for b in blocks if len(b['lines']) > 1)} blocchi dialogo")
        if self._dash_rejected_low_confidence:
            self.log(f"  🎭 Coppie speaker scartate per bassa confidenza "
                      f"(niente trattino): {self._dash_rejected_low_confidence}")
        return srt

    def save(self, segments: List[Dict], output_path) -> bool:
        """Formatta e salva il file SRT su disco."""
        try:
            srt = self.format_srt(segments)
            Path(output_path).write_text(srt, encoding='utf-8')
            return True
        except Exception as e:
            self.log(f"  ⚠️ Errore salvataggio SRT formattato: {e}")
            return False

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _clean(self, segments: List[Dict]) -> List[Dict]:
        result = []
        for seg in segments:
            s = dict(seg)
            s['text'] = self._clean_text(s.get('text', ''))
            if s['text']:
                result.append(s)
        return result

    def _clean_text(self, text: str) -> str:
        text = re.sub(r'<[^>]+>', '', text)    # tag HTML
        text = re.sub(r'^-\s+', '', text)      # trattino iniziale preesistente
        text = re.sub(r'\s+', ' ', text)        # spazi multipli
        return text.strip()

    _SENTENCE_END = re.compile(r'[.?!…]$')
    _WORD_RE = re.compile(r'\w+', re.UNICODE)

    def _normalize_for_dedup(self, text: str) -> List[str]:
        return self._WORD_RE.findall(text.lower())

    @staticmethod
    def _same_or_contained(a: List[str], b: List[str]) -> bool:
        """True se i due testi normalizzati coincidono, o se il più corto è
        una sequenza CONTIGUA di parole del più lungo.

        Il confronto è per parole, non per sottostringa: "sì" è sottostringa
        di "così" e "no" di "nonno" — un confronto testuale grezzo scartava
        battute buone. Il caso asimmetrico (uno contenuto nell'altro) è
        ammesso solo da 2 parole in su: una parola sola dentro una frase più
        lunga non è prova di duplicazione ("sì" dentro "ma sì certo").
        """
        if not a or not b:
            return False
        if a == b:
            return True
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        if len(short) < 2:
            return False
        n = len(short)
        return any(long_[i:i + n] == short for i in range(len(long_) - n + 1))

    def _dedup_overlapping(self, segs: List[Dict]) -> List[Dict]:
        """Rimuove segmenti quasi-duplicati con overlap temporale.

        Chunk audio fisicamente sovrapposti (bug storico nel chunker, vedi
        core/audio_processor.py) fanno trascrivere la stessa battuta due
        volte con timestamp leggermente diversi e fuori ordine. Ordina per
        start (ripristina l'ordine cronologico) e scarta il duplicato
        quando due segmenti si sovrappongono nel tempo E il testo
        normalizzato coincide o è contenuto l'uno nell'altro (v.
        _same_or_contained) — la sola somiglianza testuale non basta (due
        speaker possono dire la stessa battuta breve, es. "Sì."), serve
        anche l'overlap temporale.
        """
        if len(segs) < 2:
            return segs

        ordered = sorted(segs, key=lambda s: s['start'])
        result: List[Dict] = [ordered[0]]
        removed = 0
        for seg in ordered[1:]:
            prev = result[-1]
            overlap = min(prev['end'], seg['end']) - max(prev['start'], seg['start'])
            if overlap > 0:
                norm_prev = self._normalize_for_dedup(prev.get('text', ''))
                norm_seg  = self._normalize_for_dedup(seg.get('text', ''))
                if self._same_or_contained(norm_prev, norm_seg):
                    # Tieni il testo più lungo (di solito quello meglio
                    # punteggiato/con più contesto per l'aligner)
                    if len(seg.get('text', '')) > len(prev.get('text', '')):
                        result[-1] = seg
                    removed += 1
                    continue
            result.append(seg)

        if removed:
            self.log(f"  🧹 Segmenti duplicati (chunk sovrapposti) rimossi: {removed}")
        return result

    def _drop_invalid_blocks(self, blocks: List[Dict]) -> List[Dict]:
        """Scarta blocchi con timing invalido (end <= start) e garantisce
        l'ordine cronologico nel file finale, qualunque euristica a monte
        li abbia prodotti."""
        ordered = sorted(blocks, key=lambda b: b['start'])
        result = []
        dropped = 0
        for b in ordered:
            if b['end'] <= b['start']:
                dropped += 1
                continue
            result.append(b)
        if dropped:
            self.log(f"  🛡️ Blocchi con timing invalido scartati: {dropped}")
        return result

    def _merge_short_segments(self, segs: List[Dict]) -> List[Dict]:
        """Unisce segmenti consecutivi che formano la stessa frase.

        Il forced aligner e Whisper spesso spezzano frasi in più segmenti
        ravvicinati (es. "È stato colpito" | 20ms | "la testa.").
        Questo passo li riunisce prima della formattazione.

        Condizioni per il merge:
          - gap ≤ MERGE_GAP (300ms)
          - il primo segmento NON termina con punteggiatura finale (.?!…)
          - testo combinato ≤ cpl_max * 2 (84 caratteri = 2 righe piene)
          - stesso speaker (o nessuno dei due ha speaker)
        """
        if not segs:
            return segs

        result = [dict(segs[0])]
        for seg in segs[1:]:
            prev     = result[-1]
            gap      = seg['start'] - prev['end']
            prev_txt = prev.get('text', '').strip()
            combined = (prev_txt + ' ' + seg.get('text', '').strip()).strip()

            # Gap ≤ MERGE_GAP_TINY: artefatto aligner, impossibile cambio reale
            # di speaker in 50ms — ignoriamo il controllo speaker.
            # Gap ≤ MERGE_GAP: merge solo se stesso speaker.
            speaker_ok = (
                gap <= MERGE_GAP_TINY
                or prev.get('speaker') == seg.get('speaker')
            )
            can_merge = (
                0 <= gap <= MERGE_GAP
                and speaker_ok
                and prev_txt
                and not self._SENTENCE_END.search(prev_txt)
                and len(combined) <= self.cpl_max * 2
            )

            if can_merge:
                result[-1] = dict(prev)
                result[-1]['end']  = seg['end']
                result[-1]['text'] = combined
                if 'words' in prev or 'words' in seg:
                    result[-1]['words'] = (
                        prev.get('words', []) + seg.get('words', [])
                    )
            else:
                result.append(dict(seg))

        merged = len(segs) - len(result)
        if merged:
            self.log(f"  🔗 Merge frammenti: {len(segs)} → {len(result)} segmenti ({merged} uniti)")
        return result

    # ── Dialogue detection ────────────────────────────────────────────────────

    def _mark_dialogue(self, segs: List[Dict]) -> None:
        """Marca ogni segmento come dialogo (True) o monologo (False).

        Un segmento è in contesto dialogo se esiste almeno un altro
        segmento con speaker diverso la cui finestra temporale si sovrappone
        a [seg.start - dialogue_window, seg.end + dialogue_window].
        """
        for i, seg in enumerate(segs):
            spk = seg.get('speaker')
            if not spk:
                seg['_dialogue'] = False
                continue

            t0, t1 = seg['start'], seg['end']
            in_dialogue = any(
                j != i
                and other.get('speaker')
                and other['speaker'] != spk
                and other['start'] < t1 + self.dialogue_window
                and other['end']   > t0 - self.dialogue_window
                for j, other in enumerate(segs)
            )
            seg['_dialogue'] = in_dialogue

    # ── Block building ────────────────────────────────────────────────────────

    # Chiusura di frase, con l'eventuale virgoletta finale (dritta o
    # tipografica: l'ASR restituisce anche » e ”, non normalizzati qui)
    _STRONG_END = re.compile(r'[.?!…]["\'»”]?$')

    def _confident_dialogue_pair(self, seg: Dict, nxt: Dict) -> bool:
        """Decide se una coppia di segmenti (speaker diversi, già ammessa dai
        controlli di gap/lunghezza) merita davvero il trattino a due voci.

        Due condizioni aggiuntive, entrambe necessarie:
          1. Confidenza minima sull'attribuzione speaker di ENTRAMBI i
             segmenti ('speaker_confidence', assente = 1.0 per
             retrocompatibilità con diarization che non la calcolano).
          2. Un confine di turno plausibile fra i due: o la prima riga
             termina con punteggiatura forte, o il gap è almeno
             dash_min_gap secondi — altrimenti è più probabile un errore
             di segmentazione a metà frase che un vero cambio di parlante.

        Se il gate rifiuta, i due segmenti restano blocchi singoli senza
        trattino: si perde la decorazione "stile dialogo", non si espone
        un'attribuzione sbagliata.
        """
        conf_a = seg.get('speaker_confidence', 1.0)
        conf_b = nxt.get('speaker_confidence', 1.0)
        if conf_a < self.dash_confidence_min or conf_b < self.dash_confidence_min:
            self._dash_rejected_low_confidence += 1
            return False

        gap = nxt['start'] - seg['end']
        if not self._STRONG_END.search(seg['text'].strip()) and gap < self.dash_min_gap:
            self._dash_rejected_low_confidence += 1
            return False

        return True

    def _build_blocks(self, segs: List[Dict]) -> List[Dict]:
        """Raggruppa segmenti in blocchi SRT con regole di raggruppamento dialogo.

        Regola raggruppamento: due segmenti A e B (speaker diversi) vengono
        uniti in un blocco doppio se:
          - Entrambi in contesto dialogo
          - gap(A.end, B.start) ≤ gap_group
          - len(A.text) ≤ cpl_max e len(B.text) ≤ cpl_max
        """
        blocks: List[Dict] = []
        i = 0
        while i < len(segs):
            seg  = segs[i]
            nxt  = segs[i + 1] if i + 1 < len(segs) else None

            if (nxt is not None
                    and seg.get('_dialogue')
                    and nxt.get('_dialogue')
                    and seg.get('speaker') != nxt.get('speaker')
                    and (nxt['start'] - seg['end']) <= self.gap_group
                    and len(seg['text']) <= self.cpl_max
                    and len(nxt['text']) <= self.cpl_max
                    and self._confident_dialogue_pair(seg, nxt)):

                # ── Blocco dialogo (2 righe) ──────────────────────────────────
                blocks.append({
                    'start': seg['start'],
                    'end':   max(seg['end'], nxt['end']),
                    'lines': [
                        {'text': seg['text'], 'dash': True},
                        {'text': nxt['text'], 'dash': True},
                    ],
                })
                i += 2

            else:
                # ── Blocco singolo (con eventuale wrap CPL) ───────────────────
                # Stile Netflix STRETTO: trattino solo nei blocchi dialogo a
                # 2 righe (ramo sopra) — i blocchi singoli non lo ricevono
                # mai, nemmeno in contesto dialogo.
                wrapped = self._wrap_cpl(seg['text'])
                lines   = [
                    {'text': t, 'dash': False}
                    for t in wrapped
                ]
                blocks.append({
                    'start': seg['start'],
                    'end':   seg['end'],
                    'lines': lines,
                })
                i += 1

        return blocks

    def _segments_to_blocks(self, segs: List[Dict]) -> List[Dict]:
        """Converti segmenti in blocchi senza diarization (solo CPL)."""
        return [
            {
                'start': s['start'],
                'end':   s['end'],
                'lines': [{'text': t, 'dash': False}
                          for t in self._wrap_cpl(s['text'])],
            }
            for s in segs
        ]

    def _wrap_cpl(self, text: str) -> List[str]:
        """Spezza il testo in righe di max cpl_max caratteri (a confine di parola).

        Divide vicino al punto centrale per bilanciare le righe.
        """
        if len(text) <= self.cpl_max:
            return [text]

        words = text.split()
        if len(words) == 1:
            return [text]  # parola singola troppo lunga: non spezzare

        # Cerca il punto di taglio più vicino alla metà del testo
        mid = len(text) // 2
        best_i, best_dist = 1, float('inf')
        acc = 0
        for i, w in enumerate(words[:-1]):
            acc += len(w) + (1 if i > 0 else 0)
            dist = abs(acc - mid)
            if dist < best_dist:
                best_dist, best_i = dist, i + 1

        line1 = ' '.join(words[:best_i])
        line2 = ' '.join(words[best_i:])

        # Ricorsione per linee ancora troppo lunghe
        return self._wrap_cpl(line1) + self._wrap_cpl(line2)

    # ── Overlap fix ───────────────────────────────────────────────────────────

    def _fix_overlaps(self, blocks: List[Dict]) -> List[Dict]:
        """Elimina sovrapposizioni temporali tra blocchi consecutivi.

        Il forced aligner produce word timestamps dove la fine del segmento N
        supera di ~20ms l'inizio del segmento N+1. Questi micro-overlap causano
        un 'flash' nei player perché i due sottotitoli appaiono sovrapposti
        per un fotogramma prima che il primo scompaia.

        Fix: se block[i].end > block[i+1].start, clippiamo block[i].end a
        block[i+1].start - 20ms (gap minimo garantito). Se dopo il clip la
        durata è zero o negativa, usiamo direttamente block[i+1].start come
        nuovo end (il blocco durerà 0ms e verrà poi espanso da
        _enforce_min_duration se necessario).
        """
        result = list(blocks)
        for i in range(len(result) - 1):
            if result[i]['end'] > result[i + 1]['start']:
                new_end = result[i + 1]['start'] - 0.020
                result[i] = dict(result[i])
                result[i]['end'] = max(new_end, result[i]['start'])
        return result

    # ── Min duration (anti-flash) ─────────────────────────────────────────────

    def _enforce_min_duration(self, blocks: List[Dict]) -> List[Dict]:
        """Espande blocchi troppo brevi alla durata minima (anti-flash).

        Non sovrappone mai il blocco successivo: lascia almeno 50ms di gap.
        """
        result = list(blocks)
        for i in range(len(result)):
            block    = result[i]
            duration = block['end'] - block['start']
            if duration >= self.min_duration:
                continue

            desired_end = block['start'] + self.min_duration
            if i + 1 < len(result):
                max_end     = result[i + 1]['start'] - 0.05   # 50ms gap
                desired_end = min(desired_end, max_end)

            if desired_end > block['end']:
                result[i] = dict(block)
                result[i]['end'] = desired_end

        return result

    # ── Rendering ────────────────────────────────────────────────────────────

    def _render(self, blocks: List[Dict]) -> str:
        """Serializza i blocchi in stringa SRT."""
        output: List[str] = []
        idx = 0
        for block in blocks:
            text_lines = []
            for line in block['lines']:
                t = line['text']
                if not t:
                    continue
                if line.get('dash'):
                    t = f"- {t}"
                text_lines.append(t)

            if not text_lines:
                continue

            idx += 1
            output.append(str(idx))
            output.append(f"{self._ts(block['start'])} --> {self._ts(block['end'])}")
            output.extend(text_lines)
            output.append("")

        return "\n".join(output)

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _ts(seconds: float) -> str:
        """Secondi → timestamp SRT HH:MM:SS,mmm"""
        ms = int(round(seconds * 1000))
        h  = ms // 3_600_000;  ms %= 3_600_000
        m  = ms // 60_000;     ms %= 60_000
        s  = ms // 1_000;      ms %= 1_000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
