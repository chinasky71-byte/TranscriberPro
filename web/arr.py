"""Search Sonarr / Radarr and turn the results into queueable files.

The file picker is a directory browser: fine for one file, tedious for a season.
Sonarr and Radarr already know the library, so the WebUI asks them instead.

What this module does, and nothing more:

- reads the two servers' URL and API key from the config (`sonarr_url`,
  `sonarr_api_key`, `radarr_url`, `radarr_api_key`); a server without both is
  simply not offered, and the page says so;
- searches by title (`/api/v3/series/lookup`, `/api/v3/movie/lookup`) and lists
  the episodes of a series (`/api/v3/episode?seriesId=`) or the file of a movie
  (`/api/v3/movie/{id}`) with the path **as the server sees it**;
- maps that path to a local one with `arr_path_map`, the same
  `<server prefix>=<local prefix>` rules the Library Scanner uses
  (`utils/path_map.py`), so an *arr in a container (`/tv/...`) works with media on
  `/mnt/storage/tvshows/...`;
- validates the mapped path against the allowed media roots with
  `web/paths.py::is_allowed` — exactly the check the queue applies — and reports
  it as `allowed: False` instead of pretending it can be queued;
- says whether a subtitle sidecar already exists (`browse.has_subtitle`, the same
  language-agnostic check the picker's `skip_existing` uses).

Read-only on both sides: no POST to Sonarr/Radarr, no writes anywhere. Secrets
are used to build the request and never returned or logged.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

# Sonarr and Radarr live on the LAN: an `http_proxy` in the environment must not
# be used for them (urllib would send 127.0.0.1 through the proxy and hang).
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from utils import path_map
from web.browse import has_subtitle
from web.paths import compute_roots, is_allowed

TIMEOUT_S = 10
MAP_KEY = "arr_path_map"

# (kind, url key, api key key, label)
SERVERS = (
    ("series", "sonarr_url", "sonarr_api_key", "Sonarr"),
    ("movie", "radarr_url", "radarr_api_key", "Radarr"),
)


class ArrError(RuntimeError):
    """The server could not be asked. The message is user-facing and never
    contains the API key."""


@dataclass(frozen=True)
class Server:
    kind: str
    base: str
    api_key: str
    label: str


@dataclass
class Item:
    """One queueable file, already mapped and validated."""
    title: str
    subtitle: str
    path: str
    has_subtitle: bool
    allowed: bool
    reason: str = ""

    @property
    def queueable(self) -> bool:
        return self.allowed and not self.has_subtitle


@dataclass
class Group:
    """A series (or one movie) with its items."""
    title: str
    subtitle: str
    items: List[Item] = field(default_factory=list)

    @property
    def missing(self) -> List[Item]:
        return [item for item in self.items if item.queueable]


def servers(get: Callable[[str, Any], Any]) -> List[Server]:
    """The configured servers, in a stable order. A server needs URL **and** key."""
    out: List[Server] = []
    for kind, url_key, key_key, label in SERVERS:
        base = str(get(url_key, "") or "").strip().rstrip("/")
        api_key = str(get(key_key, "") or "").strip()
        if base and api_key:
            out.append(Server(kind=kind, base=base, api_key=api_key, label=label))
    return out


def _rules(get: Callable[[str, Any], Any]):
    text = str(get(MAP_KEY, "") or "")
    # the settings field is a single line in the browser; accept both separators
    return path_map.parse_map(text.replace(";", "\n"))


def _api(server: Server, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{server.base}/api/v3{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        "X-Api-Key": server.api_key,
        "Accept": "application/json",
        # Sonarr and Radarr both refuse requests without a User-Agent
        "User-Agent": "TranscriberPro-webui",
    })
    try:
        with _OPENER.open(request, timeout=TIMEOUT_S) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ArrError(f"{server.label}: HTTP {exc.code} on {path}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ArrError(f"{server.label}: {exc}") from None
    except ValueError as exc:                       # not JSON
        raise ArrError(f"{server.label}: risposta non leggibile ({exc})") from None


def _item(get, rules, roots, title: str, subtitle: str, server_path: str) -> Item:
    local = path_map.to_local(server_path, rules) if server_path else ""
    if not local:
        return Item(title, subtitle, "", False, False, "nessun file sul server")
    if not is_allowed(Path(local), roots):
        return Item(title, subtitle, local, False, False,
                    f"fuori dalle cartelle ammesse (controlla {MAP_KEY})")
    return Item(title, subtitle, local, has_subtitle(Path(local)), True)


def search(get, term: str) -> List[Group]:
    """Search every configured server; returns groups ready for the template."""
    term = (term or "").strip()
    if not term:
        return []
    rules = _rules(get)
    roots = compute_roots(get)
    groups: List[Group] = []
    for server in servers(get):
        if server.kind == "series":
            for row in _api(server, "/series/lookup", {"term": term}) or []:
                groups.append(_series_group(server, get, rules, roots, row))
        else:
            for row in _api(server, "/movie/lookup", {"term": term}) or []:
                group = _movie_group(server, get, rules, roots, row)
                if group:
                    groups.append(group)
    return [g for g in groups if g.items]


def _series_group(server: Server, get, rules, roots, row: Dict[str, Any]) -> Group:
    series_id = row.get("id")
    title = row.get("title") or row.get("sortTitle") or "?"
    year = row.get("year")
    group = Group(title=title, subtitle=f"{year} · {server.label}" if year else server.label)
    if not series_id:
        # A lookup result that is not in the library yet: nothing to queue.
        group.items.append(Item(title, "non ancora in libreria", "", False, False,
                                "aggiungilo in Sonarr perché abbia un file"))
        return group
    for episode in _api(server, "/episode", {"seriesId": series_id}) or []:
        if not episode.get("hasFile"):
            continue
        season = episode.get("seasonNumber")
        number = episode.get("episodeNumber")
        code = f"S{int(season):02d}E{int(number):02d}" if season is not None and number is not None else "?"
        ep_title = episode.get("title") or ""
        file_row = episode.get("episodeFile") or {}
        path = file_row.get("path") or ""
        group.items.append(_item(get, rules, roots, code, ep_title, path))
    group.items.sort(key=lambda i: i.title)
    return group


def _movie_group(server: Server, get, rules, roots, row: Dict[str, Any]) -> Optional[Group]:
    movie_id = row.get("id")
    title = row.get("title") or "?"
    year = row.get("year")
    group = Group(title=title, subtitle=f"{year} · {server.label}" if year else server.label)
    if not movie_id:
        group.items.append(Item(title, "non ancora in libreria", "", False, False,
                                "aggiungilo in Radarr perché abbia un file"))
        return group
    detail = _api(server, f"/movie/{movie_id}") or {}
    file_row = detail.get("movieFile") or {}
    path = file_row.get("path") or ""
    if not path:
        group.items.append(Item(title, "nessun file", "", False, False, "il film non ha file"))
        return group
    group.items.append(_item(get, rules, roots, title, str(year or ""), path))
    return group
