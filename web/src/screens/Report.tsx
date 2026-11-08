import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, createReport, getReportDefaults, getSetup, reportFileUrl, verifyReport } from "../api/client";
import type { DiscoveryResult, ReportResponse, ServiceOutcome } from "../api/types";
import { ScreenHeading } from "../components/ScreenHeading";
import { formatWhen } from "../format";
import { card, primaryButton } from "../components/styles";
import { Button } from "../ds/Button";
import { checkRows, pageCounts } from "../results/summary";
import { Hint, Notice } from "../components/ui";
import { Checkbox, TextInput } from "../ds/Fields";
import { REPORT_DEFAULTS_KEY, SETUP_KEY } from "../handover/keys";
import { useHandover } from "../handover/useHandover";

const fileLink = "font-semibold text-accent underline underline-offset-2 transition-colors hover:text-accent-hover";

/** Screen 6. Make the PDF of the latest check (the backend keeps it), preview it and check
 * its timestamp. Each outside service is its own choice, and afterwards each one says what
 * really happened. The landlord message is on the Handover page. */
export function Report({ result, onOpenHandover }: { result: DiscoveryResult; onOpenHandover: () => void }) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState<string | null>(null); // null: not touched yet
  const [ai, setAi] = useState(true);
  const [timestamp, setTimestamp] = useState(true);
  // What goes in the report: the network and device names are in, notes are out, by default.
  const [network, setNetwork] = useState(true);
  const [deviceNames, setDeviceNames] = useState(true);
  const [notes, setNotes] = useState(false);
  // AI explanations are offered only when this build has an API key.
  const setup = useQuery({ queryKey: SETUP_KEY, queryFn: getSetup, retry: false });
  const hasKey = setup.data?.outside.ai === true;
  const handover = useHandover().data;
  // The last room label used, offered again (saved encrypted with the handover data).
  const defaults = useQuery({ queryKey: REPORT_DEFAULTS_KEY, queryFn: getReportDefaults, retry: false });
  const lastLabel = defaults.data?.room_label ?? null;
  const label = typed ?? lastLabel ?? "";

  const make = useMutation({
    mutationFn: () =>
      createReport(
        {
          ai: hasKey && ai,
          timestamp,
          include_network_name: network,
          include_device_names: deviceNames,
          include_notes: notes,
        },
        label.trim() || null,
      ),
  });
  const report = make.data ?? null;
  const busy = make.isPending;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!busy) make.mutate();
  }

  const error = make.error
    ? make.error instanceof ApiError && make.error.detail
      ? make.error.detail
      : t("report.createFailed")
    : null;

  // Counted exactly as on Results (and in the PDF): things to look at per question, and the
  // checks that ran.
  const checks = checkRows(result);
  const notChecked = checks.filter((r) => r.state === "notChecked").length;
  const n = pageCounts(result);
  const perQuestion = n.perQuestion.map((q) => t(`results.questions.short.${q.id}`, { count: q.things })).join(" · ");
  const yesNo = (on: boolean) => (on ? t("report.summary.included") : t("report.summary.left"));
  const tasks = handover?.tasks.length ?? 0;

  return (
    <div className="space-y-3">
      <div>
        <ScreenHeading>{t("report.title")}</ScreenHeading>
        <p className="mt-1 max-w-measure text-lg text-muted">{t("report.intro")}</p>
      </div>

      {/* At 1024 px and wider, the choices on the left and "This report will contain" on the
          right; stacked on phones (choices, what it will contain, then the button). */}
      <form onSubmit={submit} aria-busy={busy} className={`grid gap-x-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] ${card}`}>
        <div className="lg:col-start-1">
        <TextInput
          label={t("report.roomLabel")}
          hint={lastLabel && label === lastLabel ? t("report.roomLabelLast") : t("report.roomLabelHint")}
          value={label}
          maxLength={60}
          onChange={(e) => setTyped(e.target.value)}
        />
        <fieldset className="mt-2">
          <legend className="font-semibold">{t("report.includeTitle")}</legend>
          <Checkbox label={t("report.includeNetwork")} hint={t("report.includeNetworkHint")} checked={network} onChange={setNetwork} />
          <Checkbox label={t("report.includeDevices")} hint={t("report.includeDevicesHint")} checked={deviceNames} onChange={setDeviceNames} />
          <Checkbox label={t("report.includeNotes")} hint={t("report.includeNotesHint")} checked={notes} onChange={setNotes} />
        </fieldset>
        <fieldset className="mt-2">
          <legend className="font-semibold">{t("report.servicesTitle")}</legend>
          {hasKey && (
            <Checkbox label={t("report.ai")} hint={t("report.aiHint")} checked={ai} onChange={setAi} />
          )}
          <Checkbox label={t("report.timestampChoice")} hint={t("report.timestampHint")} checked={timestamp} onChange={setTimestamp} />
        </fieldset>
        </div>

        {/* What the report will contain, before it's made. */}
        <section
          aria-labelledby="report-contents"
          className="mt-2 self-start rounded-inner bg-raised px-1.5 py-1.5 sm:px-2 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:mt-0"
        >
          <h2 id="report-contents" className="font-semibold">
            {t("report.summary.title")}
          </h2>
          <dl className="mt-0.5 grid gap-x-2 gap-y-0.5 text-sm sm:grid-cols-[auto_1fr]">
            <dt className="font-semibold">{t("report.summary.check")}</dt>
            <dd>{t("report.summary.checkValue", { when: formatWhen(result.finished_at), mode: t(`compare.mode.${result.mode}`) })}</dd>
            <dt className="font-semibold">{t("report.summary.things")}</dt>
            <dd>{t("report.summary.thingsValue", { count: n.things, list: perQuestion })}</dd>
            <dt className="font-semibold">{t("report.summary.coverage")}</dt>
            <dd>
              {notChecked > 0
                ? t("results.coverageLine.partial", { checked: checks.length - notChecked, total: checks.length })
                : t("results.coverageLine.full", { count: checks.length })}
            </dd>
            <dt className="font-semibold">{t("report.summary.tasks")}</dt>
            <dd>{t("report.summary.tasksValue", { count: tasks })}</dd>
            <dt className="font-semibold">{t("report.summary.privacy")}</dt>
            <dd>
              {t("report.summary.privacyValue", { network: yesNo(network), devices: yesNo(deviceNames), notes: yesNo(notes) })}
            </dd>
            <dt className="font-semibold">{t("report.summary.services")}</dt>
            <dd>
              {t("report.summary.servicesValue", {
                ai: hasKey && ai ? t("report.summary.on") : t("report.summary.off"),
                timestamp: timestamp ? t("report.summary.on") : t("report.summary.off"),
              })}
            </dd>
          </dl>
        </section>

        <div className="lg:col-start-1">
        <Button type="submit" variant="primary" loading={busy} className="mt-2">
          {busy ? t("report.creating") : report ? t("report.recreate") : t("report.create")}
        </Button>
        {/* Progress: the server makes the report in one go, so this says what's happening
            rather than show a made-up percentage. */}
        <div aria-live="polite">
          {busy && (
            <p role="status" className="mt-1 text-sm text-muted">
              {timestamp ? t("report.progressTimestamp") : t("report.progress")}
            </p>
          )}
          {error && !busy && (
            <div className="mt-2">
              <Notice title={error} tone="error">
                <span className="block">{t("report.retryKeeps")}</span>
                <Button variant="secondary" size="sm" className="mt-1" onClick={() => make.mutate()}>
                  {t("report.retry")}
                </Button>
              </Notice>
            </div>
          )}
        </div>
        </div>
      </form>

      {report && <MadeReport report={report} busy={busy} onRetry={() => make.mutate()} />}
      <p className="text-sm">
        {t("report.hostLink")}{" "}
        <button type="button" onClick={onOpenHandover} className="font-semibold text-accent underline underline-offset-2 hover:text-accent-hover">
          {t("report.openHandover")}
        </button>
      </p>
    </div>
  );
}

