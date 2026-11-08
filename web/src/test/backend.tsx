// Render with React Query and a stubbed backend: each test says what the API answers.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";

import { BASELINE_NONE, COMPARE_NONE, HANDOVER, SETUP_READY } from "./fixtures";

export interface Call {
  method: string;
  url: string;
  body: unknown;
}

type Answer = object | ((call: Call) => object);

/** Routes are "METHOD /path" (a trailing * matches any rest of the path). */
export function withBackend(ui: ReactNode, routes: Record<string, Answer> = {}) {
  const calls: Call[] = [];
  const table: Record<string, Answer> = {
    "GET /api/handover": HANDOVER,
    "GET /api/baseline": BASELINE_NONE,
    "GET /api/compare": COMPARE_NONE,
    "GET /api/setup": SETUP_READY,
    ...routes,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
      const call = { method, url, body };
      calls.push(call);
      const key = Object.keys(table).find((k) => {
        const [m, path] = k.split(" ");
        return m === method && (path === url || (path?.endsWith("*") && url.startsWith(path.slice(0, -1))));
      });
      if (!key) return new Response(JSON.stringify({ detail: "not mocked" }), { status: 500 });
      const answer = table[key]!;
      return new Response(JSON.stringify(typeof answer === "function" ? answer(call) : answer));
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { calls, view, client };
}
