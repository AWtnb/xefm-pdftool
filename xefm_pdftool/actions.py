"""XeFM actions for editing and transforming PDF files."""

from pathlib import Path

from xefm_pdftool.logic import (
    apply_trimbox_pdf,
    extract_pdf,
    insert_pdf,
    merge_pdfs,
    parse_page_ranges,
    pdf_name,
    range_suffix,
    rotate_pdf,
    split_pages_pdf,
    split_pdf,
    spread_pages_pdf,
    swap_pdf,
    trim_margin_pdf,
    unzip_pdf,
)

TITLE = "PDF Tools"


def _selected_pdfs(ctx):
    return _pdfs_from_pane(ctx.pane)


def _pdfs_from_pane(pane):
    entries = pane.selected() or [pane.focused]
    return [
        entry
        for entry in entries
        if entry is not None
        and entry.name != ".."
        and not entry.is_dir
        and entry.suffix.lower() == ".pdf"
    ]


def _one_pdf(ctx, pane, pane_title):
    entries = _pdfs_from_pane(pane)
    if len(entries) != 1:
        ctx.message(f"{TITLE}: select exactly one PDF in the {pane_title} pane")
        return None
    return entries[0]


def _destination(ctx):
    path = ctx.other.path
    if "://" in str(path):
        ctx.message(f"{TITLE}: the other pane must show a local folder")
        return None
    destination = Path(str(path))
    if not destination.is_dir():
        ctx.message(f"{TITLE}: the other pane must show an existing folder")
        return None
    return destination


def _start(ctx, title, targets, work):
    existing = [target.name for target in targets if target.exists()]
    if existing:
        names = ", ".join(existing)
        ctx.confirm(
            f"Replace {names}?",
            title=title,
            on_result=lambda yes: yes and _run(ctx, title, targets, work),
        )
    else:
        _run(ctx, title, targets, work)


def _run(ctx, title, targets, work):
    destination_pane = ctx.other.name

    def done(done_ctx, outcome):
        if outcome.ok:
            created = [target for target in targets if target.exists()]
            if not created:
                done_ctx.message(f"{title}: failed — no PDF files were created")
                return
            pane = getattr(done_ctx, destination_pane)
            pane.cd(pane.path, focus_name=created[-1].name)
            done_ctx.message(f"{title}: created {len(created)} PDF file(s)")
        elif outcome.status == "cancelled":
            done_ctx.message(f"{title}: cancelled")
        else:
            done_ctx.message(f"{title}: failed — {outcome.error}")

    ctx.run_task(title, work, on_done=done)


def _progress(job, index, total, detail):
    job.progress(index, total, detail=detail)


def _single_source_target(ctx, action_title, suffix):
    entries = _selected_pdfs(ctx)
    if len(entries) != 1:
        ctx.message(f"{TITLE}: select exactly one PDF to {action_title.lower()}")
        return None
    destination = _destination(ctx)
    if destination is None:
        return None
    entry = entries[0]
    return entry, destination / f"{Path(entry.name).stem}{suffix}.pdf"


def merge(ctx):
    """Merge selected PDF files into one PDF in the other pane."""
    entries = _selected_pdfs(ctx)
    if len(entries) < 2:
        ctx.message(f"{TITLE}: select at least two PDF files to merge")
        return
    destination = _destination(ctx)
    if destination is None:
        return
    default = f"{Path(entries[0].name).stem}-merged.pdf"
    sources = [entry.path for entry in entries]

    def accepted(text):
        name = pdf_name(text, default)
        if name is None:
            ctx.message(f"{TITLE}: enter a valid file name")
            return
        target = destination / name

        def work(job):
            merge_pdfs(
                sources,
                target,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail: job.progress(
                    done, total, detail=detail
                ),
            )

        _start(ctx, f"{TITLE}: merge", [target], work)

    ctx.input("Output PDF name", default, title=f"{TITLE}: merge", on_accept=accepted)


def conc(ctx):
    """Concatenate selected PDFs into one PDF in the other pane."""
    merge(ctx)


