"""Lab: score any text against this installation's key and log the result
to logs/detection_history.csv."""

import streamlit as st

import history
from ui import common, lab

common.require_role("teacher")
state = st.session_state

st.title("Detect", anchor=False)
st.caption("Re-score a text against this installation's key. Every analysis is logged.")
col_in, col_out = st.columns([3, 2], gap="large")

with col_in:
    st.file_uploader("Open a .txt file", type=["txt"], key="uploader", on_change=lab.on_upload)
    if state["upload_error"]:
        st.error(state["upload_error"], icon=":material/error:")
    st.text_area("Text to analyze", key="detect_text", height=360)
    with st.container(horizontal=True):
        analyze = st.button("Analyze", type="primary", icon=":material/manage_search:",
                            key="detect_run")
        st.button("Clear", on_click=lab.on_clear_detect, key="detect_clear")

if analyze:
    text = state["detect_text"].strip()
    state["detect_stats"] = None
    if not text:
        col_in.error("Paste or open a text first.", icon=":material/error:")
    else:
        engine, lock = common.engine()
        try:
            with st.spinner("Analyzing..."):
                with lock:
                    stats = engine.detect(text)
        except Exception as exc:
            col_in.error("Detection failed: {}".format(exc), icon=":material/error:")
        else:
            if stats is None:
                col_in.warning("The text is too short to score. It needs at least {} tokens.".format(
                    engine.min_tokens), icon=":material/hourglass_empty:")
            else:
                state["detect_stats"] = stats
                unchanged = state["detect_filename"] and text == state["detect_loaded"]
                try:
                    history.append_history(stats, source="file" if unchanged else "manual",
                                           filename=state["detect_filename"] if unchanged else "")
                except OSError as exc:
                    col_in.error("Result shown but not logged: the history CSV could not be "
                                 "written (is it open in Excel?). {}".format(exc),
                                 icon=":material/error:")

with col_out:
    with st.container(border=True):
        st.subheader("Result", anchor=False)
        stats = state["detect_stats"]
        if stats is None:
            st.caption("No analysis yet.")
        else:
            common.verdict_badge(stats["label"])
            with st.container(horizontal=True):
                st.metric("Tokens scored", stats["num_tokens_scored"], border=True)
                st.metric("Green tokens", stats["num_green_tokens"], border=True)
            with st.container(horizontal=True):
                st.metric("Green share", "{:.1f}%".format(stats["green_fraction"] * 100), border=True,
                          help="Chance level is 50%.")
                st.metric("z-score", "{:.2f}".format(stats["z_score"]), border=True)
                st.metric("p-value", "{:.2e}".format(stats["p_value"]), border=True)
            passage = stats.get("passage")
            for note in common.scoring_notes(
                    stats.get("repeated", 0), passage["z"] if passage else None,
                    "{:.1e}".format(passage["p"]) if passage else "", bool(passage and passage["decisive"])):
                st.caption(note)
            if passage:
                with st.expander("Show the passage", icon=":material/format_color_text:"):
                    st.markdown(common.highlighted(state["detect_text"], passage["start"], passage["end"]))
    st.caption("MarkText detects only text it generated with its own key and parameters. It is not "
               "a universal AI-text detector: Not detected means this watermark was not found, not "
               "that a person wrote the text.")
