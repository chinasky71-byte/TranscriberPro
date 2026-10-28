# -*- coding: utf-8 -*-
"""utils/gguf_download.py: scelta per VRAM (stesse soglie del selettore), download riprendibile con SHA-256, CLI.

Nessun download vero: un server HTTP locale finto (con e senza supporto a Range, con interruzioni a meta')."""
import hashlib
import http.server
import re
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import gguf_download as gd  # noqa: E402
from utils import gguf_quant  # noqa: E402

DATA = bytes(range(256)) * 4000          # ~1 MB, contenuto non banale
NAME = 'translategemma-12b-it-finale-IQ3_M.gguf'
ENTRY = gd.GGUFFile(NAME, len(DATA), hashlib.sha256(DATA).hexdigest())


class Server:
    """Serve DATA su /NAME. Opzioni: ranges (supporto a Range), cut_first (la prima risposta si interrompe a meta'),
    corrupt (restituisce byte sbagliati), code (risposta fissa di errore)."""

    def __init__(self, ranges=True, cut_first=False, corrupt=False, code=None):
        self.ranges, self.cut_first, self.corrupt, self.code = ranges, cut_first, corrupt, code
        self.requests = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                rng = self.headers.get('Range')
                outer.requests.append(rng)
                if outer.code:
                    self.send_error(outer.code)
                    return
                body = DATA if not outer.corrupt else b'x' * len(DATA)
                start = 0
                m = re.match(r'bytes=(\d+)-', rng or '')
                if m and outer.ranges:
                    start = int(m.group(1))
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
                else:
                    self.send_response(200)
                chunk = body[start:]
                self.send_header('Content-Length', str(len(chunk)))
                self.end_headers()
                if outer.cut_first and len(outer.requests) == 1:
                    self.wfile.write(chunk[:len(chunk) // 2])
                    self.wfile.flush()
                    self.connection.close()
                    return
                self.wfile.write(chunk)

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    made = []

    def make(**kw):
        s = Server(**kw)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


def go(srv, dest, **kw):
    return gd.download_file(srv.url, ENTRY, dest, sleep=lambda s: None, **kw)


# ------------------------------------------------------------------ scelta della quantizzazione
def test_resolve_choice():
    """ADR-009: non c'e' piu' una scelta per VRAM. 'auto' = la quantizzazione di default."""
    assert gd.resolve_choice('none') == (None, 'none')
    assert gd.resolve_choice('auto') == (gguf_quant.DEFAULT_QUANT, 'default')
    assert gd.resolve_choice('') == (gguf_quant.DEFAULT_QUANT, 'default')
    assert gd.resolve_choice('q3') == ('Q3_K_M', 'explicit')       # Q3_K_M solo se chiesta per nome
    assert gd.resolve_choice('iq3') == ('IQ3_M', 'explicit')
    assert gd.resolve_choice('q4') == ('Q4_K_M', 'explicit')
    # install.ps1 (linea Windows congelata): senza GPU non si scarica niente
    assert gd.resolve_choice('auto', no_gpu=True) == (None, 'no_gpu')
    with pytest.raises(ValueError):
        gd.resolve_choice('q9')


def test_la_quantizzazione_di_default_e_una_di_quelle_riconosciute():
    assert gguf_quant.DEFAULT_QUANT in gguf_quant.QUANT_WEIGHTS_GIB
    assert gd.MANIFEST[gguf_quant.DEFAULT_QUANT]


# ------------------------------------------------------------------ manifesto
def test_manifesto_valori_dichiarati_e_nomi_riconosciuti_dal_router():
    assert gd.MANIFEST['Q4_K_M'].size == 7300793824 and gd.MANIFEST['IQ3_M'].size == 5655737824
    assert gd.MANIFEST['Q3_K_M'].size == 6008833504
    for q, e in gd.MANIFEST.items():
        assert re.fullmatch(r'[0-9a-f]{64}', e.sha256)
        assert re.search(r'[-_.](' + '|'.join(gguf_quant.QUANT_PREFERENCE) + r')\.gguf$', e.name, re.I).group(1) == q
    assert set(gd.MANIFEST) == set(gguf_quant.QUANT_PREFERENCE)


def test_cartella_di_default_e_quella_del_motore():
    from core.llm_subtitle_translator import gguf_engine
    assert gd.DEFAULT_DEST == gguf_engine.DEFAULT_GGUF_DIR


# ------------------------------------------------------------------ download
def test_download_completo(server, tmp_path):
    s = server()
    assert go(s, tmp_path) == 'downloaded'
    assert (tmp_path / NAME).read_bytes() == DATA
    assert not (tmp_path / (NAME + '.part')).exists()


def test_gia_presente_non_scarica(server, tmp_path):
    s = server()
    go(s, tmp_path)
    s.requests.clear()
    assert go(s, tmp_path) == 'present' and s.requests == []


def test_interruzione_e_ripresa_nello_stesso_giro(server, tmp_path):
    s = server(cut_first=True)
    assert go(s, tmp_path) == 'downloaded'
    assert (tmp_path / NAME).read_bytes() == DATA
    assert s.requests[0] is None and re.match(r'bytes=\d+-$', s.requests[1])      # il secondo giro riprende con Range


def test_ripresa_da_un_parziale_di_un_giro_precedente(server, tmp_path):
    (tmp_path / (NAME + '.part')).write_bytes(DATA[:300000])
    s = server()
    assert go(s, tmp_path) == 'downloaded'
    assert (tmp_path / NAME).read_bytes() == DATA
    assert s.requests == ['bytes=300000-']


def test_server_senza_range_riparte_da_capo(server, tmp_path):
    (tmp_path / (NAME + '.part')).write_bytes(DATA[:300000])
    s = server(ranges=False)
    assert go(s, tmp_path) == 'downloaded'
    assert (tmp_path / NAME).read_bytes() == DATA


def test_parziale_gia_completo_si_verifica_e_si_rinomina(server, tmp_path):
    (tmp_path / (NAME + '.part')).write_bytes(DATA)
    s = server()
    assert go(s, tmp_path) == 'downloaded' and s.requests == []
    assert (tmp_path / NAME).read_bytes() == DATA


def test_parziale_piu_lungo_del_dovuto_si_scarta(server, tmp_path):
    (tmp_path / (NAME + '.part')).write_bytes(DATA + b'extra')
    assert go(server(), tmp_path) == 'downloaded'
    assert (tmp_path / NAME).read_bytes() == DATA


def test_sha256_sbagliato_non_lascia_un_file_valido(server, tmp_path):
    s = server(corrupt=True)
    with pytest.raises(gd.DownloadError):
        go(s, tmp_path, retries=1)
    assert not (tmp_path / NAME).exists()
    assert not (tmp_path / (NAME + '.part')).exists()      # il contenuto sbagliato non si riusa alla ripresa
    assert s.requests == [None, None]   # riprovato da zero una volta, poi basta (impronta deterministica)


def test_416_scarta_il_parziale_e_riparte(server, tmp_path):
    (tmp_path / (NAME + '.part')).write_bytes(DATA[:1000])
    s = server()
    orig = s.httpd.RequestHandlerClass.do_GET
    state = {'n': 0}

    def first_416(self):
        state['n'] += 1
        if state['n'] == 1:
            self.send_error(416)
            return
        orig(self)
    s.httpd.RequestHandlerClass.do_GET = first_416
    assert go(s, tmp_path) == 'downloaded'
    assert (tmp_path / NAME).read_bytes() == DATA


def test_rinomina_con_antivirus_che_trattiene_il_file(server, tmp_path, monkeypatch):
    real, n = gd.os.replace, {'n': 0}

    def flaky(a, b):
        n['n'] += 1
        if n['n'] < 3:
            raise PermissionError(32)
        real(a, b)
    monkeypatch.setattr(gd.os, 'replace', flaky)
    assert go(server(), tmp_path) == 'downloaded' and n['n'] == 3


def test_file_finale_diverso_viene_sostituito_solo_a_download_verificato(server, tmp_path):
    (tmp_path / NAME).write_bytes(b'versione precedente')
    assert go(server(), tmp_path) == 'replaced'
    assert (tmp_path / NAME).read_bytes() == DATA


def test_file_finale_diverso_resta_se_il_download_fallisce(server, tmp_path):
    (tmp_path / NAME).write_bytes(b'versione precedente')
    with pytest.raises(gd.DownloadError):
        go(server(corrupt=True), tmp_path, retries=1)
    assert (tmp_path / NAME).read_bytes() == b'versione precedente'


def test_manifesto_e_repository_in_un_solo_punto():
    for f in ('install.sh', 'install.ps1'):
        t = (ROOT / f).read_text(encoding='utf-8-sig')
        assert 'translategemma-12b-it-subtitles-gguf' not in t and 'finale-Q4_K_M' not in t
        for e in gd.MANIFEST.values():
            assert e.sha256 not in t and str(e.size) not in t


@pytest.mark.parametrize('code', [403, 404])
def test_errore_http_definitivo_senza_ritentare(server, tmp_path, code):
    s = server(code=code)
    with pytest.raises(gd.DownloadError):
        go(s, tmp_path)
    assert len(s.requests) == 1 and not (tmp_path / NAME).exists()


def test_rete_assente_errore_chiaro_dopo_i_tentativi(tmp_path):
    with pytest.raises(gd.DownloadError):
        gd.download_file('http://127.0.0.1:9', ENTRY, tmp_path, retries=1, timeout=2, sleep=lambda s: None)
    assert not (tmp_path / NAME).exists()


def test_disco_insufficiente(server, tmp_path, monkeypatch):
    monkeypatch.setattr(gd.shutil, 'disk_usage', lambda p: type('U', (), {'free': 10})())
    s = server()
    with pytest.raises(gd.DownloadError):
        go(s, tmp_path)
    assert s.requests == []


# ------------------------------------------------------------------ CLI
@pytest.fixture
def cli(server, tmp_path, monkeypatch):
    monkeypatch.setitem(gd.MANIFEST, 'IQ3_M', ENTRY)
    s = server()

    def run(*args, tty=False, answers=(), capsys=None):
        it = iter(answers)
        rc = gd.main(['--dest', str(tmp_path), '--base-url', s.url, *args],
                     input_fn=lambda prompt: next(it), is_tty=tty, sleep=lambda x: None)
        return rc
    run.server, run.dest = s, tmp_path
    return run


def test_cli_senza_conferma_e_senza_terminale_non_scarica(cli):
    assert cli('--gguf', 'auto') == 0
    assert cli.server.requests == [] and not (cli.dest / NAME).exists()


def test_cli_dry_run_non_scarica(cli):
    assert cli('--gguf', 'auto', '--yes', '--dry-run') == 0
    assert cli.server.requests == []


def test_cli_yes_scarica_la_quant_giusta(cli):
    assert cli('--gguf', 'iq3', '--yes') == 0
    assert (cli.dest / NAME).read_bytes() == DATA


def test_cli_domanda_si_e_no(cli):
    assert cli('--gguf', 'iq3', tty=True, answers=['n']) == 0 and cli.server.requests == []
    assert cli('--gguf', 'iq3', tty=True, answers=['s']) == 0 and (cli.dest / NAME).exists()


def test_cli_none_e_senza_gpu_non_scaricano(cli, capsys):
    assert cli('--gguf', 'none', '--yes') == 0
    assert cli('--gguf', 'auto', '--yes', '--no-gpu') == 0
    assert cli.server.requests == []


def test_cli_errore_restituisce_1(server, tmp_path, monkeypatch):
    monkeypatch.setitem(gd.MANIFEST, 'IQ3_M', ENTRY)
    s = server(code=404)
    rc = gd.main(['--dest', str(tmp_path), '--base-url', s.url, '--gguf', 'iq3', '--yes'])
    assert rc == 1


def test_cli_argomenti_errati():
    assert gd.main(['--gguf', 'q9']) == 2


def test_l_installer_non_legge_ne_scrive_la_configurazione():
    src = (ROOT / 'utils' / 'gguf_download.py').read_text(encoding='utf-8')
    assert 'get_config' not in src and 'config.json' not in src and 'utils.config' not in src


def test_tutte_le_chiavi_gd_esistono_in_en_e_it():
    """`_tr` non e' `tr`: lo scanner delle chiavi non le vede, quindi qui. (Una modifica di translations.py le aveva perse in 1.34.30.)"""
    from utils.translations import Translations as T
    src = (ROOT / 'utils' / 'gguf_download.py').read_text(encoding='utf-8')
    keys = set(re.findall(r"_tr\('(gd_[a-z_0-9]+)'", src)) | {'gd_none_' + w for w in ('none', 'no_gpu')}
    keys |= {'gd_present', 'gd_done', 'gd_replaced'}
    keys.discard('gd_none_')
    for lang in ('en', 'it'):
        assert sorted(k for k in keys if k not in T.TEXTS[lang]) == []


def test_rinomina_sempre_negata_lascia_il_vecchio_file(server, tmp_path, monkeypatch):
    (tmp_path / NAME).write_bytes(b'versione precedente')

    def denied(a, b):
        raise PermissionError(32)
    monkeypatch.setattr(gd.os, 'replace', denied)
    with pytest.raises(gd.DownloadError):
        go(server(), tmp_path)
    assert (tmp_path / NAME).read_bytes() == b'versione precedente'
