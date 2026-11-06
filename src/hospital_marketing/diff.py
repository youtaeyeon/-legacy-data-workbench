from datetime import date, datetime

from .domain import FieldChange, Hospital


def _as_text(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def compare_hospital(incoming: Hospital, stored: Hospital) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for field_name in ("hospital_name", "region", "contract_date", "source_updated_at"):
        incoming_value = getattr(incoming, field_name)
        stored_value = getattr(stored, field_name)
        if incoming_value is None:
            continue
        if incoming_value != stored_value:
            changes.append(
                FieldChange(
                    hospital_id=incoming.hospital_id,
                    field_name=field_name,
                    old_value=_as_text(stored_value),
                    new_value=_as_text(incoming_value),
                )
            )
    return changes
