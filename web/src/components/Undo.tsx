import { UndoToast } from "../ds/Feedback";

/** "Status changed to Asked. Undo": the design system's Undo toast. */
export function Undo(props: { message: string | null; onUndo: () => void; onExpire: () => void }) {
  return <UndoToast {...props} />;
}
