import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { StepIcon } from "../components/icons";
import { buttonClass, type ButtonSize, type ButtonVariant } from "./classes";

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "disabled"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Can't be used yet: aria-disabled (still focusable), clicks do nothing. Pair with a hint
   * through aria-describedby. */
  unavailable?: boolean;
  /** Working: aria-busy, a spinner, and clicks do nothing until it's done. */
  loading?: boolean;
  icon?: ReactNode;
}

/** The one button: primary, secondary, text, destructive; unavailable and loading states. */
export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = "secondary", size = "md", unavailable = false, loading = false, icon, className = "", onClick, children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-disabled={unavailable || loading}
      aria-busy={loading || undefined}
      onClick={(e) => {
        if (unavailable || loading) {
          e.preventDefault();
          return;
        }
        onClick?.(e);
      }}
      className={`${buttonClass(variant, size, unavailable)} ${loading ? "cursor-wait" : ""} ${className}`}
      {...rest}
    >
      {loading ? <StepIcon state="running" /> : icon}
      {children}
    </button>
  );
});
