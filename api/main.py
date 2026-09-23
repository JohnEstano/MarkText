"""MarkText API.

Run with:  uvicorn api.main:app --reload --port 8000

The model is loaded once at startup and shared behind a lock, the same rule
the Streamlit app follows. Every route delegates to the root modules
(engine, history, experiment, config); nothing here classifies or scores.
Authentication is a placeholder: `principal()` returns None until accounts
exist, so routes will not need to change when they do.
"""

import datetime
import io
import json
import os
import pathlib
import threading

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import config as cfg
import experiment
import history
from api import schemas
from api.jobs import BatchJob
from engine import Engine

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
GENERATED_DIR = BASE_DIR / "generated"
README_PATH = BASE_DIR / "README.md"

state = {"engine": None, "lock": threading.Lock(), "config": None, "notes": [],
         "job": BatchJob(), "load_error": None}


def principal():
    """Who is calling. None until accounts exist."""
    return None


def load_engine():
    notes = []
    config = cfg.load_config(notes=notes)
    state["config"], state["notes"] = config, notes
    if os.environ.get("MARKTEXT_SKIP_MODEL") == "1":      # tests inject a fake engine
        return
    try:
        state["engine"] = Engine(config)
    except Exception as exc:
        state["load_error"] = str(exc)


def engine_or_503():
    if state["engine"] is None:
        raise HTTPException(503, state["load_error"] or "Model not loaded")
    return state["engine"]


app = FastAPI(title="MarkText API", version="1.0.0", on_startup=[load_engine])
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get(
        "MARKTEXT_CORS", "http://localhost:3000,http://127.0.0.1:3000").split(",")],
    allow_methods=["*"], allow_headers=["*"],
)


def redacted_config(config):
    shown = json.loads(json.dumps(config))
    shown["watermark"]["hashing_key"] = "(hidden)"
    return shown


# ------------------------------------------------------------------ meta
@app.get("/health")
def health():
    config = state["config"] or {}
    return {
        "status": "ok" if state["engine"] else "model_unavailable",
        "model_id": config.get("model_id"),
        "device": getattr(state["engine"], "device", None),
        "key_is_public": (config.get("watermark", {}).get("hashing_key") == cfg.HF_PUBLIC_KEY),
        "notes": state["notes"],
        "load_error": state["load_error"],
    }


@app.get("/config")
def get_config():
    return redacted_config(state["config"] or cfg.load_config())


@app.get("/readme")
def readme():
    try:
        return {"markdown": README_PATH.read_text(encoding="utf-8-sig")}
    except OSError as exc:
        raise HTTPException(404, str(exc))


@app.get("/prompts")
def prompts():
    try:
        items = experiment.load_prompts()
    except OSError as exc:
        raise HTTPException(404, str(exc))
    return {"count": len(items), "path": str(experiment.PROMPT_FILE), "prompts": items}


# -------------------------------------------------------------- generate
@app.post("/generate")
def generate(req: schemas.GenerateRequest, who=Depends(principal)):
    engine = engine_or_503()
    with state["lock"]:
        return engine.generate(req.prompt.strip(), max_new_tokens=req.max_new_tokens,
                               watermarked=(req.mode == "watermarked"), seed=req.seed)


