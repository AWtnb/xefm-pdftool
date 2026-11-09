import pytest

from scripts.release import ReleaseError, increment_version, replace_version, version_in_section


@pytest.mark.parametrize(
    ("version", "part", "expected"),
    [
        ("0.2.0", "patch", "0.2.1"),
        ("0.2.0", "minor", "0.3.0"),
        ("0.2.0", "major", "1.0.0"),
    ],
)
def test_increment_version(version: str, part: str, expected: str) -> None:
    assert increment_version(version, part) == expected


def test_version_in_section() -> None:
    content = '[project]\nname = "xefm-pdftool"\nversion = "0.2.0"\n'

    assert version_in_section(content, "project") == "0.2.0"


def test_version_in_section_rejects_missing_version() -> None:
    with pytest.raises(ReleaseError, match="Expected one semantic version"):
        version_in_section('[project]\nname = "xefm-pdftool"\n', "project")


def test_replace_version_only_updates_requested_section() -> None:
    content = '[project]\nversion = "0.2.0"\n\n[tool.example]\nversion = "1.0.0"\n'

    assert replace_version(content, "project", "0.2.1") == (
        '[project]\nversion = "0.2.1"\n\n[tool.example]\nversion = "1.0.0"\n'
    )
