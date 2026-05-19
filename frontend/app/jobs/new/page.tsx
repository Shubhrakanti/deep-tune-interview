"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function NewJobPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [attempts, setAttempts] = useState(1);
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError("Pick a tasks.json file");
      return;
    }
    if (attempts < 1) {
      setError("Attempts per problem must be >= 1");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await api.createJob(file, attempts, name);
      router.push(`/jobs/${r.job_id}`);
    } catch (e) {
      setError(String(e));
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight mb-6">New job</h1>
      <form onSubmit={onSubmit} className="space-y-5">
        <Field
          label="Tasks JSON file"
          help="A JSON array of {id, task, answer} objects (see tasks.json in the repo)."
        >
          <input
            type="file"
            accept="application/json,.json"
            required
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-neutral-900 file:text-white file:px-3 file:py-1.5 file:cursor-pointer dark:file:bg-white dark:file:text-neutral-900"
          />
        </Field>
        <Field
          label="Attempts per problem"
          help="Each (problem, attempt#) is one rollout. 10 problems x 3 attempts = 30 rollouts."
        >
          <input
            type="number"
            min={1}
            max={50}
            value={attempts}
            onChange={(e) => setAttempts(Number(e.target.value))}
            required
            className="block w-32 rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-1.5 text-sm"
          />
        </Field>
        <Field label="Name (optional)" help="Just a label for your dashboard.">
          <input
            type="text"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. smoke-test"
            className="block w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-1.5 text-sm"
          />
        </Field>
        {error ? (
          <div className="rounded-md border border-rose-300 bg-rose-50 dark:bg-rose-950/30 p-3 text-sm text-rose-800 dark:text-rose-200">
            {error}
          </div>
        ) : null}
        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {submitting ? "Submitting…" : "Submit job"}
          </button>
          <a
            href="/"
            className="rounded-md border border-neutral-300 dark:border-neutral-700 px-4 py-2 text-sm"
          >
            Cancel
          </a>
        </div>
      </form>
    </div>
  );
}

function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium">{label}</label>
      {children}
      {help ? (
        <p className="text-xs text-neutral-500">{help}</p>
      ) : null}
    </div>
  );
}
