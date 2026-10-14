import * as React from "react";
import { cn } from "@/lib/utils";

// The signature Google-style element: a lucide icon inside a colored, lifted 3D circle.
type Color = "blue" | "green" | "yellow" | "red";

const COLORS: Record<Color, string> = {
  blue: "bg-gblue text-white",
  green: "bg-ggreen text-white",
  yellow: "bg-gyellow text-[#202124]",
  red: "bg-gred text-white",
};

const SIZES = { sm: "h-9 w-9", md: "h-12 w-12", lg: "h-14 w-14" };

export function IconBadge({
  icon: Icon,
  color = "blue",
  size = "md",
  className,
}: {
  icon: React.ComponentType<{ className?: string }>;
  color?: Color;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "icon-3d flex shrink-0 items-center justify-center",
        COLORS[color],
        SIZES[size],
        className
      )}
    >
      <Icon className={size === "sm" ? "h-4 w-4" : "h-6 w-6"} />
    </div>
  );
}
