# Translation engines against a professional reference (2026-10-28)

Compendium of the whole campaign: which engines were tried, how, what the numbers
say, what did **not** work, and where the remaining margin actually is. Written so
that a later session can resume from the conclusions instead of re-running the
measurements.

Question it answers: *after ADR-009 left a single translation engine
(TranslateGemma-12B GGUF, English→Italian), is any other available model better
for this pipeline, and is there margin left anywhere else?*

Short answer: **no off-the-shelf model wins clearly**, the differences between the
best ones are style (a matter of taste) and cost; the residual defects are few,
mostly not model-shaped, and listed in "Defect taxonomy" below.

## Material

One episode with a **professional English track and a professional Italian track**,
i.e. a golden standard rather than a synthetic clip:

- file: `<media root>/tvshows/Monster (2022)/Season 4/Monster 2022 S04E01 Bloodbath 1080p NF WEB-DL DD 5 1 Atmos H 264-playWEB.mkv`
- 54:27, English 5.1 audio, **38 SubRip tracks**
- **source** = track **2**, `eng`, not SDH → 630 cues, 3 507 words
- **reference** = track **22**, `ita`, professional → 463 cues, 2 693 words
- track 3 (`eng` SDH) exists and was **not** used: it carries sound descriptions

The reference condenses (463 cues against 630): this is why per-cue comparison is
meaningless and every metric below is computed on the **whole text**.

The files stay outside the repository (`<media root>`, `<scratch dir>`):
media and subtitles are not committed, only this document and the harness.

## Method

`bench/translation_compare.py` (new): parse the source SRT into cues, translate
**one cue per call**, write an SRT with the original timings, then compare with the
reference.

What is held constant across engines, so the comparison is direct:

- same source cues, same reference, same order, same durations → **same per-cue
  character budget** (17 CPS, cap 2×42);
- one cue per call, no ids to misalign (the failure that killed the old "adapt"
  path);
- the **product's post-processing** applied to every engine: accent fix
  (`core/italian_accents`), which matters for engines that write `e'` instead of
  `è` (worth up to 4.5 WER points, measured on Italian material on 2026-10-26).

What legitimately differs, and had to be kept consistent:

| family | prompt path |
|---|---|
| TranslateGemma (12B, 27B) | the product's own: `GGUFEngine.mt_messages()` — subtitle rules and character budget **inside the text field**, because gemma3 has no usable system role |
| EuroLLM, Tower+, Hunyuan-MT | their own chat template + the instruction from their model card; with `--rules` the subtitle rules and budget go in the **system role** |
| Seed-X | no chat template (the card says so): raw completion with the `<it>` tag |

Metrics (from `bench/metrics.py`, the same used by the ASR evaluation):

- **chrF** and **WER** against the professional Italian text — read chrF first;
  WER against a human subtitle rewards under-transcription (lesson from
  2026-10-26) and is reported for completeness;
- **chars/cue** and **% over 42** — the physical limit of a subtitle line;
- **length vs source / vs reference** — the reference condenses to 0.83× the
  English, so >1.15× is verbose;
- **identical_to_source** — see the caveat below;
- **seconds** — the same harness, so comparable, but batching differs by family
  (TranslateGemma runs 4 sequences in one call, chat models one cue per call).

### Two metrics that mislead (both verified on this episode)

1. **`identical_to_source` is not "untranslated"**. Of the 29 exact matches in the
   12B output, **21 are interjections, names or short dialogue turns** (`Hm.`,
   `No.`, `- Bridget. - Maggie.`) and 8 are song lyrics (`Ooh-ooh, ooh-ooh…`).
   Real untranslated lines: **0** for the 12B and the 27B, **1** for the 22B
   (`Maids in this home are expected to keep the house spotless,`).
2. **A shorter output is condensation, not loss**. `Are you... are you all right?`
   → `Stai bene?` is correct subtitle practice; a "output < 40% of source chars"
   detector flags it as content loss and is wrong. Real loss found: **1 cue** in
   the 12B (`- Mm... - That's it.` → `Così.`, which drops a speaker).

## Results — every engine tested

