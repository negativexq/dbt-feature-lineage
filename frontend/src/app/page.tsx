"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, DiscoveredProject, ProjectSummary } from "@/lib/api";
import { useSharedProject } from "@/lib/useProject";
import { ErrorBanner, PageHeader, PrimaryButton, PromptField } from "@/components/ui";

export default function SelectProjectPage() {
  const router = useRouter();
  const { setProject } = useSharedProject();

  const [source, setSource] = useState<"local" | "git">("local");
  const [root, setRoot] = useState("examples");
  const [gitUrl, setGitUrl] = useState("");
  const [gitRef, setGitRef] = useState("");
  const [cloning, setCloning] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredProject[]>([]);
  const [selectedPath, setSelectedPath] = useState<string>("");
  const [project, setLoadedProject] = useState<ProjectSummary | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string>("All");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    setError(null);
    api
      .discover(root)
      .then((projects) => {
        setDiscovered(projects);
        setSelectedPath(projects[0]?.path ?? "");
      })
      .catch((err) => {
        setDiscovered([]);
        setError(err.message);
      });
  }, [root]);

  useEffect(() => {
    if (!selectedPath) {
      setLoadedProject(null);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .getProject(selectedPath)
      .then((p) => {
        setLoadedProject(p);
        setSelectedGroup("All");
      })
      .catch((err) => {
        setLoadedProject(null);
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [selectedPath]);

  const handleContinue = () => {
    if (!project) return;
    setProject(project.path, selectedGroup === "All" ? null : selectedGroup);
    router.push("/dashboard");
  };

  const handleClone = () => {
    if (!gitUrl.trim()) return;
    setCloning(true);
    setError(null);
    api
      .cloneProject(gitUrl.trim(), gitRef.trim() || undefined)
      .then((projects) => {
        setDiscovered(projects);
        setSelectedPath(projects[0]?.path ?? "");
      })
      .catch((err) => {
        setDiscovered([]);
        setSelectedPath("");
        setError(err.message);
      })
      .finally(() => setCloning(false));
  };

  const handleGenerateArtifacts = () => {
    if (!project) return;
    setGenerating(true);
    setError(null);
    api
      .generateArtifacts(project.path)
      .then((p) => setLoadedProject(p))
      .catch((err) => setError(err.message))
      .finally(() => setGenerating(false));
  };

  return (
    <div className="mx-auto max-w-2xl py-8">
      <PageHeader
        eyebrow="select-project --scan"
        title="Select project"
        caption="Point at a directory, pick a project, optionally scope to one model group. Shared with every other page."
      />

      <div className="flex flex-col gap-3">
        <div className="flex gap-1 self-start rounded-md border border-line bg-ink-900 p-1">
          {(["local", "git"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSource(s)}
              className={`rounded px-3 py-1.5 font-mono text-xs transition-colors ${
                source === s ? "bg-accent-dim text-accent" : "text-text-lo hover:text-text-hi"
              }`}
            >
              {s === "local" ? "local directory" : "clone from git"}
            </button>
          ))}
        </div>

        {source === "local" ? (
          <PromptField prompt="scan">
            <input
              value={root}
              onChange={(e) => setRoot(e.target.value)}
              className="w-full bg-transparent font-mono text-sm text-text-hi outline-none placeholder:text-text-lo"
              placeholder="examples"
            />
          </PromptField>
        ) : (
          <>
            <PromptField prompt="clone">
              <input
                value={gitUrl}
                onChange={(e) => setGitUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleClone()}
                className="w-full bg-transparent font-mono text-sm text-text-hi outline-none placeholder:text-text-lo"
                placeholder="https://github.com/org/repo.git"
              />
            </PromptField>
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <PromptField prompt="ref">
                  <input
                    value={gitRef}
                    onChange={(e) => setGitRef(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleClone()}
                    className="w-full bg-transparent font-mono text-sm text-text-hi outline-none placeholder:text-text-lo"
                    placeholder="main (optional)"
                  />
                </PromptField>
              </div>
              <PrimaryButton onClick={handleClone} disabled={cloning || !gitUrl.trim()} className="shrink-0">
                {cloning ? "cloning…" : "Clone →"}
              </PrimaryButton>
            </div>
          </>
        )}

        {discovered.length > 0 && (
          <PromptField prompt="use">
            <select
              value={selectedPath}
              onChange={(e) => setSelectedPath(e.target.value)}
              className="w-full bg-transparent font-mono text-sm text-text-hi outline-none"
            >
              {discovered.map((p) => (
                <option key={p.path} value={p.path} className="bg-ink-900">
                  {p.name} ({p.relative_path})
                </option>
              ))}
            </select>
          </PromptField>
        )}

        {error && <ErrorBanner message={error} />}

        {loading && <p className="font-mono text-xs text-text-lo">loading…</p>}

        {project && (
          <>
            <p className="font-mono text-xs text-text-lo">
              <span className="text-accent">✓</span> loaded {project.name} — {project.model_count}{" "}
              models
            </p>

            {/* Static mode means dbt parse has never run for this project --
                everything still works off raw SQL parsing, but ref()/source()
                edges, tests, docs, and owners come from the manifest, so
                without one most of the app runs on a strictly weaker signal.
                Surface that gap and the one command that closes it, rather
                than leaving it to be discovered as missing data on other
                pages. */}
            <div
              className={`flex items-center justify-between gap-3 rounded-md border px-4 py-3 ${
                project.artifact_status?.mode === "manifest"
                  ? "border-line bg-ink-900"
                  : "border-amber-900/50 bg-amber-950/20"
              }`}
            >
              <div className="min-w-0">
                <p className="font-mono text-xs text-text-lo">
                  <span className={project.artifact_status?.mode === "manifest" ? "text-accent" : "text-amber-400"}>
                    {project.artifact_status?.mode === "manifest" ? "●" : "○"}
                  </span>{" "}
                  {project.artifact_status?.mode ?? "static"} mode
                </p>
                <p className="mt-0.5 truncate text-sm text-text-hi">
                  {project.artifact_status?.message ?? "No manifest found — parsing raw SQL only."}
                </p>
              </div>
              <button
                onClick={handleGenerateArtifacts}
                disabled={generating}
                className="shrink-0 rounded-md border border-line px-3.5 py-2 font-mono text-xs text-text-hi transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
              >
                {generating
                  ? "running dbt parse…"
                  : project.artifact_status?.mode === "manifest"
                    ? "re-parse"
                    : "generate artifacts →"}
              </button>
            </div>

            {project.model_groups.length > 0 && (
              <PromptField prompt="group">
                <select
                  value={selectedGroup}
                  onChange={(e) => setSelectedGroup(e.target.value)}
                  className="w-full bg-transparent font-mono text-sm text-text-hi outline-none"
                >
                  <option value="All" className="bg-ink-900">
                    All
                  </option>
                  {project.model_groups.map((g) => (
                    <option key={g} value={g} className="bg-ink-900">
                      {g}
                    </option>
                  ))}
                </select>
              </PromptField>
            )}

            <PrimaryButton onClick={handleContinue} className="mt-2 self-start">
              Continue →
            </PrimaryButton>
          </>
        )}
      </div>
    </div>
  );
}
