import type { ShiftGrid } from "../api/types";
import { ApiError } from "../components/ApiError";
import { useApi } from "../lib/useApi";

const dayLabel = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", { weekday: "short", month: "numeric", day: "numeric", timeZone: "UTC" });

export default function Shifts() {
  const { data, error } = useApi<ShiftGrid>("/api/shifts");
  if (error) return <ApiError error={error} />;
  if (!data) return <p className="text-slate-500">Loading...</p>;
  if (data.facilities.length === 0) return <p className="text-sm text-slate-500">No shifts yet. Ingest a schedule first.</p>;
  return (
    <div className="space-y-6">
      {data.facilities.map((f) => (
        <section key={f.facility_id}>
          <h2 className="mb-1 font-semibold">{f.name}</h2>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse bg-white text-sm">
              <thead>
                <tr className="bg-slate-100 text-xs text-slate-500">
                  <th className="border p-2 text-left">Person</th>
                  {data.days.map((d) => <th key={d} className="border p-2">{dayLabel(d)}</th>)}
                </tr>
              </thead>
              <tbody>
                {f.rows.map((r) => (
                  <tr key={r.person_id}>
                    <td className="border p-2 font-medium">{r.display_name} <span className="text-xs text-slate-500">{r.role}</span></td>
                    {data.days.map((d) => {
                      const c = r.cells[d];
                      return (
                        <td key={d} data-testid={c && !c.license_valid ? "invalid-cell" : undefined}
                          className={`border p-2 text-center ${c && !c.license_valid ? "bg-red-100 text-red-800" : ""}`}>
                          {c ? <>{c.token}<div className="text-xs opacity-70">{c.hours} h</div></> : <span className="text-slate-300">-</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                <tr className="bg-slate-50 font-medium">
                  <td className="border p-2">RN coverage (h)</td>
                  {data.days.map((d) => {
                    const h = f.rn_coverage[d] ?? 0;
                    return <td key={d} className={`border p-2 text-center ${h < 8 ? "bg-red-100 text-red-800" : "text-green-800"}`}>{h}</td>;
                  })}
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
