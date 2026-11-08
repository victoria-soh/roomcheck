import { useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

import { cardClass, chipClass, fieldHint, fieldLabel, fileInputClass, inputClass, rowClass } from "./classes";

/** A card: standard padding. For meaningful groups, not around every small item. */
export function Card({
  children,
  labelledBy,
  as: Tag = "section",
  className = "",
  id,
}: {
  children: ReactNode;
  labelledBy?: string;
  as?: "section" | "div" | "article" | "form";
  className?: string;
  id?: string;
}) {
  return (
    <Tag id={id} aria-labelledby={labelledBy} className={`${cardClass} ${className}`}>
      {children}
    </Tag>
  );
}

/** A two-line radio row: the whole row is the target; selected has a teal edge and an aqua
 * tint, and the focus ring is a separate dark ring outside the row. */
export function RadioRow({
  name,
  value,
  checked,
  onChange,
  label,
  hint,
}: {
  name: string;
  value: string;
  checked: boolean;
  onChange: () => void;
  label: ReactNode;
  hint?: ReactNode;
}) {
  const id = `${useId()}-${value}`;
  return (
    <label className={rowClass(checked)}>
      <input
        type="radio"
        name={name}
        value={value}
        aria-labelledby={`${id}-label`}
        aria-describedby={hint ? `${id}-hint` : undefined}
        checked={checked}
        onChange={onChange}
        className="mt-0.5 size-2.5 shrink-0 cursor-pointer appearance-none rounded-full border-2 border-line-strong bg-surface transition-colors checked:border-6 checked:border-accent focus-visible:outline-none"
      />
      <span className="min-w-0">
        <span id={`${id}-label`} className="block font-semibold">
          {label}
        </span>
        {hint && (
          <span id={`${id}-hint`} className="block text-sm text-muted">
            {hint}
          </span>
        )}
      </span>
    </label>
  );
}

/** A checkbox with its name as the label and what it means as the description. */
export function Checkbox({
  label,
  hint,
  checked,
  onChange,
}: {
  label: ReactNode;
  hint?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="mt-1 flex items-start gap-1.5">
      <input
        id={`${id}-box`}
        type="checkbox"
        checked={checked}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-2.5 shrink-0 cursor-pointer accent-accent"
      />
      <div>
        <label htmlFor={`${id}-box`} className="block cursor-pointer font-semibold">
          {label}
        </label>
        {hint && (
          <p id={`${id}-hint`} className="max-w-measure text-sm text-muted">
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}

type FieldProps = { label: string; hint?: string; error?: string | null };

function FieldShell({ id, label, hint, error, children }: FieldProps & { id: string; children: ReactNode }) {
  return (
    <div className="max-w-form">
      <label htmlFor={id} className={fieldLabel}>
        {label}
      </label>
      {hint && (
        <span id={`${id}-hint`} className={fieldHint}>
          {hint}
        </span>
      )}
      {children}
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-0.5 text-sm font-semibold text-sev-high">
          {error}
        </p>
      )}
    </div>
  );
}

function describedBy(id: string, hint?: string, error?: string | null) {
  return [hint ? `${id}-hint` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined;
}

export function TextInput({ label, hint, error, ...rest }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <input id={id} type="text" aria-describedby={describedBy(id, hint, error)} aria-invalid={error ? true : undefined} className={inputClass} {...rest} />
    </FieldShell>
  );
}

export function Textarea({ label, hint, error, ...rest }: FieldProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <textarea id={id} aria-describedby={describedBy(id, hint, error)} aria-invalid={error ? true : undefined} className={inputClass} {...rest} />
    </FieldShell>
  );
}

export function FileInput({
  label,
  hint,
  accept,
  onPick,
}: {
  label: string;
  hint: string;
  accept: string;
  onPick: (file: File | null) => void;
}) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint}>
      <input id={id} type="file" accept={accept} aria-describedby={`${id}-hint`} onChange={(e) => onPick(e.target.files?.[0] ?? null)} className={fileInputClass} />
    </FieldShell>
  );
}

/** A stat tile: a label, a number, and (as a filter) a pressed state with a tick. */
export function StatTile({
  label,
  value,
  extra,
  pressed,
  onClick,
  describedBy: described,
}: {
  label: ReactNode;
  value: ReactNode;
  extra?: ReactNode;
  pressed?: boolean; // a filter: aria-pressed, filled teal when on
  onClick?: () => void;
  describedBy?: string;
}) {
  const tile = "flex min-h-6 items-center justify-between gap-1 rounded-inner px-1.5 py-1 text-left transition-colors";
  const body = (
    <>
      <span className="flex flex-col">{label}</span>{" "}
      <span className="text-right">
        {value}
        {extra}
      </span>
    </>
  );
  if (!onClick) return <div className={`${tile} border border-line bg-raised text-muted`}>{body}</div>;
  return (
    <button
      type="button"
      aria-pressed={pressed === undefined ? undefined : pressed}
      aria-describedby={described}
      onClick={onClick}
      className={`${tile} ${chipClass(Boolean(pressed))}`}
    >
      {body}
    </button>
  );
}
