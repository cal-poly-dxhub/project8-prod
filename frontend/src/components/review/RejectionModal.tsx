import { useState } from "react";
import { Button, Label, ModalOverlay } from "../ui";

export const REJECTION_REASONS = [
  "Definition of code not met",
  "Applies to caregiver, not hero",
  "Applies to hero, not caregiver",
  "Rationale is correct but the wrong concept was used.",
  "Technical Transcription Error",
  "Transcript is unclear",
];

export interface RejectionDetails {
  reasons: string[];
  comment?: string;
  suggested_concept_id?: string | null;
  no_relevant_concept?: boolean;
}

interface Props {
  title?: string;
  onSubmit: (details: RejectionDetails) => void;
  onCancel: () => void;
}

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100";

export default function RejectionModal({ title, onSubmit, onCancel }: Props) {
  const [reasons, setReasons] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [suggested, setSuggested] = useState("");
  const [noRelevant, setNoRelevant] = useState(false);

  const toggleReason = (reason: string) => {
    setReasons((prev) =>
      prev.includes(reason) ? prev.filter((r) => r !== reason) : [...prev, reason]
    );
  };

  const canSubmit = reasons.length > 0;

  const submit = () => {
    if (!canSubmit) return;
    onSubmit({
      reasons,
      comment: comment.trim() || undefined,
      suggested_concept_id: suggested.trim() || null,
      no_relevant_concept: noRelevant,
    });
  };

  return (
    <ModalOverlay onClose={onCancel}>
      <div
        className="max-h-[85vh] w-[480px] max-w-[90vw] overflow-y-auto rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-4 text-lg font-semibold text-slate-800">
          {title ?? "Reject prediction"}
        </h3>

        <Label>Reasons (at least one required)</Label>
        <div className="mb-4 space-y-1.5">
          {REJECTION_REASONS.map((reason) => (
            <label
              key={reason}
              className="flex cursor-pointer items-start gap-2 text-sm text-slate-700"
            >
              <input
                type="checkbox"
                checked={reasons.includes(reason)}
                onChange={() => toggleReason(reason)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
              />
              <span>{reason}</span>
            </label>
          ))}
        </div>

        <Label>Comment (optional)</Label>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
          className={inputClass + " mb-4"}
        />

        <Label>Suggested concept ID (optional)</Label>
        <input
          type="text"
          value={suggested}
          onChange={(e) => setSuggested(e.target.value)}
          placeholder="e.g. C0012345"
          className={inputClass + " mb-4"}
        />

        <label className="mb-5 flex cursor-pointer items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={noRelevant}
            onChange={(e) => setNoRelevant(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
          />
          <span>No relevant concept</span>
        </label>

        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" onClick={submit} disabled={!canSubmit}>
            Submit rejection
          </Button>
        </div>
      </div>
    </ModalOverlay>
  );
}
