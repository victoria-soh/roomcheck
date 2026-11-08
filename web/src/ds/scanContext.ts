// The latest check, for the page header's context line ("Example-Home · 3 Nov, 13:24 · Full
// check") on every page after a check.
import { createContext } from "react";

import type { DiscoveryResult } from "../api/types";

export const ScanContext = createContext<DiscoveryResult | null>(null);
