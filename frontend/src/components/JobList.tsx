import { Fragment, useState, useEffect } from "react";
import { listJobs, decidePii, Job } from "../lib/api";
import { Badge, Button, Card, Spinner } from "./ui";

interface Props {
  onSelectJob: (id: string) => void;
  selectedJobId: string | null;
}

type Tone = "slate" | "blue" | "green" | "red" | "amber";

const STATUS_TONE: Record<string, Tone> = {
  UPLOADING: "amber",
  PROCESSING: "blue",
  COMPLETED: "green",
  FAILED: "red",
  PII_REVIEW: "amber",
  CANCELLED: "slate",
};

// Human-friendly labels for statuses whose raw value reads poorly.
const STATUS_LABEL: Record<string, string> = {
  PII_REVIEW: "Review needed",
};

// Order the status tracker chips appear in, so the summary reads left-to-right
// through the lifecycle rather than in whatever order jobs happen to arrive.
const TRACKER_ORDER = [
  "UPLOADING",
  "PROCESSING",
  "PII_REVIEW",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const;

// How many of the most recent jobs the tracker summarizes and lists.
const RECENT_LIMIT = 10;

// PII entity type -> plain-language label for the reupload prompt.
const PII_LABEL: Record<string, string> = {
  NAME: "name",
  EMAIL: "email address",
  PHONE: "phone number",
  ADDRESS: "address",
  USERNAME: "username",
  US_SOCIAL_SECURITY_NUMBER: "social security number",
  US_PASSPORT_NUMBER: "passport number",
  DRIVER_ID: "driver's license number",
  CA_HEALTH_NUMBER: "health number",
  UK_NATIONAL_HEALTH_SERVICE_NUMBER: "NHS number",
};

export default function JobList({ onSelectJob, selectedJobId }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [deciding, setDeciding] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const data = await listJobs();
      setJobs(data);
    } finally {
      setLoading(false);
    }
  };

  const handleDecision = async (jobId: string, decision: "proceed" | "cancel") => {
    setDeciding(jobId);
    try {
      await decidePii(jobId, decision);
      await refresh();
    } catch (e) {
      alert(`${e}`);
    } finally {
      setDeciding(null);
    }
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <Card className="p-6">
        <Spinner label="Loading jobs…" />
      </Card>
    );
  }

  if (jobs.length === 0) {
    return (
      <Card className="p-10 text-center text-sm text-slate-500">
        No jobs yet. Upload a file to get started.
      </Card>
    );
  }

  // Jobs arrive newest-first from the API; show only the most recent handful
  // and summarize their statuses in the tracker header.
  const recent = jobs.slice(0, RECENT_LIMIT);
  const counts = recent.reduce<Record<string, number>>((acc, job) => {
    acc[job.status] = (acc[job.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-slate-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-800">
            Recent jobs
            <span className="ml-2 text-sm font-normal text-slate-400">
              {jobs.length > RECENT_LIMIT
                ? `showing ${RECENT_LIMIT} of ${jobs.length}`
                : `${jobs.length} total`}
            </span>
          </h2>
          <span className="text-xs text-slate-400">Auto-refreshing</span>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {TRACKER_ORDER.filter((s) => counts[s]).map((s) => (
            <Badge key={s} tone={STATUS_TONE[s] ?? "slate"}>
              {(STATUS_LABEL[s] ?? s)}: {counts[s]}
            </Badge>
          ))}
        </div>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <th className="px-6 py-3">File</th>
            <th className="px-6 py-3">Status</th>
            <th className="px-6 py-3">Created</th>
            <th className="px-6 py-3"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {recent.map((job) => (
            <Fragment key={job.job_id}>
            <tr
              onClick={() => onSelectJob(job.job_id)}
              className={
                "cursor-pointer transition-colors hover:bg-slate-50 " +
                (job.job_id === selectedJobId ? "bg-brand-50" : "")
              }
            >
              <td className="px-6 py-3 font-medium text-slate-800">{job.filename}</td>
              <td className="px-6 py-3">
                <Badge tone={STATUS_TONE[job.status] ?? "slate"}>
                  {STATUS_LABEL[job.status] ?? job.status}
                </Badge>
              </td>
              <td className="px-6 py-3 text-slate-500">
                {new Date(job.created_at).toLocaleString()}
              </td>
              <td className="px-6 py-3 text-right">
                {job.status === "COMPLETED" && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={(e) => { e.stopPropagation(); onSelectJob(job.job_id); }}
                  >
                    View
                  </Button>
                )}
              </td>
            </tr>
            {job.status === "PII_REVIEW" && (
              <tr>
                <td colSpan={4} className="px-6 pb-4">
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    <p className="font-semibold">
                      Possible personal identifiers were found in this transcript.
                    </p>
                    <p className="mt-1">
                      Review the items below. You can proceed if you're comfortable
                      processing them, or cancel to delete the upload and re-upload a
                      redacted copy. (A participant's age is fine and is not flagged.)
                    </p>
                    {job.pii_findings && job.pii_findings.length > 0 && (
                      <ul className="mt-2 list-disc pl-5">
                        {job.pii_findings.map((f) => (
                          <li key={f.type}>
                            {PII_LABEL[f.type] ?? f.type.toLowerCase().replace(/_/g, " ")}
                            {f.count > 1 ? ` (${f.count} occurrences)` : ""}
                          </li>
                        ))}
                      </ul>
                    )}
                    <div className="mt-3 flex gap-2">
                      <Button
                        size="sm"
                        disabled={deciding === job.job_id}
                        onClick={() => handleDecision(job.job_id, "proceed")}
                      >
                        Proceed anyway
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={deciding === job.job_id}
                        onClick={() => handleDecision(job.job_id, "cancel")}
                      >
                        Cancel & delete
                      </Button>
                    </div>
                  </div>
                </td>
              </tr>
            )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
