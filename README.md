# MarkText

**Watermarking and Detection of LLM-Generated Text**

MarkText is an educational demo of text provenance watermarking. It generates text with a small local language model (Qwen2.5-0.5B-Instruct) and can bias sampling toward a keyed "green list" of tokens, following Kirchenbauer et al. (2023). A detector that knows the key re-scores a text and reports how far its green-token count sits above chance, as a z-score. Two front-ends share one core: a Tkinter desktop window and a Streamlit web page.

> **Limitation:** MarkText detects only text that MarkText itself generated with the same key, parameters and tokenizer. It is **not** a universal AI-text detector. "NOT DETECTED" means this watermark was not found, not that a human wrote the text.

---

## Purpose and users

A lecturer uses MarkText to verify whether a text was produced by *this* MarkText installation with its watermark on, and to show a class, live, that watermarked and normal text from the same prompt read alike but score very differently. Researchers and students use the History tab to compare detection strength across lengths and settings. It runs on an ordinary laptop with no GPU and no cloud API.

## Features

- **Prompt-based generation** with Qwen2.5-Instruct, normal or watermarked, with an optional fixed seed and a Cancel button
- **Watermarked generation** through Hugging Face `WatermarkingConfig` (green/red list logit bias)
- **Detection** through `WatermarkDetector`: tokens scored, green count, z-score, p-value, verdict
- **Save as .txt** with a `.json` sidecar recording mode, seed and parameters; copy to clipboard
- **Detection history** as CSV with a unique id per record; web dashboard with filters, KPIs, chart, grouped summary, export, per-record note/filename editing and deletion, backup before any destructive write
- **Batch experiment** (web tab or `experiment.py`): generate every prompt in both modes, score them all, and report true-positive and false-positive rates per length; interruptible and resumable
- Fully local after the one-time model download

## Technology

| Component | What |
|-----------|------|
| Language model | `Qwen/Qwen2.5-0.5B-Instruct` (Hugging Face Hub; the weights file is about 1 GB, safetensors) |
| Watermarking | Kirchenbauer et al. 2023 green/red list, Hugging Face's implementation (`transformers.WatermarkingConfig`) |
| Detection | `transformers.WatermarkDetector`: one-proportion z-test |
| Desktop GUI | Python Tkinter + ttk (`main.py`) |
| Web GUI | Streamlit + pandas (`app.py`) |
| Framework | PyTorch + Hugging Face Transformers |

MarkText *uses* Hugging Face's implementation of the algorithm; it does not re-implement it. The project's own code is the application around it: configuration, the shared-config design that keeps generation and detection consistent, the two front-ends, and the file handling.

## Watermark algorithm

At each generation step the vocabulary is split into a green list and a red list by a seeded shuffle. The seed comes from a secret key and the recent tokens (with `selfhash`, the candidate token itself is included). Green-list logits get a constant bias added before sampling, so green tokens are favoured but not forced.

At detection time the detector re-tokenizes the text, recomputes the green list at every position, and counts green tokens. Under the null hypothesis "the writer did not know the key", each scored token is green with probability `greenlist_ratio`, so the count is binomial and

    z = (green − γ·T) / sqrt(T·γ·(1 − γ))

