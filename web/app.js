const $ = (sel) => document.querySelector(sel);

const POLL_OPTIONS = [
  { minutes: 15, label: "15분" },
  { minutes: 30, label: "30분" },
  { minutes: 60, label: "1시간" },
  { minutes: 180, label: "3시간" },
  { minutes: 360, label: "6시간" },
];

let currentSchedule = { schedule_mode: "off", poll_minutes: null, fixed_times: [] };
let visiblePanel = null; // 정해진 시각 탭처럼 아직 저장 전인 상태를 미리 보여주기 위한 로컬 상태

const TYPES = [
  { key: "assignment", label: "과제" },
  { key: "quiz", label: "퀴즈" },
  { key: "calendar_event", label: "일정" },
  { key: "discussion_topic", label: "토론" },
  { key: "planner_note", label: "메모" },
  { key: "announcement", label: "공지사항" },
];

let currentPrefs = { course_ids: null, types: null, known_courses: [] };

function showToast(text) {
  const toast = $("#toast");
  toast.textContent = text;
  toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("show"), 2400);
}

function startLoading(button) {
  button.disabled = true;
  let seconds = 0;
  const render = () => {
    button.innerHTML = `<span class="loader"><span></span><span></span><span></span></span><span class="loading-secs">${
      seconds > 2 ? `${seconds}초째 확인 중이에요` : "확인 중이에요"
    }</span>`;
  };
  render();
  const timer = setInterval(() => {
    seconds += 1;
    render();
  }, 1000);
  return () => clearInterval(timer);
}

async function api(path, options) {
  const resp = await fetch(path, {
    method: options?.method || "GET",
    headers: options?.body ? { "Content-Type": "application/json" } : undefined,
    body: options?.body ? JSON.stringify(options.body) : undefined,
  });
  return resp.json();
}

function setPill(el, state, label) {
  el.textContent = label;
  el.classList.remove("neutral", "success", "danger");
  el.classList.add(state);
}

function setLocked(cardId, locked) {
  $(`#${cardId}`).classList.toggle("locked", locked);
}

function setDone(cardId, done) {
  $(`#${cardId}`).classList.toggle("done", done);
}

async function refreshAccount() {
  const status = await api("/api/account");
  const pill = $("#account-pill");
  const connected = $("#account-connected");
  const form = $("#account-form");
  if (status.connected) {
    setPill(pill, "success", "완료");
    connected.style.display = "block";
    form.style.display = "none";
    $("#account-masked").textContent = status.masked;
  } else {
    setPill(pill, "neutral", "연결 필요");
    connected.style.display = "none";
    form.style.display = "block";
  }
  setDone("account-card", status.connected);
  return status.connected;
}

async function refreshTelegram() {
  const status = await api("/api/telegram");
  const pill = $("#telegram-pill");
  const connected = $("#telegram-connected");
  const form = $("#telegram-form");
  if (status.connected) {
    setPill(pill, "success", "완료");
    connected.style.display = "block";
    form.style.display = "none";
    $("#telegram-masked").textContent = `chat_id ${status.chat_id}`;
  } else {
    setPill(pill, "neutral", "연결 필요");
    connected.style.display = "none";
    form.style.display = "block";
  }
  setDone("telegram-card", status.connected);
  return status.connected;
}

function renderMissedBanner(missed) {
  const el = $("#missed-banner");
  if (!missed) { el.style.display = "none"; return; }

  // 실패가 먼저다 — 놓친 것보다 지금 고쳐야 할 문제이기 때문
  if (missed.lastError) {
    el.className = "banner error";
    el.innerHTML = `<b>마지막 확인이 실패했어요.</b><br>${escapeHtml(missed.lastError)}
      <div class="banner-act"><button class="btn ghost" id="banner-run">지금 확인하기</button></div>`;
  } else if (missed.missedCount > 0) {
    // 시각을 전부 나열하면 읽히지 않는다 — 마지막 확인이 언제였는지만 짚어준다
    const last = missed.lastSuccessAt
      ? new Date(missed.lastSuccessAt).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "numeric", minute: "2-digit" })
      : null;
    el.className = "banner";
    el.innerHTML = `<b>${missed.missedCount}번 확인하지 못했어요.</b>
      ${last ? `마지막 확인은 ${escapeHtml(last)}이에요.` : ""}
      <div class="banner-act"><button class="btn ghost" id="banner-run">지금 확인하기</button></div>`;
  } else {
    el.style.display = "none";
    return;
  }
  el.style.display = "block";
  const btn = $("#banner-run");
  if (btn) btn.addEventListener("click", () => $("#run-btn")?.click());
}

