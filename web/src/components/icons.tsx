// One icon family (lucide-react, bundled locally: no CDN), one stroke weight and one size.
// Icons are decoration (aria-hidden): every icon whose meaning isn't obvious sits next to text.
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  Circle,
  CircleAlert,
  CircleCheck,
  CircleDot,
  CircleHelp,
  CircleMinus,
  Clock,
  Info,
  LoaderCircle,
  LockKeyhole,
  Minus,
  MonitorSmartphone,
  OctagonAlert,
  Radio,
  RotateCcw,
  Router,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  Undo2,
  Upload,
  Wifi,
  type LucideIcon,
} from "lucide-react";

import type { Severity } from "../api/types";

type StepState = "running" | "done" | "skipped";
const SIZE = 20;
const STROKE = 2;

function Glyph({ of: Icon, className = "shrink-0" }: { of: LucideIcon; className?: string }) {
  return <Icon size={SIZE} strokeWidth={STROKE} aria-hidden="true" focusable="false" className={className} />;
}

// Priority: a different shape for each level, so it never depends on colour alone.
const SEVERITY: Record<Severity, LucideIcon> = {
  High: OctagonAlert,
  Medium: TriangleAlert,
  Low: CircleMinus,
  Info: Info,
};

export function SeverityIcon({ level }: { level: Severity }) {
  const Icon = SEVERITY[level];
  return <Icon size={SIZE} strokeWidth={STROKE} aria-hidden="true" focusable="false" className="shrink-0" />;
}

export function StepIcon({ state }: { state: StepState | "waiting" }) {
  const Icon = state === "done" ? Check : state === "running" ? LoaderCircle : state === "skipped" ? Minus : Circle;
  // The spinner turns slowly, and only when the system allows motion.
  const spin = state === "running" ? "shrink-0 motion-safe:animate-spin" : "shrink-0";
  return <Icon size={SIZE} strokeWidth={STROKE} aria-hidden="true" focusable="false" className={spin} />;
}

export function SelectedIcon() {
  return <Glyph of={CircleCheck} />;
}
export function ArrowIcon() {
  return <Glyph of={ArrowRight} />;
}
export function InfoIcon() {
  return <Glyph of={Info} />;
}
export function ClockIcon() {
  return <Glyph of={Clock} />;
}
export function ChevronIcon() {
  return <Glyph of={ChevronDown} className="shrink-0 transition-transform group-open:rotate-180" />;
}
/** "Not detected" and other neutral states: a plain dot in a circle, never a tick, so nothing
 * reads as "passed". */
export function NeutralIcon() {
  return <Glyph of={CircleDot} />;
}
export function ProblemIcon() {
  return <Glyph of={CircleAlert} />;
}
export function DevicesIcon() {
  return <Glyph of={MonitorSmartphone} />;
}
export function LockIcon() {
  return <Glyph of={LockKeyhole} />;
}
export function SignalIcon() {
  return <Glyph of={Wifi} />;
}
export function RouterIcon() {
  return <Glyph of={Router} />;
}
export function NearbyIcon() {
  return <Glyph of={Radio} />;
}
export function HelpIcon() {
  return <Glyph of={CircleHelp} />;
}
export function NewCheckIcon() {
  return <Glyph of={RotateCcw} />;
}
export function UndoIcon() {
  return <Glyph of={Undo2} />;
}
export function TrashIcon() {
  return <Glyph of={Trash2} />;
}
export function EvidenceIcon() {
  return <Glyph of={ShieldCheck} />;
}
export function ErrorIcon() {
  return <Glyph of={OctagonAlert} />;
}
export function UploadIcon() {
  return <Glyph of={Upload} />;
}
export function BackIcon() {
  return <Glyph of={ArrowLeft} />;
}
