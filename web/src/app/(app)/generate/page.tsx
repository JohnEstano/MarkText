"use client";

import { useState } from "react";
import { DownloadSimple, FloppyDisk, Copy } from "@phosphor-icons/react";
import { api, type Generation, type Mode } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Button, Input, Label, Textarea, Help, FieldError, Panel, Notice, Skeleton, Badge } from "@/components/ui";
import { ModelLine } from "@/components/status";

const MIN = 50;
const MAX = 2000;

export default function GeneratePage() {
  const [prompt, setPrompt] = useState("Tell me about the history of cryptography.");
  const [tokens, setTokens] = useState(150);
  const [mode, setMode] = useState<Mode>("watermarked");
  const [seed, setSeed] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Generation | null>(null);
  const [saved, setSaved] = useState<{ text_path: string; sidecar_path: string } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const eta = Math.round(tokens / (mode === "watermarked" ? 4.3 : 8));

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!prompt.trim()) return setError("Please enter a prompt.");
    if (tokens < MIN || tokens > MAX) return setError(`Max tokens must be between ${MIN} and ${MAX}.`);
    if (seed && !/^\d+$/.test(seed)) return setError("Seed must be a whole number, or empty for a random seed.");
    setBusy(true);
    setResult(null);
    setSaved(null);
    setSaveError(null);
    try {
      setResult(await api.generate({ prompt: prompt.trim(), max_new_tokens: tokens, mode, seed: seed ? Number(seed) : null }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!result) return;
    setSaveError(null);
    try {
      setSaved(await api.save(result));
    } catch (err) {
      setSaveError((err as Error).message);
    }
  }

  function download() {
    if (!result) return;
    const blob = new Blob([result.text], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `marktext_${result.mode}_seed${result.seed}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function copy() {
    if (!result) return;
    await navigator.clipboard.writeText(result.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Generate</h1>
        <p className="mt-1 text-sm text-fg-muted">
          The same prompt, with or without the green-list bias. Save the result with its seed so it can be re-run.
        </p>
        <ModelLine />
        <form onSubmit={run} className="mt-6 space-y-5">
          <div className="space-y-2">
            <Label htmlFor="prompt">Prompt</Label>
            <Textarea id="prompt" rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="tokens">Max tokens</Label>
              <Input
                id="tokens"
                type="number"
                min={MIN}
                max={MAX}
                step={10}
                value={tokens}
                onChange={(e) => setTokens(Number(e.target.value))}
              />
              <Help>
                {MIN} to {MAX}. About {fmt.minutes(eta)} on a CPU.
              </Help>
            </div>
            <div className="space-y-2">
              <Label htmlFor="seed">Seed</Label>
              <Input id="seed" inputMode="numeric" placeholder="random" value={seed} onChange={(e) => setSeed(e.target.value)} />
              <Help>Same seed and settings give the same text.</Help>
            </div>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Mode</legend>
            <div className="inline-flex rounded-full border border-line-strong bg-bg-elev p-1">
              {(["watermarked", "normal"] as Mode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                  className={`rounded-full px-4 py-1.5 text-sm capitalize transition-colors ${
                    mode === m ? "bg-accent text-accent-fg" : "text-fg-muted hover:text-fg"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
            <Help>Watermarked adds the bias to green-list tokens before sampling. Normal is plain sampling.</Help>
          </fieldset>
          <FieldError>{error}</FieldError>
          <Button type="submit" size="lg" disabled={busy}>
            {busy ? "Generating" : "Generate"}
          </Button>
        </form>
      </section>

      <section aria-live="polite">
        <h2 className="text-sm font-medium text-fg-muted">Output</h2>
        {busy && (
          <Panel className="mt-3 space-y-3 p-5">
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-10/12" />
            <Skeleton className="h-4 w-9/12" />
            <p className="pt-2 text-xs text-fg-faint">Generating {tokens} tokens, about {fmt.minutes(eta)}.</p>
          </Panel>
        )}
        {!busy && !result && (
          <Panel className="mt-3 px-6 py-12 text-center text-sm text-fg-muted">
            Nothing generated yet. The text appears here with its seed and token count.
          </Panel>
        )}
        {result && !busy && (
          <Panel className="mt-3 p-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={result.mode === "watermarked" ? "accent" : "neutral"}>{result.mode}</Badge>
              <span className="tabular font-mono text-xs text-fg-muted">
                seed {result.seed} · {result.new_tokens} tokens
                {result.cancelled ? " · cancelled" : ""}
              </span>
            </div>
            <p className="pretty mt-4 whitespace-pre-wrap text-[15px] leading-relaxed">{result.text}</p>
            <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4">
              <Button variant="secondary" size="sm" onClick={save}>
                <FloppyDisk size={16} /> Save to generated/
              </Button>
              <Button variant="secondary" size="sm" onClick={download}>
                <DownloadSimple size={16} /> Download .txt
              </Button>
              <Button variant="ghost" size="sm" onClick={copy}>
                <Copy size={16} /> {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            {saved && (
              <div className="mt-3">
                <Notice tone="accent">
                  Saved with its sidecar: <span className="font-mono text-xs">{saved.text_path}</span>
                </Notice>
              </div>
            )}
            {saveError && (
              <div className="mt-3">
                <Notice tone="danger">{saveError}</Notice>
              </div>
            )}
          </Panel>
        )}
      </section>
    </div>
  );
}