function escapeHtml(t) {
  return String(t).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function refreshRuns() {
  const { runs, missed } = await api("/api/runs");
  renderMissedBanner(missed);
  const list = $("#run-list");
  if (!runs || runs.length === 0) {
    list.innerHTML = '<div class="empty-line">아직 실행한 적 없어요</div>';
    return;
  }
  list.innerHTML = runs
    .map((r) => {
      const time = new Date(r.at).toLocaleString("ko-KR", { hour12: false });
      let summary;
      if (!r.ok) summary = `실패 · ${escapeHtml(r.error || "")}`;
      else if (!r.sent) summary = "새 소식 없음";
      else summary = `일정 ${r.new_schedule}건 · 공지 ${r.new_announcements}건 전송함`;
      return `<div class="run-row"><span>${time}</span><span>${summary}</span></div>`;
    })
    .join("");
}

function formatNextRun(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `다음 자동 확인: ${d.toLocaleString("ko-KR", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}쯤`;
}

function renderScheduleUI() {
  const activeMode = visiblePanel || currentSchedule.schedule_mode;
  document
    .querySelectorAll("#schedule-mode-seg .seg-item")
    .forEach((btn) => btn.setAttribute("aria-pressed", btn.dataset.mode === activeMode));

  $("#mode-interval").style.display = activeMode === "interval" ? "block" : "none";
  $("#mode-fixed").style.display = activeMode === "fixed" ? "block" : "none";

  $("#poll-chips").innerHTML = POLL_OPTIONS.map(
    (o) =>
      `<button type="button" class="chip-btn" data-minutes="${o.minutes}" aria-pressed="${
        currentSchedule.poll_minutes === o.minutes
      }">${o.label}</button>`
  ).join("");
  $("#poll-chips")
    .querySelectorAll(".chip-btn")
    .forEach((btn) => btn.addEventListener("click", () => saveSchedule({ poll_minutes: Number(btn.dataset.minutes) })));

  const times = [...currentSchedule.fixed_times].sort();
  $("#fixed-times-chips").innerHTML =
    times.length === 0
      ? '<span class="field-hint" style="margin:0">아직 추가한 시각이 없어요</span>'
      : times
          .map((t) => `<span class="chip-removable">${escapeHtml(t)}<button type="button" data-remove="${escapeHtml(t)}">✕</button></span>`)
          .join("");
  $("#fixed-times-chips")
    .querySelectorAll("[data-remove]")
    .forEach((btn) =>
      btn.addEventListener("click", () => {
        const remaining = currentSchedule.fixed_times.filter((t) => t !== btn.dataset.remove);
        saveSchedule(
          remaining.length === 0
            ? { schedule_mode: "off", fixed_times: [] }
            : { fixed_times: remaining }
        );
      })
    );

  // activeMode가 실제 저장된 schedule_mode와 다르면(= 아직 저장 안 하고 미리보기만 하는 탭)
  // 예전 설정의 "다음 자동 확인" 값을 그대로 보여주면 헷갈리니 비워둔다.
  $("#next-run-hint").textContent =
    activeMode !== currentSchedule.schedule_mode || currentSchedule.schedule_mode === "off"
      ? ""
      : currentSchedule.running
      ? "지금 자동 확인 중이에요"
      : formatNextRun(currentSchedule.next_run_at);
}

async function refreshSchedule() {
  currentSchedule = await api("/api/schedule");
  visiblePanel = null;
  renderScheduleUI();
}

// 저장 버튼이 없는 화면이라(DESIGN.md: 수동 저장 버튼 없음) 저장됐다는 사실을 말로 알려준다.
// 무엇으로 저장됐는지까지 담아야 "눌렀는데 뭐가 바뀐 거지" 하는 상태가 안 생긴다.
function scheduleSavedMessage(sc) {
  if (sc.schedule_mode === "off") return "자동 확인을 껐어요";
  if (sc.schedule_mode === "interval") return `${sc.poll_minutes}분마다 확인할게요`;
  const times = (sc.fixed_times || []).join(", ");
  return times ? `매일 ${times}에 확인할게요` : "확인할 시각을 골라 주세요";
}

async function saveSchedule(partial) {
  const body = {
    schedule_mode: currentSchedule.schedule_mode,
    poll_minutes: currentSchedule.poll_minutes,
    fixed_times: currentSchedule.fixed_times,
    ...partial,
  };
  const result = await api("/api/schedule", { method: "POST", body });
  if (result.error) {
    showToast(result.error);
    return false;
  }
  currentSchedule = result;
  visiblePanel = null;
  renderScheduleUI();
  showToast(scheduleSavedMessage(result));
  return true;
}

// 미리보기는 서버가 실제 전송 함수로 만들어 준다 — 화면에 예시를 적어두면 포맷이 바뀔 때 어긋난다
let formatPreviews = null;

function renderFormatUI(fmt) {
  document.querySelectorAll("#format-seg .seg-item").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.format === fmt)));
  // 두 미리보기를 항상 같이 채운다 — 고르지 않고도 비교할 수 있게
  document.querySelectorAll("[data-preview]").forEach((el) => {
    el.textContent = formatPreviews
      ? (formatPreviews[el.dataset.preview] || "")
      : "불러오는 중…";
  });
  // 어느 쪽으로 보내는지는 색이 아니라 말로 알린다
  document.querySelectorAll("[data-state]").forEach((el) => {
    el.textContent = el.dataset.state === fmt ? "· 지금 이 모양으로 보내요" : "";
  });
}

