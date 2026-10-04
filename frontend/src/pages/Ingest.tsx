// Sources: https://developer.mozilla.org/en-US/docs/Web/API/HTML_Drag_and_Drop_API/File_drag_and_drop
import { useState, type DragEvent } from "react";
import { ingest } from "../api/client";
import type { Summary } from "../api/types";
import { PipelineFeed } from "../components/PipelineFeed";
import { groupByRun } from "../lib/eventLog";
import { useRun } from "../lib/RunContext";
import { useApi } from "../lib/useApi";

function Tiles({ s }: { s: Summary }) {
  const tiles: [string, number][] = [
    ["files", s.files], ["tables", s.tables], ["records", s.records], ["people", s.persons],
    ["issues", Object.values(s.issues_by_severity).reduce((a, b) => a + b, 0)],
    ["agent tasks", Object.values(s.agent_tasks).reduce((a, b) => a + b, 0)],
  ];
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
      {tiles.map(([label, n]) => (
        <div key={label} className="rounded border border-slate-200 bg-white p-3 text-center">
          <div className="text-2xl font-semibold">{n}</div>
          <div className="text-xs text-slate-500">{label}</div>
        </div>
      ))}
    </div>
  );
}

export default function Ingest() {
  const { events } = useRun();
  const { data: summary, error: summaryError } = useApi<Summary>("/api/summary");
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(files: File[]) {
    if (files.length === 0) return;
    try {
      setError(null);
      await ingest(files);
    } catch (e) {
      setError(String(e));
    }
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); upload([...e.dataTransfer.files]); };

  return (
    <div className="space-y-4">
      {summaryError && <p className="text-sm text-red-600">Cannot load summary: {summaryError}</p>}
      {summary && <Tiles s={summary} />}
      <div className="grid gap-4 md:grid-cols-2">
        <label
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
          className={`flex h-48 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed text-slate-600 ${over ? "border-blue-500 bg-blue-50" : "border-slate-300 bg-white"}`}
        >
          <span className="font-medium">Drop files here (any format)</span>
          <span className="text-sm">or click to select</span>
          <input type="file" multiple className="hidden" data-testid="file-input" onChange={(e) => upload([...(e.target.files ?? [])])} />
        </label>
        <div>
          <h2 className="mb-2 text-sm font-semibold uppercase text-slate-500">Live pipeline</h2>
          {error && <p className="text-sm text-red-600">{error}</p>}
          {events.length === 0 && <p className="text-sm text-slate-500">No run yet. Drop files to start.</p>}
          {groupByRun(events).map((r, i) => (
            <details key={r.runId} open={i === 0} className="mb-2">
              <summary className="cursor-pointer font-mono text-xs text-slate-500">{r.runId}</summary>
              <PipelineFeed events={r.events} />
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}
