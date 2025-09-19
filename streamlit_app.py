import streamlit as st
import pandas as pd
from typing import List, Dict, Set
from elo_core import EloEngine, GameRow, make_standings_table
from gsheets_backend import read_sheet_as_df, write_dataframe, append_row, delete_last_row
import io, math, os

import json, textwrap
sa_json = st.secrets.get("GSPREAD_SERVICE_ACCOUNT_JSON", "")
try:
    parsed = json.loads(sa_json)
    st.success("✅ JSON parsed successfully!")
    st.json(parsed)  # show the parsed dict
except Exception as e:
    st.error(f"❌ JSON parse failed: {e}")
    st.code(textwrap.shorten(sa_json, 200))  # show preview



st.set_page_config(page_title="Garner Ultimate Ladder", layout="wide")
st.title("Garner Ultimate Ladder — Google Sheets Edition (v3 + Undo)")

# ---- Config: Sheet IDs from secrets or env ----
SHEET_ID_GAMES = st.secrets.get("SHEET_ID_GAMES", os.environ.get("SHEET_ID_GAMES", "")).strip()
SHEET_ID_ALIASES = st.secrets.get("SHEET_ID_ALIASES", os.environ.get("SHEET_ID_ALIASES", "")).strip()
SHEET_ID_STANDINGS = st.secrets.get("SHEET_ID_STANDINGS", os.environ.get("SHEET_ID_STANDINGS", "")).strip()

if not (SHEET_ID_GAMES and SHEET_ID_ALIASES and SHEET_ID_STANDINGS):
    st.error("Missing sheet IDs. Please set SHEET_ID_GAMES, SHEET_ID_ALIASES, SHEET_ID_STANDINGS in Streamlit secrets.")
    st.stop()

