import { Incident, Evidence, InvestigationJob, InvestigationReport } from "../lib/types";

export const MOCK_INCIDENTS: Incident[] = [
  {
    id: "inc_001",
    title: "Checkout service timeout",
    service: "checkout",
    severity: "high",
    status: "investigating",
    started_at: "2026-09-29T09:30:00Z",
    ended_at: null,
    created_at: "2026-09-29T09:31:00Z",
    description: "Checkout requests are timing out.",
  },
  {
    id: "inc_002",
    title: "Payment gateway 502 bad gateway spikes",
    service: "payment",
    severity: "critical",
    status: "open",
    started_at: "2026-09-29T10:15:00Z",
    ended_at: null,
    created_at: "2026-09-29T10:16:00Z",
    description: "Spike in upstream 502 responses during token generation.",
  },
];

export const MOCK_EVIDENCE: Evidence[] = [
  {
    id: "ev_001",
    incident_id: "inc_001",
    type: "log",
    timestamp: "2026-09-29T09:32:10Z",
    service: "checkout",
    severity: "error",
    message: "Database connection timeout",
    trace_id: "trace_abc123",
    source: "otel",
    metadata: {},
  },
  {
    id: "ev_002",
    incident_id: "inc_001",
    type: "deployment",
    timestamp: "2026-09-29T09:25:00Z",
    service: "checkout",
    severity: "info",
    message: "Deployment checkout-v2",
    trace_id: null,
    source: "otel",
    metadata: { version: "v2" },
  },
];

export const MOCK_JOB: InvestigationJob = {
  job_id: "job_001",
  incident_id: "inc_001",
  status: "completed",
  stage: "report_ready",
  progress: 100,
  created_at: "2026-09-29T09:35:00Z",
  completed_at: "2026-09-29T09:36:00Z",
  error: null,
};

export const MOCK_REPORT: InvestigationReport = {
  id: "report_001",
  incident_id: "inc_001",
  status: "completed",
  summary: "Checkout requests experienced database connection timeouts.",
  hypotheses: [
    {
      id: "hyp_001",
      description: "A recent deployment may have caused connection pool exhaustion.",
      status: "possible",
      supporting_evidence: ["ev_001"],
      contradicting_evidence: [],
      missing_evidence: ["Database connection pool metrics"],
      next_step: "Inspect connection pool usage around the deployment.",
    },
  ],
  created_at: "2026-09-29T09:36:00Z",
};
