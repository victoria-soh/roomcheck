import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { getCompare, saveBaseline, setMatch } from "../api/client";
import type { BaselineFinding, CompareItem, Comparison, DiscoveryResult, MatchDecision } from "../api/types";
import { ScreenHeading } from "../components/ScreenHeading";
import { SeverityBadge } from "../components/SeverityBadge";
import { card, primaryButton, unavailableButton } from "../components/styles";
import { ConfidenceBadge, SourceBadge } from "../ds/Badge";
import { Button } from "../ds/Button";
import { ScanContext } from "../ds/scanContext";
import { BADGE, choicePillClass } from "../ds/classes";
import { StatTile } from "../ds/Fields";
import { Bullets, Notice } from "../components/ui";
import { formatWhen } from "../format";
import { BASELINE_KEY, COMPARE_KEY, HANDOVER_KEY } from "../handover/keys";
import { nameFor, useHandover } from "../handover/useHandover";

/** Layer 6: this check against the starting point (the move-in scan), as New, Not seen this
 * time and Changed. When the two checks ran differently, it says so first, and it never
 * shows something it couldn't check as gone. */
export function Compare({
  result,
  onOpenHelp,
}: {
  result: DiscoveryResult | null;
  /** Deleting the move-in scan, or everything, lives in Help (Delete your data). */
  onOpenHelp?: (section: string) => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const compare = useQuery({ queryKey: COMPARE_KEY, queryFn: getCompare });
  const refresh = () => {
    for (const key of [BASELINE_KEY, COMPARE_KEY, HANDOVER_KEY]) void client.invalidateQueries({ queryKey: key });
  };
  const data = compare.data;
  // The header's context line names the check being compared (its date and how it ran).
  const compared = data?.state === "ready" ? data.comparison : null;
  const context =
    result && compared ? { ...result, finished_at: compared.scan_at, mode: compared.scan_mode ?? result.mode } : result;

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <ScanContext.Provider value={context}>
          <ScreenHeading>{t("compare.title")}</ScreenHeading>
        </ScanContext.Provider>
        <p className="text-lg text-muted">{t("compare.intro")}</p>
      </div>

      {data?.state === "unreadable" && <Notice title={data.baseline.message ?? ""} />}
      {(data?.state === "none" || data?.state === "unreadable") && (
        <StartCard result={result} replacing={data.state === "unreadable"} onSaved={refresh} />
      )}
      {data?.state === "no_check" && data.baseline.saved_at && (
        <section aria-labelledby="compare-since" className={card}>
          <h2 id="compare-since" className="text-lg">
            {t("compare.savedTitle", { when: formatWhen(data.baseline.saved_at) })}
          </h2>
          <p className="mt-0.5">{t("compare.runAnother")}</p>
        </section>
      )}
      {data?.state === "ready" && data.comparison && <Ready comparison={data.comparison} />}

      {onOpenHelp && (
        <Button variant="text" size="sm" onClick={() => onOpenHelp("help-delete")} className="px-0">
          {t("compare.manageData")}
        </Button>
      )}
    </div>
  );
}

