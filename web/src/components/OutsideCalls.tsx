import { useTranslation } from "react-i18next";

import { OUTSIDE_CALLS } from "./outsideCallList";

/** Every outside call RoomCheck can make: when it happens and what is sent. One fixed list,
 * shown in Help ("What's sent") as a table, and in the README as one line per row, word for
 * word: "<call> (<when>): <what's sent>" (tests/unit/test_consistency.py compares them).
 * From 640 px a table; on a phone the same words as a short list per call (only one is shown,
 * so screen readers hear it once). */
export function OutsideCalls() {
  const { t } = useTranslation();
  const cell = (k: string, part: "call" | "when" | "sent") => t(`privacy.calls.${k}.${part}`);
  return (
    <>
      <p>{t("privacy.intro")}</p>
      <table className="mt-1 hidden w-full text-left text-sm sm:table">
        <thead>
          <tr className="text-muted">
            <th scope="col" className="py-0.5 pr-2 font-semibold">
              {t("help.sentTable.call")}
            </th>
            <th scope="col" className="py-0.5 pr-2 font-semibold">
              {t("help.sentTable.when")}
            </th>
            <th scope="col" className="py-0.5 font-semibold">
              {t("help.sentTable.sent")}
            </th>
          </tr>
        </thead>
        <tbody>
          {OUTSIDE_CALLS.map((k) => (
            <tr key={k} className="border-t border-line align-top">
              <th scope="row" className="py-1 pr-2 font-semibold">
                {cell(k, "call")}
              </th>
              {/* The words are the README's; only the first letter is shown capitalised. */}
              <td className="py-1 pr-2 first-letter:uppercase">{cell(k, "when")}</td>
              <td className="py-1 first-letter:uppercase">{cell(k, "sent")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="mt-1 space-y-1 text-sm sm:hidden">
        {OUTSIDE_CALLS.map((k) => (
          <li key={k} className="border-t border-line pt-1">
            <p className="font-semibold">{cell(k, "call")}</p>
            <p>
              <span className="text-muted">{t("help.sentTable.when")}: </span>
              {cell(k, "when")}
            </p>
            <p>
              <span className="text-muted">{t("help.sentTable.sent")}: </span>
              {cell(k, "sent")}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}
