"""Parsers for GSCORE Purchase Analysis and XERO Account Transactions exports.

Handles the messy reality of ERP 'Excel' exports:
  - real .xlsx (openpyxl)
  - legacy binary .xls (xlrd)
  - HTML tables saved as .xls (read_html)
  - CSV/TSV in disguise (read_csv with delimiter sniffing)
"""
from __future__ import annotations

import io
import re
from datetime import datetime

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------
# Low-level helpers
# ----------------------------------------------------------------------------
def _clean_num(x):
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).replace(",", "").replace("K", "").replace("ZMW", "").strip()
    if s in ("", "-", "—"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return np.nan


def _to_date(x):
    if pd.isna(x):
        return pd.NaT
    if isinstance(x, datetime):
        return x
    return pd.to_datetime(x, errors="coerce")


def _extract_grn(text):
    if not isinstance(text, str):
        return None
    m = re.search(r"GRN[-\s]?(\d{8}[-\s]?[A-Z0-9]+)", text, re.IGNORECASE)
    return f"GRN-{m.group(1).replace(' ', '-')}".upper() if m else None


def _extract_inv(text):
    if not isinstance(text, str):
        return None
    m = re.search(r"(INV[0-9A-Z/]+)", text, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _extract_po(text):
    if not isinstance(text, str):
        return None
    m = re.search(r"(PO[-\s]?\d{8}[-\s]?[A-Z0-9]+)", text, re.IGNORECASE)
    return m.group(1).replace(" ", "-").upper() if m else None


# ----------------------------------------------------------------------------
# Universal loader — sniffs the real file type regardless of extension
# ----------------------------------------------------------------------------
def load_any(file, nrows=None) -> list[pd.DataFrame]:
    """
    Return a list of raw DataFrames (one per sheet / HTML table / CSV chunk),
    with no header assumption — caller finds the header row itself.
    """
    if hasattr(file, "read"):
        content = file.read()
        name = getattr(file, "name", "uploaded")
    else:
        with open(file, "rb") as f:
            content = f.read()
        name = str(file)

    head = content[:2048].lstrip()

    # 1. Real XLSX / XLSM (zip container starting with PK)
    if head[:2] == b"PK":
        try:
            xls = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
            return [
                pd.read_excel(xls, sheet_name=s, header=None, dtype=object)
                for s in xls.sheet_names
            ]
        except Exception:
            pass

    # 2. Legacy binary XLS (D0 CF 11 E0 ...)
    if head[:4] == b"\xd0\xcf\x11\xe0":
        try:
            xls = pd.ExcelFile(io.BytesIO(content), engine="xlrd")
            return [
                pd.read_excel(xls, sheet_name=s, header=None, dtype=object)
                for s in xls.sheet_names
            ]
        except Exception:
            pass

    # 3. HTML table saved as .xls (very common in ERP "Export to Excel")
    text_head = head[:512].decode("utf-8", errors="ignore").lower()
    if ("<html" in text_head or "<table" in text_head
            or "<?xml" in text_head or "<tr" in text_head):
        try:
            tables = pd.read_html(io.BytesIO(content), header=None, flavor="bs4")
            return [t for t in tables if not t.empty]
        except Exception:
            # try with lxml
            try:
                tables = pd.read_html(io.BytesIO(content), header=None, flavor="lxml")
                return [t for t in tables if not t.empty]
            except Exception:
                pass

    # 4. CSV / TSV in disguise — try several separators
    for sep in (",", ";", "\t", "|"):
        try:
            df = pd.read_csv(
                io.BytesIO(content), sep=sep, header=None,
                dtype=object, engine="python", nrows=nrows,
            )
            if df.shape[1] >= 3:
                return [df]
        except Exception:
            continue

    raise ValueError(
        f"Could not read '{name}'. The file doesn't look like a real "
        "XLSX, XLS, HTML, or CSV. Open it in Excel and 'Save As' → "
        "Excel Workbook (.xlsx), then re-upload."
    )


def _find_header_row(raw: pd.DataFrame, wanted: set[str], scan: int = 120) -> int | None:
    for i in range(min(scan, len(raw))):
        vals = {
            str(v).strip().lower() if pd.notna(v) else ""
            for v in raw.iloc[i].tolist()
        }
        if wanted.issubset(vals):
            return i
    return None


def _find_header_row_fuzzy(raw: pd.DataFrame, wanted: set[str], scan: int = 120) -> int | None:
    """Fallback: any cell in the row *contains* one of the wanted tokens."""
    for i in range(min(scan, len(raw))):
        row = " | ".join(
            str(v).strip().lower() if pd.notna(v) else ""
            for v in raw.iloc[i].tolist()
        )
        if all(w in row for w in wanted):
            return i
    return None


# ----------------------------------------------------------------------------
# GSCORE
# ----------------------------------------------------------------------------
GSCORE_COLMAP_HINTS = {
    "date": "Date",
    "grn": "GRN",
    "supplier": "Supplier",
    "product": "Product",
    "category": "Category",
    "unit": "Unit",
    "qty": "Qty",
    "quantity": "Qty",
    "unit cost": "UnitCost",
    "cost": "UnitCost",
    "line total": "LineTotal",
    "total": "LineTotal",
}


def _gscore_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    header_row = _find_header_row(raw, {"date", "grn", "product"})
    if header_row is None:
        header_row = _find_header_row_fuzzy(raw, {"date", "grn", "product"})
    if header_row is None:
        raise ValueError("No GSCORE header row (needs Date, GRN, Product) found in sheet.")

    header = [
        str(v).strip() if pd.notna(v) else f"col{j}"
        for j, v in enumerate(raw.iloc[header_row].tolist())
    ]
    df = raw.iloc[header_row + 1:].copy()
    df.columns = header
    df = df.dropna(how="all")

    rename = {}
    for c in df.columns:
        cl = str(c).lower().strip()
        for hint, target in GSCORE_COLMAP_HINTS.items():
            if target in rename.values():
                continue
            if cl == hint or cl.startswith(hint):
                rename[c] = target
                break
    df = df.rename(columns=rename)

    if not {"Date", "GRN", "Product"}.issubset(df.columns):
        raise ValueError(
            f"GSCORE sheet missing required columns. Found: {list(df.columns)}"
        )

    df = df[df["GRN"].astype(str).str.upper().str.startswith("GRN", na=False)].copy()

    for c in ("Qty", "UnitCost", "LineTotal"):
        if c in df.columns:
            df[c] = df[c].apply(_clean_num)

    if "LineTotal" not in df.columns and {"Qty", "UnitCost"}.issubset(df.columns):
        df["LineTotal"] = df["Qty"] * df["UnitCost"]

    df["Date"] = df["Date"].apply(_to_date)
    df["GRN"] = df["GRN"].astype(str).str.strip().str.upper()
    df = df.dropna(subset=["Date"])
    df["Source"] = "GSCORE"
    return df.reset_index(drop=True)


def parse_gscore(file) -> pd.DataFrame:
    """Parse a GSCORE 'Purchase Analysis' export — any file format."""
    sheets = load_any(file)
    errors = []
    for i, raw in enumerate(sheets):
        try:
            df = _gscore_from_raw(raw)
            if not df.empty:
                return df
        except Exception as e:
            errors.append(f"sheet {i}: {e}")
    raise ValueError(
        "Could not find a GSCORE purchase table. Tried every sheet/table. "
        + " | ".join(errors)
    )


# ----------------------------------------------------------------------------
# XERO
# ----------------------------------------------------------------------------
def _xero_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    header_row = _find_header_row(raw, {"date", "description", "debit"})
    if header_row is None:
        # fuzzy: any row whose text contains date/description/debit
        for i in range(min(120, len(raw))):
            row = " | ".join(
                str(v).strip().lower() if pd.notna(v) else ""
                for v in raw.iloc[i].tolist()
            )
            if "date" in row and "description" in row and "debit" in row:
                header_row = i
                break
    if header_row is None:
        raise ValueError("No XERO header row (Date, Description, Debit) found.")

    header = [
        str(v).strip() if pd.notna(v) else f"col{j}"
        for j, v in enumerate(raw.iloc[header_row].tolist())
    ]
    df = raw.iloc[header_row + 1:].copy()
    df.columns = header
    df = df.dropna(how="all")

    rename = {}
    for c in df.columns:
        cl = str(c).lower().strip()
        if cl == "date":
            rename[c] = "Date"
        elif cl == "source":
            rename[c] = "Source"
        elif cl == "description":
            rename[c] = "Description"
        elif cl == "reference":
            rename[c] = "Reference"
        elif "debit" in cl and "zmw" in cl:
            rename[c] = "DebitZMW"
        elif "credit" in cl and "zmw" in cl:
            rename[c] = "CreditZMW"
        elif "debit" in cl:
            rename[c] = "DebitSrc"
        elif "credit" in cl:
            rename[c] = "CreditSrc"
        elif "currency" in cl:
            rename[c] = "Currency"
    df = df.rename(columns=rename)

    if "Date" not in df.columns or "Description" not in df.columns:
        raise ValueError(
            f"XERO sheet missing Date / Description. Found: {list(df.columns)}"
        )

    df["Date"] = df["Date"].apply(_to_date)
    df = df[df["Date"].notna()].copy()

    for target, fallback in (("DebitZMW", "DebitSrc"), ("CreditZMW", "CreditSrc")):
        if target not in df.columns:
            if fallback in df.columns:
                df[target] = df[fallback].apply(_clean_num)
            else:
                df[target] = 0.0
        df[target] = df[target].apply(_clean_num).fillna(0.0)

    text = (
        df.get("Description", pd.Series([""] * len(df), index=df.index)).astype(str)
        + " | "
        + df.get("Reference", pd.Series([""] * len(df), index=df.index)).astype(str)
    )
    df["GRN"] = text.apply(_extract_grn)
    df["PO"] = text.apply(_extract_po)
    df["Invoice"] = text.apply(_extract_inv)

    def _supplier(s: str):
        if not isinstance(s, str):
            return None
        head = re.split(r"\s*[-—]\s*", s, maxsplit=1)[0].strip()
        return head or None

    df["Supplier"] = (
        df.get("Description", pd.Series([""] * len(df), index=df.index))
        .apply(_supplier)
    )

    df["Amount"] = df["DebitZMW"] - df["CreditZMW"]
    df["Kind"] = np.where(
        df["DebitZMW"] > 0,
        "Purchase",
        np.where(df["CreditZMW"] > 0, "Credit", "Zero"),
    )
    df["Source"] = "XERO"
    return df.reset_index(drop=True)


def parse_xero(file) -> pd.DataFrame:
    """Parse a XERO 'Account Transactions' export — any file format."""
    sheets = load_any(file)
    errors = []
    for i, raw in enumerate(sheets):
        try:
            df = _xero_from_raw(raw)
            if not df.empty:
                return df
        except Exception as e:
            errors.append(f"sheet {i}: {e}")
    raise ValueError(
        "Could not find a XERO account-transactions table. Tried every sheet/table. "
        + " | ".join(errors)
    )
