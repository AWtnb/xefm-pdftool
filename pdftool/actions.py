"""XeFM actions for merging, splitting, and rotating PDF files."""

from pathlib import Path

from pdftool.logic import (
    merge_pdfs,
    parse_page_ranges,
    pdf_name,
    range_suffix,
    rotate_pdf,
    split_pdf,
)

TITLE = "PDF Tools"


def _selected_pdfs(ctx):
    entries = ctx.pane.selected() or [ctx.pane.focused]
    return [
        entry
        for entry in entries
        if entry is not None
        and entry.name != ".."
        and not entry.is_dir
        and entry.suffix.lower() == ".pdf"
    ]


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
            pane = getattr(done_ctx, destination_pane)
            pane.cd(pane.path, focus_name=targets[-1].name)
            done_ctx.message(f"{title}: created {len(targets)} PDF file(s)")
        elif outcome.status == "cancelled":
            done_ctx.message(f"{title}: cancelled")
        else:
            done_ctx.message(f"{title}: failed — {outcome.error}")

    ctx.run_task(title, work, on_done=done)


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


def split(ctx):
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
    """Rotate selected PDFs clockwise by 90 degrees into new files."""
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

    def work(job):
        for index, (entry, target) in enumerate(zip(entries, targets)):
            job.checkpoint()
            job.progress(index, len(entries), detail=entry.name)
            rotate_pdf(
                entry.path,
                target,
                90,
                checkpoint=job.checkpoint,
                progress=lambda done, total, detail: job.progress(
                    index, len(entries), detail=f"{detail} — page {done + 1}/{total}"
                ),
            )

    _start(ctx, f"{TITLE}: rotate", targets, work)
