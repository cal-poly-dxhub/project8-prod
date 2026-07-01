import type {
  ButtonHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";

/** Tiny className joiner (drops falsy values). */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "success" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-600 text-white hover:bg-brand-700 focus-visible:outline-brand-600",
  secondary:
    "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 focus-visible:outline-slate-400",
  success:
    "bg-emerald-600 text-white hover:bg-emerald-700 focus-visible:outline-emerald-600",
  danger:
    "bg-rose-600 text-white hover:bg-rose-700 focus-visible:outline-rose-600",
  ghost:
    "bg-transparent text-slate-600 hover:bg-slate-100 focus-visible:outline-slate-400",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ButtonProps) {
  const sizing = size === "sm" ? "px-3 py-1.5 text-sm" : "px-4 py-2 text-sm";
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        sizing,
        VARIANTS[variant],
        className
      )}
      {...props}
    />
  );
}

export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cx(
        "rounded-2xl border border-slate-200 bg-white shadow-sm",
        className
      )}
    >
      {children}
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return (
    <label className="mb-1.5 block text-sm font-semibold text-slate-700">
      {children}
    </label>
  );
}

export function Select({
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cx(
        "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm",
        "focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100",
        className
      )}
      {...props}
    />
  );
}

type Tone = "slate" | "blue" | "green" | "red" | "amber" | "indigo";

const TONES: Record<Tone, string> = {
  slate: "bg-slate-100 text-slate-700",
  blue: "bg-blue-100 text-blue-700",
  green: "bg-emerald-100 text-emerald-700",
  red: "bg-rose-100 text-rose-700",
  amber: "bg-amber-100 text-amber-800",
  indigo: "bg-brand-100 text-brand-700",
};

export function Badge({
  tone = "slate",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold",
        TONES[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

/** Centered overlay scrim for modals. */
export function ModalOverlay({
  onClose,
  children,
}: {
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      {children}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label ?? "Loading…"}
    </div>
  );
}

export function Alert({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      {children}
    </div>
  );
}
