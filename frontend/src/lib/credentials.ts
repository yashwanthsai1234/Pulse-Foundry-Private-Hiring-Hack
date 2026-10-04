import type { Credential } from "../api/types";

export interface Buckets { overdue: Credential[]; d30: Credential[]; d60: Credential[]; d90: Credential[] }

/** Buckets by days_left: <0 overdue, 0-30, 31-60, 61-90. Credentials beyond 90 days or without expiry are dropped. */
export function bucketCredentials(items: Credential[]): Buckets {
  const b: Buckets = { overdue: [], d30: [], d60: [], d90: [] };
  for (const c of items) {
    const d = c.days_left;
    if (d === null) continue;
    if (d < 0) b.overdue.push(c);
    else if (d <= 30) b.d30.push(c);
    else if (d <= 60) b.d60.push(c);
    else if (d <= 90) b.d90.push(c);
  }
  return b;
}
