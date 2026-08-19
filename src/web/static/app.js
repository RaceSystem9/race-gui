// Shared polling helper for all broadcast web pages.
// Each page registers a callback that receives the latest /api/state payload.

const POLL_INTERVAL_MS = 500;

function formatSeconds(value, digits = 2) {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return num.toFixed(digits);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function setConnStatus(ok) {
  const el = document.getElementById("connStatus");
  if (!el) return;
  el.classList.remove("ok", "bad");
  el.classList.add(ok ? "ok" : "bad");
  el.textContent = ok ? "실시간 연결됨" : "연결 끊김 - 재시도 중";
}

function startBroadcastPolling(onUpdate) {
  let stopped = false;

  async function poll() {
    if (stopped) return;
    try {
      const response = await fetch("/api/state", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setConnStatus(true);
      onUpdate(data);
    } catch (error) {
      setConnStatus(false);
    } finally {
      if (!stopped) setTimeout(poll, POLL_INTERVAL_MS);
    }
  }

  poll();
  return () => {
    stopped = true;
  };
}
