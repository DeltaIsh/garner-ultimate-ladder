import streamlit as st
import gspread
import json

st.title("Google Sheets Connection Test")

# Load service account JSON from secrets
try:
    sa_json = st.secrets["GSPREAD_SERVICE_ACCOUNT_JSON"]
    creds = json.loads(sa_json)
    st.success("✅ JSON parsed successfully")
except Exception as e:
    st.error(f"❌ Failed to parse JSON: {e}")
    st.stop()

# Try to connect to Google Sheets
try:
    gc = gspread.service_account_from_dict(creds)
    st.success("✅ Authenticated with Google Sheets")
except Exception as e:
    st.error(f"❌ Failed to authenticate with Google Sheets: {e}")
    st.stop()

# Try to open one of your sheets
SHEET_ID = st.secrets.get("SHEET_ID_GAMES", "")
if not SHEET_ID:
    st.error("❌ Missing SHEET_ID_GAMES in secrets")
    st.stop()

try:
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1
    data = ws.get_all_records()
    st.success(f"✅ Successfully opened sheet: {sh.title}")
    if data:
        st.write("First few rows from sheet1:", data[:5])
    else:
        st.info("Sheet is empty or has no headers yet.")
except Exception as e:
    st.error(f"❌ Failed to open sheet: {e}")
