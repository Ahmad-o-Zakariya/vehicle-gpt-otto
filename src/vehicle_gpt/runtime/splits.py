"""Source-config split gate for synthetic data; never opens ground-truth storage."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
_SPLITS = yaml.safe_load((ROOT / "configs/splits.yaml").read_text())
_INJECTIONS = yaml.safe_load((ROOT / "configs/injections.yaml").read_text())
_TRAIN_IDS = {str(x).casefold() for x in _SPLITS.get("train_development", [])}
_HELDOUT_TRIP = str(_INJECTIONS["thermal"].get("held_out_trip_id", ""))


def development_trip_ids() -> set[str]:
    return {
        trip
        for trip in _INJECTIONS["thermal"]["trip_ids"]
        if trip != _HELDOUT_TRIP
        and any(inj.endswith(trip.casefold()) for inj in _TRAIN_IDS)
    }


def is_development_trip(trip_id: str) -> bool:
    return trip_id.casefold() in {x.casefold() for x in development_trip_ids()}
