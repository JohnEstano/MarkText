"""Background batch runner for the API.

One batch at a time per process. The job thread calls experiment.run_batch,
which writes each row as it happens, so a stopped or crashed job loses at
most one generation and can be resumed by batch id.
"""

import threading
import time

import experiment


class BatchJob:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.cancel = threading.Event()
        self.state = {"running": False, "batch_id": None, "done": 0, "total": 0,
                      "last": None, "error": None, "started": None, "finished": None}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, engine, engine_lock, prompts, lengths, runs, modes, seed_base, batch_id=None):
        if self.is_running():
            raise RuntimeError("A batch is already running ({})".format(self.state["batch_id"]))
        self.cancel = threading.Event()
        with self.lock:
            self.state.update({"running": True, "batch_id": batch_id, "done": 0,
                               "total": len(prompts) * len(lengths) * len(modes) * runs,
                               "last": None, "error": None, "started": time.time(),
                               "finished": None})

        def progress(done, total, row):
            with self.lock:
                self.state.update({"done": done, "total": total, "last": row})

        def work():
            try:
                bid = experiment.run_batch(engine, prompts, lengths, runs, modes,
                                           seed_base=seed_base, batch_id=batch_id,
                                           on_progress=progress, cancel_event=self.cancel,
                                           lock=engine_lock)
                with self.lock:
                    self.state["batch_id"] = bid
            except Exception as exc:                     # reported, never swallowed
                with self.lock:
                    self.state["error"] = str(exc)
            finally:
                with self.lock:
                    self.state["running"] = False
                    self.state["finished"] = time.time()

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        # give run_batch a moment to allocate the batch id for a new batch
        for _ in range(50):
            if self.snapshot()["batch_id"] or not self.is_running():
                break
            time.sleep(0.05)
        return self.snapshot()

    def stop(self):
        self.cancel.set()
        return self.snapshot()
