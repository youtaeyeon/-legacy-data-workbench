from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from ..repository import Repository


def _excel_value(value):
    if isinstance(value, str) and value.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def export_marketing_excel(repository: Repository, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    default_sheet = workbook.active
    if default_sheet is not None:
        workbook.remove(default_sheet)

    hospitals = workbook.create_sheet("Hospitals")
    hospitals.append(("hospital_id", "hospital_name", "region", "contract_date", "source_updated_at"))
    for item in repository.list_hospitals():
        hospitals.append(tuple(_excel_value(value) for value in (item.hospital_id, item.hospital_name, item.region, item.contract_date, item.source_updated_at)))

    deliveries = workbook.create_sheet("Deliveries")
    deliveries.append(("hospital_id", "product_name", "delivery_date", "quantity"))
    materials = workbook.create_sheet("Materials")
    materials.append(("hospital_id", "product_name", "material_name", "quantity", "status"))
    channels = workbook.create_sheet("Channels")
    channels.append(("hospital_id", "platform", "channel_name", "url"))
    contents = workbook.create_sheet("RelevantContent")
    contents.append(("hospital_id", "platform", "title", "url", "matched_product", "published_at", "evidence"))

    for hospital in repository.list_hospitals():
        for item in repository.list_deliveries(hospital.hospital_id):
            deliveries.append(tuple(_excel_value(value) for value in (item.hospital_id, item.product_name, item.delivery_date, item.quantity)))
        for item in repository.list_materials(hospital.hospital_id):
            materials.append(tuple(_excel_value(value) for value in (item.hospital_id, item.product_name, item.material_name, item.quantity, item.status)))
        for item in repository.list_channels(hospital.hospital_id):
            channels.append(tuple(_excel_value(value) for value in (item.hospital_id, item.platform, item.channel_name, item.url)))
        for item in repository.list_contents(hospital.hospital_id):
            if item.relevance_status == "relevant":
                contents.append(tuple(_excel_value(value) for value in (item.hospital_id, item.platform, item.title, item.url, item.matched_product, item.published_at, item.evidence)))

    workbook.save(output_path)
    return output_path
