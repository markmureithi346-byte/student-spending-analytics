"""Validate a single transactions CSV and run each upload as an isolated analysis.

The platform never edits the committed warehouse. Every accepted upload gets its
own id, input directory, SQLite database and report; the uploaded bytes are only
parsed as CSV and then processed by the same pipeline used from the CLI. Student
profiles are derived from the transaction student IDs and budgets are optional,
so the user only has to supply one file.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import re
import shutil
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path

from . import config
from .extract import TRANSACTION_COLUMNS

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_FILE_BYTES + 1024 * 1024
MAX_CSV_ROWS = 50_000
MAX_PARTS = 12
MAX_TITLE_LENGTH = 80
ANALYSIS_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")
_RUN_LOCK = threading.Lock()

FILE_FIELDS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "transactions": ("Transactions CSV", TRANSACTION_COLUMNS, "transactions.csv"),
}


class UploadError(ValueError):
    """A user-correctable problem with an upload."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


class PipelineFailure(UploadError):
    """The files were readable but the pipeline could not build an analysis."""


@dataclass(frozen=True)
class UploadedCsv:
    field: str
    original_name: str
    payload: bytes
    row_count: int


@dataclass(frozen=True)
class UploadBundle:
    title: str
    files: dict[str, UploadedCsv]


@dataclass(frozen=True)
class AnalysisWorkspace:
    analysis_id: str
    title: str
    created_at: str
    status: str
    run_id: str
    rows_read: int
    rows_accepted: int
    rows_quarantined: int
    quality_failures: int
    db_path: Path
    report_path: Path
    inputs: dict[str, dict[str, object]]


def new_analysis_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def is_valid_analysis_id(value: str) -> bool:
    return bool(ANALYSIS_ID_PATTERN.fullmatch(value))


