# -*- coding: utf-8 -*-
"""utils/path_map.py: percorsi del server (UNC o lettera di unita') <-> cartelle montate localmente."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.path_map import parse_map, to_local, to_server  # noqa: E402

BS = chr(92)
UNC = BS * 2 + 'srv.example.lan' + BS + 'film'
TEXT = f"# commento\n{UNC}=/mnt/film\nV:{BS}=/mnt/v\n\nriga senza uguale\n{UNC}{BS}anime=/mnt/anime\n"


def test_parse_ignora_commenti_e_righe_non_valide_e_ordina_per_lunghezza():
    rules = parse_map(TEXT)
    assert [r[1] for r in rules] == ['/mnt/anime', '/mnt/film', '/mnt/v']
    assert parse_map('') == [] and parse_map(None) == []


def test_mappa_vuota_e_identita():
    p = 'V:' + BS + 'Film' + BS + 'X.mkv'
    assert to_local(p, []) == p and to_server(p, []) == p
    assert to_local('', parse_map(TEXT)) == ''


def test_unc_e_lettera_di_unita_verso_locale():
    rules = parse_map(TEXT)
    assert to_local(UNC + BS + 'Heat (1995)' + BS + 'Heat.mkv', rules) == '/mnt/film/Heat (1995)/Heat.mkv'
    assert to_local('V:' + BS + 'Serie' + BS + 'S01' + BS + 'a.mkv', rules) == '/mnt/v/Serie/S01/a.mkv'
    assert to_local('v:/Serie/a.mkv', rules) == '/mnt/v/Serie/a.mkv'                 # maiuscole e barre indifferenti
    assert to_local(UNC.upper() + BS + 'X.mkv', rules) == '/mnt/film/X.mkv'


def test_vince_il_prefisso_piu_lungo_e_i_confini_di_cartella():
    rules = parse_map(TEXT)
    assert to_local(UNC + BS + 'anime' + BS + 'Y.mkv', rules) == '/mnt/anime/Y.mkv'
    altro = BS * 2 + 'srv.example.lan' + BS + 'film2' + BS + 'Z.mkv'                    # film2 NON e' dentro film
    assert to_local(altro, rules) == altro


def test_verso_il_server_e_inverso_del_locale():
    rules = parse_map(TEXT)
    assert to_server('/mnt/film/Heat/Heat.mkv', rules) == UNC + BS + 'Heat' + BS + 'Heat.mkv'
    assert to_server('/mnt/v/Serie/a.mkv', rules) == 'V:' + BS + 'Serie' + BS + 'a.mkv'
    for srv in (UNC + BS + 'Heat' + BS + 'Heat.mkv', 'V:' + BS + 'Serie' + BS + 'a.mkv'):
        assert to_server(to_local(srv, rules), rules) == srv                           # andata e ritorno
    assert to_server('/home/u/altro.mkv', rules) == '/home/u/altro.mkv'                # fuori dalle regole: invariato


def test_to_server_con_lettera_di_unita_senza_barra_e_regole_con_lato_vuoto():
    rules = parse_map('V:=/mnt/v')
    assert to_server('/mnt/v/Serie/a.mkv', rules) == 'V:' + BS + 'Serie' + BS + 'a.mkv'
    assert parse_map('V:' + BS + '=/') == [] and parse_map('/=/mnt/x') == []       # un lato vuoto dopo la normalizzazione: scartata


def test_config_get_non_scarta_la_mappa_che_comincia_con_una_lettera_di_unita(monkeypatch):
    from utils import config as cfg
    monkeypatch.setattr(cfg, 'is_foreign_windows_path', lambda v: True)    # come su Linux
    c = cfg.Config.__new__(cfg.Config)
    c.settings = {'library_scanner_path_map': 'V:' + BS + '=/mnt/v', 'nllb_finetuned_model_path': 'D:' + BS + 'm'}
    assert c.get('library_scanner_path_map') == 'V:' + BS + '=/mnt/v'
    assert c.get('nllb_finetuned_model_path') == ''                         # un vero percorso Windows resta scartato
