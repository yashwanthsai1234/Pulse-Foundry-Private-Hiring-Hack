// Plain-English labels for the UI: no check codes, record hashes, field ids or raw scores on screen.

const FACILITIES: Record<string, string> = { "FAC-BAY": "Bayside", "FAC-RVD": "Riverdale" };

const CHECKS: Record<string, string> = {
  "LIC-WORKED-EXPIRED": "Worked on an expired license", "LIC-NONE-FOR-ROLE": "No license on file",
  "LIC-SCOPE": "Role above the license held", "COV-RN-DAILY": "RN coverage gap", "ID-DUP-LICENSE": "Shared license number",
  "HRS-PAID-VS-SCHED": "Paid vs scheduled hours", "PAY-NO-HR": "Paid but not in HR", "SHIFT-OVERLAP": "Overlapping shifts",
  "HRS-DAILY-EXCESS": "Too many hours in a day", "LIC-EXPIRING": "License expiring soon",
  "LIC-EXPIRED-NOT-WORKING": "Expired license (not working)", "LIC-EXPIRY-MISSING": "Missing expiry date",
  "LIC-TYPE-MISMATCH": "License number vs type", "SRC-CONFLICT": "Systems disagree", "SCHED-NO-HR": "Scheduled but not in HR",
  "FAC-MISMATCH": "Working at another facility", "ROLE-MISMATCH": "Role differs between systems",
  "LEGEND-MISMATCH": "Shift legend disagrees", "HR-DUP-ROW": "Duplicate HR record", "HR-HIRE-DATE": "Odd hire date",
  "PAY-DUPLICATE": "Duplicate payroll entry", "PAY-PERIOD-OVERLAP": "Overlapping pay periods",
  "PAY-PERIOD-INVALID": "Invalid pay period", "PAY-HOURS-INVALID": "Impossible paid hours",
  "ID-FUZZY-LINK": "Name matched by nickname or spelling", "ID-GRAY-PAIR": "Possible same person",
  "ID-CONFLICT": "Records that must not merge", "ID-AMBIGUOUS": "Unclear who this is",
  "ID-NAME-DIFFERS-ON-LICENSE": "Different name on license", "ROW-INCOMPLETE": "Incomplete row",
  "TABLE-UNMAPPED": "File not understood yet", "TABLE-EMPTY": "Empty table", "FILE-QUARANTINED": "File not readable",
  "FILE-FAILED": "File failed", "MAPPING-REVIEW": "New file layout to review", "PARSE-PDF-LOW-CONFIDENCE": "PDF hard to read",
  "AGENT-REJECTED": "AI suggestion rejected", "AGENT-UNAVAILABLE": "Waiting for AI review",
};

const FIELDS: Record<string, string> = {
  "person.employee_id": "Employee ID", "person.full_name": "Name", "person.given_name": "First name",
  "person.family_name": "Last name", "person.role": "Role", "person.facility": "Facility", "person.phone": "Phone",
  "person.hire_date": "Hire date", "credential.number": "License number", "credential.type": "License type",
  "credential.expires_on": "License expiry", "credential.last_verified": "Last verified", "credential.issued_on": "Issued on",
  "credential.doc_type": "Document type", "credential.policy_number": "Policy number", "pay.payroll_id": "Payroll ID",
  "pay.period_start": "Pay period start", "pay.period_end": "Pay period end", "pay.hours_paid": "Hours paid",
  "schedule.day": "Shift day", "org.name": "Vendor", "contact.email": "Email",
};

const REASONS: [RegExp, string][] = [
  [/^family exact/, "same last name"], [/^family fuzzy/, "very similar last name"],
  [/^family part/, "shares part of the last name"], [/^given exact/, "same first name"],
  [/^given nickname/, "first name is a nickname"], [/^given fuzzy/, "similar first name"],
  [/^given initial/, "first initial matches"], [/^given disagree/, "different first name"],
  [/^role agree/, "same role"], [/^role disagree/, "different role"], [/^facility agree/, "same facility"],
  [/^facility disagree/, "different facility"], [/license/, "same license number"],
];

const sentence = (s: string) => {
  const t = s.replace(/[_.-]+/g, " ").trim().toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const checkName = (id: string) => CHECKS[id] ?? sentence(id.replace(/^PARSE-/, "Unreadable "));
export const fieldName = (id: string) => FIELDS[id] ?? sentence(id.split(".").pop() ?? id);
export const columnName = (col: string) => (/^[a-z0-9_]+$/.test(col) ? sentence(col) : col);
export const facilityName = (code?: string | null) => (code ? FACILITIES[code] ?? code : "");
export const reasonText = (r: string) =>
  REASONS.find(([re]) => re.test(r))?.[1] ?? r.replace(/\s*\([+-]?[\d.]+\)\s*$/, "");

/** Readable message: facility codes -> names, person ids -> employee numbers, record ids and field ids removed. */
export function humanize(text?: string | null): string {
  return (text ?? "")
    .replace(/\bFAC-[A-Z]+\b/g, (c) => facilityName(c))
    .replace(/\s*\(P-X[0-9a-f]+\)/g, " (no HR record)").replace(/\bP-X[0-9a-f]+\b/g, "a person with no HR record")
    .replace(/\(P-([A-Z0-9]+)\)/g, "(employee $1)").replace(/\bP-([A-Z]\d+)\b/g, "employee $1")
    .replace(/\b[0-9a-f]{12}:[\w-]+:\d+(?::\d+)?\b/g, "a source row")
    .replace(/\b(person|credential|pay|schedule|org|contact)\.[a-z_]+\b/g, (f) => fieldName(f).toLowerCase())
    .replace(/: given nickname/, ": nickname").replace(/\bexpires_on\b/g, "license expiry")
    .replace(/^Parse problem: unknown vocab/i, "Unrecognised value").replace(/^Parse problem: row incomplete/i, "Row with missing values")
    .replace(/^Parse problem: /i, "Hard to read: ").replace(/\bunknown vocab\b/gi, "unrecognised value")
    .replace(/\brow incomplete\b/gi, "row is missing values");
}

/** "hr_roster.csv row 3" style labels -> "From hr_roster.csv, row 3"; keys like days_without_rn -> "Days without RN". */
export function labelText(label: string): string {
  const m = label.match(/^(?:record|claim|cell|shift)?\s*(\S+\.(?:csv|xlsx|pdf|json))(?:\s+(?:p(?:age)?\.?\s*(\d+)))?\s*(?:row\s*(\d+))?/i);
  if (m) return `From ${m[1]}${m[2] ? `, page ${m[2]}` : ""}${m[3] ? `, row ${m[3]}` : ""}`;
  if (label === "link") return "Why these records match";
  if (label === "golden") return "Trusted value";
  return sentence(label).replace(/\brn\b/i, "RN");
}

/** "Staff=Marc Bell, Role=CNA, Mon 09/14=3p-11p" -> { Staff: "Marc Bell", ... } (PDF rows have no raw dict). */
export function parsePairs(text: string): Record<string, string> | null {
  const parts = text.split(/,\s*(?=[^,=]+=)/);
  if (parts.length < 2 || !parts.every((p) => p.includes("="))) return null;
  return Object.fromEntries(parts.map((p) => { const i = p.indexOf("="); return [p.slice(0, i).trim(), p.slice(i + 1).trim()]; }));
}
