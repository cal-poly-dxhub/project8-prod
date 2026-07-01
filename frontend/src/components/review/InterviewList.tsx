import type { InterviewSummary } from "../../lib/api";
import { Badge, Card } from "../ui";

interface Props {
  interviews: InterviewSummary[];
  onSelect: (interviewId: string) => void;
}

export default function InterviewList({ interviews, onSelect }: Props) {
  if (interviews.length === 0) {
    return (
      <Card className="p-10 text-center text-sm text-slate-500">
        No interviews found for this category.
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {interviews.map((iv) => (
        <Card
          key={iv.interview_id}
          className="cursor-pointer p-4 transition-all hover:border-brand-300 hover:shadow-md"
        >
          <button
            type="button"
            onClick={() => onSelect(iv.interview_id)}
            className="block w-full text-left"
          >
            <div className="mb-3 flex items-center justify-between">
              <strong className="text-sm text-slate-800">{iv.interview_id}</strong>
              <span className="text-sm font-medium text-brand-600">Open &rarr;</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="slate">Total: {iv.total}</Badge>
              <Badge tone="indigo">Reviewed: {iv.reviewed}</Badge>
              <Badge tone="green">Approved: {iv.approved}</Badge>
              <Badge tone="red">Rejected: {iv.rejected}</Badge>
              <Badge tone="amber">Conflict: {iv.conflict}</Badge>
              <Badge tone="slate">Pending: {iv.pending}</Badge>
            </div>
          </button>
        </Card>
      ))}
    </div>
  );
}
