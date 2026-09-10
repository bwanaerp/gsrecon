"""Reconciliation engine — matches GSCORE GRNs to XERO purchase lines."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

VAT_RATE = 0.16
AMOUNT_TOL = 0.02
VAT_TOL = 0.005
DATE_WINDOW_DAYS = 45


@dataclass
class ReconResult:
    merged: pd.DataFrame
    g_grn: pd.DataFrame
    x_grn: pd.DataFrame
    x_credits: pd.DataFrame
    x_nogrn: pd.DataFrame
    g_raw: pd.DataFrame
    x_raw: pd.DataFrame
    totals: dict = field(default_factory=dict)

    def counts(self) -> dict:
        return self.merged["Status"].value_counts().to_dict()


def _status_for(g_amt, x_amt) -> str:
    if pd.isna(g_amt):
        return "Missing in GSCORE"
    if pd.isna(x_amt):
        return "Missing in XERO"
    if abs(g_amt - x_amt) <= AMOUNT_TOL:
        return "OK"
    if abs(g_amt / (1 + VAT_RATE) - x_amt) <= max(AMOUNT_TOL, VAT_TOL * abs(x_amt)):
        return "VAT (Xero net, GSCORE gross)"
    if abs(x_amt / (1 + VAT_RATE) - g_amt) <= max(AMOUNT_TOL, VAT_TOL * abs(g_amt)):
        return "VAT (GSCORE net, Xero gross)"
    return "Amount mismatch"


def reconcile(g: pd.DataFrame, x: pd.DataFrame) -> ReconResult:
    g_grn = (
        g.groupby("GRN", dropna=False)
        .agg(
            GSCORE_Date=("Date", "min"),
            GSCORE_Supplier=("Supplier", "first"),
            GSCORE_Amount=("LineTotal", "sum"),
            GSCORE_Lines=("LineTotal", "count"),
        )
        .reset_index()
    )

    x_pur = x[x["Kind"] == "Purchase"].copy()
    x_credits = x[x["Kind"] == "Credit"].copy()

    x_grn = (
        x_pur.dropna(subset=["GRN"])
        .groupby("GRN", dropna=False)
        .agg(
            XERO_Date=("Date", "min"),
            XERO_Supplier=("Supplier", "first"),
            XERO_Amount=("Amount", "sum"),
            XERO_Lines=("Amount", "count"),
        )
        .reset_index()
    )

    x_nogrn = x_pur[x_pur["GRN"].isna()].copy()

    merged = pd.merge(g_grn, x_grn, on="GRN", how="outer")
    merged["Status"] = merged.apply(
        lambda r: _status_for(r["GSCORE_Amount"], r["XERO_Amount"]), axis=1
    )
    merged["Diff (G-X)"] = merged["GSCORE_Amount"] - merged["XERO_Amount"]

    both = merged.dropna(subset=["GSCORE_Amount", "XERO_Amount"]).copy()
    both["DayGap"] = (both["XERO_Date"] - both["GSCORE_Date"]).dt.days
    merged = merged.merge(both[["GRN", "DayGap"]], on="GRN", how="left")

    totals = {
        "gscore_total": float(g["LineTotal"].sum()),
        "xero_purchases": float(x_pur["Amount"].sum()),
        "xero_credits": float(x_credits["CreditZMW"].sum()),
    }
    totals["gap"] = totals["gscore_total"] - totals["xero_purchases"]

    return ReconResult(
        merged=merged,
        g_grn=g_grn,
        x_grn=x_grn,
        x_credits=x_credits,
        x_nogrn=x_nogrn,
        g_raw=g,
        x_raw=x,
        totals=totals,
    )
