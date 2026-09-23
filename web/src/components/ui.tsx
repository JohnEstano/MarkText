/* Small owned primitives (shadcn-style: cva + tailwind, no external UI kit).
   Radius rule: surfaces 12px, inputs 8px, buttons pill. */
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: Array<string | undefined | null | false>) {
  return twMerge(clsx(inputs));
}

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition-[background-color,transform,color] duration-200 active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg hover:brightness-110",
        secondary: "bg-bg-elev text-fg border border-line-strong hover:bg-bg-muted",
        ghost: "text-fg-muted hover:text-fg hover:bg-bg-muted",
        danger: "bg-danger-soft text-danger hover:brightness-95",
      },
      size: {
        sm: "h-8 px-3 text-sm",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(button({ variant, size }), className)} {...props} />;
}

export function buttonClass(v?: VariantProps<typeof button>, extra?: string) {
  return cn(button(v), extra);
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("block text-sm font-medium text-fg", className)} {...props} />;
}

const field =
  "w-full rounded-[var(--radius-input)] border border-line-strong bg-bg-elev px-3 text-fg placeholder:text-fg-faint transition-colors focus:border-accent";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(field, "h-10 text-sm", className)} {...props} />;
}

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(field, "py-2 text-sm leading-relaxed", className)} {...props} />;
}

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(field, "h-10 text-sm", className)} {...props} />;
}

export function Help({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-fg-muted">{children}</p>;
}

export function FieldError({ children }: { children?: React.ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="text-sm text-danger">
      {children}
    </p>
  );
}

export function Panel({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-[var(--radius-surface)] border border-line bg-bg-elev", className)}
      {...props}
    />
  );
}

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: "accent" | "warn" | "neutral" | "muted" | "danger" }) {
  const tones = {
    accent: "bg-accent-soft text-accent-soft-fg",
    warn: "bg-warn-soft text-warn",
    neutral: "bg-bg-muted text-fg",
    muted: "bg-bg-muted text-fg-muted",
    danger: "bg-danger-soft text-danger",
  };
  return (
    <span
      className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", tones[tone], className)}
      {...props}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-[var(--radius-input)] bg-bg-muted", className)} />;
}

export function Notice({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "warn" | "danger" | "accent";
  children: React.ReactNode;
}) {
  const tones = {
    neutral: "border-line bg-bg-muted text-fg",
    warn: "border-warn/30 bg-warn-soft text-warn",
    danger: "border-danger/30 bg-danger-soft text-danger",
    accent: "border-accent/30 bg-accent-soft text-accent-soft-fg",
  };
  return (
    <div role="status" className={cn("rounded-[var(--radius-input)] border px-3 py-2 text-sm", tones[tone])}>
      {children}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-[var(--radius-surface)] border border-dashed border-line-strong px-6 py-12 text-center">
      <p className="font-medium text-fg">{title}</p>
      {children && <div className="mt-2 text-sm text-fg-muted">{children}</div>}
    </div>
  );
}

export function Metric({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-fg-muted">{label}</p>
      <p className="tabular mt-1 truncate font-mono text-2xl font-medium text-fg">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-fg-faint">{hint}</p>}
    </div>
  );
}

/* Client-side pager for tables the API returns whole. Shows the window it
   is on, and never lets the page run past the last one. */
export function Pager({
  page,
  total,
  per,
  onChange,
}: {
  page: number;
  total: number;
  per: number;
  onChange: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / per));
  const cur = Math.min(page, pages);
  const from = total === 0 ? 0 : (cur - 1) * per + 1;
  const to = Math.min(cur * per, total);
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3 text-sm">
      <p className="tabular font-mono text-xs text-fg-muted">
        {from}–{to} of {total}
      </p>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" disabled={cur <= 1} onClick={() => onChange(cur - 1)}>
          Previous
        </Button>
        <span className="tabular font-mono text-xs text-fg-muted">
          page {cur} of {pages}
        </span>
        <Button variant="secondary" size="sm" disabled={cur >= pages} onClick={() => onChange(cur + 1)}>
          Next
        </Button>
      </div>
    </nav>
  );
}
