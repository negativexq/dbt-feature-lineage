/**
 * Small reusable page-chrome primitives shared by every page -- the
 * design system's actual building blocks (see globals.css's token
 * comment for the color/type rationale).
 */

const LAYER_COLORS: Record<string, string> = {
  staging: "var(--layer-staging)",
  intermediate: "var(--layer-intermediate)",
  marts: "var(--layer-marts)",
  unknown: "var(--layer-unknown)",
};

export function layerColor(layer: string | null | undefined): string {
  return LAYER_COLORS[layer ?? "unknown"] ?? LAYER_COLORS.unknown;
}

const HEALTH_COLORS: Record<string, string> = {
  healthy: "var(--status-healthy)",
  caution: "var(--status-caution)",
  degraded: "var(--status-degraded)",
  unknown: "var(--status-unknown)",
};

export function healthColor(status: string | null | undefined): string {
  return HEALTH_COLORS[status ?? "unknown"] ?? HEALTH_COLORS.unknown;
}

export function PageHeader({
  eyebrow,
  title,
  caption,
  right,
}: {
  eyebrow: string;
  title: string;
  caption?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-9 flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="mb-2 font-mono text-sm tracking-wide text-text-lo">
          <span className="text-accent">$</span> {eyebrow}
        </div>
        <h1 className="text-[2.75rem] font-semibold leading-none tracking-tight text-text-hi">
          {title}
          <span className="ml-1.5 inline-block h-9 w-1 translate-y-1.5 bg-accent motion-safe:animate-pulse" />
        </h1>
        {caption && <p className="mt-3 max-w-xl text-base text-text-lo">{caption}</p>}
      </div>
      {right && <div>{right}</div>}
    </div>
  );
}

export function StatusPill({
  projectName,
  group,
  mode,
}: {
  projectName: string;
  group: string | null;
  mode: "manifest" | "static" | null;
}) {
  const dotColor = mode === "manifest" ? "var(--accent)" : "var(--layer-unknown)";
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line bg-ink-900 px-3.5 py-2 font-mono text-sm text-text-hi">
      <span className="h-2 w-2 rounded-full" style={{ background: dotColor }} />
      {projectName} &middot; {group ?? "All"} &middot; {mode ?? "static"}
    </span>
  );
}

export function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-line bg-ink-900 px-5 py-4">
      <div className="font-mono text-3xl font-medium leading-tight text-text-hi">{value}</div>
      <div className="eyebrow mt-1.5">{label}</div>
    </div>
  );
}

export function LayerBadge({ layer }: { layer: string | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-sm text-text-hi">
      <span className="h-2 w-2 rounded-full" style={{ background: layerColor(layer) }} />
      {layer ?? "unknown"}
    </span>
  );
}

export function Card({
  children,
  className = "",
  style,
}: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={style}
      className={`rounded-lg border border-line bg-ink-900 p-5 text-base shadow-[0_1px_0_rgba(255,255,255,0.03)_inset,0_8px_24px_-16px_rgba(0,0,0,0.6)] ${className}`}
    >
      {children}
    </div>
  );
}

export function EmptyState({ title, body }: { title: string; body?: string }) {
  return (
    <Card className="text-center">
      <p className="text-base font-medium text-text-hi">{title}</p>
      {body && <p className="mt-1.5 text-sm text-text-lo">{body}</p>}
    </Card>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-base text-red-300">
      {message}
    </div>
  );
}

export function PrimaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>
) {
  const { className = "", ...rest } = props;
  return (
    <button
      {...rest}
      className={`rounded-md bg-accent px-5 py-2.5 text-base font-medium text-ink-950 shadow-[0_0_0_1px_rgba(255,122,69,0.4),0_8px_20px_-8px_rgba(255,122,69,0.55)] transition-all hover:-translate-y-px hover:opacity-90 disabled:opacity-50 disabled:hover:translate-y-0 ${className}`}
    />
  );
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", ...rest } = props;
  return (
    <input
      {...rest}
      className={`w-full rounded-md border border-line bg-ink-900 px-3.5 py-2.5 text-base text-text-hi outline-none placeholder:text-text-lo focus:border-accent ${className}`}
    />
  );
}

/** A single "$ command" row -- the terminal-prompt alternative to a
 * stacked label+input block, used on Select Project so the whole picker
 * reads as one typed command rather than a form. */
export function PromptField({
  prompt,
  children,
}: {
  prompt: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-line bg-ink-900 px-4 py-3.5 focus-within:border-accent">
      <span className="shrink-0 font-mono text-base text-accent">{prompt}</span>
      {children}
    </div>
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = "", ...rest } = props;
  return (
    <select
      {...rest}
      className={`rounded-md border border-line bg-ink-900 px-3.5 py-2.5 text-base text-text-hi outline-none focus:border-accent ${className}`}
    />
  );
}