All on the same 630 cues; 2026-10-28; Radeon RX 9060 XT 16 GB, ROCm/Vulkan,
llama.cpp (llama-cpp-python 0.3.34).

| Engine | Weights | Licence | chrF | WER | chars/cue | % >42 | len/src | len/ref | identical | time |
|---|---|---|---|---|---|---|---|---|---|---|
| **TranslateGemma-12B Q4** (product, subtitles fine-tune) | 6.80 GiB | Gemma | 0.7608 | **0.7393** | **28.3** | **19.7** | **0.988** | **1.169** | 33 | **131 s** |
| TranslateGemma-12B **+ editor** (Qwen3-14B) | +11.29 | — | 0.7686 | 0.7560 | 28.4 | 19.5 | 0.992 | 1.174 | 33 | 487 s |
| TranslateGemma-27B **Q3_K_M** | 12.51 GiB | Gemma | 0.7449 | 0.8006 | 27.9 | **18.3** | 0.974 | **1.153** | 48 | 298 s |
| **EuroLLM-22B-Instruct-2512 Q4_K_M + rules** | 12.72 GiB | **Apache-2.0** | **0.7682** | 0.7653 | 29.4 | 22.2 | 1.025 | 1.213 | 33 | 495 s |
| EuroLLM-22B Q4_K_M (plain instruction) | 12.72 GiB | Apache-2.0 | 0.7664 | 0.7798 | 30.1 | 23.5 | 1.048 | 1.241 | 47 | 338 s |
| EuroLLM-22B **+ Plex synopsis** | 12.72 GiB | Apache-2.0 | 0.7698 | 0.7716 | 29.6 | 22.9 | — | 1.222 | 45 | 515 s |
| EuroLLM-22B **+ auto style sheet** | 12.72 GiB | Apache-2.0 | 0.7684 | 0.7713 | 29.5 | 22.1 | — | 1.218 | 46 | 734 s |
| EuroLLM-9B-Instruct-2512 Q4_K_M | 5.20 GiB | Apache-2.0 | 0.7600 | 0.8010 | 29.7 | 21.9 | 1.034 | 1.224 | 66 | **145 s** |
| Tower-Plus-9B Q4_K_M | 5.37 GiB | CC-BY-NC-SA | 0.7476 | 0.9005 | 33.0 | 25.1 | 1.147 | 1.358 | 68 | 173 s |
| Hunyuan-MT-7B Q4_K_M | 4.31 GiB | Tencent | 0.6959 | 1.2187 | **40.7** | **34.9** | **1.407** | **1.665** | 37 | 172 s |
| Qwen3-14B Q6_K (general) | 11.29 GiB | Apache-2.0 | 0.7420 | 0.8270 | 28.8 | 20.2 | 1.004 | 1.189 | 36 | 414 s |
| Seed-X-PPO-7B Q4_K_M | 4.24 GiB | ByteDance | **degenerate** | — | — | — | — | — | — | — |

### What each result means

- **TranslateGemma-12B stays the reference**: best WER, tightest length control
  and the fastest, at half the weights of the alternatives. This is a **subtitles
  fine-tune** of `google/translategemma-12b-it`, so it starts with an advantage
  that no generic model matched.
- **EuroLLM-22B is the only credible alternative**: it beats the 12B on chrF
  (0.7682 vs 0.7608) with a clean licence and, with the subtitle rules in the
  system prompt, it ties on `identical_to_source` (33). It costs 3.8× the time and
  1.9× the VRAM, and its WER is worse (more paraphrase, like the 27B).
