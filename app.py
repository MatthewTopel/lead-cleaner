"""
Web demo for lead-cleaner, built with Streamlit.

Run it locally with:
    streamlit run app.py

All the cleaning logic lives in lead_cleaner.py. This file only handles
the web page: picking a file, showing the results and offering downloads.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from lead_cleaner import clean_leads

SAMPLE_FILE = Path(__file__).parent / "sample_messy_leads.csv"


def read_csv(source):
    """Read a CSV the same way the command-line tool does: everything as text."""
    return pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig")


st.set_page_config(page_title="Lead Cleaner", page_icon="🧹", layout="wide")

st.title("🧹 Lead Cleaner")
st.write(
    "Cleans messy B2B lead lists (like Apollo or Clay exports) so an SDR can use them "
    "right away. It fixes names, emails and domains, removes duplicates, flags bad emails, "
    "and ranks leads by seniority."
)

# --- Pick the input: the built-in sample or the visitor's own file ---------
choice = st.radio(
    "Which lead list?",
    ["Use the sample file (40 messy rows)", "Upload my own CSV"],
    horizontal=True,
)

if choice.startswith("Upload"):
    uploaded = st.file_uploader("Upload a lead list CSV", type="csv")
    if uploaded is None:
        st.info("Upload a CSV to get started. It needs at least an email column.")
        st.stop()  # nothing more to show until a file is uploaded
    raw = read_csv(uploaded)
else:
    raw = read_csv(SAMPLE_FILE)

# --- Clean it ---------------------------------------------------------------
try:
    cleaned, flagged, stats = clean_leads(raw)
except ValueError as error:
    # For example, the file has no column we recognize as an email.
    st.error(str(error))
    st.stop()

# --- Summary numbers --------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Rows in", stats["rows_in"])
col2.metric("Clean leads", stats["rows_out"])
col3.metric("Duplicates removed", stats["duplicates_removed"])
col4.metric("Rows flagged", stats["rows_flagged"])

if stats["reason_counts"]:
    st.subheader("Why rows were flagged")
    reasons = pd.DataFrame(
        stats["reason_counts"].most_common(), columns=["Reason", "Rows"]
    )
    st.dataframe(reasons, hide_index=True)

# --- Tables: after cleaning, flagged rows, and the original -----------------
tab_clean, tab_flagged, tab_before = st.tabs(
    [f"✅ Cleaned ({len(cleaned)})", f"🚩 Flagged ({len(flagged)})", f"📄 Original ({len(raw)})"]
)

with tab_clean:
    st.caption("Good leads only, sorted by seniority (5 = C-level/Founder) and then company.")
    st.dataframe(cleaned, hide_index=True, use_container_width=True)
    st.download_button(
        "Download cleaned.csv",
        cleaned.to_csv(index=False),
        file_name="cleaned.csv",
        mime="text/csv",
    )

with tab_flagged:
    st.caption("Removed or suspicious rows. The reason column says why.")
    st.dataframe(flagged, hide_index=True, use_container_width=True)
    st.download_button(
        "Download flagged.csv",
        flagged.to_csv(index=False),
        file_name="flagged.csv",
        mime="text/csv",
    )

with tab_before:
    st.caption("The file exactly as it came in, before any cleaning.")
    st.dataframe(raw, hide_index=True, use_container_width=True)

# --- Explanation for visitors -----------------------------------------------
with st.expander("How it works"):
    st.markdown(
        """
1. **Detects columns.** "First Name", "first_name" and "FIRSTNAME" all count as the first-name column.
2. **Normalizes.** Trims whitespace, fixes names (`MCDONALD` → `McDonald`, `o'brien` → `O'Brien`),
   lowercases emails, and turns websites into domains (`https://www.acme.com/about` → `acme.com`).
3. **Deduplicates.** Removes exact duplicate emails, then flags likely duplicates
   (same first + last name at the same domain).
4. **Flags bad emails.** Invalid format, role-based (info@, sales@...), free providers (Gmail, Yahoo...),
   and email domains that don't match the company website.
5. **Scores seniority.** C-level/Founder/Owner = 5, VP = 4, Director/Head of = 3, Manager = 2, others = 1.
6. **Sorts** by seniority, then company.

Built with Python and pandas.
        """
    )
