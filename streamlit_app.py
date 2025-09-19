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
