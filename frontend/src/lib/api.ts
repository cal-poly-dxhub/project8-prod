import { fetchAuthSession } from "aws-amplify/auth";

const API_URL = import.meta.env.VITE_API_URL;

async function authHeaders(): Promise<Record<string, string>> {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString() ?? "";
  return {
    Authorization: token,
    "Content-Type": "application/json",
  };
}

export interface Job {
  job_id: string;
  filename: string;
  status: string;
  created_at: string;
  updated_at: string;
  error_message?: string;
}

export async function createUpload(filename: string, category: string): Promise<{ job_id: string; upload_url: string }> {
  const resp = await fetch(`${API_URL}uploads`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ filename, category }),
  });
  if (!resp.ok) {
    throw new Error(`Failed to create upload: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

export async function listCategories(): Promise<string[]> {
  const resp = await fetch(`${API_URL}categories`, { headers: await authHeaders() });
  const data = await resp.json();
  return data.categories ?? [];
}

export async function createCategory(category: string): Promise<void> {
  const resp = await fetch(`${API_URL}categories`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ category }),
  });
  if (!resp.ok) {
    throw new Error(`Failed to create category: ${resp.status} ${resp.statusText}`);
  }
}

export async function uploadFile(url: string, file: File): Promise<void> {
  const resp = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
    body: file,
  });
  if (!resp.ok) {
    throw new Error(`S3 upload failed: ${resp.status} ${resp.statusText}`);
  }
}

export async function listJobs(): Promise<Job[]> {
  const resp = await fetch(`${API_URL}jobs`, { headers: await authHeaders() });
  const data = await resp.json();
  return data.jobs;
}

export async function getJobStatus(jobId: string): Promise<Job> {
  const resp = await fetch(`${API_URL}jobs/${jobId}/status`, { headers: await authHeaders() });
  return resp.json();
}

export async function getResultsUrl(jobId: string): Promise<string> {
  const resp = await fetch(`${API_URL}jobs/${jobId}/results`, { headers: await authHeaders() });
  const data = await resp.json();
  return data.download_url;
}

// === Review ===

export interface InterviewSummary {
  interview_id: string;
  total: number;
  approved: number;
  rejected: number;
  conflict: number;
  pending: number;
  reviewed: number;
}

export interface Prediction {
  category: string;
  prediction_id: string; // "interview_id#idx"
  interview_id: string;
  idx: number;
  concept_id?: string;
  concept_name?: string;
  quote?: string;
  age?: string;
  rationale?: string;
  caused_by?: string[];
  status: string; // PENDING | APPROVED | REJECTED | CONFLICT (redacted to PENDING while blind)
  review_count: number;
  caller_voted: boolean;
  // Only present once the caller has voted (blind review):
  approvals?: Array<{ reviewer: string; timestamp: string }>;
  rejections?: Array<{
    reviewer: string;
    timestamp: string;
    reasons?: string[];
    comment?: string;
    suggested_concept_id?: string | null;
    no_relevant_concept?: boolean;
  }>;
}

export interface VoteResult {
  prediction_id: string;
  status: string;
  approvals: number;
  rejections: number;
}

export async function listInterviews(category: string): Promise<InterviewSummary[]> {
  const resp = await fetch(`${API_URL}interviews?category=${encodeURIComponent(category)}`, {
    headers: await authHeaders(),
  });
  const data = await resp.json();
  return data.interviews ?? [];
}

export async function listPredictions(
  category: string,
  opts: { interview?: string; status?: string } = {}
): Promise<Prediction[]> {
  const qs = new URLSearchParams({ category });
  if (opts.interview) qs.set("interview", opts.interview);
  if (opts.status) qs.set("status", opts.status);
  const resp = await fetch(`${API_URL}predictions?${qs.toString()}`, { headers: await authHeaders() });
  const data = await resp.json();
  return data.predictions ?? [];
}

// === Visualizations (aggregate) ===

export interface VizConcept {
  code_id: number;
  name: string;
  type: string;
  depth: number;
  category: string;
  category_color: string;
  domain: string;
  caregiver_count: number;
  pct: number;
  caregivers: string[];
  quote?: string | null;
  quote_caregiver?: string | null;
  quote_age?: string | null;
}

export interface VizCaregiver {
  caregiver_id: string;
  filename: string;
  timestamp: string | null;
  expected: string[];
  predicted: string[];
}

export interface AggregateData {
  category: string;
  n_interviews: number;
  caregivers: VizCaregiver[];
  concept_frequency: VizConcept[];
  quotes_by_concept: Record<string, Array<{ quote: string; caregiver: string; age: string | null }>>;
}

export async function getAggregate(category: string): Promise<AggregateData> {
  const resp = await fetch(`${API_URL}aggregate?category=${encodeURIComponent(category)}`, {
    headers: await authHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Failed to load aggregate: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

export interface VotePayload {
  category: string;
  decision: "approve" | "reject";
  reasons?: string[];
  comment?: string;
  suggested_concept_id?: string | null;
  no_relevant_concept?: boolean;
}

export async function votePrediction(predictionId: string, payload: VotePayload): Promise<VoteResult> {
  const resp = await fetch(`${API_URL}predictions/${encodeURIComponent(predictionId)}/vote`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    throw new Error(`Vote failed: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}
