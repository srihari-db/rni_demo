"""Source adapters. The demo uses SyntheticSource; production adapters would implement the same interface.

Planned real integrations (not implemented — no live GCP/SAP connectivity is required or attempted):
  * RniCloudSqlMySqlSource  — Lakehouse Federation / Lakeflow Connect to Cloud SQL MySQL (inventory, PAR, usage)
  * RniCloudSqlPostgresSource — telemetry/audit tables (Cloud SQL PostgreSQL)
  * SapOrdersSource         — SAP outbound orders, deliveries and returns (e.g. via SAP connector / extracts)
  * ClearBladeTelemetrySource — device telemetry via Pub/Sub -> Zerobus Ingest / structured streaming
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict

import pandas as pd


class RniSource(ABC):
    name: str

    @abstractmethod
    def extract(self) -> Dict[str, pd.DataFrame]:
        """Return {logical_table_name: DataFrame} in the canonical bronze schema."""


class SyntheticSource(RniSource):
    name = "SYNTHETIC_SIMULATOR"

    def __init__(self, config: dict):
        self.config = config

    def extract(self) -> Dict[str, pd.DataFrame]:
        from .simulator import simulate
        return simulate(self.config)


class NotConfiguredSource(RniSource):
    """Placeholder for real connectors; raises clearly instead of silently returning nothing."""

    def __init__(self, name: str):
        self.name = name

    def extract(self):
        raise NotImplementedError(f"{self.name} is a future integration; the demo runs on SyntheticSource only.")
