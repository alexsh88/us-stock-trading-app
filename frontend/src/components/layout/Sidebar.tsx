"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { TrendingUp, Briefcase, Settings, BarChart3, BookOpen, Activity, Search } from "lucide-react";

const nav = [
  { href: "/", label: "Dashboard", icon: TrendingUp },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/performance", label: "Performance", icon: Activity },
  { href: "/lookup", label: "Quick Analysis", icon: Search },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/guide", label: "How It Works", icon: BookOpen },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 min-h-screen bg-card border-r border-border flex flex-col">
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-6 w-6 text-primary" />
          <span className="font-bold text-sm">StockAI</span>
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-1">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-secondary"
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-border">
        <span className="text-xs text-muted-foreground">Paper Trading Mode</span>
        <div className="flex items-center gap-1 mt-1">
          <div className="h-2 w-2 rounded-full bg-green-500" />
          <span className="text-xs text-green-500">Active</span>
        </div>
      </div>
    </aside>
  );
}
