from dataclasses import dataclass, field


@dataclass(frozen=True)
class ImportIssue:
    file_name: str
    sheet: str | None
    row: int | None
    field: str | None
    code: str
    message: str


@dataclass
class ImportReport:
    source_dir: str = ""
    source_files: list[str] = field(default_factory=list)
    files_seen: int = 0
    files_failed: int = 0
    documents_converted_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    inserted_hospital_ids: list[str] = field(default_factory=list)
    updated_hospital_ids: list[str] = field(default_factory=list)
    missing_hospital_ids: list[str] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return self.files_failed > 0 or bool(self.issues)
