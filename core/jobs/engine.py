# -*- coding: utf-8 -*-
"""QueueEngine: il ciclo della coda di elaborazione, senza Qt e senza GUI.

E' la trasposizione di `ProcessingWorker.run()` e del suo `_process_single_file_subprocess()` (gui/workers.py): prende i file da
una `JobQueue` uno alla volta, li elabora con `FileRunner` (un sottoprocesso `core.pipeline_cli` per file), conta completati e
falliti, calcola l'avanzamento, produce anteprima dei passi e voce di cronologia, e a coda conclusa ripulisce le cache.

Chi lo usa non eredita nulla: passa un `QueueListener` con i ganci che gli servono.
  - GUI: `ProcessingWorker` (QThread) esegue `run()` nel suo thread e trasforma ogni gancio in un segnale Qt (stessi 11 segnali).
  - Headless: `core/queue_runner.py` esegue `run()` nel thread principale e trasforma i ganci in file di stato, log e cronologia.
I testi per l'utente sono gli stessi (tr()) per tutti: i log della coda headless sono quelli della GUI.

Interruzione: `cancel()` da un altro thread (la GUI). KeyboardInterrupt (Ctrl+C del headless) NON si cattura: il runner uccide
l'albero del figlio e l'eccezione risale a chi ha chiamato `run()`.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.jobs.file_progress import FileProgress
from core.jobs.file_runner import FileHooks, FileRunner
from core.jobs.job_queue import JobQueue
from utils.logger import setup_logger
from utils.translations import tr

logger = setup_logger()


class QueueListener:
    """Ganci della coda. Tutti facoltativi, tutti chiamati nel thread che esegue `QueueEngine.run()`."""

    def on_log(self, text: str) -> None:
        """Riga di log per l'utente (le intestazioni dei file contengono a capo)."""

    def on_progress(self, percent: int) -> None:
        """Avanzamento complessivo della coda (file elaborati / totale iniziale), 0..100."""

    def on_file_started(self, path: str) -> None: ...

    def on_file_progress(self, path: str, percent: int) -> None:
        """Percentuale del file in lavorazione (solo quando aumenta)."""

    def on_file_steps(self, path: str, snapshot) -> None:
        """Anteprima dei passi (PipelineSnapshot, immutabile)."""

    def on_file_completed(self, path: str) -> None: ...

    def on_file_failed(self, path: str) -> None: ...

    def on_file_error(self, path: str, message: str) -> None:
        """Motivo breve di un fallimento (prima di on_file_failed): 'exit code 1', errore di avvio, file inesistente."""

    def on_history(self, entry: dict) -> None:
        """Voce di cronologia di un file completato."""

    def on_queue_updated(self, remaining: int) -> None: ...

    def on_finished(self) -> None: ...


# Livello di una riga di log (solo per chi vuole farla precedere da una etichetta, come il log della coda headless): regola unica,
# sul primo carattere significativo. Il testo della riga NON cambia mai.
def level_of(text: str) -> str:
    s = (text or '').lstrip()
    if s.startswith(('❌', '🛑', '⛔', '🚫')):
        return 'ERROR'
    if s.startswith(('⚠', '⏹')):
        return 'WARNING'
    return 'INFO'


