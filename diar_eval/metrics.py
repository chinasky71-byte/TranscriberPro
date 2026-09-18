"""
diar_eval - metriche pure
File: diar_eval/metrics.py

Funzioni pure (nessuno stato, nessuna chiamata a GPU/config): parsing SRT,
metriche sui turni di diarization, valutazione contro l'insieme oro. Usate
sia da diar_bench.py sia direttamente in una shell interattiva per
ispezionare un run senza rilanciarlo.

Nessuna di queste funzioni chiama get_config()/set() — leggono solo i file
che diar_bench.py ha già scritto su disco (v. piano_fix_pipeline_
trascrizione: il banco non deve mai toccare la config globale).
"""
from __future__ import annotations
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Turn = Tuple[float, float, str]


# ── Parsing SRT ──────────────────────────────────────────────────────────

_BLOCK_RE = re.compile(
    r'(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)',
    re.DOTALL,
)


def _ts_to_seconds(ts: str) -> float:
    h, m, rest = ts.split(':')
    s, ms = rest.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path: Path) -> List[Dict]:
    """Ritorna [{'index','start','end','text'}] da un file su disco."""
    return parse_srt_text(Path(path).read_text(encoding='utf-8-sig'))


def parse_srt_text(text: str) -> List[Dict]:
    """Come parse_srt ma da una stringa già in memoria (es. l'output di
    SubtitleFormatter.format_srt(), senza scriverlo su disco). 'text' del
    blocco con newline interne preservate — serve a distinguere blocchi a 1
    riga da blocchi a 2 righe per il conteggio dialogo."""
    blocks = []
    for m in _BLOCK_RE.finditer(text.strip() + '\n\n'):
        idx, start, end, body = m.groups()
        blocks.append({
            'index': int(idx),
            'start': _ts_to_seconds(start),
            'end': _ts_to_seconds(end),
            'text': body.strip('\n'),
        })
    return blocks


def count_dialogue_blocks(blocks: List[Dict]) -> int:
    """Blocchi con almeno una riga che inizia per '- ' (stile Netflix)."""
    return sum(1 for b in blocks if any(
        line.strip().startswith('-') for line in b['text'].split('\n')))


def count_cpl_violations(blocks: List[Dict], cpl_max: int = 42) -> int:
    """Righe (al netto del trattino) più lunghe di cpl_max caratteri."""
    n = 0
    for b in blocks:
        for line in b['text'].split('\n'):
            stripped = line.strip()
            if stripped.startswith('- '):
                stripped = stripped[2:]
            elif stripped.startswith('-'):
                stripped = stripped[1:]
            if len(stripped) > cpl_max:
                n += 1
    return n


# ── Metriche sui turni di diarization ────────────────────────────────────

