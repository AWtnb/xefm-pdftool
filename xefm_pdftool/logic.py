"""PDF operations that do not depend on XeFM."""

import math
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path

import pikepdf

_PAGE_RANGE = re.compile(r"(-?\d+)\s*(?:-\s*(-?\d*))?")


def pdf_name(text: str | None, default: str) -> str | None:
    """Return a safe PDF file name, or None if the input is not a file name."""
    name = (text or "").strip() or default
    if (
        name in (".", "..")
        or any(char in name for char in '<>:"/\\|?*')
        or any(ord(char) < 32 for char in name)
    ):
        return None
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def parse_page_ranges(
    text: str, page_count: int, allow_overlaps: bool = False
) -> list[tuple[int, int]]:
    """Parse 1-based inclusive ranges; negative pages count back from the end."""
    if not text or not text.strip():
        raise ValueError("Enter one or more page ranges, such as 1-3,5.")
    if page_count < 1:
        raise ValueError("The PDF has no pages.")
    ranges = []
    for part in text.split(","):
        token = part.strip()
        match = _PAGE_RANGE.fullmatch(token)
        if match is None:
            raise ValueError(f"Invalid page range: {token!r}")
        first = int(match.group(1))
        end_text = match.group(2)
        last = (
            first
            if end_text is None
            else (page_count if end_text == "" else int(end_text))
        )
        if first == 0 or last == 0:
            raise ValueError(f"Page numbers cannot be zero: {token!r}")
        first = first if not first <= 0 else page_count + first + 1
        last = last if last is None or not last <= 0 else page_count + last + 1
        last = page_count if last is None else last
        if first < 1 or page_count < first or last < first or page_count < last:
            raise ValueError(
                f"Page range is outside the {page_count}-page PDF: {token!r}"
            )
        if not allow_overlaps and any(
            first <= previous_last and previous_first <= last
            for previous_first, previous_last in ranges
        ):
            raise ValueError("Page ranges must not overlap.")
        ranges.append((first, last))
    return ranges


def pdf_page_count(source: Path) -> int:
    """Return a PDF's page count after applying the standard PDF validation."""
    document = _open_pdf(source)
    try:
        return len(document.pages)
    finally:
        document.close()


def range_suffix(page_range: tuple[int, int]) -> str:
    first, last = page_range
    return str(first) if first == last else f"{first}-{last}"


def _page_indices(ranges: Sequence[tuple[int, int]]) -> list[int]:
    indices = []
    for first, last in ranges:
        for page_number in range(first, last + 1):
            indices.append(page_number - 1)
    return indices


def _open_pdf(path: Path):
    try:
        document = pikepdf.Pdf.open(path)
    except pikepdf.PasswordError as exc:
        raise ValueError(f"PDF is password-protected: {path.name}") from exc
    if not len(document.pages):
        document.close()
        raise ValueError(f"PDF has no pages: {path.name}")
    return document


