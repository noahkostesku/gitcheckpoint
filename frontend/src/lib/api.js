const API_BASE = (import.meta.env.VITE_API_URL || "") + "/api";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/health"),

  chat: (message, threadId = "default") =>
    request("/chat", {
      method: "POST",
      body: JSON.stringify({ message, thread_id: threadId }),
    }),

  getThreads: () => request("/threads"),

  getLog: (threadId, limit = 50) =>
    request(`/threads/${threadId}/log?limit=${limit}`),

  getDiff: (threadId, a, b) =>
    request(`/threads/${threadId}/diff/${a}/${b}`),

  checkpoint: (threadId, label) =>
    request("/checkpoint", {
      method: "POST",
      body: JSON.stringify({ thread_id: threadId, label }),
    }),

  timeTravel: (threadId, checkpointId) =>
    request("/time-travel", {
      method: "POST",
      body: JSON.stringify({ thread_id: threadId, checkpoint_id: checkpointId }),
    }),

  fork: (sourceThreadId, checkpointId, newName) =>
    request("/fork", {
      method: "POST",
      body: JSON.stringify({
        source_thread_id: sourceThreadId,
        checkpoint_id: checkpointId,
        new_thread_name: newName,
      }),
    }),

  merge: (source, target) =>
    request("/merge", {
      method: "POST",
      body: JSON.stringify({
        source_thread_id: source,
        target_thread_id: target,
      }),
    }),

  pushToGithub: (threadId) =>
    request("/github/push", {
      method: "POST",
      body: JSON.stringify({ thread_id: threadId }),
    }),

  shareGist: (threadId, isPublic = false) =>
    request("/github/gist", {
      method: "POST",
      body: JSON.stringify({ thread_id: threadId, public: isPublic }),
    }),

  transcribe: async (audioBlob) => {
    const form = new FormData();
    form.append("audio", audioBlob, "recording.webm");
    const res = await fetch(`${API_BASE}/voice/transcribe`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },
};
