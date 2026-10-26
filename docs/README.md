# Documentation index

Start at [`AGENTS.md`](../AGENTS.md). It contains the rules and the reading
order; this page is the full catalogue.

Legend: **authoritative** = current and maintained; **historical** = kept for
context, not a source of truth; **IT** = written in Italian, to be translated
when touched (documentation hard rule).

## Core documents

| Document | Purpose | Status |
|---|---|---|
| [`AGENTS.md`](../AGENTS.md) | entry point: rules, reading order, repository map, workflow | authoritative |
| [`STATUS.md`](STATUS.md) | current state: branch, what works, open issues | authoritative |
| [`PROGRESS.md`](PROGRESS.md) | append-only session log | authoritative |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | branch model, PR, session protocol, releases | authoritative |
| [`SUPPORT_MATRIX.md`](SUPPORT_MATRIX.md) | supported platforms and tiers | authoritative |

## Architecture

| Document | Purpose | Status |
|---|---|---|
| [`architecture/README.md`](architecture/README.md) | layers, dependency rules, index | authoritative |
| [`architecture/layers.md`](architecture/layers.md) | responsibilities and forbidden imports | authoritative |
| [`architecture/contracts.md`](architecture/contracts.md) | Caps, RuntimeProfile, Platform, JobManager, events | authoritative |
| [`architecture/runtime.md`](architecture/runtime.md) | CUDA/ROCm/Vulkan/CPU policy and failure modes | authoritative |
| [`architecture/platform-services.md`](architecture/platform-services.md) | OS-specific services | authoritative |
| [`architecture/domain.md`](architecture/domain.md) | pipeline steps and error semantics | authoritative |
| [`architecture/events.md`](architecture/events.md) | structured event protocol v1 | authoritative |
| [`architecture/config.md`](architecture/config.md) | configuration, env vars, secrets | authoritative |
| [`architecture/security.md`](architecture/security.md) | auth, paths, containers | authoritative |
| [`architecture/testing.md`](architecture/testing.md) | test layers and CI matrix | authoritative |
| [`architecture/extension-guide.md`](architecture/extension-guide.md) | recipes for new engines/models/backends/pages | authoritative |
| [`architecture/legacy/architecture_overview_v1.md`](architecture/legacy/architecture_overview_v1.md) | obsolete v1.0 overview | historical |

## Decisions (ADRs)

| Document | Decision |
|---|---|
| [`adr/ADR-001-one-codebase-n-artifacts.md`](adr/ADR-001-one-codebase-n-artifacts.md) | one codebase, per-stack artifacts |
| [`adr/ADR-002-webui-replaces-gui.md`](adr/ADR-002-webui-replaces-gui.md) | WebUI replaces the desktop GUI |
| [`adr/ADR-003-platform-vs-runtime.md`](adr/ADR-003-platform-vs-runtime.md) | OS services vs GPU runtime |
| [`adr/ADR-004-docker-distribution.md`](adr/ADR-004-docker-distribution.md) | Docker as the distribution artifact |
| [`adr/ADR-005-support-matrix.md`](adr/ADR-005-support-matrix.md) | explicit support tiers |
| [`adr/ADR-006-two-lines.md`](adr/ADR-006-two-lines.md) | legacy master, development product line |

## Active work

| Document | Purpose | Status |
|---|---|---|
| [`webui/SPEC.md`](webui/SPEC.md) | WebUI functional and technical specification | authoritative |
| [`webui/PLAN.md`](webui/PLAN.md) | step-by-step implementation plan and status | authoritative |
| [`../web/README.md`](../web/README.md) | Web API: run, environment, endpoints | authoritative |

## Evidence

| Document | Purpose | Status |
|---|---|---|
| [`benchmarks/README.md`](benchmarks/README.md) | method, policy, how to reproduce | authoritative |
| [`benchmarks/2026-10-25/README.md`](benchmarks/2026-10-25/README.md) | ASR and translation results on the AMD machine | authoritative |
| [`VALIDAZIONE_AMD_2026-10-24.md`](VALIDAZIONE_AMD_2026-10-24.md) | AMD hardware validation report | authoritative |

## Historical documents (not authoritative)

These files describe older versions or the legacy Windows/GUI line. They are
kept for context. Most are in Italian and must be translated when modified.

| Document | Language | Note |
|---|---|---|
| [`../README.md`](../README.md) | EN + IT | product page; the Italian section is historical |
| [`../CHANGELOG.md`](../CHANGELOG.md) | IT | release history |
| [`../CLAUDE_INTEGRATION.txt`](../CLAUDE_INTEGRATION.txt) | IT | Claude API integration guide (legacy desktop line); translate only as separate work |
| [`../COME_FUNZIONA_UPLOAD.md`](../COME_FUNZIONA_UPLOAD.md) | IT | OpenSubtitles upload notes |
| [`../LIBRARY_SCANNER_DEVELOPMENT_PLAN.md`](../LIBRARY_SCANNER_DEVELOPMENT_PLAN.md) | EN | legacy plan |
| [`PROVA_AMD_COMPLETA.md`](PROVA_AMD_COMPLETA.md) | IT | AMD checklist, superseded by the validation report |
| [`GGUF_CONVERSIONE.md`](GGUF_CONVERSIONE.md) | IT | GGUF conversion notes |
| [`GUIDA_OPENSUBTITLES_REST_API.md`](GUIDA_OPENSUBTITLES_REST_API.md) | IT | OpenSubtitles REST guide |
| [`HANDOFF_CLOUD_LINUX_AMD.md`](HANDOFF_CLOUD_LINUX_AMD.md) | IT | handoff notes |
| [`HANDOFF_LOG_GGUF_TRANSLATOR.md`](HANDOFF_LOG_GGUF_TRANSLATOR.md) | IT | handoff notes |
| [`HANDOFF_LOG_I18N.md`](HANDOFF_LOG_I18N.md) | IT | handoff notes |
| [`HANDOFF_LOG_LINUX_AMD.md`](HANDOFF_LOG_LINUX_AMD.md) | IT | handoff notes |
| [`studio_rocm_2026_10_22.md`](studio_rocm_2026_10_22.md) | IT | ROCm study |
| [`guida_installazione.md`](guida_installazione.md) | IT | installation guide |
| [`guida_installazione_update_v103.md`](guida_installazione_update_v103.md) | IT | installation update |
| [`guida_opensubtitles_v103.md`](guida_opensubtitles_v103.md) | IT | OpenSubtitles guide |
| [`guida_utente.md`](guida_utente.md) | IT | user guide |
| [`guida_utente_updated_v103.md`](guida_utente_updated_v103.md) | IT | user guide update |
| [`docs_update_summary_v103.md`](docs_update_summary_v103.md) | IT | documentation update summary |
| [`adaptive_batch_readme_it.md`](adaptive_batch_readme_it.md) | IT | adaptive batch notes |
| [`opensubtitles_readme.md`](opensubtitles_readme.md) | IT | OpenSubtitles notes |
| [`troubleshooting.md`](troubleshooting.md) | IT | troubleshooting notes |
| [`../opensubtitles_upload_guida.md`](../opensubtitles_upload_guida.md) | IT | upload guide |
| [`../opensubtitles_api_upload_guide.md`](../opensubtitles_api_upload_guide.md) | IT | upload guide |

English historical references that remain useful: `installation_guide_en.md`,
`opensubtitles_readme_en.md`, `adaptive_batch_readme_en.md`,
`opensubtitles_quickstart.md`.