def _save_atomically(document: pikepdf.Pdf, target: Path) -> None:
    temporary = _temporary_pdf_path(target)
    try:
        document.save(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _temporary_pdf_path(target: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=".part.pdf", dir=target.parent
    )
    os.close(descriptor)
    return target.with_name(os.path.basename(name))


def _ensure_distinct_outputs(sources: Sequence[Path], targets: Sequence[Path]) -> None:
    output_paths = {target.resolve() for target in targets}
    for source in sources:
        if "://" not in str(source) and Path(str(source)).resolve() in output_paths:
            raise ValueError(f"Output would overwrite an input PDF: {source.name}")


def merge_pdfs(
    sources: Sequence[Path],
    target: Path,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    """Merge source PDFs, writing the completed result atomically."""
    if not sources:
        raise ValueError("Select at least one source PDF.")
    _ensure_distinct_outputs(sources, [target])
    result = pikepdf.Pdf.new()
    try:
        for index, source in enumerate(sources):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(sources), source.name)
            document = _open_pdf(source)
            try:
                result.pages.extend(document.pages)
            finally:
                document.close()
        if checkpoint:
            checkpoint()
        _save_atomically(result, target)
    finally:
        result.close()


def split_pdf(
    source: Path,
    ranges: Sequence[tuple[int, int]],
    targets: Sequence[Path],
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    """Write each 1-based inclusive page range to its own PDF."""
    if len(ranges) != len(targets):
        raise ValueError("Each page range must have one output file.")
    if not ranges:
        raise ValueError("Select at least one page range.")
    _ensure_distinct_outputs([source], targets)
    document = _open_pdf(source)
    temporary_files = []
    try:
        page_count = len(document.pages)
        for first, last in ranges:
            if first < 1 or last < first or page_count < last:
                raise ValueError(
                    f"Page range {range_suffix((first, last))} exceeds the "
                    f"{page_count}-page PDF."
                )
        for index, ((first, last), target) in enumerate(zip(ranges, targets)):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(ranges), target.name)
            part = pikepdf.Pdf.new()
            try:
                part.pages.extend(document.pages[first - 1 : last])
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
    source: Path,
    target: Path,
    degrees: int = 90,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    page_ranges: str | None = None,
) -> None:
    """Write a rotated copy of a PDF, leaving the source unchanged."""
    if not isinstance(degrees, int) or degrees % 90:
        raise ValueError("Rotation must be a multiple of 90 degrees.")
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    try:
        selected = None
        if page_ranges is not None:
            ranges = parse_page_ranges(
                page_ranges, len(document.pages), allow_overlaps=True
            )
            selected = set(_page_indices(ranges))
        for index, page in enumerate(document.pages):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(document.pages), source.name)
            if selected is None or index in selected:
                page.obj["/Rotate"] = (_page_rotation(page) + degrees) % 360
        if checkpoint:
            checkpoint()
        _save_atomically(document, target)
    finally:
        document.close()


def resolve_insertion_index(value: int, page_count: int) -> int:
    """Convert a 1-based (or negative-from-end) insertion page to an index."""
    if not isinstance(value, int) or value == 0:
        raise ValueError("Enter a non-zero insertion page.")
    index = value - 1 if not value <= 0 else page_count + value
    if index < 0 or page_count < index:
        raise ValueError(f"Insertion page must be between 1 and {page_count + 1}.")
    return index


def _page_rotation(page: pikepdf.Page) -> int:
    node = page.obj
    while node is not None:
        rotation = node.get("/Rotate")
        if rotation is not None:
            return int(rotation)
        node = node.get("/Parent")
    return 0


def _copy_page_indices(
    source: Path,
    target: Path,
    indices: Sequence[int],
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    document = _open_pdf(source)
    result = pikepdf.Pdf.new()
    try:
        for index, page_number in enumerate(indices):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(indices), f"page {page_number + 1}")
            result.pages.append(document.pages[page_number])
        if checkpoint:
            checkpoint()
        _save_atomically(result, target)
    finally:
        result.close()
        document.close()