@app.post("/generate/save")
def save_generation(req: schemas.SaveRequest, who=Depends(principal)):
    info = req.generation
    text = str(info.get("text", ""))
    mode = info.get("mode")
    if not text or mode not in ("normal", "watermarked"):
        raise HTTPException(422, "generation needs text and a mode")
    folder = GENERATED_DIR / mode
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = folder / "marktext_{}_{}.txt".format(mode, stamp)
    try:
        path.write_text(text, encoding="utf-8")
        record = {k: v for k, v in info.items() if k != "text"}
        record["saved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record["text_file"] = path.name
        with open(path.with_suffix(".json"), "w", encoding="utf-8") as f:
            json.dump(record, f, indent=4)
    except OSError as exc:
        raise HTTPException(500, "Save failed: {}".format(exc))
    return {"text_path": str(path), "sidecar_path": str(path.with_suffix(".json"))}


# ---------------------------------------------------------------- detect
@app.post("/detect")
def detect(req: schemas.DetectRequest, who=Depends(principal)):
    engine = engine_or_503()
    text = req.text.strip()
    with state["lock"]:
        stats = engine.detect(text)
    if stats is None:
        raise HTTPException(422, "Text is too short for analysis. Need at least {} tokens."
                            .format(engine.min_tokens))
    logged, log_error = None, None
    try:
        logged = history.append_history(stats, source=req.source, filename=req.filename,
                                        extra=req.extra)
    except OSError as exc:
        log_error = str(exc)
    return {**stats, "run_id": logged, "log_error": log_error}


# --------------------------------------------------------------- history
def history_frame():
    history.ensure_history()
    try:
        df = pd.read_csv(history.HISTORY_PATH, parse_dates=["timestamp"], encoding="utf-8")
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=history.COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for c in ("filename", "mode", "batch_id", "source", "note", "seeding_scheme", "run_id"):
        df[c] = df[c].fillna("").astype(str)
    for c in ("tokens_scored", "green_tokens", "green_pct", "z_score", "p_value", "max_new_tokens", "seed", "gen_tokens"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def apply_filters(df, result, source, batch_id, q, date_from, date_to, min_tokens):
    mask = pd.Series(True, index=df.index)
    if result:
        mask &= df["result"].isin(result)
    if source:
        mask &= df["source"].isin(source)
    if batch_id:
        mask &= df["batch_id"] == batch_id
    if q:
        mask &= df["filename"].str.contains(q, case=False, na=False)
    if date_from:
        mask &= df["timestamp"].dt.date >= pd.Timestamp(date_from).date()
    if date_to:
        mask &= df["timestamp"].dt.date <= pd.Timestamp(date_to).date()
    if min_tokens:
        mask &= df["tokens_scored"] >= min_tokens
    return df[mask]


def summarise(df, by):
    if df.empty:
        return []
    out = (df.groupby(by)
             .agg(analyses=("z_score", "count"), mean_z=("z_score", "mean"),
                  mean_green_pct=("green_pct", "mean"), mean_tokens=("tokens_scored", "mean"))
             .reset_index())
    return json.loads(out.to_json(orient="records"))


def frame_records(df):
    out = df.copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return json.loads(out.to_json(orient="records"))


@app.get("/history")
def get_history(result: list[str] | None = Query(None), source: list[str] | None = Query(None),
                batch_id: str | None = None, q: str | None = None,
                date_from: str | None = None, date_to: str | None = None,
                min_tokens: int = 0, limit: int = 500, who=Depends(principal)):
    try:
        df = history_frame()
    except (OSError, ValueError) as exc:
        raise HTTPException(500, "Could not read the history CSV: {}".format(exc))
    filtered = apply_filters(df, result, source, batch_id, q, date_from, date_to, min_tokens)
    has_modes = (filtered["mode"] != "").any() if not filtered.empty else False
    config = state["config"] or cfg.load_config()
    kpis = {
        "count": int(len(filtered)),
        "mean_z": float(filtered["z_score"].mean()) if len(filtered) else None,
        "flagged_rate": float((filtered["result"] == "LIKELY MARKTEXT").mean()) if len(filtered) else None,
        "median_tokens": float(filtered["tokens_scored"].median()) if len(filtered) else None,
    }
    rows = filtered.sort_values("timestamp", ascending=False).head(limit)
    return {
        "total": int(len(df)),
        "kpis": kpis,
        "summary": summarise(filtered, ["mode", "result"] if has_modes else ["result"]),
        "rows": frame_records(rows),
        "options": {"results": sorted(df["result"].unique().tolist()),
                    "sources": sorted(df["source"].unique().tolist()),
                    "batches": sorted(b for b in df["batch_id"].unique().tolist() if b)},
        "thresholds": {k: config[k] for k in ("detection_threshold", "possible_threshold",
                                              "min_tokens_for_verdict")},
    }


@app.get("/history/export")
def export_history(result: list[str] | None = Query(None), source: list[str] | None = Query(None),
                   batch_id: str | None = None, q: str | None = None, who=Depends(principal)):
    df = apply_filters(history_frame(), result, source, batch_id, q, None, None, 0)
    history.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = history.EXPORT_DIR / "history_filtered_{}.csv".format(stamp)
    df.to_csv(path, index=False, encoding="utf-8")          # the app's own write
    buf = io.StringIO(); df.to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename={}".format(path.name),
                                      "X-Saved-Path": str(path)})


