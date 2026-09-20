"""MarkText — Streamlit web front-end.

Run with:  streamlit run app.py

Same four sections as the Tkinter app (main.py), built on the same core:
  config.py    JSON configuration
  engine.py    generation + watermark detection
  detector.py  CSV detection history

Streamlit reruns this whole script on every interaction, so anything that
must survive a rerun lives in st.session_state (per browser tab) or in
st.cache_resource (the model, shared by the whole server process).
"""

import datetime
import pathlib
import threading

import streamlit as st

import config as cfg
import detector
from engine import Engine

BASE_DIR = pathlib.Path(__file__).resolve().parent
GENERATED_DIR = BASE_DIR / "generated"

MIN_TOKENS = 50
MAX_TOKENS = 2000

# classify_z() label -> Streamlit call that renders it in a matching colour
VERDICT_STYLE = {
    "LIKELY MARKTEXT": st.error,
    "POSSIBLE WATERMARK": st.warning,
    "NO WATERMARK": st.success,
}

ABOUT_MD = """\
### MarkText — Watermarking and Detection of LLM-Generated Text

MarkText is an educational demo of text provenance watermarking. It generates
text with a local pretrained language model (Qwen2.5) and can bias sampling
toward a keyed "green list" of tokens (Kirchenbauer et al., 2023,
arXiv:2301.10226) through Hugging Face `WatermarkingConfig`. The Detect tab
re-tokenizes a text, counts green tokens with `WatermarkDetector`, and reports
a z-score.

**Limitations**

- MarkText detects ONLY text it generated with its own watermark key,
  parameters and tokenizer. It is NOT a universal AI-text detector.
- A low z-score means this watermark was not found. It does not show that a
  human wrote the text.
- Short texts carry little evidence; editing or paraphrasing weakens the signal.

**Two front-ends, one core**

- `app.py` (this page): Streamlit, `streamlit run app.py`
- `main.py`: Tkinter desktop window, `python main.py`

Both share `engine.py`, `config.py`, `detector.py` and the same files:

| File | Format | Used for |
|---|---|---|
| `config/watermark_config.json` | JSON | model id, sampling and watermark parameters |
| `generated/normal/*.txt`, `generated/watermarked/*.txt` | TXT | saved generations |
| `logs/detection_history.csv` | CSV | one row per analysis |

Everything runs locally after the model has been downloaded once.
"""


# ---------------------------------------------------------------- resources
@st.cache_resource(show_spinner="Loading model (first run may download ~1 GB)...")
def get_engine():
    """Load the model once per server process; every session shares it.

    The lock serialises model and detector calls, because the cached Engine
    is one object shared by all browser tabs.
    """
    return Engine(cfg.load_config()), threading.Lock()


def ensure_dirs():
    for d in (GENERATED_DIR / "normal", GENERATED_DIR / "watermarked"):
        d.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------ file handling
def save_txt(text, mode):
    folder = GENERATED_DIR / mode
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / default_filename(mode)
    path.write_text(text, encoding="utf-8")
    return path


def default_filename(mode):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return "marktext_{}_{}.txt".format(mode, stamp)


# ---------------------------------------------------------------- callbacks
# Callbacks run before the rerun, which is the only moment a widget's value
# may be set through st.session_state.
def on_save():
    state = st.session_state
    try:
        state["gen_saved"] = str(save_txt(state["gen_text"], state["gen_mode"]))
        state["gen_save_error"] = ""
    except OSError as exc:
        state["gen_saved"] = ""
        state["gen_save_error"] = str(exc)


def on_upload():
    state = st.session_state
    state["upload_error"] = ""
    uploaded = state.get("uploader")
    if uploaded is None:
        state["detect_filename"] = ""
        state["detect_loaded"] = ""
        return
    try:
        text = uploaded.getvalue().decode("utf-8")
    except UnicodeDecodeError as exc:
        state["upload_error"] = "{} is not valid UTF-8 text: {}".format(uploaded.name, exc)
        return
    state["detect_text"] = text
    state["detect_loaded"] = text.strip()
    state["detect_filename"] = uploaded.name
    state["detect_stats"] = None


def on_clear_detect():
    state = st.session_state
    state["detect_text"] = ""
    state["detect_loaded"] = ""
    state["detect_filename"] = ""
    state["detect_stats"] = None
    state["upload_error"] = ""


def on_clear_history():
    state = st.session_state
    try:
        detector.clear_history()
        state["history_msg"] = "History cleared."
    except OSError as exc:
        state["history_msg"] = "Could not clear history: {}".format(exc)
    state["confirm_clear"] = False


# --------------------------------------------------------------------- page
st.set_page_config(page_title="MarkText", layout="wide")
st.title("MarkText")
st.caption("Watermarking and Detection of LLM-Generated Text")

config = cfg.load_config()
ensure_dirs()

state = st.session_state
for key, default in (
    ("gen_text", ""), ("gen_mode", ""), ("gen_saved", ""), ("gen_save_error", ""),
    ("detect_text", ""), ("detect_loaded", ""), ("detect_filename", ""),
    ("detect_stats", None), ("upload_error", ""), ("history_msg", ""),
):
    state.setdefault(key, default)

try:
    engine, engine_lock = get_engine()
except Exception as exc:
    st.error("Failed to load the model:\n\n{}".format(exc))
    st.stop()

st.caption("Ready — {} on {}".format(config["model_id"], engine.device))

