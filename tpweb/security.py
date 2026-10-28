# -*- coding: utf-8 -*-
"""Protezioni del server locale (decisioni 3 del piano: solo 127.0.0.1, nessun accesso da altri dispositivi).

  - `Host` ammesso solo 127.0.0.1:<porta> / localhost:<porta> (anti DNS rebinding);
  - sessione = token casuale: il primo accesso `/?t=<token>` imposta un cookie HttpOnly SameSite=Strict e rimanda a `/`;
    ogni altra richiesta richiede il cookie (o l'intestazione X-TP-Token);
  - metodi non sicuri: `Origin` assente (client non-browser con X-TP-Token) oppure uguale all'origine del server;
  - nessun CORS; intestazioni di sicurezza; nessuna cache.
Provate da linux_tests/test_tpweb_security.py."""
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

COOKIE = 'tp_session'
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"


def install_guard(app: FastAPI, token: str, port: int) -> None:
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    allowed_origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}

    @app.middleware('http')
    async def guard(request: Request, call_next):
        if request.headers.get('host', '') not in allowed_hosts:
            return JSONResponse({'error': 'host non ammesso'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({'error': 'origin non ammessa'}, status_code=403)
        if request.method == 'OPTIONS':
            return JSONResponse({'error': 'CORS non supportato'}, status_code=405)
        if request.url.path == '/' and request.query_params.get('t') is not None:
            if secrets.compare_digest(request.query_params['t'], token):
                r = RedirectResponse('/', status_code=303)
                r.set_cookie(COOKIE, token, httponly=True, samesite='strict', path='/')
                return r
            return JSONResponse({'error': 'token errato'}, status_code=401)
        sent = request.cookies.get(COOKIE) or request.headers.get('x-tp-token') or ''
        if not secrets.compare_digest(sent, token):
            return JSONResponse({'error': 'non autorizzato'}, status_code=401)
        resp = await call_next(request)
        resp.headers['Cache-Control'] = 'no-store'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        resp.headers['Content-Security-Policy'] = CSP
        return resp
