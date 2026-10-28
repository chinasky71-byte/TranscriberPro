# -*- coding: utf-8 -*-
"""Finto `core/glossary_builder_cli.py` per i test del server web: come glossary_stub_cli.py ma scrive un vero report.json.
Scenari dal campo `name`: ok (due candidati), gateko (gate insufficiente, nessun candidato), badreport (report non JSON), slow (60 s), err."""
import json
import sys
import time
from pathlib import Path


def ev(**kw):
    sys.stdout.write(json.dumps(kw, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    args_path = Path(sys.argv[1])
    args = json.loads(args_path.read_text(encoding='utf-8'))
    name = args['name']
    rep = args_path.parent / 'report.json'
    ev(ev='log', msg='avvio ' + name)
    if name.startswith('slow'):
        ev(ev='log', msg='STUB_SLOW_STARTED')
        time.sleep(60)
        return 0
    if name.startswith('err'):
        ev(ev='error', msg='qualcosa e andato storto')
        return 1
    ev(ev='gate', ok=not name.startswith('gateko'), blocks=7000, need_blocks=6000)
    ev(ev='progress', phase='align', done=1, total=4, msg='uno')
    if name.startswith('badreport'):
        rep.write_text('non json', encoding='utf-8')
    elif name.startswith('gateko'):
        rep.write_text(json.dumps({'gate': {'ok': False, 'blocks': 100, 'need_blocks': 6000}, 'candidates': []}), encoding='utf-8')
    else:
        rep.write_text(json.dumps({'gate': {'ok': True}, 'tmdb_id': args.get('tmdb_id'), 'episodes_used': [[1, 1], [1, 2]],
                                   'candidates': [{'term': 'Winterfell', 'dominant': 'Grande Inverno', 'status': 'auto', 'occurrences': 12,
                                                   'clusters': [{'text': 'Grande Inverno', 'n': 9, 'examples': [{'en': 'a', 'it': 'b'}]}]},
                                                  {'term': 'Raven', 'dominant': 'Corvo', 'status': 'review', 'occurrences': 5, 'clusters': []}]}),
                       encoding='utf-8')
    ev(ev='log', msg='fine')
    ev(ev='done', report=str(rep))
    return 0


if __name__ == '__main__':
    sys.exit(main())