# ---- Load Google Sheets ----
def load_games_df():
    df = read_sheet_as_df(SHEET_ID_GAMES)
    if df.empty:
        return pd.DataFrame(columns=["date","game_id","score_w","score_l","winners","losers"])
    for col in ["date","winners","losers"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    if "game_id" in df.columns:
        df["game_id"] = pd.to_numeric(df["game_id"], errors="coerce").fillna(0).astype(int)
    else:
        df["game_id"] = 0
    if "score_w" in df.columns:
        df["score_w"] = pd.to_numeric(df["score_w"], errors="coerce").fillna(0).astype(int)
    else:
        df["score_w"] = 0
    if "score_l" in df.columns:
        df["score_l"] = pd.to_numeric(df["score_l"], errors="coerce").fillna(0).astype(int)
    else:
        df["score_l"] = 0
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
            cands = [p for p in cands if any(seg.lower().startswith(initial) for seg in p.lower().split()[1:])]
        if len(cands)==1:
            out.append(cands[0]); continue
        out.append(t)
    return out

# Roster inferred from games + baseline
roster = sorted(set(
    list(baseline.keys()) +
    [n for col in ["winners","losers"] for names in games_df[col] for n in str(names).split(";")]
))

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

# Session state for last submission (Undo)
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
        st.success("Standings written to your frisbee_standings sheet.")

    # Download Excel
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df_std.to_excel(writer, index=False, sheet_name="Standings")
        log_rows = [{"date": g.date, "score": f"{g.score_w}-{g.score_l}", "winners": "; ".join(g.winners), "losers": "; ".join(g.losers)} for g in games_list]
        pd.DataFrame(log_rows).to_excel(writer, index=False, sheet_name="Match Log")
    st.download_button("Download Excel Export", data=bio.getvalue(), file_name="ladder_export.xlsx")

# ===== Add Match =====
with tabs[1]:
    st.subheader("Add a Match (writes to your frisbee_games Google Sheet)")
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
        engine = EloEngine(starting_rating=1200.0, K=30.0, forfeit_MOV=0.75, round_display=True)
        games_before = build_games(games_df)
        res_before = engine.recompute(games_before, baseline=baseline if baseline else None)
        ratings_before = res_before["ratings"]

        winners_raw = team1 if score1 >= score2 else team2
        losers_raw  = team2 if score1 >= score2 else team1
        winners = resolve_team(winners_raw, list(ratings_before.keys()), alias_map)
        losers  = resolve_team(losers_raw,  list(ratings_before.keys()), alias_map)

        def rget(n): return ratings_before.get(n, 1200.0)
        RA = sum(rget(n) for n in winners)/len(winners) if winners else 1200.0
        RB = sum(rget(n) for n in losers)/len(losers)  if losers else 1200.0
        pW = 1.0 / (1.0 + 10.0 ** ((RB - RA) / 400.0))
        diff = abs(int(max(score1,score2)) - int(min(score1,score2)))
        MOV = 0.0 if diff==0 else math.log(diff+1) * (2.2 / ((abs(RA-RB)/400.0) + 2.2))
        sW = 1.0 if score1 != score2 else 0.5
        D = 30.0 * MOV * (sW - pW)

        # Append to Google Sheet
        append_row(SHEET_ID_GAMES, {
            "date": date,
            "game_id": "",
            "score_w": str(int(max(score1,score2))),
            "score_l": str(int(min(score1,score2))),
            "winners": ";".join(winners),
            "losers":  ";".join(losers),
        })
        st.session_state.last_added = True

        # Reload games_df for "after"
        games_df[:] = load_games_df()
        games_after = build_games(games_df)
        res_after = engine.recompute(games_after, baseline=baseline if baseline else None)
        ratings_after = res_after["ratings"]

        played = sorted(set(winners + losers))
        rows = [{"Player": p, "Old": round(ratings_before.get(p,1200.0),3), "Δ": round(ratings_after.get(p,1200.0)-ratings_before.get(p,1200.0),3), "New": round(ratings_after.get(p,1200.0),3)} for p in played]

        st.markdown("**Computation details**")
        c3,c4,c5 = st.columns(3)
        c3.metric("Team A (winners) avg", f"{RA:.3f}")
        c4.metric("Team B (losers) avg", f"{RB:.3f}")
        c5.metric("Expected (A)", f"{pW:.3f}")
        c6,c7,c8 = st.columns(3)
        c6.metric("Margin", f"{diff}")
        c7.metric("MOV factor", f"{MOV:.4f}")
        c8.metric("Team delta D", f"{D:.4f}")
        st.dataframe(pd.DataFrame(rows).sort_values("Δ", ascending=False), use_container_width=True)
        st.success("Submitted and saved to Google Sheet.")

    if undo_col.button("Undo last submission (delete last row)"):
        delete_last_row(SHEET_ID_GAMES)
        games_df[:] = load_games_df()
        st.session_state.last_added = False
        st.success("Last submission removed from Google Sheet.")

# ===== All Games =====
with tabs[2]:
    st.subheader("All Games (live from Google Sheet)")
    view = games_df.copy()
    c1, c2 = st.columns(2)
    with c1:
        date_filter = st.text_input("Filter by date (YYYY-MM-DD)", value="")
    with c2:
        player_filter = st.text_input("Filter by player", value="")
    if date_filter.strip():
        view = view[view["date"].astype(str)==date_filter.strip()]
    if player_filter.strip():
        pf = player_filter.strip().lower()
        view = view[view.apply(lambda r: pf in str(r["winners"]).lower() or pf in str(r["losers"]).lower(), axis=1)]
    show = view.copy()
    for col in ("winners","losers"):
        if col in show.columns:
            show[col] = show[col].str.replace(";", "; ")
    cols = [c for c in ["date","game_id","score_w","score_l","winners","losers"] if c in show.columns]
    st.dataframe(show[cols], use_container_width=True)
    st.download_button("Download All Games (CSV)", data=view.to_csv(index=False).encode("utf-8"), file_name="all_games.csv")

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
        tg_wins = together.apply(lambda r: 1 if (p1 in set_from(r["winners"]) and p2 in set_from(r["winners"])) else 0, axis=1).sum()
        tg_losses = len(together) - tg_wins
        vs = games_df[games_df.apply(lambda r: (p1 in set_from(r["winners"]) and p2 in set_from(r["losers"])) or (p2 in set_from(r["winners"]) and p1 in set_from(r["losers"])), axis=1)]
        p1_w = vs.apply(lambda r: 1 if (p1 in set_from(r["winners"]) and p2 in set_from(r["losers"])) else 0, axis=1).sum()
        p1_l = len(vs) - p1_w
        st.markdown(f"**Together:** {int(tg_wins)}-{int(tg_losses)} (games: {len(together)})")
        if len(together): st.dataframe(together[[c for c in ['date','game_id','score_w','score_l','winners','losers'] if c in together.columns]], use_container_width=True)
        st.markdown(f"**Head-to-head ({p1} vs {p2}):** {int(p1_w)}-{int(p1_l)} (games: {len(vs)})")
        if len(vs): st.dataframe(vs[[c for c in ['date','game_id','score_w','score_l','winners','losers'] if c in vs.columns]], use_container_width=True)

st.markdown("---")
st.caption("Exact rules preserved: start 1200, K=30, 400-pt logistic, MOV ln(|Δ|+1)*2.2/((|ΔR|/400)+2.2), team mean, full team delta, forfeit MOV=0.75.")
