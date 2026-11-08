import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { RecognitionProps } from "../handover/useHandover";
import { ChevronIcon } from "./icons";
import { NameField, RecognitionChoices } from "./Recognition";
import { Bullets } from "./ui";

/** "Help identify this": one guided panel that links what RoomCheck already has. Its clues in
 * plain words, "Find it" for flagged nearby items (the locator's own rules), an optional name
 * and note, then Mine / Host's / Unknown. Nothing new is collected. */
export function IdentifyPanel({
  props,
  clues,
  find,
  withAnswer = true,
}: {
  props: RecognitionProps;
  clues: string[];
  find: ReactNode; // a "Locate signal" button, or why it can't be located
  /** Off where the card asks "Do you recognise this?" itself (Nearby cards). */
  withAnswer?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <details className="group mt-2 rounded-inner border border-line">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-inner px-2 py-1 font-semibold text-accent transition-colors hover:bg-canvas">
        {t("identify.summary")}
        <span className="text-muted transition-transform group-open:rotate-180">
          <ChevronIcon />
        </span>
      </summary>
      <div className="space-y-2 px-2 pt-0.5 pb-2">
        <p className="text-sm text-muted">{t("identify.intro")}</p>
        <section>
          <h4 className="font-semibold">{t("identify.cluesTitle")}</h4>
          <Bullets items={clues} />
        </section>
        <section>
          <h4 className="font-semibold">{t("identify.findTitle")}</h4>
          <div className="mt-0.5">{find}</div>
        </section>
        <section>
          <h4 className="font-semibold">{t("identify.nameTitle")}</h4>
          <NameField key={`${props.name}|${props.note}`} props={props} withNote />
        </section>
        {withAnswer && (
          <section>
            <h4 className="mb-0.5 font-semibold">{t("identify.answerTitle")}</h4>
            <RecognitionChoices props={props} />
          </section>
        )}
      </div>
    </details>
  );
}
