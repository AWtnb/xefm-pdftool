# xefm-pdftool

XeFM extension for merging selected PDFs, extracting page ranges, and rotating
PDFs clockwise by 90 degrees. It uses PyMuPDF.

## Use

Install the extension from its folder with:

```powershell
xefm ext install .
```

In XeFM, select PDFs in one pane and keep a local destination folder open in
the other pane. The **File** menu, the file context menu, and the command
palette provide these actions:

- **Merge PDFs…** combines the selected PDFs in pane order.
- **Split PDF…** prompts for one or more page ranges (for example `1-3,5`)
  and writes one PDF for each range.
- **Rotate PDFs 90°…** writes a clockwise-rotated copy of each selected PDF.

The source PDFs are never changed. Existing output files are replaced only
after confirmation. Page numbers are 1-based. Password-protected PDFs are not
supported.

## Development

Use uv to sync dependencies, run the tests, and validate the XeFM extension:

```powershell
uv sync
uv run python -m pytest
xefm ext check .
```
