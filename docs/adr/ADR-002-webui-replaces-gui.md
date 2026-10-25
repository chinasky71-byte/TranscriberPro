# ADR-002 — The WebUI replaces the desktop GUI

- Status: accepted
- Date: 2026-10-25

## Context

The PyQt6 GUI duplicates the queue, progress and settings logic that a web
interface needs; it also requires a display, Qt dependencies and
platform-specific packaging. The pipeline is already headless
(`core.pipeline_cli`) and the container is the intended distribution.

## Decision

The WebUI becomes the primary interface. The GUI is frozen, kept as a
functional reference during the transition, then removed. PyQt6 moves to an
optional extra and is no longer a requirement of the product.

## Alternatives considered

- Keep both interfaces: rejected, two frontends to maintain with no benefit.
- GUI inside the container (X11): rejected, fragile and pointless for a server.
- CLI only: rejected, the queue and progress need a graphical interface.

## Consequences

- A service layer (`core/jobs/`) must be extracted before removing the GUI.
- Web security becomes part of the product: bind address, auth, path allowlist.
- The Windows native desktop path is no longer a supported distribution.
