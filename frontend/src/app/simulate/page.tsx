"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api-client";
import { Incident } from "../../lib/types";

interface FaultScenario {
  id: string;
  name: string;
  service: string;
  badgeColor: string;
  httpStatus: string;
  description: string;
  mechanism: string;
  expectedRule: string;
}

const SCENARIOS: FaultScenario[] = [
  {
    id: "db_pool_exhaustion",
    name: "Database Connection Pool Timeout",
    service: "checkout",
    badgeColor: "bg-rose-950/80 text-rose-300 border-rose-800/80",
    httpStatus: "HTTP 500",
    description: "Simulates full connection pool exhaustion (20/20 active) causing 5000ms acquisition timeout.",
    mechanism: "Internal span 'db.acquire_connection' records ConnectionPoolTimeoutError, logs critical error, and emits checkout.db.pool.exhausted metric.",
    expectedRule: "db_pool_exhaustion_detected",
  },
  {
    id: "payment_gateway_declined",
    name: "Payment Gateway Transaction Declined",
    service: "payment",
    badgeColor: "bg-amber-950/80 text-amber-300 border-amber-800/80",
    httpStatus: "HTTP 502",
    description: "Simulates payment processor card rejection due to fraud check or insufficient funds.",
    mechanism: "Downstream Payment service throws card_issuer_declined, emits payment.gateway.declined metric, and returns Bad Gateway to Checkout.",
    expectedRule: "payment_declines_detected",
  },
  {
    id: "inventory_out_of_stock",
    name: "Warehouse Out-of-Stock Conflict",
    service: "inventory",
    badgeColor: "bg-purple-950/80 text-purple-300 border-purple-800/80",
    httpStatus: "HTTP 409",
    description: "Simulates inventory exhaustion in warehouse-east for ordered items.",
    mechanism: "Inventory service fails inventory.check_stock span, logs inventory allocation error, and emits inventory.stock.out_of_stock metric.",
    expectedRule: "inventory_stock_errors_detected",
  },
  {
    id: "sustained_latency",
    name: "Sustained Latency Degradation",
    service: "checkout",
    badgeColor: "bg-cyan-950/80 text-cyan-300 border-cyan-800/80",
    httpStatus: "HTTP 200 (Delayed)",
    description: "Injects 3500ms latency into distributed request execution.",
    mechanism: "Adds artificial delay across spans, causing checkout.duration_ms metric to spike above the 3000ms p95 threshold.",
    expectedRule: "sustained_latency_detected",
  },
];

interface ExecutionLog {
  id: string;
  time: string;
  scenario: string;
  status: "success" | "failure";
  httpCode?: number;
  response: any;
}

