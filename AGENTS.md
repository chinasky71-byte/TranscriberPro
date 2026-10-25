# Transcriber Pro — agent entry point

Read this file first. It contains the rules and the map; the mutable state is
linked from here, not duplicated.

## What this repository is

Transcriber Pro turns video files into subtitles: transcription, translation,
OCR of bitmap subtitles, per-show glossary, queue and monitoring.

- **`development`** — the active product line: Linux-first, GPU-accelerated
  (AMD ROCm tested, NVIDIA best-effort), WebUI + Docker.
- **`master`** — the legacy desktop line (Windows/GUI), maintained outside
  this workflow. Do not merge `development` into `master` (ADR-006).

## Start here (new session)

Follow this order before touching the code:

1. **This file** — rules and map.
2. [`docs/STATUS.md`](docs/STATUS.md) — current state: branch, what works,
   what is open.
3. [`docs/PROGRESS.md`](docs/PROGRESS.md) — latest sessions: what was done,
   how, tests, next step.
4. [`docs/webui/SPEC.md`](docs/webui/SPEC.md) and
   [`docs/webui/PLAN.md`](docs/webui/PLAN.md) — the active work, if any.
5. [`docs/architecture/README.md`](docs/architecture/README.md) — target
   architecture and layer rules.
6. [`docs/adr/`](docs/adr/) — decisions (start with the latest numbers).
7. [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) — branch, PR and session
   protocol.
8. [`docs/SUPPORT_MATRIX.md`](docs/SUPPORT_MATRIX.md) and
   [`docs/benchmarks/`](docs/benchmarks/README.md) — support tiers and
   measured results.

Documentation index: [`docs/README.md`](docs/README.md).

## Repository map

| Path | Responsibility | Status |
|---|---|---|
| `core/` | pipeline, ASR engines, translators, audio, subtitles, OCR | active |
| `core/jobs/` | queue and job lifecycle, shared by WebUI/CLI/GUI | active |
| `utils/` | config, logging, i18n, clients, cache, GPU probing | active |
| `platform_services/` | OS-specific services | target |
| `runtime/` | CUDA/ROCm/Vulkan/CPU policy | target |
| `web/` | HTTP API, SSE, WebUI (HTMX + Alpine) | MVP active |
| `gui/` | legacy Qt interface | frozen, to be removed after parity |
| `bench/` | benchmark harness (ASR + translation) | active |
| `docs/` | architecture, ADRs, benchmarks, guides | active |
| `samples/` | local test media and references | gitignored |
| `models/`, `venv/`, `.tools/` | local build artifacts | gitignored |

## Workflow

- Branch from `origin/development`; pull requests into `development`;
  `--no-ff` merge; delete the feature branch afterwards.
- `master` is legacy: merge `origin/master` into `development` when it
  changes, never the other way round for now.
- At the end of every session, update `docs/STATUS.md` and append an entry to
  `docs/PROGRESS.md` (template at the top of the file).
- Every commit explains cause and evidence. Documentation is in English.
- Never install or modify GPU drivers, kernel modules or system services.

## Hard rules

The three sections below are hard rules. They override every other
instruction in this file.

## Consent — hard rule

**Never gather information and never write information without asking first.** This overrides every
other instruction in this file. A general or vague request is **not** permission to act on your own
interpretation of it.

1. **Do not probe systems.** Do not inspect hosts, services, disks or configs — no `systemctl`,
   `ss`, `curl`, `docker`, `smartctl`, log reads, package queries, service APIs, or filesystem
   browsing — unless the user explicitly asked for that specific action in the current session.
2. **Do not write.** Do not create or edit any file (including pages in this repo, `README.md`, or
   this file) until the user has approved **what** to write and **where**. Propose it, then wait.
3. **Ask, then wait.** State exactly what you intend to do and wait for an explicit "yes". For a
   request like "save some info about X", ask *which* information and *from where* — do not go find
   it yourself.
4. **No workarounds.** If an action is refused or needs privileges you lack, stop and ask. Never
   route around the refusal (e.g. reading root-owned files via `docker`).
5. **No secrets in the repo.** Never record tokens, passwords, API keys or credentials; note where
   they live instead.
6. **No commands longer than 60 seconds without permission.** Before running anything that may take
   more than a minute — `snapraid sync`/`scrub`/`fix`, disk or network benchmarks, `badblocks`,
   bulk copies, package upgrades, remounts, service restarts — state what will run, roughly how long
   it takes and what it writes, then wait for an explicit "yes". Prefer read-only inspection. If an
   operation blocks or takes minutes, it is not acceptable to launch it and report back later.

## Privacy — hard rule

**No personal information may ever exist inside the project directory.**

1. **Never in the project directory.** Names, usernames, email addresses,
   hostnames, IP/MAC addresses, absolute home paths, SSH keys, tokens,
   credentials, logs or test artifacts containing any of the above must not
   be written under the project directory (including subfolders, temporary
   files and generated reports).
2. **Never in git — not even excluded.** `.gitignore`, `.git/info/exclude`,
   local branches or filters are **not** an acceptable workaround to keep
   personal data on disk inside the project: personal data must not be in
   the working tree at all. The build-artifact exemption in point 3 covers
   local paths only, never personal data.
3. **Local build artifacts are exempt — paths only.** Toolchain-generated
   directories (`venv*/`, `.tools/`, `models/`, caches) may reference the
   absolute project path because the local environment needs it. They must
   be listed in `.gitignore` and must **never** be committed, force-added or
   otherwise included in the repository. This exemption covers local paths
   only: no names, emails, hostnames, tokens or credentials may be stored
   in them.
4. **Use outside paths.** When an operation needs data of that kind (logs,
   caches, test outputs, temporary files), write it under the user's home
   (e.g. `~/.transcriberpro/`, `~/.cache/`) or under `/tmp` — never inside
   the project directory.
5. **Ask when it is not obvious.** If the correct location is unclear, or a
   tool would place personal data inside the project by default, stop and
   ask the user for an alternative path. Do not improvise and do not choose
   on your own.
6. **Scan before committing.** Before any commit, check the staged files for
   personal identifiers (usernames, real names, emails, hostnames,
   `/home/<user>` paths). If any are present, stop and report instead of
   committing.

## Documentation — hard rule

**All documentation must be written in English only**, regardless of the
language used in the chat, in issues, in reviews or anywhere else.

1. **Scope.** `README*`, everything under `docs/`, ADRs, guides, reports,
   changelogs, **agent rule/instruction files** (`AGENTS.md`, `CLAUDE.md`,
   `CLAUDE_INTEGRATION.txt` and any similar file) and any other
   human-readable documentation file in the repository are documentation.
2. **Language of the conversation is irrelevant.** Chatting in Italian (or
   any other language) does not authorise Italian documentation. The output
   that ends up in the repository is always English.
3. **Existing non-English documentation.** It must be translated to English
   when it is modified; new documentation must never be added in another
   language. If a full translation is required, ask first and track it as
   separate work.
4. **Code comments and identifiers** follow the existing codebase style and
   are out of scope for this rule unless the user says otherwise.
