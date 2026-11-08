import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { getBaseline, saveBaseline } from "../api/client";
import { formatWhen } from "../format";
import { BASELINE_KEY, COMPARE_KEY, HANDOVER_KEY } from "../handover/keys";
import { ConfirmButton } from "./ConfirmButton";
import { card, secondaryButton, unavailableButton } from "./styles";
import { Notice } from "./ui";


/** "Save as my move-in scan", after a check. Encrypted on this laptop for this Windows account. */
export function BaselineCard({ onOpenCompare }: { onOpenCompare: () => void }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const info = useQuery({ queryKey: BASELINE_KEY, queryFn: getBaseline });
  const save = useMutation({
    mutationFn: saveBaseline,
    onSuccess: (next) => {
      client.setQueryData(BASELINE_KEY, next);
      void client.invalidateQueries({ queryKey: COMPARE_KEY });
      void client.invalidateQueries({ queryKey: HANDOVER_KEY });
    },
  });
  const data = info.data;
  if (!data) return null;
  const busy = save.isPending;

  return (
    <section aria-labelledby="baseline-card" className={card}>
      <h2 id="baseline-card" className="text-lg">
        {t("baseline.title")}
      </h2>
      {/* What saving it is for, in one sentence, until it's saved. */}
      {data.state !== "saved" && <p className="mt-0.5 max-w-measure">{t("baseline.value")}</p>}
      <div aria-live="polite">
        {data.state === "unreadable" && (
          <div className="mt-1">
            <Notice title={data.message ?? ""} />
          </div>
        )}
        {data.state === "saved" && data.saved_at && (
          <p className="mt-0.5">{t("baseline.saved", { when: formatWhen(data.saved_at) })}</p>
        )}
        {save.isError && (
          <div className="mt-1">
            <Notice title={t("baseline.saveFailed")} />
          </div>
        )}
      </div>
      {data.state === "saved" && data.saved_at ? (
        <div className="mt-1 flex flex-wrap items-start gap-1">
          <button type="button" onClick={onOpenCompare} className={secondaryButton}>
            {t("baseline.openCompare")}
          </button>
          <ConfirmButton
            quiet
            label={t("baseline.replace")}
            question={t("baseline.replaceConfirm", { when: formatWhen(data.saved_at), devices: data.devices, nearby: data.nearby })}
            yes={t("baseline.replaceYes")}
            no={t("baseline.keep")}
            busy={busy}
            onConfirm={() => save.mutate()}
          />
        </div>
      ) : (
        <>
          <button
            type="button"
            aria-disabled={busy}
            onClick={() => !busy && save.mutate()}
            // Outlined: the summary's Review button is the page's only filled one.
            className={`mt-1 ${busy ? unavailableButton : secondaryButton}`}
          >
            {busy ? t("baseline.saving") : data.state === "unreadable" ? t("baseline.startNew") : t("baseline.save")}
          </button>
          <p className="mt-1 text-sm text-muted">{t("baseline.saveHint")}</p>
        </>
      )}
    </section>
  );
}
