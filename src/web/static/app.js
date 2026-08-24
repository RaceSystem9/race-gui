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

  // 현재 URL 경로를 파악하여 보여줄 라운드 번호 결정
  const pathname = window.location.pathname;
  let forcedRound = null;

  if (pathname.includes("round1") || pathname.includes("round-1")) {
    forcedRound = 1;
  } else if (pathname.includes("round2") || pathname.includes("round-2")) {
    forcedRound = 2;
  }

  async function poll() {
    if (stopped) return;
    try {
      const response = await fetch("/api/state", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setConnStatus(true);

      // 페이지 파일명에 맞춰 리더보드 데이터 및 라운드 정보 강제 교체
      if (forcedRound !== null && data) {
        const roundKey = `ROUND${forcedRound}`;
        
        data.current_round = forcedRound;
        data.view_mode = roundKey;
        data.view_mode_title = `${forcedRound}차`;
        
        // 서버에서 전달된 leaderboards 객체에서 해당 라운드 데이터를 추출해 replacement
        if (data.leaderboards && data.leaderboards[roundKey]) {
          data.leaderboard = data.leaderboards[roundKey];
        }
      }

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