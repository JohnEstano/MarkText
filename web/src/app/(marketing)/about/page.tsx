"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { Notice, Skeleton, Panel } from "@/components/ui";

export default function AboutPage() {
  const [md, setMd] = useState<string | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.readme().then((r) => setMd(r.markdown)).catch((e) => setError(e.message));
    api.config().then(setConfig).catch(() => {});
  }, []);
  return (
    <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:px-6 lg:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
      <article className="prose-marktext">
        {error && <Notice tone="danger">{error}</Notice>}
        {!md && !error && (
          <div className="space-y-3">
            <Skeleton className="h-8 w-1/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-9/12" />
          </div>
        )}
        {md && <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>}
      </article>
      <aside className="lg:sticky lg:top-24 lg:self-start">
        <h2 className="text-sm font-medium text-fg-muted">Current configuration</h2>
        <Panel className="mt-3 overflow-x-auto p-4">
          {config ? (
            <pre className="font-mono text-xs leading-relaxed">{JSON.stringify(config, null, 2)}</pre>
          ) : (
            <Skeleton className="h-40" />
          )}
        </Panel>
        <p className="mt-2 text-xs text-fg-faint">Read from config/watermark_config.json. The key is never shown.</p>
      </aside>
    </div>
  );
}
