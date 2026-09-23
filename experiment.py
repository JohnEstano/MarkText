"""Batch experiment for MarkText: measure detection, do not just demo it.

For every prompt x length x mode x run: generate, detect, append one row
to logs/detection_history.csv tagged with a batch_id. Rows are written as
they happen, so an interrupted batch keeps what finished and can be
resumed with the same batch_id. summarise_batch() turns the rows into the
table that matters: true-positive and false-positive rates per length.

Run with:  python experiment.py --help
"""

import argparse
import datetime
import hashlib
import json
import pathlib
import threading
import time
import uuid

import pandas as pd

import config as cfg
import history

APPEND_RETRIES = 3          # a locked CSV (Excel) gets a few seconds to be released

BASE_DIR = pathlib.Path(__file__).resolve().parent
PROMPT_FILE = BASE_DIR / "prompts" / "experiment_prompts.txt"
EXPORT_DIR = history.EXPORT_DIR
MODES = ("normal", "watermarked")


# ------------------------------------------------------------------ prompts
def load_prompts(path=None, limit=None):
    """One prompt per line, blank lines and '#' comments ignored."""
    path = pathlib.Path(path or PROMPT_FILE)
    lines = [l.strip() for l in path.read_text(encoding="utf-8-sig").splitlines()]
    prompts = [l for l in lines if l and not l.startswith("#")]
    return prompts[:limit] if limit else prompts


def prompt_file_hash(path=None):
    path = pathlib.Path(path or PROMPT_FILE)
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


# -------------------------------------------------------------------- plan
def plan_cells(n_prompts, lengths, runs, modes=MODES):
    """The full grid, in execution order, as (prompt_idx, length, mode, run)."""
    return [(p, int(L), m, r)
            for p in range(n_prompts)
            for L in lengths
            for m in modes
            for r in range(runs)]


def cell_seed(seed_base, p, L, mode, r):
    """Deterministic per cell and independent of the grid, so a batch that is
    resumed or extended with more lengths still gives each cell the same seed."""
    key = "{}|{}|{}|{}".format(p, int(L), mode, r).encode("utf-8")
    return int(seed_base) + int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % 1_000_000


def done_cells(batch_id):
    """Cells already logged for this batch, from the history file."""
    done = set()
    for row in history.read_history():
        if row.get("batch_id") != batch_id:
            continue
        try:
            note = json.loads(row.get("note") or "{}")
            done.add((int(note["p"]), int(row["max_new_tokens"]), row["mode"], int(note["r"])))
        except (KeyError, ValueError, TypeError):
            continue
    return done


def settings_path(batch_id):
    return EXPORT_DIR / "experiment_{}.json".format(batch_id)


def write_settings(batch_id, settings):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(settings_path(batch_id), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)


