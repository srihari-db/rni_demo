"""Curated, parameterized SQL fallback for the prevalidated questions (used ONLY when Genie is unavailable).
Answers are labeled CURATED_SQL_FALLBACK and are never presented as Genie responses."""
from __future__ import annotations

import difflib
from typing import Optional

from .client import GenieAnswer
from .space_config import EXAMPLE_SQL


class CuratedFallback:
    def __init__(self, repo):
        self.repo = repo

    def match(self, question: str) -> Optional[int]:
        qs = [q.lower() for q, _ in EXAMPLE_SQL]
        m = difflib.get_close_matches(question.lower().strip(), qs, n=1, cutoff=0.55)
        return qs.index(m[0]) if m else None

    def answer(self, question: str) -> GenieAnswer:
        i = self.match(question)
        if i is None:
            return GenieAnswer(question, "CURATED_SQL_FALLBACK",
                               text="Genie is unavailable and this question is not in the curated set. "
                                    "Try one of the suggested questions.")
        q, sql = EXAMPLE_SQL[i]
        sql = sql.format(g=self.repo.gold)
        df = self.repo.run_curated(sql)
        return GenieAnswer(question, "CURATED_SQL_FALLBACK", text=f"Curated query for: “{q}”", sql=sql, data=df)
