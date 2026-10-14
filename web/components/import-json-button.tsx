"use client";

import { Loader2, Upload } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";

/** A button that opens a file picker, parses the chosen file as JSON, and
 *  hands it to `onImport` — the shared other half of `downloadJson`. */
export function ImportJsonButton<T>({
  label = "Import",
  onImport,
}: {
  label?: string;
  onImport: (data: T) => Promise<unknown>;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file after an error
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      const data = JSON.parse(await file.text()) as T;
      await onImport(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid file");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" onClick={() => inputRef.current?.click()} disabled={busy}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
        {label}
      </Button>
      <input ref={inputRef} type="file" accept="application/json" hidden onChange={handleFile} />
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}
