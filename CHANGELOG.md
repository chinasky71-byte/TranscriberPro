# Changelog

Tutte le modifiche rilevanti di Transcriber Pro. Versioni secondo
[SemVer](https://semver.org/lang/it/): `APP_VERSION` in `main.py` è l'unica fonte di verità.

## [1.6.0] — 2026-07-15

### Gender Corrector v2 — redesign completo (audio-driven, deterministico)

Il correttore di genere LLM (Qwen2.5-14B GGUF) è stato sostituito integralmente:
misurato sul benchmark, correggeva 2 errori su ~90 (+0,66 punti — di fatto inerte).

**Nuovo approccio**: il genere di chi parla non è deducibile dal testo
("I'm tired" non dice se parla un uomo o una donna) — ma è nella **voce**.

- **Speaker Gender Map** (`core/speaker_gender.py`): diarization pyannote +
  classificatore ECAPA (VoxCeleb2) → genere di ogni parlante con confidenza.
  Accuratezza 95,0% (validata su 22 episodi contro sottotitoli professionali).
- **Selettore morfosintattico** (`core/gender_line_selector.py`, spaCy in venv
  separato): individua le sole forme di 1ª/2ª persona che concordano col
  parlante/interlocutore; esclusioni blindate (participi con *avere*,
  modificatori nominali, dialoghi doppi, impersonali...).
- **Riscrittura deterministica + validatore** (`core/gender_rewriter.py`):
  flip morfologico (-o↔-a + tabella articoli/pronomi) accettato solo se ogni
  parola cambiata è una coppia di flessione plausibile → allucinazioni
  impossibili per costruzione. Il motore deterministico ha battuto Qwen2.5-14B
  nel confronto diretto (86,8% vs 83,1%).
- **2ª persona** ("sei stanca?"): genere dell'interlocutore dai turni di
  dialogo (91,4%, modalità strict) e dai vocativi col cast TMDB
  ("Sei cresciuta, Veronica").
- **Riuso diarization**: i turni calcolati in trascrizione vengono riusati
  dallo STEP 6.5 (~1-2 minuti risparmiati a film).

**Risultati** (ground-truth auto-estratto da sottotitoli professionali dual-track):
| Metrica | Prima (NLLB) | Dopo |
|---|---|---|
| 1ª persona femminile (corpus) | 19,3% | **86,8%** |
| 1ª persona maschile (corpus) | 89,3% | **93,3%** |
| A/B episodio reale, femminili | 0% | **60%** |
| A/B episodio reale, maschili | 100% | **100%** (mai degradato) |

**Migrazione**: il modello GGUF non serve più. Per la correzione genere ora
servono: venv NLP separato con spaCy (`venv_nlp/`, vedi README → Installation)
e un token HuggingFace (pyannote). Nuove chiavi config:
`gender_correction_second_person` (default on), `gender_selector_python`
(auto-discovery se vuota). UI impostazioni aggiornata.

Include inoltre: harness di valutazione completo in `gender_eval/`
(benchmark MT-GenEval, ground-truth builder dai film dual-track, A/B runner).

## [1.5.x] — 2026-06/07

Versioni precedenti al changelog: modulo OCR bitmap PGS/VOBSUB → SRT
(Tesseract parallelo, review UI, writeback mux/sidecar), integrazione Library
Scanner (badge bitmap, batch OCR, Superpower), routing OCR nella coda
principale, GUI revamp (icone SVG, settings unificati, i18n IT/EN),
ottimizzazione avvio (~2s), fix import bitmap in coda. Vedi la cronologia git.
