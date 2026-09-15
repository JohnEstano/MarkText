"""MarkText — Watermarking and Detection of LLM-Generated Text.

Run with:  python main.py

Four-tab Tkinter desktop application:
  1) Generate — prompt the model, normal or watermarked
  2) Detect   — check text for MarkText's watermark
  3) History  — browse / clear detection log
  4) About    — description and limitations
"""

import pathlib
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import config as cfg
import detector
from engine import Engine

BASE_DIR = pathlib.Path(__file__).resolve().parent
GENERATED_DIR = BASE_DIR / "generated"

ABOUT_TEXT = """\
MarkText — Watermarking and Detection of LLM-Generated Text

DESCRIPTION

MarkText demonstrates how generated text can carry an invisible statistical
watermark using the Kirchenbauer et al. green/red list algorithm (2023). The
system wraps a pretrained causal language model (Qwen2.5) with a deterministic
logits processor that biases generation toward green tokens. A separate
detector can later verify the watermark using only the secret key.

LIMITATIONS

- MarkText detects ONLY text it generated with its own watermark key.
  It is NOT a universal AI-text detector.
- Detection requires the same watermark parameters used during generation.
- Enough text is needed for statistics to be meaningful (200+ tokens ideal).
- Editing, paraphrasing, or heavily rewriting text can weaken detection.
- The underlying model (Qwen2.5) generates text based on its training data.

TECHNOLOGY

  Model:           Qwen2.5 (Hugging Face Hub)
  Watermarking:    Kirchenbauer et al. 2023 — green/red list via HF
                   WatermarkingConfig and WatermarkDetector
  GUI:             Tkinter + ttk
  Processing:      Fully local after model download

FILES

  config/watermark_config.json   Watermark parameters (JSON)
  generated/normal/*.txt         Unwatermarked text
  generated/watermarked/*.txt    Watermarked text
  logs/detection_history.csv     Detection log (CSV)

ASSIGNMENT REQUIREMENTS MAPPING

  ML / NLP              Pretrained causal language model (Qwen2.5) +
                        established watermarking algorithm
  Python                Hugging Face Transformers + PyTorch + custom logic
  File handling         JSON config, TXT export, CSV detection log,
                        HF model cache (serialized weights)
  Topic                 Provenance and identification of generative AI output
  No cloud API          Fully local after model download
  No LLM training       Avoids enormous compute
"""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MarkText — Watermarking and Detection of LLM-Generated Text")
        self.geometry("960x740")
        self.minsize(840, 640)

        self.config = cfg.load_config()
        self.engine = None
        self._gen_ok = True
        self._gen_result = ""

        self._ensure_dirs()
        detector.ensure_history()

        self._build_ui()
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
        self.max_tokens_var = tk.StringVar(value="300")
        ttk.Spinbox(sf, from_=50, to=2000, width=7,
                     textvariable=self.max_tokens_var).pack(side="left")
        ttk.Label(sf, text="(50–2000)").pack(side="left", padx=(2, 14))

        self.mode_var = tk.StringVar(value="watermarked")
        ttk.Radiobutton(sf, text="Normal", variable=self.mode_var,
                        value="normal").pack(side="left", padx=4)
        ttk.Radiobutton(sf, text="Watermarked", variable=self.mode_var,
                        value="watermarked").pack(side="left", padx=4)

        self.gen_btn = ttk.Button(sf, text="Generate", command=self._start_generate)
        self.gen_btn.pack(side="left", padx=(18, 0))

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
        ttk.Button(bf, text="Analyze", command=self._analyze).pack(side="left", padx=4)
        ttk.Button(bf, text="Clear", command=self._clear_detect).pack(side="left", padx=4)

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
        ]
        for i, (key, text) in enumerate(labels):
            ttk.Label(rf, text=text + ":", anchor="w", width=18).grid(
                row=i, column=0, sticky="w", padx=8, pady=3)
            var = tk.StringVar(value="—")
            self.det_vars[key] = var
            ttk.Label(rf, textvariable=var, anchor="w",
                      foreground="#2255aa").grid(row=i, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(rf, text="Result:", anchor="w", width=18).grid(
            row=4, column=0, sticky="w", padx=8, pady=3)
        self.det_result_var = tk.StringVar(value="—")
        self.det_result_lbl = ttk.Label(rf, textvariable=self.det_result_var,
                                        anchor="w", font=("", 10, "bold"))
        self.det_result_lbl.grid(row=4, column=1, sticky="w", padx=8, pady=3)

        ttk.Separator(rf, orient="horizontal").grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=8)

        disc = ttk.Label(rf, wraplength=240, justify="left", foreground="#884400",
                         text="MarkText detects ONLY text it generated with "
                              "its own watermark key. It is NOT a universal "
                              "AI-text detector.")
        disc.grid(row=6, column=0, columnspan=2, sticky="nw", padx=8, pady=2)

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

        tf = ttk.Frame(f)
        tf.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)

        cols = ("time", "file", "tokens", "green", "z", "result")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=18)
        hdr = {"time": "Date / Time", "file": "Filename", "tokens": "Tokens",
               "green": "Green %", "z": "Z-score", "result": "Result"}
        wds = {"time": 155, "file": 200, "tokens": 80, "green": 90, "z": 80, "result": 170}
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

    # ----- TAB 4 — ABOUT
    def _build_about_tab(self):
        f = self.tab_about
        txt = tk.Text(f, wrap="word", relief="flat", bg="#f8f8f8",
                      font=("Consolas", 10), padx=12, pady=12)
        sb = ttk.Scrollbar(f, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.insert("1.0", ABOUT_TEXT)
        txt.configure(state="disabled")
        txt.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        sb.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)

    # =============================================================== ENGINE
    def _load_engine_async(self):
        self.set_status("Loading model (may download on first run)...")

        def safe_progress(msg):
            try:
                self.after(0, self.set_status, msg)
            except Exception:
                pass

        t = threading.Thread(target=self._load_worker, args=(safe_progress,), daemon=True)
        t.start()
        self.after(300, self._poll_load, t)

    def _load_worker(self, progress_callback):
        try:
            self.engine = Engine(self.config, progress_callback=progress_callback)
            self._load_ok = True
        except Exception as exc:
            self._load_error = str(exc)
            self._load_ok = False

    def _poll_load(self, t):
        if t.is_alive():
            self.after(300, self._poll_load, t)
        else:
            if getattr(self, "_load_ok", False):
                self.set_status("Ready — " + self.config["model_id"])
            else:
                messagebox.showerror("Model Error",
                                     "Failed to load the model:\n"
                                     + getattr(self, "_load_error", "unknown"))
                self.set_status("Model load failed")

    # ============================================================ GENERATE
    def _start_generate(self):
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showerror("Empty Prompt", "Please enter a prompt.")
            return
        try:
            max_tok = int(self.max_tokens_var.get())
            if max_tok < 1 or max_tok > 2000:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Max Tokens",
                                 "Enter a whole number between 50 and 2000.")
            return
        if self.engine is None:
            messagebox.showerror("No Model", "The model is still loading.")
            return

        mode = self.mode_var.get()
        self.gen_btn.configure(state="disabled")
        self.set_status("Generating{} text...".format(
            " watermarked" if mode == "watermarked" else ""))

        t = threading.Thread(target=self._gen_worker,
                             args=(prompt, max_tok, mode == "watermarked"),
                             daemon=True)
        t.start()
        self.after(200, self._poll_gen, t)

    def _gen_worker(self, prompt, max_tok, watermarked):
        try:
            self._gen_result = self.engine.generate(
                prompt, max_new_tokens=max_tok, watermarked=watermarked)
            self._gen_ok = True
        except Exception as exc:
            self._gen_error = str(exc)
            self._gen_ok = False

    def _poll_gen(self, t):
        if t.is_alive():
            self.after(200, self._poll_gen, t)
            return
        self.gen_btn.configure(state="normal")
        if self._gen_ok:
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", self._gen_result)
            n = len(self._gen_result.split())
            self.gen_status_var.set("{:,} words generated".format(n))
            self.set_status("Done")
        else:
            messagebox.showerror("Generation Error", str(self._gen_error))
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

        mode = self.mode_var.get()
        folder = GENERATED_DIR / mode
        folder.mkdir(parents=True, exist_ok=True)
        import datetime
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
        except OSError as exc:
            messagebox.showerror("Save Failed", str(exc))
            return
        self.gen_status_var.set("Saved: " + p.name)
        messagebox.showinfo("Saved", "Saved to:\n" + str(p))

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
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            messagebox.showerror("File Error", str(exc))
            return
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", text)
        self._detect_filename = pathlib.Path(path).name

    def _analyze(self):
        text = self.input_text.get("1.0", "end").strip()
        if not text:
            messagebox.showerror("Empty Input", "Paste or open text to analyze.")
            return
        if self.engine is None:
            messagebox.showerror("No Model", "The model is still loading.")
            return

        self.set_status("Analyzing...")
        self.update_idletasks()

        try:
            stats = self.engine.detect(text)
        except Exception as exc:
            messagebox.showerror("Detection Error", str(exc))
            self.set_status("Analysis failed")
            return

        if stats is None:
            messagebox.showerror("Too Short",
                                 "Text is too short for analysis. "
                                 "Need at least ~6 tokens (a sentence or two).")
            self.set_status("Text too short")
            return

        green_pct = stats["green_fraction"] * 100.0
        z = stats["z_score"]
        if z >= 4.0:
            result = "LIKELY MARKTEXT-GENERATED"
            color = "#cc0000"
        elif z >= 2.0:
            result = "POSSIBLE WATERMARK"
            color = "#cc8800"
        else:
            result = "NO WATERMARK"
            color = "#228822"

        self.det_vars["tokens"].set(str(stats["num_tokens_scored"]))
        self.det_vars["green"].set(str(stats["num_green_tokens"]))
        self.det_vars["signal"].set("{:.1f}%".format(green_pct))
        self.det_vars["zscore"].set("{:.2f}".format(z))
        self.det_result_var.set(result)
        self.det_result_lbl.configure(foreground=color)

        filename = getattr(self, "_detect_filename", "manual_input")
        detector.append_history(filename, stats)
        self._detect_filename = None
        self._refresh_history()
        self.set_status("Analysis complete")

    def _clear_detect(self):
        self.input_text.delete("1.0", "end")
        self._detect_filename = None
        for v in self.det_vars.values():
            v.set("—")
        self.det_result_var.set("—")
        self.det_result_lbl.configure(foreground="#000000")

    # =========================================================== HISTORY
    def _refresh_history(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in detector.read_history():
            self.tree.insert("", "end", values=(
                row.get("timestamp", ""),
                row.get("filename", ""),
                row.get("tokens_scored", ""),
                row.get("green_fraction", ""),
                row.get("z_score", ""),
                row.get("result", ""),
            ))

    def _clear_history(self):
        if not self.tree.get_children():
            messagebox.showinfo("Empty", "History is already empty.")
            return
        if not messagebox.askyesno("Clear History",
                                   "Delete all detection records?\n"
                                   "The CSV header will be preserved."):
            return
        detector.clear_history()
        self._refresh_history()
        messagebox.showinfo("Cleared", "History cleared.")

    # ============================================================ UTILS
    def set_status(self, msg):
        self.status_var.set(msg)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()