export default function SimulatePage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string>("");
  const [loadingScenario, setLoadingScenario] = useState<string | null>(null);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);

  useEffect(() => {
    async function loadIncidents() {
      try {
        const res = await api.getIncidents({ limit: 15, status: "open" });
        setIncidents(res.items);
      } catch (err) {
        console.error("Failed to load incidents:", err);
      }
    }
    loadIncidents();
  }, []);

  const triggerFault = async (scenario: FaultScenario) => {
    setLoadingScenario(scenario.id);
    const logId = `exec_${Date.now()}`;
    const timestamp = new Date().toLocaleTimeString();

    try {
      const data = await api.simulateFailure(scenario.id, selectedIncidentId || undefined);
      setLogs((prev) => [
        {
          id: logId,
          time: timestamp,
          scenario: scenario.name,
          status: "success",
          httpCode: 200,
          response: data,
        },
        ...prev,
      ]);
    } catch (err: any) {
      setLogs((prev) => [
        {
          id: logId,
          time: timestamp,
          scenario: scenario.name,
          status: "failure",
          httpCode: err.statusCode || 500,
          response: err.details || { error: err.message },
        },
        ...prev,
      ]);
    } finally {
      setLoadingScenario(null);
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center space-x-2">
            <h2 className="text-2xl font-bold tracking-tight text-white">
              Chaos Engineering & Fault Injection
            </h2>
            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-rose-950 text-rose-400 border border-rose-800">
              Live Failure Injection
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Trigger real, controlled application failures across microservices. Telemetry is transmitted through OpenTelemetry Collector to the PostgreSQL ingestion engine, where the detection engine will automatically flag anomalies.
          </p>
        </div>

        {/* Association Selector */}
        <div className="flex items-center space-x-2 bg-slate-900 p-2.5 rounded-xl border border-slate-800 text-xs">
          <span className="text-slate-400">Incident Mode:</span>
          <select
            value={selectedIncidentId}
            onChange={(e) => setSelectedIncidentId(e.target.value)}
            className="bg-slate-950 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1 text-xs focus:ring-1 focus:ring-indigo-500 outline-none"
          >
            <option value="">⚡ Automatic Detection Engine</option>
            {incidents.map((inc) => (
              <option key={inc.id} value={inc.id}>
                Tag to: {inc.title.slice(0, 28)}...
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Grid of Scenarios */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {SCENARIOS.map((sc) => {
          const isRunning = loadingScenario === sc.id;
          return (
            <div
              key={sc.id}
              className="p-6 rounded-2xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition-all flex flex-col justify-between space-y-5"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className={`px-2 py-0.5 rounded text-[11px] font-mono border font-semibold ${sc.badgeColor}`}>
                    svc:{sc.service} · {sc.httpStatus}
                  </span>
                  <span className="text-[11px] font-mono text-slate-400">
                    Rule: {sc.expectedRule}
                  </span>
                </div>

                <h3 className="text-base font-bold text-white">{sc.name}</h3>
                <p className="text-xs text-slate-300 leading-relaxed">{sc.description}</p>

                <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80 text-[11px] text-slate-400 space-y-1 font-mono">
                  <span className="text-slate-500 block text-[10px]">EXECUTION PATH:</span>
                  <p className="text-slate-300 break-words">{sc.mechanism}</p>
                </div>
              </div>

              <div className="pt-2 flex items-center justify-between border-t border-slate-800">
                <span className="text-xs text-slate-500 font-mono">POST /checkout/simulate/{sc.id}</span>
                <button
                  onClick={() => triggerFault(sc)}
                  disabled={Boolean(loadingScenario)}
                  className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-semibold transition-all shadow-lg shadow-rose-600/20 flex items-center space-x-2"
                >
                  {isRunning ? (
                    <>
                      <span className="w-2 h-2 rounded-full bg-white animate-ping"></span>
                      <span>Injecting Fault...</span>
                    </>
                  ) : (
                    <span>Inject Failure ⚡</span>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Execution Response Log Console */}
      <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse"></span>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Fault Injection Execution Log ({logs.length})
            </h3>
          </div>
          {logs.length > 0 && (
            <button
              onClick={() => setLogs([])}
              className="text-xs text-slate-500 hover:text-slate-300"
            >
              Clear Log
            </button>
          )}
        </div>

        {logs.length === 0 ? (
          <div className="py-8 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
            No faults injected in this session yet. Click any &quot;Inject Failure&quot; card above to trigger a controlled microservice incident.
          </div>
        ) : (
          <div className="space-y-3 font-mono text-xs max-h-96 overflow-y-auto pr-1">
            {logs.map((log) => (
              <div
                key={log.id}
                className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="text-slate-500 text-[11px]">{log.time}</span>
                    <span className="font-semibold text-slate-200">{log.scenario}</span>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold border ${
                      log.status === "failure"
                        ? "bg-rose-950/80 text-rose-300 border-rose-800"
                        : "bg-emerald-950/80 text-emerald-300 border-emerald-800"
                    }`}
                  >
                    HTTP {log.httpCode}
                  </span>
                </div>

                <pre className="p-2.5 rounded bg-slate-900 text-slate-300 text-[11px] overflow-x-auto border border-slate-800/80 leading-relaxed">
                  {JSON.stringify(log.response, null, 2)}
                </pre>

                <div className="flex items-center justify-end space-x-3 pt-1 text-[11px]">
                  <a
                    href="/telemetry"
                    className="text-indigo-400 hover:text-indigo-300 underline"
                  >
                    View Ingested Telemetry →
                  </a>
                  <a
                    href="/"
                    className="text-purple-400 hover:text-purple-300 underline"
                  >
                    Check Incidents Board →
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
