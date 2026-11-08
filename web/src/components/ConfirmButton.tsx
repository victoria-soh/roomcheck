import { useEffect, useId, useRef, useState } from "react";

import { Button } from "../ds/Button";
import { insetClass } from "../ds/classes";

/** A button that asks first. Focus moves to the safe choice when the question opens, and back
 * to the button if you keep things as they are. Destructive: the trigger and the confirming
 * button use the destructive style, and the question says exactly what will be lost. */
export function ConfirmButton({
  label,
  question,
  yes,
  no,
  onConfirm,
  busy = false,
  error = null,
  quiet = false,
  destructive = false,
}: {
  label: string;
  question: string;
  yes: string;
  no: string;
  onConfirm: () => void;
  busy?: boolean;
  error?: string | null;
  quiet?: boolean;
  destructive?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const noRef = useRef<HTMLButtonElement>(null);
  const openRef = useRef<HTMLButtonElement>(null);
  const wasAsking = useRef(false);
  const id = useId();

  useEffect(() => {
    if (asking) noRef.current?.focus();
    else if (wasAsking.current) openRef.current?.focus();
    wasAsking.current = asking;
  }, [asking]);

  if (!asking) {
    return (
      <Button
        ref={openRef}
        variant={destructive ? "destructive" : quiet ? "text" : "secondary"}
        size={quiet || destructive ? "sm" : "md"}
        onClick={() => setAsking(true)}
      >
        {label}
      </Button>
    );
  }
  return (
    <div role="group" aria-labelledby={id} className={`max-w-form border border-line ${insetClass}`}>
      <p id={id} className="font-semibold">
        {question}
      </p>
      <div className="mt-1 flex flex-wrap gap-1">
        <Button ref={noRef} variant="primary" onClick={() => setAsking(false)} unavailable={busy}>
          {no}
        </Button>
        <Button variant={destructive ? "destructive-confirm" : "secondary"} onClick={onConfirm} loading={busy}>
          {yes}
        </Button>
      </div>
      {error && (
        <p role="alert" className="mt-1 text-sm font-semibold text-sev-high">
          {error}
        </p>
      )}
    </div>
  );
}
