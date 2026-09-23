"""MarkText — Watermarking and Detection of LLM-Generated Text.

Run with:  python main.py

Four-tab Tkinter desktop application:
  1) Generate — prompt the model, normal or watermarked
  2) Detect   — check text for MarkText's watermark
  3) History  — browse / clear detection log
  4) About    — the project README

Threading rule: anything slow (model load, generation, detection) runs in
a daemon thread. Workers only write results to attributes on the App or
to a queue; the main thread polls with after() and is the only thread
that touches widgets.
"""

import csv
import datetime
import json
import pathlib
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import config as cfg
import history
from engine import (
    Engine, LABEL_INCONCLUSIVE, LABEL_LIKELY, LABEL_NOT_DETECTED, LABEL_POSSIBLE,
)

BASE_DIR = pathlib.Path(__file__).resolve().parent
GENERATED_DIR = BASE_DIR / "generated"
README_PATH = BASE_DIR / "README.md"

MIN_TOKENS = 50
MAX_TOKENS = 2000

LABEL_COLORS = {
    LABEL_LIKELY: "#cc0000",
    LABEL_POSSIBLE: "#cc8800",
    LABEL_NOT_DETECTED: "#228822",
    LABEL_INCONCLUSIVE: "#555555",
}

ABOUT_FALLBACK = """\
MarkText — Watermarking and Detection of LLM-Generated Text

README.md was not found next to main.py. See the project repository for
the full description. MarkText detects ONLY text it generated with its own
watermark key and parameters; it is NOT a universal AI-text detector.
"""


