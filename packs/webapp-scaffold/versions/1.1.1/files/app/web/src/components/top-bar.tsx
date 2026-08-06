"use client";

import { useRouter } from "next/navigation";
import { ChevronDown, LogOut, Menu, User } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { apiPost } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface TopBarProps {
  onMenuClick?: () => void;
}

export function TopBar({ onMenuClick }: TopBarProps) {
  const router = useRouter();
  const { user, clearUser } = useAuthStore();

  async function handleLogout() {
    try {
      await apiPost("/api/auth/logout");
    } catch {
      // logout failed, clear client state anyway
    }
    clearUser();
    router.replace("/login");
  }

  return (
    <header className="flex min-h-14 items-center justify-between gap-3 border-b bg-background px-4">
      <div className="mr-auto inline-flex items-center">
        {onMenuClick && (
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={onMenuClick}
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </Button>
        )}
        <span className="text-sm font-medium text-muted-foreground">
          {{project_display_name}}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="gap-2">
              <User className="h-4 w-4" />
              <span className="hidden sm:inline">
                {user?.name || user?.email || "Account"}
              </span>
              <ChevronDown className="h-4 w-4 opacity-50" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>
              {user?.email}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout}>
              <LogOut className="mr-2 h-4 w-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
