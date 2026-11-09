"""PDF operations that do not depend on XeFM."""

import math
import os
import re
import tempfile
from contextlib import ExitStack
from pathlib import Path

import pymupdf

_PAGE_RANGE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")
_PAGE_TOKEN = re.compile(r"(-?\d+)\s*(?:-\s*(-?\d*))?")


def pdf_name(text, default):
    """Return a safe PDF file name, or None if the input is not a file name."""
    name = (text or "").strip() or default
    if (
        name in (".", "..")
        or any(char in name for char in '<>:"/\\|?*')
        or any(ord(char) < 32 for char in name)
    ):
        return None
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def parse_page_ranges(text):
    """Parse 1-based inclusive ranges such as ``1-3, 5, 8-10``."""
    if not text or not text.strip():
        raise ValueError("Enter one or more page ranges, such as 1-3,5.")
    ranges = []
    for part in text.split(","):
        match = _PAGE_RANGE.fullmatch(part.strip())
        if match is None:
            raise ValueError(f"Invalid page range: {part.strip()!r}")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first < 1 or last < first:
            raise ValueError(f"Invalid page range: {part.strip()!r}")
        if any(
            first <= previous_last and previous_first <= last
            for previous_first, previous_last in ranges
        ):
            raise ValueError("Page ranges must not overlap.")
        ranges.append((first, last))
    return ranges


def range_suffix(page_range):
    first, last = page_range
    return str(first) if first == last else f"{first}-{last}"


def _open_pdf(path):
    with path.open("rb") as stream:
        document = pymupdf.open(stream=stream.read(), filetype="pdf")
    if document.needs_pass:
        document.close()
        raise ValueError(f"PDF is password-protected: {path.name}")
    if not document.page_count:
        document.close()
        raise ValueError(f"PDF has no pages: {path.name}")
    return document


def _save_atomically(document, target):
    temporary = _temporary_pdf_path(target)
    try:
        document.save(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _temporary_pdf_path(target):
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=".part.pdf", dir=target.parent
    )
    os.close(descriptor)
    return target.with_name(os.path.basename(name))


def _ensure_distinct_outputs(sources, targets):
    output_paths = {target.resolve() for target in targets}
    for source in sources:
        if "://" not in str(source) and Path(str(source)).resolve() in output_paths:
            raise ValueError(f"Output would overwrite an input PDF: {source.name}")


def merge_pdfs(sources, target, checkpoint=None, progress=None):
    """Merge source PDFs, writing the completed result atomically."""
    if not sources:
        raise ValueError("Select at least one source PDF.")
    _ensure_distinct_outputs(sources, [target])
    result = pymupdf.open()
    try:
        for index, source in enumerate(sources):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(sources), source.name)
            document = _open_pdf(source)
            try:
                result.insert_pdf(document)
            finally:
                document.close()
        if checkpoint:
            checkpoint()
        _save_atomically(result, target)
    finally:
        result.close()


def split_pdf(source, ranges, targets, checkpoint=None, progress=None):
    """Write each 1-based inclusive page range to its own PDF."""
    if len(ranges) != len(targets):
        raise ValueError("Each page range must have one output file.")
    if not ranges:
        raise ValueError("Select at least one page range.")
    _ensure_distinct_outputs([source], targets)
    document = _open_pdf(source)
    temporary_files = []
    try:
        for first, last in ranges:
            if first < 1 or last < first or last > document.page_count:
                raise ValueError(
                    f"Page range {range_suffix((first, last))} exceeds the "
                    f"{document.page_count}-page PDF."
                )
        for index, ((first, last), target) in enumerate(zip(ranges, targets)):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(ranges), target.name)
            part = pymupdf.open()
            try:
                part.insert_pdf(document, from_page=first - 1, to_page=last - 1)
                temporary = _temporary_pdf_path(target)
                temporary_files.append((temporary, target))
                part.save(temporary)
            finally:
                part.close()
        if checkpoint:
            checkpoint()
        for temporary, target in temporary_files:
            os.replace(temporary, target)
    finally:
        document.close()
        for temporary, _ in temporary_files:
            if temporary.exists():
                temporary.unlink()


def rotate_pdf(
    source,
    target,
    degrees=90,
    checkpoint=None,
    progress=None,
    page_indices=None,
):
    """Write a rotated copy of a PDF, leaving the source unchanged."""
    if not isinstance(degrees, int) or degrees % 90:
        raise ValueError("Rotation must be a multiple of 90 degrees.")
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    try:
        selected = set(page_indices) if page_indices is not None else None
        for index, page in enumerate(document):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, document.page_count, source.name)
            if selected is None or index in selected:
                page.set_rotation((page.rotation + degrees) % 360)
        if checkpoint:
            checkpoint()
        _save_atomically(document, target)
    finally:
        document.close()