class QueueEngine:
    def __init__(self, queue: JobQueue, listener: Optional[QueueListener] = None, *, cleanup_caches: bool = True,
                 check_exists: bool = False, project_root: Optional[Path] = None):
        self.queue = queue
        self.listener = listener or QueueListener()
        self.cleanup_caches = cleanup_caches
        self.check_exists = check_exists       # True: un file inesistente fallisce subito, senza lanciare il figlio
        self.project_root = project_root
        self.is_cancelled = False
        self.completed_files = 0
        self.failed_files = 0
        self.total_files_at_start = 0
        self._runner: Optional[FileRunner] = None

    # ----------------------------------------------------------------------------------------------------------- controllo
    def note_removed(self, n: int = 1) -> None:
        """Un file ancora in attesa e' stato tolto dalla coda mentre il motore lavora: il totale usato per la percentuale e per
        l'intestazione 'File N/totale' scende di n (altrimenti la barra non arriva piu' al 100%)."""
        self.total_files_at_start = max(1, self.total_files_at_start - n)

    def cancel(self) -> None:
        """Dal thread chiamante (GUI): segna e uccide l'albero del figlio in corso."""
        self.is_cancelled = True
        runner = self._runner
        if runner is not None:
            runner.cancel()

    # --------------------------------------------------------------------------------------------------------------- ciclo
    def run(self) -> None:
        L = self.listener
        # Salva il totale iniziale per statistiche
        self.total_files_at_start = len(self.queue)
        L.on_log(tr('worker_start').format(n=self.total_files_at_start))

        # Loop dinamico: prende e rimuove atomicamente il primo file; si possono aggiungere/togliere/riordinare file mentre lavora
        while not self.is_cancelled:
            item = self.queue.take_next()
            if item is None:
                break
            video_path, overrides = item
            filename = Path(video_path).name
            files_processed = self.completed_files + self.failed_files

            L.on_log(
                f"\n{'='*70}\n"
                f"{tr('worker_file_header').format(current=files_processed+1, total=self.total_files_at_start, filename=filename)}\n"
                f"{'='*70}"
            )
            L.on_file_started(video_path)

            success = self._process_file(video_path, overrides)

            if success:
                self.completed_files += 1
                L.on_file_completed(video_path)
            else:
                self.failed_files += 1
                L.on_file_failed(video_path)

            files_processed = self.completed_files + self.failed_files
            L.on_progress(min(100, int((files_processed / self.total_files_at_start) * 100)))
            L.on_queue_updated(len(self.queue))

        if self.is_cancelled:
            L.on_log(tr('worker_cancelled_user'))
        else:
            L.on_log(
                f"\n{'='*70}\n"
                f"{tr('worker_done_header')}\n"
                f"{tr('worker_stats_completed').format(n=self.completed_files)}\n"
                f"{tr('worker_stats_failed').format(n=self.failed_files)}\n"
                f"{tr('worker_stats_total').format(n=self.completed_files + self.failed_files)}\n"
                f"{'='*70}"
            )

        # Cache modelli HF/torch: pulizia UNA volta sola, a coda conclusa (fine naturale o "Ferma"). Prima stava in
        # pipeline._cleanup() e girava a ogni file, riscaricando gli stessi modelli decine di volte. cache_cleaner importa solo
        # shutil/pathlib (e in modo lazy config/engine dell'LLM, senza torch): nessun costo ML nel processo chiamante.
        if self.cleanup_caches:
            self._cleanup_caches()

        L.on_finished()

    def _cleanup_caches(self) -> None:
        try:
            from utils.cache_cleaner import cleanup_non_italian_caches

            def _cache_log(m):
                self.listener.on_log(m)    # log a schermo
                logger.info(m)             # e nel file di log

            res = cleanup_non_italian_caches(log_callback=_cache_log)
            if res['removed']:
                _cache_log(f"🗑️ Cache modelli liberata a fine coda: {len(res['removed'])} elementi")
            if res['failed']:
                logger.warning(f"Cache cleanup parziale: {len(res['failed'])} elementi non rimossi")
        except Exception as e:
            logger.warning(f"Errore cache cleanup a fine coda: {e}")

    # -------------------------------------------------------------------------------------------------------- un file
    def _process_file(self, video_path: str, overrides: dict) -> bool:
        """Un file che solleva un'eccezione non ferma la coda: il file fallisce, con il motivo nel log. (KeyboardInterrupt no.)"""
        try:
            return self._process_file_inner(video_path, overrides)
        except Exception as exc:
            logger.error(f"Errore elaborando {video_path}: {exc}", exc_info=True)
            self.listener.on_log(tr('worker_critical_error').format(filename=Path(video_path).name, error=str(exc)))
            self.listener.on_file_error(video_path, f'{type(exc).__name__}: {exc}')
            return False

    def _process_file_inner(self, video_path: str, overrides: dict) -> bool:
        """Elabora un file in un subprocess ISOLATO (core.pipeline_cli): l'isolamento evita l'accumulo di RAM su code lunghe
        (ogni film gira in un processo che muore a fine elaborazione) e tiene torch fuori dal processo chiamante."""
        L = self.listener
        filename = Path(video_path).name

        from utils.config import get_config
        from utils.job_overrides import clean as _clean_ov
        overrides = _clean_ov(overrides)
        target_language = overrides.get('target_language') or get_config().get_target_language()
        # Avanzamento del file: fasi pesate per durata reale + barra interna di fase (core/jobs/file_progress.py).
        file_progress = FileProgress(target_language)
        # Anteprima dei passi (Log Sintetico): gira SEMPRE, cosi' spuntando la casella a meta' file lo stato e' gia' vero.
        from core.jobs.step_plan import StepTracker, PlanOptions
        try:
            steps = StepTracker(video_path, PlanOptions.from_config(get_config(), target_language, overrides))
            L.on_file_steps(video_path, steps.snapshot())
        except Exception:
            steps = None

        def steps_emit(changed=True):
            if steps is not None and changed:
                try:
                    L.on_file_steps(video_path, steps.snapshot())
                except Exception:
                    pass

        if self.check_exists and not Path(video_path).exists():
            L.on_file_error(video_path, tr('qr_file_not_found'))
            if steps is not None:
                steps.mark_failed()
                steps_emit()
            return False

        files_done = self.completed_files + self.failed_files
        engine = self

        class _Hooks(FileHooks):
            def on_text(self, line):
                L.on_log(line)

            def on_noise(self, line):
                # rumore che alcune librerie scrivono su STDOUT bypassando il logging (torch.hub): solo nel file di log
                logger.info(f"[child-stdout] {line}")

            def on_event(self, kind, fields):
                # evento strutturato: muove l'anteprima dei passi (la barra del file l'ha gia' mossa il runner)
                if steps is not None:
                    try:
                        steps_emit(steps.feed_event(kind, fields))
                    except Exception:
                        pass

            def on_progress(self, value, phase, changed):
                if changed:
                    L.on_file_progress(video_path, value)

            def on_stderr(self, line):
                # stderr del figlio (tqdm, warning di librerie): SOLO nel file di log, MAI a schermo
                logger.info(f"[child-stderr] {line}")

        L.on_log(tr('worker_start_single'))
        runner = FileRunner(self.project_root)
        self._runner = runner
        try:
            result = runner.run(
                video_path, target_language, files_done, progress=file_progress, hooks=_Hooks(), overrides=overrides,
                is_cancelled=lambda: engine.is_cancelled, ipc_prefix='tp_pipe_', feed_diag_progress=False,
                converting_cleanup='cancelled', raise_on_spawn_error=False)
        finally:
            self._runner = None

        if result.spawn_error is not None:
            L.on_log(tr('worker_critical_error').format(filename=filename, error=result.spawn_error))
            logger.error(f"Spawn pipeline_cli fallito: {result.spawn_error}")
            L.on_file_error(video_path, result.spawn_error)
            if steps is not None:
                steps.mark_failed()
                steps_emit()
            return False

        if result.cancelled:
            if steps is not None:
                steps.mark_stopped()
                steps_emit()
            L.on_log(tr('worker_cancelled_file').format(filename=filename))
            return False

        success = result.success
        last_output_path = result.output or ''

        if steps is not None:
            (steps.mark_completed if success else steps.mark_failed)()
            steps_emit()

        if success:
            L.on_log(tr('worker_completed').format(filename=filename))
            try:
                L.on_history({
                    'name': Path(video_path).name,
                    'date_iso': datetime.now().isoformat(timespec='seconds'),
                    'src_lang': 'auto',
                    'dst_lang': target_language,
                    'duration_seconds': round(result.duration),
                    'size_bytes': Path(video_path).stat().st_size,
                    'srt_path': last_output_path,
                    'video_path': video_path,
                })
            except Exception:
                pass
            return True

        L.on_file_error(video_path, f'exit code {result.returncode}')
        L.on_log(tr('worker_failed').format(filename=filename))
        L.on_log(tr('worker_hint'))
        return False
