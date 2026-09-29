"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api-client";
import { ServiceHealthResponse } from "../lib/types";

interface ServiceHealthModalProps {
  onClose: () => void;
}

export default function ServiceHealthModal({ onClose }: ServiceHealthModalProps) {
  const [health, setHealth] = useState<ServiceHealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  async function checkHealth() {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getServiceHealth();
      setHealth(data);
    } catch (err: any) {
      setError(err.message || "Failed to query system health");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    checkHealth();
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-xl shadow-2xl p-6 space-y-5">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-2">
            <span className="text-base font-bold text-white">System Architecture & Service Health</span>
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800"
          >
            ✕
          </button>
        </div>

        {loading ? (
          <div className="py-8 text-center text-slate-400 text-sm">Pinging microservices & infrastructure...</div>
        ) : error ? (
          <div className="p-4 rounded-lg bg-rose-950/40 border border-rose-800 text-rose-300 text-xs">
            {error}
          </div>
        ) : health ? (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {Object.entries(health.services).map(([key, item]) => {
                const isHealthy = item.status === "healthy";
                return (
                  <div
                    key={key}
                    className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 flex items-start justify-between space-x-3 text-xs"
                  >
                    <div className="space-y-0.5">
                      <span className="font-semibold text-slate-200 capitalize">
                        {key.replace("_", " ")}
                      </span>
                      <p className="text-[11px] text-slate-400">{item.component}</p>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wide border shrink-0 ${
                        isHealthy
                          ? "bg-emerald-950/80 text-emerald-400 border-emerald-800"
                          : "bg-rose-950/80 text-rose-400 border-rose-800"
                      }`}
                    >
                      {item.status}
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="pt-2 flex items-center justify-between text-xs text-slate-500 border-t border-slate-800/80">
              <span>Overall Status: <strong className="text-emerald-400 font-medium uppercase">{health.status}</strong></span>
              <button
                onClick={checkHealth}
                className="text-indigo-400 hover:text-indigo-300 underline font-mono text-[11px]"
              >
                Refresh Pings ↻
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
