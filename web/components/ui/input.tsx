import * as React from "react";
import { cn } from "@/lib/utils";

// Shared field styling — reuse on <select> and <textarea> too.
export const fieldClass =
  "h-9 w-full border border-input bg-background px-3 text-sm text-foreground " +
  "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background " +
  "disabled:cursor-not-allowed disabled:opacity-50";

/** One generated id shared by a <Label> and the control beside it. Without it
 *  the label is a bare <label> — clicking it doesn't focus the field and screen
 *  readers announce an unlabelled textbox (WCAG 1.3.1 / 4.1.2). */
const FieldIdContext = React.createContext<string | undefined>(undefined);

/** Wrap a Label + control pair so the two associate automatically. */
export function FieldGroup({ children }: { children: React.ReactNode }) {
  const id = React.useId();
  return <FieldIdContext.Provider value={id}>{children}</FieldIdContext.Provider>;
}

/** The enclosing FieldGroup's id, for controls that aren't <Input> (a raw
 *  <select> or <textarea> styled with fieldClass). */
export function useFieldId(): string | undefined {
  return React.useContext(FieldIdContext);
}

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, id, ...props }, ref) => {
  const fieldId = React.useContext(FieldIdContext);
  return <input ref={ref} id={id ?? fieldId} className={cn(fieldClass, className)} {...props} />;
});
Input.displayName = "Input";

export function Label({
  className,
  htmlFor,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  const fieldId = React.useContext(FieldIdContext);
  return (
    <label
      htmlFor={htmlFor ?? fieldId}
      className={cn("text-xs font-medium text-muted-foreground", className)}
      {...props}
    />
  );
}
