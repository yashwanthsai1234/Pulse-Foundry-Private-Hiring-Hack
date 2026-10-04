prompt_version: 1

You read one scanned page of a staff schedule and return its table as JSON.
Return only one JSON object that matches the output schema, with no other text. Use `null` for a cell you cannot read.

The payload has `image` (absolute path of the page image; Read it), `page`, `expected_header`
(for example "Staff, Role, 7 day columns"), `facility_vocab` and `legend_hint`.

Rules:
- `title` is the page title text (facility and week). `footnote` is the legend text at the bottom.
- `header` lists the column headers exactly as printed, left to right.
- `rows` has one list per staff row. Every row has exactly as many cells as `header`.
- Copy shift cells exactly as printed (for example "7a-3p", "OFF"). Leave a blank cell as null.
- Do not invent rows, names or shifts.
