// Fonts, all bundled (no web-font request: the CSP allows fonts only from RoomCheck itself),
// and only the weights used. Each @font-face has font-display: swap.
// Atkinson Hyperlegible Next: body and UI text.
import "@fontsource/atkinson-hyperlegible-next/400.css";
import "@fontsource/atkinson-hyperlegible-next/600.css";
import "@fontsource/atkinson-hyperlegible-next/700.css";
// Its digits 0-9 from Plus Jakarta Sans (unslashed zero), same family name: after Atkinson.
import "./styles/digits.css";
// Plus Jakarta Sans: headings, card titles and the summary headline.
import "@fontsource/plus-jakarta-sans/600.css";
import "@fontsource/plus-jakarta-sans/700.css";
// JetBrains Mono: fingerprints, hashes and other machine values.
import "@fontsource/jetbrains-mono/400.css";
// Saira SemiBold, for the wordmark only.
import "@fontsource/saira/600.css";
import "./styles/index.css";
import "./i18n";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function mount(ui: ReactNode) {
  const root = document.getElementById("root");
  if (root) {
    createRoot(root).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
      </StrictMode>,
    );
  }
}

// The component gallery: the dev build only (npm run dev, then /gallery). In a production build
// import.meta.env.DEV is false, so this branch and the gallery's code are left out entirely.
if (import.meta.env.DEV && window.location.pathname === "/gallery") {
  void import("./gallery/Gallery").then(({ Gallery }) => mount(<Gallery />));
} else {
  mount(<App />);
}