def split_ranges(ctx):
    """Extract the requested page ranges into separate PDFs."""
    entries = _selected_pdfs(ctx)
    if len(entries) != 1:
        ctx.message(f"{TITLE}: select exactly one PDF to split")
        return
    destination = _destination(ctx)
    if destination is None:
        return
    entry = entries[0]
    stem = Path(entry.name).stem

    def accepted(text):
        try:
            ranges = parse_page_ranges(text)
        except ValueError as exc:
            ctx.message(f"{TITLE}: {exc}")
            return
        targets = [
            destination / f"{stem}-pages-{range_suffix(page_range)}.pdf"
            for page_range in ranges
        ]

        def work(job):
            split_pdf(
                entry.path,
                ranges,
                targets,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail: job.progress(
                    done, total, detail=detail
                ),
            )

        _start(ctx, f"{TITLE}: split", targets, work)

    ctx.input(
        "Page ranges (for example 1-3,5)",
        "",
        title=f"{TITLE}: split",
        on_accept=accepted,
    )


def rotate(ctx):
    """Rotate selected PDF pages by a multiple of 90 degrees."""
    entries = _selected_pdfs(ctx)
    if not entries:
        ctx.message(f"{TITLE}: select one or more PDF files to rotate")
        return
    destination = _destination(ctx)
    if destination is None:
        return
    targets = [
        destination / f"{Path(entry.name).stem}-rotated.pdf" for entry in entries
    ]

    def request_ranges(degrees):
        try:
            angle = int(degrees.strip())
            if angle % 90:
                raise ValueError
        except ValueError:
            ctx.message(f"{TITLE}: rotation must be a multiple of 90 degrees")
            return

        def accepted(ranges):
            def work(job):
                for index, (entry, target) in enumerate(zip(entries, targets)):
                    job.checkpoint()
                    rotate_pdf(
                        entry.path,
                        target,
                        angle,
                        checkpoint=job.checkpoint,
                        progress=lambda done, total, detail, index=index, entry=entry: job.progress(
                            index,
                            len(entries),
                            detail=f"{entry.name} — page {done + 1}/{total}",
                        ),
                        page_ranges=ranges,
                    )

            _start(ctx, f"{TITLE}: rotate", targets, work)

        ctx.input(
            "Page ranges (for example 1-3,5,-1)",
            "1-",
            title=f"{TITLE}: rotate",
            on_accept=accepted,
        )

    ctx.input(
        "Rotation degrees (a multiple of 90)",
        "90",
        title=f"{TITLE}: rotate",
        on_accept=request_ranges,
    )


def apply_trimbox(ctx):
    """Apply each page's trim box to the selected PDFs."""
    entries = _selected_pdfs(ctx)
    if not entries:
        ctx.message(f"{TITLE}: select one or more PDF files")
        return
    destination = _destination(ctx)
    if destination is None:
        return
    targets = [
        destination / f"{Path(entry.name).stem}-trimbox.pdf" for entry in entries
    ]

    def work(job):
        for index, (entry, target) in enumerate(zip(entries, targets)):
            job.checkpoint()
            apply_trimbox_pdf(
                entry.path,
                target,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail, index=index, entry=entry: job.progress(
                    index,
                    len(entries),
                    detail=f"{entry.name} — page {done + 1}/{total}",
                ),
            )

    _start(ctx, f"{TITLE}: apply trim box", targets, work)


def extract(ctx):
    """Extract selected page ranges from one PDF."""
    selected = _single_source_target(ctx, "extract pages from", "-extracted")
    if selected is None:
        return
    entry, target = selected

    def accepted(ranges):
        def work(job):
            extract_pdf(
                entry.path,
                target,
                ranges,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail: _progress(
                    job, done, total, detail
                ),
            )

        _start(ctx, f"{TITLE}: extract", [target], work)

    ctx.input(
        "Page ranges (for example 1-3,5,7-,-1)",
        "1-",
        title=f"{TITLE}: extract",
        on_accept=accepted,
    )


def _paired_sources(ctx, action_title):
    base = _one_pdf(ctx, ctx.pane, "active")
    if base is None:
        return None
    other = _one_pdf(ctx, ctx.other, "other")
    if other is None:
        return None
    destination = _destination(ctx)
    if destination is None:
        return None
    target = destination / f"{Path(base.name).stem}-{action_title}.pdf"
    return base, other, target


