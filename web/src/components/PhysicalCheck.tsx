import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { finishPhysical, setPhysicalItem } from "../api/client";
import { PHYSICAL_ITEMS, type HandoverState, type PhysicalCheck as Check, type PhysicalItemId } from "../api/types";
import { Button } from "../ds/Button";
import { Checkbox, Textarea } from "../ds/Fields";
import { formatWhen } from "../format";
import { HANDOVER_KEY } from "../handover/keys";
import { useHandover } from "../handover/useHandover";
import { ChevronIcon } from "./icons";
import { Notice } from "./ui";

const EMPTY: Check = { items: {}, done_at: null };

/** "Do a 3-minute physical check": places to look with your own eyes and a phone torch, each
 * with a tick box and an optional note. Saved on this laptop, encrypted, like the other
 * answers, and listed in the report. It never says the room is clear: the ending only asks the
 * user to note anything they weren't sure about. */
/** Opened from a card: that device's places first, and its "Where is it?" question. */
export interface PhysicalFocus {
  label: string; // e.g. "camera-like device"
  order: PhysicalItemId[];
  where?: ReactNode;
}

export function PhysicalCheck({ open = false, focus }: { open?: boolean; focus?: PhysicalFocus | null }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const data = useHandover().data;
  const check = data?.physical ?? EMPTY;
  const looked = PHYSICAL_ITEMS.filter((i) => check.items[i]?.looked).length;
  const save = (state: HandoverState) => client.setQueryData(HANDOVER_KEY, state);
  const item = useMutation({
    mutationFn: ({ name, change }: { name: PhysicalItemId; change: { looked?: boolean; note?: string } }) => setPhysicalItem(name, change),
    onSuccess: save,
  });
  const done = useMutation({ mutationFn: finishPhysical, onSuccess: save });
  const failed = item.isError || done.isError;

  return (
    <details id="physical-check" open={open} className="group rounded-card border border-line bg-surface shadow-soft">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-card px-3 py-2 transition-colors hover:bg-canvas">
        <span>
          <h2 className="text-lg">{t("physical.offer")}</h2>
          <span className="block text-sm text-muted">
            {check.done_at ? t("physical.doneOn", { when: formatWhen(check.done_at) }) : t("physical.offerBody")}
          </span>
        </span>
        <span className="text-muted">
          <ChevronIcon />
        </span>
      </summary>
      <div className="px-3 pb-3">
        <p className="max-w-measure">{t("physical.intro")}</p>
        {focus && (
          <div className="mt-1 rounded-inner bg-raised p-1.5">
            <p className="font-semibold">{t("physical.focusIntro", { label: focus.label })}</p>
            {focus.where}
          </div>
        )}
        <ul className="mt-1.5 space-y-1.5">
          {ordered(focus?.order).map((name) => (
            <PhysicalItem
              key={name}
              name={name}
              looked={check.items[name]?.looked ?? false}
              note={check.items[name]?.note ?? ""}
              onLooked={(on) => item.mutate({ name, change: { looked: on } })}
              onNote={(note) => item.mutate({ name, change: { note } })}
            />
          ))}
        </ul>
        <p aria-live="polite" className="mt-1.5 text-sm text-muted">
          {t("physical.progress", { looked, total: PHYSICAL_ITEMS.length })}
        </p>
        {failed && (
          <div className="mt-1">
            <Notice title={t("physical.notSaved", { reason: data?.storage_reason ?? t("baseline.saveFailed") })} />
          </div>
        )}
        {check.done_at ? (
          <div className="mt-1.5 space-y-1">
            <p className="font-semibold">{t("physical.doneText")}</p>
            <Button variant="text" size="sm" className="px-0" onClick={() => done.mutate(false)}>
              {t("physical.change")}
            </Button>
          </div>
        ) : (
          <Button variant="secondary" className="mt-1.5" loading={done.isPending} onClick={() => done.mutate(true)}>
            {t("physical.done")}
          </Button>
        )}
      </div>
    </details>
  );
}

/** The device type's places first, then the rest in the usual order. */
function ordered(first: PhysicalItemId[] | undefined): PhysicalItemId[] {
  if (!first) return [...PHYSICAL_ITEMS];
  return [...first, ...PHYSICAL_ITEMS.filter((i) => !first.includes(i))];
}

function PhysicalItem({
  name,
  looked,
  note,
  onLooked,
  onNote,
}: {
  name: PhysicalItemId;
  looked: boolean;
  note: string;
  onLooked: (on: boolean) => void;
  onNote: (note: string) => void;
}) {
  const { t } = useTranslation();
  // The note is saved when the box loses focus, so typing doesn't send a request per key.
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <li className="rounded-inner border border-line px-1.5 py-1">
      <Checkbox label={t(`physical.items.${name}`)} hint={t(`physical.hints.${name}`)} checked={looked} onChange={onLooked} />
      {/* The note box appears once the place is ticked (or already has a note). */}
      {(looked || note !== "" || draft !== null) && (
        <Textarea
          label={t("physical.note")}
          rows={1}
          maxLength={200}
          value={draft ?? note}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            if (draft !== null && draft !== note) onNote(draft);
            setDraft(null);
          }}
        />
      )}
    </li>
  );
}
