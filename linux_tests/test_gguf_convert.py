# -*- coding: utf-8 -*-
"""scripts_manutenzione/gguf_convert.py: funzioni pure (comandi, corpus, intestazione GGUF). Nessun modello, nessun llama.cpp."""
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts_manutenzione'))

import pytest  # noqa: E402

import gguf_convert as gc  # noqa: E402
from utils import translator_path_select as sel  # noqa: E402


def _s(x: str) -> bytes:
    b = x.encode()
    return struct.pack('<Q', len(b)) + b


def make_gguf(path, arch='gemma3', ftype=12, template=None):
    kv = [(b'general.architecture', 8, _s(arch)), (b'general.file_type', 4, struct.pack('<I', ftype)),
          (b'general.alignment', 4, struct.pack('<I', 32)),
          (b'tokenizer.ggml.scores', 9, struct.pack('<IQ', 6, 2) + struct.pack('<ff', 0.0, 1.0))]
    if template:
        kv.append((b'tokenizer.chat_template', 8, _s(template)))
    body = b''.join(struct.pack('<Q', len(k)) + k + struct.pack('<I', t) + v for k, t, v in kv)
    Path(path).write_bytes(b'GGUF' + struct.pack('<IQQ', 3, 7, len(kv)) + body)


def test_read_gguf_meta(tmp_path):
    p = tmp_path / 'm.gguf'
    make_gguf(p, 'gemma3', 12, 'tpl')
    m = gc.read_gguf_meta(p)
    assert m['general.architecture'] == 'gemma3' and m['quant'] == 'Q3_K_M' and m['n_tensors'] == 7
    assert m['tokenizer.chat_template'] == 'tpl' and m['size_bytes'] == p.stat().st_size
    make_gguf(p, 'qwen2', 27)
    m = gc.read_gguf_meta(p)
    assert m['quant'] == 'IQ3_M' and 'tokenizer.chat_template' not in m


def test_read_gguf_meta_rifiuta_file_non_gguf(tmp_path):
    (tmp_path / 'x').write_bytes(b'nope')
    with pytest.raises(ValueError):
        gc.read_gguf_meta(tmp_path / 'x')


def test_nomi_file_riconosciuti_dal_router(tmp_path):
    from core.llm_subtitle_translator import path_router as pr
    for q in gc.DEFAULT_QUANTS:
        (tmp_path / gc.quant_filename('translategemma-12b-it-finale', q)).write_bytes(b'x')
    assert set(pr.scan_gguf_dir(tmp_path)) == set(gc.DEFAULT_QUANTS) == set(sel.QUANT_PREFERENCE)


def test_comandi():
    c = gc.build_convert_cmd('/m', '/o/f16.gguf', '/llama.cpp', 'f16', python='py')
    assert gc.build_convert_cmd('/m', 'o', '/l')[-1] == 'bf16'
    assert c == ['py', str(Path('/llama.cpp/convert_hf_to_gguf.py')), '/m', '--outfile', '/o/f16.gguf', '--outtype', 'f16']
    q = gc.build_quantize_cmd('/llama.cpp', 'a.gguf', 'b.gguf', 'IQ3_M', imatrix='im.gguf', threads=8, binary='lq')
    assert q == ['lq', '--imatrix', 'im.gguf', 'a.gguf', 'b.gguf', 'IQ3_M', '8']
    assert gc.build_quantize_cmd('/l', 'a', 'b', 'Q4_K_M', binary='lq') == ['lq', 'a', 'b', 'Q4_K_M']
    i = gc.build_imatrix_cmd('/l', 'm.gguf', 'c.txt', 'o.gguf', ngl=20, ctx=512, binary='li')
    assert i == ['li', '-m', 'm.gguf', '-f', 'c.txt', '-o', 'o.gguf', '-c', '512', '-ngl', '20', '--parse-special']


def test_parse_pairs_e_corpus():
    txt = "Hello.\tCiao.\nsolo inglese\n\tsolo italiano\nLine one\\nLine two\tUno\\nDue\nBye\tAddio\n"
    pairs = gc.parse_pairs(txt)
    assert pairs == [('Hello.', 'Ciao.'), ('Line one\nLine two', 'Uno\nDue'), ('Bye', 'Addio')]
    assert gc.parse_pairs(txt, max_pairs=1) == [('Hello.', 'Ciao.')]
    out = gc.corpus_from_pairs(pairs[:1], lambda en: f'<P:{en}>')
    assert out == '<P:Hello.>Ciao.<end_of_turn>\n'


def test_corpus_usa_il_prompt_del_motore():
    from core.llm_subtitle_translator.engine import SubtitleLLMEngine
    from core.llm_subtitle_translator.gguf_engine import render_prompt
    eng = SubtitleLLMEngine('translategemma-12b')
    out = gc.corpus_from_pairs([('Hello.', 'Ciao.')], lambda en: render_prompt(eng.mt_messages(en)))
    assert out.startswith('<bos><start_of_turn>user\nYou are a professional English (en) to Italian (it)')
    assert out.endswith('Hello.<end_of_turn>\n<start_of_turn>model\nCiao.<end_of_turn>\n')


