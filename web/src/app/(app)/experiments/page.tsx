"use client";

import { useCallback, useEffect, useState } from "react";
import { DownloadSimple, Stop } from "@phosphor-icons/react";
import { api, type BatchDetail, type JobState } from "@/lib/api";
import { estimateSeconds, fmt } from "@/lib/format";
import { Button, Input, Label, Select, Help, FieldError, Panel, Notice, Skeleton, Empty, buttonClass } from "@/components/ui";
import { ZChart } from "@/components/history-chart";

const LENGTHS = [50, 150, 300, 500];

export default function ExperimentsPage() {
  const [promptCount, setPromptCount] = useState<number | null>(null);
  const [nPrompts, setNPrompts] = useState(100);
  const [lengths, setLengths] = useState<number[]>([150]);
  const [runs, setRuns] = useState(1);
  const [seed, setSeed] = useState(100);
  const [resume, setResume] = useState("");
  const [batches, setBatches] = useState<Array<{ batch_id: string; rows: number; settings: Record<string, unknown> | null }>>([]);
  const [job, setJob] = useState<JobState | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await api.experiments();
      setBatches(r.batches);
      setJob(r.job);
      if (!selected && r.batches[0]) setSelected(r.batches[0].batch_id);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [selected]);

  useEffect(() => {
    api.prompts().then((p) => setPromptCount(p.count)).catch(() => setPromptCount(0));
    const t = setTimeout(refresh, 0);
    return () => clearTimeout(t);
  }, [refresh]);

  // poll while a job runs
  useEffect(() => {
    if (!job?.running) return;
    const t = setInterval(async () => {
      try {
        const r = await api.experiments();
        setJob(r.job);
        setBatches(r.batches);
        if (r.job.batch_id) {
          setSelected(r.job.batch_id);
          setDetail(await api.experiment(r.job.batch_id));
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [job?.running]);

  useEffect(() => {
    if (!selected) return;
    api.experiment(selected).then(setDetail).catch((e) => setError((e as Error).message));
  }, [selected]);

  const total = nPrompts * lengths.length * 2 * runs;
  const eta = estimateSeconds(nPrompts, lengths, runs);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!lengths.length) return setError("Choose at least one length.");
    setBusy(true);
    try {
      const j = await api.startExperiment({ n_prompts: nPrompts, lengths, runs, seed_base: seed, resume: resume || null });
      setJob(j);
      if (j.batch_id) setSelected(j.batch_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!job?.batch_id) return;
    try {
      setJob(await api.stopExperiment(job.batch_id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Experiments</h1>
        <p className="mt-1 max-w-[65ch] text-sm text-fg-muted">
          Measure detection instead of demonstrating it: every prompt is generated in both modes, scored, and logged under a
          batch id. The summary gives the true-positive rate (watermarked rows flagged) and the false-positive rate (normal
          rows flagged) per length.
        </p>
      </div>

      {error && <Notice tone="danger">{error}</Notice>}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <form onSubmit={start} className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="x-n">Prompts {promptCount != null ? `(of ${promptCount})` : ""}</Label>
              <Input id="x-n" type="number" min={1} max={promptCount ?? 100} value={nPrompts} onChange={(e) => setNPrompts(Number(e.target.value))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="x-runs">Runs per cell</Label>
              <Input id="x-runs" type="number" min={1} max={5} value={runs} onChange={(e) => setRuns(Number(e.target.value))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="x-seed">Seed base</Label>
              <Input id="x-seed" type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="x-resume">Resume a batch</Label>
              <Select id="x-resume" value={resume} onChange={(e) => setResume(e.target.value)}>
                <option value="">(new batch)</option>
                {batches.map((b) => (
                  <option key={b.batch_id} value={b.batch_id}>
                    {b.batch_id} ({b.rows} rows)
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Lengths (max tokens)</legend>
            <div className="flex flex-wrap gap-2">
              {LENGTHS.map((L) => {
                const on = lengths.includes(L);
                return (
                  <button
                    key={L}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setLengths(on ? lengths.filter((x) => x !== L) : [...lengths, L].sort((a, b) => a - b))}
                    className={`rounded-full border px-3 py-1 font-mono text-sm ${on ? "border-accent bg-accent-soft text-accent-soft-fg" : "border-line-strong text-fg-muted"}`}
                  >
                    {L}
                  </button>
                );
              })}
            </div>
          </fieldset>
          <Help>
            {fmt.int(total)} generations, roughly {fmt.minutes(eta)} on a CPU. For anything over an hour use the command
            line, which can be interrupted and resumed: <code className="font-mono">python experiment.py --lengths {lengths.join(" ")} --runs {runs} --seed {seed}</code>
          </Help>
          <FieldError>{error && !job?.running ? null : null}</FieldError>
          <div className="flex gap-2">
            <Button type="submit" size="lg" disabled={busy || job?.running || !promptCount}>
              {job?.running ? "Running" : "Run experiment"}
            </Button>
            {job?.running && (
              <Button type="button" variant="secondary" size="lg" onClick={stop}>
                <Stop size={16} /> Stop after this generation
              </Button>
            )}
          </div>
        </form>

        <Panel className="p-5">
          <h2 className="text-sm font-medium text-fg-muted">Progress</h2>
          {job?.running ? (
            <div className="mt-3 space-y-3">
              <div className="h-2 w-full overflow-hidden rounded-full bg-bg-muted">
                <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${job.total ? (job.done / job.total) * 100 : 0}%` }} />
              </div>
              <p className="tabular font-mono text-sm">
                {job.done} / {job.total}
                {job.last ? ` · p${job.last.prompt_idx} L${job.last.length} ${job.last.mode} z=${fmt.z(job.last.z)} ${job.last.label}` : ""}
              </p>
              <p className="text-xs text-fg-faint">Batch {job.batch_id}. Rows are written as they finish; closing this page does not lose them.</p>
            </div>
          ) : job?.error ? (
            <div className="mt-3">
              <Notice tone="danger">{job.error}</Notice>
            </div>
          ) : job?.finished ? (
            <p className="mt-3 text-sm text-fg-muted">
              Last batch {job.batch_id} finished: {job.done} of {job.total} generations.
            </p>
          ) : (
            <p className="mt-3 text-sm text-fg-muted">No batch running.</p>
          )}
        </Panel>
      </div>

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-tight">Results</h2>
          <div className="flex items-center gap-2">
            <Select value={selected} onChange={(e) => setSelected(e.target.value)} className="w-56">
              {batches.map((b) => (
                <option key={b.batch_id} value={b.batch_id}>
                  {b.batch_id} ({b.rows} rows)
                </option>
              ))}
            </Select>
            {selected && (
              <a href={api.exportExperimentUrl(selected)} className={buttonClass({ variant: "secondary", size: "sm" })}>
                <DownloadSimple size={16} /> Export summary
              </a>
            )}
          </div>
        </div>

        {!batches.length && <Empty title="No batches yet">Run a small one above, or use the command line for a long run.</Empty>}

        {selected && !detail && <Skeleton className="h-48" />}

        {detail && (
          <>
            {detail.settings && (
              <p className="text-xs text-fg-faint">
                {detail.rows} rows · created {String(detail.settings.created)} · prompt file hash {String(detail.settings.prompt_file_hash)} · seed base{" "}
                {String(detail.settings.seed_base)} · lengths {JSON.stringify(detail.settings.lengths)}
              </p>
            )}
            <div className="overflow-x-auto rounded-[var(--radius-surface)] border border-line">
              <table className="w-full text-sm">
                <thead className="bg-bg-muted text-left text-xs text-fg-muted">
                  <tr>
                    {["mode", "length", "n", "mean z", "mean green %", "flagged rate", "≥ possible", "inconclusive", "re-tokenize mismatch", "meaning"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {detail.summary.map((r, i) => (
                    <tr key={i}>
                      <td className="px-3 py-2">{r.mode}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{r.max_new_tokens}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{r.n}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{fmt.z(r.mean_z)}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{fmt.pct100(r.mean_green_pct)}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs font-medium">{fmt.pct(r.flagged_rate)}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{fmt.pct(r.possible_or_above_rate)}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{fmt.pct(r.inconclusive_rate)}</td>
                      <td className="tabular px-3 py-2 font-mono text-xs">{r.retokenize_mismatch}</td>
                      <td className="px-3 py-2 text-xs text-fg-muted">{r.rate_meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {detail.points.length > 0 && (
              <Panel className="p-3">
                <ZChart points={detail.points.map((p) => ({ ...p, result: p.result }))} />
              </Panel>
            )}
          </>
        )}
      </section>
    </div>
  );
}