- **The 27B loses on numbers but reads better in places** (`E sulla forca
  dondolerà` vs the 12B's abstract `E sull'impiccagione si dondolerà`). A blind
  A/B on 20 diverging cues put it **behind 6–13**, so the impression is local.
- **Translation specialists are structurally verbose**: Tower+ 33 chars/cue,
  Hunyuan-MT 40.7, against 28.3 — 34.9% of Hunyuan cues exceed 42 characters and
  its text is 66% longer than the professional. They never saw a length
  constraint; a subtitle pipeline cannot use them as they come.
- **Qwen3-14B (general, Q6) is worse than the smaller specialised model** and its
  errors are grammatical (`un asce`, `Espera`, `non carico lui`, `Che
  interessante`): quantization precision does not compensate for not being
  trained on translation.
- **Seed-X-PPO via the unofficial GGUF degenerates** (repetition loops, Thai
  characters, invented COVID text). The model card warns against unofficial
  quants and it has no chat template. Verdict on the model: **not tested**; the
  packaging was.

## What did NOT work

Three ideas were tested properly and rejected with data.

### 1. Context in the prompt

Two sources of context: the **Plex synopsis** of the episode and an **auto style
sheet** generated from the whole English SRT (setting, period, register,
characters, tricky terms).

| Engine | no context | + Plex synopsis | + auto style sheet |
|---|---|---|---|
| 12B Q4 | chrF 0.7608 · identical 33 | 0.7605 · 33 · **1 cue changed of 630** | 0.7608 · 33 · **0 cues changed of 630** |
| EuroLLM-22B + rules | 0.7682 · 33 | 0.7698 · **45** | 0.7684 · **46** |

- **On the 12B the context is inert**: 1 cue changed out of 630 with the synopsis,
  **zero** with the style sheet. It translates isolated sentences inside a rigid
  template and ignores the preamble — adding it only costs tokens.
- **On the 22B it acts (176–217 cues changed) but hurts**: chrF creeps up while
  the untranslated/share of English gets worse (33 → 45/46) and the WER too. The
  mechanism is that a longer system prompt dilutes the most important rule
  ("translate everything, no English left").
- Verdict: **context as prose is archived**. The auto style sheet keeps its value
  as **material for a glossary** (it found *fainting couch*, *dovecote*, *cherry
  cordial*), not as prompt context.

### 2. Second pass ("editor") over the 12B draft

Qwen3-14B Q6 rewriting the 12B draft, per cue, with the English visible,
constraints (never longer, no new content) and a per-cue fallback to the draft.

- 193 of 630 cues modified, 18 rejected by the guards;
- chrF 0.7608 → 0.7686 (+0.008), WER 0.7393 → 0.7560 (**worse**);
- it fixes real things (`Ha colpito sua madre 40 volte` → `Ha dato 40 ceffoni a
  sua madre`) and **invents** others (`E sull'impiccagione` → `E
  sull'altana`, a rooftop terrace, not a gallows);
- on the *fainting couch* cue it only drops a word, it does not find *dormeuse*.

Verdict: rejected. The guards cannot catch a single wrong word, and +6 minutes per
episode for a wash on the metrics is not a trade the pipeline should make. It
would need to be a **constrained corrector** (content words frozen) to be worth
retrying, and that is a different project.

### 3. "Just use a bigger model"

27B at Q3 and Qwen3-14B at Q6 both lost to a 12B at Q4 that was fine-tuned for
subtitles. Size and quantization precision are not the missing ingredient; the
missing ingredient is the task (subtitle adaptation with a length budget).

## Defect taxonomy — what is real and what is not

Derived from reading the outputs cue by cue, not from the metrics. Useful because
three of these are commonly mistaken for defects.

| Class | Example (short quote) | Real defect? | Who can fix it |
|---|---|---|---|
| **referent / subject error** | `This one will never be asked to go.` → `Non ti chiederanno mai di andartene.` (12B: wrong person; the 22B keeps the subject, clumsily) | **yes**, visible on first read | nothing automatic: no parser in the pipeline. A different model fixes it *sometimes* — one instance each way in this campaign |
| **whole line left in English** | `Maids in this home are expected to keep the house spotless,` (22B, 1 occurrence) | yes | **already covered**: the product's validator flags `wrong_language` (and `copy_through` above 12 characters) and retries |
| **rare term** | `fainting couch` → professional `dormeuse`; engines: `divano da finto svenimento`, `poltrona per svenimenti`, `divano svenimento` | yes, cosmetic | **human-curated glossary only** — no model knows the word, and an automatic extractor cannot invent the rendering |
| **condensation** | `Are you... are you all right?` → `Stai bene?` | **no** — this is the goal | — |
| **interjections, names, lyrics** | `Hm.`, `- Bridget. - Maggie.`, `Ooh-ooh, ooh-ooh…` | **no** | — |
| **dropping a nonsense word** | `Flapdoodle! This is my personality.` → `È la mia personalità.` | **no** (noise removed); a human editor would keep `Sciocchezze!` | — |

Count on this episode, after the taxonomy: **2 real defects** in the 12B
(one subject error, one dropped speaker turn) plus the rare terms; **2** in the
22B (one line left in English — which the product repairs — and clumsy phrasing).

## Conclusions

1. **No off-the-shelf engine justifies replacing the current one.** The 22B is the
   only one that beats it on chrF, and it pays 3.8× the time and 1.9× the VRAM;
   the difference is style, not correctness.
2. **The remaining margin is not in the model market**: it is
   (a) the rare-terms glossary, human-curated, whose value is real but bounded to
   a handful of cues per episode; (b) comprehension errors, which no validator can
   catch and which a bigger model only sometimes avoids; (c) nothing else — the
   other "defects" in the first analysis were condensation and interjections.
3. **What the campaign is worth keeping**: the method (golden standard, same
   prompt path, text-level metrics, blind A/B for style), the harness
   (`bench/translation_compare.py`), and the two metric caveats above.

## Limits worth stating

- **One episode.** The comparison is *direct* (same input, same reference), so the
  **mechanisms** it exposes are portable: verbosity of MT specialists, the 12B
  ignoring prose context, the editor inventing words, the unofficial Seed-X quant
  degenerating. The **absolute numbers** and the small margins are not: 12B vs 22B
  is 8 thousandths of chrF and could invert on another episode.
- **One genre**: period drama, dense dialogue, simple names. Nothing here says how
  any of these engines behaves on comedy, puns, invented names, or technical
  narration.
- **chrF/WER reward lexical proximity** to a professional subtitle that itself
  paraphrases and condenses; they punish the more idiomatic engines. That is why
  a blind A/B was used for style and why the 27B reads better than its numbers.
- **Batching differs between families**, so the seconds column is comparable in
  order of magnitude, not exactly. TranslateGemma runs 4 sequences per call; the
  chat engines run one cue per call.

## How to reproduce

```bash
# baseline: the product's own engine and prompt path
venv/bin/python -m bench.translation_compare translate --engine translategemma \
  --gguf models/translategemma-12b-gguf/translategemma-12b-it-finale-Q4_K_M.gguf \
  --src <work>/en_professional.srt --ref <work>/it_professional.srt \
  --out <work> --name tg12b_q4

# a chat model with the subtitle rules (budget + "translate everything")
venv/bin/python -m bench.translation_compare translate --engine chat --family eurollm \
  --gguf <models>/EuroLLM-22B-Instruct-2512.Q4_K_M.gguf --rules \
  --src <work>/en_professional.srt --ref <work>/it_professional.srt \
  --out <work> --name eurollm_22b_rules

# the same with a synopsis or a generated style sheet
venv/bin/python -m bench.translation_compare translate --engine chat --family eurollm \
  --gguf <models>/EuroLLM-22B-Instruct-2512.Q4_K_M.gguf --rules \
  --context-file <work>/context_plex.txt ...

# the editor pass: rewrite the 12B draft with a second model, per cue, with fallback
venv/bin/python -m bench.translation_compare edit --gguf <models>/Qwen3-14B-Q6_K.gguf \
  --src <work>/en_professional.srt --draft <work>/tg12b_q4.srt \
  --ref <work>/it_professional.srt --out <work> --name tg12b_edited
```

The two extracted tracks come from the episode with `ffmpeg -map 0:2` and
`-map 0:22`; they stay outside the repository.

---

# Appendix — what the numbers look like in the text

One cue per example, chosen where the engines diverge; excerpts from the SRTs
produced in this campaign, for evaluation only.

## 1. A concrete word five engines lose

```
EN        And on the gallows she will swing
ref       Mentre la figlia dalla forca penzolerà
12B Q4    E sull'impiccagione si dondolerà        ← abstract, loses "gallows"
27B Q3    E sulla forca dondolerà                 ← keeps it
EuroLLM-9B E sulla forca verrà appesa             ← changes the meaning
EuroLLM-22B E sulla forca lei oscillerà           ← keeps it (extra pronoun)
Tower+    E sulla forca si dondolerà              ← literal but correct
Hunyuan   E sulla forca oscillerà…                ← correct, ellipsis added
```

## 2. A referent error, and the one no validator catches

```
EN         This one will never be asked to go.
ref        Questa qui non la inviteranno mai.
12B Q4     Non ti chiederanno mai di andartene.   ← wrong person ("ti")
27B Q3     Non verrà mai più invitato.            ← right subject
EuroLLM-9B Questo non verrà mai chiesto di andare. ← right subject, clumsy
```

## 3. A nonsense word: three different failure modes

```
EN         Flapdoodle! This is my personality.
ref        Sciocchezze! Questo è il mio carattere.
12B Q4     È la mia personalità.                  ← drops it (noise removed)
27B Q3     Assurdità! È la mia personalità.       ← guesses well
EuroLLM-9B Flapdoodle! Questa è la mia personalità. ← leaves English
EuroLLM-22B Flappalacchere! Questa è la mia…      ← invents a word
EuroLLM-22B + rules  Fesseria! Questa è la mia personalità. ← the rule works
```

## 4. A rare term: only a human glossary has the word

```
EN         That fainting couch has been in my family for three generations.
ref        Quella dormeuse è nella mia famiglia da tre generazioni.
12B Q4     Quel divano da finto svenimento è nella mia famiglia da tre generazioni.
27B Q3     Quel divanetto è un cimelio di famiglia da tre generazioni.
EuroLLM-22B Quella poltrona per svenimenti è stata nella mia famiglia per tre generazioni.
Tower+     Quel divano svenimento è stato nella mia famiglia per tre generazioni.
Hunyuan    Quel divano su cui si può svenire appartiene alla mia famiglia da tre generazioni.
```

Nobody knows *dormeuse*. This is the case that justifies a curated glossary and
nothing else.

## 5. Condensation that looks like loss and is not

```
EN         Are you... are you all right?
12B Q4     Stai bene?                     ← correct subtitle practice
EN         - Ah... - Do you know what that is?
12B Q4     Sai cos'è?                     ← drops the interjection, keeps the question
EN         - Mm... - That's it.
12B Q4     Così.                          ← this one IS a loss: a speaker turn disappears
```

## 6. Verbosity, visible in one line

```
EN         Breathe in.            EN      And breathe out.
ref        Inspira,              ref     ed espira.
12B Q4     Inspira.              12B Q4  E ora espira.
27B Q3     Inspira.              27B Q3  Espira.
EuroLLM-9B Fai un respiro profondo.  EuroLLM-9B E respira fuori.
Hunyuan    Fai un respiro profondo.  Hunyuan    E espira.
Tower+     Respirate dentro.         Tower+     E sbuffate.     ← wrong verb
```

## 7. Interjections and lyrics: what `identical_to_source` was counting

```
EN      No. No, no, no, no, no, no, no!       ref: No.
12B Q4  No, no, no, no, no, no, no!            ← the repetition is never condensed
EN      Ooh-ooh, ooh-ooh, ooh, ooh             ← song lyrics, identical by design
EN      - Bridget. - Maggie.                   ← names only
```

None of these is a translation defect; all of them inflate a naive
`untranslated` count.

## 8. What the auto style sheet produced (and why it is glossary material)

Generated once from the English SRT with a 22B model, 120 words:

```
Ambientazione: fine XIX secolo, Stati Uniti, casa borghese.
Registro: dialogo formale, toni drammatici e ironici.
Personaggi: Mrs. Borden, Lizzie Borden, Heath.
Termini da curare: fainting couch, cherry cordial, dovecote, lady time, diluvian.
```

The characters and the rare terms are exactly the right input for a glossary —
which is why the prose-context experiment failed while this output still looks
useful.