async function loadFormatPreviews() {
  try {
    formatPreviews = await api("/api/message-preview");
  } catch (err) {
    formatPreviews = null;
  }
  renderFormatUI(currentPrefs?.message_format || "detailed");
}

document.querySelectorAll("#format-seg .seg-item").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const fmt = btn.dataset.format;
    renderFormatUI(fmt);   // 먼저 반영해 눌린 느낌을 준다
    try {
      await api("/api/message-format", { method: "POST", body: { format: fmt } });
      showToast(fmt === "simple" ? "간단히 보낼게요" : "자세히 보낼게요");
    } catch (err) {
      showToast("알림 형식을 저장하지 못했어요");
    }
  }));

document.querySelectorAll("#schedule-mode-seg .seg-item").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const mode = btn.dataset.mode;

    if (mode === currentSchedule.schedule_mode) {
      // 이미 저장돼 있는 진짜 모드로 돌아가는 것 - 다시 저장할 필요 없이 미리보기만 해제
      visiblePanel = null;
      renderScheduleUI();
      return;
    }

    if (mode === "fixed" && currentSchedule.fixed_times.length === 0) {
      // 아직 시각을 하나도 안 넣었으면 서버에 저장하지 않고 입력 패널만 미리 보여준다
      visiblePanel = "fixed";
      renderScheduleUI();
      return;
    }
    if (mode === "interval" && !currentSchedule.poll_minutes) {
      await saveSchedule({ schedule_mode: mode, poll_minutes: POLL_OPTIONS[0].minutes });
    } else {
      await saveSchedule({ schedule_mode: mode });
    }
    showToast({ off: "자동 확인을 껐어요", interval: "반복 주기로 확인할게요", fixed: "정해진 시각에 확인할게요" }[mode]);
  })
);

$("#add-fixed-time").addEventListener("click", async () => {
  const input = $("#fixed-time-input");
  if (!input.value) {
    showToast("시각을 먼저 선택하세요");
    return;
  }
  if (currentSchedule.fixed_times.includes(input.value)) {
    showToast("이미 추가된 시각이에요");
    return;
  }
  const ok = await saveSchedule({
    schedule_mode: "fixed",
    fixed_times: [...currentSchedule.fixed_times, input.value].sort(),
  });
  if (ok) input.value = "";   // 저장 안내는 saveSchedule 이 더 구체적으로 띄운다
});

