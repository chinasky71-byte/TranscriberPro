# Vendored frontend assets

Committed locally so the WebUI works offline and without external CDNs.

| File | Project | Version | License |
|---|---|---|---|
| `htmx.min.js` | [htmx](https://htmx.org) | 2.0.4 | BSD 2-Clause |
| `alpine.min.js` | [Alpine.js](https://alpinejs.dev) | 3.14.8 | MIT |

Downloaded from `unpkg.com` on 2026-10-25. Update both files and this table
together; never load them from a CDN at runtime (CSP and offline use).
