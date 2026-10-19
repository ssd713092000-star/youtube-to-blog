import { forwardRef } from "react";

import { cn } from "@/lib/utils";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ className, invalid, ...props }, ref) {
    return (
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          "h-9 w-full rounded-md border border-border bg-surface px-3 text-sm text-fg placeholder:text-fg-faint",
          "focus:border-accent focus:outline-none disabled:opacity-60",
          invalid && "border-danger",
          className,
        )}
        {...props}
      />
    );
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function Textarea({ className, invalid, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-faint",
          "focus:border-accent focus:outline-none",
          invalid && "border-danger",
          className,
        )}
        {...props}
      />
    );
  },
);

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("mb-1.5 block text-xs font-medium text-fg-muted", className)} {...props} />;
}

export function FieldError({ children }: { children?: React.ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="mt-1 text-xs text-danger">
      {children}
    </p>
  );
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-[10px] border border-border bg-surface", className)} {...props} />;
}

export function CardHeader({ title, description, actions }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
      <div>
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        {description && <p className="mt-0.5 text-xs text-fg-subtle">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-border/70", className)} />;
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-sidebar px-1.5 py-0.5 font-mono text-[10.5px] text-fg-subtle">{children}</kbd>
  );
}

export function Mono({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("font-mono", className)} {...props} />;
}

export function SectionTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">{children}</h2>
      {right}
    </div>
  );
}
