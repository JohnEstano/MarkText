"""MarkText API.

Run with:  uvicorn api.main:app --reload --port 8000

One engine per model, each loaded (and downloaded) on first use and shared
behind a lock, the same rule the Streamlit app follows. Every route
delegates to the root modules (engine, history, experiment, config);
nothing here classifies or scores. Authentication is a placeholder:
`principal()` returns None until accounts exist, so routes will not need
to change when they do.
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

def make_scorer_for(config, name):
    """One model's scorer (tokenizer only, no weights). Tests replace
    state["scorer_factory"] with a fake."""
    from scorer import Scorer
    return Scorer(cfg.config_for_model(config, name))


state = {"engine": None, "engines": {}, "scorer_factory": make_scorer_for, "scorers": {},
         "lock": threading.Lock(), "config": None,
         "notes": [], "job": BatchJob(), "load_error": None}


def scorers_for_all():
    """[(model name, scorer, lock)] for every catalog model, each built on
    first use. Tokenizers only: no weights download."""
    config = state["config"] or cfg.load_config()
    out = []
    for name in cfg.model_names(config):
        if name not in state["scorers"]:
            state["scorers"][name] = state["scorer_factory"](config, name)
        out.append((name, state["scorers"][name], state["lock"]))
    return out


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
        state["engine"] = engine_for_model(None)
    except Exception as exc:
        state["load_error"] = str(exc)


def engine_for_model(model):
    """The engine for one catalog model (None: the default), loading and
    downloading it on first use. One engine per model, shared by requests.
    The startup engine (or a test's injected one) serves default requests."""
    config = state["config"] or cfg.load_config()
    try:
        name = model or cfg.default_model_name(config)
        resolved = cfg.config_for_model(config, name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if name == cfg.default_model_name(config) and state["engine"] is not None:
        return state["engine"]
    if name not in state["engines"]:
        try:
            with state["lock"]:
                state["engines"][name] = Engine(resolved, model=name)
        except Exception as exc:
            raise HTTPException(503, "Model {} could not load: {}".format(name, exc))
    if state["engine"] is None:
        state["engine"] = state["engines"][name]
    return state["engines"][name]


app = FastAPI(title="MarkText API", version="1.0.0", on_startup=[load_engine])
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get(
        "MARKTEXT_CORS", "http://localhost:3000,http://127.0.0.1:3000").split(",")],
    allow_methods=["*"], allow_headers=["*"],
)


def redacted_config(config):
    return json.loads(json.dumps(cfg.redacted(config)))


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


# ---------------------------------------------------------------- models
@app.get("/models")
def list_models(who=Depends(principal)):
    config = state["config"] or cfg.load_config()
    return {"default": cfg.default_model_name(config), "models": cfg.public_models(config)}


# -------------------------------------------------------------- generate
@app.post("/generate")
def generate(req: schemas.GenerateRequest, who=Depends(principal)):
    engine = engine_for_model(req.model)
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
    from classroom import detection as scoring
    config = state["config"] or cfg.load_config()
    text = req.text.strip()
    if req.model is not None:
        if req.model not in config.get("models", {}):
            raise HTTPException(422, "Unknown model {!r}; choose one of: {}".format(
                req.model, ", ".join(cfg.model_names(config))))
        if req.model not in state["scorers"]:
            state["scorers"][req.model] = state["scorer_factory"](config, req.model)
        candidates = [(req.model, state["scorers"][req.model], state["lock"])]
    else:
        candidates = scorers_for_all()
    winner, stats, scores = scoring.trial_models(candidates, text)
    if stats is None:
        raise HTTPException(422, "Text is too short for analysis. Need at least {} tokens."
                            .format(candidates[0][1].min_tokens))
    model = scoring.winner_model(winner, stats)
    logged, log_error = None, None
    try:
        extra = dict(req.extra)
        extra["model"] = model
        logged = history.append_history(stats, source=req.source, filename=req.filename,
                                        extra=extra, text=text)
    except OSError as exc:
        log_error = str(exc)
    return {**stats, "model": model,
            "scores": [{"model": n, "z": z, "label": label} for n, z, label in scores],
            "run_id": logged, "log_error": log_error}


# --------------------------------------------------------------- history
def history_frame():
    history.ensure_history()
    try:
        df = pd.read_csv(history.HISTORY_PATH, parse_dates=["timestamp"], encoding="utf-8")
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=history.COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for c in ("filename", "mode", "model", "batch_id", "source", "note", "seeding_scheme",
              "run_id", "content"):
        df[c] = df[c].fillna("").astype(str)
    for c in ("tokens_scored", "green_tokens", "green_pct", "z_score", "p_value", "max_new_tokens", "seed", "gen_tokens"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def apply_filters(df, result, source, batch_id, q, date_from, date_to, min_tokens,
                  model=None):
    mask = pd.Series(True, index=df.index)
    if result:
        mask &= df["result"].isin(result)
    if source:
        mask &= df["source"].isin(source)
    if batch_id:
        mask &= df["batch_id"] == batch_id
    if model:
        mask &= df["model"].isin(model)
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
                min_tokens: int = 0, limit: int = 500,
                model: list[str] | None = Query(None), who=Depends(principal)):
    try:
        df = history_frame()
    except (OSError, ValueError) as exc:
        raise HTTPException(500, "Could not read the history CSV: {}".format(exc))
    filtered = apply_filters(df, result, source, batch_id, q, date_from, date_to, min_tokens,
                             model)
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
                    "batches": sorted(b for b in df["batch_id"].unique().tolist() if b),
                    "models": sorted(m for m in df["model"].unique().tolist() if m)},
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
            "points": json.loads(df[["run_id", "mode", "model", "max_new_tokens",
                                     "tokens_scored", "z_score", "result"]].to_json(orient="records"))}


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
    engine = engine_for_model(req.model)
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
