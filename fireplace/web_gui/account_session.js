/* Keep private pages in sync when another tab changes the login cookie.
 * Account identity is always re-read from the server; localStorage carries
 * only a change notification, never credentials or session tokens. */

const CHANGE_KEY = "fireplace.auth-change";

export function announceAccountChange() {
  try {
    localStorage.setItem(CHANGE_KEY, `${Date.now()}-${Math.random()}`);
  } catch (_error) {
    // A visible tab also rechecks its session periodically.
  }
}

export function watchAccountSession(accountId, onChange) {
  let checking = false;
  let changed = false;
  let pendingHide = false;

  async function check({ hide = false } = {}) {
    if (hide) document.documentElement.style.visibility = "hidden";
    if (changed) return;
    if (checking) {
      pendingHide ||= hide;
      return;
    }
    checking = true;
    try {
      const response = await fetch("/api/account/session", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (response.status === 401) {
        changed = true;
        onChange();
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (!payload?.authenticated || payload?.account?.id !== accountId) {
        changed = true;
        onChange();
        return;
      }
      if (hide) document.documentElement.style.visibility = "";
    } catch (_error) {
      // A login/logout notification should clear a stale private page even
      // if the server is temporarily unavailable. Background checks can
      // retry without discarding an otherwise healthy editor.
      if (hide) {
        changed = true;
        onChange();
      }
    } finally {
      checking = false;
      if (pendingHide && !changed) {
        pendingHide = false;
        void check({ hide: true });
      }
    }
  }

  window.addEventListener("storage", (event) => {
    if (event.key === CHANGE_KEY) void check({ hide: true });
  });
  window.addEventListener("focus", () => { void check(); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void check();
  });
  window.setInterval(() => { if (document.visibilityState === "visible") void check(); }, 5000);
}