def parse_upload(content_type: str, body: bytes) -> UploadBundle:
    """Parse and validate a multipart upload without touching the filesystem."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise UploadError(
            "The upload must use the multipart form on this page.", status=415
        )
    try:
        header = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
        ).encode("latin-1")
    except UnicodeEncodeError:
        raise UploadError("The upload headers are not valid.") from None

    message = BytesParser(policy=policy.HTTP).parsebytes(header + body)
    if not message.is_multipart():
        raise UploadError("The upload form could not be read.")

    parts = list(message.iter_parts())
    if len(parts) > MAX_PARTS:
        raise UploadError("The upload form has too many fields.", status=413)

    files: dict[str, UploadedCsv] = {}
    seen: set[str] = set()
    title = ""
    synthetic = False

    for part in parts:
        if part.is_multipart():
            raise UploadError("Nested multipart uploads are not accepted.")
        field = part.get_param("name", header="content-disposition")
        if not isinstance(field, str) or not field:
            raise UploadError("The upload form contains an unnamed field.")
        if field in seen:
            raise UploadError(f"The field {field!r} appeared more than once.")
        seen.add(field)

        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if field in FILE_FIELDS:
            label, columns, _ = FILE_FIELDS[field]
            if filename is None or not filename.strip():
                raise UploadError(f"Choose a file for {label}.")
            if len(payload) > MAX_FILE_BYTES:
                raise UploadError(
                    f"{label} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB."
                )
            original_name = _clean_filename(filename)
            if not original_name.lower().endswith(".csv"):
                raise UploadError(f"{label} must be a .csv file.")
            row_count = _inspect_csv(payload, label, columns)
            files[field] = UploadedCsv(
                field=field,
                original_name=original_name,
                payload=payload,
                row_count=row_count,
            )
        elif field == "title":
            title = _clean_text(_decode_text(payload, "Title")).strip()
            if len(title) > MAX_TITLE_LENGTH:
                raise UploadError(
                    f"The analysis title must be {MAX_TITLE_LENGTH} characters or fewer."
                )
        elif field == "synthetic":
            synthetic = _decode_text(payload, "Synthetic confirmation").strip().lower() in {
                "yes",
                "on",
                "true",
            }
        else:
            raise UploadError(f"Unexpected field {field!r} in the upload form.")

    missing = [FILE_FIELDS[field][0] for field in FILE_FIELDS if field not in files]
    if missing:
        raise UploadError("Add the missing file(s): " + ", ".join(missing) + ".")
    if not synthetic:
        raise UploadError(
            "Confirm that the file contains only synthetic data before running analysis."
        )
    return UploadBundle(title=title, files=files)


def create_analysis(bundle: UploadBundle) -> AnalysisWorkspace:
    """Persist the files, run the pipeline and return the finished workspace."""
    analysis_id = new_analysis_id()
    data_root = Path(config.UPLOAD_DATA_DIR) / analysis_id
    db_path = Path(config.UPLOAD_WAREHOUSE_DIR) / f"{analysis_id}.db"
    report_dir = Path(config.UPLOAD_REPORT_DIR) / analysis_id
    quarantine_dir = data_root / "quarantine"

    try:
        data_root.mkdir(parents=True, exist_ok=False)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)
        for field, info in FILE_FIELDS.items():
            (data_root / info[2]).write_bytes(bundle.files[field].payload)

        from .cli import PipelineOptions, run_pipeline

        options = PipelineOptions(
            transactions_csv=data_root / FILE_FIELDS["transactions"][2],
            profiles_csv=None,
            budgets_csv=None,
            db_path=db_path,
            reports_dir=report_dir,
            quarantine_dir=quarantine_dir,
        )
        output = io.StringIO()
        with _RUN_LOCK, contextlib.redirect_stdout(output):
            code = run_pipeline(options)

        run = _read_run(db_path)
        quality_failures = _read_quality_failures(db_path, str(run.get("run_id", "")))
        if code in (2, 3) or not run:
            message = str(
                run.get("message")
                or "The pipeline could not build an analysis from these files."
            )
            raise PipelineFailure(message)
        if int(run.get("rows_accepted", 0)) == 0:
            raise PipelineFailure(
                "No clean transactions could be loaded. Check the CSV columns and values."
            )

        status = "success" if code == 0 else "quality_failed"
        created_at = config.utc_now()
        metadata = {
            "version": 1,
            "analysis_id": analysis_id,
            "title": bundle.title or "Untitled analysis",
            "created_at": created_at,
            "status": status,
            "run_id": run.get("run_id", ""),
            "rows_read": _as_int(run.get("rows_read")),
            "rows_accepted": _as_int(run.get("rows_accepted")),
            "rows_quarantined": _as_int(run.get("rows_quarantined")),
            "quality_failures": quality_failures,
            "inputs": {
                field: {
                    "filename": bundle.files[field].original_name,
                    "rows": bundle.files[field].row_count,
                }
                for field in FILE_FIELDS
            },
        }
        temporary = data_root / "metadata.json.tmp"
        temporary.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(data_root / "metadata.json")

        logger.info(
            "analysis %s built with exit %d (%d accepted, %d flagged checks)",
            analysis_id,
            code,
            _as_int(run.get("rows_accepted")),
            quality_failures,
        )
        logger.debug("pipeline output for %s:\n%s", analysis_id, output.getvalue())

        workspace = workspace_for(analysis_id)
        if workspace is None:
            raise PipelineFailure("The analysis files could not be published.")
        return workspace
    except Exception:
        _discard_workspace(analysis_id)
        raise


def workspace_for(analysis_id: str) -> AnalysisWorkspace | None:
    """Return a published analysis only when its metadata and database exist."""
    if not is_valid_analysis_id(analysis_id):
        return None
    data_root = Path(config.UPLOAD_DATA_DIR) / analysis_id
    db_path = Path(config.UPLOAD_WAREHOUSE_DIR) / f"{analysis_id}.db"
    report_path = (
        Path(config.UPLOAD_REPORT_DIR) / analysis_id / "spending_report.html"
    )
    metadata = _read_metadata(data_root / "metadata.json")
    if not metadata or not db_path.is_file():
        return None
    if metadata.get("analysis_id") != analysis_id:
        return None

    status = str(metadata.get("status", "unknown"))
    if status not in {"success", "quality_failed"}:
        return None
    inputs = metadata.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}
    return AnalysisWorkspace(
        analysis_id=analysis_id,
        title=_clean_text(str(metadata.get("title", "")))[:MAX_TITLE_LENGTH]
        or "Untitled analysis",
        created_at=str(metadata.get("created_at", "")),
        status=status,
        run_id=str(metadata.get("run_id", "")),
        rows_read=_as_int(metadata.get("rows_read")),
        rows_accepted=_as_int(metadata.get("rows_accepted")),
        rows_quarantined=_as_int(metadata.get("rows_quarantined")),
        quality_failures=_as_int(metadata.get("quality_failures")),
        db_path=db_path,
        report_path=report_path,
        inputs={
            str(key): value
            for key, value in inputs.items()
            if isinstance(value, dict)
        },
    )


def list_analyses(limit: int = 8) -> list[AnalysisWorkspace]:
    """Newest published analyses first, ignoring incomplete workspaces."""
    root = Path(config.UPLOAD_DATA_DIR)
    if not root.is_dir():
        return []
    analyses: list[AnalysisWorkspace] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not is_valid_analysis_id(entry.name) or not entry.is_dir():
            continue
        workspace = workspace_for(entry.name)
        if workspace is not None:
            analyses.append(workspace)
    analyses.sort(key=lambda item: (item.created_at, item.analysis_id), reverse=True)
    return analyses[: max(0, limit)]


def _inspect_csv(payload: bytes, label: str, columns: tuple[str, ...]) -> int:
    text = _decode_text(payload, label)
    if "\x00" in text:
        raise UploadError(f"{label} contains binary data, not CSV text.")
    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = [cell.strip() for cell in next(reader)]
        except StopIteration:
            raise UploadError(f"{label} is empty.") from None
        missing = [column for column in columns if column not in header]
        if missing:
            raise UploadError(
                f"{label} is missing required column(s): {', '.join(missing)}."
            )
        data_rows = 0
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            data_rows += 1
            if data_rows > MAX_CSV_ROWS:
                raise UploadError(
                    f"{label} has more than {MAX_CSV_ROWS:,} data rows."
                )
    except csv.Error as error:
        raise UploadError(f"{label} could not be parsed as CSV: {error}.") from None
    if data_rows == 0:
        raise UploadError(f"{label} has a header but no data rows.")
    return data_rows


def _decode_text(payload: bytes, label: str) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadError(f"{label} must be UTF-8 encoded text.") from None


def _clean_text(value: str) -> str:
    return "".join(character for character in value if character.isprintable())


def _clean_filename(value: str) -> str:
    name = Path(value.replace("\\", "/")).name
    cleaned = _clean_text(name).strip()[:120]
    return cleaned or "upload.csv"


def _read_metadata(path: Path) -> dict:
    try:
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_run(db_path: Path) -> dict:
    if not db_path.is_file():
        return {}
    try:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT * FROM pipeline_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}
    return dict(row) if row is not None else {}


def _read_quality_failures(db_path: Path, run_id: str) -> int:
    if not run_id or not db_path.is_file():
        return 0
    try:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM data_quality_results "
                "WHERE run_id = ? AND passed = 0",
                (run_id,),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _discard_workspace(analysis_id: str) -> None:
    """Remove only the partial files this upload created."""
    shutil.rmtree(Path(config.UPLOAD_DATA_DIR) / analysis_id, ignore_errors=True)
    (Path(config.UPLOAD_WAREHOUSE_DIR) / f"{analysis_id}.db").unlink(missing_ok=True)
    shutil.rmtree(Path(config.UPLOAD_REPORT_DIR) / analysis_id, ignore_errors=True)