def turn_metrics(turns: List[Turn]) -> Dict:
    """speakers/turns/speech_s/turn_med_s/top1_pct/top5_pct/n_spk_ge2pct/
    tail_lt2pct — calcolate DAI TURNI, non da grep sul log (v. spec §3.5:
    il log resta un riscontro incrociato, non la sorgente dei dati)."""
    if not turns:
        return dict(speakers=0, turns=0, speech_s=0.0, turn_med_s=0.0,
                     top1_pct=0.0, top5_pct=[], n_spk_ge2pct=0, tail_lt2pct=0)

    by_speaker: Dict[str, float] = defaultdict(float)
    durations = []
    for start, end, spk in turns:
        d = end - start
        by_speaker[spk] += d
        durations.append(d)

    speech_total = sum(by_speaker.values())
    durations.sort()
    n = len(durations)
    turn_med = durations[n // 2] if n % 2 else (durations[n // 2 - 1] + durations[n // 2]) / 2

    ranked = sorted(by_speaker.values(), reverse=True)
    top5_pct = [round(100 * d / speech_total, 1) for d in ranked[:5]] if speech_total > 0 else []
    top1_pct = top5_pct[0] if top5_pct else 0.0
    n_spk_ge2pct = sum(1 for d in by_speaker.values() if speech_total > 0 and d / speech_total >= 0.02)
    tail_lt2pct = sum(1 for d in by_speaker.values() if speech_total > 0 and d / speech_total < 0.02)

    return dict(
        speakers=len(by_speaker), turns=len(turns), speech_s=round(speech_total, 1),
        turn_med_s=round(turn_med, 2), top1_pct=top1_pct, top5_pct=top5_pct,
        n_spk_ge2pct=n_spk_ge2pct, tail_lt2pct=tail_lt2pct,
    )


def speaker_at(turns: List[Turn], t: float) -> Optional[str]:
    """Speaker con overlap massimo su un singolo istante (fallback: nessun
    turno tocca t -> None). Usato per la valutazione oro (intervalli
    brevi: prende il midpoint dell'intervallo)."""
    best_spk, best_dur = None, 0.0
    for start, end, spk in turns:
        if start <= t <= end:
            return spk
    return None


def speaker_for_interval(turns: List[Turn], a: float, b: float) -> Optional[str]:
    """Speaker con overlap massimo sull'intervallo [a,b] (più robusto del
    solo midpoint quando l'intervallo scavalca un confine di turno)."""
    overlap: Dict[str, float] = defaultdict(float)
    for start, end, spk in turns:
        ov = min(b, end) - max(a, start)
        if ov > 0:
            overlap[spk] += ov
    if not overlap:
        return None
    return max(overlap, key=overlap.get)


# ── Valutazione contro l'insieme oro ──────────────────────────────────────

def score_gold(gold_pairs: List[Dict], turns: List[Turn]) -> Dict:
    """Per ogni coppia oro (a=[start,end], b=[start,end], same_speaker),
    predice same/diverso dai turni del run e calcola recall_same,
    spec_diff, balanced_acc. Coppie con same_speaker None (etichetta '?')
    sono escluse dal punteggio ma contate separatamente."""
    tp = fp = tn = fn = skipped = n_unmatched = 0
    wrong_ids = []
    for pair in gold_pairs:
        truth = pair.get('same_speaker')
        if truth is None:
            skipped += 1
            continue
        spk_a = speaker_for_interval(turns, *pair['a'])
        spk_b = speaker_for_interval(turns, *pair['b'])
        # Nessun parlato rilevato su un lato: chiave per confrontare modelli
        # diversi (bug-check Opus, community-1). Su una coppia 'same' finisce
        # in fn (penalizza recall_same); su una coppia 'diff' finisce in tn
        # GRATIS (regala spec_diff) — se non è ~0 su entrambi gli arm, il
        # confronto di balanced_acc fra due modelli non è comparabile senza
        # escludere queste coppie da entrambi.
        if spk_a is None or spk_b is None:
            n_unmatched += 1
        pred_same = (spk_a is not None and spk_a == spk_b)
        if truth:
            if pred_same:
                tp += 1
            else:
                fn += 1
                wrong_ids.append(pair['id'])
        else:
            if pred_same:
                fp += 1
                wrong_ids.append(pair['id'])
            else:
                tn += 1

    recall_same = tp / (tp + fn) if (tp + fn) else float('nan')
    spec_diff = tn / (tn + fp) if (tn + fp) else float('nan')
    valid = [x for x in (recall_same, spec_diff) if x == x]  # scarta NaN
    balanced_acc = sum(valid) / len(valid) if valid else float('nan')

    return dict(
        tp=tp, fp=fp, tn=tn, fn=fn, skipped=skipped, n_unmatched=n_unmatched,
        recall_same=round(recall_same, 3) if recall_same == recall_same else None,
        spec_diff=round(spec_diff, 3) if spec_diff == spec_diff else None,
        balanced_acc=round(balanced_acc, 3) if balanced_acc == balanced_acc else None,
        wrong_ids=wrong_ids,
    )


# ── Confronto v1/v2 per il punto C (CDF di min(conf_a, conf_b)) ──────────

def dash_threshold_curve(
    annotated_segments: List[Dict],
    thresholds: List[float],
    build_blocks_fn,
) -> Dict[float, int]:
    """Per ciascuna soglia, conta i blocchi dialogo prodotti da
    build_blocks_fn(segments, dash_confidence_min=thr). build_blocks_fn è
    iniettata dal chiamante (in pratica: un SubtitleFormatter già istanziato
    per quella soglia) — questo modulo resta senza dipendenze da core/.
    """
    return {thr: build_blocks_fn(annotated_segments, thr) for thr in thresholds}


def histogram(values: List[float], n_bins: int = 20, lo: float = 0.0, hi: float = 1.0) -> List[int]:
    """Istogramma testuale semplice, nessuna dipendenza numpy."""
    bins = [0] * n_bins
    width = (hi - lo) / n_bins
    for v in values:
        if v != v:  # NaN
            continue
        idx = int((v - lo) / width)
        idx = max(0, min(n_bins - 1, idx))
        bins[idx] += 1
    return bins


def render_histogram(bins: List[int], label: str = '') -> str:
    peak = max(bins) if bins else 1
    peak = peak or 1
    row = ''.join('#' * max(1, round(30 * b / peak)) if b else '.' for b in bins)
    return f"{label:>4} |{row}"