def extract_pdf(
    source: Path,
    target: Path,
    ranges: str,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    """Write the selected pages, preserving the range order."""
    document = _open_pdf(source)
    try:
        parsed_ranges = parse_page_ranges(
            ranges, len(document.pages), allow_overlaps=True
        )
        indices = _page_indices(parsed_ranges)
    finally:
        document.close()
    _ensure_distinct_outputs([source], [target])
    _copy_page_indices(source, target, indices, checkpoint, progress)


def insert_pdf(
    base_source: Path,
    insert_source: Path,
    target: Path,
    start: int = 1,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    """Insert every page from one PDF before a page in another PDF."""
    _ensure_distinct_outputs([base_source, insert_source], [target])
    with ExitStack() as stack:
        base = _open_pdf(base_source)
        stack.callback(base.close)
        inserted = _open_pdf(insert_source)
        stack.callback(inserted.close)
        result = pikepdf.Pdf.new()
        stack.callback(result.close)
        base_page_count = len(base.pages)
        position = resolve_insertion_index(start, base_page_count)
        if checkpoint:
            checkpoint()
        if progress:
            progress(0, 3, base_source.name)
        if position:
            result.pages.extend(base.pages[:position])
        if progress:
            progress(1, 3, insert_source.name)
        result.pages.extend(inserted.pages)
        if position < base_page_count:
            result.pages.extend(base.pages[position:])
        if checkpoint:
            checkpoint()
        _save_atomically(result, target)


def swap_pdf(
    base_source: Path,
    replacement_source: Path,
    target: Path,
    start: int = 1,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    """Replace pages in the base PDF with every page from another PDF."""
    _ensure_distinct_outputs([base_source, replacement_source], [target])
    with ExitStack() as stack:
        base = _open_pdf(base_source)
        stack.callback(base.close)
        replacement = _open_pdf(replacement_source)
        stack.callback(replacement.close)
        result = pikepdf.Pdf.new()
        stack.callback(result.close)
        base_page_count = len(base.pages)
        position = resolve_insertion_index(start, base_page_count)
        if base_page_count == position:
            raise ValueError("The swap start page must refer to an existing page.")
        if checkpoint:
            checkpoint()
        if progress:
            progress(0, 3, base_source.name)
        if position:
            result.pages.extend(base.pages[:position])
        if progress:
            progress(1, 3, replacement_source.name)
        result.pages.extend(replacement.pages)
        tail_start = min(position + len(replacement.pages), base_page_count)
        if tail_start < base_page_count:
            result.pages.extend(base.pages[tail_start:])
        if checkpoint:
            checkpoint()
        _save_atomically(result, target)


def apply_trimbox_pdf(
    source: Path,
    target: Path,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str | int], None] | None = None,
) -> None:
    """Set each page's media box to its trim box."""
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    try:
        for index, page in enumerate(document.pages):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(document.pages), index + 1)
            page.mediabox = page.trimbox
            page.cropbox = page.trimbox
        if checkpoint:
            checkpoint()
        _save_atomically(document, target)
    finally:
        document.close()


def _parse_margins(text: str) -> list[float]:
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


def trim_margin_pdf(
    source: Path,
    target: Path,
    margins: str,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str | int], None] | None = None,
) -> None:
    """Crop percentage margins from each page (top,right,bottom,left)."""
    top, right, bottom, left = _parse_margins(margins)
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    try:
        for index, page in enumerate(document.pages):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(document.pages), index + 1)
            x0, y0, x1, y1 = [float(value) for value in page.mediabox]
            width = x1 - x0
            height = y1 - y0
            x_inset = width * left / 100
            x_outset = width * right / 100
            y_inset = height * top / 100
            y_outset = height * bottom / 100
            if width <= x_inset + x_outset or height <= y_inset + y_outset:
                raise ValueError("Margins would remove the entire page.")
            cropped_box = [
                x0 + x_inset,
                y0 + y_outset,
                x1 - x_outset,
                y1 - y_inset,
            ]
            page.mediabox = cropped_box
            page.cropbox = cropped_box
        if checkpoint:
            checkpoint()
        _save_atomically(document, target)
    finally:
        document.close()


def _page_box(page: pikepdf.Page) -> tuple[float, float, float, float]:
    media_box = [float(value) for value in page.mediabox]
    crop_box = [float(value) for value in page.cropbox]
    return (
        max(media_box[0], crop_box[0]),
        max(media_box[1], crop_box[1]),
        min(media_box[2], crop_box[2]),
        min(media_box[3], crop_box[3]),
    )


def _show_clipped_page(
    output: pikepdf.Pdf,
    source: pikepdf.Page,
    clip: tuple[float, float, float, float],
    width: float,
    height: float,
) -> None:
    form = source.as_form_xobject()
    form["/BBox"] = pikepdf.Array(clip)
    page = output.add_blank_page(page_size=(width, height))
    page.add_overlay(
        form,
        pikepdf.Rectangle(0, 0, width, height),
    )


