import pymupdf
import pytest

from xefm_pdftool.logic import (
    apply_trimbox_pdf,
    extract_pdf,
    insert_pdf,
    merge_pdfs,
    parse_page_ranges,
    pdf_name,
    rotate_pdf,
    split_pages_pdf,
    split_pdf,
    spread_pages_pdf,
    swap_pdf,
    trim_margin_pdf,
    unzip_pdf,
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
    assert parse_page_ranges("1-3, 5, 8-10", 10) == [
        (1, 3),
        (5, 5),
        (8, 10),
    ]
    assert parse_page_ranges("1-1000000000", 1_000_000_000) == [
        (1, 1_000_000_000)
    ]
    for text in ("", "0", "3-1", "1-2,2-3", "one"):
        with pytest.raises(ValueError):
            parse_page_ranges(text, 10)


def test_parse_page_ranges_supports_pdfjig_syntax_with_page_count():
    assert parse_page_ranges(
        "1-3,5,7-,-3--1", 10, allow_overlaps=True
    ) == [(1, 3), (5, 5), (7, 10), (8, 10)]
    assert parse_page_ranges("-1", 3) == [(3, 3)]
    assert parse_page_ranges("-3--1", 5) == [(3, 5)]
    assert parse_page_ranges("2-", 5) == [(2, 5)]
    for text in ("", "0", "1-0", "5-3", "1-4", "abc"):
        with pytest.raises(ValueError):
            parse_page_ranges(text, 3)

    with pytest.raises(ValueError, match="outside"):
        parse_page_ranges("-4", 3)


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


def test_rotate_pdf_can_rotate_only_selected_pages(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 3)
    target = tmp_path / "rotated.pdf"

    rotate_pdf(source, target, -90, page_ranges="-1")

    original = pymupdf.open(source)
    rotated = pymupdf.open(target)
    try:
        assert [page.rotation for page in original] == [0, 0, 0]
        assert [page.rotation for page in rotated] == [0, 0, 270]
    finally:
        original.close()
        rotated.close()


def test_extract_pdf_writes_selected_pages_in_requested_order(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 5)
    target = tmp_path / "extracted.pdf"

    extract_pdf(source, target, "-1,1-2")

    assert page_text(target) == ["Page 5", "Page 1", "Page 2"]
    assert source.exists()


def test_insert_pdf_inserts_other_document_before_requested_page(tmp_path):
    base = make_pdf(tmp_path / "base.pdf", 3)
    inserted = make_pdf(tmp_path / "inserted.pdf", 2)
    target = tmp_path / "result.pdf"

    insert_pdf(base, inserted, target, start=2)

    assert page_text(target) == ["Page 1", "Page 1", "Page 2", "Page 2", "Page 3"]
    assert base.exists() and inserted.exists()


def test_swap_pdf_replaces_the_same_number_of_base_pages_as_inserted(tmp_path):
    base = make_pdf(tmp_path / "base.pdf", 4)
    replacement = make_pdf(tmp_path / "replacement.pdf", 2)
    target = tmp_path / "result.pdf"

    swap_pdf(base, replacement, target, start=2)

    assert page_text(target) == ["Page 1", "Page 1", "Page 2", "Page 4"]


def test_apply_trimbox_and_trim_margin_preserve_sources(tmp_path):
    source = tmp_path / "source.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=300)
    page.insert_text((72, 72), "Page 1")
    page.set_trimbox(pymupdf.Rect(10, 20, 190, 280))
    document.save(source)
    document.close()
    trimbox_target = tmp_path / "trimbox.pdf"
    margin_target = tmp_path / "margin.pdf"

    apply_trimbox_pdf(source, trimbox_target)
    trim_margin_pdf(source, margin_target, "10")

    original = pymupdf.open(source)
    trimbox = pymupdf.open(trimbox_target)
    trimmed = pymupdf.open(margin_target)
    try:
        expected_trimbox = original[0].trimbox
        assert trimbox[0].mediabox.width == pytest.approx(expected_trimbox.width)
        assert trimbox[0].mediabox.height == pytest.approx(expected_trimbox.height)
        assert trimmed[0].cropbox.width == pytest.approx(
            original[0].cropbox.width * 0.8
        )
        assert trimmed[0].cropbox.height == pytest.approx(
            original[0].cropbox.height * 0.8
        )
    finally:
        original.close()
        trimbox.close()
        trimmed.close()
    assert page_text(trimbox_target) == ["Page 1"]
    assert source.exists()


def test_trim_margin_rejects_margins_that_remove_the_page(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 1)

    with pytest.raises(ValueError, match="entire page"):
        trim_margin_pdf(source, tmp_path / "trimmed.pdf", "50")

    assert not (tmp_path / "trimmed.pdf").exists()


def test_split_and_spread_pages(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 2)
    split_target = tmp_path / "split.pdf"
    spread_target = tmp_path / "spread.pdf"

    split_pages_pdf(source, split_target)
    spread_pages_pdf(source, spread_target)

    split = pymupdf.open(split_target)
    spread = pymupdf.open(spread_target)
    try:
        assert split.page_count == 4
        assert split[0].rect.width == pytest.approx(split[1].rect.width)
        source_doc = pymupdf.open(source)
        try:
            assert split[0].rect.width == pytest.approx(source_doc[0].rect.width / 2)
            assert spread[0].rect.width == pytest.approx(source_doc[0].rect.width * 2)
        finally:
            source_doc.close()
        assert spread.page_count == 1
    finally:
        split.close()
        spread.close()


def test_unzip_pdf_writes_odd_and_even_pages(tmp_path):
    source = make_pdf(tmp_path / "source.pdf", 5)
    odd = tmp_path / "odd.pdf"
    even = tmp_path / "even.pdf"

    unzip_pdf(source, odd, even)

    assert page_text(odd) == ["Page 1", "Page 3", "Page 5"]
    assert page_text(even) == ["Page 2", "Page 4"]
