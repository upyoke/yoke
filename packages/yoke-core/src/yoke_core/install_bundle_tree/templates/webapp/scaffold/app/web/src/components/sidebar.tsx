"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Settings,
} from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
];

const BOTTOM_ITEMS = [
  { href: "/settings", label: "Settings", icon: Settings },
];

interface SidebarContentProps {
  onNavigate?: () => void;
}

/** Shared nav content used by both desktop sidebar and mobile drawer */
export function SidebarContent({ onNavigate }: SidebarContentProps) {
  const pathname = usePathname();

  function isActive(href: string) {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  }

  return (
    <>
      <div className="flex h-14 items-center border-b px-4">
        <Link href="/dashboard" className="text-lg font-semibold" onClick={onNavigate}>
          {{project_display_name}}
        </Link>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive(item.href)
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
            )}
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </Link>
        ))}
        <Separator className="my-3" />
        {BOTTOM_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive(item.href)
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
            )}
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </Link>
        ))}
      </nav>
    </>
  );
}

/** Desktop sidebar — hidden below lg breakpoint */
export function Sidebar() {
  return (
    <aside className="hidden lg:flex h-full w-60 flex-col border-r bg-muted/40">
      <SidebarContent />
    </aside>
  );
}
