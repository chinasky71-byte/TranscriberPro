"""
Quanta VRAM consuma davvero ogni motore, e a che batch comincia a sbordare
=========================================================================
Su Windows la scheda non va mai in OOM: il driver WDDM, quando la memoria
dedicata finisce, continua ad allocare nella RAM di sistema ("shared GPU
memory"). Non arriva nessun errore — arriva solo un rallentamento di 4-5 volte,
che è esattamente il guasto silenzioso già visto sul batch adattivo di NLLB.

Per questo la misura che conta NON è `torch.cuda.max_memory_allocated()`, che
vede solo il lato PyTorch, ma la coppia:

  - memoria DEDICATA usata sull'adattatore (nvidia-smi)
  - memoria CONDIVISA usata sull'adattatore (contatore prestazioni Windows,
    `\\GPU Adapter Memory(*)\\Shared Usage`) -> se sale sopra zero, si è sbordati

Lo script prova ogni modello a batch crescenti sugli stessi blocchi e riporta i
picchi, così i limiti per modello si scelgono su un numero e non a intuito.

Uso:
    venv\\Scripts\\python mt_eval\\vram_probe.py --model translategemma-12b
    venv\\Scripts\\python mt_eval\\vram_probe.py --model aya-expanse-8b --batches 4,8,12,16
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

GB = 1024.0 ** 3


# --------------------------------------------------------------------------
# Lettura dei due contatori di memoria dell'adattatore
# --------------------------------------------------------------------------
def dedicated_mib():
    """Memoria dedicata occupata sulla scheda, secondo il driver."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return -1


_PS_SHARED = (
    "$c = Get-Counter '\\GPU Adapter Memory(*)\\Shared Usage' "
    "-ErrorAction SilentlyContinue; "
    "if ($c) { ($c.CounterSamples | Measure-Object -Property CookedValue "
    "-Sum).Sum } else { 0 }"
)


def shared_mib():
    """Memoria di sistema requisita dalla GPU: sopra zero significa spillover.

    Il contatore è per-adattatore e per-processo insieme; si somma tutto perché
    quello che interessa è se la scheda ha dovuto uscire dalla propria memoria,
    non quale processo l'abbia fatto.
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _PS_SHARED],
            capture_output=True, text=True, timeout=25)
        val = out.stdout.strip().replace(",", ".")
        return int(float(val) / 1024 / 1024) if val else -1
    except Exception:
        return -1


class PeakWatcher(threading.Thread):
    """Campiona i due contatori mentre la generazione è in corso.

    Serve un campionamento continuo: il picco dura una frazione di secondo,
    dentro `generate()`, e una lettura prima-e-dopo non lo vedrebbe mai.
    """

    def __init__(self, interval=0.4):
        super().__init__(daemon=True)
        self.interval = interval
        self.stop_flag = threading.Event()
        self.peak_ded = 0
        self.peak_shared = 0
        self.base_shared = max(0, shared_mib())

    def run(self):
        while not self.stop_flag.is_set():
            d = dedicated_mib()
            if d > self.peak_ded:
                self.peak_ded = d
            s = shared_mib()
            if s > self.peak_shared:
                self.peak_shared = s
            self.stop_flag.wait(self.interval)

    def stop(self):
        self.stop_flag.set()
        self.join(timeout=5)


# --------------------------------------------------------------------------
def load_blocks(path, n):
    p = path if os.path.isabs(path) else os.path.join(SCRIPT_DIR, path)
    items = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    # I blocchi lunghi sono il caso peggiore: più token in ingresso e in uscita
    # significa KV cache più grande, ed è lì che si sborda.
    return sorted(items, key=lambda d: -len(d["source"]))[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="translategemma-12b")
    ap.add_argument("--batches", default="4,8,12,16")
    ap.add_argument("--set", default="filmset_deadpool2_sample.jsonl")
    ap.add_argument("--n", type=int, default=48)
    args = ap.parse_args()

    batches = [int(b) for b in args.batches.split(",") if b.strip()]
    items = load_blocks(args.set, args.n)

    print(f"Riposo: dedicata {dedicated_mib()} MiB | "
          f"condivisa {shared_mib()} MiB\n")

    import torch
    from core.llm_subtitle_translator.engine import get_engine, unload_engine

    engine = get_engine(args.model, log_callback=lambda m: print(f"  {m}"))
    spec = engine.spec
    torch.cuda.reset_peak_memory_stats()
    after_load_ded = dedicated_mib()
    print(f"\nCaricato: dedicata {after_load_ded} MiB | "
          f"pesi PyTorch {torch.cuda.memory_allocated() / GB:.2f} GB\n")

    rows = []
    for bs in batches:
        chunk = items[:bs]
        torch.cuda.reset_peak_memory_stats()
        w = PeakWatcher()
        w.start()
        t0 = time.time()
        try:
            if spec.prompt_style == "mt":
                convs = [engine.mt_messages(d["source"]) for d in chunk]
                engine.generate(convs, max_new_tokens=160)
            else:
                # Percorso "adapt": un solo prompt con tutti i blocchi dentro.
                from core.llm_subtitle_translator.prompt_builder import (
                    SubtitleUnit, build_messages)
                units = [SubtitleUnit(id=d["id"], text=d["source"],
                                      duration=3.0) for d in chunk]
                engine.generate([build_messages(units)],
                                max_new_tokens=90 * bs)
            err = ""
        except Exception as exc:
            err = type(exc).__name__
        el = time.time() - t0
        w.stop()
        torch_peak = torch.cuda.max_memory_reserved() / GB
        spill = max(0, w.peak_shared - w.base_shared)
        rows.append((bs, w.peak_ded, torch_peak, spill, el, err))
        print(f"  batch {bs:>3} | dedicata picco {w.peak_ded:>6} MiB | "
              f"torch reserved {torch_peak:5.2f} GB | "
              f"spillover {spill:>5} MiB | {el:5.1f}s {err}")

    unload_engine()

    total = 12288
    print(f"\n{'=' * 74}")
    print(f"  {spec.label} — scheda da {total} MiB")
    print(f"  {'batch':>6}{'dedicata':>11}{'% scheda':>10}"
          f"{'spillover':>12}{'tempo':>9}{'per blocco':>12}")
    print(f"  {'-' * 66}")
    for bs, ded, tp, spill, el, err in rows:
        flag = "  <- SBORDA" if spill > 64 else ""
        print(f"  {bs:>6}{ded:>11}{ded * 100.0 / total:>9.0f}%"
              f"{spill:>12}{el:>8.1f}s{el / bs:>11.2f}s{flag}")
    print(f"{'=' * 74}")
    print("  Il batch consigliato è il più grande che tiene lo spillover a")
    print("  zero: oltre, il tempo per blocco smette di scendere e risale.")


if __name__ == "__main__":
    main()
