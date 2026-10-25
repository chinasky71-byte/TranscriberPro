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
