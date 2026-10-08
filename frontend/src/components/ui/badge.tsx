import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium", {
  variants: {
    variant: {
      default: "bg-secondary text-secondary-foreground",
      outline: "bg-transparent text-foreground",
      success: "border-success/40 bg-success/10 text-success",
      warning: "border-warning/40 bg-warning/10 text-warning",
      destructive: "border-destructive/40 bg-destructive/10 text-destructive",
    },
  },
  defaultVariants: { variant: "default" },
});

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
