"""
Copia TESTUALE (solo lettura, per la misura offline) del metodo
FasterWhisperEngine._split_segment_by_words di produzione al 24/09/2026
(sha256 del file motore prima dell'aggancio: bb05d412...). Unica differenza:
funzione libera invece di metodo (nessun uso di self nel corpo).
I test verificano che il metodo del motore con l'opzione spenta dia lo stesso
risultato di questa copia.
"""


def orig_split(segment: dict, max_chars: int = 80, max_duration: float = 6.0) -> list:
    words = segment.get('words', [])
    text = segment['text']
    duration = segment['end'] - segment['start']

    # Segmento già corto: nessuno split necessario
    if not words or (len(text) <= max_chars and duration <= max_duration):
        return [{'start': segment['start'], 'end': segment['end'],
                 'text': text, 'words': words}]

    result = []
    current_words = []
    current_start = None
    current_text = ''

    for word in words:
        w_text = word['word']
        if current_start is None:
            current_start = word['start']

        candidate_text = current_text + w_text
        candidate_duration = word['end'] - current_start

        if current_words and (
            len(candidate_text.strip()) > max_chars
            or candidate_duration > max_duration
        ):
            result.append({
                'start': current_start,
                'end': current_words[-1]['end'],
                'text': current_text.strip(),
                'words': list(current_words),
            })
            current_start = word['start']
            current_text = w_text
            current_words = [word]
        else:
            current_text = candidate_text
            current_words.append(word)

    if current_words and current_text.strip():
        result.append({
            'start': current_start,
            'end': current_words[-1]['end'],
            'text': current_text.strip(),
            'words': list(current_words),
        })

    if len(result) >= 2 and len(result[-1]['words']) < 4:
        tail = result[-1]
        prev = result[-2]
        tail_gap = tail['words'][0]['start'] - prev['words'][-1]['end']
        prev_concluded = prev['text'].rstrip().endswith(
            ('.', '!', '?', '…', '。', '！', '？'))
        if tail_gap <= 0.8 and not prev_concluded:
            result.pop()
            result[-1] = {
                'start': prev['start'],
                'end':   tail['end'],
                'text':  (prev['text'] + ' ' + tail['text']).strip(),
                'words': prev['words'] + tail['words'],
            }

    return result or [{'start': segment['start'], 'end': segment['end'], 'text': text}]
