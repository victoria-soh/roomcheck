// The handover state (answers, adjusted steps, tasks, the bundled message), shared by Results,
// Nearby and Handover. Answers and statuses show at once (optimistically); the backend's reply
// then replaces the state, and a failed save puts the old state back.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getHandover, recheckTask, setAnswer, setLocation, setName, updateTask } from "../api/client";
import type { Answer, Draft, Finding, HandoverState, CameraLocation, TaskStatus } from "../api/types";
import { HANDOVER_KEY } from "./keys";

export function useHandover() {
  return useQuery({ queryKey: HANDOVER_KEY, queryFn: getHandover });
}

function useOptimistic<V>(send: (v: V) => Promise<HandoverState>, apply: (s: HandoverState, v: V) => HandoverState) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onMutate: async (v: V) => {
      await client.cancelQueries({ queryKey: HANDOVER_KEY });
      const before = client.getQueryData<HandoverState>(HANDOVER_KEY);
      if (before) client.setQueryData(HANDOVER_KEY, apply(before, v));
      return { before };
    },
    onError: (_e, _v, context) => {
      if (context?.before) client.setQueryData(HANDOVER_KEY, context.before);
    },
    onSuccess: (state: HandoverState) => client.setQueryData(HANDOVER_KEY, state),
  });
}

export function useAnswer() {
  return useOptimistic(
    ({ subject, answer, confirmed }: { subject: string; answer: Answer | null; confirmed?: boolean | null }) =>
      setAnswer(subject, answer, confirmed),
    (s, { subject, answer, confirmed }) => {
      const answers = { ...s.answers };
      if (answer) answers[subject] = answer;
      else delete answers[subject];
      const known = { ...(s.confirmed ?? {}) };
      if (answer === "landlord" && confirmed != null) known[subject] = confirmed;
      else if (answer !== "landlord") delete known[subject];
      return { ...s, answers, confirmed: known };
    },
  );
}

export function useName() {
  return useOptimistic(
    ({ subject, name, note }: { subject: string; name: string; note?: string }) => setName(subject, name, note),
    (s, { subject, name, note }) => {
      const names = { ...(s.names ?? {}) };
      if (name) names[subject] = name;
      else delete names[subject];
      const notes = { ...(s.notes ?? {}) };
      if (note) notes[subject] = note;
      else if (note === "") delete notes[subject];
      return { ...s, names, notes };
    },
  );
}

/** A camera's "Where is it?": the next step follows from the server's answer. */
export function useLocation() {
  return useOptimistic(
    ({ subject, location }: { subject: string; location: CameraLocation | null }) => setLocation(subject, location),
    (s, { subject, location }) => {
      const locations = { ...(s.locations ?? {}) };
      if (location) locations[subject] = location;
      else delete locations[subject];
      return { ...s, locations };
    },
  );
}

/** Recheck one task. Not optimistic: the result comes from a real check. */
export function useRecheck() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => recheckTask(id),
    onSuccess: (state: HandoverState) => client.setQueryData(HANDOVER_KEY, state),
  });
}

export interface TaskChange {
  id: string;
  status?: TaskStatus;
  notes?: string;
  host_confirmed?: boolean;
}

export function useTaskUpdate() {
  return useOptimistic(
    ({ id, status, notes, host_confirmed }: TaskChange) => updateTask(id, { status, notes, host_confirmed }),
    (s, { id, status, host_confirmed }) => ({
      ...s,
      tasks: s.tasks.map((t) =>
        t.id === id
          ? { ...t, ...(status ? { status } : {}), ...(host_confirmed !== undefined ? { host_confirmed } : {}) }
          : t,
      ),
    }),
  );
}

export interface RecognitionProps {
  subject: string;
  answer: Answer | null;
  confirmed: boolean | null; // "Host's" only
  name: string;
  note: string;
  onAnswer: (answer: Answer | null, confirmed?: boolean | null) => void; // null: no answer
  onName: (name: string, note?: string) => void;
  busy: boolean;
  failed: boolean;
  nameFailed: boolean;
  adjusted?: { next_step: string; guidance: string[]; draft?: Draft };
  location: CameraLocation | null; // a camera's "Where is it?"
  onLocation: (location: CameraLocation | null) => void;
}

/** The recognition props for one finding's card, or undefined for network-wide findings.
 * Answers and names are kept by subject, so one answer applies wherever the device appears. */
export function useRecognitionProps() {
  const state = useHandover();
  const answer = useAnswer();
  const naming = useName();
  const placing = useLocation();
  return (f: Finding): RecognitionProps | undefined => {
    const subject = f.subject;
    if (!subject || f.scope === "network") return undefined;
    const mine = answer.variables?.subject === subject;
    return {
      subject,
      answer: state.data?.answers[subject] ?? null,
      confirmed: state.data?.confirmed?.[subject] ?? null,
      name: state.data?.names?.[subject] ?? "",
      note: state.data?.notes?.[subject] ?? "",
      onAnswer: (a: Answer | null, confirmed?: boolean | null) => answer.mutate({ subject, answer: a, confirmed }),
      onName: (name: string, note?: string) => naming.mutate({ subject, name, note }),
      busy: answer.isPending && mine,
      failed: answer.isError && mine,
      nameFailed: naming.isError && naming.variables?.subject === subject,
      adjusted: state.data?.adjusted[f.id],
      location: state.data?.locations?.[subject] ?? null,
      onLocation: (location: CameraLocation | null) => placing.mutate({ subject, location }),
    };
  };
}

/** The user's own name for a subject, if they gave one. */
export function nameFor(subject: string | null | undefined, state: HandoverState | undefined): string {
  return (subject && state?.names?.[subject]) || "";
}

/** Findings the user said are theirs: shown in "Your devices", still with severity and evidence. */
export function isMine(f: Finding, state: HandoverState | undefined): boolean {
  return Boolean(f.subject && state?.answers[f.subject] === "mine");
}
