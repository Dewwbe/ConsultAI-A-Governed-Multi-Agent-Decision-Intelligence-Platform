import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const alertVariants = cva("rounded-lg border p-4 text-sm", {
  variants: {
    variant: {
      default: "bg-card",
      destructive: "border-destructive/50 bg-destructive/5",
      warning: "border-warning/50 bg-warning/5",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Alert({
  className,
  variant,
  ...props
}: HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>) {
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />;
}
export function AlertTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("font-semibold leading-tight", className)} {...props} />;
}
export function AlertDescription({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("mt-1 text-muted-foreground", className)} {...props} />;
}
