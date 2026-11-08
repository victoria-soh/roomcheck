import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, verifyReport } from "../api/client";
import type { VerifyResult } from "../api/types";
import { ChevronIcon, ProblemIcon, SelectedIcon, SeverityIcon, StepIcon, UploadIcon } from "../components/icons";
import { ScreenHeading } from "../components/ScreenHeading";
import { card, secondaryButton } from "../components/styles";
import { Button } from "../ds/Button";
import { Hint, Notice } from "../components/ui";
import { FileInput } from "../ds/Fields";
import { slotOf, sortFiles, type Picked, type Problems, type Slot } from "../verify/files";

/** Screen 7. Check a report PDF against its .tsr token (and .sha256, if given). One drop area
 * takes all three files and works out which is which, with a checklist of what's received
 * and what's missing; the individual fields are still there. The files go to RoomCheck's own
 * backend on 127.0.0.1 and are checked there, offline; nothing else. Four
 * distinct outcomes: Verified, Files don't match, Couldn't verify (with the reason), and Not
 * timestamped, which is explained and never called altered. */
export function Verify({ onBack }: { onBack?: () => void }) {
  // Remounting the form clears the file inputs for "Verify another report".
  const [round, setRound] = useState(0);
  return <VerifyForm key={round} onBack={onBack} onAnother={() => setRound((n) => n + 1)} />;
}