@app.get("/history/{run_id}")
def get_record(run_id: str, who=Depends(principal)):
    rec = history.find_record(run_id)
    if rec is None:
        raise HTTPException(404, "No record with run_id {}".format(run_id))
    return rec


@app.patch("/history/{run_id}")
def patch_record(run_id: str, req: schemas.RecordUpdate, who=Depends(principal)):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(422, "Nothing to update")
    try:
        backup = history.update_record(run_id, **fields)
    except ValueError as exc:
        raise HTTPException(404 if "match" in str(exc) else 422, str(exc))
    except OSError as exc:
        raise HTTPException(500, str(exc))
    return {"record": history.find_record(run_id), "backup": str(backup)}


@app.delete("/history/{run_id}")
def delete_record(run_id: str, who=Depends(principal)):
    try:
        backup = history.delete_record(run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except OSError as exc:
        raise HTTPException(500, str(exc))
    return {"deleted": run_id, "backup": str(backup)}


@app.post("/history/clear")
def clear_history(who=Depends(principal)):
    try:
        return {"backup": str(history.clear_history())}
    except OSError as exc:
        raise HTTPException(500, str(exc))


# ------------------------------------------------------------ experiments
def batch_payload(batch_id):
    config = state["config"] or cfg.load_config()
    df = experiment.batch_frame(batch_id)
    summary = experiment.summarise_batch(df, config)
    try:
        settings = experiment.read_settings(batch_id)
    except (OSError, ValueError):
        settings = None
    return {"batch_id": batch_id, "rows": int(len(df)), "settings": settings,
            "summary": json.loads(summary.to_json(orient="records")),
            "points": json.loads(df[["run_id", "mode", "max_new_tokens", "tokens_scored",
                                     "z_score", "result"]].to_json(orient="records"))}


@app.get("/experiments")
def list_experiments(who=Depends(principal)):
    batches = experiment.known_batches()
    out = []
    for bid, n in sorted(batches.items(), reverse=True):
        try:
            settings = experiment.read_settings(bid)
        except (OSError, ValueError):
            settings = None
        out.append({"batch_id": bid, "rows": n, "settings": settings})
    return {"batches": out, "job": state["job"].snapshot()}


@app.post("/experiments", status_code=202)
def start_experiment(req: schemas.ExperimentRequest, who=Depends(principal)):
    engine = engine_or_503()
    try:
        prompts_list = experiment.load_prompts(limit=req.n_prompts)
    except OSError as exc:
        raise HTTPException(404, str(exc))
    if not req.lengths:
        raise HTTPException(422, "lengths must not be empty")
    try:
        snap = state["job"].start(engine, state["lock"], prompts_list, req.lengths, req.runs,
                                  req.modes, None if req.resume else req.seed_base, req.resume)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return snap


@app.get("/experiments/{batch_id}")
def get_experiment(batch_id: str, who=Depends(principal)):
    if batch_id not in experiment.known_batches() and state["job"].snapshot()["batch_id"] != batch_id:
        raise HTTPException(404, "Unknown batch {}".format(batch_id))
    job = state["job"].snapshot()
    return {**batch_payload(batch_id),
            "job": job if job["batch_id"] == batch_id else None}


@app.post("/experiments/{batch_id}/stop")
def stop_experiment(batch_id: str, who=Depends(principal)):
    job = state["job"].snapshot()
    if job["batch_id"] != batch_id or not job["running"]:
        raise HTTPException(409, "Batch {} is not running".format(batch_id))
    return state["job"].stop()


@app.get("/experiments/{batch_id}/export")
def export_experiment(batch_id: str, who=Depends(principal)):
    config = state["config"] or cfg.load_config()
    summary = experiment.summarise_batch(experiment.batch_frame(batch_id), config)
    path = experiment.export_summary(batch_id, summary)
    return StreamingResponse(iter([summary.to_csv(index=False)]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename={}".format(path.name),
                                      "X-Saved-Path": str(path)})
