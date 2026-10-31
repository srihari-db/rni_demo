"""Genie Conversation API client for the 'RNI Inventory Intelligence Agent'.

* Uses the official Databricks SDK Genie API (start_conversation / create_message / get_message /
  get_message_attachment_query_result) with polling, timeouts and retry on transient errors.
* Returns a structured ``GenieAnswer`` whose ``source`` is "GENIE" only when the response genuinely came from Genie.
* ``CuratedFallback`` answers the prevalidated questions with fixed, parameterized Gold SQL; its answers are
  always labeled source="CURATED_SQL_FALLBACK" and must never be presented as Genie responses.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

log = logging.getLogger("rni.genie")
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}


@dataclass
class GenieAnswer:
    question: str
    source: str                         # GENIE | CURATED_SQL_FALLBACK | ERROR
    text: str = ""
    sql: Optional[str] = None
    data: Optional[pd.DataFrame] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    suggested_questions: List[str] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_s: float = 0.0


class GenieClient:
    def __init__(self, space_id: Optional[str] = None, workspace_client=None, timeout_s: int = 120):
        self.space_id = space_id or os.environ.get("GENIE_SPACE_ID")
        self._w = workspace_client
        self.timeout_s = timeout_s

    @property
    def w(self):
        if self._w is None:
            from databricks.sdk import WorkspaceClient
            self._w = WorkspaceClient()
        return self._w

    @property
    def configured(self) -> bool:
        return bool(self.space_id)

    def _retry(self, fn, *a, attempts=3, **kw):
        for i in range(attempts):
            try:
                return fn(*a, **kw)
            except Exception as e:
                msg = str(e)
                transient = any(s in msg for s in ("429", "503", "502", "504", "TEMPORARILY", "RESOURCE_EXHAUSTED", "timed out"))
                if i == attempts - 1 or not transient:
                    raise
                time.sleep(2 ** i)

    def ask(self, question: str, conversation_id: Optional[str] = None) -> GenieAnswer:
        t0 = time.time()
        if not self.configured:
            return GenieAnswer(question, "ERROR", error="Genie space is not configured")
        try:
            if conversation_id:
                wait = self._retry(self.w.genie.create_message, self.space_id, conversation_id, question)
            else:
                wait = self._retry(self.w.genie.start_conversation, self.space_id, question)
            first = wait.response if hasattr(wait, "response") else None
            conv_id = getattr(first, "conversation_id", None) or getattr(wait, "conversation_id", None)
            msg_id = getattr(first, "message_id", None) or getattr(first, "id", None) or getattr(wait, "message_id", None)
            msg = None
            delay = 1.0
            while time.time() - t0 < self.timeout_s:
                msg = self._retry(self.w.genie.get_message, self.space_id, conv_id, msg_id)
                status = str(getattr(msg.status, "value", msg.status))
                if status in TERMINAL:
                    break
                time.sleep(delay)
                delay = min(delay * 1.5, 5.0)
            else:
                return GenieAnswer(question, "ERROR", conversation_id=conv_id, message_id=msg_id,
                                   error="Genie did not respond in time", elapsed_s=time.time() - t0)
            status = str(getattr(msg.status, "value", msg.status))
            if status != "COMPLETED":
                err = getattr(msg.error, "error", None) if msg.error else status
                return GenieAnswer(question, "ERROR", conversation_id=conv_id, message_id=msg_id,
                                   error=f"Genie could not answer ({err})", elapsed_s=time.time() - t0)
            ans = GenieAnswer(question, "GENIE", conversation_id=conv_id, message_id=msg_id)
            texts = []
            for att in msg.attachments or []:
                if att.text and att.text.content:
                    texts.append(att.text.content)
                if att.suggested_questions and getattr(att.suggested_questions, "questions", None):
                    ans.suggested_questions = list(att.suggested_questions.questions)
                if att.query:
                    ans.sql = att.query.query
                    if att.query.description:
                        texts.insert(0, att.query.description)
                    ans.data = self._result(conv_id, msg_id, att.attachment_id)
            ans.text = "\n\n".join(texts)
            ans.elapsed_s = time.time() - t0
            return ans
        except Exception as e:
            log.exception("Genie request failed")
            return GenieAnswer(question, "ERROR", error=f"{type(e).__name__}", elapsed_s=time.time() - t0)

    def _result(self, conv_id, msg_id, att_id) -> Optional[pd.DataFrame]:
        try:
            r = self._retry(self.w.genie.get_message_attachment_query_result, self.space_id, conv_id, msg_id, att_id)
            sr = r.statement_response
            cols = [c.name for c in sr.manifest.schema.columns]
            rows = (sr.result.data_array or []) if sr.result else []
            df = pd.DataFrame(rows, columns=cols)
            for c in df.columns:
                conv = pd.to_numeric(df[c], errors="coerce")
                if conv.notna().sum() == df[c].notna().sum() and df[c].notna().any():
                    df[c] = conv
            return df
        except Exception as e:
            log.warning("could not fetch Genie query result: %s", e)
            return None
