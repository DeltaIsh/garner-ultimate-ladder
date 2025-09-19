import streamlit as st
import pandas as pd
import math, io, os, json
from typing import List, Dict, Set
import gspread

from elo_core import EloEngine, GameRow, make_standings_table

st.set_page_config(page_title="Garner Ultimate Ladder", layout="wide")
st.title("Garner Ultimate Ladder — Google Sheets Edition (v3 + Undo)")

# ---- Connect to Google Sheets ----
try:
    sa_json = st.secrets["GSPREAD_SERVICE_ACCOUNT_JSON"]
    creds = json.loads(sa_json)
    gc = gspread.service_account_from_dict(creds)
    st.success("✅ Connected to Google Sheets")
except Exception as e:
    st.error(f"❌ Failed to connect to Google Sheets: {e}")
    st.stop()

# ---- Config: Sheet IDs ----
SHEET_ID_GAMES = st.secrets.get("SHEET_ID_GAMES", "")
SHEET_ID_ALIASES = st.secrets.get("SHEET_ID_ALIASES", "")
SHEET_ID_STANDINGS = st.secrets.get("SHEET_ID_STANDINGS", "")

if not (SHEET_ID_GAMES and SHEET_ID_ALIASES and SHEET_ID_STANDINGS):
    st.error("❌ Missing one of the sheet IDs (games, aliases, standings) in secrets.")
    st.stop()

# ---- Helpers for reading/writing ----
def read_sheet_as_df(sheet_id):
    try:
        sh = gc.open_by_key(sheet_id)
        ws = sh.sheet1
        data = ws.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error reading sheet {sheet_id}: {e}")
        return pd.DataFrame()

def write_dataframe(sheet_id, df):
    try:
        sh = gc.open_by_key(sheet_id)
        ws = sh.sheet1
        ws.clear()
        ws.update([df.columns.values.tolist()] + df.values.tolist())
    except Exception as e:
        st.error(f"Error writing to sheet {sheet_id}: {e}")

def append_row(sheet_id, row_dict):
    try:
        sh = gc.open_by_key(sheet_id)
        ws = sh.sheet1
        ws.append_row([row_dict.get(c, "") for c in ["date","game_id","score_w","score_l","winners","losers"]])
    except Exception as e:
        st.error(f"Error appending row to sheet {sheet_id}: {e}")

def delete_last_row(sheet_id):
    try:
        sh = gc.open_by_key(sheet_id)
        ws = sh.sheet1
        n = len(ws.get_all_values())
        if n > 1:
            ws.delete_rows(n)
    except Exception as e:
        st.error(f"Error deleting last row from sheet {sheet_id}: {e}")

