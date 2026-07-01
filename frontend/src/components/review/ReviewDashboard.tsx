import { useState, useEffect, useCallback } from "react";
import {
  listCategories,
  listInterviews,
  listPredictions,
  votePrediction,
  type InterviewSummary,
  type Prediction,
} from "../../lib/api";
import InterviewList from "./InterviewList";
import PredictionCard from "./PredictionCard";
import RejectionModal, { type RejectionDetails } from "./RejectionModal";
import { Alert, Button, Card, Label, Select, Spinner } from "../ui";

type RejectTarget = { kind: "single"; id: string } | { kind: "bulk"; ids: string[] };

export default function ReviewDashboard() {
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState("");
  const [interviews, setInterviews] = useState<InterviewSummary[]>([]);
  const [interviewId, setInterviewId] = useState<string | null>(null);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rejectTarget, setRejectTarget] = useState<RejectTarget | null>(null);

  useEffect(() => {
    listCategories().then(setCategories).catch(() => setCategories([]));
  }, []);

  // Load interviews when a category is chosen.
  useEffect(() => {
    setInterviews([]);
    setInterviewId(null);
    setPredictions([]);
    if (!category) return;
    setLoading(true);
    listInterviews(category)
      .then(setInterviews)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [category]);

  const loadPredictions = useCallback(
    (iv: string) => {
      setLoading(true);
      setError(null);
      return listPredictions(category, { interview: iv })
        .then((preds) => {
          setPredictions(preds);
          setSelected(new Set());
        })
        .catch((e) => setError(String(e)))
        .finally(() => setLoading(false));
    },
    [category]
  );

  const openInterview = (iv: string) => {
    setInterviewId(iv);
    loadPredictions(iv);
  };

  const backToList = () => {
    setInterviewId(null);
    setPredictions([]);
    // Refresh interview summaries to reflect any votes cast.
    if (category) listInterviews(category).then(setInterviews).catch(() => {});
  };

  const refresh = useCallback(() => {
    if (interviewId) return loadPredictions(interviewId);
    return Promise.resolve();
  }, [interviewId, loadPredictions]);

  const approve = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      await votePrediction(id, { category, decision: "approve" });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const bulkApprove = async () => {
    const ids = [...selected];
    if (ids.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const id of ids) {
        await votePrediction(id, { category, decision: "approve" });
      }
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const submitRejection = async (details: RejectionDetails) => {
    if (!rejectTarget) return;
    const ids = rejectTarget.kind === "single" ? [rejectTarget.id] : rejectTarget.ids;
    setRejectTarget(null);
    setBusy(true);
    setError(null);
    try {
      for (const id of ids) {
        await votePrediction(id, {
          category,
          decision: "reject",
          reasons: details.reasons,
          comment: details.comment,
          suggested_concept_id: details.suggested_concept_id,
          no_relevant_concept: details.no_relevant_concept,
        });
      }
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectableCount = predictions.filter((p) => !p.caller_voted).length;

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="max-w-sm">
          <Label>Category</Label>
          <Select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full"
          >
            <option value="">Select a category…</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </div>
      </Card>

      {error && <Alert>{error}</Alert>}

      {loading && (
        <Card className="p-6">
          <Spinner />
        </Card>
      )}

      {!interviewId && category && !loading && (
        <InterviewList interviews={interviews} onSelect={openInterview} />
      )}

      {interviewId && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <Button variant="secondary" size="sm" onClick={backToList}>
              &larr; Back
            </Button>
            <strong className="text-base text-slate-800">{interviewId}</strong>
          </div>

          {selectableCount > 0 && (
            <Card className="flex flex-wrap items-center gap-3 p-4">
              <span className="text-sm text-slate-600">{selected.size} selected</span>
              <Button
                variant="success"
                size="sm"
                onClick={bulkApprove}
                disabled={busy || selected.size === 0}
              >
                Approve selected
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={() => setRejectTarget({ kind: "bulk", ids: [...selected] })}
                disabled={busy || selected.size === 0}
              >
                Reject selected
              </Button>
            </Card>
          )}

          {predictions.map((p) => (
            <PredictionCard
              key={p.prediction_id}
              prediction={p}
              selectable={!p.caller_voted}
              selected={selected.has(p.prediction_id)}
              onToggleSelect={toggleSelect}
              onApprove={approve}
              onReject={(id) => setRejectTarget({ kind: "single", id })}
              busy={busy}
            />
          ))}

          {!loading && predictions.length === 0 && (
            <Card className="p-10 text-center text-sm text-slate-500">
              No predictions for this interview.
            </Card>
          )}
        </div>
      )}

      {rejectTarget && (
        <RejectionModal
          title={
            rejectTarget.kind === "bulk"
              ? `Reject ${rejectTarget.ids.length} predictions`
              : "Reject prediction"
          }
          onSubmit={submitRejection}
          onCancel={() => setRejectTarget(null)}
        />
      )}
    </div>
  );
}
