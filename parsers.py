"""Parsers for GSCORE Purchase Analysis and XERO Account Transactions exports."""
from __future__ import annotations
import re
from datetime import datetime
import numpy as np
import pandas as pd

def _clean_num(x):
    if pd.isna(x): return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)): return float(x)
    s = str(x).replace(",", "").replace("K", "").replace("ZMW", "").strip()
    if s in ("", "-", "—"): return 0.0
    try: return float(s)
    except ValueError: return np.nan

def _to_date(x):
    if pd.isna(x): return pd.NaT
    if isinstance(x, datetime): return x
    return pd.to_datetime(x, errors="coerce")

def _extract_grn(text):
    if not isinstance(text, str): return None
    m = re.search(r"GRN[-\s]?(\d{8}[-\s]?[A-Z0-9]+)", text, re.I)
    return f"GRN-{m.group(1).replace(' ', '-')}".upper() if m else None

def _extract_inv(text):
    if not isinstance(text, str): return None
    m = re.search(r"(INV[0-9A-Z/]+)", text, re.I)
    return m.group(1).upper() if m else None

def _extract_po(text):
    if not isinstance(text, str): return None
    m = re.search(r"(PO[-\s]?\d{8}[-\s]?[A-Z0-9]+)", text, re.I)
    return m.group(1).replace(" ", "-").upper() if m else None

GSCORE_COLMAP_HINTS = {
    "date": "Date", "grn": "GRN", "supplier": "Supplier",
    "product": "Product", "category": "Category", "unit": "Unit",
    "qty": "Qty", "quantity": "Qty", "unit cost": "UnitCost",
    "cost": "UnitCost", "line total": "LineTotal", "total": "LineTotal",
}

def _find_header_row(raw, wanted, scan=80):
    for i in range(min(scan, len(raw))):
        vals = {str(v).strip().lower() if pd.notna(v) else "" for v in raw.iloc[i].tolist()}
        if wanted.issubset(vals): return i
    return None

def parse_gscore(file):
    raw = pd.read_excel(file, sheet_name=0, header=None, dtype=object)
    header_row = _find_header_row(raw, {"date", "grn", "product"})
    if header_row is None:
        raise ValueError("Could not find GSCORE detail header row. Expected Date, GRN, Product.")
    header = [str(v).strip() if pd.notna(v) else f"col{j}" for j,v in enumerate(raw.iloc[header_row].tolist())]
    df = raw.iloc[header_row+1:].copy(); df.columns = header; df = df.dropna(how="all")
    rename = {}
    for c in df.columns:
        cl = str(c).lower().strip()
        for hint,target in GSCORE_COLMAP_HINTS.items():
            if target in rename.values(): continue
            if cl == hint or cl.startswith(hint):
                rename[c]=target; break
    df=df.rename(columns=rename)
    missing={"Date","GRN","Product"}-set(df.columns)
    if missing: raise ValueError(f"GSCORE file missing required columns: {missing}")
    df=df[df["GRN"].astype(str).str.upper().str.startswith("GRN", na=False)].copy()
    for c in ("Qty","UnitCost","LineTotal"):
        if c in df.columns: df[c]=df[c].apply(_clean_num)
    if "LineTotal" not in df.columns and {"Qty","UnitCost"}.issubset(df.columns):
        df["LineTotal"]=df["Qty"]*df["UnitCost"]
    df["Date"]=df["Date"].apply(_to_date)
    df["GRN"]=df["GRN"].astype(str).str.strip().str.upper()
    df=df.dropna(subset=["Date"]); df["Source"]="GSCORE"
    return df.reset_index(drop=True)

def parse_xero(file):
    xls=pd.ExcelFile(file); raw=pd.read_excel(file, sheet_name=xls.sheet_names[0], header=None, dtype=object)
    header_row=_find_header_row(raw, {"date","description","debit"}, scan=80)
    if header_row is None:
        for i in range(min(80,len(raw))):
            vals=" ".join(str(v).strip().lower() if pd.notna(v) else "" for v in raw.iloc[i].tolist())
            if "date" in vals and "description" in vals and "debit" in vals:
                header_row=i; break
    if header_row is None: raise ValueError("Could not locate XERO header row (Date / Description / Debit).")
    header=[str(v).strip() if pd.notna(v) else f"col{j}" for j,v in enumerate(raw.iloc[header_row].tolist())]
    df=raw.iloc[header_row+1:].copy(); df.columns=header; df=df.dropna(how="all")
    rename={}
    for c in df.columns:
        cl=str(c).lower().strip()
        if cl=="date": rename[c]="Date"
        elif cl=="source": rename[c]="Source"
        elif cl=="description": rename[c]="Description"
        elif cl=="reference": rename[c]="Reference"
        elif "debit" in cl and "zmw" in cl: rename[c]="DebitZMW"
        elif "credit" in cl and "zmw" in cl: rename[c]="CreditZMW"
        elif "debit" in cl: rename[c]="DebitSrc"
        elif "credit" in cl: rename[c]="CreditSrc"
        elif "currency" in cl: rename[c]="Currency"
    df=df.rename(columns=rename)
    if "Date" not in df.columns or "Description" not in df.columns:
        raise ValueError("XERO file missing Date / Description columns.")
    df["Date"]=df["Date"].apply(_to_date); df=df[df["Date"].notna()].copy()
    for target,fallback in (("DebitZMW","DebitSrc"),("CreditZMW","CreditSrc")):
        if target not in df.columns: df[target]=df[fallback].apply(_clean_num) if fallback in df.columns else 0.0
        df[target]=df[target].apply(_clean_num).fillna(0.0)
    text=df.get("Description",pd.Series([""]*len(df),index=df.index)).astype(str)+" | "+df.get("Reference",pd.Series([""]*len(df),index=df.index)).astype(str)
    df["GRN"]=text.apply(_extract_grn); df["PO"]=text.apply(_extract_po); df["Invoice"]=text.apply(_extract_inv)
    def _supplier(s):
        if not isinstance(s,str): return None
        head=re.split(r"\s*[-—]\s*",s,maxsplit=1)[0].strip()
        return head or None
    df["Supplier"]=df.get("Description",pd.Series([""]*len(df),index=df.index)).apply(_supplier)
    df["Amount"]=df["DebitZMW"]-df["CreditZMW"]
    df["Kind"]=np.where(df["DebitZMW"]>0,"Purchase",np.where(df["CreditZMW"]>0,"Credit","Zero"))
    df["Source"]="XERO"
    return df.reset_index(drop=True)
