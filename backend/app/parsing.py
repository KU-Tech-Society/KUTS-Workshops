import csv
import io
import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


@dataclass(frozen=True)
class ImportedEntry:
    submitted: str
    status: str
    message: str | None
    login: str | None
    source_row: int
    workshops: tuple[str, ...] = ()


class ImportErrorDetail(ValueError):
    pass


def _normalize(value: str) -> tuple[str | None, str | None]:
    value = value.strip()
    if not value:
        return None, "Empty value."

    if value.startswith("@"):
        value = value[1:]
    elif "://" in value:
        try:
            parsed = urlsplit(value)
            valid_profile_host = (
                parsed.scheme.lower() == "https"
                and parsed.hostname is not None
                and parsed.hostname.lower() == "github.com"
                and parsed.username is None
                and parsed.password is None
                and parsed.port is None
            )
        except ValueError:
            parsed = None
            valid_profile_host = False
        if not valid_profile_host or parsed is None or parsed.query or parsed.fragment:
            return None, "Use a GitHub profile URL on https://github.com only."
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 1 or not parts[0]:
            return None, "Use a profile URL, not a repository or nested path."
        value = parts[0]
    elif "/" in value or "\\" in value:
        return None, "Enter a username or a GitHub profile URL."

    if len(value) > 39 or not LOGIN_PATTERN.fullmatch(value):
        return (
            None,
            "Username must be 1-39 letters, numbers, or hyphens and cannot start or end with a hyphen.",
        )
    return value, None


def parse_import(
    *,
    source: str,
    text: str,
    username_column: int | None,
    has_header: bool,
    max_bytes: int,
    max_rows: int,
    workshop_column: int | None = None,
    workshops: list[str] | None = None,
) -> list[ImportedEntry]:
    if len(text.encode("utf-8")) > max_bytes:
        raise ImportErrorDetail(f"Input exceeds the {max_bytes:,}-byte limit.")
    if any(workshop not in {"CW", "AIW"} for workshop in workshops or []):
        raise ImportErrorDetail("Choose CW, AIW, or both workshops.")
    if workshop_column is not None and (
        source != "csv" or workshop_column < 0 or workshop_column == username_column
    ):
        raise ImportErrorDetail(
            "Choose a separate non-negative workshop column for CSV input."
        )

    if source == "lines":
        rows = [[line] for line in text.splitlines()]
        column = 0
    elif source == "csv":
        if username_column is None or username_column < 0:
            raise ImportErrorDetail("Choose a non-negative username column.")
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error as exc:
            raise ImportErrorDetail(
                "CSV could not be parsed. Check its quoting and separators."
            ) from exc
        column = username_column
    else:
        raise ImportErrorDetail("Unsupported input format.")

    if len(rows) - int(source == "csv" and has_header) > max_rows:
        raise ImportErrorDetail(f"Input exceeds the {max_rows:,}-row limit.")
    if not rows:
        raise ImportErrorDetail("Add at least one username.")
    if has_header and source == "csv":
        if column >= len(rows[0]):
            raise ImportErrorDetail(
                "The selected username column is not present in the header row."
            )
        rows = rows[1:]

    seen: dict[str, int] = {}
    results: list[ImportedEntry] = []
    for row_number, row in enumerate(
        rows, start=2 if has_header and source == "csv" else 1
    ):
        if not any(cell.strip() for cell in row):
            continue
        if column >= len(row):
            results.append(
                ImportedEntry(
                    "",
                    "invalid_input",
                    "Selected column is missing in this row.",
                    None,
                    row_number,
                )
            )
            continue

        submitted = row[column].strip()
        row_workshops = set(workshops or [])
        if workshop_column is not None:
            if workshop_column >= len(row):
                results.append(
                    ImportedEntry(
                        submitted,
                        "invalid_input",
                        "Workshop column is missing in this row.",
                        None,
                        row_number,
                    )
                )
                continue
            row_workshops = set(
                re.split(r"[;,|\s]+", row[workshop_column].strip().upper())
            )
            if not row_workshops or not row_workshops <= {"CW", "AIW"}:
                results.append(
                    ImportedEntry(
                        submitted,
                        "invalid_input",
                        "Workshop must be CW, AIW, or CW;AIW for both.",
                        None,
                        row_number,
                    )
                )
                continue
        assigned = tuple(
            workshop for workshop in ("CW", "AIW") if workshop in row_workshops
        )
        login, message = _normalize(submitted)
        if login is None:
            results.append(
                ImportedEntry(
                    submitted, "invalid_input", message, None, row_number, assigned
                )
            )
            continue

        key = login.casefold()
        if key in seen:
            original_index = seen[key]
            original = results[original_index]
            if row_workshops - set(original.workshops):
                combined = tuple(
                    workshop
                    for workshop in ("CW", "AIW")
                    if workshop in row_workshops or workshop in original.workshops
                )
                results[original_index] = replace(original, workshops=combined)
                continue
            results.append(
                ImportedEntry(
                    submitted,
                    "duplicate_input",
                    "This username was already included for these workshops.",
                    login,
                    row_number,
                    assigned,
                )
            )
            continue
        seen[key] = len(results)
        results.append(
            ImportedEntry(
                submitted, "awaiting_resolution", None, login, row_number, assigned
            )
        )

    if not results:
        raise ImportErrorDetail("No usernames were found in the selected column.")
    return results
