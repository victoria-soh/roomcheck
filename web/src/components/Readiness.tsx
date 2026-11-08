import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { getSetup } from "../api/client";
import { ProblemIcon, StepIcon } from "./icons";
import { quietButton } from "./styles";
import { Disclosure } from "./ui";
import { SETUP_KEY } from "../handover/keys";

/** The Start screen's connection bar: "Connected to <network>" and "Check again". Anything
 * missing is listed below it, with how to switch networks.
 * Missing items never block the start; they only say which checks will be limited, and the one
 * start button below then reads "Start check (some parts limited)". The network name is shown
 * here on this laptop only. */
export function Readiness() {
  const { t } = useTranslation();
  const setup = useQuery({ queryKey: SETUP_KEY, queryFn: getSetup, retry: false });
  const data = setup.data;
  // "Check again": GET /api/setup re-reads the network, Npcap, Nmap, Wi-Fi, Bluetooth and
  // Location every time (nothing is cached). While it runs the button says so; afterwards the
  // time is shown and announced, and the status and missing lines update from the new answer.
  const [rechecking, setRechecking] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [recheckFailed, setRecheckFailed] = useState(false);
  async function checkAgain() {
    if (rechecking) return;
    setRechecking(true);
    setRecheckFailed(false);
    const next = await setup.refetch();
    setRechecking(false);
    if (next.isError) setRecheckFailed(true);
    else setCheckedAt(new Date());
  }
  const time = checkedAt?.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const network = !data
    ? null
    : data.network.kind === "wifi"
      ? t("start.ready.connectedTo", { name: data.network.name })
      : data.network.kind === "cable"
        ? t("start.ready.cable")
        : null;
  const missing = data?.items.filter((i) => !i.ready) ?? [];
  const ready = data?.items.filter((i) => i.ready) ?? [];
  const allSet = data && data.all_ready && data.network.kind !== "none";
  // The readiness check reports a problem: not connected, or something missing.
  const problem = Boolean(data) && !allSet;

  return (
    <section aria-label={t("start.ready.label")} className="rounded-inner border border-line bg-surface px-2 py-1">
      <div aria-live="polite" className="space-y-0.5">
        {setup.isPending && <p className="text-muted">{t("start.ready.checking")}</p>}
        {setup.isError && <p className="text-muted">{t("start.ready.failed")}</p>}

        {data && (
          <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
            {network ? (
              <p className="flex items-center gap-1 font-semibold">
                {allSet && (
                  <span className="text-accent">
                    <StepIcon state="done" />
                  </span>
                )}
                {network}
              </p>
            ) : (
              <p className="flex items-start gap-1 font-semibold">
                <span className="text-sev-medium">
                  <ProblemIcon />
                </span>
                <span>
                  {t("start.ready.none")}
                  <span className="block text-sm font-normal">{t("start.ready.noneFix")}</span>
                </span>
              </p>
            )}
            <div className="flex flex-wrap items-center gap-x-2 text-sm">
              {/* How to switch networks: only when something here needs fixing. */}
              {problem && (
                <Disclosure summary={t("start.ready.different")}>
                  <ul className="space-y-0.5 text-sm">
                    <li>{t("start.ready.differentBody.one")}</li>
                    <li>{t("start.ready.differentBody.two")}</li>
                    <li>{t("start.ready.differentBody.three")}</li>
                  </ul>
                </Disclosure>
              )}
              <button
                type="button"
                disabled={rechecking}
                aria-disabled={rechecking}
                onClick={() => void checkAgain()}
                className={`${quietButton} disabled:cursor-wait disabled:opacity-70`}
              >
                {rechecking ? t("start.ready.rechecking") : t("start.ready.recheck")}
              </button>
            </div>
          </div>
        )}

        {/* Announced: the new time, or that it couldn't check. */}
        {(checkedAt || recheckFailed) && !rechecking && (
          <p className="text-sm text-muted">{recheckFailed ? t("start.ready.recheckFailed") : t("start.ready.checkedAt", { time })}</p>
        )}

        {data && missing.length > 0 && (
          <>
            <ul className="space-y-0.5 text-sm">
              {missing.map((i) => (
                <li key={i.name} className="flex items-start gap-1">
                  <span className="flex shrink-0 items-center gap-0.5 font-semibold text-sev-medium">
                    <ProblemIcon />
                    {t("start.ready.status.missing")}
                  </span>
                  <span>
                    <span className="font-semibold">{t(`start.ready.item.${i.name}.name`)}:</span>{" "}
                    <span className="text-muted">{t(`start.ready.item.${i.name}.fix`)}</span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-sm">
                {t("start.ready.limited", {
                  list: missing.map((i) => t(`start.ready.item.${i.name}.limits`)).join(", "),
                })}
                {ready.length > 0 && (
                  <span className="text-muted">
                    {" "}
                    {t("start.ready.alsoReady", {
                      list: ready.map((i) => t(`start.ready.item.${i.name}.name`)).join(", "),
                    })}
                  </span>
                )}
            </p>
          </>
        )}
      </div>

    </section>
  );
}
