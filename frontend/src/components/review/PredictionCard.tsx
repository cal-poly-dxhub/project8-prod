import { useState } from "react";
import type { Prediction } from "../../lib/api";
import FullInterviewModal from "./FullInterviewModal";
import { Badge, Button, Card } from "../ui";

interface Props {
  prediction: Prediction;
  selectable: boolean;
  selected: boolean;
  onToggleSelect: (predictionId: string) => void;
  onApprove: (predictionId: string) => void;
  onReject: (predictionId: string) => void;
  busy: boolean;
}

type Tone = "slate" | "green" | "red" | "amber";

const STATUS_TONE: Record<string, Tone> = {
  APPROVED: "green",
  REJECTED: "red",
  CONFLICT: "amber",
  PENDING: "slate",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "slate"}>{status}</Badge>;
}

export default function PredictionCard({
  prediction,
  selectable,
  selected,
  onToggleSelect,
  onApprove,
  onReject,
  busy,
}: Props) {
  const [showTranscript, setShowTranscript] = useState(false);
  const p = prediction;

  return (
    <Card
      className={
        "p-5 transition-shadow hover:shadow-md " +
        (selected ? "ring-2 ring-brand-200" : "")
      }
    >
      <div className="mb-2 flex items-center gap-2">
        {selectable && (
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(p.prediction_id)}
            title="Select for bulk action"
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
          />
        )}
        <span className="text-sm text-slate-400">#{p.idx + 1}</span>
        <strong className="text-[15px] text-slate-800">
          {p.concept_name ?? "(no concept name)"}
        </strong>
        {p.concept_id && (
          <span className="text-xs text-slate-400">{p.concept_id}</span>
        )}
        <span className="ml-auto">
          <StatusBadge status={p.status} />
        </span>
      </div>

      {p.quote && (
        <blockquote className="my-2 border-l-[3px] border-brand-200 pl-3 text-sm italic text-slate-600">
          "{p.quote}"
        </blockquote>
      )}

      <div className="mb-3 space-y-0.5 text-sm text-slate-600">
        {p.age && (
          <div>
            <strong className="font-semibold text-slate-700">Age:</strong> {p.age}
          </div>
        )}
        {p.rationale && (
          <div>
            <strong className="font-semibold text-slate-700">Rationale:</strong> {p.rationale}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="success" size="sm" onClick={() => onApprove(p.prediction_id)} disabled={busy}>
          Approve
        </Button>
        <Button variant="danger" size="sm" onClick={() => onReject(p.prediction_id)} disabled={busy}>
          Reject
        </Button>
        <Button variant="secondary" size="sm" onClick={() => setShowTranscript(true)}>
          View full interview
        </Button>
        <span className="ml-auto text-xs text-slate-400">
          {p.review_count} review{p.review_count === 1 ? "" : "s"}
        </span>
      </div>

      {/* Blind review: others' decisions hidden until the caller votes. */}
      {!p.caller_voted ? (
        <div className="mt-3 text-xs italic text-slate-400">
          Submit your review to see others' decisions.
        </div>
      ) : (
        <div className="mt-3 space-y-1 text-xs text-slate-600">
          {(p.approvals?.length ?? 0) > 0 && (
            <div>
              <strong className="font-semibold text-slate-700">Approved by:</strong>{" "}
              {p.approvals!.map((a) => a.reviewer).join(", ")}
            </div>
          )}
          {(p.rejections?.length ?? 0) > 0 && (
            <div>
              <strong className="font-semibold text-slate-700">Rejected by:</strong>
              {p.rejections!.map((r, i) => (
                <div key={i} className="ml-2 mt-0.5">
                  {r.reviewer}
                  {r.reasons && r.reasons.length > 0 && <> — {r.reasons.join("; ")}</>}
                  {r.comment && <> ({r.comment})</>}
                  {r.suggested_concept_id && <> [suggested: {r.suggested_concept_id}]</>}
                  {r.no_relevant_concept && <> [no relevant concept]</>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {showTranscript && (
        // TODO: transcripts endpoint pending; pass empty array until wired.
        <FullInterviewModal
          paragraphs={[]}
          highlight={p.quote ?? ""}
          onClose={() => setShowTranscript(false)}
        />
      )}
    </Card>
  );
}
