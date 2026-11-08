import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type MouseEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { getSetup } from "../api/client";
import { DeleteAllData } from "../components/DeleteAllData";
import { DeleteMoveInScan } from "../components/DeleteMoveInScan";
import { OutsideCalls } from "../components/OutsideCalls";
import { ScreenHeading } from "../components/ScreenHeading";
import { Bullets } from "../components/ui";
import { BackIcon, ChevronIcon } from "../components/icons";
import { Button } from "../ds/Button";
import { BADGE } from "../ds/classes";
import { Card } from "../ds/Fields";
import { SETUP_KEY } from "../handover/keys";

/** The rows of "How RoomCheck works", each collapsed until opened (or linked to). */
const ROWS = ["help-checks", "help-cant", "help-priority", "help-permission"] as const;
type RowId = (typeof ROWS)[number];
const isRow = (id: string | undefined): id is RowId => (ROWS as readonly string[]).includes(id ?? "");

/** The jump links, in page order: each goes to a card's heading. */
const JUMPS = [
  ["camera", "help-camera"],
  ["how", "help-how"],
  ["sent", "help-online"],
  ["data", "help-data"],
] as const;

const link = "font-semibold text-accent underline underline-offset-4 hover:text-accent-hover";

function goTo(id: string) {
  const el = document.getElementById(id);
  el?.scrollIntoView?.({ block: "start" });
  // A row: focus its summary, so Enter closes it again. A card: its heading.
  (el?.tagName === "DETAILS" ? el.querySelector("summary") : el)?.focus();
}

/** Help, one column of four cards: if you find a hidden camera; how RoomCheck works; what's
 * sent; your data (what it keeps on this laptop, and how to delete it). Links from elsewhere
 * (`section`) land on a card's heading, or open and focus one row of "How RoomCheck works". */
