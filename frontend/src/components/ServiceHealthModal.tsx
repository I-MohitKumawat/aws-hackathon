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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4">
      <div className="bg-white border border-slate-300 rounded-xl w-full max-w-xl shadow-2xl p-5 space-y-4 text-xs">
        <div className="flex items-center justify-between border-b border-slate-200 pb-3">
          <div className="flex items-center space-x-2">
            <span className="text-sm font-bold text-slate-900">System Architecture & Service Health</span>
            <span className="w-2 h-2 rounded-full bg-teal-500 animate-ping"></span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-700 rounded hover:bg-slate-100 cursor-pointer"
          >
            ✕
          </button>
        </div>

        {loading ? (
          <div className="py-8 text-center text-slate-500 space-y-2">
            <div className="w-5 h-5 border-2 border-teal-600 border-t-transparent rounded-full animate-spin mx-auto"></div>
            <p>Pinging microservices & infrastructure...</p>
          </div>
        ) : error ? (
          <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700">
            {error}
          </div>
        ) : health ? (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {Object.entries(health.services).map(([key, item]) => {
                const isHealthy = item.status === "healthy";
                return (
                  <div
                    key={key}
                    className="p-2.5 rounded-lg bg-slate-50 border border-slate-200 flex items-start justify-between space-x-2"
                  >
                    <div className="space-y-0.5 min-w-0">
                      <span className="font-semibold text-slate-800 capitalize block truncate">
                        {key.replace("_", " ")}
                      </span>
                      <p className="text-[10px] text-slate-500 font-mono truncate">{item.component}</p>
                    </div>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold tracking-wide border shrink-0 ${
                        isHealthy
                          ? "bg-emerald-50 text-emerald-800 border-emerald-300"
                          : "bg-red-50 text-red-800 border-red-300"
                      }`}
                    >
                      {item.status}
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="pt-2 flex items-center justify-between text-slate-600 border-t border-slate-100">
              <span>Overall System Status: <strong className="text-emerald-700 font-bold uppercase">{health.status}</strong></span>
              <button
                onClick={checkHealth}
                className="text-teal-700 hover:text-teal-900 underline font-mono text-[11px] cursor-pointer"
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
