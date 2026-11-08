import { useTranslation } from "react-i18next";

import type { RoomSummary } from "../api/types";
import { InfoIcon } from "./icons";

/** Always shown, whatever was found: what these checks can never see, and what didn't run. */
export function CantSee({ summary }: { summary: RoomSummary }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="cant-see-title" className="rounded-card border border-line bg-raised p-3 sm:p-4">
      <div className="flex items-center gap-1.5">
        <span className="text-accent">
          <InfoIcon />
        </span>
        <h2 id="cant-see-title" className="text-lg">
          {t("results.cantSee.title")}
        </h2>
      </div>
      <Bullets items={summary.cant_see} />
      {summary.not_checked.length > 0 && (
        <>
          <h3 className="mt-3 font-semibold">{t("results.cantSee.notChecked")}</h3>
          <Bullets items={summary.not_checked} />
        </>
      )}
    </section>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="mt-1.5 space-y-1 text-muted">
      {items.map((line) => (
        <li key={line} className="flex gap-1.5">
          <span aria-hidden="true" className="mt-1 size-0.75 shrink-0 rounded-full bg-muted" />
          <span>{line}</span>
        </li>
      ))}
    </ul>
  );
}
