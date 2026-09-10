# GSCORE ⇄ XERO Reconciliation

Upload a GSCORE Purchase Analysis export and a XERO Account Transactions export. The app reconciles purchases GRN-by-GRN and flags VAT deltas, amount mismatches, missing GRNs, cutoff/date gaps, unlinked XERO purchases, and credit lines.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud
Upload this ZIP to GitHub (or extract it into a repo), then select `app.py` as the main file.
