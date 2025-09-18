from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Literal, Any
from datetime import datetime
import math, pandas as pd

def expected_score(RA: float, RB: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((RB - RA) / 400.0))

def mov_factor(RA: float, RB: float, score_a: int, score_b: int) -> float:
    diff = abs(int(score_a) - int(score_b))
    if diff == 0: return 0.0
    denom = (abs(RA - RB) / 400.0) + 2.2
    return math.log(diff + 1) * (2.2 / denom)

@dataclass
class GameRow:
    date: str
    winners: List[str]
    losers: List[str]
    score_w: int
    score_l: int
    forfeit_against: Optional[Literal["A","B"]] = None
    _seq: int = 0

class EloEngine:
    def __init__(self, starting_rating: float = 1200.0, K: float = 30.0, forfeit_MOV: float = 0.75, round_display: bool = True):
        self.starting_rating = float(starting_rating)
        self.K = float(K)
        self.forfeit_MOV = float(forfeit_MOV)
        self.round_display = bool(round_display)

    def recompute(self, games: List[GameRow], baseline: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        R0 = self.starting_rating
        K = self.K
        ratings: Dict[str, float] = {} if baseline is None else baseline.copy()
        records: Dict[str, Dict[str, int]] = {}

        def r(name: str) -> float: return ratings.get(name, R0)
        def ensure(name: str):
            if name not in ratings: ratings[name] = R0
            if name not in records: records[name] = {"games":0,"wins":0,"losses":0,"ties":0}

        def date_key(d: str):
            try: return datetime.fromisoformat(d).timestamp()
            except Exception:
                try: return datetime.strptime(d, "%Y-%m-%d").timestamp()
                except Exception: return float("inf")

        rows = sorted(games, key=lambda g: (date_key(g.date), g._seq))

        for row in rows:
            winners, losers = row.winners, row.losers
            for n in winners + losers: ensure(n)
            RA = sum(r(n) for n in winners)/len(winners)
            RB = sum(r(n) for n in losers)/len(losers)
            pW = expected_score(RA, RB)
            MOV = self.forfeit_MOV if row.forfeit_against in ("A","B") else mov_factor(RA,RB,row.score_w,row.score_l)
            sW = 1.0 if row.score_w>row.score_l else 0.0 if row.score_w<row.score_l else 0.5
            D = K * MOV * (sW - pW)
            for n in winners: ratings[n] = r(n) + D
            for n in losers:  ratings[n] = r(n) - D
            for n in winners:
                rec = records[n]; rec["games"]+=1; rec["wins"]+= (1 if sW==1.0 else 0); rec["losses"]+= (1 if sW==0.0 else 0); rec["ties"]+= (1 if sW==0.5 else 0)
            for n in losers:
                rec = records[n]; rec["games"]+=1; rec["losses"]+= (1 if sW==1.0 else 0); rec["wins"]+= (1 if sW==0.0 else 0); rec["ties"]+= (1 if sW==0.5 else 0)

        return {"ratings": ratings, "records": records}

def make_standings_table(ratings: Dict[str,float], records: Dict[str,Dict[str,int]]):
    rows = []
    for p, rt in ratings.items():
        rec = records.get(p, {"games":0,"wins":0,"losses":0,"ties":0})
        g,w,l,t = rec["games"], rec["wins"], rec["losses"], rec["ties"]
        rows.append({"Player": p, "Rating": round(rt,3), "Games": g, "W": w, "L": l, "T": t})
    df = pd.DataFrame(rows).sort_values(["Rating","Player"], ascending=[False, True]).reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df)+1))
    if df["T"].sum() == 0:
        df = df.drop(columns=["T"])
    return df
