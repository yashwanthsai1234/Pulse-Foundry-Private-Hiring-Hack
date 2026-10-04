# FX1 ingest notes (wave 4)

- B3-01: `scoring.completeness` = extracted body rows / row-like text lines (>= 3 shift tokens without a suffix) of the page;
  cascade score = worst grid score x completeness. A zebra table read by pdf.lines as 2 rows scores 0.11 and falls through to
  pdf.words / pdf.text. Camelot reports quality instead of trusting the extractor: https://github.com/camelot-dev/camelot ;
  pdfplumber lines strategy uses rect edges: https://github.com/jsvine/pdfplumber#table-extraction-settings
- Stacked headers ("Mon" / "Staff Role" / "09/14") are joined into one row (`methods._stack_header`); blank spacer rows and a
  trailing footnote row are dropped; header-only or day-less grids are not tables.
- B3-05: `base._WRAPPED_HYPHEN` (hyphen + space between two letters, or "3p- 11p"). https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- B3-10: soft hyphen deleted, U+2010-2015 / U+2212 -> "-" (Unicode charts above).
- RC4: UTF-8 BOM only trusted when the rest is valid UTF-8 (https://www.unicode.org/faq/utf_bom.html#bom1), else cp1252; BOM bytes stripped.
- RC6/B-004: header = first all-text, mostly unique row with a number/date below it; all-text tables fall back to the first
  row of modal width (DuckDB sniffer idea: https://duckdb.org/2023/10/27/csv-sniffer.html).
- B2-04: rows with header+1 fields, all split at the same ", " -> rejoined (RFC 4180 requires quoting).
- B-005 (streaming CSV > 200 MB): WONTFIX. It needs a second code path (chunked Polars/Parquet) for a case the demo data never hits;
  the stdlib reader parses 200k rows in < 1 s (A1.md).
- Not fixed: libreoffice_docx_pandoc.pdf (B3-02): pdfplumber reads the ligature "fi" char as "fia" ("Sofiaa", "Thuu"); PyMuPDF words
  are clean. Needs the `words` method to use PyMuPDF words (not in FX1 scope).
