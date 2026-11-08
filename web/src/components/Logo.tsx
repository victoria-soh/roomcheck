// The RoomCheck logo: the main mark (docs/branding/roomcheck-mark.svg) and the Saira wordmark.
// Lagoon teal is for the logo only; the app's buttons, links and text keep their own colours.
// Inline SVG with presentation attributes, so the CSP (no inline styles) stays intact.

export const MARK_PATH =
  "M16 6 H48 L54 12 V32 L32 55 L10 32 V12 Z M18 34 V24 L32 14.6 L46 24 V34 H35.5 V27 H28.5 V34 Z";

/** The main mark. Hidden from screen readers: the wordmark next to it names it. */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden="true"
      focusable="false"
      data-logo="mark"
      className="shrink-0"
    >
      <path d={MARK_PATH} fill="#1BA9A6" fillRule="evenodd" />
    </svg>
  );
}

/** "RoomCheck" in Saira SemiBold, one colour. */
export function Wordmark({ children }: { children: string }) {
  return <span className="font-wordmark text-brand font-semibold text-wordmark">{children}</span>;
}