/** "Added", "Unavailable" with the reason, or "Not requested": what really happened. */
function Outcome({ label, outcome }: { label: string; outcome: ServiceOutcome }) {
  const { t } = useTranslation();
  const state = t(`report.outcome.${outcome.state}`);
  return (
    <div>
      <dt className="font-semibold">{label}</dt>
      <dd className="mt-0.5">{outcome.reason ? t("report.outcomeReason", { state, reason: outcome.reason }) : state}</dd>
    </div>
  );
}

function MadeReport({ report, busy, onRetry }: { report: ReportResponse; busy: boolean; onRetry: () => void }) {
  const { t } = useTranslation();
  // Check the new report straight away, the same way the Verify page does: fetch its files
  // from the backend and ask the backend to verify them. Nothing leaves the laptop.
  const check = useQuery({
    queryKey: ["report-verify", report.pdf],
    enabled: report.tsr !== null,
    retry: false,
    queryFn: async () => {
      const fileBlob = async (name: string) => (await fetch(reportFileUrl(name))).blob();
      const [pdf, tsr] = await Promise.all([fileBlob(report.pdf), fileBlob(report.tsr as string)]);
      return verifyReport(pdf, tsr, null);
    },
  });

  return (
    <>
      <section aria-labelledby="report-preview" className={card}>
        <h2 id="report-preview" className="text-lg">
          {t("report.previewTitle")}
        </h2>
        <iframe
          title={t("report.previewTitle")}
          // The browser's PDF viewer, without its thumbnail sidebar.
          src={`${reportFileUrl(report.pdf, true)}#navpanes=0`}
          className="mt-2 h-80 w-full rounded-inner border border-line bg-raised sm:h-96"
        />
        <p className="mt-0.5 text-sm text-muted">{t("report.previewNote")}</p>
        <div className="mt-2">
          <a href={reportFileUrl(report.bundle)} download={report.bundle} className={primaryButton}>
            {t("report.downloadBundle")}
          </a>
          <p className="mt-0.5 text-sm text-muted">{report.tsr ? t("report.bundleHint") : t("report.bundleHintNoTsr")}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-sm">
            <span className="text-muted">{t("report.individually")}</span>
            <a href={reportFileUrl(report.pdf)} download={report.pdf} className={fileLink}>
              {t("report.download")}
            </a>
            {report.tsr && (
              <a href={reportFileUrl(report.tsr)} download={report.tsr} className={fileLink}>
                {t("report.downloadTsr")}
              </a>
            )}
            <a href={reportFileUrl(report.sha256_file)} download={report.sha256_file} className={fileLink}>
              {t("report.downloadHash")}
            </a>
          </p>
        </div>
      </section>

      <section aria-labelledby="report-outcomes" className={card}>
        <h2 id="report-outcomes" className="text-lg">
          {t("report.outcomesTitle")}
        </h2>
        <dl className="mt-2 space-y-1.5">
          <Outcome label={t("report.ai")} outcome={report.ai} />
          <Outcome label={t("report.timestampChoice")} outcome={report.timestamp} />
        </dl>
        {/* Anything that didn't work can be tried again, with the same label and choices. */}
        {report.timestamp.state === "unavailable" && (
          <Button variant="secondary" size="sm" className="mt-1.5" loading={busy} onClick={onRetry}>
            {busy ? t("report.progressTimestamp") : t("report.retry")}
          </Button>
        )}
      </section>

      <section aria-labelledby="report-evidence" className={card}>
        <h2 id="report-evidence" className="text-lg">
          {t("report.evidenceTitle")}
        </h2>
        <dl className="mt-2 space-y-2">
          <div>
            <dt className="font-semibold">{t("report.fingerprint")}</dt>
            <dd className="mt-0.5 font-mono text-sm break-all">{report.sha256}</dd>
            <dd className="text-sm text-muted">{t("report.fingerprintHelp")}</dd>
          </div>
          <div>
            <dt className="font-semibold">{t("report.timestamp")}</dt>
            {report.timestamped_at ? (
              <>
                <dd className="mt-0.5">{t("report.timestampAt", { when: formatWhen(report.timestamped_at) })}</dd>
                <dd className="mt-0.5" aria-live="polite">
                  {check.isPending ? (
                    <span className="text-muted">{t("report.verifying")}</span>
                  ) : check.isError ? (
                    <Hint>{t("report.verifyFailed")}</Hint>
                  ) : check.data?.outcome === "verified" ? (
                    <span className="font-semibold text-accent">{t("report.verifiedOk")}</span>
                  ) : (
                    <Notice title={t(`verify.outcome.${check.data?.outcome ?? "couldnt_verify"}`)}>
                      {check.data?.reason ?? check.data?.message}
                    </Notice>
                  )}
                </dd>
              </>
            ) : (
              // Never promised: only a timestamp that was actually added is shown as one.
              <dd className="mt-0.5">{t("report.noTimestamp")}</dd>
            )}
          </div>
        </dl>
        <div className="mt-2 space-y-0.5">
          {/* Worded for what this report has: only a timestamped one can show it's unchanged
              "since it was timestamped". */}
          <Hint>{report.tsr ? t("report.notProof") : t("report.notProofNoTimestamp")}</Hint>
          {report.tsr && <Hint>{t("report.keepFiles")}</Hint>}
        </div>
      </section>
    </>
  );
}
