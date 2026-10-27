# -*- coding: utf-8 -*-
"""Finto server Library Scanner (stdlib, in-process) per i test di G4: registra ogni richiesta e risponde con dati configurabili."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class FakeLibraryScanner:
    def __init__(self):
        self.requests = []                 # (metodo, percorso, query dict, headers dict, corpo json o None)
        self.routes = {}                   # (metodo, percorso) -> (status, payload, ritardo_s)
        self.default = (404, {'error': 'no route'}, 0)
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self, method):
                u = urlparse(self.path)
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(n).decode('utf-8')) if n else None
                owner.requests.append((method, u.path, {k: v[0] for k, v in parse_qs(u.query).items()},
                                       {k.lower(): v for k, v in self.headers.items()}, body))
                status, payload, delay = owner.routes.get((method, u.path), owner.default)
                if delay:
                    time.sleep(delay)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def do_GET(self):
                self._handle('GET')

            def do_POST(self):
                self._handle('POST')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def route(self, method, path, payload, status=200, delay=0):
        self.routes[(method, path)] = (status, payload, delay)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
