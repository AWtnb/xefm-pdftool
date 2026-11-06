import pymupdf
import pytest

from xefm_pdftool.logic import (
    merge_pdfs,
    parse_page_ranges,
    pdf_name,
    rotate_pdf,
    split_pdf,
)


def make_pdf(path, page_count):
    document = pymupdf.open()
    for number in range(1, page_count + 1):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {number}")
    document.save(path)
    document.close()
    return path


def page_text(path):
    document = pymupdf.open(path)
    try:
        return [page.get_text().strip() for page in document]
    finally:
        document.close()


def test_pdf_name_adds_extension_and_rejects_paths():
    assert pdf_name(" merged ", "default.pdf") == "merged.pdf"
    assert pdf_name("", "default.pdf") == "default.pdf"
    assert pdf_name("../outside.pdf", "default.pdf") is None


def test_parse_page_ranges():
    assert parse_page_ranges("1-3, 5, 8-10") == [(1, 3), (5, 5), (8, 10)]
    assert parse_page_ranges("1-1000000000") == [(1, 1000000000)]
    for text in ("", "0", "3-1", "1-2,2-3", "one"):
        with pytest.raises(ValueError):
            parse_page_ranges(text)


def test_merge_pdfs_preserves_source_order(tmp_path):
    first = make_pdf(tmp_path / "first.pdf", 2)
    second = make_pdf(tmp_path / "second.pdf", 1)
    target = tmp_path / "merged.pdf"

    merge_pdfs([first, second], target)

    assert page_text(target) == ["Page 1", "Page 2", "Page 1"]
    assert first.exists() and second.exists()


def test_merge_pdfs_refuses_to_overwrite_a_source(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 1)

    with pytest.raises(ValueError, match="overwrite an input"):
        merge_pdfs([source], source)

    assert page_text(source) == ["Page 1"]


def test_split_pdf_writes_requested_ranges(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 5)
    first = tmp_path / "pages-1-2.pdf"
    second = tmp_path / "pages-5.pdf"

    split_pdf(source, [(1, 2), (5, 5)], [first, second])

    assert page_text(first) == ["Page 1", "Page 2"]
    assert page_text(second) == ["Page 5"]
    assert source.exists()


def test_split_pdf_rejects_out_of_bounds_without_outputs(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 2)
    target = tmp_path / "pages.pdf"

    with pytest.raises(ValueError, match="exceeds"):
        split_pdf(source, [(1, 3)], [target])

    assert not target.exists()


def test_rotate_pdf_rotates_copy_and_preserves_source(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 1)
    target = tmp_path / "rotated.pdf"

    rotate_pdf(source, target)

    original = pymupdf.open(source)
    rotated = pymupdf.open(target)
    try:
        assert original[0].rotation == 0
        assert rotated[0].rotation == 90
    finally:
        original.close()
        rotated.close()


def test_rotate_pdf_rejects_unsupported_angle(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 1)

    with pytest.raises(ValueError, match="Rotation"):
        rotate_pdf(source, tmp_path / "rotated.pdf", 45)
