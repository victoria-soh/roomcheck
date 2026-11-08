import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { deleteBaseline, getBaseline } from "../api/client";
import { formatWhen } from "../format";
import { BASELINE_KEY, COMPARE_KEY, HANDOVER_KEY } from "../handover/keys";
import { ConfirmButton } from "./ConfirmButton";
import { Hint } from "./ui";

/** "Delete move-in scan" (in Help, under Delete your data): asks first, saying when it was saved
 * and what goes. Shown only while there is a move-in scan to delete. */
export function DeleteMoveInScan() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const info = useQuery({ queryKey: BASELINE_KEY, queryFn: getBaseline });
  const remove = useMutation({
    mutationFn: deleteBaseline,
    onSuccess: (next) => {
      client.setQueryData(BASELINE_KEY, next);
      for (const key of [COMPARE_KEY, HANDOVER_KEY]) void client.invalidateQueries({ queryKey: key });
    },
  });
  const baseline = info.data;
  const saved = baseline && baseline.state !== "none";
  return (
    <div className="space-y-1">
      {saved && (
        <ConfirmButton
          quiet
          label={t("compare.delete")}
          question={t("compare.deleteConfirm", {
            when: baseline.saved_at ? formatWhen(baseline.saved_at) : "",
            devices: baseline.devices,
            nearby: baseline.nearby,
          })}
          yes={t("compare.deleteYes")}
          no={t("compare.deleteNo")}
          busy={remove.isPending}
          error={remove.isError ? t("compare.deleteFailed") : null}
          onConfirm={() => remove.mutate()}
          destructive
        />
      )}
      <div aria-live="polite">{remove.isSuccess && <Hint>{t("compare.deleted")}</Hint>}</div>
    </div>
  );
}