This project runs with `greenlist_ratio = 0.5` and `bias = 3.0` (Hugging Face's defaults are 0.25 and 2.0). Verdicts:

| z-score | Verdict |
|---|---|
| ≥ `detection_threshold` (4.0) | LIKELY MARKTEXT |
| ≥ `possible_threshold` (2.0) | POSSIBLE WATERMARK |
| below | NOT DETECTED |
| fewer than `min_tokens_for_verdict` (100) tokens scored | INCONCLUSIVE (short text) |

All four numbers live in `config/watermark_config.json` and are applied in one place (`engine.classify`). The paper's own running example is z > 4, about a 3×10⁻⁵ false-positive probability.

## The key

The hashing key is a shared secret: whoever holds it can verify the watermark and can also produce text that carries it. On first run MarkText generates a private key and writes it to `config/watermark_config.json`, which is git-ignored; `config/watermark_config.example.json` shows the schema. Changing the key makes previously generated text undetectable, so texts are tied to the installation that made them. If a config carries Hugging Face's public default key (15485863), both front-ends warn on startup. The sample texts under `generated/` in this repository were produced with that public key.

## Files

| File | Type | Purpose |
|------|------|---------|
| `config/watermark_config.json` | JSON | Model id, sampling and watermark parameters, thresholds, private key (git-ignored; created on first run) |
| `config/watermark_config.example.json` | JSON | Schema with a null key |
| `generated/normal/*.txt`, `generated/watermarked/*.txt` | TXT | Saved generations |
| `generated/**/*.json` | JSON | Sidecar per saved text: mode, seed, parameters, device |
| `prompts/experiment_prompts.txt` | TXT | 100 prompts, one per line, read by the experiment |
| `logs/detection_history.csv` | CSV | One row per analysis: `run_id`, source, mode, seed, tokens, green %, z, p-value, verdict, watermark parameters, device, note |
| `logs/exports/experiment_<batch>.json` | JSON | Settings of a batch (prompt-file hash, lengths, seed base, config snapshot without the key) |
| `logs/exports/detection_history_v1_*.csv` | CSV | Archive of a history file in the old 7-column layout, written once when it is migrated |
| `logs/exports/*.csv` | CSV | Exports, summaries and backups written by the History tab |

## File handling

- **Read**: config JSON (`config.py`), TXT files and their sidecars, the prompt list, the CSV history, `README.md` for the About tab
- **Write**: TXT exports and JSON sidecars, the config on first run, batch settings JSON, new CSVs under `logs/exports/`
- **Update**: append one CSV row per analysis; edit one record's note or filename, or delete one record, by `run_id` with a backup first and a check that exactly one row matches (`history.py`, `csv.DictWriter`)
- **Process**: tokenize, run inference, compute the z-score; filter, group and summarise the history and batch results with pandas (web app)
- **Organize**: directories created on start, `normal/` vs `watermarked/`, timestamped names, backup before every destructive write, automatic migration of an old history layout with the original archived

Row writing uses the standard library `csv` module; pandas only reads the file and writes new ones. Model weights are read by `transformers` from the Hugging Face cache.

## Installation

Requires **Python 3.11+**.

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

## Running

Desktop (Tkinter):

```bash
python main.py
```

Web (Streamlit), opens at http://localhost:8501 (bound to localhost in `.streamlit/config.toml`):

```bash
streamlit run app.py
```

On first run Hugging Face downloads Qwen2.5-0.5B-Instruct (about 1 GB) into `~/.cache/huggingface/hub`; later launches use the cache. Both front-ends share the config, the history CSV and the `generated/` folders. Generation on a CPU takes a few tokens per second.

Tests (no model download needed):

```bash
pip install pytest
pytest -q
```

## GUI

Four tabs in the desktop app, five in the web app:

1. **Generate**: prompt, max tokens, Normal or Watermarked, Generate / Cancel. Copy, or Save (.txt + .json sidecar; the web app also downloads a copy).
2. **Detect**: open a TXT (its sidecar is shown if present) or paste text, Analyze. Shows tokens analyzed, green tokens, signal, z-score, p-value and the verdict.
3. **History**: the log. Web app: filter by result, source, batch, filename, date and length; KPIs; z-score vs tokens chart with the threshold line; summary by mode and result; export filtered rows or summary to a new CSV; edit a record's note or filename or delete it by `run_id`; Clear History writes a backup first.
4. **Experiment** (web app only): run the batch described below and read its summary.
5. **About**: this README, read from disk, plus the current configuration (key hidden).

## Experiment: measuring detection

The thresholds are only claims until they are measured. The experiment generates every prompt in `prompts/experiment_prompts.txt` in both modes at chosen lengths, scores each text, and logs one history row per generation under a batch id. The summary per (mode, length) reports:

- **flagged rate**: for watermarked rows the true-positive rate, for normal rows the false-positive rate, both at `detection_threshold`;
- the share at or above `possible_threshold`, the share INCONCLUSIVE, mean z, mean green %, and how many rows failed the token round trip (`gen_tokens − context_width + 1 ≠ tokens_scored`).

```bash
# quick smoke, about 10 minutes on a CPU
python experiment.py --prompts 3 --lengths 50 150 300

# the demo batch: 100 prompts x 150 tokens x 2 modes, about 1 h 40 min
python experiment.py --lengths 150 --seed 100

# the full grid, about 5 hours; interrupt with Ctrl-C and continue later
python experiment.py --lengths 50 150 300 --seed 100
python experiment.py --resume <batch_id>
```

Every row is written as soon as it exists, so an interrupted batch loses at most one generation; `--resume` skips finished cells. Each cell's seed is derived from the seed base and the cell itself (prompt, length, mode, run), so a batch can be repeated exactly and extended with more lengths without changing existing cells. The summary is exported to `logs/exports/experiment_<batch_id>_summary.csv` and shown in the web app's Experiment tab.

Measured results: see the table at the end of this file once the demo batch has run.

## Limitations

- Only detects text generated by MarkText with the same key and parameters, on the same device type.
- Short texts give little evidence; below 100 scored tokens the verdict is INCONCLUSIVE.
- Editing, paraphrasing or heavily rewriting text weakens or destroys the watermark.
- The key is a symmetric secret: leaking it allows forgery; rotating it orphans old texts.
- Detection assumes independent scored positions; overlapping and repeated n-grams make the z-score an approximation.
- The underlying model generates from its own training data; MarkText does not claim ownership of it.

## Assignment requirements mapping

- **Purpose and target users**: an educational provenance demo and verifier for lecturers, students and researchers; see "Purpose and users".
- **Main features**: generation in two modes, detection with a calibrated statistic, saving with metadata, history with analysis.
- **Files/data**: JSON (config, sidecars), TXT (generations), CSV (history, exports), safetensors weights read by the library.
- **File handling**: reads, creates, appends, updates and deletes single records, backs up, migrates, exports and organises those files; see "File handling".
- **ML/NLP component**: a pretrained causal language model, a sampling-time watermark, a statistical detector, and an experiment that measures the detector's error rates, all via Hugging Face Transformers.

## References

- Kirchenbauer, J. et al. "A Watermark for Large Language Models." (2023) [arXiv:2301.10226](https://arxiv.org/abs/2301.10226)
- Kirchenbauer, J. et al. "On the Reliability of Watermarks for Large Language Models." (2023) [arXiv:2306.04634](https://arxiv.org/abs/2306.04634), the paper Hugging Face's implementation cites
- Hugging Face Transformers: [WatermarkingConfig & WatermarkDetector](https://huggingface.co/docs/transformers/generation_strategies#watermarking)
- Qwen2.5: [Hugging Face Model Card](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)
