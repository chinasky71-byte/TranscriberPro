# -*- coding: utf-8 -*-
"""Library search through Sonarr/Radarr (web/arr.py): two fake servers, path mapping,
subtitle state, paths outside the roots, and the config contract behind it.

The two fake servers are plain `ThreadingHTTPServer`s on 127.0.0.1 with a fixed
port 0, started once per test and shut down in teardown — the same pattern as
`test_library_scanner_fake_server.py`.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web import arr  # noqa: E402
from web.config_schema import ConfigError, normalise_values  # noqa: E402

SONARR_KEY = "test-sonarr-key"
RADARR_KEY = "test-radarr-key"

# The paths as the servers see them (a container: /tv, /movies).
TV_PATH = "/tv/Show"
MOVIE_PATH = "/movies/The Lost Leonardo (2021)"

# Sonarr 5.0's `/episode?seriesId=` carries `hasFile` and `episodeFileId` but no
# `episodeFile` object: the path is a second call, measured on a real instance.
EPISODES = [
    {"seasonNumber": 1, "episodeNumber": 1, "title": "Providence", "hasFile": True,
     "episodeFileId": 101},
    {"seasonNumber": 1, "episodeNumber": 2, "title": "S.W.A.K.", "hasFile": True,
     "episodeFileId": 102},
    {"seasonNumber": 1, "episodeNumber": 3, "title": "No file yet", "hasFile": False},
]

EPISODE_FILES = [
    {"id": 101, "seasonNumber": 1, "path": f"{TV_PATH}/S01E01.mkv"},
    {"id": 102, "seasonNumber": 1, "path": f"{TV_PATH}/S01E02.mkv"},
]


class _Fake(BaseHTTPRequestHandler):
    """Shared JSON plumbing; each server subclass answers its own paths."""

    key = ""

    def log_message(self, *args):                 # keep the test output clean
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self):
        # a wrong key answers 401 in the body, so the client sees a real error
        if self.headers.get("X-Api-Key") != self.key:
            self._send(401, {"error": "unauthorised"})
            return False
        return True


class _Sonarr(_Fake):
    key = SONARR_KEY
    episodes = EPISODES

    def do_GET(self):
        if not self._authorised():
            return
        if self.path.startswith("/api/v3/series/lookup"):
            self._send(200, [{"id": 7, "title": "Outlander - Blood of My Blood", "year": 2025}])
        elif self.path.startswith("/api/v3/episodefile"):   # before /episode: prefix
            assert "seriesId=7" in self.path
            self._send(200, EPISODE_FILES)
        elif self.path.startswith("/api/v3/episode"):
            assert "seriesId=7" in self.path
            self._send(200, type(self).episodes)
        else:
            self._send(404, {})


class _Radarr(_Fake):
    key = RADARR_KEY

    def do_GET(self):
        if not self._authorised():
            return
        if self.path.startswith("/api/v3/movie/lookup"):
            self._send(200, [{"id": 3, "title": "The Lost Leonardo", "year": 2021}])
        elif self.path.startswith("/api/v3/movie/3"):
            self._send(200, {"id": 3, "title": "The Lost Leonardo", "year": 2021,
                             "movieFile": {"path": f"{MOVIE_PATH}/The Lost Leonardo.mkv"}})
        else:
            self._send(404, {})


@pytest.fixture
def servers(tmp_path, monkeypatch):
    """Two fake servers (Sonarr, Radarr) and the local media they point at."""
    # `compute_roots` prefers TP_MEDIA_ROOTS over the config: an ambient value
    # would silently replace the roots these tests set up.
    monkeypatch.delenv("TP_MEDIA_ROOTS", raising=False)
    # with HTTP(S)_PROXY set, urllib would send 127.0.0.1 to the proxy
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    media = tmp_path / "media"
    (media / "tv" / "Show").mkdir(parents=True)
    movie_dir = media / "movies" / "The Lost Leonardo (2021)"
    movie_dir.mkdir(parents=True)
    ep1 = media / "tv" / "Show" / "S01E01.mkv"
    ep2 = media / "tv" / "Show" / "S01E02.mkv"
    movie = movie_dir / "The Lost Leonardo.mkv"
    for path in (ep1, ep2, movie):
        path.write_text("x", encoding="utf-8")
    (media / "tv" / "Show" / "S01E01.it.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nCiao\n", encoding="utf-8")

    started = []
    for handler in (_Sonarr, _Radarr):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02},
                         daemon=True).start()
        started.append(srv)
    try:
        yield {
            "media": media, "ep1": ep1, "ep2": ep2, "movie": movie,
            "sonarr": f"http://127.0.0.1:{started[0].server_address[1]}",
            "radarr": f"http://127.0.0.1:{started[1].server_address[1]}",
            "map": f"/tv={media}/tv\n/movies={media}/movies",
        }
    finally:
        for srv in started:
            srv.shutdown()
            srv.server_close()


def _getter(values):
    return lambda key, default=None: values.get(key, default)


# ---- configuration contract ------------------------------------------------------------------------------------------

def test_servers_need_url_and_key():
    assert arr.servers(_getter({"sonarr_url": "http://x:8989"})) == []
    assert len(arr.servers(_getter({"sonarr_url": "http://x:8989", "sonarr_api_key": "k"}))) == 1


def test_a_non_http_url_is_never_used():
    """`file://` through urllib would read a local file instead of asking a server."""
    for base in ("file:///etc/passwd", "ftp://host/x", "sonarr:8989"):
        assert arr.servers(_getter({"sonarr_url": base, "sonarr_api_key": "k"})) == []


def test_config_accepts_urls_and_map_and_clears_them():
    cleaned = normalise_values({
        "sonarr_url": " http://sonarr:8989/ ", "sonarr_api_key": " k ",
        "radarr_url": "https://radarr.lan:7878", "radarr_api_key": " r ",
        "arr_path_map": "/tv=/mnt/tv; /movies=/mnt/films\n# a comment\n",
    })
    assert cleaned["sonarr_url"] == "http://sonarr:8989"
    assert cleaned["sonarr_api_key"] == "k"
    assert cleaned["arr_path_map"] == "/tv=/mnt/tv\n/movies=/mnt/films"
    assert normalise_values({"sonarr_url": "", "arr_path_map": ""}) == {
        "sonarr_url": "", "arr_path_map": ""}


def test_config_rejects_a_bad_url_and_a_bad_map_line():
    with pytest.raises(ConfigError) as url_error:
        normalise_values({"sonarr_url": "file:///etc/passwd"})
    assert "sonarr_url" in str(url_error.value) and "http" in str(url_error.value)
    for bad in ("/tv", "/tv=", "=/mnt/tv"):
        with pytest.raises(ConfigError) as map_error:
            normalise_values({"arr_path_map": bad})
        assert "arr_path_map" in str(map_error.value)


def test_secrets_are_write_only():
    from web.config_schema import read_values

    class Config:
        values = {"sonarr_api_key": "secret-key", "radarr_api_key": ""}

        def get(self, key, default=None):
            return self.values.get(key, default)

    values = read_values(Config())
    assert values["sonarr_api_key"] == {"is_set": True}
    assert values["radarr_api_key"] == {"is_set": False}
    assert "secret-key" not in json.dumps(values, default=str)


# ---- search ---------------------------------------------------------------------------------------------------------

def test_search_maps_paths_and_marks_subtitle_state(servers):
    cfg = {
        "sonarr_url": servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "allowed_media_roots": [str(servers["media"])],
        "arr_path_map": servers["map"],
    }
    result = arr.search(_getter(cfg), "outlander")
    assert result.warnings == []
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.title.startswith("Outlander")
    assert len(group.items) == 2                     # the episode without a file is skipped
    by_code = {item.title: item for item in group.items}
    assert by_code["S01E01"].path == str(servers["ep1"])
    assert by_code["S01E01"].has_subtitle is True    # the .it.srt sidecar exists
    assert by_code["S01E02"].has_subtitle is False
    assert [item.title for item in group.missing] == ["S01E02"]


def test_paths_outside_the_roots_are_reported_not_queued(servers):
    cfg = {
        "sonarr_url": servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "allowed_media_roots": ["/nonexistent-root"],
        "arr_path_map": servers["map"],
    }
    item = arr.search(_getter(cfg), "outlander").groups[0].items[0]
    assert item.allowed is False and item.queueable is False
    assert "allowed roots" in item.reason


def test_without_mapping_the_server_path_is_not_queueable(servers):
    cfg = {
        "sonarr_url": servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "allowed_media_roots": [str(servers["media"])],
        "arr_path_map": "",                          # no rules at all
    }
    item = arr.search(_getter(cfg), "outlander").groups[0].items[0]
    assert item.allowed is False and item.path.startswith("/tv/")


def test_movie_search_returns_one_file(servers):
    cfg = {
        "radarr_url": servers["radarr"], "radarr_api_key": RADARR_KEY,
        "allowed_media_roots": [str(servers["media"])],
        "arr_path_map": servers["map"],
    }
    group = arr.search(_getter(cfg), "lost leonardo").groups[0]
    assert group.title == "The Lost Leonardo"
    assert group.items[0].path == str(servers["movie"])
    assert group.items[0].allowed is True


def test_a_dead_server_is_a_warning_and_the_other_one_still_answers(servers):
    cfg = {
        "sonarr_url": servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "radarr_url": "http://127.0.0.1:1", "radarr_api_key": RADARR_KEY,
        "allowed_media_roots": [str(servers["media"])],
        "arr_path_map": servers["map"],
    }
    result = arr.search(_getter(cfg), "outlander")
    assert len(result.groups) == 1                   # Sonarr answered
    assert result.warnings and "Radarr" in result.warnings[0]


def test_a_short_term_asks_no_server(servers):
    cfg = {"sonarr_url": servers["sonarr"], "sonarr_api_key": SONARR_KEY}
    result = arr.search(_getter(cfg), "o")
    assert result.groups == [] and result.warnings == []


def test_http_error_is_reported_without_the_key(servers):
    cfg = {"sonarr_url": servers["sonarr"], "sonarr_api_key": "wrong-key-abcdef"}
    result = arr.search(_getter(cfg), "outlander")
    assert result.groups == []
    assert result.warnings and "401" in result.warnings[0]
    assert "wrong-key-abcdef" not in result.warnings[0]


def test_episode_paths_come_from_the_episodefile_endpoint(servers):
    """A real Sonarr 5.0 omits `episodeFile` from the episode list and keeps the
    path in `/api/v3/episodefile`: reading only the episode row leaves every
    episode "no file on the server" and the queue button never appears."""
    cfg = {
        "sonarr_url": servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "allowed_media_roots": [str(servers["media"])],
        "arr_path_map": servers["map"],
    }
    item = arr.search(_getter(cfg), "outlander").groups[0].items[0]
    assert item.allowed is True
    assert item.path == str(servers["ep1"])
    assert item.reason == ""


def test_an_older_sonarr_with_the_inline_episode_file_still_works(servers, monkeypatch):
    """Sonarr 3.x inlines `episodeFile`; that shape must keep working, and it must
    not cost a second call."""
    monkeypatch.setattr(_Sonarr, "episodes", [
        {"seasonNumber": 1, "episodeNumber": 1, "title": "Providence", "hasFile": True,
         "episodeFile": {"path": f"{TV_PATH}/S01E01.mkv"}},
    ])
    cfg = {
        "sonarr_url": servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "allowed_media_roots": [str(servers["media"])],
        "arr_path_map": servers["map"],
    }
    items = arr.search(_getter(cfg), "outlander").groups[0].items
    assert [i.path for i in items] == [str(servers["ep1"])]
    assert items[0].has_subtitle is True          # the .it.srt sidecar exists
