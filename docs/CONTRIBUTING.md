# Contributing

Read `AGENTS.md` first. The hard rules there (consent, privacy, English-only
documentation) apply to every contribution.

## Branch model

```
master          ← releases only, protected
  ↑ PR (from development)
development     ← integration, protected
  ↑ PR (from feature branches)
feat/…  fix/…  docs/…  test/…  bench/…
```

- Never commit directly to `master` or `development`.
- Create the branch from the **current** `origin/development`.
- Delete the feature branch after the merge (locally and remotely).

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
- `development` → `master`: only at a milestone/release, via PR.

## Releases

- Bump `APP_VERSION` in `main.py` and update `CHANGELOG.md`.
- Tag `master`.
- Build and publish Docker images with tags `backend-version` and `backend-sha`.
