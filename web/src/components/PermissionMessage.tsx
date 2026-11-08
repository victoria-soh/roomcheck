import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Textarea } from "../ds/Fields";
import { ChevronIcon } from "./icons";
import { secondaryButton } from "./styles";

/** A message the user edits, copies and sends themselves: RoomCheck never sends anything.
 * Closed, it's one line; the message is only in the page while it's open, so a closed panel
 * adds a single tab stop. */
export function CopyMessage({
  id,
  title,
  intro,
  message,
  note,
  open = false,
}: {
  id: string;
  title: string;
  intro: string;
  message: string;
  note: string;
  open?: boolean;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState(message);
  const [copy, setCopy] = useState<"copied" | "failed" | null>(null);
  const [shown, setShown] = useState(open);

  async function copyText() {
    try {
      await navigator.clipboard.writeText(text);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  }

  return (
    <details id={id} open={shown} onToggle={(e) => setShown(e.currentTarget.open)} className="group rounded-inner border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-inner px-1.5 py-1 font-semibold transition-colors hover:bg-canvas">
        {title}
        <span className="text-muted">
          <ChevronIcon />
        </span>
      </summary>
      {shown && (
        <div className="px-1.5 pb-1.5">
          <p className="max-w-measure text-sm">{intro}</p>
          <div className="mt-1 max-w-form">
            <Textarea
              label={t("report.messageLabel")}
              hint={note}
              value={text}
              rows={Math.max(7, text.split("\n").length + 2)}
              onChange={(e) => {
                setText(e.target.value);
                setCopy(null);
              }}
            />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            <button type="button" aria-disabled={text.trim() === ""} onClick={() => text.trim() !== "" && void copyText()} className={secondaryButton}>
              {t("report.copy")}
            </button>
            <p aria-live="polite" className="text-sm">
              {copy === "copied" ? t("report.copied") : copy === "failed" ? t("report.copyFailed") : ""}
            </p>
          </div>
        </div>
      )}
    </details>
  );
}

/** "Ask your host for permission": a message asking to check the devices on the network, so
 * the user can get it in writing. */
export function PermissionMessage({ open = false }: { open?: boolean }) {
  const { t } = useTranslation();
  return (
    <CopyMessage
      id="ask-permission"
      title={t("permission.title")}
      intro={t("permission.intro")}
      message={t("permission.message")}
      note={t("permission.note")}
      open={open}
    />
  );
}

/** "Draft a report to the platform": for a camera inside a short-stay listing. */
export function PlatformReport({ id, open = false }: { id: string; open?: boolean }) {
  const { t } = useTranslation();
  return (
    <CopyMessage
      id={id}
      title={t("results.draftPlatform")}
      intro={t("platformReport.intro")}
      message={t("platformReport.message")}
      note={t("platformReport.note")}
      open={open}
    />
  );
}