def read_settings(batch_id):
    with open(settings_path(batch_id), "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------- run
def run_batch(engine, prompts, lengths, runs=1, modes=MODES, seed_base=None,
              batch_id=None, on_progress=None, cancel_event=None, lock=None,
              prompt_file=None):
    """Generate, detect and log every cell of the grid. Returns the batch_id.

    on_progress(done, total, row_dict) is called after every logged row.
    cancel_event (threading.Event) stops between generations and also
    cuts a running generation short. lock, if given, is held per call.
    """
    lock = lock or threading.Lock()
    cancel_event = cancel_event or threading.Event()
    if batch_id is None:
        batch_id = "b" + uuid.uuid4().hex[:7]
        if seed_base is None:
            seed_base = int(time.time()) % 1_000_000
        write_settings(batch_id, {
            "batch_id": batch_id,
            "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "prompt_file": str(prompt_file or PROMPT_FILE),
            "prompt_file_hash": prompt_file_hash(prompt_file),
            "n_prompts": len(prompts),
            "lengths": [int(L) for L in lengths],
            "runs": runs,
            "modes": list(modes),
            "seed_base": seed_base,
            "model_id": engine.config["model_id"],
            "device": engine.device,
            "watermark": {k: v for k, v in engine.config["watermark"].items()
                          if k != "hashing_key"},
            "thresholds": {k: engine.config[k] for k in
                           ("detection_threshold", "possible_threshold", "min_tokens_for_verdict")},
        })
    else:
        try:
            saved = read_settings(batch_id)
        except (OSError, ValueError) as exc:
            if seed_base is None:
                raise ValueError("Settings for batch {} could not be read ({}); pass a seed base "
                                 "to resume without them".format(batch_id, exc)) from exc
            saved = {}
        if seed_base is None:
            seed_base = saved["seed_base"]

    cells = plan_cells(len(prompts), lengths, runs, modes)
    already = done_cells(batch_id)
    total = len(cells)
    done = len([c for c in cells if c in already])

    for i, (p, L, mode, r) in enumerate(cells):
        if cancel_event.is_set():
            break
        if (p, L, mode, r) in already:
            continue
        seed = cell_seed(seed_base, p, L, mode, r)
        with lock:
            gen = engine.generate(prompts[p], max_new_tokens=L,
                                  watermarked=(mode == "watermarked"),
                                  seed=seed, cancel_event=cancel_event)
        if cancel_event.is_set() or gen["cancelled"]:
            break
        with lock:
            stats = engine.detect(gen["text"])
        if stats is None:
            # too short to score at all: log a placeholder so the cell counts
            stats = {"num_tokens_scored": 0, "num_green_tokens": 0,
                     "green_fraction": 0.0, "z_score": 0.0, "p_value": 1.0,
                     "label": "INCONCLUSIVE (short text)", "device": engine.device,
                     "watermark": {k: engine.config["watermark"][k] for k in
                                   ("bias", "greenlist_ratio", "seeding_scheme", "context_width")}}
        extra = {"mode": mode, "batch_id": batch_id, "max_new_tokens": L,
                 "seed": seed, "gen_tokens": gen["new_tokens"],
                 "note": json.dumps({"p": p, "r": r})}
        for attempt in range(APPEND_RETRIES):
            try:
                run_id = history.append_history(stats, source="batch", filename="", extra=extra)
                break
            except OSError:
                if attempt == APPEND_RETRIES - 1:
                    raise OSError("Could not append to the history CSV (is it open in Excel?). "
                                  "Resume with --resume {}".format(batch_id))
                time.sleep(2)
        done += 1
        if on_progress:
            on_progress(done, total, {"run_id": run_id, "prompt_idx": p, "length": L,
                                      "mode": mode, "run": r, "z": stats["z_score"],
                                      "label": stats["label"]})
    return batch_id


# ----------------------------------------------------------------- results
def batch_frame(batch_id):
    """Rows of one batch as a DataFrame with numeric columns."""
    rows = [r for r in history.read_history() if r.get("batch_id") == batch_id]
    df = pd.DataFrame(rows, columns=history.COLUMNS)
    for c in ("max_new_tokens", "seed", "gen_tokens", "tokens_scored", "green_tokens",
              "green_pct", "z_score", "p_value", "context_width"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def summarise_batch(df, config):
    """Per (mode, max_new_tokens): n, mean z, and the detection rates."""
    det = float(config.get("detection_threshold", 4.0))
    pos = float(config.get("possible_threshold", 2.0))
    if df.empty:
        return pd.DataFrame(columns=["mode", "max_new_tokens", "n", "mean_z", "mean_green_pct",
                                     "flagged_rate", "possible_or_above_rate",
                                     "inconclusive_rate", "retokenize_mismatch"])
    d = df.copy()
    d["flagged"] = d["result"] == "LIKELY MARKTEXT"
    d["possible_or_above"] = d["z_score"] >= pos
    d["inconclusive"] = d["result"].str.startswith("INCONCLUSIVE")
    d["mismatch"] = (d["gen_tokens"] - d["context_width"] + 1) != d["tokens_scored"]
    out = (d.groupby(["mode", "max_new_tokens"])
            .agg(n=("run_id", "count"),
                 mean_z=("z_score", "mean"),
                 mean_green_pct=("green_pct", "mean"),
                 flagged_rate=("flagged", "mean"),
                 possible_or_above_rate=("possible_or_above", "mean"),
                 inconclusive_rate=("inconclusive", "mean"),
                 retokenize_mismatch=("mismatch", "sum"))
            .reset_index())
    # flagged_rate is the true-positive rate for watermarked rows and the
    # false-positive rate for normal rows, both at detection_threshold
    out["rate_meaning"] = out["mode"].map({"watermarked": "TP rate @ z>={}".format(det),
                                           "normal": "FP rate @ z>={}".format(det)})
    return out


def export_summary(batch_id, summary):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / "experiment_{}_summary.csv".format(batch_id)
    summary.to_csv(path, index=False, encoding="utf-8")
    return path


def known_batches():
    """batch_id -> row count, from the history file."""
    counts = {}
    for r in history.read_history():
        b = r.get("batch_id")
        if b:
            counts[b] = counts.get(b, 0) + 1
    return counts


# --------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prompt-file", default=str(PROMPT_FILE))
    ap.add_argument("--prompts", type=int, default=None, help="use only the first N prompts")
    ap.add_argument("--lengths", type=int, nargs="+", default=[150])
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    ap.add_argument("--seed", type=int, default=None, help="seed base; each cell derives its own seed from it")
    ap.add_argument("--resume", default=None, metavar="BATCH_ID")
    ap.add_argument("--summary-only", default=None, metavar="BATCH_ID",
                    help="print and export the summary of a finished batch, no generation")
    args = ap.parse_args(argv)

    config = cfg.load_config()
    if args.summary_only:
        summary = summarise_batch(batch_frame(args.summary_only), config)
        print(summary.to_string(index=False))
        print("exported:", export_summary(args.summary_only, summary))
        return 0

    from engine import Engine   # imported late: loading the model is slow
    prompts = load_prompts(args.prompt_file, args.prompts)
    print("Loading model...")
    engine = Engine(config, progress_callback=print)
    total = len(prompts) * len(args.lengths) * len(args.modes) * args.runs
    print("Batch: {} prompts x {} x {} x {} run(s) = {} generations".format(
        len(prompts), args.lengths, args.modes, args.runs, total))

    cancel = threading.Event()
    start = time.time()

    def progress(done, total, row):
        elapsed = time.time() - start
        eta = elapsed / max(done, 1) * (total - done)
        print("[{}/{}] p{} L{} {:<11} z={:>6.2f} {:<26} elapsed {:>5.0f}s  eta {:>5.0f}s".format(
            done, total, row["prompt_idx"], row["length"], row["mode"], row["z"],
            row["label"], elapsed, eta), flush=True)

    try:
        batch_id = run_batch(engine, prompts, args.lengths, args.runs, args.modes,
                             seed_base=args.seed, batch_id=args.resume,
                             on_progress=progress, cancel_event=cancel,
                             prompt_file=args.prompt_file)
    except KeyboardInterrupt:
        cancel.set()
        print("\nInterrupted. Resume with:  python experiment.py --resume <batch_id>")
        return 1
    summary = summarise_batch(batch_frame(batch_id), config)
    print("\nbatch_id:", batch_id)
    print(summary.to_string(index=False))
    print("exported:", export_summary(batch_id, summary))
    print("Resume or extend with:  python experiment.py --resume", batch_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