function renderTypeChips() {
  const selected = currentPrefs.types === null ? TYPES.map((t) => t.key) : currentPrefs.types;
  $("#type-chips").innerHTML = TYPES.map(
    (t) =>
      `<button type="button" class="chip-btn" data-type="${t.key}" aria-pressed="${selected.includes(t.key)}">${t.label}</button>`
  ).join("");
  $("#type-chips")
    .querySelectorAll(".chip-btn")
    .forEach((btn) => btn.addEventListener("click", () => toggleType(btn.dataset.type)));
}

function renderCourseList() {
  const courses = currentPrefs.known_courses || [];
  const list = $("#course-list");
  if (courses.length === 0) {
    list.innerHTML = '<div class="empty-line">아직 과목 목록을 안 가져왔어요</div>';
    return;
  }
  const selected = currentPrefs.course_ids === null ? courses.map((c) => c.id) : currentPrefs.course_ids;
  list.innerHTML = courses
    .map(
      (c) => `
    <label class="course-row">
      <input type="checkbox" data-course="${escapeHtml(c.id)}" ${selected.includes(c.id) ? "checked" : ""} />
      <span>${escapeHtml(c.name)}</span>
    </label>`
    )
    .join("");
  list.querySelectorAll("input[type=checkbox]").forEach((cb) =>
    cb.addEventListener("change", () => toggleCourse(cb.dataset.course))
  );
}

function updateFiltersPill() {
  const customized = currentPrefs.course_ids !== null || currentPrefs.types !== null;
  setPill($("#filters-pill"), customized ? "success" : "neutral", customized ? "맞춤 설정" : "전체");
}

async function savePrefs() {
  try {
    currentPrefs = await api("/api/prefs", {
      method: "POST",
      body: { course_ids: currentPrefs.course_ids, types: currentPrefs.types },
    });
  } catch (err) {
    showToast("설정을 저장하지 못했어요");
    return;
  }
  updateFiltersPill();
  showToast("저장했어요");
}

function toggleType(key) {
  const all = TYPES.map((t) => t.key);
  const selected = new Set(currentPrefs.types === null ? all : currentPrefs.types);
  if (selected.has(key)) selected.delete(key);
  else selected.add(key);
  currentPrefs.types = selected.size === all.length ? null : Array.from(selected);
  renderTypeChips();
  savePrefs();
}

function toggleCourse(id) {
  const all = (currentPrefs.known_courses || []).map((c) => c.id);
  const selected = new Set(currentPrefs.course_ids === null ? all : currentPrefs.course_ids);
  if (selected.has(id)) selected.delete(id);
  else selected.add(id);
  currentPrefs.course_ids = selected.size === all.length ? null : Array.from(selected);
  renderCourseList();
  savePrefs();
}

async function loadPrefs() {
  currentPrefs = await api("/api/prefs");
  renderTypeChips();
  renderCourseList();
  updateFiltersPill();
  renderFormatUI(currentPrefs.message_format || "detailed");
  if (!formatPreviews) loadFormatPreviews();
}

$("#refresh-courses").addEventListener("click", async () => {
  const btn = $("#refresh-courses");
  const stop = startLoading(btn);
  const result = await api("/api/courses/refresh", { method: "POST", body: {} });
  stop();
  btn.disabled = false;
  btn.textContent = "과목 불러오기";
  if (result.error) {
    showToast(result.error);
    return;
  }
  currentPrefs = result;
  renderCourseList();
  showToast(`과목 ${result.known_courses.length}개를 가져왔어요`);
});

// 실제로 Canvas 인지 확인한 학교만 넣는다. 도메인을 추측해서 넣으면
// 틀렸을 때 "우리 학교는 안 되는구나"로 오해받는다.
// 실제로 Canvas 인지 확인한 학교만 넣는다. 도메인을 추측해서 넣으면
// 틀렸을 때 "우리 학교는 안 되는구나"로 오해받는다.
// 확인 방법: /api/v1/users/self 가 Canvas 특유의 "Invalid access token." 을 돌려주고,
// 텔레그램 도움말 (i) 토글
(function () {
  const btn = $("#telegram-help-btn"), panel = $("#telegram-help");
  if (!btn || !panel) return;
  btn.addEventListener("click", () => {
    const open = panel.hasAttribute("hidden");
    if (open) panel.removeAttribute("hidden");
    else panel.setAttribute("hidden", "");
    btn.setAttribute("aria-expanded", String(open));
  });
})();

