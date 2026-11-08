import { useTranslation } from "react-i18next";

import type { CheckStatus, Finding } from "../api/types";
import { ProblemIcon, SeverityIcon, StepIcon } from "./icons";
import { findingAnchor, NETWORK_CHECKS } from "./links";
import { SEVERITY_TEXT } from "./severity";

/** The Network health panel on Results: the Layer 3 checks. */
export function NetworkHealth({
  checks,
  findings,
}: {
  checks: CheckStatus[];
  findings: Finding[];
}) {
  const { t } = useTranslation();
  return (
    <CheckList
      id="health-title"
      title={t("results.networkHealth.title")}
      intro={t("results.networkHealth.intro")}
      checks={checks}
      findings={findings}
      rules={NETWORK_CHECKS}
    />
  );
}

/** What each check did, compactly. A check that ran and flagged nothing says only that; a
 * flagged one links to its card. Used for Network health and the Nearby checks. */
export function CheckList({
  id,
  title,
  intro,
  checks,
  findings,
  rules,
}: {
  id: string;
  title: string;
  intro: string;
  checks: CheckStatus[];
  findings: Finding[];
  rules: Record<string, string[]>;
}) {
  return (
    <section
      aria-labelledby={id}
      className="rounded-card border border-line bg-surface p-3 shadow-soft sm:p-4"
    >
      <h2 id={id} className="text-lg">
        {title}
      </h2>
      <p className="mt-0.5 text-muted">{intro}</p>
      <CheckRows checks={checks} findings={findings} rules={rules} />
    </section>
  );
}

/** The rows of a CheckList, on their own (Nearby shows them inside its coverage disclosure). */
export function CheckRows({
  checks,
  findings,
  rules,
}: {
  checks: CheckStatus[];
  findings: Finding[];
  rules: Record<string, string[]>;
}) {
  const { t } = useTranslation();
  const rows = checks.filter((c) => c.name in rules);
  return (
    <ul className="mt-1 divide-y divide-line">
      {rows.map((c) => {
        const flagged = findings.filter((f) =>
          rules[c.name]?.includes(f.rule_id),
        );
        const top = flagged[0];
        return (
          <li key={c.name} className="flex gap-1.5 py-1.5">
            <span
              className={`mt-0.5 ${
                top
                  ? SEVERITY_TEXT[top.severity]
                  : c.status === "ran"
                    ? "text-accent"
                    : c.status === "failed"
                      ? "text-sev-medium"
                      : "text-muted"
              }`}
            >
              {top ? (
                <SeverityIcon level={top.severity} />
              ) : c.status === "failed" ? (
                <ProblemIcon />
              ) : (
                <StepIcon state={c.status === "ran" ? "done" : "skipped"} />
              )}
            </span>
            <div className="min-w-0">
              <p className="font-medium">{c.label}</p>
              {c.status === "ran" && flagged.length === 0 && (
                <p className="text-sm text-muted">
                  {t("results.networkHealth.ran")}
                </p>
              )}
              {flagged.map((f) => (
                <p key={f.id} className="text-sm">
                  <a
                    href={`#${findingAnchor(f.id)}`}
                    // The address holds the screen (App's routes), so jump to the card in place.
                    onClick={(e) => {
                      const el = document.getElementById(findingAnchor(f.id));
                      if (!el) return;
                      e.preventDefault();
                      el.scrollIntoView?.({ block: "start" });
                      (el.closest("article") ?? el).focus();
                    }}
                    className="font-semibold text-accent underline underline-offset-2 transition-colors hover:text-accent-hover"
                  >
                    {t("results.networkHealth.found", { title: f.title })}
                  </a>
                </p>
              ))}
              {c.status !== "ran" && (
                <p className="text-sm text-muted">
                  {t(`results.networkHealth.${c.status}`, {
                    reason: c.reason ?? t("results.networkHealth.noReason"),
                  })}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
