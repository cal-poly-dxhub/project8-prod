import { useState, useEffect } from "react";
import { getJobStatus, getResultsUrl, Job } from "../lib/api";
import { Button, Card, Spinner } from "./ui";

interface Props {
  jobId: string;
}

interface Annotation {
  concept_id: number;
  concept_name: string;
  group: string;
  mentioned_verbatim?: boolean;
  raw_highlight?: string;
  rationale?: string;
  paragraph_id?: string;
}

export default function ResultsViewer({ jobId }: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setAnnotations(null);
      const status = await getJobStatus(jobId);
      if (cancelled) return;
      setJob(status);

      if (status.status === "COMPLETED") {
        const url = await getResultsUrl(jobId);
        const resp = await fetch(url);
        const data = await resp.json();
        if (!cancelled) setAnnotations(data);
      }
      setLoading(false);
    }
    load();
    return () => { cancelled = true; };
  }, [jobId]);

  const Wrap = ({ children }: { children: React.ReactNode }) => (
    <Card className="p-6">{children}</Card>
  );

  if (loading) return <Wrap><Spinner label="Loading results…" /></Wrap>;
  if (!job) return null;

  if (job.status === "PROCESSING")
    return <Wrap><p className="text-sm text-slate-500">Job is still processing. Results will appear here when done.</p></Wrap>;
  if (job.status === "FAILED")
    return <Wrap><p className="text-sm text-rose-600">Job failed: {job.error_message}</p></Wrap>;
  if (job.status === "UPLOADING")
    return <Wrap><p className="text-sm text-slate-500">File is still uploading…</p></Wrap>;

  if (!annotations) return <Wrap><p className="text-sm text-slate-500">No results available.</p></Wrap>;

  const present = Array.isArray(annotations) ? annotations : [];
  const groups = [...new Set(present.map((a) => a.group))];

  const handleDownload = async () => {
    const url = await getResultsUrl(jobId);
    window.open(url, "_blank");
  };

  return (
    <Card className="p-6">
      <div className="mb-1 flex items-center justify-between gap-4">
        <h2 className="text-base font-semibold text-slate-800">
          Results: <span className="font-normal text-slate-600">{job.filename}</span>
        </h2>
        <Button variant="secondary" size="sm" onClick={handleDownload}>
          Download JSON
        </Button>
      </div>
      <p className="mb-5 text-sm text-slate-500">
        {present.length} concepts identified across {groups.length} groups
      </p>

      <div className="space-y-6">
        {groups.map((group) => (
          <div key={group}>
            <h3 className="mb-2 text-sm font-semibold capitalize text-slate-700">
              {group.replace(/_/g, " ")}
            </h3>
            <div className="overflow-hidden rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-2.5">ID</th>
                    <th className="px-4 py-2.5">Concept</th>
                    <th className="px-4 py-2.5">Quote</th>
                    <th className="px-4 py-2.5">Rationale</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {present.filter((a) => a.group === group).map((a, i) => (
                    <tr key={`${a.concept_id}-${i}`} className="align-top">
                      <td className="px-4 py-2.5 text-slate-500">{a.concept_id}</td>
                      <td className="px-4 py-2.5 font-medium text-slate-800">{a.concept_name}</td>
                      <td className="max-w-[250px] truncate px-4 py-2.5 italic text-slate-600">
                        {a.raw_highlight ?? "-"}
                      </td>
                      <td className="max-w-[300px] px-4 py-2.5 text-slate-600">
                        {a.rationale ?? "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
