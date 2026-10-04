import { PBJ_COLUMNS, type PbjRow, type PbjStatus } from "../api/types";

/** Splits CSV text into records, honouring double-quoted fields (RFC 4180: "" is an escaped quote). */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      rows.push(row); row = [];
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

export function parsePbj(text: string): PbjRow[] {
  const [header, ...rows] = parseCsv(text);
  if (!header) return [];
  return rows.filter((r) => r.length > 1).map((r) => {
    const rec = Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""]));
    return Object.fromEntries(PBJ_COLUMNS.map((c) => [c, rec[c] ?? ""])) as PbjRow;
  });
}

export const filterPbj = (rows: PbjRow[], status: PbjStatus | "all") =>
  status === "all" ? rows : rows.filter((r) => r.status === status);
