import { useState } from "react";
import { Authenticator } from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";
import Upload from "./components/Upload";
import JobList from "./components/JobList";
import ResultsViewer from "./components/ResultsViewer";
import ReviewDashboard from "./components/review/ReviewDashboard";
import VizDashboard from "./components/viz/VizDashboard";
import { Button, cx } from "./components/ui";

type View = "pipeline" | "review" | "viz";

const TABS: { id: View; label: string }[] = [
  { id: "pipeline", label: "Pipeline" },
  { id: "review", label: "Review" },
  { id: "viz", label: "Visualizations" },
];

function PipelineView() {
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="space-y-6">
      <Upload onUploadComplete={() => setRefreshKey((k) => k + 1)} />
      <JobList
        key={refreshKey}
        onSelectJob={(id) => setSelectedJobId(id)}
        selectedJobId={selectedJobId}
      />
      {selectedJobId && <ResultsViewer jobId={selectedJobId} />}
    </div>
  );
}

function AppContent({ signOut }: { signOut?: () => void }) {
  const [view, setView] = useState<View>("pipeline");

  return (
    <div className="min-h-full">
      {/* Gradient header bar */}
      <header className="bg-gradient-to-r from-brand-700 via-brand-600 to-indigo-500 shadow-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/20 text-lg font-bold text-white ring-1 ring-white/30">
              P8
            </div>
            <h1 className="text-lg font-bold tracking-tight text-white">
              Annotation Pipeline
            </h1>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={signOut}
            className="text-white hover:bg-white/15"
          >
            Sign out
          </Button>
        </div>
      </header>

      {/* Pill tabs */}
      <nav className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl gap-1 px-6 py-3">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setView(tab.id)}
              className={cx(
                "rounded-full px-4 py-1.5 text-sm font-semibold transition-colors",
                view === tab.id
                  ? "bg-brand-600 text-white shadow-sm"
                  : "text-slate-600 hover:bg-slate-100"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </nav>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {view === "pipeline" ? (
          <PipelineView />
        ) : view === "review" ? (
          <ReviewDashboard />
        ) : (
          <VizDashboard />
        )}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Authenticator hideSignUp>
      {({ signOut }) => <AppContent signOut={signOut} />}
    </Authenticator>
  );
}