tab_gen, tab_det, tab_hist, tab_about = st.tabs(
    ["Generate", "Detect", "History", "About"])

# ----- TAB 1 — GENERATE
with tab_gen:
    with st.form("generate_form"):
        prompt = st.text_area("Prompt", height=140,
                              value="Tell me about the history of cryptography.")
        col_tok, col_mode = st.columns(2)
        default_tokens = min(max(int(config.get("max_new_tokens", 300)), MIN_TOKENS),
                             MAX_TOKENS)
        max_tok = col_tok.number_input(
            "Max tokens ({}–{})".format(MIN_TOKENS, MAX_TOKENS),
            min_value=MIN_TOKENS, max_value=MAX_TOKENS,
            value=default_tokens, step=10)
        mode_label = col_mode.radio("Mode", ["Watermarked", "Normal"], horizontal=True)
        submitted = st.form_submit_button("Generate", type="primary")

    if submitted:
        if not prompt.strip():
            st.error("Please enter a prompt.")
        else:
            mode = mode_label.lower()
            try:
                with st.spinner("Generating {} text...".format(mode)):
                    with engine_lock:
                        text = engine.generate(prompt.strip(),
                                               max_new_tokens=int(max_tok),
                                               watermarked=(mode == "watermarked"))
            except Exception as exc:
                st.error("Generation failed: {}".format(exc))
            else:
                # remember the mode this text was made with, not the radio's
                # later position
                state["gen_text"] = text
                state["gen_mode"] = mode
                state["gen_saved"] = ""
                state["gen_save_error"] = ""

    if state["gen_text"]:
        st.subheader("Output ({})".format(state["gen_mode"]))
        # st.code gives a built-in copy-to-clipboard button
        st.code(state["gen_text"], language=None, wrap_lines=True)
        st.caption("{:,} words generated".format(len(state["gen_text"].split())))
        st.download_button(
            "Save .TXT",
            data=state["gen_text"].encode("utf-8"),
            file_name=default_filename(state["gen_mode"]),
            mime="text/plain",
            on_click=on_save,
            help="Writes the text into generated/{}/ and downloads a copy.".format(
                state["gen_mode"]))
        if state["gen_saved"]:
            st.success("Saved to: {}".format(state["gen_saved"]))
        if state["gen_save_error"]:
            st.error("Save failed: {}".format(state["gen_save_error"]))

# ----- TAB 2 — DETECT
with tab_det:
    col_in, col_out = st.columns([2, 1])

    with col_in:
        st.file_uploader("Open TXT", type=["txt"], key="uploader", on_change=on_upload)
        if state["upload_error"]:
            st.error(state["upload_error"])
        st.text_area("Text to analyze", key="detect_text", height=380)
        col_a, col_c = st.columns(2)
        analyze = col_a.button("Analyze", type="primary")
        col_c.button("Clear", on_click=on_clear_detect)

    if analyze:
        text = state["detect_text"].strip()
        state["detect_stats"] = None
        if not text:
            col_in.error("Paste or open text to analyze.")
        else:
            try:
                with st.spinner("Analyzing..."):
                    with engine_lock:
                        stats = engine.detect(text)
            except Exception as exc:
                col_in.error("Detection failed: {}".format(exc))
            else:
                if stats is None:
                    col_in.warning("Text is too short for analysis. "
                                   "Need at least ~6 tokens (a sentence or two).")
                else:
                    state["detect_stats"] = stats
                    # the file name only applies if the box still holds that file
                    unchanged = state["detect_filename"] and text == state["detect_loaded"]
                    filename = state["detect_filename"] if unchanged else "manual_input"
                    try:
                        detector.append_history(filename, stats)
                    except OSError as exc:
                        col_in.error("Result shown but NOT logged; could not write "
                                     "the history CSV (is it open in Excel?): "
                                     "{}".format(exc))

    with col_out:
        st.subheader("Detection Results")
        stats = state["detect_stats"]
        if stats is None:
            st.write("—")
        else:
            m1, m2 = st.columns(2)
            m1.metric("Tokens analyzed", stats["num_tokens_scored"])
            m2.metric("Green tokens", stats["num_green_tokens"])
            m1.metric("Watermark signal", "{:.1f}%".format(stats["green_fraction"] * 100.0))
            m2.metric("Z-score", "{:.2f}".format(stats["z_score"]))
            verdict = detector.classify_z(stats["z_score"])
            VERDICT_STYLE.get(verdict, st.info)(verdict)
        st.caption("MarkText detects ONLY text it generated with its own watermark "
                   "key. It is NOT a universal AI-text detector.")

# ----- TAB 3 — HISTORY
with tab_hist:
    if state["history_msg"]:
        st.info(state["history_msg"])
        state["history_msg"] = ""

    try:
        detector.ensure_history()
        rows = detector.read_history()
    except OSError as exc:
        rows = []
        st.error("Could not read the history CSV: {}".format(exc))

    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption("{} analyses, newest first — {}".format(
            len(rows), detector.HISTORY_PATH))
        confirm = st.checkbox("Yes, delete all detection records "
                              "(the CSV header is kept)", key="confirm_clear")
        st.button("Clear History", disabled=not confirm, on_click=on_clear_history)
    else:
        st.write("No detection history yet.")

# ----- TAB 4 — ABOUT
with tab_about:
    st.markdown(ABOUT_MD)
