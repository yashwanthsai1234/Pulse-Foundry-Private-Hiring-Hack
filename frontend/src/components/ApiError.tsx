/** Inline error line for a failed request or action; renders nothing when there is no error. */
export function ApiError({ error }: { error: string | null }) {
  return error ? <p role="alert" className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">{error}</p> : null;
}
