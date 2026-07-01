import { useEffect, useRef } from "react";
import { Button, ModalOverlay } from "../ui";

interface Props {
  paragraphs: string[];
  highlight: string;
  onClose: () => void;
}

export default function FullInterviewModal({ paragraphs, highlight, onClose }: Props) {
  const markRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (markRef.current) {
      markRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [paragraphs, highlight]);

  const norm = highlight.trim();
  let highlighted = false;

  return (
    <ModalOverlay onClose={onClose}>
      <div
        className="max-h-[85vh] w-[720px] max-w-[90vw] overflow-y-auto rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-800">Full interview</h3>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

        {paragraphs.length === 0 ? (
          <p className="text-sm text-slate-500">Transcript not available yet.</p>
        ) : (
          <div className="space-y-3">
            {paragraphs.map((para, i) => {
              const isMatch = !highlighted && norm.length > 0 && para.includes(norm);
              if (isMatch) {
                highlighted = true;
                return (
                  <p key={i} className="text-sm leading-relaxed text-slate-700">
                    <mark
                      ref={markRef}
                      className="rounded bg-amber-200 px-0.5 py-px"
                    >
                      {para}
                    </mark>
                  </p>
                );
              }
              return (
                <p key={i} className="text-sm leading-relaxed text-slate-700">
                  {para}
                </p>
              );
            })}
          </div>
        )}
      </div>
    </ModalOverlay>
  );
}