def test_stime_coerenti_con_le_dimensioni_dichiarate():
    r = gc.estimate_resources()
    assert 21 < r['f16_gib'] < 24                                 # "~24 GB" decimali
    # i GB dichiarati nell'incarico (7,3 / 5,9 / 5,4) sono decimali: in GiB le stime sono piu' basse, quindi quelle del selettore
    # (che le usa come GiB) sono prudenti
    for q, declared in (('Q4_K_M', 7.3), ('Q3_K_M', 5.9), ('IQ3_M', 5.4)):
        assert r['sizes_gib'][q] <= sel.QUANT_WEIGHTS_GIB[q] + 0.1
        assert abs(r['sizes_gib'][q] * 1.0737 - declared) < 0.7
    assert r['disk_gib'] > 50


def test_quantize_iq3_senza_imatrix_avvisa_non_rifiuta(tmp_path, capsys):
    gc.main(['quantize', '--llama-cpp', str(tmp_path), '--gguf', str(tmp_path / 'x-bf16.gguf'),
             '--outdir', str(tmp_path / 'o'), '--quants', 'IQ3_M', '--dry-run'])
    out = capsys.readouterr().out
    assert 'ATTENZIONE' in out and 'x-IQ3_M.gguf' in out


def test_quantize_dry_run_nomi(tmp_path, capsys):
    gc.main(['quantize', '--llama-cpp', str(tmp_path), '--gguf', str(tmp_path / 'tg-f16.gguf'), '--outdir', str(tmp_path / 'o'),
             '--quants', 'Q4_K_M,IQ3_M', '--imatrix', 'im.gguf', '--dry-run'])
    out = capsys.readouterr().out
    assert 'tg-Q4_K_M.gguf' in out and 'tg-IQ3_M.gguf' in out and '--imatrix' in out


def test_convert_chiede_il_vocabolario(tmp_path):
    (tmp_path / 'config.json').write_text('{}')
    with pytest.raises(SystemExit) as e:
        gc.main(['convert', '--model', str(tmp_path), '--llama-cpp', str(tmp_path), '--out', str(tmp_path / 'o.gguf'), '--dry-run'])
    assert 'tokenizer.model' in str(e.value)


def test_plan_stampa_il_commit_di_llama_cpp(capsys):
    gc.main(['plan'])
    out = capsys.readouterr().out
    assert gc.LLAMA_CPP_COMMIT in out and 'IQ3_M' in out


def test_find_binary_cerca_anche_release(tmp_path):
    exe = 'llama-quantize' + ('.exe' if os.name == 'nt' else '')
    d = tmp_path / 'build' / 'bin' / 'Release'
    d.mkdir(parents=True)
    (d / exe).write_bytes(b'x')
    assert gc.find_binary(tmp_path, 'llama-quantize') == str(d / exe)
    assert gc.find_binary(tmp_path / 'altro', 'llama-quantize').endswith(os.path.join('build', 'bin', exe))


def test_binario_mancante_errore_chiaro(tmp_path):
    with pytest.raises(SystemExit) as e:
        gc._run([str(tmp_path / 'llama-quantize'), 'x'])
    assert 'compila llama.cpp' in str(e.value)


def test_verify_segnala_nome_che_non_corrisponde(tmp_path, capsys):
    p = tmp_path / 'tg-Q3_K_M.gguf'
    make_gguf(p, 'gemma3', 27)                                     # dentro c'e' IQ3_M
    with pytest.raises(SystemExit) as e:
        gc.main(['verify', str(p)])
    assert e.value.code == 1 and 'il nome dice Q3_K_M' in capsys.readouterr().out


def test_stem_toglie_il_suffisso_bf16(tmp_path, capsys):
    gc.main(['quantize', '--llama-cpp', str(tmp_path), '--gguf', str(tmp_path / 'tg-bf16.gguf'), '--outdir', str(tmp_path / 'o'),
             '--quants', 'Q4_K_M', '--dry-run'])
    assert 'tg-Q4_K_M.gguf' in capsys.readouterr().out


def test_corpus_poche_coppie_rifiutato(tmp_path):
    (tmp_path / 'p.tsv').write_text('a\tb\n' * 10, encoding='utf-8')
    with pytest.raises(SystemExit) as e:
        gc.main(['corpus', '--pairs', str(tmp_path / 'p.tsv'), '--out', str(tmp_path / 'c.txt')])
    assert 'coppie' in str(e.value)


def test_read_gguf_meta_versione_non_supportata(tmp_path):
    (tmp_path / 'v.gguf').write_bytes(b'GGUF' + struct.pack('<IQQ', 99, 0, 0))
    with pytest.raises(ValueError):
        gc.read_gguf_meta(tmp_path / 'v.gguf')
