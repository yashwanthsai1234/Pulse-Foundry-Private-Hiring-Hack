import type { Credential } from "../api/types";
import { ApiError } from "../components/ApiError";
import { bucketCredentials } from "../lib/credentials";
import { useApi } from "../lib/useApi";

const COLUMNS = [
  ["overdue", "Overdue", "border-red-300 bg-red-50"],
  ["d30", "Within 30 days", "border-orange-300 bg-orange-50"],
  ["d60", "Within 60 days", "border-amber-300 bg-amber-50"],
  ["d90", "Within 90 days", "border-slate-300 bg-white"],
] as const;

function Holders({ title, items }: { title: string; items: Credential[] }) {
  return (
    <div>
      <h4 className="text-xs uppercase text-slate-500">{title}</h4>
      {items.length === 0 ? <p className="text-xs text-slate-400">none</p> : items.map((c) => (
        <p key={c.credential_id} className="text-sm">
          <span className="font-medium">{c.holder_name}</span> {c.credential_type} {c.number}
          <span className="block text-xs text-slate-500">expires {c.expires_on} ({c.days_left} d)</span>
        </p>
      ))}
    </div>
  );
}

export default function Credentials() {
  const { data, error } = useApi<Credential[]>("/api/credentials?horizon_days=90");
  const buckets = bucketCredentials(data ?? []);
  if (error) return <ApiError error={error} />;
  if (data?.length === 0) return <p className="text-sm text-slate-500">No credentials expiring within 90 days.</p>;
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {COLUMNS.map(([key, label, color]) => (
        <section key={key} className={`space-y-3 rounded border p-3 ${color}`}>
          <h3 className="font-semibold">{label} ({buckets[key].length})</h3>
          <Holders title="People" items={buckets[key].filter((c) => c.holder_type === "person")} />
          <Holders title="Organizations" items={buckets[key].filter((c) => c.holder_type === "organization")} />
        </section>
      ))}
    </div>
  );
}
