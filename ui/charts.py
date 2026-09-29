"""Charts for the classroom pages (Altair, which Streamlit bundles)."""

import altair as alt
import pandas as pd
import streamlit as st

import verdict

# verdict -> colour, per theme; the same meaning as the badges
VERDICT_COLOURS = {
    "light": {verdict.LABEL_LIKELY: "#a33b3b", verdict.LABEL_POSSIBLE: "#9a6b1f",
              verdict.LABEL_NOT_DETECTED: "#71717a", verdict.LABEL_INCONCLUSIVE: "#a1a1aa"},
    "dark": {verdict.LABEL_LIKELY: "#e07a7a", verdict.LABEL_POSSIBLE: "#d4a24c",
             verdict.LABEL_NOT_DETECTED: "#a1a1aa", verdict.LABEL_INCONCLUSIVE: "#71717a"},
}
SHORT = {verdict.LABEL_LIKELY: "Likely MarkText", verdict.LABEL_POSSIBLE: "Possible watermark",
         verdict.LABEL_NOT_DETECTED: "Not detected", verdict.LABEL_INCONCLUSIVE: "Inconclusive"}


def theme():
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:          # no browser context (tests)
        return "light"


def scores_chart(points, detection, possible, height=300):
    """z-score against tokens scored for each current version, one dot per
    student and assignment, with the two thresholds drawn as lines."""
    colours = VERDICT_COLOURS[theme()]
    df = pd.DataFrame(points)
    df["verdict"] = df["label"].map(lambda l: SHORT.get(l, l))
    df["who"] = df["student"] + " · v" + df["version"].astype(str)
    domain = [SHORT[l] for l in verdict.LABELS]
    dots = alt.Chart(df).mark_circle(size=110, opacity=0.9).encode(
        x=alt.X("tokens_scored:Q", title="tokens scored", scale=alt.Scale(zero=False),
                axis=alt.Axis(tickCount=6, format="d")),
        y=alt.Y("z_score:Q", title="z-score"),
        color=alt.Color("verdict:N", title=None,
                        scale=alt.Scale(domain=domain, range=[colours[l] for l in verdict.LABELS]),
                        legend=alt.Legend(orient="bottom")),
        tooltip=[alt.Tooltip("who:N", title="student"), alt.Tooltip("assignment:N"),
                 alt.Tooltip("z_score:Q", title="z", format=".2f"),
                 alt.Tooltip("tokens_scored:Q", title="tokens"), alt.Tooltip("verdict:N")])
    # the threshold lines get fixed colours, so they never share the dots' colour scale
    likely = alt.Chart(pd.DataFrame({"z": [detection]})).mark_rule(
        strokeDash=[6, 4], color=colours[verdict.LABEL_LIKELY]).encode(y="z:Q")
    possible_line = alt.Chart(pd.DataFrame({"z": [possible]})).mark_rule(
        strokeDash=[2, 4], color=colours[verdict.LABEL_POSSIBLE]).encode(y="z:Q")
    return (likely + possible_line + dots).properties(height=height)