def _insert_or_swap(ctx, operation, label):
    selected = _paired_sources(ctx, label)
    if selected is None:
        return
    base, other, target = selected

    def accepted(start_text):
        try:
            start = int(start_text.strip())
            if start == 0:
                raise ValueError
        except ValueError:
            ctx.message(f"{TITLE}: enter a non-zero page number")
            return

        def work(job):
            operation(
                base.path,
                other.path,
                target,
                start=start,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail: _progress(
                    job, done, total, detail
                ),
            )

        _start(ctx, f"{TITLE}: {label}", [target], work)

    ctx.input(
        "Start page (1-based; negative numbers count from the end)",
        "1",
        title=f"{TITLE}: {label}",
        on_accept=accepted,
    )


def insert(ctx):
    """Insert the other pane's selected PDF into the active pane's PDF."""
    _insert_or_swap(ctx, insert_pdf, "insert")


def swap(ctx):
    """Replace pages in the active pane's PDF with the other pane's PDF."""
    _insert_or_swap(ctx, swap_pdf, "swap")


def _read_flags(ctx, title, allowed, on_accept):
    def accepted(text):
        flags = {part.strip().lower() for part in text.split(",") if part.strip()}
        invalid = flags - allowed
        if invalid:
            ctx.message(f"{TITLE}: unsupported option: {', '.join(sorted(invalid))}")
            return
        on_accept(flags)

    ctx.input(
        "Options (comma-separated): " + ", ".join(sorted(allowed)),
        "",
        title=f"{TITLE}: {title}",
        on_accept=accepted,
    )


def split_pages(ctx):
    """Split every page into two half-pages."""
    selected = _single_source_target(ctx, "split", "-split")
    if selected is None:
        return
    entry, target = selected

    def run(flags):
        def work(job):
            split_pages_pdf(
                entry.path,
                target,
                vertical="v" in flags,
                opposite="o" in flags,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail: _progress(
                    job, done, total, detail
                ),
            )

        _start(ctx, f"{TITLE}: half split", [target], work)

    _read_flags(ctx, "half split", {"v", "o"}, run)


def split(ctx):
    """Split each selected PDF page into two half-pages."""
    split_pages(ctx)


def spread(ctx):
    """Combine adjacent pages into spreads."""
    selected = _single_source_target(ctx, "spread pages from", "-spread")
    if selected is None:
        return
    entry, target = selected

    def run(flags):
        def work(job):
            spread_pages_pdf(
                entry.path,
                target,
                vertical="v" in flags,
                single_top="s" in flags,
                opposite="o" in flags,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail: _progress(
                    job, done, total, detail
                ),
            )

        _start(ctx, f"{TITLE}: spread", [target], work)

    _read_flags(ctx, "spread", {"v", "o", "s"}, run)


def trim_margin(ctx):
    """Crop percentage margins from one PDF."""
    selected = _single_source_target(ctx, "trim margins from", "-trimmargin")
    if selected is None:
        return
    entry, target = selected

    def accepted(margins):
        def work(job):
            trim_margin_pdf(
                entry.path,
                target,
                margins,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail: _progress(
                    job, done, total, detail
                ),
            )

        _start(ctx, f"{TITLE}: trim margin", [target], work)

    ctx.input(
        "Margins in percent: top,right,bottom,left (for example 5 or 5,2)",
        "0",
        title=f"{TITLE}: trim margin",
        on_accept=accepted,
    )


def unzip(ctx):
    """Write odd- and even-numbered pages to separate PDFs."""
    entry = _one_pdf(ctx, ctx.pane, "active")
    if entry is None:
        return
    destination = _destination(ctx)
    if destination is None:
        return
    stem = Path(entry.name).stem
    targets = [destination / f"{stem}-odd.pdf", destination / f"{stem}-even.pdf"]

    def work(job):
        unzip_pdf(
            entry.path,
            targets[0],
            targets[1],
            checkpoint=job.checkpoint,
            progress=lambda done, total, detail: _progress(job, done, total, detail),
        )

    _start(ctx, f"{TITLE}: unzip", targets, work)
