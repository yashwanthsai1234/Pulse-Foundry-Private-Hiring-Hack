# PDF extraction spike (A2)

Question: does the unseen schedule PDF yield a clean table automatically? Method: render 9 layout variants
(`backend/tools/synth/render.py`) from three specs, run each cascade method on its own, and compare every cell with the
spec (flattened rows over all pages; extra or missing rows count as wrong).

Specs: `e1` = example_e1 (2 pages, 1 row each), `mid` = 4 facilities x 6 rows (long names, 8 pt), `big` = 2 facilities x 25 rows
(1 page each, 8 pt). `wrapped_*` and `two_tables_one_page` have no `big` run (25 rows do not fit one page there).
`raster_150dpi` is image-only: it has no text layer, so it goes to the scan parser (see below).

## Cell accuracy / extraction score per method

| variant | spec | pdf.lines | pdf.mupdf | pdf.words | pdf.text |
|---|---|---|---|---|---|
| grid | e1 | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 0.0% / 0.00 |
| grid | mid | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 2.8% / 0.00 |
| grid | big | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 4.8% / 0.00 |
| merged_header | e1 | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 0.0% / 0.00 |
| merged_header | mid | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 8.5% / 0.00 |
| merged_header | big | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 4.8% / 0.00 |
| no_footnote | e1 | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 0.0% / 0.00 |
| no_footnote | mid | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 7.4% / 0.00 |
| no_footnote | big | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 4.9% / 0.00 |
| nogrid | e1 | 0.0% / 0.00 (no table) | 0.0% / 0.00 (no table) | 100.0% / 1.00 | 0.0% / 0.00 |
| nogrid | mid | 0.0% / 0.00 (no table) | 0.0% / 0.00 (no table) | 100.0% / 1.00 | 2.8% / 0.00 |
| nogrid | big | 0.0% / 0.00 (no table) | 0.0% / 0.00 (no table) | 100.0% / 1.00 | 4.8% / 0.00 |
| portrait | e1 | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 0.0% / 0.00 |
| portrait | mid | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 4.0% / 0.00 |
| portrait | big | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 4.8% / 0.00 |
| two_tables_one_page | e1 | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 0.0% / 0.24 |
| two_tables_one_page | mid | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 0.3% / 0.00 |
| wrapped_names | e1 | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 0.0% / 0.00 |
| wrapped_names | mid | 100.0% / 1.00 | 100.0% / 1.00 | 100.0% / 1.00 | 4.0% / 0.00 |
| wrapped_nogrid | e1 | 0.0% / 0.00 (no table) | 0.0% / 0.00 (no table) | 100.0% / 1.00 | 0.0% / 0.00 |
| wrapped_nogrid | mid | 0.0% / 0.00 (no table) | 0.0% / 0.00 (no table) | 100.0% / 1.00 | 4.0% / 0.00 |
| **mean accuracy** | all | 76.2% | 76.2% | **100.0%** | 2.7% |
| mean time per document | all | 34 ms | 37 ms | 25 ms | 46 ms |

`score` is the one the cascade uses (`header_score x cell_validity x shape`, min over the page's tables).

## Findings and decisions

1. **The score separates right from wrong cleanly.** Every correct extraction scored 1.00; every failure scored 0.00 (0.24 once).
   Any threshold between 0.3 and 0.99 gives the same decisions on these variants, so the default `pdf.method_min_score = 0.80` stays.
   Sensitivity (25-row pages, unknown tokens "ORIENT" injected into day cells): 0% -> 1.00, 2% -> 0.97, 5% -> 0.91-0.94,
   20% -> 0.79-0.80, 40% -> 0.54-0.61. The table is still right at 20% garbage, but the score drops under 0.8, so the page is
   flagged low confidence, and the best method result is kept. Good behaviour: bad tokens get flagged, not hidden.
2. **Method order changed: lines, mupdf, words, text** (spec: lines, text, mupdf, words).
   - `pdf.text` (pdfplumber text strategy) never produced a usable table: the title and subtitle lines contribute word edges
     that shift every column (header cells came out as "Role M", "on 09/14 T"). Mean accuracy 2.7%. It stays only as the last
     resort. It never won in any variant.
   - `pdf.lines` and `pdf.mupdf` are exact on ruled grids and give real cell borders as bboxes; on unruled pages they find no table
     (cost 7-50 ms, then fall through).
   - `pdf.words` (own clustering) was 100% on every variant, including unruled and wrapped names.
3. **Columns from x corridors, not header centres.** First version assigned words to columns by midpoints between header cells.
   It scored 97.2-99.6% on `mid`/`big` (long names such as "Oluwaseun Nguyen" spilled into the Role column), and the score
   did not notice (it stayed 1.00). Fix: cluster all table words by x (gap < 0.6 x font size); the corridors between clusters are
   the column edges; fall back to header cells only if the cluster count differs. Now 100%.
4. **Wrapped names:** a row with text only in the first column is the rest of the previous or next row's name; it joins the neighbour
   with the smaller vertical gap (works for top- and bottom-aligned cells).
5. **Two tables per page:** the gap between them is split at the first line in the gap's largest font (the next title). Before: footnote of
   the upper table. After: title and subtitle of the lower one. A first version used "bigger than body font" and mis-assigned the
   footnote to the next table's subtitle; the test caught it.
6. **Process pool: not used.** 40 pages (25 rows each): serial 1.69 s (42 ms/page), ProcessPool 1.13 s (1.5x). Real schedules are
   a few pages; the gain is under 100 ms there, so the extra code (pickling RawTables, per-process file opens) is not worth it.
7. **Raster pages:** `raster_150dpi` has 0 text chars/page: `PdfTextParser.sniff` = 0.1, `PdfScanParser.sniff` = 0.9, text extraction returns
   no tables. The scan parser renders PNGs at 150 dpi and submits one `page_reader` task per page.

## Limits of this evidence (honest)

- All variants come from one renderer (reportlab). Real schedule PDFs (Excel/Word print-to-PDF, EHR exports) can differ:
  coloured cells, merged day/date header rows, rotated text, rows split across pages with no repeated header.
  The cascade falls through to the agent `page_reader` when the best score is under 0.5; the score gives that signal.
- `merged_header` is a spanning title row above the header, not a two-line day/date header.
- Unknown tokens are kept verbatim, not dropped; `PARSE-SHIFT-TOKEN` issues come from downstream normalization.