def split_pages_pdf(
    source: Path,
    target: Path,
    vertical: bool = False,
    opposite: bool = False,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str | int], None] | None = None,
) -> None:
    """Split every page into two equal halves."""
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    output = pikepdf.Pdf.new()
    try:
        for index, page in enumerate(document.pages):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, len(document.pages), index + 1)
            box = _page_box(page)
            x0, y0, x1, y1 = box
            if vertical:
                middle = (y0 + y1) / 2
                clips = [
                    (x0, middle, x1, y1),
                    (x0, y0, x1, middle),
                ]
            else:
                middle = (x0 + x1) / 2
                clips = [
                    (x0, y0, middle, y1),
                    (middle, y0, x1, y1),
                ]
            if opposite:
                clips.reverse()
            for clip in clips:
                _show_clipped_page(
                    output,
                    page,
                    clip,
                    clip[2] - clip[0],
                    clip[3] - clip[1],
                )
        if checkpoint:
            checkpoint()
        _save_atomically(output, target)
    finally:
        output.close()
        document.close()


def spread_pages_pdf(
    source: Path,
    target: Path,
    vertical: bool = False,
    single_top: bool = False,
    opposite: bool = False,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str | int], None] | None = None,
) -> None:
    """Combine adjacent page pairs into landscape/portrait spreads."""
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    output = pikepdf.Pdf.new()
    try:
        page_numbers = list(range(len(document.pages)))
        if single_top and page_numbers:
            output.pages.append(document.pages[0])
            page_numbers = page_numbers[1:]
        for index in range(0, len(page_numbers), 2):
            if checkpoint:
                checkpoint()
            first = document.pages[page_numbers[index]]
            if len(page_numbers) == index + 1:
                output.pages.append(first)
                continue
            second = document.pages[page_numbers[index + 1]]
            pair = [first, second]
            if opposite:
                pair.reverse()
            first_box, second_box = _page_box(pair[0]), _page_box(pair[1])
            first_width = first_box[2] - first_box[0]
            first_height = first_box[3] - first_box[1]
            second_width = second_box[2] - second_box[0]
            second_height = second_box[3] - second_box[1]
            if vertical:
                width = max(first_width, second_width)
                height = first_height + second_height
                placements = [
                    (0, second_height, first_width, height),
                    (
                        0,
                        0,
                        second_width,
                        second_height,
                    ),
                ]
            else:
                width = first_width + second_width
                height = max(first_height, second_height)
                placements = [
                    (0, 0, first_width, first_height),
                    (
                        first_width,
                        0,
                        width,
                        second_height,
                    ),
                ]
            spread = output.add_blank_page(page_size=(width, height))
            for source_page, placement in zip(pair, placements):
                form = source_page.as_form_xobject()
                form["/BBox"] = pikepdf.Array(_page_box(source_page))
                spread.add_overlay(
                    form,
                    pikepdf.Rectangle(*placement),
                )
            if progress:
                progress(
                    index // 2,
                    (len(page_numbers) + 1) // 2,
                    page_numbers[index] + 1,
                )
        if checkpoint:
            checkpoint()
        _save_atomically(output, target)
    finally:
        output.close()
        document.close()


def unzip_pdf(
    source: Path,
    odd_target: Path,
    even_target: Path,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    """Write odd- and even-numbered pages to separate PDFs."""
    _ensure_distinct_outputs([source], [odd_target, even_target])
    document = _open_pdf(source)
    try:
        odd = [index for index in range(len(document.pages)) if index % 2 == 0]
        even = [index for index in range(len(document.pages)) if index % 2 == 1]
    finally:
        document.close()
    _copy_page_indices(source, odd_target, odd, checkpoint, progress)
    if even:
        _copy_page_indices(source, even_target, even, checkpoint, progress)
