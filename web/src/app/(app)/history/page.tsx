"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { DownloadSimple, PencilSimple, Trash, X } from "@phosphor-icons/react";
import { api, type HistoryFilters, type HistoryResponse, type HistoryRow } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Button, Input, Label, Select, Panel, Notice, Skeleton, Metric, Empty, Badge, Pager, buttonClass } from "@/components/ui";
import { VerdictBadge } from "@/components/verdict";
import { ZChart } from "@/components/history-chart";

export default function HistoryPage() {
  const [filters, setFilters] = useState<HistoryFilters>({});
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<HistoryRow | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [page, setPage] = useState(1);
  const PER = 10;

  /* a new filter mask always starts at the first page */
  function updateFilters(f: HistoryFilters) {
    setFilters(f);
    setPage(1);
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.history(filters));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    // the fetch is kicked off from a callback, not the effect body
    const t = setTimeout(load, 0);
    return () => clearTimeout(t);
  }, [load]);

  const th = data?.thresholds;
  const summaryCols = useMemo(
    () => (data?.summary?.[0] ? Object.keys(data.summary[0]) : []),
    [data],
  );
  const pageRows = useMemo(() => {
    const rows = data?.rows ?? [];
    const pages = Math.max(1, Math.ceil(rows.length / PER));
    const cur = Math.min(page, pages);
    return rows.slice((cur - 1) * PER, cur * PER);
  }, [data, page]);

  async function clearAll() {
    try {
      const r = await api.clearHistory();
      setNotice(`History cleared. Backup: ${r.backup}`);
      setConfirmClear(false);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">History</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Every analysis, one row each. Filter, summarise, export to a new file, or edit one record by its id.
          </p>
        </div>
        <a href={api.exportHistoryUrl(filters)} className={buttonClass({ variant: "secondary", size: "sm" })}>
          <DownloadSimple size={16} /> Export filtered rows
        </a>
      </div>

      {notice && <Notice tone="accent">{notice}</Notice>}
      {error && <Notice tone="danger">{error}</Notice>}

      {/* filters: one combined mask on the server */}
      <Panel className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-5">
        <div className="space-y-1.5">
          <Label htmlFor="f-result">Result</Label>
          <Select
            id="f-result"
            value={filters.result?.[0] ?? ""}
            onChange={(e) => updateFilters({ ...filters, result: e.target.value ? [e.target.value] : undefined })}
          >
            <option value="">All</option>
            {data?.options.results.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-source">Source</Label>
          <Select
            id="f-source"
            value={filters.source?.[0] ?? ""}
            onChange={(e) => updateFilters({ ...filters, source: e.target.value ? [e.target.value] : undefined })}
          >
            <option value="">All</option>
            {data?.options.sources.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-batch">Batch</Label>
          <Select id="f-batch" value={filters.batch_id ?? ""} onChange={(e) => updateFilters({ ...filters, batch_id: e.target.value || undefined })}>
            <option value="">All</option>
            {data?.options.batches.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-q">Filename contains</Label>
          <Input id="f-q" value={filters.q ?? ""} onChange={(e) => updateFilters({ ...filters, q: e.target.value || undefined })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-min">Min tokens</Label>
          <Input
            id="f-min"
            type="number"
            min={0}
            step={10}
            value={filters.min_tokens ?? 0}
            onChange={(e) => updateFilters({ ...filters, min_tokens: Number(e.target.value) || undefined })}
          />
        </div>
      </Panel>

      {loading && !data && (
        <div className="grid gap-4 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      )}

      {data && data.total === 0 && (
        <Empty title="No detection history yet">Run an analysis on the Detect page or start an experiment.</Empty>
      )}

      {data && data.total > 0 && (
        <>
          <div className="grid gap-6 border-y border-line py-5 sm:grid-cols-4">
            <Metric label="Analyses in view" value={fmt.int(data.kpis.count)} hint={`of ${data.total}`} />
            <Metric label="Mean z-score" value={fmt.z(data.kpis.mean_z)} />
            <Metric label="Flagged LIKELY MARKTEXT" value={fmt.pct(data.kpis.flagged_rate)} />
            <Metric label="Median tokens" value={fmt.int(data.kpis.median_tokens)} />
          </div>

          {data.kpis.count === 0 ? (
            <Empty title="No records match the filters" />
          ) : (
            <>
              <section>
                <h2 className="mb-2 text-sm font-medium text-fg-muted">z-score vs tokens analysed</h2>
                <Panel className="p-3">
                  <ZChart points={data.rows} detection={th?.detection_threshold} possible={th?.possible_threshold} />
                </Panel>
                <p className="mt-1 text-xs text-fg-faint">
                  Dashed line: detection threshold {th?.detection_threshold}. Verdicts below {th?.min_tokens_for_verdict} scored tokens are inconclusive.
                </p>
              </section>

              <section>
                <h2 className="mb-2 text-sm font-medium text-fg-muted">Summary by {summaryCols.includes("mode") ? "mode and result" : "result"}</h2>
                <div className="overflow-x-auto rounded-[var(--radius-surface)] border border-line">
                  <table className="w-full text-sm">
                    <thead className="bg-bg-muted text-left text-xs text-fg-muted">
                      <tr>
                        {summaryCols.map((c) => (
                          <th key={c} className="px-3 py-2 font-medium">
                            {c.replace(/_/g, " ")}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {data.summary.map((r, i) => (
                        <tr key={i}>
                          {summaryCols.map((c) => (
                            <td key={c} className="tabular px-3 py-2 font-mono text-xs">
                              {typeof r[c] === "number" ? (Number.isInteger(r[c]) ? r[c] : (r[c] as number).toFixed(2)) : r[c]}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section>
                <h2 className="mb-2 text-sm font-medium text-fg-muted">Records</h2>
                <div className="overflow-x-auto rounded-[var(--radius-surface)] border border-line">
                  <table className="w-full text-sm">
                    <thead className="bg-bg-muted text-left text-xs text-fg-muted">
                      <tr>
                        {["run id", "time", "source", "mode", "filename", "tokens", "green %", "z", "p", "result", ""].map((h) => (
                          <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {pageRows.map((r) => (
                        <tr key={r.run_id} className="hover:bg-bg-muted/60">
                          <td className="px-3 py-2 font-mono text-xs">{r.run_id}</td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-fg-muted">{r.timestamp}</td>
                          <td className="px-3 py-2 text-xs">{r.source}</td>
                          <td className="px-3 py-2 text-xs">{r.mode || <span className="text-fg-faint">-</span>}</td>
                          <td className="max-w-[16ch] truncate px-3 py-2 text-xs" title={r.filename}>
                            {r.filename || <span className="text-fg-faint">-</span>}
                          </td>
                          <td className="tabular px-3 py-2 font-mono text-xs">{r.tokens_scored}</td>
                          <td className="tabular px-3 py-2 font-mono text-xs">{fmt.pct100(r.green_pct)}</td>
                          <td className="tabular px-3 py-2 font-mono text-xs">{fmt.z(r.z_score)}</td>
                          <td className="tabular px-3 py-2 font-mono text-xs">{fmt.p(r.p_value)}</td>
                          <td className="px-3 py-2">
                            <VerdictBadge label={r.result} />
                          </td>
                          <td className="px-2 py-2 text-right">
                            <button
                              aria-label={`Edit record ${r.run_id}`}
                              onClick={() => setEditing(r)}
                              className="rounded-full p-1.5 text-fg-muted hover:bg-bg-muted hover:text-fg"
                            >
                              <PencilSimple size={16} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-3">
                  <Pager page={page} total={data.rows.length} per={PER} onChange={setPage} />
                </div>
              </section>
            </>
          )}

          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5 text-sm">
            <label className="flex items-center gap-2 text-fg-muted">
              <input type="checkbox" checked={confirmClear} onChange={(e) => setConfirmClear(e.target.checked)} />
              Yes, clear all records (a backup copy is written first)
            </label>
            <Button variant="danger" size="sm" disabled={!confirmClear} onClick={clearAll}>
              Clear history
            </Button>
          </div>
        </>
      )}

      {editing && (
        <RecordDrawer
          row={editing}
          onClose={() => setEditing(null)}
          onChanged={(msg) => {
            setNotice(msg);
            setEditing(null);
            load();
          }}
        />
      )}
    </div>
  );
}

/* Slide-over for one record: note and filename are editable, everything
   else is shown read-only. Delete needs an explicit confirmation. */
function RecordDrawer({ row, onClose, onChanged }: { row: HistoryRow; onClose: () => void; onChanged: (msg: string) => void }) {
  const [note, setNote] = useState(row.note ?? "");
  const [filename, setFilename] = useState(row.filename ?? "");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.updateRecord(row.run_id, { note, filename });
      onChanged(`Record ${row.run_id} updated. Backup: ${r.backup}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.deleteRecord(row.run_id);
      onChanged(`Record ${row.run_id} deleted. Backup: ${r.backup}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-fg/20" onClick={onClose}>
      <aside
        role="dialog"
        aria-label={`Record ${row.run_id}`}
        onClick={(e) => e.stopPropagation()}
        className="h-full w-full max-w-md overflow-y-auto border-l border-line bg-bg-elev p-6 shadow-[var(--shadow-surface)]"
      >
        <div className="flex items-center justify-between">
          <h2 className="font-mono text-sm">{row.run_id}</h2>
          <button aria-label="Close" onClick={onClose} className="rounded-full p-1.5 text-fg-muted hover:bg-bg-muted">
            <X size={18} />
          </button>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          {(
            [
              ["time", row.timestamp],
              ["source", row.source],
              ["mode", row.mode || "-"],
              ["tokens scored", row.tokens_scored],
              ["green %", fmt.pct100(row.green_pct)],
              ["z", fmt.z(row.z_score)],
              ["p", fmt.p(row.p_value)],
              ["seed", row.seed ?? "-"],
              ["device", row.device ?? "-"],
              ["bias / ratio", `${row.bias ?? "-"} / ${row.greenlist_ratio ?? "-"}`],
            ] as Array<[string, React.ReactNode]>
          ).map(([k, v]) => (
            <div key={k}>
              <dt className="text-fg-faint">{k}</dt>
              <dd className="tabular font-mono">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-3">
          <VerdictBadge label={row.result} />
        </div>
        <div className="mt-6 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="e-filename">Filename</Label>
            <Input id="e-filename" value={filename} onChange={(e) => setFilename(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="e-note">Note</Label>
            <Input id="e-note" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <p className="text-xs text-fg-muted">Measurements are immutable. A backup is written before any change.</p>
          {error && <Notice tone="danger">{error}</Notice>}
          <div className="flex gap-2">
            <Button onClick={save} disabled={busy}>
              Save changes
            </Button>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </div>
        <div className="mt-8 space-y-3 border-t border-line pt-5">
          <label className="flex items-center gap-2 text-sm text-fg-muted">
            <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            Yes, delete this record
          </label>
          <Button variant="danger" size="sm" disabled={!confirm || busy} onClick={remove}>
            <Trash size={16} /> Delete record
          </Button>
          <Badge tone="muted">backup first, exactly one match required</Badge>
        </div>
      </aside>
    </div>
  );
}
