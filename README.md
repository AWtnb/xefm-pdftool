# xefm-pdftool

[XeFM](https://github.com/crftwr/xefm) extension for editing and transforming PDF files with [PyMuPDF](https://pymupdf.readthedocs.io/).

## Use

Install the extension from its folder with:

```
xefm ext install github:AWtnb/xefm-pdftool
```

## Updating

After a newer release is published, update the extension with:

```cmd
xefm ext upgrade xefm-pdftool
```

In XeFM, choose **Tools > Advanced > Check for Extension Updates…** instead.

Actions are available from the **File** menu, the file context menu, and the
command palette. When an action needs parameters, it asks for them with XeFM's
input prompt. PDF outputs are written to the other pane's local folder, and
existing files are replaced only after confirmation.

- **Merge PDFs… / Concatenate PDFs…** combines selected PDFs in pane order and
  asks for an output name.
- **Extract PDF pages…** writes selected pages from one PDF to a new file.
- **Split PDF pages in half…** lets you choose left/right or top/bottom halves
  and which half comes first.
- **Split PDF by page ranges…** writes each requested range to a separate file.
- **Rotate PDF pages…** asks for a rotation angle (a multiple of 90) and page
  ranges.
- **Insert PDF from other pane…** inserts the other pane's selected PDF into
  the active pane's selected PDF at the requested page.
- **Swap PDF pages from other pane…** replaces pages in the active pane's PDF
  with the other pane's selected PDF, starting at the requested page.
- **Spread PDF pages…** lets you choose side-by-side or stacked spreads, page
  order, and whether to leave the first page by itself.
- **Apply PDF trim boxes…** makes each page's trim box its visible crop.
- **Trim PDF margins…** crops percentages from every page. Enter one value for
  all sides, two for top/bottom and right/left, or four as
  `top,right,bottom,left`.
- **Separate odd/even PDF pages…** writes odd- and even-numbered pages to
  separate files.

Page ranges use human-facing page numbers and are comma-separated. Positive
numbers are 1-based (`1` is the first page); negative numbers count back from
the end (`-1` is the last page, `-3--1` is the last three pages). Ranges may be
closed (`1-3`) or open-ended (`7-`). The source PDFs are never changed.
Password-protected PDFs are not supported.

## Development

Use uv to sync dependencies, run the tests, and validate the XeFM extension:

```cmd
uv sync
uv run python -m pytest
xefm ext check .
```

To publish a release, commit all changes first, then run:

```cmd
uv run scripts/release.py
```

The script increments the patch version in both TOML files, syncs `uv.lock`,
creates a release commit and annotated `vX.Y.Z` tag, then atomically pushes the
current branch and tag to `origin`. The working tree must be clean. Use
`--part minor` or `--part major` for a different version component, or
`--dry-run` to preview.

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

### Dependencies

- [PyMuPDF](https://github.com) (Licensed under AGPLv3)
