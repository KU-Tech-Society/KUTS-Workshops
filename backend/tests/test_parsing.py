import pytest

from app.parsing import ImportErrorDetail, parse_import


def parse_lines(text: str):
    return parse_import(
        source="lines",
        text=text,
        username_column=None,
        has_header=False,
        max_bytes=1024,
        max_rows=20,
    )


def test_normalizes_usernames_and_deduplicates_case_insensitively():
    entries = parse_lines("octocat\n@OctoCat\nhttps://github.com/other-user/\n")

    assert [entry.status for entry in entries] == [
        "awaiting_resolution",
        "duplicate_input",
        "awaiting_resolution",
    ]
    assert [entry.login for entry in entries] == ["octocat", "OctoCat", "other-user"]


def test_rejects_repository_urls_non_github_urls_and_malformed_logins():
    entries = parse_lines(
        "https://github.com/org/repo\n"
        "https://github.com.evil.example/user\n"
        "https://github.com:bad/user\n"
        "-bad\n"
    )

    assert all(entry.status == "invalid_input" for entry in entries)
    assert "profile URL" in entries[0].message
    assert "github.com only" in entries[1].message


def test_maps_csv_header_and_ignores_unrelated_columns():
    entries = parse_import(
        source="csv",
        text="student,github,email\nA,octocat,a@example.test\nB,@other,b@example.test\n",
        username_column=1,
        has_header=True,
        max_bytes=1024,
        max_rows=20,
    )

    assert [(entry.submitted, entry.login) for entry in entries] == [
        ("octocat", "octocat"),
        ("@other", "other"),
    ]
    assert [entry.source_row for entry in entries] == [2, 3]


@pytest.mark.parametrize(
    ("text", "max_bytes", "max_rows"),
    [("octocat", 2, 20), ("one\ntwo\nthree", 1024, 2)],
)
def test_rejects_oversized_input(text, max_bytes, max_rows):
    with pytest.raises(ImportErrorDetail):
        parse_import(
            source="lines",
            text=text,
            username_column=None,
            has_header=False,
            max_bytes=max_bytes,
            max_rows=max_rows,
        )


def test_handles_invalid_csv_column_and_ragged_rows():
    entries = parse_import(
        source="csv",
        text="name,username\nAda\n",
        username_column=1,
        has_header=True,
        max_bytes=1024,
        max_rows=20,
    )
    assert entries[0].status == "invalid_input"
    assert entries[0].message == "Selected column is missing in this row."