export function Help({ back, section }: { back?: { label: string; onBack: () => void }; section?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<ReadonlySet<RowId>>(() => new Set(isRow(section) ? [section] : []));
  // Opened at one section (e.g. from Results' "Fixed rules set every priority"): its row is
  // open from the first render (and when a new link lands here while Help is showing)...
  const [landed, setLanded] = useState(section);
  if (section !== landed) {
    setLanded(section);
    if (isRow(section)) setOpen((rows) => new Set(rows).add(section));
  }
  // ...then it is scrolled to and focused, after the page title has taken focus.
  useEffect(() => {
    if (section) goTo(section);
  }, [section]);
  const toggle = (id: RowId, isOpen: boolean) =>
    setOpen((rows) => {
      if (rows.has(id) === isOpen) return rows;
      const next = new Set(rows);
      if (isOpen) next.add(id);
      else next.delete(id);
      return next;
    });
  const jump = (id: string) => (e: MouseEvent) => {
    e.preventDefault();
    goTo(id);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <ScreenHeading>{t("help.title")}</ScreenHeading>
        <p className="max-w-measure text-lg text-muted">{t("help.intro")}</p>
        <nav aria-label={t("help.jump.label")}>
          <ul className="flex flex-wrap gap-x-1 gap-y-0.5">
            {JUMPS.map(([k, id], i) => (
              <li key={k} className="flex items-center gap-1">
                <a href={`#${id}`} onClick={jump(id)} className={link}>
                  {t(`help.jump.${k}`)}
                </a>
                {/* After each link, so a wrapped line never starts with a dot. */}
                {i < JUMPS.length - 1 && (
                  <span aria-hidden="true" className="text-muted">
                    ·
                  </span>
                )}
              </li>
            ))}
          </ul>
        </nav>
        {/* Back to Handover or Report, as you left it: nothing chosen or typed is lost. */}
        {back && (
          <Button variant="text" size="sm" icon={<BackIcon />} onClick={back.onBack} className="px-0">
            {back.label}
          </Button>
        )}
      </div>

      {/* The same steps as the camera card's expander (rules.yaml R-CAM guidance). */}
      <Card labelledBy="help-camera" className="border-l-4 border-l-sev-medium">
        <h2 id="help-camera" tabIndex={-1} className="text-lg focus:outline-none">
          {t("help.cameraTitle")}
        </h2>
        <div className="mt-1">
          <Bullets items={(["touch", "leave", "report"] as const).map((k) => t(`help.camera.${k}`))} />
        </div>
        <p className="mt-1 max-w-measure text-sm text-muted">{t("help.camera.note")}</p>
      </Card>

      <Card labelledBy="help-how">
        <h2 id="help-how" tabIndex={-1} className="text-lg focus:outline-none">
          {t("help.howTitle")}
        </h2>
        <div className="mt-1">
          <Row id="help-checks" title={t("help.checksTitle")} open={open.has("help-checks")} onToggle={toggle}>
            <Bullets items={(["devices", "router", "nearby"] as const).map((k) => t(`start.checks.${k}`))} />
          </Row>
          <Row id="help-cant" title={t("help.cantTitle")} open={open.has("help-cant")} onToggle={toggle}>
            <Bullets
              items={[t("start.trust.limitation"), ...(["offline", "where", "login"] as const).map((k) => t(`start.trust.cant.${k}`))]}
            />
          </Row>
          <Row id="help-priority" title={t("help.priorityTitle")} open={open.has("help-priority")} onToggle={toggle}>
            <Bullets items={(["fixed", "levels", "ai"] as const).map((k) => t(`help.priority.${k}`))} />
          </Row>
          <Row id="help-permission" title={t("help.permissionTitle")} open={open.has("help-permission")} onToggle={toggle}>
            <Bullets
              items={[
                `${t("start.permission.whatCountsBody.own")} ${t("start.permission.whatCountsBody.said")}`,
                t("start.permission.legal"),
                t("start.permission.whatCountsBody.advice"),
              ]}
            />
          </Row>
        </div>
      </Card>

      <WhatsSent />

      <Card labelledBy="help-data">
        <h2 id="help-data" tabIndex={-1} className="text-lg focus:outline-none">
          {t("help.dataTitle")}
        </h2>
        <h3 className="mt-1 text-card">{t("help.savedTitle")}</h3>
        <Bullets items={(["baseline", "tasks", "answers", "key"] as const).map((k) => t(`help.saved.${k}`))} />
        <p className="mt-1 max-w-measure">{t("help.where")}</p>
        <h3 className="mt-2 text-card">{t("help.reportsTitle")}</h3>
        <p className="max-w-measure">{t("help.reports")}</p>
        <h3 id="help-delete" tabIndex={-1} className="mt-2 mb-1 text-card focus:outline-none">
          {t("help.deleteTitle")}
        </h3>
        <div className="space-y-1">
          <DeleteMoveInScan />
          <DeleteAllData />
        </div>
      </Card>
    </div>
  );
}

/** One collapsed row of "How RoomCheck works": a native details/summary, opened by a click,
 * Enter or Space, or by a link that lands on it. */
function Row({
  id,
  title,
  open,
  onToggle,
  children,
}: {
  id: RowId;
  title: string;
  open: boolean;
  onToggle: (id: RowId, open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <details id={id} open={open} onToggle={(e) => onToggle(id, e.currentTarget.open)} className="group border-t border-line first:border-t-0">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-control py-1.5 transition-colors hover:text-accent-hover">
        <h3 className="text-card">{title}</h3>
        <span className="text-muted transition-transform group-open:rotate-180">
          <ChevronIcon />
        </span>
      </summary>
      <div className="pb-2">{children}</div>
    </details>
  );
}

/** What goes out, and whether AI is on in this setup (from this build's real configuration). */
function WhatsSent() {
  const { t } = useTranslation();
  const setup = useQuery({ queryKey: SETUP_KEY, queryFn: getSetup, retry: false }).data;
  return (
    <Card labelledBy="help-online">
      <div className="flex flex-wrap items-center justify-between gap-1">
        <h2 id="help-online" tabIndex={-1} className="text-lg focus:outline-none">
          {t("help.onlineTitle")}
        </h2>
        {setup && <span className={BADGE.status}>{setup.outside.ai ? t("privacy.aiOn") : t("privacy.aiOff")}</span>}
      </div>
      <div className="mt-1 max-w-measure">
        <OutsideCalls />
        <p className="mt-1 text-sm text-muted">{t("start.trust.networkName")}</p>
      </div>
    </Card>
  );
}