/** The one empty-state card: what the latest check was, and saving it as the starting point. */
function StartCard({
  result,
  replacing,
  onSaved,
}: {
  result: DiscoveryResult | null;
  replacing: boolean;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const hint = useId();
  const save = useMutation({
    mutationFn: saveBaseline,
    onSuccess: (info) => {
      client.setQueryData(BASELINE_KEY, info);
      onSaved();
    },
  });
  const busy = save.isPending;
  const network = !result
    ? null
    : result.room_network
      ? result.room_network
      : result.network === null || result.network === undefined
        ? t("compare.networkUnknown")
        : t("compare.networkCable");
  return (
    <section aria-labelledby="compare-start" className={card}>
      <h2 id="compare-start" className="text-lg">
        {t("compare.startTitle")}
      </h2>
      <p id={hint} className="mt-0.5 text-muted">
        {t("compare.startBody")}
      </p>
      {result ? (
        <>
          <dl className="mt-1.5 space-y-0.5">
            <div>
              <dt className="inline font-semibold">{t("compare.latest")}: </dt>
              <dd className="inline">{t("compare.latestWhen", { when: formatWhen(result.finished_at) })}</dd>
            </div>
            <div>
              <dd>{t("compare.latestNetwork", { name: network })}</dd>
            </div>
            <div>
              <dd>{t(`compare.mode.${result.mode}`)}</dd>
            </div>
          </dl>
          <button
            type="button"
            aria-disabled={busy}
            aria-describedby={hint}
            onClick={() => !busy && save.mutate()}
            className={`mt-1.5 ${busy ? unavailableButton : primaryButton}`}
          >
            {busy ? t("baseline.saving") : replacing ? t("baseline.startNew") : t("baseline.save")}
          </button>
          <div aria-live="polite">
            {save.isError && (
              <div className="mt-1">
                <Notice title={t("baseline.saveFailed")} />
              </div>
            )}
          </div>
        </>
      ) : (
        <p className="mt-1.5">{t("compare.noCheckYet")}</p>
      )}
    </section>
  );
}

type Group = "new" | "changed" | "gone";

/** Move-in scan vs this check (when and how each ran), then New / Not seen this time /
 * Changed as filters. "Possibly the same device" pairs can be confirmed or rejected. */
function Ready({ comparison }: { comparison: Comparison }) {
  const { t } = useTranslation();
  const [only, setOnly] = useState<Group | null>(null);
  const groups: [Group, CompareItem[]][] = [
    ["new", comparison.new],
    ["gone", comparison.gone],
    ["changed", comparison.changed],
  ];
  const shown = groups.filter(([status]) => only === null || only === status);
  const possible = comparison.possible ?? [];
  const warnings = comparison.warnings ?? [];
  const varied = comparison.varied ?? [];
  const notChecked = comparison.not_checked ?? [];
  const mode = (m: "full" | "passive" | null | undefined) => (m ? t(`compare.mode.${m}`) : t("compare.modeUnknown"));
  return (
    <>
      {/* One plain note: differences a listening-only check can't see are already left out. */}
      {comparison.ran_differently && <Notice title={t("compare.ranDifferently")} />}
      {warnings.length > 0 && (
        <Notice title={t("compare.warningsTitle")}>
          <Bullets items={warnings} />
        </Notice>
      )}
      <section aria-labelledby="compare-since" className={`summary-glow ${card}`}>
        <h2 id="compare-since" className="text-lg font-semibold">
          {t("compare.versus")}
        </h2>
        <dl className="mt-1 grid gap-1 sm:grid-cols-2">
          <div className="rounded-inner border border-line bg-surface px-1.5 py-1">
            <dt className="text-sm font-semibold text-muted">{t("compare.reference")}</dt>
            <dd className="font-semibold">{formatWhen(comparison.baseline_saved_at)}</dd>
            <dd className="text-sm text-muted">{mode(comparison.baseline_mode)}</dd>
          </div>
          <div className="rounded-inner border border-line bg-surface px-1.5 py-1">
            <dt className="text-sm font-semibold text-muted">{t("compare.thisScan")}</dt>
            <dd className="font-semibold">{formatWhen(comparison.scan_at)}</dd>
            <dd className="text-sm text-muted">{mode(comparison.scan_mode)}</dd>
          </div>
        </dl>
        <h3 id="compare-filter" className="mt-2 text-sm font-semibold">
          {t("compare.filterLabel")}
        </h3>
        <ul aria-labelledby="compare-filter" className="mt-0.5 grid grid-cols-2 gap-1 sm:grid-cols-4">
          <li className="flex flex-col">
            <StatTile
              label={<span className="text-sm font-semibold">{t("compare.all")}</span>}
              value={<span className="text-xl leading-none font-semibold tabular-nums">{comparison.new.length + comparison.gone.length + comparison.changed.length}</span>}
              pressed={only === null}
              onClick={() => setOnly(null)}
            />
          </li>
          {groups.map(([status, items]) => (
            <li key={status} className="flex flex-col">
              <StatTile
                label={<span className="text-sm font-semibold">{t(`compare.status.${status}`)}</span>}
                value={<span className="text-xl leading-none font-semibold tabular-nums">{items.length}</span>}
                pressed={only === status}
                onClick={() => setOnly(only === status ? null : status)}
              />
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-sm">{t("compare.unchanged", { count: comparison.unchanged })}</p>
        {comparison.unchanged_possible > 0 && (
          <p className="text-sm text-muted">{t("compare.unchangedPossible", { count: comparison.unchanged_possible })}</p>
        )}
        {comparison.not_compared > 0 && (
          <p className="text-sm text-muted">{t("compare.notCompared", { count: comparison.not_compared })}</p>
        )}
      </section>

      {shown.map(([status, items]) => (
        <section key={status} aria-labelledby={`compare-${status}`} className="space-y-2">
          <h2 id={`compare-${status}`} className="text-lg">
            {t(`compare.${status}Title`, { count: items.length })}
          </h2>
          {status === "gone" && <p className="text-sm text-muted">{t("compare.goneNote")}</p>}
          {items.length === 0 && <p className="text-muted">{t("compare.nothingNew")}</p>}
          {items.map((item, i) => (
            <CompareCard key={`${status}-${item.match_id ?? i}`} item={item} />
          ))}
        </section>
      ))}

      {/* Unchanged pairs matched by name and services only: answer them here. */}
      {possible.length > 0 && (only === null || only === "changed") && (
        <section aria-labelledby="compare-possible" className="space-y-2">
          <h2 id="compare-possible" className="text-lg">
            {t("compare.possibleTitle", { count: possible.length })}
          </h2>
          <p className="text-sm text-muted">{t("compare.possibleIntro")}</p>
          {possible.map((item) => (
            <CompareCard key={item.match_id ?? item.label} item={item} />
          ))}
        </section>
      )}

      {/* Same device, but Likely in one check and Possible in the other: not a change. */}
      {varied.length > 0 && only === null && (
        <section aria-labelledby="compare-varied" className="space-y-2">
          <h2 id="compare-varied" className="text-lg">
            {t("compare.variedTitle", { count: varied.length })}
          </h2>
          <p className="text-sm text-muted">{t("compare.variedIntro")}</p>
          {varied.map((item, i) => (
            <CompareCard key={`varied-${item.subject ?? i}`} item={item} />
          ))}
        </section>
      )}

      {notChecked.length > 0 && (
        <section aria-labelledby="compare-not-checked" className="space-y-1">
          <h2 id="compare-not-checked" className="text-lg">
            {t("compare.notCheckedTitle")}
          </h2>
          <p className="text-sm text-muted">{t("compare.notCheckedIntro")}</p>
          <Bullets items={notChecked} />
        </section>
      )}
    </>
  );
}

/** "Is this the same device as at move-in?": Same, Different, or Not sure (no answer). Saved
 * like the other answers; it changes how Compare groups the two checks, never a finding. */
function MatchQuestion({ item }: { item: CompareItem }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const id = useId();
  const answer = useMutation({
    mutationFn: (decision: MatchDecision | null) => setMatch(item.match_id!, decision),
    onSuccess: (next) => client.setQueryData(COMPARE_KEY, next),
  });
  const current = answer.isPending ? (answer.variables ?? null) : (item.decision ?? null);
  const choices: [MatchDecision | null, string][] = [
    ["same", t("compare.match.same")],
    ["different", t("compare.match.different")],
    [null, t("compare.match.unsure")],
  ];
  return (
    <fieldset className="mt-1.5">
      <legend className="font-semibold">{t("compare.match.question")}</legend>
      <div className="mt-0.5 flex flex-wrap gap-1">
        {choices.map(([value, label]) => (
          <label key={label} className={choicePillClass(current === value)}>
            <input
              type="radio"
              name={`${id}-match`}
              checked={current === value}
              onChange={() => answer.mutate(value)}
              className="size-2 accent-accent"
            />
            {label}
          </label>
        ))}
      </div>
      <p aria-live="polite" className="mt-0.5 text-sm text-muted">
        {answer.isError ? t("compare.match.failed") : item.decision ? t(`compare.match.saved.${item.decision}`) : t("compare.match.hint")}
      </p>
    </fieldset>
  );
}

function CompareCard({ item }: { item: CompareItem }) {
  const { t } = useTranslation();
  const id = useId();
  const name = nameFor(item.subject, useHandover().data);
  return (
    <article aria-labelledby={`${id}-title`} className={card}>
      <div className="flex flex-wrap items-center gap-1">
        {item.status !== "unchanged" && <span className={BADGE.status}>{t(`compare.status.${item.status}`)}</span>}
        {item.kind === "nearby" && <SourceBadge source="nearby" />}
        {item.match === "possible" && (
          <span className={BADGE.confidence} aria-describedby={`${id}-possible`}>
            {t("compare.possible")}
          </span>
        )}
      </div>
      <h3 id={`${id}-title`} className="mt-1.5 text-lg">
        {item.label}
      </h3>
      <p className="mt-0.5 text-sm text-muted">
        {t(`compare.kind.${item.kind}`)}
        {item.maker ? ` · ${t("results.madeBy", { maker: item.maker })}` : ""}
        {name ? ` · ${t("compare.yourName", { name })}` : ""}
      </p>
      {item.match === "possible" && (
        <p id={`${id}-possible`} className="mt-0.5 text-sm text-muted">
          {t("compare.possibleHint")}
        </p>
      )}
      {item.identification_varied && item.band && (
        <p className="mt-1 flex flex-wrap items-center gap-1 text-sm">
          <ConfidenceBadge band={item.band} />
          <span className="text-muted">{t("compare.varied")}</span>
        </p>
      )}
      {item.match_id && <MatchQuestion item={item} />}
      {item.changes.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {item.changes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
      {item.findings.length > 0 && (
        <div className="mt-1.5">
          <h4 className="text-sm font-semibold">{t("compare.findings")}</h4>
          <ul className="mt-0.5 space-y-1">
            {findingRows(item.findings).map(({ finding: f, also }) => (
              <li key={f.rule_id} className="flex flex-wrap items-center gap-1">
                <SeverityBadge level={f.severity} />
                <span>{f.title}</span>
                {also && <span className="w-full text-sm text-muted">{t("compare.alsoRule", { title: also.title })}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

/** One row per finding, except that a new camera (R-NEW-CAMERA) and "Likely camera" (R-CAM) on
 * the same device are one row: the new-camera finding, with the other noted inside it. */
function findingRows(findings: BaselineFinding[]): { finding: BaselineFinding; also?: BaselineFinding }[] {
  const fresh = findings.find((f) => f.rule_id === "R-NEW-CAMERA");
  const cam = findings.find((f) => f.rule_id === "R-CAM");
  if (!fresh || !cam) return findings.map((finding) => ({ finding }));
  return findings.filter((f) => f !== cam).map((finding) => (finding === fresh ? { finding, also: cam } : { finding }));
}
