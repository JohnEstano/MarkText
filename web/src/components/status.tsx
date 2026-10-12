"use client";

import { useEffect, useState } from "react";
import { api, type Health, type ModelOption } from "@/lib/api";
import { Notice } from "@/components/ui";

/* The model catalog for the model dropdowns (each model watermarks with
   its own key). Falls back to null when the API is unreachable; pages hide
   the dropdown then and the server uses its default model. */
export function useModels() {
  const [catalog, setCatalog] = useState<{ default: string; models: ModelOption[] } | null>(null);
  useEffect(() => {
    api.models().then(setCatalog).catch(() => setCatalog(null));
  }, []);
  return catalog;
}

/* Reads /health once per page so every app screen can say, before the user
   types anything, whether the model is up and whether the key is public. */
export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(e.message));
  }, []);
  return { health, error };
}

export function ApiStatus() {
  const { health, error } = useHealth();
  if (error) return <Notice tone="danger">{error}</Notice>;
  if (!health) return null;
  return (
    <div className="space-y-2">
      {health.status !== "ok" && (
        <Notice tone="danger">Model not loaded: {health.load_error ?? "unknown error"}</Notice>
      )}
      {health.notes.map((n) => (
        <Notice key={n} tone="warn">
          {n}
        </Notice>
      ))}
    </div>
  );
}

export function ModelLine() {
  const { health } = useHealth();
  if (!health?.model_id) return null;
  return (
    <p className="text-xs text-fg-faint">
      {health.model_id} on {health.device}
    </p>
  );
}
