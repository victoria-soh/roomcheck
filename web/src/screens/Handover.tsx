import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import type { HandoverState, Task, TaskStatus } from "../api/types";
import { ChevronIcon, InfoIcon } from "../components/icons";
import { taskAnchor } from "../components/links";
import { Undo } from "../components/Undo";
import { ScreenHeading } from "../components/ScreenHeading";
import { SeverityBadge } from "../components/SeverityBadge";
import { quietButton, secondaryButton } from "../components/styles";
import { EvidenceBadge, StatusBadge } from "../ds/Badge";
import { chipClass, choicePillClass, inputClass } from "../ds/classes";
import { Checkbox } from "../ds/Fields";
import { Bullets, Hint, Notice } from "../components/ui";
import { formatWhen } from "../format";
import { askable, isOpen, messageFor, stepsBeyondAsk } from "../handover/message";
import { nameFor, useHandover, useRecheck, useTaskUpdate } from "../handover/useHandover";
import type { HandoverFocus } from "./Results";

const STATUSES: TaskStatus[] = ["todo", "asked", "resolved"];
const AUTOSAVE_MS = 800; // notes save this long after typing stops
const MESSAGE_ID = "host-message";

type Filter = "all" | "open" | "resolved";

/** Layer 6 handover assistant: a task per High or Medium finding, from fixed templates. Each
 * has a workflow status (To do, Asked, Resolved) and, separately, its evidence: "Host
 * confirmed" (what the user recorded) and "Observed by RoomCheck" (a recheck). Everything is
 * saved on this laptop as you go. The message to the host comes first: choose which open
 * tasks it asks about, then edit and copy it. Task cards are compact and open for the rest. */
export function Handover({ focus, onOpenReport }: { focus?: HandoverFocus; onOpenReport?: () => void }) {
  const { t } = useTranslation();
  const state = useHandover();
  const data = state.data;
  // From a Results card: go straight to the message, or to that device's task (opened).
  const target = !focus ? null : focus === "message" ? MESSAGE_ID : taskAnchor(focus.task);
  const ready = Boolean(data);
  useEffect(() => {
    if (!target || !ready) return;
    const el = document.getElementById(target);
    if (el instanceof HTMLDetailsElement) el.open = true;
    el?.querySelector<HTMLDetailsElement>("details")?.setAttribute("open", "");
    el?.scrollIntoView?.({ block: "start" });
    (el instanceof HTMLDetailsElement ? el.querySelector("summary") : el)?.focus();
  }, [target, ready]);

  return (
    <div className="space-y-3">
      <div>
        <ScreenHeading>{t("handover.title")}</ScreenHeading>
        <p className="mt-1 max-w-measure text-lg text-muted">{t("handover.intro")}</p>
        {/* Handover notes and task statuses go into the report: a short way there. */}
        {onOpenReport && (
          <button type="button" id="handover-report" onClick={onOpenReport} className={`mt-1 ${quietButton} px-0`}>
            {t("handover.createReport")}
          </button>
        )}
        {data && (
          <div className="mt-1">
            <Storage data={data} />
          </div>
        )}
      </div>

      {data && (
        <>
          {/* Keyed by the open tasks, so the choice resets when they change. */}
          <HostMessage key={askable(data).map((task) => task.id).join(" ")} data={data} />
          <Tasks data={data} />
        </>
      )}
    </div>
  );
}

/** What's kept and where, or why the last change wasn't saved. */
function Storage({ data }: { data: HandoverState }) {
  const { t } = useTranslation();
  if (data.storage === "not_saved") {
    return <Notice title={t("handover.notSavedTitle", { reason: data.storage_reason ?? "" })} />;
  }
  return <Hint>{t("handover.saved")}</Hint>;
}

/** "Draft message to host": tick the open tasks to include, edit the text, copy it. RoomCheck
 * never sends it. Edits are kept when the choice changes; "Rewrite from the tasks you chose"
 * replaces them only when asked. */
