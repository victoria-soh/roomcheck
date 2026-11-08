import { useTranslation } from "react-i18next";

/** The small "AI" label on text an AI wrote. The full disclosure is said once, near the
 * summary; this keeps the full words for screen readers. */
export function AiTag() {
  const { t } = useTranslation();
  return (
    <span className="ml-1 inline-flex items-center rounded-full bg-raised px-1 align-middle text-sm leading-tight font-semibold text-muted">
      <span aria-hidden="true">{t("results.aiTag")}</span>
      <span className="sr-only">({t("results.aiTagFull")})</span>
    </span>
  );
}
