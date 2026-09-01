// Shared client-side data helpers for the standalone "번외 주차경기" scoring
// pages (parking_admin / parking_teams / parking_team-result / parking_leaderboard).
// Results are stored by parking_server.py so every browser sees the same data.
// localStorage is retained only as a one-time migration source for past results.

const PARKING_STORAGE_KEY = "parkingRaceData";
const PARKING_START_SCORE = 500;
let parkingData = { teams: [], scores: {} };
let parkingSaveChain = Promise.resolve();
let parkingMutationVersion = 0;

// 9 채점 항목 정의 (제9회 국민대 대회 주차경기 채점표 기준)
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
  { key: "disqualified", label: "실격", type: "bool", penalty: 1000 },
];

function parkingLoadData() {
  return parkingData;
}

function parkingLoadLocalData() {
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
  parkingData = data;
  const mutationVersion = ++parkingMutationVersion;
  const dataToSave = structuredClone(data);
  window.dispatchEvent(new CustomEvent("parking-data-changed"));
  parkingSaveChain = parkingSaveChain
    .catch(() => {})
    .then(() => fetch("/api/parking-results", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dataToSave),
    }))
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((savedData) => {
      if (mutationVersion === parkingMutationVersion) {
        parkingData = parkingNormalizeData(savedData);
      }
    })
    .catch((error) => console.error("Parking results were not saved:", error));
}

function parkingNormalizeData(data) {
  return {
    teams: Array.isArray(data?.teams) ? data.teams : [],
    scores: data?.scores && typeof data.scores === "object" ? data.scores : {},
  };
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
  async function loadServerData() {
    const requestVersion = parkingMutationVersion;
    try {
      const response = await fetch("/api/parking-results", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const serverData = parkingNormalizeData(await response.json());
      if (requestVersion !== parkingMutationVersion) return;
      if (serverData.teams.length === 0) {
        const localData = parkingLoadLocalData();
        parkingData = localData;
        if (localData.teams.length || Object.keys(localData.scores).length) parkingSaveData(localData);
      } else {
        parkingData = serverData;
      }
    } catch (error) {
      console.error("Parking results could not be loaded:", error);
    }
  }

  function tick() {
    onUpdate(parkingLoadData());
  }
  tick();
  loadServerData().then(() => parkingEnsureConfiguredTeams()).then(tick);
  window.addEventListener("parking-data-changed", tick);
  setInterval(() => loadServerData().then(tick), 1000);
}
