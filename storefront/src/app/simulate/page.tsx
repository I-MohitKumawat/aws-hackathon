"use client";

import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import { FaultScenario } from "../../lib/types";

const SCENARIOS: FaultScenario[] = [
  {
    id: "inventory_out_of_stock",
    name: "Warehouse Out-of-Stock Conflict",
    service: "inventory",
    badgeColor: "bg-purple-950/80 text-purple-300 border-purple-800/80",
    httpStatus: "HTTP 409",
    description: "Simulates stock exhaustion in warehouse-east during inventory allocation.",
    mechanism: "Inventory service fails 'inventory.check_stock' span, emits error log with item details, and reports 'inventory.stock.out_of_stock=1' metric.",
    expectedRule: "critical_error_log / repeated_service_failures",
  },
  {
    id: "db_pool_exhaustion",
    name: "Database Connection Pool Timeout",
    service: "checkout",
    badgeColor: "bg-rose-950/80 text-rose-300 border-rose-800/80",
    httpStatus: "HTTP 500",
    description: "Simulates complete database connection pool saturation (20/20 active) causing 5000ms acquisition timeout.",
    mechanism: "Internal span 'db.acquire_connection' records ConnectionPoolTimeoutError, logs critical error, and emits checkout.db.pool.exhausted gauge=1.",
    expectedRule: "critical_error_log / db_pool_exhaustion_detected",
  },
  {
    id: "payment_gateway_declined",
    name: "Payment Gateway Transaction Declined",
    service: "payment",
    badgeColor: "bg-amber-950/80 text-amber-300 border-amber-800/80",
    httpStatus: "HTTP 502",
    description: "Simulates payment processor card rejection due to issuer fraud check or decline.",
    mechanism: "Downstream payment service throws card_issuer_declined, logs error, emits payment.gateway.declined metric, and returns HTTP 502 to checkout.",
    expectedRule: "critical_error_log / payment_declines_detected",
  },
  {
    id: "sustained_latency",
    name: "Sustained Latency Degradation",
    service: "checkout",
    badgeColor: "bg-cyan-950/80 text-cyan-300 border-cyan-800/80",
    httpStatus: "HTTP 200 (Delayed)",
    description: "Injects 3500ms artificial delay into distributed request execution.",
    mechanism: "Adds artificial delay across spans, causing checkout.request.duration_ms metric to spike above the latency threshold.",
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

export default function SimulateFaultPage() {
  const [loadingScenario, setLoadingScenario] = useState<string | null>(null);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);

  const triggerFault = async (scenario: FaultScenario) => {
    setLoadingScenario(scenario.id);
    const logId = `exec_${Date.now()}`;
    const timestamp = new Date().toLocaleTimeString();

    try {
      const data = await api.simulateFailure(scenario.id);
      setLogs((prev) => [
        {
          id: logId,
          time: timestamp,
          scenario: scenario.name,
          status: "success",
          httpCode: 200,
          response: data,
        },
        ...prev.slice(0, 19),
      ]);
    } catch (err: any) {
      setLogs((prev) => [
        {
          id: logId,
          time: timestamp,
          scenario: scenario.name,
          status: "failure",
          httpCode: err.statusCode || 500,
          response: err.data || { message: err.message },
        },
        ...prev.slice(0, 19),
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
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20 uppercase tracking-wider">
              Developer Controls
            </span>
            <span className="text-xs font-mono text-slate-400">Isolated Fault Injection</span>
          </div>
          <h1 className="text-2xl font-bold text-white mt-1">Controlled Fault Injection</h1>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Trigger real failure mechanisms against the live microservices architecture. Telemetry is emitted through OpenTelemetry Collector to the Incident Investigator.
          </p>
        </div>

        <a
          href="http://localhost:3000"
          target="_blank"
          rel="noopener noreferrer"
          className="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition-all flex items-center space-x-2 shrink-0 shadow-lg shadow-indigo-600/20"
        >
          <span>Open Investigator (port 3000) ↗</span>
        </a>
      </div>

      {/* Developer Notice */}
      <div className="p-4 rounded-xl bg-amber-950/20 border border-amber-800/40 text-amber-200 text-xs flex items-start space-x-3">
        <span className="text-lg shrink-0">⚠️</span>
        <div>
          <p className="font-semibold text-amber-100">Notice for Operators and Evaluators</p>
          <p className="mt-0.5 text-amber-300/80 leading-relaxed">
            This panel directly invokes the instrumented failure endpoints on the backend checkout service (<code>http://localhost:8080/checkout/simulate/&lt;type&gt;</code>). It is completely segregated from the Incident Investigator application on port 3000.
          </p>
        </div>
      </div>

      {/* Scenarios Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {SCENARIOS.map((scenario) => {
          const isLoading = loadingScenario === scenario.id;

          return (
            <div
              key={scenario.id}
              className="p-5 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between space-y-4 hover:border-slate-700 transition-colors"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${scenario.badgeColor}`}>
                    {scenario.service}
                  </span>
                  <span className="text-xs font-mono text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
                    {scenario.httpStatus}
                  </span>
                </div>

                <div>
                  <h3 className="font-bold text-white text-base">{scenario.name}</h3>
                  <p className="text-xs text-slate-300 mt-1 leading-relaxed">
                    {scenario.description}
                  </p>
                </div>

                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-[11px] space-y-1">
                  <div className="text-slate-400">
                    <strong className="text-slate-300">Mechanism:</strong> {scenario.mechanism}
                  </div>
                  <div className="text-slate-400">
                    <strong className="text-slate-300">Detection Rule:</strong>{" "}
                    <span className="font-mono text-indigo-400">{scenario.expectedRule}</span>
                  </div>
                </div>
              </div>

              <button
                onClick={() => triggerFault(scenario)}
                disabled={isLoading}
                className="w-full py-2.5 rounded-lg bg-rose-600 hover:bg-rose-500 disabled:bg-rose-950 disabled:text-rose-400 text-white font-semibold text-xs transition-all shadow-md flex items-center justify-center space-x-2 cursor-pointer"
              >
                {isLoading ? (
                  <>
                    <span className="w-2 h-2 rounded-full bg-white animate-ping"></span>
                    <span>Injecting Fault...</span>
                  </>
                ) : (
                  <span>Trigger {scenario.name} ⚡</span>
                )}
              </button>
            </div>
          );
        })}
      </div>

      {/* Execution Logs */}
      <div className="space-y-3 pt-4 border-t border-slate-800">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-white">Recent Fault Injections</h2>
          {logs.length > 0 && (
            <button
              onClick={() => setLogs([])}
              className="text-xs text-slate-400 hover:text-slate-200 transition-colors"
            >
              Clear Logs
            </button>
          )}
        </div>

        {logs.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
            No faults triggered yet this session. Click any scenario button above to inject a failure.
          </div>
        ) : (
          <div className="space-y-2">
            {logs.map((log) => (
              <div
                key={log.id}
                className="p-3.5 rounded-lg bg-slate-900 border border-slate-800 text-xs space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-slate-400">{log.time}</span>
                    <span className="font-semibold text-white">{log.scenario}</span>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded font-mono font-semibold text-[10px] ${
                      log.status === "success"
                        ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                        : "bg-rose-950 text-rose-400 border border-rose-800"
                    }`}
                  >
                    HTTP {log.httpCode}
                  </span>
                </div>
                <pre className="p-2.5 rounded bg-slate-950 text-slate-300 font-mono text-[11px] overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify(log.response, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
