import { useCallback, useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Answer } from "../api/types";
import type { RecognitionProps } from "../handover/useHandover";
import { choicePillClass, inputClass } from "../ds/classes";
import { secondaryButton } from "./styles";
import { Undo } from "./Undo";

const CHOICES: Answer[] = ["mine", "landlord", "unknown"];
export const MAX_NAME = 40; // the backend checks the same (app/handover/models.py)
export const MAX_NOTE = 200;

/** "Do you recognise this device?" with an optional short name, shown wherever the device
 * appears. Answers change the next steps and tasks, never the finding. */
export function Recognition({ props }: { props: RecognitionProps }) {
  return (
    <div className="mt-2 rounded-inner border border-line p-2">
      <RecognitionChoices props={props} />
      {/* A name only once it's known whose it is (Mine or Host's). Keyed by the saved name, so
          the box shows it again after it changes elsewhere. */}
      {(props.answer === "mine" || props.answer === "landlord") && <NameField key={props.name} props={props} />}
    </div>
  );
}

/** Mine, Host's or Unknown, with nothing chosen at first. "Host's" asks whether the host has
 * confirmed it. */
export function RecognitionChoices({ props }: { props: RecognitionProps }) {
  const { t } = useTranslation();
  const id = useId();
  const { subject, answer, confirmed, busy, failed } = props;
  // The answer before the last change, so it can always be put back.
  const [before, setBefore] = useState<{ answer: Answer | null; confirmed: boolean | null; message: string } | null>(null);
  const clear = useCallback(() => setBefore(null), []);
  const change = (next: Answer, nextConfirmed: boolean | null) => {
    setBefore({ answer, confirmed, message: t("undo.answer", { answer: t(`recognise.${next}`) }) });
    props.onAnswer(next, nextConfirmed);
  };
  const undo = () => {
    if (!before) return;
    props.onAnswer(before.answer, before.answer === "landlord" ? before.confirmed : null);
    setBefore(null);
  };
  return (
    <fieldset aria-describedby={`${id}-hint`}>
      <legend className="px-0.5 font-semibold">{t("recognise.legend")}</legend>
      <p id={`${id}-hint`} className="text-sm text-muted">
        {t("recognise.hint")}
      </p>
      <Choices
        name={`recognise-${subject}`}
        options={CHOICES.map((c) => ({ value: c, label: t(`recognise.${c}`) }))}
        value={answer}
        onChange={(a) => change(a, a === "landlord" ? confirmed : null)}
      />
      {answer === "landlord" && (
        <fieldset className="mt-1.5">
          <legend className="text-sm font-semibold">{t("recognise.confirmLegend")}</legend>
          <Choices
            name={`confirmed-${subject}`}
            options={[
              { value: "yes", label: t("recognise.confirmYes") },
              { value: "notYet", label: t("recognise.confirmNotYet") },
            ]}
            value={confirmed === null ? null : confirmed ? "yes" : "notYet"}
            onChange={(v) => change("landlord", v === "yes")}
          />
        </fieldset>
      )}
      <p aria-live="polite" className="mt-0.5 text-sm empty:hidden">
        {busy ? <span className="text-muted">{t("recognise.saving")}</span> : failed ? t("recognise.failed") : ""}
      </p>
      <Undo message={before?.message ?? null} onUndo={undo} onExpire={clear} />
    </fieldset>
  );
}

function Choices<V extends string>({
  name,
  options,
  value,
  onChange,
}: {
  name: string;
  options: { value: V; label: string }[];
  value: V | null;
  onChange: (value: V) => void;
}) {
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {options.map((o) => (
        <label
          key={o.value}
          className={choicePillClass(value === o.value)}
        >
          <input
            type="radio"
            name={name}
            value={o.value}
            checked={value === o.value}
            onChange={() => onChange(o.value)}
            className="size-2 accent-accent focus-visible:outline-none"
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

/** The optional short name and, in "Help identify this", a short note. Plain text only. */
export function NameField({ props, withNote = false }: { props: RecognitionProps; withNote?: boolean }) {
  const { t } = useTranslation();
  const id = useId();
  const [text, setText] = useState(props.name);
  const [note, setNote] = useState(props.note);
  const [saved, setSaved] = useState(false);
  const tooLong = text.length > MAX_NAME || note.length > MAX_NOTE;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (tooLong) return;
    if (withNote) props.onName(text.trim(), note.trim());
    else props.onName(text.trim());
    setSaved(true);
  }

  return (
    <form onSubmit={submit} className="mt-1.5 max-w-form" noValidate>
      <label htmlFor={`${id}-name`} className="block text-sm font-semibold">
        {t("recognise.nameLabel")}
      </label>
      <p id={`${id}-name-hint`} className="text-sm text-muted">
        {t("recognise.nameHint")}
      </p>
      <div className="mt-0.5 flex flex-wrap items-center gap-1">
        <input
          id={`${id}-name`}
          type="text"
          value={text}
          maxLength={MAX_NAME}
          autoComplete="off"
          aria-describedby={`${id}-name-hint`}
          aria-invalid={props.nameFailed || undefined}
          onChange={(e) => {
            setText(e.target.value);
            setSaved(false);
          }}
          className="min-w-0 flex-1 rounded-control border border-line-strong bg-surface px-1.5 py-0.5"
        />
        {!withNote && (
          <button type="submit" className={`${secondaryButton} py-0.5 text-sm`}>
            {t("recognise.saveName")}
          </button>
        )}
      </div>
      {withNote && (
        <>
          <label htmlFor={`${id}-note`} className="mt-1 block text-sm font-semibold">
            {t("recognise.noteLabel")}
          </label>
          <p id={`${id}-note-hint`} className="text-sm text-muted">
            {t("recognise.noteHint")}
          </p>
          <textarea
            id={`${id}-note`}
            value={note}
            rows={2}
            maxLength={MAX_NOTE}
            aria-describedby={`${id}-note-hint`}
            onChange={(e) => {
              setNote(e.target.value);
              setSaved(false);
            }}
            className={inputClass}
          />
          <button type="submit" className={`mt-1 ${secondaryButton} py-0.5 text-sm`}>
            {t("recognise.saveNameNote")}
          </button>
        </>
      )}
      <p aria-live="polite" className="mt-0.5 text-sm empty:hidden">
        {props.nameFailed ? (
          t(withNote ? "recognise.noteFailed" : "recognise.nameFailed")
        ) : saved ? (
          <span className="text-muted">{t(withNote ? "recognise.nameNoteSaved" : "recognise.nameSaved")}</span>
        ) : (
          ""
        )}
      </p>
    </form>
  );
}
