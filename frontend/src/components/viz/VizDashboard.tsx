import { useEffect, useRef, useState } from "react";
import { listCategories, getAggregate, type AggregateData } from "../../lib/api";
import {
  buildModel,
  conceptFrequencyChart,
  cooccurrenceChart,
  landscapeChart,
  hierarchyChart,
  saturationChart,
  ageDistributionChart,
  conceptByAgeChart,
  heroProgressionChart,
  comorbidityChart,
  legendRow,
} from "./charts";
import { Alert, Card, Label, Select, Spinner } from "../ui";

function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-5 mt-12 border-t-2 border-slate-200 pt-7 text-center">
      <div className="text-xl font-bold text-slate-900">{title}</div>
      <div className="mt-1 text-sm text-slate-500">{subtitle}</div>
    </div>
  );
}

// Mounts a vanilla DOM node (built by charts.ts) into a React-managed div.
function ChartMount({ node }: { node: HTMLElement | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    host.replaceChildren();
    if (node) host.appendChild(node);
    return () => { host.replaceChildren(); };
  }, [node]);
  return <div ref={ref} />;
}

export default function VizDashboard() {
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState("");
  const [data, setData] = useState<AggregateData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hmMin, setHmMin] = useState(6);

  useEffect(() => {
    listCategories().then(setCategories).catch(() => setCategories([]));
  }, []);

  useEffect(() => {
    setData(null);
    setError(null);
    if (!category) return;
    setLoading(true);
    getAggregate(category)
      .then((d) => {
        setData(d);
        // Default co-occurrence threshold to ~half the interviews.
        setHmMin(Math.max(1, Math.round(d.n_interviews / 2)));
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [category]);

  const model = data ? buildModel(data) : null;
  const hasConcepts = !!model && model.allConcepts.length > 0;

  // Build chart nodes once per (data, control) change. The quotes panel for the
  // frequency chart is shared so its click handlers can show/hide it.
  const quotesPanel = useRef<HTMLDivElement | null>(null);
  if (!quotesPanel.current) {
    const el = document.createElement("div");
    el.style.cssText =
      "margin-top:16px;border:1px solid #e0e0e0;border-radius:10px;background:#fafafa;font-family:Inter,sans-serif;display:none;overflow:hidden;width:680px;max-width:100%;";
    quotesPanel.current = el;
  }

  const freqNode = model && hasConcepts ? conceptFrequencyChart(model, quotesPanel.current!) : null;
  const coocNode = model && hasConcepts ? cooccurrenceChart(model, hmMin) : null;
  const landscapeNode = model && hasConcepts ? landscapeChart(model) : null;
  const hierarchyNode = model && hasConcepts ? hierarchyChart(model) : null;
  const saturationNode = model && hasConcepts ? saturationChart(model) : null;
  const showAge = !!model && hasConcepts && model.hasAges;
  const ageDistNode = showAge ? ageDistributionChart(model!) : null;
  const conceptByAgeNode = showAge ? conceptByAgeChart(model!) : null;
  // Hero-level charts. Comorbidity needs any hero ids; progression needs a hero
  // with 2+ aged interviews.
  const hasHeroes = !!model && hasConcepts && model.heroIds.some((h) => h !== null);
  const showHeroTimeline = !!model && hasConcepts && model.hasHeroTimeline;
  const heroProgressionNode = showHeroTimeline ? heroProgressionChart(model!) : null;
  const comorbidityNode = hasHeroes ? comorbidityChart(model!) : null;

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
              <option key={c} value={c}>{c}</option>
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

      {!loading && category && data && !hasConcepts && (
        <Card className="p-10 text-center text-sm text-slate-500">
          No (non-rejected) predictions to visualize for this category yet.
        </Card>
      )}

      {!loading && data && hasConcepts && model && (
        <Card className="mx-auto max-w-[1440px] p-6">
          <div className="pt-2 text-center text-sm text-slate-500">
            {category} · N = {data.n_interviews} interview{data.n_interviews !== 1 ? "s" : ""} · counts every prediction not yet rejected
          </div>

          <SectionHeader
            title="Concept Frequency by Category"
            subtitle={`How many caregivers mentioned each concept · grouped by category · concepts coded in at least half of caregivers shown`}
          />
          <ChartMount node={freqNode} />
          <div className="flex justify-center">
            <ChartMount node={quotesPanel.current} />
          </div>

          <SectionHeader
            title="Concept Co-occurrence"
            subtitle="How often concepts appear together · columns = top 5 per category · color intensity = normalized co-occurrence within each panel"
          />
          <div className="mb-2.5 flex items-center justify-center gap-2.5 text-sm text-slate-600">
            <label htmlFor="hmMin">Min caregivers (both axes): {hmMin}</label>
            <input
              id="hmMin"
              type="range"
              min={1}
              max={Math.max(1, data.n_interviews)}
              step={1}
              value={hmMin}
              onChange={(e) => setHmMin(Number(e.target.value))}
              className="accent-brand-600"
            />
          </div>
          <ChartMount node={coocNode} />

          <SectionHeader
            title="Concept Landscape"
            subtitle="All coded concepts mapped by domain · bubble size and height = caregiver count · color = category"
          />
          <ChartMount node={landscapeNode} />
          <ChartMount node={legendRow()} />

          <SectionHeader
            title="Concept Hierarchy"
            subtitle="Category → Domain → Concept · click a tile to drill in · click the background to go back up"
          />
          <ChartMount node={hierarchyNode} />

          <SectionHeader
            title="Concept Saturation"
            subtitle="How many new concepts emerged as each caregiver was interviewed · a flattening curve indicates saturation"
          />
          <ChartMount node={saturationNode} />
          <ChartMount node={legendRow()} />

          {showAge && (
            <>
              <SectionHeader
                title="Interviewee Age Distribution"
                subtitle="Ages of interviewees at interview time · binned in 2-year steps · colored by age group · only interviews with a recorded age"
              />
              <ChartMount node={ageDistNode} />

              <SectionHeader
                title="Concept Prevalence by Age Group"
                subtitle="Share of interviews in each age group that mentioned each concept · top 20 concepts overall · darker = more prevalent within that age group"
              />
              <ChartMount node={conceptByAgeNode} />
            </>
          )}

          {showHeroTimeline && (
            <>
              <SectionHeader
                title="Concept Progression Over Age"
                subtitle="For heroes interviewed at multiple ages · concepts mentioned per category at each age · one panel per hero"
              />
              <ChartMount node={heroProgressionNode} />
            </>
          )}

          {hasHeroes && (
            <>
              <SectionHeader
                title="Comorbidity Co-occurrence"
                subtitle="Concept pairs that appear together within the same hero (concepts unioned across a hero's interviews) · darker = stronger comorbidity"
              />
              <ChartMount node={comorbidityNode} />
            </>
          )}
        </Card>
      )}
    </div>
  );
}
