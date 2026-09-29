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
    { name: "Demo Store", href: "/store" },
    { name: "Fault Injection", href: "/simulate" },
    { name: "Live Telemetry", href: "/telemetry" },
  ];

  return (
    <>
      <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur sticky top-0 z-40 px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center space-x-6">
          <Link href="/" className="flex items-center space-x-3 group">
            <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-500 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/25 group-hover:scale-105 transition-transform">
              AI
            </div>
            <div>
              <div className="flex items-center space-x-1.5">
                <span className="text-sm font-bold leading-tight text-white tracking-tight">
                  Incident Investigator
                </span>
                <span className="text-[10px] uppercase font-semibold bg-indigo-950 text-indigo-400 border border-indigo-800/80 px-1.5 py-0.2 rounded">
                  v2.0
                </span>
              </div>
              <p className="text-[11px] text-slate-400">Autonomous Telemetry & AI Diagnosis</p>
            </div>
          </Link>

          {/* Navigation Links */}
          <nav className="hidden md:flex items-center space-x-1">
            {navItems.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/" || pathname?.startsWith("/incidents")
                  : pathname?.startsWith(item.href);

              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    active
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

        {/* Status Indicator & Health Trigger */}
        <div className="flex items-center space-x-3 text-xs">
          <a
            href="http://localhost:16686"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden sm:inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-mono text-slate-400 hover:text-indigo-300 hover:bg-slate-800/60 border border-slate-800 transition-colors"
          >
            Jaeger UI ↗
          </a>

          <button
            onClick={() => setShowHealthModal(true)}
            className="inline-flex items-center px-3 py-1 rounded-lg text-xs font-medium bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 transition-all cursor-pointer shadow-sm"
          >
            <span
              className={`w-2 h-2 mr-2 rounded-full ${
                isHealthy === true
                  ? "bg-emerald-400 shadow-sm shadow-emerald-400/50 animate-pulse"
                  : isHealthy === false
                  ? "bg-rose-400"
                  : "bg-amber-400 animate-pulse"
              }`}
            ></span>
            <span className="text-slate-200">
              {isHealthy === true ? "7 Services Active" : isHealthy === false ? "Health Degraded" : "Pinging Services..."}
            </span>
          </button>
        </div>
      </header>

      {showHealthModal && (
        <ServiceHealthModal onClose={() => setShowHealthModal(false)} />
      )}
    </>
  );
}
