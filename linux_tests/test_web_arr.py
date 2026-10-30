# -*- coding: utf-8 -*-
"""Ricerca in Sonarr/Radarr (web/arr.py) con un server finto: mappa percorsi, stato sottotitoli, coda."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web import arr  # noqa: E402

SONARR_KEY = "k-sonarr-123"
RADARR_KEY = "k-radarr-456"


class _Server(ThreadingHTTPServer):
    """Daemon threads: un server finto non deve tenere vivo il processo a fine test."""
    daemon_threads = True
    allow_reuse_address = True


def _handler(server_path: str, episodes, movie_path: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):        # silenzio nei test
            pass

        def _send(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            key = self.headers.get("X-Api-Key")
            if self.path.startswith("/api/v3/series/lookup"):
                assert key == SONARR_KEY
                self._send([{"id": 7, "title": "Outlander - Blood of My Blood", "year": 2025}])
            elif self.path.startswith("/api/v3/episode"):
                assert key == SONARR_KEY
                assert "seriesId=7" in self.path
                self._send(episodes)
            elif self.path.startswith("/api/v3/movie/lookup"):
                assert key == RADARR_KEY
                self._send([{"id": 3, "title": "The Lost Leonardo", "year": 2021}])
            elif self.path.startswith("/api/v3/movie/3"):
                assert key == RADARR_KEY
                self._send({"id": 3, "title": "The Lost Leonardo", "year": 2021,
                            "movieFile": {"path": server_path}})
            else:                          # pragma: no cover
                self.send_response(404)
                self.end_headers()

    return Handler


@pytest.fixture
def fake_servers(tmp_path):
    """Due server finti (Sonarr e Radarr) con i percorsi come li vedrebbe il server."""
    media = tmp_path / "media"
    (media / "Show").mkdir(parents=True)
    ep1 = media / "Show" / "S01E01.mkv"
    ep2 = media / "Show" / "S01E02.mkv"
    for f in (ep1, ep2):
        f.write_text("x")
    (media / "Show" / "S01E01.it.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nCiao\n")

    episodes = [
        {"seasonNumber": 1, "episodeNumber": 1, "title": "Providence", "hasFile": True,
         "episodeFile": {"path": "/tv/Show/S01E01.mkv"}},
        {"seasonNumber": 1, "episodeNumber": 2, "title": "S.W.A.K.", "hasFile": True,
         "episodeFile": {"path": "/tv/Show/S01E02.mkv"}},
        {"seasonNumber": 1, "episodeNumber": 3, "title": "No file yet", "hasFile": False},
    ]
    movie = str(media / "Show" / "S01E02.mkv")

    # Sonarr e Radarr servono percorsi diversi: due server separati
    srv_sonarr = _Server(("127.0.0.1", 0), _handler("/tv/Show/S01E01.mkv", episodes, movie))
    srv_radarr = _Server(("127.0.0.1", 0), _handler(movie, episodes, movie))
    servers = [srv_sonarr, srv_radarr]
    for srv in servers:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
    yield {
        "media": media, "ep1": ep1, "ep2": ep2, "movie": Path(movie),
        "sonarr": f"http://127.0.0.1:{srv_sonarr.server_port}",
        "radarr": f"http://127.0.0.1:{srv_radarr.server_port}",
    }
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _getter(values):
    return lambda key, default=None: values.get(key, default)


def test_servers_need_url_and_key():
    assert arr.servers(_getter({"sonarr_url": "http://x:8989"})) == []
    assert len(arr.servers(_getter({"sonarr_url": "http://x:8989", "sonarr_api_key": "k"}))) == 1


def test_search_maps_paths_and_marks_subtitle_state(fake_servers):
    cfg = {
        "sonarr_url": fake_servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "allowed_media_roots": [str(fake_servers["media"])],
        "arr_path_map": f"/tv={fake_servers['media']}",
    }
    groups = arr.search(_getter(cfg), "outlander")
    assert len(groups) == 1
    group = groups[0]
    assert group.title.startswith("Outlander") and len(group.items) == 2   # l'episodio senza file è escluso
    by_code = {i.title: i for i in group.items}
    assert by_code["S01E01"].path == str(fake_servers["ep1"])
    assert by_code["S01E01"].has_subtitle is True          # il sidecar .it.srt esiste
    assert by_code["S01E02"].has_subtitle is False
    assert [i.title for i in group.missing] == ["S01E02"]  # solo quello senza sottotitoli


def test_paths_outside_the_roots_are_reported_not_queued(fake_servers):
    cfg = {
        "sonarr_url": fake_servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "allowed_media_roots": ["/nonexistent-root"],
        "arr_path_map": f"/tv={fake_servers['media']}",
    }
    item = arr.search(_getter(cfg), "outlander")[0].items[0]
    assert item.allowed is False and item.queueable is False
    assert "cartelle ammesse" in item.reason


def test_without_mapping_the_server_path_is_not_queueable(fake_servers):
    cfg = {
        "sonarr_url": fake_servers["sonarr"], "sonarr_api_key": SONARR_KEY,
        "allowed_media_roots": [str(fake_servers["media"])],
        "arr_path_map": "",                      # nessuna mappa
    }
    item = arr.search(_getter(cfg), "outlander")[0].items[0]
    assert item.allowed is False and "/tv/" in item.path


def test_movie_search_returns_one_file(fake_servers):
    cfg = {
        "radarr_url": fake_servers["radarr"], "radarr_api_key": RADARR_KEY,
        "allowed_media_roots": [str(fake_servers["media"])],
        "arr_path_map": f"/tv={fake_servers['media']}",
    }
    group = arr.search(_getter(cfg), "lost leonardo")[0]
    assert group.title == "The Lost Leonardo"
    assert group.items[0].path == str(fake_servers["movie"])
    assert group.items[0].allowed is True


def test_http_error_is_reported_without_the_key(fake_servers):
    cfg = {"sonarr_url": "http://127.0.0.1:1", "sonarr_api_key": "super-secret-key"}
    with pytest.raises(arr.ArrError) as exc:
        arr.search(_getter(cfg), "outlander")
    assert "super-secret-key" not in str(exc.value)