def parse_page_selection(text, page_count):
    """Parse pdfjig-style ranges into zero-based page indices."""
    if not text or not text.strip():
        raise ValueError("Enter one or more page ranges.")
    if page_count < 1:
        raise ValueError("The PDF has no pages.")

    indices = []
    for token in text.split(","):
        token = token.strip()
        match = _PAGE_TOKEN.fullmatch(token)
        if match is None:
            raise ValueError(f"Invalid page range: {token!r}")

        first = int(match.group(1))
        end_text = match.group(2)
        last = first if end_text is None else (
            page_count if end_text == "" else int(end_text)
        )
        if first == 0 or last == 0:
            raise ValueError(f"Page numbers cannot be zero: {token!r}")

        first = first - 1 if first > 0 else page_count + first
        last = last - 1 if last > 0 else page_count + last
        if first < 0 or first >= page_count or last < first or last >= page_count:
            raise ValueError(
                f"Page range is outside the {page_count}-page PDF: {token!r}"
            )
        indices.extend(range(first, last + 1))
    return indices


def resolve_insertion_index(value, page_count):
    """Convert a 1-based (or negative-from-end) insertion page to an index."""
    if not isinstance(value, int) or value == 0:
        raise ValueError("Enter a non-zero insertion page.")
    index = value - 1 if value > 0 else page_count + value
    if index < 0 or index > page_count:
        raise ValueError(f"Insertion page must be between 1 and {page_count + 1}.")
    return index


def _copy_page_indices(source, target, indices, checkpoint=None, progress=None):
    document = _open_pdf(source)
    result = pymupdf.open()
    try:
        for index, page_number in enumerate(indices):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(indices), f"page {page_number + 1}")
            result.insert_pdf(document, from_page=page_number, to_page=page_number)
        if checkpoint:
            checkpoint()
        _save_atomically(result, target)
    finally:
        result.close()
        document.close()


def extract_pdf(source, target, ranges, checkpoint=None, progress=None):
    """Write the selected pages, preserving the range order."""
    document = _open_pdf(source)
    try:
        indices = parse_page_selection(ranges, document.page_count)
    finally:
        document.close()
    _ensure_distinct_outputs([source], [target])
    _copy_page_indices(source, target, indices, checkpoint, progress)


def insert_pdf(
    base_source, insert_source, target, start=1, checkpoint=None, progress=None
):
    """Insert every page from one PDF before a page in another PDF."""
    _ensure_distinct_outputs([base_source, insert_source], [target])
    with ExitStack() as stack:
        base = _open_pdf(base_source)
        stack.callback(base.close)
        inserted = _open_pdf(insert_source)
        stack.callback(inserted.close)
        result = pymupdf.open()
        stack.callback(result.close)
        position = resolve_insertion_index(start, base.page_count)
        if checkpoint:
            checkpoint()
        if progress:
            progress(0, 3, base_source.name)
        if position:
            result.insert_pdf(base, from_page=0, to_page=position - 1)
        if progress:
            progress(1, 3, insert_source.name)
        result.insert_pdf(inserted)
        if position < base.page_count:
            result.insert_pdf(base, from_page=position, to_page=base.page_count - 1)
        if checkpoint:
            checkpoint()
        _save_atomically(result, target)


def swap_pdf(
    base_source, replacement_source, target, start=1, checkpoint=None, progress=None
):
    """Replace pages in the base PDF with every page from another PDF."""
    _ensure_distinct_outputs([base_source, replacement_source], [target])
    with ExitStack() as stack:
        base = _open_pdf(base_source)
        stack.callback(base.close)
        replacement = _open_pdf(replacement_source)
        stack.callback(replacement.close)
        result = pymupdf.open()
        stack.callback(result.close)
        position = resolve_insertion_index(start, base.page_count)
        if position == base.page_count:
            raise ValueError("The swap start page must refer to an existing page.")
        if checkpoint:
            checkpoint()
        if progress:
            progress(0, 3, base_source.name)
        if position:
            result.insert_pdf(base, from_page=0, to_page=position - 1)
        if progress:
            progress(1, 3, replacement_source.name)
        result.insert_pdf(replacement)
        tail_start = min(position + replacement.page_count, base.page_count)
        if tail_start < base.page_count:
            result.insert_pdf(base, from_page=tail_start, to_page=base.page_count - 1)
        if checkpoint:
            checkpoint()
        _save_atomically(result, target)


def apply_trimbox_pdf(source, target, checkpoint=None, progress=None):
    """Set each page's media box to its trim box."""
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    try:
        for index, page in enumerate(document):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, document.page_count, page.number + 1)
            page.set_mediabox(page.trimbox)
        if checkpoint:
            checkpoint()
        _save_atomically(document, target)
    finally:
        document.close()


def _parse_margins(text):
    try:
        values = [float(part.strip()) for part in text.split(",")]
    except ValueError as exc:
        raise ValueError("Margins must be percentages: top,right,bottom,left.") from exc
    if len(values) not in (1, 2, 4) or any(
        not math.isfinite(value) or value < 0 for value in values
    ):
        raise ValueError("Enter one, two, or four non-negative margin percentages.")
    if len(values) == 1:
        return values * 4
    if len(values) == 2:
        return [values[0], values[1], values[0], values[1]]
    return values


