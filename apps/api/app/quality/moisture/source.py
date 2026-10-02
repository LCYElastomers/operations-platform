"""Moisture source data.

The production source is an Access query. Until synchronization exists the
API can serve a development fixture with the same field names.
"""

import json
import logging
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.quality.moisture.schemas import DataSourceInfo, MoistureRecord

logger = logging.getLogger(__name__)

SOURCE_FIELD_MAP = {
    "DATE": "date",
    "CAMPNO": "campaign_no",
    "LOT": "lot",
    "Location": "location",
    "PRODUCT": "product",
    "AvgOfMOISTURE": "avg_moisture",
    "AvgOfCOLOR": "avg_color",
    "AvgOfCombined_BD": "avg_combined_bd",
}

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "moisture_development_fixture.json"

FIXTURE_DATA_SOURCE = DataSourceInfo(
    kind="development-fixture",
    is_fixture=True,
    label="Development fixture. Not production data.",
)

DATABASE_DATA_SOURCE = DataSourceInfo(
    kind="database",
    is_fixture=False,
    label="Operations database.",
)


def record_from_source_row(row: Mapping[str, Any]) -> MoistureRecord:
    missing = set(SOURCE_FIELD_MAP) - set(row)
    if missing:
        raise ValueError(f"Source row is missing fields: {sorted(missing)}")
    return MoistureRecord.model_validate(
        {domain: row[source] for source, domain in SOURCE_FIELD_MAP.items()}
    )


@lru_cache
def load_fixture_records() -> tuple[MoistureRecord, ...]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    records = tuple(record_from_source_row(row) for row in payload["rows"])
    logger.info("Loaded moisture development fixture: %d records", len(records))
    return records
