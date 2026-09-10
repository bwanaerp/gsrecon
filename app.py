"""GSCORE ⇄ XERO Reconciliation — Streamlit app."""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from parsers import parse_gscore, parse_xero
from reconcile import reconcile
from report import (
    summary_cards,
    issues_table,
    cutoff_table,
    unlinked_xero_table,
    credits_table,
)
import ui


st.set_page_config(
    page_title="GSCORE ⇄ XERO Recon",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ui.inject_tailwind()


# ----------------------------------------------------------------------------
# Hero
# ----------------------------------------------------------------------------
ui.hero(
    "GSCORE ⇄ XERO Reconciliation",
    "Upload a GSCORE Purchase Analysis and the matching XERO Account Transactions. "
    "The app matches GRN-by-GRN and flags VAT, amount, and cutoff mismatches.",
)


# ----------------------------------------------------------------------------
# Upload row
# ----------------------------------------------------------------------------
col1, col2 = st.columns(2, gap="large")

with col1:
    ui.upload_card(
        "① GSCORE · Purchase Analysis",
        "Drag the .xls / .xlsx export here",
    )
    g_file = st.file_uploader(
        "GSCORE file",
        type=["xls", "xlsx", "xml", "csv"],
        key="gscore",
        label_visibility="collapsed",
    )
    if g_file:
        st.markdown(
            f'<div class="tw-kv">📄 <b>{g_file.name}</b> '
            f'<span style="color:#64748B">({g_file.size/1024:.0f} KB)</span></div>',
            unsafe_allow_html=True,
        )

with col2:
    ui.upload_card(
        "② XERO · Account Transactions",
        "Drag the .xls / .xlsx export here",
    )
    x_file = st.file_uploader(
        "XERO file",
        type=["xls", "xlsx", "xml", "csv"],
        key="xero",
        label_visibility="collapsed",
    )
    if x_file:
        st.markdown(
            f'<div class="tw-kv">📄 <b>{x_file.name}</b> '
            f'<span style="color:#64748B">({x_file.size/1024:.0f} KB)</span></div>',
            unsafe_allow_html=True,
        )


# ----------------------------------------------------------------------------
# Debug panel (collapsed by default; expand only when something breaks)
# ----------------------------------------------------------------------------
with st.expander("🛠 Debug — what did the loader see?", expanded=False):
    import io as _io
    from parsers import load_any

    for label, f in (("GSCORE", g_file), ("XERO", x_file)):
        if not f:
            continue
        try:
            f.seek(0)
        except Exception:
            pass
        raw_bytes = f.read()
        try:
            f.seek(0)
        except Exception:
            pass

        st.markdown(f"**{label}**")
        st.code(f"first 300 bytes:\n{raw_bytes[:300]!r}", language="text")
        try:
            sheets = load_any(_io.BytesIO(raw_bytes))
            st.write(f"→ loader returned **{len(sheets)}** sheet(s)")
            for i, s in enumerate(sheets):
                st.write(f"**Sheet {i}** — shape {s.shape}")
                st.dataframe(s.head(10), use_container_width=True)
        except Exception as e:
            st.error(f"loader failed: {e}")


# ----------------------------------------------------------------------------
# Gate
# ----------------------------------------------------------------------------
if not (g_file and x_file):
    ui.section("How it works")
    st.markdown(
        """
        1. **Upload** the GSCORE *Purchase Analysis* export.
        2. **Upload** the XERO *Account Transactions* export.
        3. The app will:
           - Match every GRN between the two systems
           - Flag VAT-style mismatches (×1.16)
           - Flag missing GRNs on either side
           - Flag cutoff / date misalignment (> 31 days)
           - List XERO purchases with no GRN token
           - List XERO credit lines (consumption / journals)
        """
    )
    st.stop()


# ----------------------------------------------------------------------------
# Parse
# ----------------------------------------------------------------------------
try:
    g = parse_gscore(g_file)
except Exception as e:
    st.error(f"**GSCORE parse error:** {e}")
    st.info("Open the '🛠 Debug' panel above to see what the loader found.")
    st.stop()

try:
    x = parse_xero(x_file)
except Exception as e:
    st.error(f"**XERO parse error:** {e}")
    st.info("Open the '🛠 Debug' panel above to see what the loader found.")
    st.stop()


with st.expander("🔎 Preview parsed rows", expanded=False):
    a, b = st.columns(2)
    with a:
        st.caption(f"GSCORE · {len(g):,} rows")
        st.dataframe(g.head(30), use_container_width=True, height=300)
    with b:
        st.caption(f"XERO · {len(x):,} rows")
        st.dataframe(x.head(30), use_container_width=True, height=300)


# ----------------------------------------------------------------------------
# Reconcile
# ----------------------------------------------------------------------------
result = reconcile(g, x)
cards = summary_cards(result)


# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
ui.section("Summary")
c1, c2, c3, c4 = st.columns(4)
with c1:
    ui.metric_card(
        "GSCORE purchases",
        f"K{cards['gscore_total']:,.2f}",
        f"{len(result.g_grn):,} GRNs",
    )
with c2:
    ui.metric_card(
        "XERO purchases",
        f"K{cards['xero_total']:,.2f}",
        f"{len(result.x_grn):,} tagged GRNs",
    )
with c3:
    gap = cards["gap"]
    ui.metric_card(
        "Gap (G − X)",
        f"K{gap:,.2f}",
        "GSCORE minus XERO debits",
        tone="bad" if abs(gap) > 0.02 else "good",
    )
with c4:
    ui.metric_card(
        "XERO credits",
        f"K{cards['xero_credits']:,.2f}",
        "Consumption / journals",
        tone="info",
    )


ui.section("GRN match status")
m1, m2, m3, m4, m5 = st.columns(5)
with m1: ui.metric_card("✅ Matched OK", str(cards["ok"]), "exact")
with m2: ui.metric_card("🟡 VAT delta", str(cards["vat"]), "×1.16 factor")
with m3: ui.metric_card("🔴 Amount mismatch", str(cards["mismatch"]), "same GRN, different value")
with m4: ui.metric_card("⬅️ Missing in XERO", str(cards["missing_xero"]), "GSCORE only")
with m5: ui.metric_card("➡️ Missing in GSCORE", str(cards["missing_gscore"]), "XERO only")


# ----------------------------------------------------------------------------
# Issues
# ----------------------------------------------------------------------------
ui.section(
    "⚠️ Things to look at",
    "Ranked by absolute difference. Every row is a GRN that isn't a clean match.",
)
issues = issues_table(result)
if issues.empty:
    st.success("No GRN-level issues detected. 🎉")
else:
    st.dataframe(
        issues.style.format(
            {
                "GSCORE_Amount": "{:,.2f}",
                "XERO_Amount": "{:,.2f}",
                "Diff (G-X)": "{:,.2f}",
                "GSCORE_Date": lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "",
                "XERO_Date": lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "",
            }
        ),
        use_container_width=True,
        height=420,
    )


# ----------------------------------------------------------------------------
# Cutoff
# ----------------------------------------------------------------------------
ui.section(
    "📅 Cutoff / date mismatches",
    "Matched on GRN, but the GSCORE date and XERO posting date are more than 31 days apart.",
)
cutoff = cutoff_table(result)
if cutoff.empty:
    st.info("None — every matched GRN sits within ~1 month of its GSCORE date.")
else:
    st.dataframe(
        cutoff.style.format(
            {
                "GSCORE_Amount": "{:,.2f}",
                "XERO_Amount": "{:,.2f}",
                "GSCORE_Date": lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "",
                "XERO_Date": lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "",
            }
        ),
        use_container_width=True,
    )


# ----------------------------------------------------------------------------
# XERO with no GRN
# ----------------------------------------------------------------------------
ui.section(
    "🧾 XERO purchases with no GRN in the description",
    "These cannot be matched to GSCORE. Usually non-PO invoices or manual entries.",
)
nogrn = unlinked_xero_table(result)
if nogrn.empty:
    st.info("None — every XERO debit line carries a GRN token.")
else:
    st.dataframe(
        nogrn.style.format({"Amount": "{:,.2f}"}),
        use_container_width=True,
        height=320,
    )


# ----------------------------------------------------------------------------
# Credits
# ----------------------------------------------------------------------------
ui.section(
    "📉 XERO credit lines (consumption / journals)",
    "If the total here is far larger than what GSCORE issued, that journal is the suspect.",
)
credits = credits_table(result)
if credits.empty:
    st.info("No credit lines found in the XERO export.")
else:
    st.dataframe(
        credits.style.format({"Credit": "{:,.2f}"}),
        use_container_width=True,
        height=320,
    )
    st.markdown(
        f'<div class="tw-kv">Total credits: '
        f'<b>K{credits["Credit"].sum():,.2f}</b></div>',
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------------
ui.section("⬇ Download reconciliation workbook")
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl", datetime_format="YYYY-MM-DD") as w:
    result.merged.to_excel(w, sheet_name="GRN Match", index=False)
    (issues if not issues.empty else pd.DataFrame({"note": ["no issues"]})).to_excel(
        w, sheet_name="Issues", index=False
    )
    (cutoff if not cutoff.empty else pd.DataFrame({"note": ["no cutoff issues"]})).to_excel(
        w, sheet_name="Cutoff", index=False
    )
    (nogrn if not nogrn.empty else pd.DataFrame({"note": ["none"]})).to_excel(
        w, sheet_name="XERO no-GRN", index=False
    )
    (credits if not credits.empty else pd.DataFrame({"note": ["none"]})).to_excel(
        w, sheet_name="XERO credits", index=False
    )
buf.seek(0)

st.download_button(
    "⬇ Download .xlsx",
    data=buf,
    file_name=f"recon_{datetime.now():%Y%m%d_%H%M}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
