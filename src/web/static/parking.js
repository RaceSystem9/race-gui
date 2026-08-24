// Shared client-side data helpers for the standalone "번외 주차경기" scoring
// pages (parking_admin / parking_teams / parking_team-result / parking_leaderboard).
// All data lives in the browser's localStorage - this is intentionally
// independent from the main race DB / /api/state so it cannot affect the
// existing GUI, server, or broadcast pages in any way.

const PARKING_STORAGE_KEY = "parkingRaceData";
const PARKING_START_SCORE = 500;

// 8 채점 항목 정의 (제9회 국민대 대회 주차경기 채점표 기준)
const PARKING_ITEMS = [
  { key: "cone_touch", label: "라바콘 살짝 접촉", type: "count", penalty: 10 },
  { key: "cone_move", label: "라바콘 전복/이동", type: "count", penalty: 20 },
  { key: "wall_touch", label: "칸막이 접촉", type: "count", penalty: 30 },
  { key: "wall_move", label: "칸막이 이동", type: "count", penalty: 50 },
  {
    key: "protrude",
    label: "주차 사각형 돌출",
    type: "choice",
    choices: [
      { value: 0, label: "없음", penalty: 0 },
      { value: 1, label: "1면 돌출", penalty: 10 },
      { value: 2, label: "2면 이상 돌출", penalty: 20 },
    ],
  },
  {
    key: "park_fail",
    label: "주차 실패",
    type: "choice",
    choices: [
      { value: 0, label: "없음", penalty: 0 },
      { value: 1, label: "1번 실패", penalty: 100 },
      { value: 2, label: "2번 실패", penalty: 200 },
    ],
  },
  { key: "start_fail", label: "처음 위치 정차 실패", type: "bool", penalty: 20 },
  { key: "time_over", label: "제한시간 초과", type: "bool", penalty: 50 },
];

function parkingLoadData() {
  try {
    const raw = localStorage.getItem(PARKING_STORAGE_KEY);
    if (!raw) return { teams: [], scores: {} };
    const data = JSON.parse(raw);
    return {
      teams: Array.isArray(data.teams) ? data.teams : [],
      scores: data.scores && typeof data.scores === "object" ? data.scores : {},
    };
  } catch (e) {
    return { teams: [], scores: {} };
  }
}

function parkingSaveData(data) {
  localStorage.setItem(PARKING_STORAGE_KEY, JSON.stringify(data));
  // Same-tab pages don't get a native "storage" event, so poke listeners here.
  window.dispatchEvent(new CustomEvent("parking-data-changed"));
}

function parkingCalcDeduction(score) {
  const s = score || {};
  let total = 0;
  for (const item of PARKING_ITEMS) {
    if (item.type === "count") {
      total += (Number(s[item.key]) || 0) * item.penalty;
    } else if (item.type === "bool") {
      total += s[item.key] ? item.penalty : 0;
    } else if (item.type === "choice") {
      const choice = item.choices.find((c) => c.value === Number(s[item.key] || 0));
      total += choice ? choice.penalty : 0;
    }
  }
  return total;
}

function parkingFinalScore(score) {
  return PARKING_START_SCORE - parkingCalcDeduction(score);
}

function parkingEscapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function parkingEnsureConfiguredTeams() {
  try {
    const response = await fetch("/api/parking-teams", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const configuredTeams = await response.json();
    if (!Array.isArray(configuredTeams) || configuredTeams.length === 0) return;

    const latest = parkingLoadData();
    const teams = configuredTeams
      .filter((team) => team && team.team_no !== undefined)
      .map((team) => ({
        id: Number(team.team_no),
        school: team.school || "",
        team_name: team.team_name || "",
      }));
    if (JSON.stringify(latest.teams) !== JSON.stringify(teams)) {
      latest.teams = teams;
      parkingSaveData(latest);
    }
  } catch (error) {
    // The admin page remains usable for manual team entry if config loading fails.
  }
}

// Display pages (teams / team-result / leaderboard) call this to stay in
// sync with the admin input page, whether it's open in another tab (native
// "storage" event) or was just edited in the same tab (custom event).
function parkingStartPolling(onUpdate) {
  function tick() {
    onUpdate(parkingLoadData());
  }
  tick();
  parkingEnsureConfiguredTeams().then(tick);
  window.addEventListener("storage", (e) => {
    if (!e.key || e.key === PARKING_STORAGE_KEY) tick();
  });
  window.addEventListener("parking-data-changed", tick);
  setInterval(tick, 1000);
}