function HostMessage({ data }: { data: HandoverState }) {
  const { t } = useTranslation();
  const id = useId();
  const open = askable(data);
  const [chosen, setChosen] = useState<string[]>(() => open.map((task) => task.id));
  const [edited, setEdited] = useState<string | null>(null);
  const [copy, setCopy] = useState<"copied" | "failed" | null>(null);
  const picked = open.filter((task) => chosen.includes(task.id));
  const generated = messageFor(picked, data, t);
  const text = edited ?? generated;
  const stale = edited !== null && edited !== generated;
  const note = data.message?.note ?? t("handover.message.note");

  async function copyText() {
    try {
      await navigator.clipboard.writeText(text);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  }

  return (
    <details id={MESSAGE_ID} className="group scroll-mt-3 rounded-card border border-line bg-surface shadow-soft">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-card px-3 py-2 transition-colors hover:bg-raised">
        <span>
          <span className="block text-lg font-semibold">{t("handover.message.title")}</span>
          <span className="block text-sm text-muted">
            {open.length === 0 ? t("handover.message.noneShort") : t("handover.message.summary", { count: open.length })}
          </span>
        </span>
        <span className="text-muted">
          <ChevronIcon />
        </span>
      </summary>
      <div className="px-3 pb-3">
        {open.length === 0 ? (
          <p className="text-muted">{t("report.noMessage")}</p>
        ) : (
          <>
            <fieldset>
              <legend className="font-semibold">{t("handover.message.choose")}</legend>
              {open.map((task) => (
                <Checkbox
                  key={task.id}
                  label={task.title}
                  checked={chosen.includes(task.id)}
                  onChange={(on) => {
                    setChosen((c) => (on ? [...c, task.id] : c.filter((x) => x !== task.id)));
                    setCopy(null);
                  }}
                />
              ))}
            </fieldset>
            <div className="mt-2 max-w-form">
              <label htmlFor={`${id}-text`} className="block font-semibold">
                {t("report.messageLabel")}
              </label>
              <textarea
                id={`${id}-text`}
                value={text}
                // Tall enough for the whole message, so nothing is hidden below the fold.
                rows={Math.max(7, text.split("\n").length + 2)}
                aria-describedby={`${id}-note`}
                onChange={(e) => {
                  setEdited(e.target.value);
                  setCopy(null);
                }}
                className={inputClass}
              />
              <p id={`${id}-note`} className="text-sm text-muted">
                {note}
              </p>
            </div>
            {stale && (
              <p className="mt-1 flex flex-wrap items-center gap-x-1 text-sm">
                {t("handover.message.edited")}
                <button type="button" onClick={() => setEdited(null)} className="font-semibold text-accent underline underline-offset-4 hover:text-accent-hover">
                  {t("handover.message.rewrite")}
                </button>
              </p>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
              <button
                type="button"
                aria-disabled={text.trim() === ""}
                onClick={() => text.trim() !== "" && void copyText()}
                className={secondaryButton}
              >
                {t("report.copy")}
              </button>
              <p aria-live="polite" className="text-sm">
                {copy === "copied" ? t("report.copied") : copy === "failed" ? t("report.copyFailed") : picked.length === 0 && edited === null ? t("handover.message.pickOne") : ""}
              </p>
            </div>
          </>
        )}
      </div>
    </details>
  );
}

/** "N open · N resolved", the Open / Resolved filters, and the cards. A filter is applied when
 * chosen: a card whose status you then change stays in view (with its Undo) until you filter
 * again. Cards that are filtered out are hidden, not removed, so nothing typed is lost. */
function Tasks({ data }: { data: HandoverState }) {
  const { t } = useTranslation();
  const tasks = data.tasks;
  const openCount = tasks.filter(isOpen).length;
  const resolvedCount = tasks.filter((task) => task.status === "resolved").length;
  const [filter, setFilter] = useState<{ kind: Filter; ids: Set<string> | null }>({ kind: "all", ids: null });
  const choose = (kind: Filter) =>
    setFilter({
      kind,
      ids: kind === "all" ? null : new Set(tasks.filter((task) => (kind === "open" ? isOpen(task) : task.status === "resolved")).map((task) => task.id)),
    });
  const shown = useMemo(() => tasks.filter((task) => !filter.ids || filter.ids.has(task.id)), [tasks, filter]);
  const filters: { kind: Filter; label: string }[] = [
    { kind: "all", label: t("handover.filter.all", { count: tasks.length }) },
    { kind: "open", label: t("handover.filter.open", { count: openCount }) },
    { kind: "resolved", label: t("handover.filter.resolved", { count: resolvedCount }) },
  ];

  return (
    <section aria-labelledby="tasks-title" className="space-y-2">
      <div className="flex flex-wrap items-end justify-between gap-x-2 gap-y-1">
        <div>
          <h2 id="tasks-title" className="text-lg">
            {t("handover.tasksTitle", { count: tasks.length })}
          </h2>
          <p className="text-sm font-semibold text-muted tabular-nums">
            {t("handover.summary", { open: openCount, resolved: resolvedCount })}
          </p>
        </div>
        {tasks.length > 0 && (
          <div role="group" aria-label={t("handover.filter.label")} className="flex flex-wrap gap-1">
            {filters.map((f) => (
              <button
                key={f.kind}
                type="button"
                aria-pressed={filter.kind === f.kind}
                onClick={() => choose(f.kind)}
                className={`rounded-full px-1.5 py-0.5 text-sm font-semibold transition-colors ${chipClass(filter.kind === f.kind)}`}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {tasks.length === 0 && <p className="text-muted">{t("handover.none")}</p>}
      {tasks.length > 0 && shown.length === 0 && (
        <p className="text-muted">{filter.kind === "open" ? t("handover.filter.noneOpen") : t("handover.filter.noneResolved")}</p>
      )}
      {tasks.map((task) => (
        <TaskCard key={task.id} task={task} name={nameFor(task.subject, data)} hidden={!shown.includes(task)} />
      ))}
    </section>
  );
}

/** "Recheck this" once a task is Resolved or Host confirmed, where RoomCheck can see the fix;
 * the plain "can't check this" line where it never can; and every result so far. */
function RecheckPanel({ task }: { task: Task }) {
  const { t } = useTranslation();
  const recheck = useRecheck();
  const id = useId();
  const offer = task.recheck_offer ?? "none";
  // The status shows at once (optimistically), so judge from it rather than wait for the reply.
  const ready = (offer === "available" || offer === "needs_status") && (task.status === "resolved" || Boolean(task.host_confirmed));
  const error =
    recheck.error instanceof ApiError && recheck.error.detail ? recheck.error.detail : recheck.isError ? t("handover.recheckFailed") : null;
  const earlier = (task.rechecks ?? []).slice(0, -1);
  if (offer === "unobservable") {
    return (
      <p className="mt-1.5 flex items-start gap-1 text-sm text-muted">
        <span className="text-accent">
          <InfoIcon />
        </span>
        {t("handover.unobservable")}
      </p>
    );
  }
  if (!ready && !task.recheck) return null;
  return (
    <div className="mt-1.5 space-y-0.5">
      {ready && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <button
            type="button"
            disabled={recheck.isPending}
            aria-describedby={`${id}-hint`}
            onClick={() => recheck.mutate(task.id)}
            className={`${secondaryButton} disabled:cursor-wait disabled:opacity-80`}
          >
            {t("handover.recheck")}
          </button>
          <span id={`${id}-hint`} className="text-sm text-muted">
            {t("handover.recheckHint")}
          </span>
        </div>
      )}
      <p aria-live="polite" className="text-sm empty:hidden">
        {recheck.isPending ? (
          <span className="text-muted">{t("handover.rechecking")}</span>
        ) : error ? (
          error
        ) : task.recheck ? (
          t("handover.rechecked", { when: formatWhen(task.recheck.checked_at), text: task.recheck.text })
        ) : (
          ""
        )}
      </p>
      {earlier.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-semibold text-accent">{t("handover.earlierRechecks")}</summary>
          <ul className="mt-0.5 space-y-0.5 text-muted">
            {earlier.map((r) => (
              <li key={r.checked_at}>{t("handover.rechecked", { when: formatWhen(r.checked_at), text: r.text })}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** A compact card: title, priority, device, status and evidence. It opens for the question,
 * the steps, the status, the evidence and the notes. Closing it keeps everything typed. */
function TaskCard({ task, name, hidden }: { task: Task; name: string; hidden: boolean }) {
  const { t } = useTranslation();
  const update = useTaskUpdate();
  const id = useId();
  const failed = update.isError;
  // The status before the last change: a status can always be changed back.
  const [before, setBefore] = useState<{ status: TaskStatus; message: string } | null>(null);
  const clear = useCallback(() => setBefore(null), []);
  const setStatus = (s: TaskStatus) => {
    setBefore({ status: task.status, message: t("undo.status", { status: t(`handover.statusValue.${s}`) }) });
    update.mutate({ id: task.id, status: s });
  };
  const extra = stepsBeyondAsk(task.ask, task.steps);
  const topic = t(`handover.supportTopic.${task.rule_id}`, { defaultValue: "" });

  return (
    <article
      id={taskAnchor(task.id)}
      tabIndex={-1}
      hidden={hidden}
      aria-labelledby={`${id}-title`}
      // Compact: less padding than a full card, and the badges beside the title when there's room.
      className="scroll-mt-3 rounded-card border border-line bg-surface px-2 py-1.5 shadow-soft sm:px-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1">
        <div className="min-w-0">
          <h3 id={`${id}-title`} className="text-card font-semibold">
            {task.title}
          </h3>
          <p className="text-sm text-muted">
            {t("handover.fromFinding", { title: task.finding_title })}
            {name && ` · ${t("handover.yourName", { name })}`}
            {task.check_at && ` · ${t("handover.fromCheck", { when: formatWhen(task.check_at) })}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <SeverityBadge level={task.severity} />
          <StatusBadge status={task.status} />
          {/* Evidence, apart from the status: what the host said, and what RoomCheck saw. */}
          {task.host_confirmed && <EvidenceBadge>{t("handover.hostConfirmed")}</EvidenceBadge>}
          {task.observed && <EvidenceBadge>{t("handover.labelObserved")}</EvidenceBadge>}
        </div>
      </div>

      <details className="group mt-1">
        <summary className="inline-flex cursor-pointer list-none items-center gap-0.5 rounded-control font-semibold text-accent underline-offset-4 transition-colors hover:text-accent-hover hover:underline">
          {t("handover.details")}
          <ChevronIcon />
        </summary>
        <div className="mt-1.5">
          <dl className="space-y-1.5">
            <div>
              <dt className="font-semibold">{t("handover.who")}</dt>
              <dd>{t(`handover.whoValue.${task.who}`)}</dd>
            </div>
            {/* The question and the steps, without saying the same thing twice. */}
            <div>
              <dt className="font-semibold">{t("handover.ask")}</dt>
              <dd className="max-w-measure">{task.ask}</dd>
              {extra.length > 0 && (
                <dd className="mt-0.5">
                  <Bullets items={extra} />
                </dd>
              )}
            </div>
            {/* Not required by the finding: apart from the steps, each with its own reason. */}
            {(task.optional ?? []).length > 0 && (
              <div>
                <dt className="font-semibold">{t("handover.optionalTitle")}</dt>
                {(task.optional ?? []).map((o) => (
                  <dd key={o.text} className="mt-0.5">
                    {o.text} <span className="text-sm text-muted">{t("handover.optionalReason", { reason: o.reason })}</span>
                  </dd>
                ))}
              </div>
            )}
          </dl>

          {task.support && (
            <p className="mt-1 text-sm">
              <a
                href={task.support.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-describedby={`${id}-support`}
                className="text-accent underline underline-offset-2 transition-colors hover:text-accent-hover"
              >
                {topic ? t("handover.supportOn", { topic, name: task.support.name }) : t("handover.support", { name: task.support.name })}
              </a>{" "}
              <span id={`${id}-support`} className="text-muted">
                {t("handover.supportHint")}
              </span>
            </p>
          )}

          <fieldset className="mt-2">
            <legend className="font-semibold">{t("handover.status")}</legend>
            <div className="mt-0.5 flex flex-wrap gap-1">
              {STATUSES.map((s) => (
                <label key={s} className={choicePillClass(task.status === s)}>
                  <input
                    type="radio"
                    name={`status-${task.id}`}
                    value={s}
                    checked={task.status === s}
                    onChange={() => setStatus(s)}
                    className="size-2 accent-accent"
                  />
                  {t(`handover.statusValue.${s}`)}
                </label>
              ))}
            </div>
          </fieldset>
          <p className="mt-0.5 text-sm text-muted">
            {task.changed_at ? t("handover.changed", { when: formatWhen(task.changed_at) }) : t("handover.notChanged")}
          </p>
          {/* Straight after the status, so it's the next stop for the keyboard. */}
          <Undo
            message={before?.message ?? null}
            onUndo={() => {
              if (!before) return;
              update.mutate({ id: task.id, status: before.status });
              setBefore(null);
            }}
            onExpire={clear}
          />

          <fieldset className="mt-1.5">
            <legend className="font-semibold">{t("handover.evidence")}</legend>
            <Checkbox
              label={t("handover.hostConfirmed")}
              hint={t("handover.hostConfirmedHint")}
              checked={Boolean(task.host_confirmed)}
              onChange={(on) => update.mutate({ id: task.id, host_confirmed: on })}
            />
            <ul className="mt-0.5 space-y-0.5 text-sm text-muted">
              {task.host_confirmed && task.host_confirmed_at && (
                <li>{t("handover.hostConfirmedAt", { when: formatWhen(task.host_confirmed_at) })}</li>
              )}
              {task.observed && task.observed_at && <li>{t("handover.observedAt", { when: formatWhen(task.observed_at) })}</li>}
            </ul>
          </fieldset>
          <RecheckPanel task={task} />

          <Notes task={task} />
        </div>
      </details>
      {failed && (
        <div className="mt-1">
          <Notice title={t("handover.updateFailed")} />
        </div>
      )}
    </article>
  );
}

/** Notes save themselves once typing stops, and say whether they were saved. */
function Notes({ task }: { task: Task }) {
  const { t } = useTranslation();
  const update = useTaskUpdate();
  const [notes, setNotes] = useState(task.notes);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [reason, setReason] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const id = useId();
  useEffect(() => () => clearTimeout(timer.current), []);

  function save(text: string) {
    setState("saving");
    update.mutate(
      { id: task.id, notes: text },
      {
        onSuccess: (next) => {
          // Saved to the backend, but the backend couldn't write it to disk: say why.
          setReason(next.storage === "not_saved" ? (next.storage_reason ?? t("handover.updateFailed")) : null);
          setState(next.storage === "not_saved" ? "failed" : "saved");
        },
        onError: (e) => {
          setReason(e instanceof ApiError && e.detail ? e.detail : t("handover.updateFailed"));
          setState("failed");
        },
      },
    );
  }

  return (
    <div className="mt-2 max-w-form">
      <label htmlFor={`${id}-notes`} className="block font-semibold">
        {t("handover.notes")}
      </label>
      <p id={`${id}-hint`} className="text-sm text-muted">
        {t("handover.notesHint")}
      </p>
      <textarea
        id={`${id}-notes`}
        value={notes}
        rows={3}
        maxLength={2000}
        aria-describedby={`${id}-hint ${id}-status`}
        onChange={(e) => {
          const text = e.target.value;
          setNotes(text);
          setState("idle");
          clearTimeout(timer.current);
          timer.current = setTimeout(() => save(text), AUTOSAVE_MS);
        }}
        className={inputClass}
      />
      <p id={`${id}-status`} aria-live="polite" className="text-sm empty:hidden">
        {state === "saving" ? (
          <span className="text-muted">{t("handover.notesSaving")}</span>
        ) : state === "saved" ? (
          <span className="text-muted">{t("handover.notesSavedLocal")}</span>
        ) : state === "failed" ? (
          <span className="font-semibold">{t("handover.notesNotSaved", { reason })}</span>
        ) : (
          ""
        )}
      </p>
    </div>
  );
}
