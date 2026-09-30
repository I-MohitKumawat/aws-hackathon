"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { api } from "../lib/api-client";
import ServiceHealthModal from "./ServiceHealthModal";

export default function Navbar() {
  const pathname = usePathname();
  const [showHealthModal, setShowHealthModal] = useState(false);
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    async function check() {
      try {
        const res = await api.getServiceHealth();
        if (mounted) setIsHealthy(res.status === "healthy");
      } catch {
        if (mounted) setIsHealthy(false);
      }
    }
    check();
    const interval = setInterval(check, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const navItems = [
    { name: "Incidents", href: "/" },
    { name: "Live Telemetry", href: "/telemetry" },
  ];

  return (
    <>
      <header className="bg-[#111625] text-slate-200 border-b border-slate-800 sticky top-0 z-40 px-4 h-11 flex items-center justify-between shadow-sm select-none">
        <div className="flex items-center space-x-6 h-full">
          <Link href="/" className="flex items-center space-x-2 font-bold tracking-tight text-white hover:text-teal-300 transition-colors">
            <span className="w-3 h-3 bg-teal-500 rounded-sm inline-block"></span>
            <span className="text-sm font-semibold tracking-normal uppercase">Incident Investigator</span>
          </Link>

          {/* Navigation Tabs */}
          <nav className="flex items-center space-x-1 h-full">
            {navItems.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/" || pathname?.startsWith("/incidents")
                  : pathname?.startsWith(item.href);

              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={`h-full flex items-center px-3.5 text-xs transition-colors border-b-2 font-medium ${
                    active
                      ? "border-teal-500 text-white font-semibold"
                      : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
                  }`}
                >
                  {item.name}
                </Link>
              );
            })}

            <a
              href="http://localhost:16686"
              target="_blank"
              rel="noopener noreferrer"
              className="h-full flex items-center px-3 text-xs text-slate-400 hover:text-teal-300 hover:bg-slate-800/40 border-b-2 border-transparent transition-colors font-mono"
            >
              Jaeger UI ↗
            </a>
          </nav>
        </div>

        {/* System Health Status Indicator */}
        <div className="flex items-center space-x-3 text-xs">
          <button
            onClick={() => setShowHealthModal(true)}
            title="Click to view detailed component health"
            className="flex items-center space-x-2 px-2.5 py-1 rounded bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 text-slate-300 text-[11px] transition-colors cursor-pointer"
          >
            <span
              className={`w-2 h-2 rounded-full ${
                isHealthy === true
                  ? "bg-teal-400"
                  : isHealthy === false
                  ? "bg-rose-500 animate-pulse"
                  : "bg-slate-500"
              }`}
            ></span>
            <span className="font-mono">
              {isHealthy === true
                ? "System Healthy"
                : isHealthy === false
                ? "Degraded"
                : "Checking..."}
            </span>
          </button>
        </div>
      </header>

      {showHealthModal && <ServiceHealthModal onClose={() => setShowHealthModal(false)} />}
    </>
  );
}