$("#account-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = $("#account-error");
  const submitBtn = $("#account-submit");
  errorEl.style.display = "none";

  const body = { student_id: $("#student-id").value.trim(), password: $("#password").value };

  const stop = startLoading(submitBtn);
  const result = await api("/api/account", { method: "POST", body });
  stop();
  submitBtn.disabled = false;
  submitBtn.textContent = "연결하기";
  if (result.ok === false || result.error) {
    errorEl.textContent = result.error || "연결에 실패했어요";
    errorEl.style.display = "block";
    return;
  }
  $("#password").value = "";
  showToast("LMS 계정이 연결됐어요");
  await refreshFlowState();
});

$("#account-disconnect").addEventListener("click", async () => {
  await api("/api/account/disconnect", { method: "POST", body: {} });
  showToast("연결을 해제했어요");
  await refreshFlowState();
});

$("#fetch-chat-id").addEventListener("click", async () => {
  const bot_token = $("#bot-token").value.trim();
  if (!bot_token) {
    showToast("봇 토큰을 먼저 입력하세요");
    return;
  }
  const result = await api("/api/telegram/chat-id", { method: "POST", body: { bot_token } });
  if (result.chat_id) {
    $("#chat-id").value = result.chat_id;
    showToast("chat_id를 찾았어요");
  } else {
    showToast("아직 메시지를 못 받았어요. 봇에게 먼저 메시지를 보내보세요");
  }
});

$("#telegram-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const bot_token = $("#bot-token").value.trim();
  const chat_id = $("#chat-id").value.trim();
  const errorEl = $("#telegram-error");
  const submitBtn = $("#telegram-submit");
  errorEl.style.display = "none";
  const stop = startLoading(submitBtn);
  const result = await api("/api/telegram", { method: "POST", body: { bot_token, chat_id } });
  stop();
  submitBtn.disabled = false;
  submitBtn.textContent = "연결하기";
  if (result.ok === false || result.error) {
    errorEl.textContent = result.error || "연결에 실패했어요";
    errorEl.style.display = "block";
    return;
  }
  showToast("텔레그램이 연결됐어요. 확인 메시지를 보냈어요");
  await refreshFlowState();
});

$("#telegram-disconnect").addEventListener("click", async () => {
  await api("/api/telegram/disconnect", { method: "POST", body: {} });
  showToast("연결을 해제했어요");
  await refreshFlowState();
});

$("#run-btn").addEventListener("click", async () => {
  const btn = $("#run-btn");
  const resultBox = $("#run-result");
  const stop = startLoading(btn);
  const result = await api("/api/run", { method: "POST", body: { days: 7 } });
  stop();
  btn.disabled = false;
  btn.textContent = "지금 확인해서 보내기";

  resultBox.style.display = "block";
  if (result.error) {
    resultBox.textContent = result.error;
  } else if (!result.ok) {
    resultBox.textContent = `로그인에 실패했어요: ${result.error}`;
  } else if (!result.sent) {
    resultBox.textContent = "새로운 일정/공지가 없어요.";
  } else {
    resultBox.textContent = result.preview;
    showToast("텔레그램으로 보냈어요");
  }
  await refreshRuns();
});

async function refreshFlowState() {
  const [accountOk, telegramOk] = await Promise.all([refreshAccount(), refreshTelegram()]);
  setLocked("filters-card", !accountOk);
  setLocked("telegram-card", !accountOk);
  setLocked("run-card", !(accountOk && telegramOk));
  $("#run-btn").disabled = !(accountOk && telegramOk);
  return { accountOk, telegramOk };
}

(async function init() {
  await refreshFlowState();
  await loadPrefs();
  await refreshRuns();
  await refreshSchedule();
  setInterval(refreshSchedule, 30000);
  setInterval(refreshRuns, 30000);
})();
