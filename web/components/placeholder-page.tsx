import { Construction } from "lucide-react";
import { Badge } from "@/components/ui/badge";

/** Polished placeholder for routes that arrive in later build phases. */
export function PlaceholderPage({
  title,
  description,
  phase,
}: {
  title: string;
  description: string;
  phase: string;
}) {
  return (
    <div className="mx-auto max-w-6xl animate-fade-in px-6 py-8">
      <div className="flex items-center gap-2.5 pb-8">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <Badge tone="info">{phase}</Badge>
      </div>

      <div className="flex flex-col items-center justify-center gap-4 rounded-lg border border-dashed border-border py-20 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
          <Construction className="h-5 w-5 text-muted-foreground" />
        </div>
        <div className="space-y-1.5">
          <p className="text-sm font-medium">Arriving in {phase}</p>
          <p className="mx-auto max-w-sm text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
    </div>
  );
}
