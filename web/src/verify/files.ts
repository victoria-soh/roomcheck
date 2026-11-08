/** Working out which report file is which, for the Verify page's one drop area. */

export type Slot = "pdf" | "tsr" | "hash";

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024; // the same cap as app/main.py

export interface Picked {
  pdf: File | null;
  tsr: File | null;
  hash: File | null;
}

/** Each file's problem, next to the file it's about; "other" is for files that aren't one of
 * the three. Values are string keys under verify.problem. */
export type Problems = Partial<Record<Slot | "other", { key: string; name: string }>>;

export function slotOf(file: File): Slot | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf") || file.type === "application/pdf") return "pdf";
  if (name.endsWith(".tsr")) return "tsr";
  if (name.endsWith(".sha256") || name.endsWith(".txt")) return "hash";
  return null;
}

/** Sort dropped or chosen files into the PDF, the .tsr and the .sha256. A file of a kind
 * already chosen replaces it; two of a kind at once keeps the first and says so. */
export function sortFiles(files: File[], current: Picked): { picked: Picked; problems: Problems } {
  const picked = { ...current };
  const problems: Problems = {};
  const seen = new Set<Slot>();
  for (const file of files) {
    const slot = slotOf(file);
    if (slot === null) {
      problems.other = { key: "unknown", name: file.name };
      continue;
    }
    if (seen.has(slot)) {
      problems[slot] = { key: "twoOfAKind", name: file.name };
      continue;
    }
    seen.add(slot);
    if (file.size === 0) {
      problems[slot] = { key: "empty", name: file.name };
      picked[slot] = null;
      continue;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      problems[slot] = { key: "tooLarge", name: file.name };
      picked[slot] = null;
      continue;
    }
    picked[slot] = file;
  }
  return { picked, problems };
}
