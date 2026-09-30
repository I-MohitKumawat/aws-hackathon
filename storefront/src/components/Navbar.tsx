"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();

  const navItems = [
    { name: "Storefront", href: "/" },
    { name: "⚡ Dev Controls: Fault Injection", href: "/simulate", devOnly: true },
  ];

  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-40 px-6 py-3.5 flex items-center justify-between">
      <div className="flex items-center space-x-6">
        <Link href="/" className="flex items-center space-x-3 group">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-500 flex items-center justify-center font-bold text-white shadow-lg shadow-emerald-500/25 group-hover:scale-105 transition-transform text-lg">
            🛒
          </div>
          <div>
            <div className="flex items-center space-x-1.5">
              <span className="text-sm font-bold leading-tight text-white tracking-tight">
                CloudShop
              </span>
              <span className="text-[10px] uppercase font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800/80 px-1.5 py-0.2 rounded">
                Storefront
              </span>
            </div>
            <p className="text-[11px] text-slate-400">Target Microservices Demo Application</p>
          </div>
        </Link>

        {/* Navigation Links */}
        <nav className="hidden md:flex items-center space-x-2">
          {navItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  item.devOnly
                    ? active
                      ? "bg-rose-950/80 text-rose-300 border border-rose-800 font-semibold shadow-sm"
                      : "text-rose-400/80 hover:text-rose-300 hover:bg-rose-950/30 border border-rose-900/40"
                    : active
                    ? "bg-slate-800 text-white shadow-sm font-semibold border border-slate-700/60"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                }`}
              >
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* External platform links */}
      <div className="flex items-center space-x-3 text-xs">
        <a
          href="http://localhost:16686"
          target="_blank"
          rel="noopener noreferrer"
          className="hidden sm:inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-mono text-slate-400 hover:text-indigo-300 hover:bg-slate-800/60 border border-slate-800 transition-colors"
        >
          Jaeger Tracing ↗
        </a>
        <a
          href="http://localhost:3000"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm transition-all"
        >
          <span>🛡️ Open Investigator (port 3000) ↗</span>
        </a>
      </div>
    </header>
  );
}
