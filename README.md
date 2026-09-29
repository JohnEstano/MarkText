# MarkText

**A class space for written work, with a watermark the teacher can check**

MarkText Classroom is a small learning-management system built around text provenance watermarking. A teacher creates classes and assignments; students hand in their writing, and may draft it with MarkText's own writing assistant. The assistant is a local language model (Qwen2.5-0.5B-Instruct) whose output carries a keyed "green list" watermark (Kirchenbauer et al., 2023). The teacher scores each submission with the watermark detector, records a decision with a note, and returns it to the student.

> **What detection answers:** "was this text drafted with this installation's assistant?", not "was this written by AI?". MarkText recognises only text generated with its own key, parameters and tokenizer. *Not detected* means this watermark was not found, not that a person wrote the text. Editing a draft heavily weakens the watermark.

---

## Purpose and users

- **Teachers** (the main user). They run classes, collect submissions, score them, decide and return them, and export reports. Every file the system manages passes through the teacher's pages.
- **Students** join a class with a code, read the assignment, write or upload their answer, can ask the assistant for a first draft, and see the teacher's decision and note when the work comes back.
- **Lecturers and researchers** use the Lab pages (the original MarkText) to demonstrate the watermark live and to measure the detector's error rates with a batch experiment.

It runs on an ordinary laptop with no GPU and no cloud service.

## Features

**Teacher**
- Home page with what needs attention across all classes and the most recent flags
- Classes with a join code (six characters, no look-alike letters), a new code on demand, archive and restore
- Roster: students who joined with the code, a CSV roster import (registered students are enrolled, unknown usernames invited until they register), removal that keeps the history, and a roster export
- Assignments with instructions and a due date; close and reopen
- Review page: every student with their state (not submitted, not scored, scored, decided, returned), the submitted text and all earlier versions, scoring one or all submissions, the detector's numbers, a decision (accepted, flagged, needs review) with a note, and returning the work
- Reports: the assignment table and a class summary, each saved as a new CSV and downloaded

**Student**
- Register, join classes with a code, see open assignments and returned work
- Write in the editor or upload a `.txt` file; every hand-in is a new version and none is overwritten
- **Draft with the assistant** (can be switched off): a watermarked first draft, recorded with its seed in the submission's sidecar
- The teacher's decision and note after the work is returned (the detector's numbers stay on the teacher's side)

**Lab** (teacher only): Generate (normal or watermarked, save as TXT + JSON sidecar), Detect (any text), History (a dashboard over every detection), Experiment (true- and false-positive rates over many prompts).

