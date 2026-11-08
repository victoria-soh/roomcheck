import type { TFunction } from "i18next";

import type { HandoverState, Task } from "../api/types";

/** Still to ask: not resolved, and the host hasn't answered yet (Task.open in app/handover). */
export function isOpen(task: Task): boolean {
  return task.status !== "resolved" && !task.host_confirmed;
}

/** The open tasks a message to the host can include (not the ones meant for you). */
export function askable(data: HandoverState): Task[] {
  return data.tasks.filter((task) => isOpen(task) && task.who !== "you");
}

/** The standard message for a chosen set of open tasks: the same template as
 * app/handover/tasks.py bundle_message, so a subset reads exactly like the full message.
 * When every open task is chosen, the server's own draft (perhaps the AI's) is used instead. */
export function messageFor(chosen: Task[], data: HandoverState, t: TFunction): string {
  const all = askable(data);
  if (data.message && chosen.length === all.length && all.every((task) => chosen.includes(task))) {
    return data.message.text;
  }
  if (chosen.length === 0) return "";
  const lines = chosen.map((task, i) => `${i + 1}. ${task.ask}`).join("\n");
  return `${t("handover.message.opening", { count: chosen.length })}\n\n${lines}\n\n${t("handover.message.closing")}`;
}

const STOP = new Set(["a", "an", "the", "and", "or", "to", "for", "of", "it", "is", "you", "your", "can", "could", "me", "tell", "ask", "so", "if", "that", "this", "on", "in"]);

function words(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9']+/g) ?? []).filter((w) => !STOP.has(w));
}

/** The steps that add something to the question itself: a step whose words are nearly all in
 * the question ("Ask where it is, what it records and who can view it") is left out, so "What
 * to ask" and "Steps" don't say the same thing twice. */
export function stepsBeyondAsk(ask: string, steps: string[]): string[] {
  const asked = new Set(words(ask));
  return steps.filter((step) => {
    const w = words(step);
    if (w.length === 0) return false;
    const covered = w.filter((x) => asked.has(x)).length / w.length;
    return covered < 0.8;
  });
}
