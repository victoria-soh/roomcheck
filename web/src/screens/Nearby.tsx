import { useId, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { DiscoveryResult, NearbyItem } from "../api/types";
import { FindingCard } from "../components/FindingCard";
import { NEARBY_CHECKS } from "../components/links";
import { ChevronIcon } from "../components/icons";
import { CheckRows } from "../components/NetworkHealth";
import { ScreenHeading } from "../components/ScreenHeading";
import { quietButton, secondaryButton } from "../components/styles";
import { Bullets, Hint, Notice } from "../components/ui";
import { EmptyState } from "../ds/Feedback";
import {
  isMine,
  useHandover,
  useRecognitionProps,
} from "../handover/useHandover";
import { onResults } from "../results/summary";

/** Screen 4. Wi-Fi and Bluetooth findings (moved here from Results), each with "Locate signal",
 * a one-line count of what else was heard (and discarded), and compact coverage and limits. */
export function Nearby({
  result,
  onFind,
}: {
  result: DiscoveryResult;
  onFind: (item: NearbyItem) => void;
}) {
  const { t } = useTranslation();
  const handover = useHandover().data;
  const recognition = useRecognitionProps();
  // Only signals that aren't your own network: findings about its router are on Results.
  const all = result.findings.filter((f) => !onResults(f));
  const findings = all.filter((f) => !isMine(f, handover));
  const yours = all.filter((f) => isMine(f, handover));
  const explanations = result.explanations?.items ?? [];
  const heard = result.nearby_heard ?? null;
  const ran = heard !== null;

  const coverageRef = useRef<HTMLDetailsElement>(null);
  const nearbyChecks = result.checks.filter((c) => c.name in NEARBY_CHECKS);
  const checked = nearbyChecks.filter((c) => c.status === "ran").length;
  const nothingFlagged = ran && findings.length === 0;
  function openCoverage() {
    const el = coverageRef.current;
    if (!el) return;
    el.open = true;
    el.scrollIntoView?.({ block: "start" });
    el.querySelector("summary")?.focus();
  }

  return (
    <div className="space-y-3">
      <div>
        <ScreenHeading>{t("nearby.title")}</ScreenHeading>
        <p className="mt-1 max-w-measure text-lg text-muted">
          {t("nearby.intro")}
        </p>
        {result.room_network && (
          <p className="mt-0.5 text-sm text-muted">
            {t("nearby.comparedWith", { name: result.room_network })}
          </p>
        )}
      </div>

      {!ran && <Notice title={t("nearby.notRun")} />}

      <section aria-labelledby="nearby-flagged" className="space-y-2">
        <h2 id="nearby-flagged" className="text-lg">
          {t("nearby.flaggedTitle")} ({findings.length})
        </h2>
        {nothingFlagged && (
          <EmptyState title={t("nearby.emptyTitle")}>
            <span className="block">{t("nearby.emptyBody")}</span>
            <button
              type="button"
              onClick={openCoverage}
              className={`mt-1 ${quietButton} px-0`}
            >
              {t("nearby.emptyCoverage")}
            </button>
          </EmptyState>
        )}
        {findings.map((f) => {
          const item = result.nearby_items.find((i) => i.ref === f.nearby_ref);
          return (
            <FindingCard
              key={f.id}
              finding={f}
              nearby={item}
              explanation={explanations.find((e) => e.finding_id === f.id)}
              recognition={recognition(f)}
              action={
                item ? (
                  <FindIt item={item} onFind={onFind} />
                ) : (
                  <Hint>{t("nearby.notLocatable")}</Hint>
                )
              }
            />
          );
        })}
      </section>

      {yours.length > 0 && (
        <section aria-labelledby="nearby-yours" className="space-y-2">
          <h2 id="nearby-yours" className="text-lg">
            {t("recognise.yoursTitle", { count: yours.length })}
          </h2>
          <p className="text-muted">{t("recognise.yoursIntro")}</p>
          {yours.map((f) => {
            const item = result.nearby_items.find(
              (i) => i.ref === f.nearby_ref,
            );
            return (
              <FindingCard
                key={f.id}
                finding={f}
                nearby={item}
                explanation={explanations.find((e) => e.finding_id === f.id)}
                recognition={recognition(f)}
                action={
                  item ? <FindIt item={item} onFind={onFind} /> : undefined
                }
              />
            );
          })}
        </section>
      )}

      {/* What else was heard: one small line; nothing about these signals was kept. */}
      {heard && (
        <div>
          <p className="text-sm font-semibold tabular-nums">
            {t("nearby.otherSignals", {
              wifi: t("nearby.heardWifi", { count: heard.wifi_access_points }),
              bluetooth: t("nearby.heardBluetooth", {
                count: heard.bluetooth_devices,
              }),
            })}
            {Object.keys(heard.bluetooth_by_category).length > 0 && (
              <span className="font-normal text-muted">
                {" "}
                (
                {Object.entries(heard.bluetooth_by_category)
                  .map(([what, n]) => `${n} ${what}`)
                  .join(", ")}
                )
              </span>
            )}
          </p>
          <p className="text-sm text-muted">{t("nearby.heardNote")}</p>
        </div>
      )}

      {/* Coverage and limits, compact; open from the start when nothing was flagged, so
          "Not detected" always comes with what was and wasn't checked. */}
      <details
        id="nearby-checks"
        ref={coverageRef}
        open={nothingFlagged || undefined}
        className="group rounded-card border border-line bg-surface shadow-soft"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-card px-3 py-1.5 transition-colors hover:bg-raised">
          <span>
            <span className="block font-semibold">
              {t("nearby.coverageTitle")}
            </span>
            <span className="block text-sm text-muted">
              {t("results.coverage.summary", {
                checked,
                notChecked: nearbyChecks.length - checked,
              })}
            </span>
          </span>
          <span className="text-muted">
            <ChevronIcon />
          </span>
        </summary>
        <div className="px-3 pb-2">
          <p className="text-sm text-muted">{t("nearby.checksIntro")}</p>
          <CheckRows
            checks={result.checks}
            findings={all}
            rules={NEARBY_CHECKS}
          />
          <h3 className="mt-1.5 text-sm font-semibold">
            {t("nearby.limitsTitle")}
          </h3>
          <Bullets
            items={[
              t("nearby.scopeNote"),
              t("nearby.findItHint"),
              t("start.trust.cant.where"),
            ]}
          />
        </div>
      </details>
    </div>
  );
}

function FindIt({
  item,
  onFind,
}: {
  item: NearbyItem;
  onFind: (item: NearbyItem) => void;
}) {
  const { t } = useTranslation();
  const hintId = useId();
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <button
        type="button"
        aria-describedby={hintId}
        onClick={() => onFind(item)}
        className={secondaryButton}
      >
        {t("nearby.findIt")}
      </button>
      <span id={hintId} className="text-sm text-muted">
        {t("nearby.findItHint")}
      </span>
    </div>
  );
}