**Accounts**: passwords hashed with salted PBKDF2-HMAC-SHA256 (Python's `hashlib`); the first account is the teacher, created on a setup screen; more teachers only from the command line.

## How a submission travels

1. **Hand in.** `classroom/submissions.py` writes `v001.txt` and a `v001.json` sidecar under `data/submissions/<class>/<assignment>/<student>/` and appends a row to `data/submissions.csv`. A later version is written beside it, and the index marks the older row `superseded`.
2. **Score.** `classroom/detection.py` reads the text, runs `Engine.detect`, appends a row to `logs/detection_history.csv` (source `submission`, with the class, assignment and student ids in its note) and a review row to `data/reviews.csv` with a copy of the numbers, the model id and the key id.
3. **Decide and return.** `classroom/reviews.py` rewrites that one review row (backup first) with the decision, the note and the return time.
4. **Report.** `classroom/reports.py` joins roster, submissions and reviews with pandas and writes a new CSV under `data/reports/`.

The review keeps its own copy of the numbers so that clearing the lab history never erases a teacher's record; measurements cannot be edited in either file, so the two copies cannot disagree.

## Technology

| Component | What |
|-----------|------|
| Language model | `Qwen/Qwen2.5-0.5B-Instruct` (Hugging Face Hub; about 1 GB, safetensors) |
| Watermarking | Kirchenbauer et al. 2023 green/red list, Hugging Face's implementation (`transformers.WatermarkingConfig`) |
| Detection | `scorer.py`: a one-proportion z-test on the green list of Hugging Face's `WatermarkLogitsProcessor`, counting each repeated n-gram once, with an exact p-value and a passage scan |
| Web app | Streamlit multipage app (`app.py`, `app_pages/`, `ui/`), pandas and Altair for tables and charts |
| Classroom rules | `classroom/`: plain Python with the standard library (`csv`, `json`, `hashlib`, `secrets`, `pathlib`) |
| Desktop app | Tkinter (`main.py`), the original single-window MarkText |
| Framework | PyTorch + Hugging Face Transformers |

MarkText *uses* Hugging Face's implementation of the watermark: the same `WatermarkLogitsProcessor` biases generation and says which tokens are green at detection time. The counting and the statistics are MarkText's own (`scorer.py`), because two parts of the library's `WatermarkDetector` (transformers 5.17) do not do what they say: its `ignore_repeated_ngrams` switch never finds a repeat (it puts tensors in a `Counter`, and tensors hash by identity), and its p-value drops a square root from the normal-tail approximation (0.039 instead of 0.023 at z = 2). A test checks that, counting every position, `scorer.py` gives exactly the library's token and green counts.

## Watermark algorithm

At each generation step the vocabulary is split into a green list and a red list by a seeded shuffle. The seed comes from a secret key and the recent tokens (with `selfhash`, the candidate token itself is included). Green-list logits get a constant bias added before sampling, so green tokens are favoured but not forced.

At detection time the scorer re-tokenizes the text, recomputes the green list at every position, and counts green tokens. A repeated n-gram (the same context and token again) is counted once: its colour is fixed by the key, so a second copy of a phrase is not new evidence, and counting it again inflates z on human text that repeats itself (the recommendation of arXiv:2306.04634). Under the null hypothesis "the writer did not know the key", each distinct scored n-gram is green with probability `greenlist_ratio`, so the count is binomial and

    z = (green − γ·T) / sqrt(T·γ·(1 − γ)),   p = P(Z ≥ z)

This project runs with `greenlist_ratio = 0.5` and `bias = 3.0` (Hugging Face's defaults are 0.25 and 2.0). Verdicts:

| z-score | Verdict |
|---|---|
| ≥ `detection_threshold` (4.0) | LIKELY MARKTEXT |
| ≥ `possible_threshold` (2.0) | POSSIBLE WATERMARK |
| below | NOT DETECTED |
| fewer than `min_tokens_for_verdict` (100) tokens scored | INCONCLUSIVE (short text) |

All four numbers live in `config/watermark_config.json` and are applied in one place (`verdict.classify`). The paper's own running example is z > 4, about a 3×10⁻⁵ false-positive probability.

**Passages.** A student may paste an assistant draft into a longer essay; the whole-text z dilutes it. The scorer also scores windows of 150 scored tokens, one every 50 tokens. Looking at k windows is k tests, so the best window's p-value is multiplied by k (Bonferroni) and compared with the "likely" threshold's p-value (3.2×10⁻⁵ for z = 4). A passage can raise a verdict to LIKELY, never lower one and never produce POSSIBLE, so for text without the watermark the chance of LIKELY is at most twice one test's (6.3×10⁻⁵, the union bound) and the chance of POSSIBLE is unchanged. In simulation (human text as fair coin flips, a passage green 70% of the time, as the assistant's drafts measure), a 200-token passage inside a 1000-token essay is found as LIKELY 70% of the time; the whole-text z alone finds it 6% of the time. The review page highlights the passage.

## The key

The hashing key is a shared secret: whoever holds it can verify the watermark and can also produce text that carries it. On first run MarkText generates a private key and writes it to `config/watermark_config.json`, which is git-ignored; `config/watermark_config.example.json` shows the schema. Changing the key makes previously generated text undetectable, so texts are tied to the installation that made them. If a config carries Hugging Face's public default key (15485863), the teacher's home page and the desktop app warn about it.

The key never leaves the config file: generation results, sidecars, reports and the About page show only the public parameters (`config.public_watermark`) and a **key id**, a random label stored beside the key and regenerated with it. A review records the key id it was scored with, so the review page can say when a submission was scored under an older key. The key id is random on purpose: any hash of a 31-bit key could be reversed by trying every value.

## Files

| File | Type | Owner | Purpose |
|------|------|-------|---------|
| `config/watermark_config.json` | JSON | `config.py` | Model, sampling and watermark parameters, thresholds, private key and key id, classroom switches (git-ignored; created on first run) |
| `data/users.json` | JSON | `classroom/accounts.py` | Accounts: display name, role, salted password hash, last sign-in |
| `data/classes.json` | JSON | `classroom/classes.py` | Classes: name, term, teacher, join code, archived |
| `data/rosters.csv` | CSV | `classroom/classes.py` | One row per student per class: active, invited or removed |
| `data/assignments.csv` | CSV | `classroom/assignments.py` | Title, instructions, due date, open or closed |
| `data/submissions.csv` | CSV | `classroom/submissions.py` | Index of every submitted version: version, source, SHA-256, word count, current or superseded |
| `data/submissions/…/vNNN.txt` + `.json` | TXT + JSON | `classroom/submissions.py` | The text of each version and its sidecar (how it was produced; the assistant's seed and model, never the key) |
| `data/reviews.csv` | CSV | `classroom/reviews.py` | One row per scoring: numbers, model id, key id, decision, note, returned |
| `data/reports/*.csv` | CSV | `classroom/reports.py`, `classes.py` | Exported assignment tables, class summaries and rosters |
| `data/backups/*` | copies | `classroom/store.py` | A copy of any JSON or CSV file taken before it is rewritten |
| `logs/detection_history.csv` | CSV | `history.py` | One row per detection, lab or classroom, with a unique `run_id` |
| `logs/exports/*` | CSV, JSON | `history.py`, `experiment.py`, `ui/lab.py` | Lab exports, batch settings and summaries, history backups |
| `generated/{normal,watermarked}/*.txt` + `.json` | TXT + JSON | `ui/lab.py`, `main.py` | Lab generations and their sidecars |
| `prompts/experiment_prompts.txt` | TXT | `experiment.py` | 100 prompts for the batch experiment |
| `classroom/demo_texts/*.txt` | TXT | `classroom/seed_demo.py` | Four essays written by people, for the demo class |

## File handling

Every write follows the same rules (`classroom/store.py`, `history.py`): paths come from `pathlib` anchored on the project folder; text files are opened with `encoding="utf-8"`; CSV files go through `csv.DictWriter`/`DictReader` with a fixed column list and `newline=""`; a rewrite first copies the old file to a backup, then writes a temporary file and swaps it in with `os.replace`, so a crash never leaves half a file; a file with unexpected columns is refused, not "repaired"; new files never overwrite old ones. One lock per file keeps two browser sessions from interleaving a read-modify-write.

When a file cannot be read or written, for example a CSV that is open in Excel (which locks the files it opens), the page shows a message naming the file and nothing is left half-done: a hand-in that fails removes the two files it had just created, and scoring checks both the history log and `reviews.csv` before the detector runs and takes the log row back out if the review row still fails. Files are read with `encoding="utf-8-sig"`, so a file saved back by Excel or Notepad (which may add a byte-order mark) still reads, and dates in the forms Excel writes (`10/15/2026`) are understood. A damaged `config/watermark_config.json` stops the app with a message instead of being replaced, because a replacement would carry a new key and earlier texts would silently stop being detected.

What the teacher's actions do to the files:

| Teacher action | Reads | Writes | Updates | Processes |
|---|---|---|---|---|
| Sign in | `users.json` | | last sign-in | verifies the password hash |
| Create a class, new join code | `classes.json` | `classes.json` (backup) | join code | makes a unique code |
| Import a roster | the uploaded CSV, `users.json` | `rosters.csv` (one backed-up rewrite) | invited → active when the student registers | validates usernames: enrol, invite or skip |
| Export a roster | `rosters.csv`, `users.json` | `data/reports/roster_*.csv` | | joins names to usernames |
| Remove a student | `rosters.csv` | backup | status → removed | exactly one row must match |
| Create, close, reopen an assignment | `assignments.csv` | a row | status | |
| Open a submission | `vNNN.txt`, its sidecar, `reviews.csv` | | | |
| Score one or all submissions | the texts | a history row and a review row each | | tokenises and runs the z-test |
| Decide, return | `reviews.csv` | backup | decision, note, returned (a copy of the decision and note the student sees) | a decision changed after returning waits for the next return |
| Export a report | roster, submissions, reviews | `data/reports/assignment_*.csv`, `class_*_summary_*.csv` | | pandas left joins, one state per student |
| Lab pages | history CSV, prompts, TXT uploads | TXT + JSON, new CSVs | note or filename of one record | summaries, charts, batch rates |

Students read their assignments and their own files, and write one TXT + JSON pair per version; they never update or delete anything.

## Installation

Requires **Python 3.11+**.

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

## Running

```bash
streamlit run app.py
```

It opens at http://localhost:8501 (bound to localhost in `.streamlit/config.toml`). The first visit shows a setup screen that creates the teacher account. The model (about 1 GB) downloads into `~/.cache/huggingface/hub` the first time a page needs it; signing in and browsing never wait for it.

A demo class for presentations (teacher `prof`, students `alice`, `ben`, `chloe`, `dan`, `eva`; four essays written by people and one drafted with the assistant, all scored). The demo accounts get the password you pass with `--password`, or a random one that is printed at the end; no password is written in the code:

```bash
python -m classroom.seed_demo                        # about two minutes on a CPU
python -m classroom.seed_demo --password "..."       # choose the demo accounts' password
python -m classroom.seed_demo --no-model             # quick: essays only, nothing scored
python -m classroom.seed_demo --reset                # move data/ aside first (renamed, never deleted)
```

The teacher's home page offers the same demo when there are no classes yet; it asks for the demo students' password first.

Passwords need at least eight characters, may not be one of the most common passwords and may not contain the username. An older account with a weak password still signs in and is asked to change it.

More teachers, and password resets, from the command line:

```bash
python -m classroom.cli create-teacher reyes --display-name "Prof. Reyes"
python -m classroom.cli list-users
python -m classroom.cli reset-password alice
```

To switch the student's assistant off, set `"assistant_enabled": false` under `"classroom"` in `config/watermark_config.json`; the rest of the system is unchanged.

The original desktop app still runs on the same config, history and `generated/` folders:

```bash
python main.py
```

Tests (no model download needed; a fake engine stands in for the model):

```bash
pip install pytest
pytest -q
```

## Pages

**Teacher**: Home, Classes (roster, assignments, summary), Review, and under Lab: Generate, Detect, History, Experiment. **Student**: Home, Assignment, My submissions. **Both**: Account (name, password) and About (this README; for the teacher also the list of files MarkText keeps and the configuration with the key hidden).

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

Every row is written as soon as it exists, so an interrupted batch loses at most one generation; `--resume` skips finished cells. Each cell's seed is derived from the seed base and the cell itself (prompt, length, mode, run), so a batch can be repeated exactly and extended with more lengths without changing existing cells. The summary is exported to `logs/exports/experiment_<batch_id>_summary.csv` and shown on the Experiment page.

Measured results (batch `b6299b88`, 2026-09-23, 100 prompts x 150 tokens x both modes, seed base 100, bias 3.0, ratio 0.5, `selfhash`, width 5, CPU):

| Mode | n | Flagged at z ≥ 4 | At or above z ≥ 2 | Mean z | Mean green share | Inconclusive |
|---|---|---|---|---|---|---|
| watermarked | 100 | **86%** (true-positive rate) | 100% | 5.22 | 71.7% | 1% |
| normal | 100 | **0%** (false-positive rate) | 0% | -0.35 | 48.5% | 1% |

Reading it: at 150 tokens the threshold of 4.0 catches 86 of 100 watermarked texts and none of the normal ones; every watermarked text clears 2.0. The smoke batch (3 prompts x 50/150/300 tokens) showed 100% at 300 tokens and 0% at 50 tokens, where everything is inconclusive. Ten of the 200 texts (7 normal, 3 watermarked) re-tokenized to a different count than they were generated with, which is the decode-then-encode gap the detector has to live with.

## Limitations

- Detection recognises only text generated by this installation's assistant, with the same key and parameters. It is not a general AI-text detector.
- Short texts give little evidence; below 100 scored tokens the verdict is INCONCLUSIVE.
- Editing, paraphrasing or heavily rewriting a draft weakens or destroys the watermark, so a low score is not proof of independent work.
- The key is a symmetric secret: leaking it allows forgery; rotating it orphans old texts (reviews say which key scored them).
- Sign-in lasts for one browser tab: reloading the page signs you out. The files are meant for one server process; two servers on one `data/` folder are not supported.
- Detection assumes independent scored positions. Repeated n-grams are counted once; overlapping n-grams still share tokens, so the z-score remains an approximation.
- The underlying model generates from its own training data; MarkText does not claim ownership of it.

## Assignment requirements mapping

- **Purpose and target users**: a classroom system in which a teacher checks whether submissions were drafted with the class's watermarking assistant; users are the teacher, the students, and lecturers or researchers in the Lab. See "Purpose and users".
- **Main features**: accounts and roles, classes with join codes and rosters, assignments, versioned submissions, scoring, decisions and returns, reports, the assistant, and the Lab (generation, detection, history, experiment).
- **Files/data**: JSON (config, accounts, classes, sidecars), CSV (rosters, assignments, submissions index, reviews, detection history, reports), TXT (submissions, generations, prompts), safetensors weights read by the library. See "Files".
- **File handling**: the teacher's actions read, write, update and process those files through one set of rules (backup, atomic replace, fixed columns, exactly-one-match updates, never overwrite). See "File handling".
- **ML/NLP component**: a pretrained causal language model, a sampling-time watermark, a statistical detector applied to student submissions, and an experiment that measures the detector's error rates, all via Hugging Face Transformers.

## References

- Kirchenbauer, J. et al. "A Watermark for Large Language Models." (2023) [arXiv:2301.10226](https://arxiv.org/abs/2301.10226)
- Kirchenbauer, J. et al. "On the Reliability of Watermarks for Large Language Models." (2023) [arXiv:2306.04634](https://arxiv.org/abs/2306.04634), the paper Hugging Face's implementation cites
- Hugging Face Transformers: [WatermarkingConfig & WatermarkDetector](https://huggingface.co/docs/transformers/generation_strategies#watermarking)
- Qwen2.5: [Hugging Face Model Card](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)
