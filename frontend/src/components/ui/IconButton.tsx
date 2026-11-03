import type { ComponentProps, ReactNode } from "react";
import { iconButtonClasses, type ButtonVariant } from "./styles";

export interface IconButtonProps extends Omit<ComponentProps<"button">, "children"> {
  /** Accessible name (also shown as the native tooltip). */
  label: string;
  icon: ReactNode;
  variant?: ButtonVariant;
  size?: "sm" | "md";
}

/** Square button that only shows an icon; `label` provides its accessible name. */
export function IconButton({
  label,
  icon,
  variant = "ghost",
  size = "md",
  className,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={iconButtonClasses(variant, size, className)}
      {...rest}
    >
      {icon}
    </button>
  );
}
