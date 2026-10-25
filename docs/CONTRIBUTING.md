# Contributing

Read `AGENTS.md` first. The hard rules there (consent, privacy, English-only
documentation) apply to every contribution.

## Branch model

```
master          ← legacy desktop line, maintained outside this workflow
development     ← integration for the new product (WebUI, Linux, Docker)
  ↑ PR (from feature branches)
feat/…  fix/…  docs/…  test/…  bench/…
```

- `development` is the integration branch. Create feature branches from the
  **current** `origin/development`.
- **Do not merge `development` into `master` for now**: the two lines have
  different targets (see ADR-006). `master` is maintained by another
  contributor.
- Merge `origin/master` into `development` when master changes, so the legacy
  line stays compatible.
- Never commit directly to `development`.
- Delete the feature branch after the merge (locally and remotely).
- `development` may become a separate repository later; the split is a
  separate decision (ADR-006).

## Session protocol (avoid divergence)

Before starting work:

```bash
git fetch origin
git status -sb
git switch -c <type>/<short-name> origin/development
```

Before opening a pull request:

```bash
git fetch origin
git rebase origin/development
```

If the branch diverges or the remote moved in an unexpected way: **stop and ask**.
Do not force-push shared branches.

## Rules

1. **Published history is immutable.** No rebase, amend or filter on
   `master`/`development` or on a branch someone else may have based work on.
   `--force-with-lease` is allowed only on your own feature branch.
2. **Small pull requests**: one task, one branch, one PR. Aim for under ~400
   changed lines where possible.
3. **Tests**: a bug fix includes a regression test; a feature includes tests for
   the new contract.
4. **Documentation in English** (hard rule). Update the relevant document when
   a contract, event or config key changes.
5. **No personal data** in the repository, logs committed to git, or fixtures.
6. **No secrets**: tokens, passwords and keys never enter the tree.
7. **Platform code** goes to `platform_services/` or `runtime/`; the domain
   must not check `sys.platform` or `torch.version.hip`.
8. **No driver installs** and no system modifications at runtime.
9. **Commits**: imperative subject, body explaining cause and evidence, plus
   the project trailers when applicable.

## Pull requests

Use the template. A PR is ready when:

- CI is green (unit tests, guard tests, Docker build);
- the change is reviewed;
- documentation is updated;
- no allowlist entry was added without justification.

## Merge strategy

- Feature branch → `development`: `--no-ff` merge commit.
- `master` → `development`: merge when the legacy line changes.
- `development` → `master`: **not for now**. `development` releases are tagged
  independently; `master` releases are handled by its maintainer (ADR-006).

## Releases

- Development line: bump `APP_VERSION` in `main.py`, update `CHANGELOG.md`,
  tag `development`.
- Build and publish Docker images with tags `backend-version` and `backend-sha`.
- Legacy line: release handling stays with the `master` maintainer.