function VerifyForm({ onBack, onAnother }: { onBack?: () => void; onAnother: () => void }) {
  const { t } = useTranslation();
  const [files, setFiles] = useState<Picked>({ pdf: null, tsr: null, hash: null });
  const [problems, setProblems] = useState<Problems>({});
  const [dragging, setDragging] = useState(false);
  const hintId = useId();
  const dropId = useId();
  const check = useMutation({ mutationFn: () => verifyReport(files.pdf as File, files.tsr, files.hash) });
  const ready = files.pdf !== null; // a report without a timestamp can still be checked
  const busy = check.isPending;

  function take(list: FileList | File[] | null) {
    if (!list || list.length === 0) return;
    const sorted = sortFiles([...list], files);
    setFiles(sorted.picked);
    setProblems(sorted.problems);
    check.reset();
  }
  // One of the individual fields: the same checks, for that slot only.
  function takeOne(slot: Slot, file: File | null) {
    check.reset();
    if (!file) {
      setFiles((f) => ({ ...f, [slot]: null }));
      setProblems((p) => ({ ...p, [slot]: undefined }));
      return;
    }
    const sorted = sortFiles([file], { ...files, [slot]: null });
    const kind = slotOf(file);
    if (kind !== slot) {
      setProblems((p) => ({ ...p, [slot]: { key: `wrongKind.${slot}`, name: file.name } }));
      return;
    }
    setFiles(sorted.picked);
    setProblems((p) => ({ ...p, [slot]: sorted.problems[slot] }));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (ready && !busy) check.mutate();
  }

  const failed = check.error
    ? check.error instanceof ApiError && check.error.detail
      ? check.error.detail
      : t("verify.failed")
    : null;
  const problem = (slot: Slot | "other") => {
    const p = problems[slot];
    return p ? t(`verify.problem.${p.key}`, { name: p.name }) : null;
  };
  const rows: { slot: Slot; label: string; missing: string }[] = [
    { slot: "pdf", label: t("verify.pdf"), missing: t("verify.missingPdf") },
    { slot: "tsr", label: t("verify.tsrShort"), missing: t("verify.missingTsr") },
    { slot: "hash", label: t("verify.sha256Short"), missing: t("verify.missingHash") },
  ];

  return (
    <div className="space-y-3">
      <div>
        <ScreenHeading context={false}>{t("verify.title")}</ScreenHeading>
        <p className="mt-1 max-w-measure text-lg text-muted">{t("verify.intro")}</p>
        <div className="mt-1">
          <Hint>{t("verify.local")}</Hint>
        </div>
      </div>

      {/* The form and the result: one width, the page's own (as every screen). */}
      <form onSubmit={submit} className={card}>
        {/* One area for all three files: choose them together, or drop them on it. */}
        <label
          htmlFor={dropId}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            take(e.dataTransfer.files);
          }}
          className={`flex cursor-pointer flex-col items-center gap-0.5 rounded-card border-2 border-dashed px-2 py-3 text-center transition-colors has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus ${
            dragging ? "border-accent bg-aqua" : "border-line-strong bg-raised hover:bg-aqua"
          }`}
        >
          <span className="text-accent">
            <UploadIcon />
          </span>
          <span id={`${dropId}-label`} className="font-semibold text-accent underline underline-offset-4">
            {t("verify.choose")}
          </span>
          <span id={`${dropId}-hint`} className="text-sm text-muted">
            {t("verify.chooseHint")}
          </span>
          <input
            id={dropId}
            type="file"
            multiple
            accept=".pdf,application/pdf,.tsr,.sha256,.txt"
            aria-labelledby={`${dropId}-label`}
            aria-describedby={`${dropId}-hint`}
            onChange={(e) => take(e.target.files)}
            className="sr-only"
          />
        </label>

        {/* What's here and what's missing, with any problem next to the file it's about. */}
        <h2 id="verify-files" className="mt-2 font-semibold">
          {t("verify.filesTitle")}
        </h2>
        <ul aria-labelledby="verify-files" className="mt-0.5 divide-y divide-line">
          {rows.map(({ slot, label, missing }) => {
            const file = files[slot];
            const issue = problem(slot);
            return (
              <li key={slot} className="flex items-start gap-1 py-1">
                <span className={file ? "text-accent" : slot === "pdf" ? "text-sev-medium" : "text-muted"}>
                  {file ? <StepIcon state="done" /> : slot === "pdf" ? <ProblemIcon /> : <StepIcon state="skipped" />}
                </span>
                <div className="min-w-0">
                  <p className="font-semibold">{label}</p>
                  <p className="text-sm break-all text-muted">{file ? t("verify.received", { name: file.name }) : missing}</p>
                  {issue && (
                    <p role="alert" className="text-sm font-semibold text-sev-high">
                      {issue}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {problem("other") && (
          <p role="alert" className="mt-0.5 text-sm font-semibold text-sev-high">
            {problem("other")}
          </p>
        )}

        <details className="group mt-1.5">
          <summary className="inline-flex cursor-pointer list-none items-center gap-0.5 rounded-control text-sm font-semibold text-accent hover:text-accent-hover hover:underline">
            {t("verify.individually")}
            <ChevronIcon />
          </summary>
          <div className="mt-1 space-y-2">
            <FileInput label={t("verify.pdf")} hint={t("verify.pdfHint")} accept=".pdf,application/pdf" onPick={(f) => takeOne("pdf", f)} />
            <FileInput label={t("verify.tsr")} hint={t("verify.tsrHint")} accept=".tsr" onPick={(f) => takeOne("tsr", f)} />
            <FileInput label={t("verify.sha256")} hint={t("verify.sha256Hint")} accept=".sha256,.txt" onPick={(f) => takeOne("hash", f)} />
          </div>
        </details>

        <Button
          type="submit"
          variant="primary"
          unavailable={!ready}
          loading={busy}
          aria-describedby={!ready ? hintId : undefined}
          className="mt-2"
        >
          {busy ? t("verify.checking") : t("verify.check")}
        </Button>
        {!ready && (
          <div className="mt-1">
            <Hint id={hintId}>{t("verify.required")}</Hint>
          </div>
        )}
      </form>

      <div aria-live="polite">
        {failed && <Notice title={failed} tone="error" />}
        {check.data && <VerifyOutcome result={check.data} />}
      </div>

      <div className="flex flex-wrap gap-1">
        {(check.data || failed) && (
          <Button variant="secondary" onClick={onAnother}>
            {t("verify.another")}
          </Button>
        )}
        {onBack && (
          <button type="button" onClick={onBack} className={secondaryButton}>
            {t("scanning.startAgain")}
          </button>
        )}
      </div>
    </div>
  );
}

function VerifyOutcome({ result }: { result: VerifyResult }) {
  const { t } = useTranslation();
  const title = t(`verify.outcome.${result.outcome}`);
  const lead =
    result.outcome === "mismatch"
      ? t("verify.mismatchBody")
      : result.outcome === "couldnt_verify" && result.reason
        ? result.reason
        : result.message;
  const rows: [string, string][] = [
    [t("verify.rowTimestamp"), t(`verify.token.${result.token}`)],
    [t("verify.rowHashFile"), t(`verify.hash.${result.hash_file}`)],
    [
      t("verify.rowAuthority"),
      result.pinned_authority === null
        ? t("verify.authority.unknown")
        : result.pinned_authority
          ? t("verify.authority.pinned")
          : t("verify.authority.other"),
    ],
  ];
  const body = (
    <>
      <p>{lead}</p>
      {result.outcome === "verified" && <p className="mt-1 text-sm text-muted">{t("report.notProof")}</p>}
      <dl className="mt-2 grid gap-x-2 gap-y-0.5 sm:grid-cols-3 sm:gap-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="font-semibold">{k}</dt>
            <dd className="mb-1 sm:col-span-2 sm:mb-0">{v}</dd>
          </div>
        ))}
        <div className="contents">
          <dt className="font-semibold">{t("verify.rowFingerprint")}</dt>
          <dd className="font-mono text-sm break-all sm:col-span-2">{result.sha256}</dd>
        </div>
      </dl>
    </>
  );
  // One card for every outcome, at the form's width. Files don't match is a danger (the High
  // tokens: red icon and border); couldn't verify is amber; not timestamped is just explained.
  const look =
    result.outcome === "mismatch"
      ? "border-sev-high"
      : result.outcome === "couldnt_verify"
        ? "border-notice-line"
        : "";
  return (
    <section aria-labelledby="verify-result" data-outcome={result.outcome} className={look ? card.replace("border-line", look) : card}>
      <h2 id="verify-result" className="flex items-center gap-1 text-lg">
        {result.outcome === "verified" && (
          <span className="text-accent">
            <SelectedIcon />
          </span>
        )}
        {result.outcome === "mismatch" && (
          <span className="text-sev-high">
            <SeverityIcon level="High" />
          </span>
        )}
        {result.outcome === "couldnt_verify" && (
          <span className="text-sev-medium">
            <ProblemIcon />
          </span>
        )}
        {title}
      </h2>
      <div className="mt-1">{body}</div>
    </section>
  );
}