# ---- Load DataFrames ----
def load_games_df():
    df = read_sheet_as_df(SHEET_ID_GAMES)
    if df.empty:
        return pd.DataFrame(columns=["date","game_id","score_w","score_l","winners","losers"])
    for col in ["date","winners","losers"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    for c in ["game_id","score_w","score_l"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    return df

def load_aliases_df():
    df = read_sheet_as_df(SHEET_ID_ALIASES)
    if df.empty:
        return pd.DataFrame(columns=["alias","canonical"])
    df["alias"] = df["alias"].astype(str)
    df["canonical"] = df["canonical"].astype(str)
    return df

def load_standings_baseline():
    df = read_sheet_as_df(SHEET_ID_STANDINGS)
    if df.empty or "Player" not in df.columns or "Rating" not in df.columns:
        return {}
    out = {}
    for _, r in df.iterrows():
        try:
            out[str(r["Player"])] = float(r["Rating"])
        except Exception:
            pass
    return out

games_df = load_games_df()
aliases_df = load_aliases_df()
baseline = load_standings_baseline()

alias_map = {row["alias"].strip().lower(): row["canonical"].strip() for _, row in aliases_df.iterrows()}

def resolve_team(raw: str, roster: List[str], alias_map: Dict[str,str]) -> List[str]:
    chunks = [x.strip() for x in str(raw).split(";") if x.strip()]
    out = []
    lowers = {p.lower(): p for p in roster}
    for tok in chunks:
        t = tok.strip()
        if t.lower() in alias_map:
            out.append(alias_map[t.lower()]); continue
        if t.lower() in lowers:
            out.append(lowers[t.lower()]); continue
        parts = t.split()
        first = parts[0].lower()
        initial = parts[1][0].lower() if len(parts)>1 and parts[1] else None
        cands = [p for p in roster if p.lower().split()[0] == first]
        if initial:
            cands = [p for p in cands if any(seg.lower().startswith(initial) for seg in p.lower().split()[1:]) ]
        if len(cands)==1:
            out.append(cands[0]); continue
        out.append(t)
    return out

# Roster inferred from games + baseline
roster = sorted(set(list(baseline.keys()) + [n for col in ["winners","losers"] for names in games_df[col] for n in str(names).split(";")])))

def build_games(df: pd.DataFrame) -> List[GameRow]:
    rows = []
    for _, r in df.iterrows():
        rows.append(GameRow(
            date=str(r["date"]),
            winners=str(r["winners"]).split(";"),
            losers=str(r["losers"]).split(";"),
            score_w=int(r["score_w"]),
            score_l=int(r["score_l"]),
            _seq=int(r["game_id"]),
        ))
    return rows

# Session state for Undo
if "last_added" not in st.session_state:
    st.session_state.last_added = False

tabs = st.tabs(["Standings", "Add Match", "All Games", "Pair Filter"])

# ===== Standings =====
with tabs[0]:
    st.subheader("Standings (computed from Google Sheet games)")
    engine = EloEngine(starting_rating=1200.0, K=30.0, forfeit_MOV=0.75, round_display=True)
    games_list = build_games(games_df)
    result = engine.recompute(games_list, baseline=baseline if baseline else None)
    df_std = make_standings_table(result["ratings"], result["records"])
    st.dataframe(df_std, use_container_width=True)

    if st.button("Publish current standings to Google Sheet"):
        write_dataframe(SHEET_ID_STANDINGS, df_std)
        st.success("Standings written to frisbee_standings sheet.")

    # Excel export
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df_std.to_excel(writer, index=False, sheet_name="Standings")
    st.download_button("Download Excel Export", data=bio.getvalue(), file_name="ladder_export.xlsx")

# ===== Add Match =====
with tabs[1]:
    st.subheader("Add a Match")
    c1, c2 = st.columns(2)
    with c1:
        date = st.text_input("Date (YYYY-MM-DD)", value=pd.Timestamp.now().strftime("%Y-%m-%d"))
        team1 = st.text_input("Team 1 (aliases ok; ';' separated)", value="")
        score1 = st.number_input("Team 1 score", min_value=0, step=1, value=7)
    with c2:
        team2 = st.text_input("Team 2 (aliases ok; ';' separated)", value="")
        score2 = st.number_input("Team 2 score", min_value=0, step=1, value=6)

    add_col, undo_col = st.columns([1,1])
    if add_col.button("Submit to Google Sheet"):
        winners_raw = team1 if score1 >= score2 else team2
        losers_raw  = team2 if score1 >= score2 else team1
        winners = resolve_team(winners_raw, roster, alias_map)
        losers  = resolve_team(losers_raw,  roster, alias_map)

        append_row(SHEET_ID_GAMES, {
            "date": date,
            "game_id": "",
            "score_w": str(int(max(score1,score2))),
            "score_l": str(int(min(score1,score2))),
            "winners": ";".join(winners),
            "losers":  ";".join(losers),
        })
        st.session_state.last_added = True
        st.success("✅ Submitted and saved to Google Sheet")

    if undo_col.button("Undo last submission (delete last row)") and st.session_state.last_added:
        delete_last_row(SHEET_ID_GAMES)
        st.session_state.last_added = False
        st.success("✅ Last submission removed")

# ===== All Games =====
with tabs[2]:
    st.subheader("All Games (live from Google Sheet)")
    view = games_df.copy()
    if not view.empty:
        for col in ("winners","losers"):
            if col in view.columns:
                view[col] = view[col].str.replace(";", "; ")
        st.dataframe(view, use_container_width=True)
    else:
        st.info("No games found yet.")

# ===== Pair Filter =====
with tabs[3]:
    st.subheader("Pair Filter")
    roster_pf = sorted(set([n for col in ["winners","losers"] for names in games_df[col] for n in str(names).split(";")]))
    if not roster_pf:
        st.info("No players found yet.")
    else:
        p1 = st.selectbox("Player 1", roster_pf)
        p2 = st.selectbox("Player 2", [x for x in roster_pf if x != p1] or [p1])
        def set_from(s: str) -> Set[str]:
            return set([x for x in str(s).split(";") if x])
        together = games_df[games_df.apply(lambda r: (p1 in set_from(r["winners"]) and p2 in set_from(r["winners"])) or (p1 in set_from(r["losers"]) and p2 in set_from(r["losers"])), axis=1)]
        vs = games_df[games_df.apply(lambda r: (p1 in set_from(r["winners"]) and p2 in set_from(r["losers"])) or (p2 in set_from(r["winners"]) and p1 in set_from(r["losers"])), axis=1)]
        st.markdown(f"**Together:** {len(together)} games")
        if len(together): st.dataframe(together, use_container_width=True)
        st.markdown(f"**Head-to-head ({p1} vs {p2}):** {len(vs)} games")
        if len(vs): st.dataframe(vs, use_container_width=True)

st.markdown("---")
st.caption("Exact rules preserved: start 1200, K=30, 400-pt logistic, MOV ln(|Δ|+1)*2.2/((|ΔR|/400)+2.2), team mean, full team delta, forfeit MOV=0.75.")
