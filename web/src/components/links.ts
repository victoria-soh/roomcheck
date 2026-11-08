// Shared between the finding cards, the handover tasks and the network health panel.
import type { TFunction } from "i18next";

import type { Device } from "../api/types";

/** The id of a finding's card, for "See the card above" links. */
export function findingAnchor(id: string): string {
  return `finding-${id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

// The Layer 3 checks (app/checks/runner.py) and the rules each one feeds.
export const NETWORK_CHECKS: Record<string, string[]> = {
  wifi_encryption: ["R-WIFI-ENC"],
  dns: ["R-DNS"],
  arp: ["R-ARP"],
  dhcp: ["R-DHCP"],
  upnp: ["R-UPNP"],
  cve: ["R-CVE"],
};

// The Layer 4 nearby checks (app/wireless/survey.py) and the rules each one feeds.
export const NEARBY_CHECKS: Record<string, string[]> = {
  nearby_wifi: ["R-HIDDEN", "R-OPEN", "R-CAMHOT"],
  lookalike: ["R-TWIN", "R-TWIN-VENDOR", "R-TWIN-DOWNGRADE"],
  wps: ["R-WPS"],
  bluetooth: ["R-TRACKER"],
};

/** The id of a handover task's card, for "View in handover". */
export function taskAnchor(id: string): string {
  return `task-${id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

/** A device's host name and maker, e.g. "cam-hallway · Made by Example Camera Co.". */
export function deviceName(device: Device | undefined, t: TFunction): string {
  if (!device) return "";
  const parts: string[] = [];
  if (device.hostnames[0]) parts.push(device.hostnames[0]);
  parts.push(device.vendor ? t("results.madeBy", { maker: device.vendor }) : t("results.unknownDevice"));
  return parts.join(" · ");
}
