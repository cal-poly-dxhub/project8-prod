import { useState, useCallback, useEffect } from "react";
import { createUpload, uploadFile, listCategories, createCategory } from "../lib/api";
import { Card, Label, Select, Spinner, cx } from "./ui";

interface Props {
  onUploadComplete: () => void;
}

const NEW_CATEGORY = "__new__";

export default function Upload({ onUploadComplete }: Props) {
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [categories, setCategories] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [newCategory, setNewCategory] = useState("");

  useEffect(() => {
    listCategories().then(setCategories).catch(() => setCategories([]));
  }, []);

  // The effective category: either the chosen existing one or the typed new one.
  const effectiveCategory =
    selected === NEW_CATEGORY ? newCategory.trim() : selected.trim();

  const handleFile = useCallback(async (file: File) => {
    if (!file.name.endsWith(".docx")) {
      alert("Please upload a .docx file");
      return;
    }
    if (!effectiveCategory) {
      alert("Please choose or create a category before uploading.");
      return;
    }
    setUploading(true);
    try {
      // Persist a brand-new category so it appears in the dropdown next time.
      if (selected === NEW_CATEGORY && !categories.includes(effectiveCategory)) {
        await createCategory(effectiveCategory);
        setCategories((c) => [...c, effectiveCategory].sort());
        setSelected(effectiveCategory);
        setNewCategory("");
      }
      const { upload_url } = await createUpload(file.name, effectiveCategory);
      await uploadFile(upload_url, file);
      onUploadComplete();
    } catch (e) {
      alert(`Upload failed: ${e}`);
    } finally {
      setUploading(false);
    }
  }, [onUploadComplete, effectiveCategory, selected, categories]);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <Card className="p-6">
      <div
        role="note"
        className="mb-5 flex gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-relaxed text-amber-900"
      >
        <span aria-hidden className="mt-0.5 text-base">⚠️</span>
        <p>
          <strong className="font-semibold">Protected health information (PHI):</strong>{" "}
          Interview transcripts may contain identifying details. Uploaded files are
          processed by AWS Bedrock within this AWS account and are not used to train
          any model. Only upload files you are authorized to share, and follow your
          organization's data handling policies.
        </p>
      </div>

      <div className="mb-5 max-w-sm">
        <Label>Category</Label>
        <div className="flex flex-wrap gap-2">
          <Select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="min-w-60 flex-1"
          >
            <option value="">Select a category…</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
            <option value={NEW_CATEGORY}>+ Create new category</option>
          </Select>
          {selected === NEW_CATEGORY && (
            <input
              type="text"
              placeholder="New category name"
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              className="min-w-48 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100"
            />
          )}
        </div>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={cx(
          "flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          dragOver
            ? "border-brand-500 bg-brand-50"
            : "border-slate-300 bg-slate-50"
        )}
      >
        {uploading ? (
          <Spinner label="Uploading…" />
        ) : (
          <>
            <svg
              className="mb-3 h-10 w-10 text-slate-400"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              aria-hidden
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
              />
            </svg>
            <p className="font-medium text-slate-700">
              Drag and drop a .docx interview file here
            </p>
            <p className="my-2 text-xs uppercase tracking-wide text-slate-400">or</p>
            <label className="cursor-pointer rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-700">
              Browse files
              <input type="file" accept=".docx" onChange={onFileInput} className="hidden" />
            </label>
          </>
        )}
      </div>
    </Card>
  );
}
