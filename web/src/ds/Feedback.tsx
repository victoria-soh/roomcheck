import { useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ChevronIcon, ErrorIcon, InfoIcon, ProblemIcon, UndoIcon } from "../components/icons";
import { Button } from "./Button";
import { NOTICE, type NoticeTone } from "./classes";

const NOTICE_ICON = { info: InfoIcon, warning: ProblemIcon, error: ErrorIcon } as const;

/** A notice: info (aqua), warning (amber: something didn't work or can't be confirmed) or
 * error (red). Notices never move. */
export function Notice({ title, children, tone = "warning" }: { title?: string; children?: ReactNode; tone?: NoticeTone }) {
  const Icon = NOTICE_ICON[tone];
  return (
    <div className={NOTICE[tone].box}>
      {title && (
        <p className="flex items-start gap-1 font-semibold">
          <span className={`mt-0.5 ${NOTICE[tone].icon}`}>
            <Icon />
          </span>
          <span>{title}</span>
        </p>
      )}
      {children && <div className={title ? "mt-0.5" : ""}>{children}</div>}
    </div>
  );
}

/** A quiet line with an info icon, for hints such as why a button can't be used yet. */
export function Hint({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <p id={id} className="flex max-w-measure items-start gap-1 text-sm text-muted">
      <span className="text-accent">
        <InfoIcon />
      </span>
      <span>{children}</span>
    </p>
  );
}

/** Nothing to show yet: a short title and what to do next. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-inner border border-dashed border-line-strong bg-surface px-2 py-1.5">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-0.5 text-muted">{children}</div>}
    </div>
  );
}

/** A native details/summary: Enter or Space opens it, and screen readers say expanded or not. */
export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group">
      <summary className="inline-flex cursor-pointer list-none items-center gap-0.5 rounded-control font-semibold text-accent underline-offset-4 transition-colors hover:text-accent-hover hover:underline">
        {summary}
        <ChevronIcon />
      </summary>
      <div className="mt-1 max-w-measure rounded-inner bg-raised px-2 py-1.5">{children}</div>
    </details>
  );
}

/** A bigger disclosure for sections inside a card (an accordion row). */
export function Accordion({ summary, children, id }: { summary: ReactNode; children: ReactNode; id?: string }) {
  return (
    <details id={id} className="group rounded-card border border-line bg-surface shadow-soft">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-card px-3 py-2 font-semibold transition-colors hover:bg-raised">
        {summary}
        <span className="text-muted">
          <ChevronIcon />
        </span>
      </summary>
      <div className="px-3 pb-2">{children}</div>
    </details>
  );
}

export function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="max-w-measure space-y-0.5 text-ink">
      {items.map((item) => (
        <li key={item} className="flex gap-1.5">
          <span aria-hidden="true" className="mt-1 size-0.75 shrink-0 rounded-full bg-accent" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** "Status changed to Asked. Undo": a small toast after a change, announced politely and
 * reachable by keyboard. It stays until the next change or 15 seconds. */
export function UndoToast({
  message,
  onUndo,
  onExpire,
}: {
  message: string | null;
  onUndo: () => void;
  onExpire: () => void;
}) {
  const { t } = useTranslation();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(timer.current);
    if (message) timer.current = setTimeout(onExpire, 15_000);
    return () => clearTimeout(timer.current);
  }, [message, onExpire]);
  return (
    <div aria-live="polite" className="mt-0.5 empty:hidden">
      {message && (
        <p className="inline-flex flex-wrap items-center gap-x-1 rounded-control border border-line bg-raised px-1 py-0.5 text-sm">
          <span>{message}</span>
          <Button variant="text" size="sm" icon={<UndoIcon />} onClick={onUndo}>
            {t("undo.button")}
          </Button>
        </p>
      )}
    </div>
  );
}