def write_sidecar(txt_path, info):
    """Write <name>.json next to a saved text: mode, seed, parameters."""
    side = txt_path.with_suffix(".json")
    record = dict(info)
    record.pop("text", None)
    record["saved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record["text_file"] = txt_path.name
    with open(side, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=4)
    return side


def read_sidecar(txt_path):
    side = txt_path.with_suffix(".json")
    if not side.exists():
        return None
    try:
        with open(side, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MarkText — Watermarking and Detection of LLM-Generated Text")
        self.geometry("960x740")
        self.minsize(840, 640)

        # `settings`, not `config`: tk.Tk.config is a Tk method (alias of configure)
        self.config_notes = []
        try:
            self.settings = cfg.load_config(notes=self.config_notes)
        except ValueError as exc:
            messagebox.showerror("Configuration Error", str(exc))
            raise

        # all cross-thread state exists from the start
        self.engine = None
        self.load_state = "loading"          # loading | ready | failed
        self.load_error = ""
        self.progress_queue = queue.Queue()
        self.gen_result = None               # dict from Engine.generate
        self.gen_error = ""
        self.gen_cancel = threading.Event()
        self.det_result = None               # dict from Engine.detect, or None
        self.det_error = ""
        self.det_too_short = False
        self.detect_filename = ""
        self.detect_loaded_text = ""
        self.detect_sidecar = None

        self._ensure_dirs()
        history.ensure_history()

        self._build_ui()
        self._show_config_notes()
        self._load_engine_async()

    # ---------------------------------------------------------------- dirs
    def _ensure_dirs(self):
        for d in (
            BASE_DIR / "config",
            GENERATED_DIR / "normal",
            GENERATED_DIR / "watermarked",
            BASE_DIR / "logs",
        ):
            d.mkdir(parents=True, exist_ok=True)

    def _show_config_notes(self):
        if self.config_notes:
            messagebox.showwarning("Configuration", "\n\n".join(self.config_notes))

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        self.tab_gen = ttk.Frame(self.notebook)
        self.tab_det = ttk.Frame(self.notebook)
        self.tab_hist = ttk.Frame(self.notebook)
        self.tab_about = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_gen, text="  Generate  ")
        self.notebook.add(self.tab_det, text="  Detect  ")
        self.notebook.add(self.tab_hist, text="  History  ")
        self.notebook.add(self.tab_about, text="  About  ")

        self._build_generate_tab()
        self._build_detect_tab()
        self._build_history_tab()
        self._build_about_tab()

        self.status_var = tk.StringVar(value="Starting...")
        tk.Label(self, textvariable=self.status_var, anchor="w",
                 relief="sunken", bg="#eeeeee", padx=8).pack(
            fill="x", side="bottom", padx=8, pady=(0, 8))

    # ----- TAB 1 — GENERATE
    def _build_generate_tab(self):
        f = self.tab_gen

        ttk.Label(f, text="Prompt:").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        pf = ttk.Frame(f)
        pf.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=12, pady=4)
        self.prompt_text = tk.Text(pf, wrap="word", height=6, relief="solid")
        ps = ttk.Scrollbar(pf, command=self.prompt_text.yview)
        self.prompt_text.configure(yscrollcommand=ps.set)
        self.prompt_text.grid(row=0, column=0, sticky="nsew")
        ps.grid(row=0, column=1, sticky="ns")
        pf.columnconfigure(0, weight=1)
        pf.rowconfigure(0, weight=1)
        self.prompt_text.insert("1.0", "Tell me about the history of cryptography.")

        sf = ttk.Frame(f)
        sf.grid(row=2, column=0, columnspan=4, sticky="ew", padx=12, pady=4)

        ttk.Label(sf, text="Max tokens:").pack(side="left", padx=(0, 4))
        default_tokens = min(max(int(self.settings.get("max_new_tokens", 300)),
                                 MIN_TOKENS), MAX_TOKENS)
        self.max_tokens_var = tk.StringVar(value=str(default_tokens))
        ttk.Spinbox(sf, from_=MIN_TOKENS, to=MAX_TOKENS, width=7,
                     textvariable=self.max_tokens_var).pack(side="left")
        ttk.Label(sf, text="({}–{})".format(MIN_TOKENS, MAX_TOKENS)).pack(
            side="left", padx=(2, 14))

        self.mode_var = tk.StringVar(value="watermarked")
        ttk.Radiobutton(sf, text="Normal", variable=self.mode_var,
                        value="normal").pack(side="left", padx=4)
        ttk.Radiobutton(sf, text="Watermarked", variable=self.mode_var,
                        value="watermarked").pack(side="left", padx=4)

        self.gen_btn = ttk.Button(sf, text="Generate", command=self._start_generate)
        self.gen_btn.pack(side="left", padx=(18, 0))
        self.cancel_btn = ttk.Button(sf, text="Cancel", command=self._cancel_generate,
                                     state="disabled")
        self.cancel_btn.pack(side="left", padx=4)

        ttk.Label(f, text="Output:").grid(row=3, column=0, sticky="w", padx=12, pady=(6, 0))
        of = ttk.Frame(f)
        of.grid(row=4, column=0, columnspan=4, sticky="nsew", padx=12, pady=4)
        self.output_text = tk.Text(of, wrap="word", height=18, relief="solid")
        os_ = ttk.Scrollbar(of, command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=os_.set)
        self.output_text.grid(row=0, column=0, sticky="nsew")
        os_.grid(row=0, column=1, sticky="ns")
        of.columnconfigure(0, weight=1)
        of.rowconfigure(0, weight=1)

        bf = ttk.Frame(f)
        bf.grid(row=5, column=0, columnspan=4, sticky="ew", padx=12, pady=(4, 8))
        ttk.Button(bf, text="Copy Text", command=self._copy_output).pack(side="left", padx=4)
        ttk.Button(bf, text="Save .TXT", command=self._save_output).pack(side="left", padx=4)
        ttk.Button(bf, text="Clear", command=self._clear_generate).pack(side="left", padx=4)
        self.gen_status_var = tk.StringVar(value="")
        ttk.Label(bf, textvariable=self.gen_status_var,
                  foreground="#555").pack(side="right", padx=8)

        f.rowconfigure(4, weight=1)
        f.columnconfigure(0, weight=1)

    # ----- TAB 2 — DETECT
    def _build_detect_tab(self):
        f = self.tab_det

        bf = ttk.Frame(f)
        bf.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 4))
        ttk.Button(bf, text="Open TXT", command=self._open_for_detect).pack(side="left", padx=4)
        self.analyze_btn = ttk.Button(bf, text="Analyze", command=self._analyze)
        self.analyze_btn.pack(side="left", padx=4)
        ttk.Button(bf, text="Clear", command=self._clear_detect).pack(side="left", padx=4)
        self.det_source_var = tk.StringVar(value="")
        ttk.Label(bf, textvariable=self.det_source_var,
                  foreground="#555").pack(side="left", padx=12)

        inf = ttk.LabelFrame(f, text=" Text to Analyze ")
        inf.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=6)
        self.input_text = tk.Text(inf, wrap="word", height=22, relief="solid")
        is_ = ttk.Scrollbar(inf, command=self.input_text.yview)
        self.input_text.configure(yscrollcommand=is_.set)
        self.input_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        is_.grid(row=0, column=1, sticky="ns")
        inf.columnconfigure(0, weight=1)
        inf.rowconfigure(0, weight=1)

        rf = ttk.LabelFrame(f, text=" Detection Results ")
        rf.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=6)

        self.det_vars = {}
        labels = [
            ("tokens", "Tokens analyzed"),
            ("green", "Green tokens"),
            ("signal", "Watermark signal"),
            ("zscore", "Z-score"),
            ("pvalue", "p-value"),
        ]
        for i, (key, text) in enumerate(labels):
            ttk.Label(rf, text=text + ":", anchor="w", width=18).grid(
                row=i, column=0, sticky="w", padx=8, pady=3)
            var = tk.StringVar(value="—")
            self.det_vars[key] = var
            ttk.Label(rf, textvariable=var, anchor="w",
                      foreground="#2255aa").grid(row=i, column=1, sticky="w", padx=8, pady=3)

        row = len(labels)
        ttk.Label(rf, text="Result:", anchor="w", width=18).grid(
            row=row, column=0, sticky="w", padx=8, pady=3)
        self.det_result_var = tk.StringVar(value="—")
        self.det_result_lbl = ttk.Label(rf, textvariable=self.det_result_var,
                                        anchor="w", font=("", 10, "bold"))
        self.det_result_lbl.grid(row=row, column=1, sticky="w", padx=8, pady=3)

        ttk.Separator(rf, orient="horizontal").grid(
            row=row + 1, column=0, columnspan=2, sticky="ew", padx=8, pady=8)

        disc = ttk.Label(rf, wraplength=240, justify="left", foreground="#884400",
                         text="MarkText detects ONLY text it generated with "
                              "its own watermark key and parameters. It is NOT "
                              "a universal AI-text detector. 'NOT DETECTED' "
                              "means this watermark was not found, not that a "
                              "human wrote the text.")
        disc.grid(row=row + 2, column=0, columnspan=2, sticky="nw", padx=8, pady=2)

        f.rowconfigure(1, weight=1)
        f.columnconfigure(0, weight=2)
        f.columnconfigure(1, weight=1)

    # ----- TAB 3 — HISTORY
    def _build_history_tab(self):
        f = self.tab_hist

        bf = ttk.Frame(f)
        bf.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        ttk.Button(bf, text="Refresh", command=self._refresh_history).pack(side="left", padx=4)
        ttk.Button(bf, text="Clear History", command=self._clear_history).pack(side="left", padx=4)
        ttk.Label(bf, text="Filtering, charts, export, record editing and the batch "
                           "experiment: run the web app (streamlit run app.py).",
                  foreground="#555").pack(side="left", padx=12)

        tf = ttk.Frame(f)
        tf.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)

        cols = ("id", "time", "source", "file", "mode", "tokens", "green", "z", "p", "result")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=18)
        hdr = {"id": "Run id", "time": "Date / Time", "source": "Source", "file": "Filename",
               "mode": "Mode", "tokens": "Tokens", "green": "Green %", "z": "Z-score",
               "p": "p-value", "result": "Result"}
        wds = {"id": 80, "time": 140, "source": 70, "file": 170, "mode": 90, "tokens": 65,
               "green": 70, "z": 65, "p": 80, "result": 180}
        for c in cols:
            self.tree.heading(c, text=hdr[c])
            self.tree.column(c, width=wds[c], anchor="w")

        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.columnconfigure(0, weight=1)
        tf.rowconfigure(0, weight=1)

        f.rowconfigure(1, weight=1)
        f.columnconfigure(0, weight=1)

        self._refresh_history()

    # ----- TAB 4 — ABOUT (the README, read from disk)
    def _build_about_tab(self):
        f = self.tab_about
        try:
            about = README_PATH.read_text(encoding="utf-8-sig")
        except OSError:
            about = ABOUT_FALLBACK
        txt = tk.Text(f, wrap="word", relief="flat", bg="#f8f8f8",
                      font=("Consolas", 10), padx=12, pady=12)
        sb = ttk.Scrollbar(f, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.insert("1.0", about)
        txt.configure(state="disabled")
        txt.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        sb.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)

    # =============================================================== ENGINE
    def _load_engine_async(self):
        self.set_status("Loading model (may download on first run)...")
        t = threading.Thread(target=self._load_worker, daemon=True)
        t.start()
        self.after(300, self._poll_load, t)

    def _load_worker(self):
        # runs on the worker: no widget access, progress goes through the queue
        try:
            self.engine = Engine(self.settings, progress_callback=self.progress_queue.put)
            self.load_state = "ready"
        except Exception as exc:
            self.load_error = str(exc)
            self.load_state = "failed"

    def _poll_load(self, t):
        while True:
            try:
                self.set_status(self.progress_queue.get_nowait())
            except queue.Empty:
                break
        if t.is_alive():
            self.after(300, self._poll_load, t)
            return
        if self.load_state == "ready":
            self.set_status("Ready — {} on {}".format(
                self.settings["model_id"], self.engine.device))
        else:
            messagebox.showerror("Model Error",
                                 "Failed to load the model:\n" + self.load_error)
            self.set_status("Model load failed")

    def _engine_ready(self):
        """Explain the engine's state to the user; True only when usable."""
        if self.load_state == "ready":
            return True
        if self.load_state == "failed":
            messagebox.showerror("No Model", "The model failed to load:\n" + self.load_error)
        else:
            messagebox.showinfo("No Model", "The model is still loading. Please wait.")
        return False

    # ============================================================ GENERATE
    def _start_generate(self):
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showerror("Empty Prompt", "Please enter a prompt.")
            return
        try:
            max_tok = int(self.max_tokens_var.get())
            if not MIN_TOKENS <= max_tok <= MAX_TOKENS:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Max Tokens",
                                 "Enter a whole number between {} and {}.".format(
                                     MIN_TOKENS, MAX_TOKENS))
            return
        if not self._engine_ready():
            return

        mode = self.mode_var.get()
        self.gen_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.gen_cancel.clear()
        self.set_status("Generating{} text...".format(
            " watermarked" if mode == "watermarked" else ""))

        t = threading.Thread(target=self._gen_worker,
                             args=(prompt, max_tok, mode == "watermarked"),
                             daemon=True)
        t.start()
        self.after(200, self._poll_gen, t)

    def _cancel_generate(self):
        self.gen_cancel.set()
        self.set_status("Cancelling after the current token...")

    def _gen_worker(self, prompt, max_tok, watermarked):
        try:
            self.gen_result = self.engine.generate(
                prompt, max_new_tokens=max_tok, watermarked=watermarked,
                cancel_event=self.gen_cancel)
            self.gen_error = ""
        except Exception as exc:
            self.gen_result = None
            self.gen_error = str(exc)

    def _poll_gen(self, t):
        if t.is_alive():
            self.after(200, self._poll_gen, t)
            return
        self.gen_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if self.gen_result is not None:
            info = self.gen_result
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", info["text"])
            n = len(info["text"].split())
            self.gen_status_var.set("{:,} words, {} mode, seed {}{}".format(
                n, info["mode"], info["seed"], " (cancelled)" if info["cancelled"] else ""))
            self.set_status("Done" if not info["cancelled"] else "Generation cancelled")
        else:
            messagebox.showerror("Generation Error", self.gen_error)
            self.set_status("Generation failed")

    def _copy_output(self):
        text = self.output_text.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.gen_status_var.set("Copied to clipboard")

    def _save_output(self):
        text = self.output_text.get("1.0", "end").strip()
        if not text:
            messagebox.showerror("Nothing to Save", "Generate some text first.")
            return
        # the folder follows how the text was generated, not the radio's
        # current position; edited text is still tagged with its origin
        info = self.gen_result or {}
        mode = info.get("mode", self.mode_var.get())
        folder = GENERATED_DIR / mode
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = "marktext_{}_{}.txt".format(mode, stamp)

        path = filedialog.asksaveasfilename(
            title="Save generated text",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(folder),
            initialfile=default,
        )
        if not path:
            return
        p = pathlib.Path(path)
        if p.suffix.lower() != ".txt":
            p = p.with_suffix(".txt")
        try:
            p.write_text(text, encoding="utf-8")
            side = write_sidecar(p, info) if info else None
        except OSError as exc:
            messagebox.showerror("Save Failed", str(exc))
            return
        self.gen_status_var.set("Saved: " + p.name)
        messagebox.showinfo("Saved", "Saved to:\n{}{}".format(
            p, "\nParameters in:\n{}".format(side) if side else ""))

    def _clear_generate(self):
        self.output_text.delete("1.0", "end")
        self.gen_status_var.set("")

    # ============================================================= DETECT
    def _open_for_detect(self):
        path = filedialog.askopenfilename(
            title="Open text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(GENERATED_DIR),
        )
        if not path:
            return
        p = pathlib.Path(path)
        try:
            text = p.read_text(encoding="utf-8-sig")   # tolerate a BOM
        except (OSError, UnicodeDecodeError) as exc:
            messagebox.showerror("File Error", str(exc))
            return
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", text)
        self.detect_filename = p.name
        self.detect_loaded_text = text.strip()
        side = read_sidecar(p)
        self.detect_sidecar = side
        self.det_source_var.set("{} ({} mode, seed {})".format(
            p.name, side.get("mode", "?"), side.get("seed", "?")) if side else p.name)

    def _analyze(self):
        text = self.input_text.get("1.0", "end").strip()
        if not text:
            messagebox.showerror("Empty Input", "Paste or open text to analyze.")
            return
        if not self._engine_ready():
            return

        self.analyze_btn.configure(state="disabled")
        self.set_status("Analyzing...")
        t = threading.Thread(target=self._det_worker, args=(text,), daemon=True)
        t.start()
        self.after(200, self._poll_detect, t, text)

    def _det_worker(self, text):
        try:
            self.det_result = self.engine.detect(text)
            self.det_too_short = self.det_result is None
            self.det_error = ""
        except Exception as exc:
            self.det_result = None
            self.det_too_short = False
            self.det_error = str(exc)

    def _poll_detect(self, t, text):
        if t.is_alive():
            self.after(200, self._poll_detect, t, text)
            return
        self.analyze_btn.configure(state="normal")

        if self.det_error:
            messagebox.showerror("Detection Error", self.det_error)
            self.set_status("Analysis failed")
            return
        if self.det_too_short:
            messagebox.showerror("Too Short",
                                 "Text is too short for analysis. Need at least "
                                 "{} tokens (a sentence or two).".format(self.engine.min_tokens))
            self.set_status("Text too short")
            return

        stats = self.det_result
        self.det_vars["tokens"].set(str(stats["num_tokens_scored"]))
        self.det_vars["green"].set(str(stats["num_green_tokens"]))
        self.det_vars["signal"].set("{:.1f}%".format(stats["green_fraction"] * 100.0))
        self.det_vars["zscore"].set("{:.2f}".format(stats["z_score"]))
        self.det_vars["pvalue"].set("{:.2e}".format(stats["p_value"]))
        self.det_result_var.set(stats["label"])
        self.det_result_lbl.configure(foreground=LABEL_COLORS.get(stats["label"], "#000000"))

        # the file name applies only while the box still holds that file's text
        unchanged = self.detect_filename and text == self.detect_loaded_text
        extra = {}
        if unchanged and self.detect_sidecar:
            side = self.detect_sidecar
            extra = {"mode": side.get("mode", ""), "seed": side.get("seed", ""),
                     "max_new_tokens": side.get("max_new_tokens", ""),
                     "gen_tokens": side.get("new_tokens", "")}
        try:
            history.append_history(stats,
                                   source="file" if unchanged else "manual",
                                   filename=self.detect_filename if unchanged else "",
                                   extra=extra)
        except OSError as exc:
            messagebox.showerror("History Not Saved",
                                 "The result is shown but could not be logged "
                                 "(is the CSV open in Excel?):\n" + str(exc))
            self.set_status("Analysis complete (not logged)")
            return
        self._refresh_history()
        self.set_status("Analysis complete")

    def _clear_detect(self):
        self.input_text.delete("1.0", "end")
        self.detect_filename = ""
        self.detect_loaded_text = ""
        self.detect_sidecar = None
        self.det_source_var.set("")
        for v in self.det_vars.values():
            v.set("—")
        self.det_result_var.set("—")
        self.det_result_lbl.configure(foreground="#000000")

    # =========================================================== HISTORY
    def _refresh_history(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        try:
            rows = history.read_history()
        except (OSError, csv.Error, UnicodeDecodeError, ValueError) as exc:
            messagebox.showerror("History Error",
                                 "Could not read the history CSV:\n" + str(exc))
            return
        for row in rows:
            self.tree.insert("", "end", values=(
                row.get("run_id", ""),
                row.get("timestamp", ""),
                row.get("source", ""),
                row.get("filename", ""),
                row.get("mode", ""),
                row.get("tokens_scored", ""),
                row.get("green_pct", ""),
                row.get("z_score", ""),
                row.get("p_value", ""),
                row.get("result", ""),
            ))

    def _clear_history(self):
        if not self.tree.get_children():
            messagebox.showinfo("Empty", "History is already empty.")
            return
        if not messagebox.askyesno("Clear History",
                                   "Delete all detection records?\n"
                                   "A backup copy is written to logs/exports/ first."):
            return
        try:
            backup = history.clear_history()
        except OSError as exc:
            messagebox.showerror("Clear Failed", str(exc))
            return
        self._refresh_history()
        messagebox.showinfo("Cleared", "History cleared.\nBackup: " + str(backup))

    # ============================================================ UTILS
    def set_status(self, msg):
        self.status_var.set(msg)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
