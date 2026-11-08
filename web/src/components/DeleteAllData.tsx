import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { deleteAllData } from "../api/client";
import { BASELINE_KEY, COMPARE_KEY, HANDOVER_KEY, REPORT_DEFAULTS_KEY } from "../handover/keys";
import { ConfirmButton } from "./ConfirmButton";
import { Hint } from "./ui";

/** "Delete all saved RoomCheck data": the move-in scan, handover tasks, statuses, notes,
 * answers, device names and the salt. Asks first, saying exactly what goes; report files stay. */
export function DeleteAllData() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const remove = useMutation({
    mutationFn: deleteAllData,
    onSuccess: ({ baseline, handover }) => {
      client.setQueryData(BASELINE_KEY, baseline);
      client.setQueryData(HANDOVER_KEY, handover);
      void client.invalidateQueries({ queryKey: COMPARE_KEY });
      // The last room label was deleted too: an open Report page mustn't keep offering it.
      client.setQueryData(REPORT_DEFAULTS_KEY, { room_label: null });
      void client.invalidateQueries({ queryKey: REPORT_DEFAULTS_KEY });
    },
  });
  return (
    <div className="space-y-1">
      <ConfirmButton
        quiet
        label={t("deleteAll.button")}
        question={t("deleteAll.question")}
        yes={t("deleteAll.yes")}
        no={t("deleteAll.no")}
        busy={remove.isPending}
        error={remove.isError ? t("deleteAll.failed") : null}
        onConfirm={() => remove.mutate()}
        destructive
      />
      <div aria-live="polite">{remove.isSuccess && <Hint>{t("deleteAll.done")}</Hint>}</div>
    </div>
  );
}
