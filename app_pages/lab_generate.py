"""Lab: generate text with or without the watermark and save it as TXT
plus a JSON sidecar under generated/<mode>/."""

import streamlit as st

from ui import common, lab

common.require_role("teacher")
state = st.session_state
config = common.load_config()

st.title("Generate", anchor=False)
st.caption("The same prompt, with or without the green-list bias. Saved texts keep their seed "
           "and parameters in a sidecar file.")

with st.form("generate_form"):
    prompt = st.text_area("Prompt", height=140, value="Tell me about the history of cryptography.",
                          key="gen_prompt")
    left, right = st.columns(2)
    default_tokens = min(max(int(config.get("max_new_tokens", 300)), lab.MIN_TOKENS), lab.MAX_TOKENS)
    max_tok = left.number_input("Max tokens ({} to {})".format(lab.MIN_TOKENS, lab.MAX_TOKENS),
                                min_value=lab.MIN_TOKENS, max_value=lab.MAX_TOKENS,
                                value=default_tokens, step=10, key="gen_tokens")
    mode_label = right.segmented_control("Mode", ["Watermarked", "Normal"], default="Watermarked",
                                         key="gen_mode_pick", required=True)
    submitted = st.form_submit_button("Generate", type="primary", icon=":material/play_arrow:",
                                      key="gen_submit")

if submitted:
    if not prompt.strip():
        st.error("Write a prompt first.", icon=":material/error:")
    else:
        mode = (mode_label or "Watermarked").lower()
        engine, lock = common.engine()
        seconds = int(max_tok) / 4.3

        def generate(text=prompt.strip(), tokens=int(max_tok), marked=(mode == "watermarked")):
            with lock:
                return engine.generate(text, max_new_tokens=tokens, watermarked=marked)
        # in a thread of its own, so a click during the wait does not lose the text
        # (common.start_job); the model can fail in many ways, and the error is shown
        if common.job_running("gen_job"):
            st.info("Still generating the last text.", icon=":material/hourglass_top:")
        else:
            common.start_job("gen_job", generate,
                             "Generating {} text, about {:.0f} s on this CPU.".format(mode, seconds), seconds)

job = common.finished_job("gen_job")
if job and job["error"]:
    st.error("Generation failed: {}".format(job["error"]), icon=":material/error:")
elif job:
    info = job["result"]
    state["gen_info"], state["gen_text"], state["gen_mode"] = info, info["text"], info["mode"]
    state["gen_saved"] = state["gen_save_error"] = ""

if state["gen_text"]:
    info = state["gen_info"] or {}
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.subheader("Output", anchor=False)
            st.badge(state["gen_mode"].capitalize(),
                     color="green" if state["gen_mode"] == "watermarked" else "gray")
        st.code(state["gen_text"], language=None, wrap_lines=True)
        st.caption("{:,} words, {} tokens, seed {}".format(
            len(state["gen_text"].split()), info.get("new_tokens", "?"), info.get("seed", "?")))
        st.download_button("Save as .txt", data=state["gen_text"].encode("utf-8"),
                           file_name=lab.default_filename(state["gen_mode"]), mime="text/plain",
                           on_click=lab.on_save, icon=":material/download:", key="gen_save",
                           help="Writes the text and a .json sidecar (mode, seed, parameters) into "
                                "generated/{}/ and downloads a copy.".format(state["gen_mode"]))
    if state["gen_saved"]:
        st.success("Saved to {}".format(state["gen_saved"]), icon=":material/check_circle:")
    if state["gen_save_error"]:
        st.error("Save failed: {}".format(state["gen_save_error"]), icon=":material/error:")
