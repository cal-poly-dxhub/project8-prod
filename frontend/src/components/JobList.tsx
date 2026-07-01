import { useState, useEffect } from "react";
import { listJobs, Job } from "../lib/api";
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
};

export default function JobList({ onSelectJob, selectedJobId }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      const data = await listJobs();
      setJobs(data);
    } finally {
      setLoading(false);
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

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-slate-200 px-6 py-4">
        <h2 className="text-base font-semibold text-slate-800">Your Jobs</h2>
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
          {jobs.map((job) => (
            <tr
              key={job.job_id}
              onClick={() => onSelectJob(job.job_id)}
              className={
                "cursor-pointer transition-colors hover:bg-slate-50 " +
                (job.job_id === selectedJobId ? "bg-brand-50" : "")
              }
            >
              <td className="px-6 py-3 font-medium text-slate-800">{job.filename}</td>
              <td className="px-6 py-3">
                <Badge tone={STATUS_TONE[job.status] ?? "slate"}>{job.status}</Badge>
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
          ))}
        </tbody>
      </table>
    </Card>
  );
}