def trim_margin_pdf(source, target, margins, checkpoint=None, progress=None):
    """Crop percentage margins from each page (top,right,bottom,left)."""
    top, right, bottom, left = _parse_margins(margins)
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    try:
        for index, page in enumerate(document):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, document.page_count, page.number + 1)
            box = page.mediabox
            x_inset = box.width * left / 100
            x_outset = box.width * right / 100
            y_inset = box.height * top / 100
            y_outset = box.height * bottom / 100
            if x_inset + x_outset >= box.width or y_inset + y_outset >= box.height:
                raise ValueError("Margins would remove the entire page.")
            page.set_mediabox(
                pymupdf.Rect(
                    box.x0 + x_inset,
                    box.y0 + y_inset,
                    box.x1 - x_outset,
                    box.y1 - y_outset,
                )
            )
        if checkpoint:
            checkpoint()
        _save_atomically(document, target)
    finally:
        document.close()


def _show_clipped_page(output, source, page_number, clip):
    page = output.new_page(width=clip.width, height=clip.height)
    page.show_pdf_page(page.rect, source, page_number, clip=clip)


def split_pages_pdf(
    source, target, vertical=False, opposite=False, checkpoint=None, progress=None
):
    """Split every page into two equal halves."""
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    output = pymupdf.open()
    try:
        for index, page in enumerate(document):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, document.page_count, page.number + 1)
            box = page.rect
            if vertical:
                middle = (box.y0 + box.y1) / 2
                clips = [
                    pymupdf.Rect(box.x0, box.y0, box.x1, middle),
                    pymupdf.Rect(box.x0, middle, box.x1, box.y1),
                ]
            else:
                middle = (box.x0 + box.x1) / 2
                clips = [
                    pymupdf.Rect(box.x0, box.y0, middle, box.y1),
                    pymupdf.Rect(middle, box.y0, box.x1, box.y1),
                ]
            if opposite:
                clips.reverse()
            for clip in clips:
                _show_clipped_page(output, document, page.number, clip)
        if checkpoint:
            checkpoint()
        _save_atomically(output, target)
    finally:
        output.close()
        document.close()


def spread_pages_pdf(
    source,
    target,
    vertical=False,
    single_top=False,
    opposite=False,
    checkpoint=None,
    progress=None,
):
    """Combine adjacent page pairs into landscape/portrait spreads."""
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    output = pymupdf.open()
    try:
        page_numbers = list(range(document.page_count))
        if single_top and page_numbers:
            output.insert_pdf(document, from_page=0, to_page=0)
            page_numbers = page_numbers[1:]
        for index in range(0, len(page_numbers), 2):
            if checkpoint:
                checkpoint()
            first = document[page_numbers[index]]
            if index + 1 == len(page_numbers):
                output.insert_pdf(
                    document, from_page=first.number, to_page=first.number
                )
                continue
            second = document[page_numbers[index + 1]]
            pair = [first, second]
            if opposite:
                pair.reverse()
            first_box, second_box = pair[0].rect, pair[1].rect
            if vertical:
                width = max(first_box.width, second_box.width)
                height = first_box.height + second_box.height
                placements = [
                    pymupdf.Rect(0, 0, first_box.width, first_box.height),
                    pymupdf.Rect(
                        0,
                        first_box.height,
                        second_box.width,
                        first_box.height + second_box.height,
                    ),
                ]
            else:
                width = first_box.width + second_box.width
                height = max(first_box.height, second_box.height)
                placements = [
                    pymupdf.Rect(0, 0, first_box.width, first_box.height),
                    pymupdf.Rect(
                        first_box.width,
                        0,
                        first_box.width + second_box.width,
                        second_box.height,
                    ),
                ]
            spread = output.new_page(width=width, height=height)
            for page, placement in zip(pair, placements):
                spread.show_pdf_page(
                    placement, document, page.number, clip=page.rect
                )
            if progress:
                progress(index // 2, (len(page_numbers) + 1) // 2, first.number + 1)
        if checkpoint:
            checkpoint()
        _save_atomically(output, target)
    finally:
        output.close()
        document.close()


def unzip_pdf(source, odd_target, even_target, checkpoint=None, progress=None):
    """Write odd- and even-numbered pages to separate PDFs."""
    _ensure_distinct_outputs([source], [odd_target, even_target])
    document = _open_pdf(source)
    try:
        odd = [index for index in range(document.page_count) if index % 2 == 0]
        even = [index for index in range(document.page_count) if index % 2 == 1]
    finally:
        document.close()
    _copy_page_indices(source, odd_target, odd, checkpoint, progress)
    if even:
        _copy_page_indices(source, even_target, even, checkpoint, progress)
