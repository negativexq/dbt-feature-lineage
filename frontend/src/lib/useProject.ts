"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * The client-side equivalent of the Streamlit app's
 * st.session_state["shared_project_path"]/["shared_model_group"]:
 * written once on the Select Project page, read by every other page.
 * localStorage instead of a server session since there's no server-side
 * per-user state here -- this is a single-user local tool, same as the
 * Streamlit app was.
 */

const PATH_KEY = "dfl.project_path";
const GROUP_KEY = "dfl.model_group";

export function useSharedProject() {
  const [path, setPathState] = useState<string | null>(null);
  const [group, setGroupState] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setPathState(window.localStorage.getItem(PATH_KEY));
    setGroupState(window.localStorage.getItem(GROUP_KEY));
    setReady(true);
  }, []);

  const setProject = useCallback((newPath: string, newGroup: string | null) => {
    window.localStorage.setItem(PATH_KEY, newPath);
    if (newGroup) {
      window.localStorage.setItem(GROUP_KEY, newGroup);
    } else {
      window.localStorage.removeItem(GROUP_KEY);
    }
    setPathState(newPath);
    setGroupState(newGroup);
  }, []);

  return { path, group, ready, setProject };
}

/**
 * The project's real name and manifest/static mode, for the header
 * StatusPill -- several pages previously hardcoded mode="manifest"
 * regardless of what the project actually was, which is wrong for any
 * static-mode project (like the bundled examples straight out of the
 * box). One small fetch per page load, not cached client-side: the
 * backend's own cached_load_project() already makes this cheap, and a
 * `dbt parse` run elsewhere should be reflected on the next page visit
 * rather than a stale client-side cache hiding it.
 */
export function useProjectSummary(path: string | null) {
  const [name, setName] = useState<string | null>(null);
  const [mode, setMode] = useState<"manifest" | "static" | null>(null);

  useEffect(() => {
    if (!path) {
      setName(null);
      setMode(null);
      return;
    }
    api
      .getProject(path)
      .then((p) => {
        setName(p.name);
        setMode(p.artifact_status?.mode ?? "static");
      })
      .catch(() => {
        setName(null);
        setMode(null);
      });
  }, [path]);

  return { name, mode };
}
