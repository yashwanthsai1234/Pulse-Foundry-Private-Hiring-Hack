import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useRun } from "./RunContext";

/** GET `path` (null = skip); refetches when the path changes or a run event bumps the global version. */
export function useApi<T>(path: string | null) {
  const { version } = useRun();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (path === null) { setData(null); return; }
    let live = true;
    api<T>(path).then((d) => { if (live) { setData(d); setError(null); } }, (e) => live && setError(String(e)));
    return () => { live = false; };
  }, [path, version]);
  return { data, error };
}
