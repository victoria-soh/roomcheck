// The clues "Help identify this" shows, from what RoomCheck already found. Nothing new.
import type { TFunction } from "i18next";

import type { Device, NearbyItem } from "../api/types";
import type { RecognitionProps } from "../handover/useHandover";

/** A device's clues, from what discovery and identification already found. */
export function deviceClues(device: Device | undefined, t: TFunction): string[] {
  if (!device) return [t("identify.clue.makerUnknown"), t("identify.clue.looksUnknown")];
  const clues = [device.vendor ? t("identify.clue.maker", { maker: device.vendor }) : t("identify.clue.makerUnknown")];
  if (device.hostnames[0]) clues.push(t("identify.clue.calls", { name: device.hostnames[0] }));
  clues.push(
    device.fingerprint && device.fingerprint.type !== "unknown"
      ? t("identify.clue.looks", { label: device.fingerprint.label, band: t(`results.band.${device.fingerprint.band}`) })
      : t("identify.clue.looksUnknown"),
  );
  return [...clues, ...(device.notes ?? [])];
}

/** A flagged nearby item's clues: what it broadcast, nothing more. */
export function nearbyClues(item: NearbyItem | undefined, t: TFunction): string[] {
  if (!item) return [t("identify.clue.makerUnknown")];
  const clues = [t("identify.clue.nearby", { label: item.label })];
  clues.push(item.maker ? t("identify.clue.maker", { maker: item.maker }) : t("identify.clue.makerUnknown"));
  if (item.band) clues.push(t("identify.clue.band", { band: item.band }));
  if (item.security) clues.push(t("identify.clue.security", { security: item.security }));
  if (item.signal_dbm != null) clues.push(t("identify.clue.signal", { dbm: item.signal_dbm }));
  return clues;
}

/** "Unknown device" cards: no maker and no type, or the user answered "Unknown". */
export function needsIdentifying(device: Device | undefined, props: RecognitionProps): boolean {
  const unidentified = !device?.vendor && (!device?.fingerprint || device.fingerprint.type === "unknown");
  return unidentified || props.answer === "unknown";
}
