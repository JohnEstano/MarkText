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
- **Detection history** as CSV, with a dashboard in the web app: filters, KPIs, chart, grouped summary, export, backup before clear
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
| `logs/detection_history.csv` | CSV | One row per analysis |
| `logs/exports/*.csv` | CSV | Exports, summaries and backups written by the History tab |

## File handling

- **Read**: config JSON (`config.py`), TXT files and their sidecars, the CSV history, `README.md` for the About tab
- **Write**: TXT exports and JSON sidecars, the config on first run, new CSVs under `logs/exports/`
- **Update**: append one CSV row per analysis (`history.py`, `csv.DictWriter`)
- **Process**: tokenize, run inference, compute the z-score; filter, group and summarise the history with pandas (web app)
- **Organize**: directories created on start, `normal/` vs `watermarked/`, timestamped names, backup before clearing

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

Four tabs in both front-ends:

1. **Generate**: prompt, max tokens, Normal or Watermarked, Generate / Cancel. Copy, or Save (.txt + .json sidecar; the web app also downloads a copy).
2. **Detect**: open a TXT (its sidecar is shown if present) or paste text, Analyze. Shows tokens analyzed, green tokens, signal, z-score, p-value and the verdict.
3. **History**: the log. Web app: filter by result, filename, date and length; KPIs; z-score vs tokens chart; summary by result; export filtered rows or summary to a new CSV; Clear History writes a backup first.
4. **About**: this README, read from disk, plus the current configuration (key hidden).

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
- **File handling**: reads, creates, appends, backs up, exports and organises those files; see "File handling".
- **ML/NLP component**: a pretrained causal language model, a sampling-time watermark, and a statistical detector, all via Hugging Face Transformers.

## References

- Kirchenbauer, J. et al. "A Watermark for Large Language Models." (2023) [arXiv:2301.10226](https://arxiv.org/abs/2301.10226)
- Kirchenbauer, J. et al. "On the Reliability of Watermarks for Large Language Models." (2023) [arXiv:2306.04634](https://arxiv.org/abs/2306.04634), the paper Hugging Face's implementation cites
- Hugging Face Transformers: [WatermarkingConfig & WatermarkDetector](https://huggingface.co/docs/transformers/generation_strategies#watermarking)
- Qwen2.5: [Hugging Face Model Card](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)
