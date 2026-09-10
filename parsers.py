"""Parsers for GSCORE Purchase Analysis and XERO Account Transactions exports.

Handles the messy reality of ERP 'Excel' exports:
  - real .xlsx (openpyxl)
  - legacy binary .xls (xlrd)
  - Excel 2003 XML Spreadsheet (<?xml><Workbook>)
  - HTML tables saved as .xls
  - CSV / TSV / pipe-delimited in disguise
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
# Header finder — tolerant of case, whitespace, punctuation, merged cells
# ----------------------------------------------------------------------------
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _norm(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return _NORMALIZE_RE.sub("", str(s).lower())


def _find_header_row(raw: pd.DataFrame, wanted: set[str], scan: int = 200) -> int | None:
    wanted_norm = {_norm(w) for w in wanted}
    for i in range(min(scan, len(raw))):
        row_cells = [_norm(v) for v in raw.iloc[i].tolist()]
        row_blob = "|".join(row_cells)
        if all(
            any(w in c for c in row_cells) or w in row_blob
            for w in wanted_norm
        ):
            return i
    return None


# ----------------------------------------------------------------------------
# Excel 2003 XML Spreadsheet reader
# ----------------------------------------------------------------------------
def _read_xml_spreadsheet(content: bytes) -> list[pd.DataFrame]:
    from xml.etree import ElementTree as ET

    text = content.decode("utf-8", errors="ignore")
    start = text.find("<?xml")
    if start > 0:
        text = text[start:]
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.IGNORECASE)

    root = ET.fromstring(text)

    def _local(tag: str) -> str:
        return tag.split("}", 1)[-1]

    sheets: list[pd.DataFrame] = []
    for ws in root.iter():
        if _local(ws.tag) != "Worksheet":
            continue
        rows: list[list] = []
        for row in ws.iter():
            if _local(row.tag) != "Row":
                continue
            cells: list = []
            for cell in row:
                if _local(cell.tag) != "Cell":
                    continue
                idx = cell.attrib.get(
                    "{urn:schemas-microsoft-com:office:spreadsheet}Index"
                ) or cell.attrib.get("Index")
                if idx:
                    try:
                        want = int(idx) - 1
                        while len(cells) < want:
                            cells.append(None)
                    except ValueError:
                        pass
                data = None
                for d in cell:
                    if _local(d.tag) == "Data":
                        data = d.text
                        break
                cells.append(data)
            rows.append(cells)

        if not rows:
            continue

        width = max(len(r) for r in rows)
        rows = [r + [None] * (width - len(r)) for r in rows]
        sheets.append(pd.DataFrame(rows, dtype=object))

    return [s for s in sheets if not s.empty]


# ----------------------------------------------------------------------------
# Universal loader
# ----------------------------------------------------------------------------
def load_any(file, nrows=None) -> list[pd.DataFrame]:
    if hasattr(file, "read"):
        content = file.read()
        name = getattr(file, "name", "uploaded")
    else:
        with open(file, "rb") as f:
            content = f.read()
        name = str(file)

    head = content[:4096].lstrip()
    head_l = head[:1024].decode("utf-8", errors="ignore").lower()

    # 1. XLSX (zip)
    if head[:2] == b"PK":
        try:
            xls = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
            return [
                pd.read_excel(xls, sheet_name=s, header=None, dtype=object)
                for s in xls.sheet_names
            ]
        except Exception:
            pass

    # 2. Legacy binary XLS
    if head[:4] == b"\xd0\xcf\x11\xe0":
        try:
            xls = pd.ExcelFile(io.BytesIO(content), engine="xlrd")
            return [
                pd.read_excel(xls, sheet_name=s, header=None, dtype=object)
                for s in xls.sheet_names
            ]
        except Exception:
            pass

    # 3. Excel 2003 XML Spreadsheet
    if head_l.startswith("<?xml") and ("spreadsheet" in head_l or "workbook" in head_l):
        try:
            result = _read_xml_spreadsheet(content)
            if result:
                return result
        except Exception:
            pass

    # 4. HTML table
    if any(tok in head_l for tok in ("<html", "<table", "<tr", "<thead", "<tbody")):
        for flavor in ("bs4", "lxml", "html5lib"):
            try:
                tables = pd.read_html(io.BytesIO(content), header=None, flavor=flavor)
                clean = [t for t in tables if not t.empty and t.shape[1] >= 3]
                if clean:
                    return clean
            except Exception:
                continue

    # 5. CSV / TSV / pipe
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
        f"Could not read '{name}'. Open it in Excel and 'Save As' → "
        "Excel Workbook (.xlsx), then re-upload."
    )


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
        header_row = _find_header_row(raw, {"date", "grn"})
    if header_row is None:
        header_row = _find_header_row(raw, {"grn", "product"})
    if header_row is None:
        for i in range(min(200, len(raw))):
            row = raw.iloc[i].tolist()
            if any(
                isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v.strip())
                for v in row if pd.notna(v)
            ):
                header_row = max(0, i - 1)
                break

    if header_row is None:
        raise ValueError(
            "No GSCORE header row found. First 5 rows were:\n"
            + raw.head(5).to_string()
        )

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

    if not {"Date", "GRN"}.issubset(df.columns):
        raise ValueError(
            f"GSCORE sheet found header at row {header_row} but is missing "
            f"required columns. Columns seen: {list(df.columns)}"
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
        for i in range(min(200, len(raw))):
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
            f"XERO sheet missing Date / Description. Columns seen: {list(df.columns)}"
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
