"""PDF operations that do not depend on XeFM."""

import os
import re
import tempfile
from pathlib import Path

import pymupdf

_PAGE_RANGE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")


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


def rotate_pdf(source, target, degrees=90, checkpoint=None, progress=None):
    """Write a rotated copy of a PDF, leaving the source unchanged."""
    if degrees not in (90, 180, 270):
        raise ValueError("Rotation must be 90, 180, or 270 degrees.")
    _ensure_distinct_outputs([source], [target])
    document = _open_pdf(source)
    try:
        for index, page in enumerate(document):
            if checkpoint:
                checkpoint()
            if progress:
                progress(index, document.page_count, source.name)
            page.set_rotation((page.rotation + degrees) % 360)
        if checkpoint:
            checkpoint()
        _save_atomically(document, target)
    finally:
        document.close()
