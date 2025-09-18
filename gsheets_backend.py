import os, json, gspread, pandas as pd
from typing import Optional, Dict
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _get_client():
    sa_json = os.environ.get("GSPREAD_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        try:
            import streamlit as st
            sa_json = st.secrets.get("GSPREAD_SERVICE_ACCOUNT_JSON", None)
        except Exception:
            sa_json = None
    if not sa_json:
        raise RuntimeError("Missing GSPREAD_SERVICE_ACCOUNT_JSON in secrets/env.")
    info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _open_sheet(sheet_id: str):
    return _get_client().open_by_key(sheet_id)

def read_sheet_as_df(sheet_id: str) -> pd.DataFrame:
    ws = _open_sheet(sheet_id).sheet1
    data = ws.get_all_records()
    return pd.DataFrame(data) if data else pd.DataFrame()

def write_dataframe(sheet_id: str, df: pd.DataFrame):
    ws = _open_sheet(sheet_id).sheet1
    ws.clear()
    if df.empty:
        return
    ws.update([df.columns.tolist()] + df.astype(str).values.tolist())

def append_row(sheet_id: str, row: Dict[str,str]):
    ws = _open_sheet(sheet_id).sheet1
    headers = ws.row_values(1)
    if not headers:
        headers = list(row.keys()); ws.update([headers])
    ordered = [str(row.get(h, "")) for h in headers]
    ws.append_row(ordered)

def delete_last_row(sheet_id: str):
    ws = _open_sheet(sheet_id).sheet1
    values = ws.get_all_values()
    last = 0
    for i, r in enumerate(values, start=1):
        if any(cell.strip() for cell in r): last = i
    if last > 1: ws.delete_rows(last)
