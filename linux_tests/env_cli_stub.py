# -*- coding: utf-8 -*-
"""Finto `core.env_check_cli` per i test del dialogo del modello di traduzione (nessun modello, nessun download).

`python env_cli_stub.py <comando>`; lo scenario dipende dalla variabile ENV_STUB_MODE:
  (assente/ok)  stampa righe di progresso ("⏳ ...") e di stato, exit 0
  fail          stampa una riga d'errore e termina con exit 1
  silent_fail   non stampa nulla e termina con exit 1
  slow          stampa una riga e attende 3 s"""
import os
import sys
import time


def out(line):
    sys.stdout.write(line + '\n')
    sys.stdout.flush()


def main():
    mode = os.environ.get('ENV_STUB_MODE', 'ok')
    sys.stderr.write('STUB_STDERR rumore\n')
    if mode == 'silent_fail':
        return 1
    if mode == 'fail':
        out('⏳ scarico…')
        out("❌ ultima riga d'errore")
        return 1
    if mode == 'slow':
        out('⏳ lento')
        time.sleep(3)
        return 0
    out('riga uno')
    out('⏳ scarico…')
    out('riga due')
    out('')
    out('riga tre')
    out('OK finale')
    return 0


if __name__ == '__main__':
    sys.exit(main())
