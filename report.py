"""Report tables for ReconResult."""
import pandas as pd
from reconcile import ReconResult

def summary_cards(r):
    c=r.counts()
    return {"gscore_total":r.totals["gscore_total"],"xero_total":r.totals["xero_purchases"],"gap":r.totals["gap"],"xero_credits":r.totals["xero_credits"],"ok":c.get("OK",0),"missing_gscore":c.get("Missing in GSCORE",0),"missing_xero":c.get("Missing in XERO",0),"vat":c.get("VAT (Xero net, GSCORE gross)",0)+c.get("VAT (GSCORE net, Xero gross)",0),"mismatch":c.get("Amount mismatch",0)}

def issues_table(r):
    df=r.merged[r.merged["Status"]!="OK"].copy()
    if df.empty:return df
    df["absdiff"]=df["Diff (G-X)"].abs(); df=df.sort_values("absdiff",ascending=False).drop(columns="absdiff")
    cols=["GRN","Status","GSCORE_Date","XERO_Date","GSCORE_Supplier","XERO_Supplier","GSCORE_Amount","XERO_Amount","Diff (G-X)"]
    return df[[c for c in cols if c in df.columns]]

def cutoff_table(r,threshold=31):
    df=r.merged.dropna(subset=["GSCORE_Amount","XERO_Amount","DayGap"]).copy(); df=df[df["DayGap"].abs()>threshold]
    if df.empty:return df
    df=df.sort_values("DayGap",key=lambda s:s.abs(),ascending=False)
    return df[["GRN","GSCORE_Date","XERO_Date","DayGap","GSCORE_Amount","XERO_Amount"]]

def unlinked_xero_table(r):
    df=r.x_nogrn.copy()
    if df.empty:return df
    cols=["Date","Supplier","Description","Reference","Amount"]
    return df[[c for c in cols if c in df.columns]].sort_values("Amount",ascending=False)

def credits_table(r):
    df=r.x_credits.copy()
    if df.empty:return df
    cols=["Date","Supplier","Description","Reference","CreditZMW"]
    return df[[c for c in cols if c in df.columns]].rename(columns={"CreditZMW":"Credit"})
