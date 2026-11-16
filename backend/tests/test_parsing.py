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


def test_csv_workshop_mapping_combines_both_applications_for_one_account():
    entries = parse_import(
        source="csv",
        text="name,github,workshop\nExample,@student-one,CW\nExample,Student-One,AIW\nOther,student-two,AIW\n",
        username_column=1,
        workshop_column=2,
        has_header=True,
        max_bytes=1024,
        max_rows=20,
    )
    assert [(entry.login, entry.workshops) for entry in entries] == [
        ("student-one", ("CW", "AIW")),
        ("student-two", ("AIW",)),
    ]
    assert all(entry.status == "awaiting_resolution" for entry in entries)


def test_csv_header_does_not_consume_a_student_row_slot():
    entries = parse_import(
        source="csv",
        text="github,workshop\nstudent-one,CW\nstudent-two,AIW\n",
        username_column=0,
        workshop_column=1,
        has_header=True,
        max_bytes=1024,
        max_rows=2,
    )
    assert len(entries) == 2


def test_pasted_usernames_can_be_assigned_to_both_workshops():
    entries = parse_import(
        source="lines",
        text="student-one\nstudent-two",
        username_column=None,
        has_header=False,
        workshops=["AIW", "CW"],
        max_bytes=1024,
        max_rows=20,
    )
    assert all(entry.workshops == ("CW", "AIW") for entry in entries)


def test_csv_rejects_unknown_or_missing_workshops_and_keeps_real_duplicates():
    entries = parse_import(
        source="csv",
        text="github,workshop\nstudent-one,CW\nSTUDENT-ONE,CW\nstudent-two,OTHER\nstudent-three,\nstudent-four\nstudent-five,CW;AIW\n",
        username_column=0,
        workshop_column=1,
        has_header=True,
        max_bytes=1024,
        max_rows=20,
    )
    assert [entry.status for entry in entries] == [
        "awaiting_resolution",
        "duplicate_input",
        "invalid_input",
        "invalid_input",
        "invalid_input",
        "awaiting_resolution",
    ]
    assert entries[-1].workshops == ("CW", "AIW")
