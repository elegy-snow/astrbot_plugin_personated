/**
 * Personated Companion Dashboard - Schedule Module Controller
 * Communicates with AstrBot Core via window.AstrBotPluginView (Bridge SDK)
 */

// 1. Initialize AstrBot Bridge (with graceful fallback and polling for deferred injection)
let _bridge = null;
async function getBridge() {
  if (_bridge) return _bridge;
  const deadline = Date.now() + 3000;
  while (!window.AstrBotPluginPage && !window.AstrBotPluginView && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 50));
  }
  _bridge = window.AstrBotPluginPage || window.AstrBotPluginView;
  if (!_bridge) {
    console.warn("[Bridge] AstrBotPluginPage / AstrBotPluginView bridge not found within timeout");
    return null;
  }
  if (typeof _bridge.ready === "function") {
    try {
      await Promise.race([
        _bridge.ready(),
        new Promise((_, reject) => setTimeout(() => reject(new Error("bridge.ready timeout")), 1500)),
      ]);
    } catch (e) {
      console.warn("[Bridge] ready() warning:", e);
    }
  }
  return _bridge;
}

const DEFAULT_SEGMENTS_PRESET = [
  { id: "morning_early", name: "清晨苏醒与晨练", start: "06:00", end: "08:30" },
  { id: "morning_work", name: "上午工作/学习", start: "08:30", end: "12:00" },
  { id: "lunch_rest", name: "午休与用餐", start: "12:00", end: "14:00" },
  { id: "afternoon_work", name: "下午工作/日常", start: "14:00", end: "18:00" },
  { id: "evening_leisure", name: "傍晚娱乐与晚餐", start: "18:00", end: "22:00" },
  { id: "night_sleep", name: "夜间就寝休息", start: "22:00", end: "06:00" },
];

// App State
const state = {
  activeView: "view-live",
  todayData: null,
  rulesConfig: null,
  rulesSegments: [],
  // Editor State
  selectedDate: formatLocalDate(new Date()),
  editorSchedule: null,
  editorItems: [],
  editorMode: "cards", // 'cards' | 'table'
  historyDates: [],
  // Modal State
  modalTarget: null, // { context: 'live' | 'editor', index: number, isNew: boolean }
  // UMO Prompt Injector State
  umoRules: [],
  umoConfig: { enabled: true, default_inject_mode: "system_prompt", total_rules: 0, enabled_rules: 0 },
  discoveredUmos: [],
  umoFilter: { search: "", chatType: "all", status: "all" },
};

// ============================================================================
// API Helper
// ============================================================================
function unwrapApiResponse(resp) {
  if (resp && typeof resp === "object") {
    if (resp.data !== undefined && (resp.status === "ok" || resp.status === undefined)) {
      return resp.data;
    }
  }
  return resp;
}

async function apiGet(endpoint, params = {}) {
  const b = await getBridge();
  if (b && typeof b.apiGet === "function") {
    try {
      const resp = await b.apiGet(endpoint, params);
      return unwrapApiResponse(resp);
    } catch (e) {
      console.error(`Bridge apiGet failed for ${endpoint}:`, e);
      throw e;
    }
  }
  // Local development / browser preview fallback
  console.warn(`[MockBridge] GET ${endpoint}`, params);
  return null;
}

async function apiPost(endpoint, body = {}) {
  const b = await getBridge();
  if (b && typeof b.apiPost === "function") {
    try {
      const resp = await b.apiPost(endpoint, body);
      return unwrapApiResponse(resp);
    } catch (e) {
      console.error(`Bridge apiPost failed for ${endpoint}:`, e);
      throw e;
    }
  }
  // Local development / browser preview fallback
  console.warn(`[MockBridge] POST ${endpoint}`, body);
  return { status: "ok" };
}

// ============================================================================
// UI & Toast Helpers
// ============================================================================
function showToast(message, type = "info") {
  const toast = document.getElementById("toast");
  if (!toast) return;

  toast.textContent = message;
  toast.className = `toast show ${type === "error" ? "toast-error" : type === "success" ? "toast-success" : ""}`;

  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    toast.className = "toast";
  }, 3500);
}

function formatLocalDate(dateObj) {
  const y = dateObj.getFullYear();
  const m = String(dateObj.getMonth() + 1).padStart(2, "0");
  const d = String(dateObj.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function updateClock() {
  const now = new Date();
  const timeEl = document.getElementById("clock-display");
  const dateEl = document.getElementById("date-display");

  if (timeEl) {
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    const ss = String(now.getSeconds()).padStart(2, "0");
    timeEl.textContent = `${hh}:${mm}:${ss}`;
  }

  if (dateEl) {
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const date = String(now.getDate()).padStart(2, "0");
    const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
    dateEl.textContent = `${year}/${month}/${date} 周${weekdays[now.getDay()]}`;
  }
}

function isCrossMidnight(start, end) {
  if (!start || !end) return false;
  return start > end;
}

// ============================================================================
// View Navigation
// ============================================================================
function switchView(viewId) {
  state.activeView = viewId;

  // Update sidebar active class
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
    if (item.getAttribute("data-view") === viewId) {
      item.classList.add("active");
    } else {
      item.classList.remove("active");
    }
  });

  // Update panels
  document.querySelectorAll(".view-panel").forEach((panel) => {
    if (panel.id === viewId) {
      panel.classList.add("active");
    } else {
      panel.classList.remove("active");
    }
  });

  // Update breadcrumb
  const breadcrumb = document.getElementById("breadcrumb-title");
  if (breadcrumb) {
    const titles = {
      "view-live": "今日即时看板",
      "view-editor": "日程查看与编辑",
      "view-rules": "作息规则与分段",
      "view-umo-injector": "会话专属提示词注入",
    };
    breadcrumb.textContent = titles[viewId] || "拟人化看板";
  }

  // Trigger data refresh on switch
  if (viewId === "view-live") {
    loadTodayLive();
  } else if (viewId === "view-editor") {
    loadHistoryDates();
    loadEditorSchedule(state.selectedDate);
  } else if (viewId === "view-rules") {
    loadRulesConfig();
  } else if (viewId === "view-umo-injector") {
    loadUmoConfigAndRules();
  }
}

// ============================================================================
// VIEW 1: 今日即时看板 (Live Board)
// ============================================================================
async function loadTodayLive() {
  const timelineEl = document.getElementById("live-timeline-list");
  if (!timelineEl) return;

  try {
    const res = await apiGet("schedule/today");
    if (!res) {
      timelineEl.innerHTML = '<div class="loading-box">无法连接到插件服务，请确保插件正常运行</div>';
      const actEl = document.getElementById("live-activity-text");
      if (actEl) actEl.textContent = "无法获取今日状态，请点击右上角刷新";
      const stateEl = document.getElementById("live-state-text");
      if (stateEl) stateEl.textContent = "未连接";
      return;
    }

    state.todayData = res;

    // Fill stats
    document.getElementById("stat-today-date").textContent = `${res.date || "--"} (${res.weekday || "--"})`;
    document.getElementById("stat-today-gentime").textContent = res.daily_generate_time || "04:00";
    document.getElementById("stat-today-model").textContent = res.schedule_provider_id || "自动回退对话模型";

    const schedule = res.today_schedule;
    const items = schedule && Array.isArray(schedule.items) ? schedule.items : [];
    document.getElementById("stat-today-count").textContent = `${items.length} 段`;

    // Fill Hero live status
    const activeSeg = res.active_segment;
    const badgeEl = document.getElementById("live-segment-badge");
    const actEl = document.getElementById("live-activity-text");
    const stateEl = document.getElementById("live-state-text");
    const quickEditBtn = document.getElementById("btn-quick-edit-now");

    if (activeSeg) {
      badgeEl.textContent = `${activeSeg.name} (${activeSeg.start} ~ ${activeSeg.end})`;
      badgeEl.className = "badge badge-active";
      actEl.textContent = activeSeg.activity || "日常活动中";
      stateEl.textContent = activeSeg.state || "平和自然";
      quickEditBtn.disabled = false;
    } else {
      badgeEl.textContent = "未匹配到当前时段";
      badgeEl.className = "badge badge-gray";
      actEl.textContent = "当前未在任何预定作息时段内或今日暂未生成作息安排";
      stateEl.textContent = "待命中";
      quickEditBtn.disabled = true;
    }

    // Render Timeline
    if (items.length === 0) {
      timelineEl.innerHTML = `
        <div class="loading-box">
          <p>今日（${res.date}）尚未生成日程安排。</p>
          <button class="btn btn-primary btn-sm" style="margin-top: 12px;" onclick="window._triggerLiveRegenerate()">
            ✨ 立即规划今日作息
          </button>
        </div>
      `;
      return;
    }

    let html = "";
    items.forEach((item, idx) => {
      const isActive = activeSeg && activeSeg.id === item.id;
      const cross = isCrossMidnight(item.start, item.end);

      html += `
        <div class="timeline-card ${isActive ? "is-active" : ""}" data-id="${escapeHtml(item.id)}">
          <div class="timeline-card-header">
            <div class="timeline-title-wrap">
              <span class="timeline-name">${escapeHtml(item.name)}</span>
              <span class="timeline-time-pill">${escapeHtml(item.start)} - ${escapeHtml(item.end)}</span>
              ${cross ? '<span class="tag-cross-midnight">🌙 跨夜</span>' : ""}
              ${isActive ? '<span class="badge badge-active">🟢 进行中</span>' : ""}
            </div>
            <button class="btn btn-secondary btn-sm" onclick="window._editLiveItem('${escapeHtml(item.id)}')">
              ✏️ 编辑此段
            </button>
          </div>
          <div class="timeline-card-body">
            <div class="timeline-activity-row">
              <strong>活动事件：</strong>${escapeHtml(item.activity)}
            </div>
            <div class="timeline-state-row">
              <strong>心情状态：</strong>${escapeHtml(item.state)}
            </div>
          </div>
        </div>
      `;
    });

    timelineEl.innerHTML = html;
  } catch (err) {
    console.error("loadTodayLive failed:", err);
    timelineEl.innerHTML = `<div class="loading-box" style="color:var(--danger)">加载今日日程出错：${escapeHtml(err.message || String(err))}</div>`;
    const actEl = document.getElementById("live-activity-text");
    if (actEl) actEl.textContent = "同步失败：" + (err.message || String(err));
    const stateEl = document.getElementById("live-state-text");
    if (stateEl) stateEl.textContent = "异常";
  }
}

// ============================================================================
// VIEW 2: 日程查看与详细编辑 (Editor & History)
// ============================================================================
async function loadHistoryDates() {
  const selectEl = document.getElementById("select-history-dates");
  if (!selectEl) return;

  try {
    const res = await apiGet("schedule/dates");
    if (res && Array.isArray(res.dates)) {
      state.historyDates = res.dates;

      let html = '<option value="">-- 选择已存档历史日期 --</option>';
      res.dates.forEach((d) => {
        const isCurrent = d.date === state.selectedDate;
        html += `<option value="${d.date}" ${isCurrent ? "selected" : ""}>${d.date} (${d.weekday || ""}, ${d.items_count}段)</option>`;
      });
      selectEl.innerHTML = html;
    }
  } catch (e) {
    console.warn("loadHistoryDates failed:", e);
  }
}

async function loadEditorSchedule(dateStr) {
  state.selectedDate = dateStr;

  const dateInput = document.getElementById("editor-date-input");
  if (dateInput) dateInput.value = dateStr;

  const cardsContainer = document.getElementById("editor-cards-container");
  const tableBody = document.getElementById("editor-table-body");

  if (cardsContainer) cardsContainer.innerHTML = '<div class="loading-box">正在读取日程数据...</div>';
  if (tableBody) tableBody.innerHTML = '<tr><td colspan="7" class="loading-box">正在读取日程数据...</td></tr>';

  try {
    const res = await apiGet("schedule/detail", { date: dateStr });
    if (!res || !res.found || !res.schedule) {
      state.editorSchedule = null;
      state.editorItems = [];

      // Update meta bar
      document.getElementById("editor-meta-date").textContent = `${dateStr} (暂无数据)`;
      document.getElementById("editor-meta-count").textContent = "共 0 个时段";
      document.getElementById("editor-meta-provider").textContent = "模型: --";
      document.getElementById("editor-meta-gentime").textContent = "生成于: --";

      const emptyHtml = `
        <div class="loading-box">
          <p>日期【${dateStr}】暂未生成日程安排。</p>
          <div style="margin-top: 14px; display: flex; gap: 10px; justify-content: center;">
            <button class="btn btn-primary btn-sm" onclick="window._triggerEditorRegenerate()">
              ✨ 立即以此日生成日程
            </button>
            <button class="btn btn-secondary btn-sm" onclick="window._addNewEditorItem()">
              ➕ 手动添加事项
            </button>
          </div>
        </div>
      `;
      if (cardsContainer) cardsContainer.innerHTML = emptyHtml;
      if (tableBody) tableBody.innerHTML = `<tr><td colspan="7">${emptyHtml}</td></tr>`;
      return;
    }

    state.editorSchedule = res.schedule;
    state.editorItems = Array.isArray(res.schedule.items) ? JSON.parse(JSON.stringify(res.schedule.items)) : [];

    // Update meta bar
    document.getElementById("editor-meta-date").textContent = `${res.schedule.date} 星期${res.schedule.weekday || ""}`;
    document.getElementById("editor-meta-count").textContent = `共 ${state.editorItems.length} 个时段`;
    document.getElementById("editor-meta-provider").textContent = `模型: ${res.schedule.provider_used || "未知"}`;
    document.getElementById("editor-meta-gentime").textContent = `生成于: ${res.schedule.generated_at ? res.schedule.generated_at.substring(0, 16).replace("T", " ") : "--"}`;

    renderEditorViews();
  } catch (err) {
    console.error("loadEditorSchedule error:", err);
    if (cardsContainer) cardsContainer.innerHTML = `<div class="loading-box" style="color:var(--danger)">加载失败: ${escapeHtml(err.message || String(err))}</div>`;
  }
}

function renderEditorViews() {
  renderEditorCards();
  renderEditorTable();
}

function renderEditorCards() {
  const container = document.getElementById("editor-cards-container");
  if (!container) return;

  if (state.editorItems.length === 0) {
    container.innerHTML = `
      <div class="loading-box">
        <p>暂无时段事项。</p>
        <button class="btn btn-outline btn-sm" style="margin-top: 10px;" onclick="window._addNewEditorItem()">
          ➕ 添加第一个事项
        </button>
      </div>
    `;
    return;
  }

  let html = "";
  state.editorItems.forEach((item, idx) => {
    const cross = isCrossMidnight(item.start, item.end);
    html += `
      <div class="editor-item-card" data-index="${idx}">
        <div class="item-card-header">
          <div class="item-header-title">
            <span class="item-index-badge">#${idx + 1}</span>
            <h4>${escapeHtml(item.name || "未命名时段")}</h4>
            <span class="timeline-time-pill">${escapeHtml(item.start || "00:00")} - ${escapeHtml(item.end || "00:00")}</span>
            ${cross ? '<span class="tag-cross-midnight">🌙 跨夜</span>' : ""}
          </div>
          <div class="item-actions">
            <button class="btn btn-secondary btn-sm" onclick="window._moveEditorItem(${idx}, -1)" ${idx === 0 ? "disabled" : ""} title="上移">⬆️</button>
            <button class="btn btn-secondary btn-sm" onclick="window._moveEditorItem(${idx}, 1)" ${idx === state.editorItems.length - 1 ? "disabled" : ""} title="下移">⬇️</button>
            <button class="btn btn-secondary btn-sm" onclick="window._editEditorItem(${idx})">✏️ 编辑</button>
            <button class="btn btn-danger-outline btn-sm" onclick="window._deleteEditorItem(${idx})" title="删除">🗑️</button>
          </div>
        </div>
        <div class="item-card-body">
          <div class="item-card-field">
            <div class="item-field-label">正在做的事 (Activity)</div>
            <div class="item-field-val">${escapeHtml(item.activity || "--")}</div>
          </div>
          <div class="item-card-field">
            <div class="item-field-label">心情与心理状态 (State)</div>
            <div class="item-field-val">${escapeHtml(item.state || "--")}</div>
          </div>
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

function renderEditorTable() {
  const tbody = document.getElementById("editor-table-body");
  if (!tbody) return;

  if (state.editorItems.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading-box">暂无时段事项</td></tr>';
    return;
  }

  let html = "";
  state.editorItems.forEach((item, idx) => {
    html += `
      <tr data-index="${idx}">
        <td style="text-align: center; font-weight: 600;">${idx + 1}</td>
        <td>
          <input type="text" class="table-input" value="${escapeHtml(item.name || "")}" onchange="window._onTableFieldChange(${idx}, 'name', this.value)" />
        </td>
        <td>
          <input type="time" class="table-input" value="${escapeHtml(item.start || "00:00")}" onchange="window._onTableFieldChange(${idx}, 'start', this.value)" />
        </td>
        <td>
          <input type="time" class="table-input" value="${escapeHtml(item.end || "00:00")}" onchange="window._onTableFieldChange(${idx}, 'end', this.value)" />
        </td>
        <td>
          <textarea class="table-textarea" rows="2" onchange="window._onTableFieldChange(${idx}, 'activity', this.value)">${escapeHtml(item.activity || "")}</textarea>
        </td>
        <td>
          <input type="text" class="table-input" value="${escapeHtml(item.state || "")}" onchange="window._onTableFieldChange(${idx}, 'state', this.value)" />
        </td>
        <td>
          <div style="display: flex; gap: 4px;">
            <button class="btn-icon-text" onclick="window._editEditorItem(${idx})" title="弹窗详细编辑">✏️</button>
            <button class="btn-icon-text" style="color:var(--danger)" onclick="window._deleteEditorItem(${idx})" title="删除">🗑️</button>
          </div>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

// ============================================================================
// VIEW 3: 作息规则与分段模板 (Rules & Templates)
// ============================================================================
async function loadRulesConfig() {
  try {
    const res = await apiGet("schedule/config");
    if (!res) return;

    state.rulesConfig = res;
    state.rulesSegments = Array.isArray(res.schedule_segments)
      ? JSON.parse(JSON.stringify(res.schedule_segments))
      : JSON.parse(JSON.stringify(DEFAULT_SEGMENTS_PRESET));

    // Form inputs
    const genTimeInput = document.getElementById("rules-gen-time");
    if (genTimeInput) genTimeInput.value = res.daily_generate_time || "04:00";

    const injectModeSelect = document.getElementById("rules-inject-mode");
    if (injectModeSelect) injectModeSelect.value = res.inject_mode || "extra_user_content";

    const injectEnabledCheck = document.getElementById("rules-inject-enabled");
    if (injectEnabledCheck) injectEnabledCheck.checked = res.inject_context_enabled !== false;

    const promptTextarea = document.getElementById("rules-prompt-template");
    if (promptTextarea) promptTextarea.value = res.custom_prompt_template || "";

    // Provider select
    const provSelect = document.getElementById("rules-provider-select");
    if (provSelect) {
      let provHtml = '<option value="">(留空自动回退对话模型)</option>';
      if (Array.isArray(res.available_providers)) {
        res.available_providers.forEach((p) => {
          const isSelected = p.id === res.schedule_provider_id;
          provHtml += `<option value="${escapeHtml(p.id)}" ${isSelected ? "selected" : ""}>${escapeHtml(p.name)}</option>`;
        });
      }
      provSelect.innerHTML = provHtml;
    }

    renderRulesSegmentsTable();
  } catch (err) {
    console.error("loadRulesConfig error:", err);
    showToast("加载规则配置失败：" + (err.message || String(err)), "error");
  }
}

function renderRulesSegmentsTable() {
  const tbody = document.getElementById("rules-segments-tbody");
  if (!tbody) return;

  if (state.rulesSegments.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading-box">暂无分段定义，请点击上方“添加新时间段”或“恢复默认预设”</td></tr>';
    return;
  }

  let html = "";
  state.rulesSegments.forEach((seg, idx) => {
    const cross = isCrossMidnight(seg.start, seg.end);
    html += `
      <tr data-index="${idx}">
        <td style="text-align: center; font-weight: 600;">${idx + 1}</td>
        <td>
          <input type="text" class="table-input" value="${escapeHtml(seg.id || "")}" onchange="window._onRuleSegmentChange(${idx}, 'id', this.value)" placeholder="时段ID" />
        </td>
        <td>
          <input type="text" class="table-input" value="${escapeHtml(seg.name || "")}" onchange="window._onRuleSegmentChange(${idx}, 'name', this.value)" placeholder="如：上午工作" />
        </td>
        <td>
          <input type="time" class="table-input" value="${escapeHtml(seg.start || "00:00")}" onchange="window._onRuleSegmentChange(${idx}, 'start', this.value)" />
        </td>
        <td>
          <input type="time" class="table-input" value="${escapeHtml(seg.end || "00:00")}" onchange="window._onRuleSegmentChange(${idx}, 'end', this.value)" />
        </td>
        <td>
          ${cross ? '<span class="tag-cross-midnight">🌙 跨夜</span>' : '<span style="color:var(--text-muted); font-size:0.75rem;">当日内</span>'}
        </td>
        <td>
          <div style="display: flex; gap: 4px;">
            <button class="btn-icon-text" onclick="window._moveRuleSegment(${idx}, -1)" ${idx === 0 ? "disabled" : ""} title="上移">⬆️</button>
            <button class="btn-icon-text" onclick="window._moveRuleSegment(${idx}, 1)" ${idx === state.rulesSegments.length - 1 ? "disabled" : ""} title="下移">⬇️</button>
            <button class="btn-icon-text" style="color:var(--danger)" onclick="window._deleteRuleSegment(${idx})" title="删除">🗑️</button>
          </div>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

// ============================================================================
// Modal Dialog Controller
// ============================================================================
function openItemModal(opts) {
  state.modalTarget = opts;
  const modal = document.getElementById("item-modal");
  const titleEl = document.getElementById("modal-item-title");

  const nameInput = document.getElementById("modal-input-name");
  const idInput = document.getElementById("modal-input-id-val");
  const startInput = document.getElementById("modal-input-start");
  const endInput = document.getElementById("modal-input-end");
  const actTextarea = document.getElementById("modal-input-activity");
  const stateInput = document.getElementById("modal-input-state");

  if (opts.isNew) {
    titleEl.textContent = "添加新作息事项";
    nameInput.value = "";
    idInput.value = `seg_${Date.now().toString().slice(-4)}`;
    startInput.value = "12:00";
    endInput.value = "13:00";
    actTextarea.value = "";
    stateInput.value = "心情平静惬意";
  } else {
    titleEl.textContent = "编辑时段安排";
    const item = opts.item;
    nameInput.value = item.name || "";
    idInput.value = item.id || "";
    startInput.value = item.start || "00:00";
    endInput.value = item.end || "00:00";
    actTextarea.value = item.activity || "";
    stateInput.value = item.state || "";
  }

  modal.classList.add("show");
}

function closeItemModal() {
  const modal = document.getElementById("item-modal");
  modal.classList.remove("show");
  state.modalTarget = null;
}

async function saveItemModal() {
  if (!state.modalTarget) return;

  const name = document.getElementById("modal-input-name").value.trim();
  const id = document.getElementById("modal-input-id-val").value.trim();
  const start = document.getElementById("modal-input-start").value.trim();
  const end = document.getElementById("modal-input-end").value.trim();
  const activity = document.getElementById("modal-input-activity").value.trim();
  const itemState = document.getElementById("modal-input-state").value.trim();

  if (!name) {
    showToast("请输入时段名称", "error");
    return;
  }
  if (!start || !end) {
    showToast("起止时刻不能为空", "error");
    return;
  }

  const updatedItem = {
    id: id || `seg_${Date.now()}`,
    name,
    start,
    end,
    activity: activity || "日常活动",
    state: itemState || "平静",
  };

  const { context, index, isNew } = state.modalTarget;

  if (context === "editor") {
    if (isNew) {
      state.editorItems.push(updatedItem);
    } else {
      state.editorItems[index] = updatedItem;
    }
    renderEditorViews();
    closeItemModal();
    showToast("已更新项，请记得点击「保存所有修改」进行保存！", "info");
  } else if (context === "live") {
    // Directly call live update API
    try {
      const res = await apiPost("schedule/item/update", {
        id: updatedItem.id,
        activity: updatedItem.activity,
        state: updatedItem.state,
      });
      if (res && res.updated) {
        showToast("今日该时段状态已成功更新！", "success");
        closeItemModal();
        loadTodayLive();
      } else {
        showToast("更新失败：" + (res?.message || "未知原因"), "error");
      }
    } catch (err) {
      showToast("更新出错：" + (err.message || String(err)), "error");
    }
  }
}

// ============================================================================
// Global Window Event Handlers (for Inline HTML Calls)
// ============================================================================
function setupGlobalWindowHandlers() {
  // Live actions
  window._triggerLiveRegenerate = async () => {
    if (!confirm("确定要重新生成今日日程吗？这将覆盖今日现有的作息规划。")) return;
    showToast("正在请求大模型生成今日作息，请稍候...", "info");
    try {
      const res = await apiPost("schedule/generate");
      if (res && res.success) {
        showToast(res.message || "今日日程重新生成成功！", "success");
        loadTodayLive();
      } else {
        showToast("重新生成失败：" + (res?.message || "未知原因"), "error");
      }
    } catch (e) {
      showToast("请求失败: " + (e.message || String(e)), "error");
    }
  };

  window._editLiveItem = (itemId) => {
    if (!state.todayData || !state.todayData.today_schedule) return;
    const items = state.todayData.today_schedule.items || [];
    const item = items.find((x) => x.id === itemId);
    if (!item) return;

    openItemModal({
      context: "live",
      item,
      isNew: false,
    });
  };

  // Editor actions
  window._addNewEditorItem = () => {
    openItemModal({
      context: "editor",
      isNew: true,
    });
  };

  window._editEditorItem = (idx) => {
    const item = state.editorItems[idx];
    if (!item) return;
    openItemModal({
      context: "editor",
      index: idx,
      item,
      isNew: false,
    });
  };

  window._deleteEditorItem = (idx) => {
    state.editorItems.splice(idx, 1);
    renderEditorViews();
    showToast("已移除该时段，请点击「保存所有修改」完成保存。", "info");
  };

  window._moveEditorItem = (idx, delta) => {
    const targetIdx = idx + delta;
    if (targetIdx < 0 || targetIdx >= state.editorItems.length) return;
    const temp = state.editorItems[idx];
    state.editorItems[idx] = state.editorItems[targetIdx];
    state.editorItems[targetIdx] = temp;
    renderEditorViews();
  };

  window._onTableFieldChange = (idx, field, val) => {
    if (state.editorItems[idx]) {
      state.editorItems[idx][field] = val;
    }
  };

  window._triggerEditorRegenerate = async () => {
    const targetDate = state.selectedDate;
    if (!confirm(`确定要为日期【${targetDate}】重新生成作息日程吗？`)) return;

    showToast(`正在生成 ${targetDate} 的作息安排...`, "info");
    try {
      const res = await apiPost("schedule/generate-date", { date: targetDate });
      if (res && res.success) {
        showToast(res.message || "生成成功！", "success");
        loadHistoryDates();
        loadEditorSchedule(targetDate);
        if (targetDate === formatLocalDate(new Date())) {
          loadTodayLive();
        }
      } else {
        showToast("生成失败: " + (res?.message || "未知原因"), "error");
      }
    } catch (e) {
      showToast("请求失败: " + (e.message || String(e)), "error");
    }
  };

  // Rule Segment actions
  window._onRuleSegmentChange = (idx, field, val) => {
    if (state.rulesSegments[idx]) {
      state.rulesSegments[idx][field] = val;
      if (field === "start" || field === "end") {
        renderRulesSegmentsTable();
      }
    }
  };

  window._moveRuleSegment = (idx, delta) => {
    const targetIdx = idx + delta;
    if (targetIdx < 0 || targetIdx >= state.rulesSegments.length) return;
    const temp = state.rulesSegments[idx];
    state.rulesSegments[idx] = state.rulesSegments[targetIdx];
    state.rulesSegments[targetIdx] = temp;
    renderRulesSegmentsTable();
  };

  window._deleteRuleSegment = (idx) => {
    state.rulesSegments.splice(idx, 1);
    renderRulesSegmentsTable();
  };

  // UMO Prompt Injector actions
  window.openDiscoverModal = openDiscoverModal;
  window.closeDiscoverModal = closeDiscoverModal;
  window.selectDiscoveredUmo = selectDiscoveredUmo;
  window.openUmoRuleModal = openUmoRuleModal;
  window.closeUmoRuleModal = closeUmoRuleModal;
  window.toggleUmoRule = toggleUmoRule;
  window.deleteUmoRule = deleteUmoRule;
  window.copyToClipboard = copyToClipboard;
}

// ============================================================================
// DOM Event Binding & Initialization
// ============================================================================
function bindDomEvents() {
  // Navigation tabs
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
    item.addEventListener("click", () => {
      const viewId = item.getAttribute("data-view");
      switchView(viewId);
    });
  });

  // Global Refresh
  const btnGlobalRefresh = document.getElementById("btn-global-refresh");
  if (btnGlobalRefresh) {
    btnGlobalRefresh.addEventListener("click", () => {
      showToast("正在刷新...", "info");
      loadTodayLive();
      if (state.activeView === "view-editor") {
        loadHistoryDates();
        loadEditorSchedule(state.selectedDate);
      } else if (state.activeView === "view-rules") {
        loadRulesConfig();
      }
    });
  }

  // Live action buttons
  const btnLiveRegen = document.getElementById("btn-live-regenerate");
  if (btnLiveRegen) btnLiveRegen.addEventListener("click", window._triggerLiveRegenerate);

  const btnSwitchToEditor = document.getElementById("btn-switch-to-editor");
  if (btnSwitchToEditor) {
    btnSwitchToEditor.addEventListener("click", () => switchView("view-editor"));
  }

  const btnQuickEditNow = document.getElementById("btn-quick-edit-now");
  if (btnQuickEditNow) {
    btnQuickEditNow.addEventListener("click", () => {
      if (state.todayData && state.todayData.active_segment) {
        window._editLiveItem(state.todayData.active_segment.id);
      }
    });
  }

  // Editor date nav
  const dateInput = document.getElementById("editor-date-input");
  if (dateInput) {
    dateInput.value = state.selectedDate;
    dateInput.addEventListener("change", (e) => {
      if (e.target.value) {
        loadEditorSchedule(e.target.value);
      }
    });
  }

  const btnPrev = document.getElementById("btn-date-prev");
  if (btnPrev) {
    btnPrev.addEventListener("click", () => {
      const cur = new Date(state.selectedDate + "T00:00:00");
      cur.setDate(cur.getDate() - 1);
      const nextDate = formatLocalDate(cur);
      loadEditorSchedule(nextDate);
    });
  }

  const btnNext = document.getElementById("btn-date-next");
  if (btnNext) {
    btnNext.addEventListener("click", () => {
      const cur = new Date(state.selectedDate + "T00:00:00");
      cur.setDate(cur.getDate() + 1);
      const nextDate = formatLocalDate(cur);
      loadEditorSchedule(nextDate);
    });
  }

  const btnToday = document.getElementById("btn-date-today");
  if (btnToday) {
    btnToday.addEventListener("click", () => {
      const todayStr = formatLocalDate(new Date());
      loadEditorSchedule(todayStr);
    });
  }

  const selectHistoryDates = document.getElementById("select-history-dates");
  if (selectHistoryDates) {
    selectHistoryDates.addEventListener("change", (e) => {
      if (e.target.value) {
        loadEditorSchedule(e.target.value);
      }
    });
  }

  // Editor actions
  const btnEditorAdd = document.getElementById("btn-editor-add-item");
  if (btnEditorAdd) btnEditorAdd.addEventListener("click", window._addNewEditorItem);

  const btnEditorRegen = document.getElementById("btn-editor-regenerate");
  if (btnEditorRegen) btnEditorRegen.addEventListener("click", window._triggerEditorRegenerate);

  const btnEditorSaveAll = document.getElementById("btn-editor-save-all");
  if (btnEditorSaveAll) {
    btnEditorSaveAll.addEventListener("click", async () => {
      if (!state.selectedDate) return;
      showToast("正在保存修改...", "info");

      try {
        const payload = {
          date: state.selectedDate,
          items: state.editorItems,
          weekday: state.editorSchedule ? state.editorSchedule.weekday : undefined,
          persona_id: state.editorSchedule ? state.editorSchedule.persona_id : "default",
          provider_used: state.editorSchedule ? state.editorSchedule.provider_used : "manual_edit",
        };

        const res = await apiPost("schedule/save-full", payload);
        if (res && res.saved) {
          showToast(res.message || "已成功保存所有时段修改！", "success");
          loadHistoryDates();
          loadEditorSchedule(state.selectedDate);
          if (state.selectedDate === formatLocalDate(new Date())) {
            loadTodayLive();
          }
        } else {
          showToast("保存失败：" + (res?.message || "未知原因"), "error");
        }
      } catch (err) {
        showToast("保存出错：" + (err.message || String(err)), "error");
      }
    });
  }

  const btnEditorDeleteDay = document.getElementById("btn-editor-delete-day");
  if (btnEditorDeleteDay) {
    btnEditorDeleteDay.addEventListener("click", async () => {
      const d = state.selectedDate;
      if (!confirm(`确定要彻底删除日期【${d}】的全部日程记录吗？此操作无法撤销。`)) return;

      try {
        const res = await apiPost("schedule/delete-date", { date: d });
        if (res && res.deleted) {
          showToast(res.message || "已删除该日日程存档", "success");
          loadHistoryDates();
          loadEditorSchedule(d);
          if (d === formatLocalDate(new Date())) {
            loadTodayLive();
          }
        } else {
          showToast(res?.message || "删除未成功", "info");
        }
      } catch (e) {
        showToast("删除出错: " + (e.message || String(e)), "error");
      }
    });
  }

  // View Mode Tabs (Cards vs Table)
  document.querySelectorAll(".view-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.getAttribute("data-mode");
      state.editorMode = mode;

      document.querySelectorAll(".view-mode-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      const cardsContainer = document.getElementById("editor-cards-container");
      const tableContainer = document.getElementById("editor-table-container");

      if (mode === "cards") {
        cardsContainer.style.display = "flex";
        tableContainer.style.display = "none";
        renderEditorCards();
      } else {
        cardsContainer.style.display = "none";
        tableContainer.style.display = "block";
        renderEditorTable();
      }
    });
  });

  // Rules actions
  const btnRulesResetPreset = document.getElementById("btn-rules-reset-preset");
  if (btnRulesResetPreset) {
    btnRulesResetPreset.addEventListener("click", () => {
      if (!confirm("确定要恢复默认预设的 6 个时间段吗？")) return;
      state.rulesSegments = JSON.parse(JSON.stringify(DEFAULT_SEGMENTS_PRESET));
      renderRulesSegmentsTable();
      showToast("已恢复默认时间段预设，请记得点击下方保存。", "info");
    });
  }

  const btnRulesAddSeg = document.getElementById("btn-rules-add-segment");
  if (btnRulesAddSeg) {
    btnRulesAddSeg.addEventListener("click", () => {
      const count = state.rulesSegments.length + 1;
      state.rulesSegments.push({
        id: `seg_${Date.now().toString().slice(-4)}`,
        name: `新时段 ${count}`,
        start: "18:00",
        end: "20:00",
      });
      renderRulesSegmentsTable();
    });
  }

  const btnRulesSave = document.getElementById("btn-rules-save-all");
  if (btnRulesSave) {
    btnRulesSave.addEventListener("click", async () => {
      const genTime = document.getElementById("rules-gen-time").value.trim();
      const provId = document.getElementById("rules-provider-select").value.trim();
      const injectMode = document.getElementById("rules-inject-mode").value.trim();
      const injectEnabled = document.getElementById("rules-inject-enabled").checked;
      const promptTemplate = document.getElementById("rules-prompt-template").value.trim();

      if (!genTime) {
        showToast("请输入每日自动生成时刻", "error");
        return;
      }

      if (state.rulesSegments.length === 0) {
        showToast("时间段划分列表不能为空", "error");
        return;
      }

      showToast("正在保存规则配置...", "info");

      try {
        const payload = {
          daily_generate_time: genTime,
          schedule_provider_id: provId,
          inject_mode: injectMode,
          inject_context_enabled: injectEnabled,
          schedule_segments: state.rulesSegments,
          custom_prompt_template: promptTemplate,
        };

        const res = await apiPost("schedule/config/save", payload);
        if (res && res.saved) {
          showToast(res.message || "配置已成功保存！", "success");
          loadRulesConfig();
          loadTodayLive();
        } else {
          showToast("保存失败：" + (res?.message || "未知原因"), "error");
        }
      } catch (err) {
        showToast("保存出错：" + (err.message || String(err)), "error");
      }
    });
  }

  // Modal events
  const modalClose = document.getElementById("modal-item-close");
  const modalCancel = document.getElementById("modal-item-cancel");
  const modalSave = document.getElementById("modal-item-save");

  if (modalClose) modalClose.addEventListener("click", closeItemModal);
  if (modalCancel) modalCancel.addEventListener("click", closeItemModal);
  if (modalSave) modalSave.addEventListener("click", saveItemModal);

  // Bind UMO prompt injector DOM events
  bindUmoDomEvents();
}

// ============================================================================
// VIEW 4: 会话专属提示词注入 (UMO Prompt Injector)
// ============================================================================

const PROMPT_PRESETS = {
  group_assistant: "【群聊专属角色设定】\n你当前处于该群聊中。请以热情、友好、富有亲和力且略带幽默感的群助理语气参与交流。适时活跃气氛，主动帮助群友解答疑问，避免长篇大论，多使用简练口语化的交流方式。",
  formal_work: "【工作群专属角色设定】\n你当前处于正式工作/技术群聊中。回答请保持严谨、客观、专业且高效。直奔主题，给出经过验证的准确结论，条理清晰，不使用多余的闲聊废话。",
  playful_friend: "【密友互怼专属设定】\n你和对方是非常亲密无间、无话不谈的死党/好友。对话时语气轻松随意、带点小调侃和幽默吐槽，像日常微信好友私聊一样自然，不用客套，有话直说。",
  tsundere: "【傲娇角色专属设定】\n你对该会话的对象有着特殊的傲娇性格：表面上总爱撇嘴、挑刺或显得漫不经心（如'哼，才不是特意帮你的'），但字里行间却透露出细致的关切与陪伴，口是心非但非常真诚。",
  custom_context: "【专属背景与知识前置】\n请注意：当前会话拥有以下专属上下文和背景设定：\n1. 请严格遵守本群核心讨论规范。\n2. 默认使用通俗易懂的表述方式。\n3. 在涉及相关话题时，主动结合本群背景进行拓展说明。"
};

async function loadUmoConfigAndRules() {
  const listEl = document.getElementById("umo-rules-list");
  if (!listEl) return;

  try {
    // 1. Load global config
    const cfg = await apiGet("prompt-injector/config");
    if (cfg) {
      state.umoConfig = cfg;
      const toggleEl = document.getElementById("umo-global-enabled-toggle");
      if (toggleEl) toggleEl.checked = !!cfg.enabled;
      const modeEl = document.getElementById("stat-umo-default-mode");
      if (modeEl) modeEl.textContent = cfg.default_inject_mode || "system_prompt";
    }

    // 2. Load rules list
    const res = await apiGet("prompt-injector/rules");
    if (res && Array.isArray(res.rules)) {
      state.umoRules = res.rules;
    } else {
      state.umoRules = [];
    }

    // 3. Update stats
    const totalCountEl = document.getElementById("stat-umo-total-count");
    if (totalCountEl) totalCountEl.textContent = `${state.umoRules.length} 条`;

    const enabledCount = state.umoRules.filter((r) => r.enabled).length;
    const enabledCountEl = document.getElementById("stat-umo-enabled-count");
    if (enabledCountEl) enabledCountEl.textContent = `${enabledCount} 条`;

    // 4. Render
    renderUmoRules();
  } catch (err) {
    console.error("loadUmoConfigAndRules error:", err);
    listEl.innerHTML = `<div class="loading-box" style="color:var(--danger)">加载专属提示词规则失败：${escapeHtml(err.message || String(err))}</div>`;
  }
}

function renderUmoRules() {
  const listEl = document.getElementById("umo-rules-list");
  if (!listEl) return;

  const searchKeyword = (state.umoFilter.search || "").toLowerCase().trim();
  const chatTypeFilter = state.umoFilter.chatType || "all";
  const statusFilter = state.umoFilter.status || "all";

  const filtered = state.umoRules.filter((rule) => {
    // Search keyword against name, umo, group_id, prompt
    if (searchKeyword) {
      const matchName = (rule.name || "").toLowerCase().includes(searchKeyword);
      const matchUmo = (rule.umo || "").toLowerCase().includes(searchKeyword);
      const matchGroup = (rule.group_id || "").toLowerCase().includes(searchKeyword);
      const matchPrompt = (rule.prompt || "").toLowerCase().includes(searchKeyword);
      if (!matchName && !matchUmo && !matchGroup && !matchPrompt) return false;
    }

    // Chat type filter
    if (chatTypeFilter !== "all") {
      const isGroup = rule.chat_type === "group";
      if (chatTypeFilter === "group" && !isGroup) return false;
      if (chatTypeFilter === "private" && isGroup) return false;
    }

    // Status filter
    if (statusFilter === "enabled" && !rule.enabled) return false;
    if (statusFilter === "disabled" && rule.enabled) return false;

    return true;
  });

  if (filtered.length === 0) {
    listEl.innerHTML = `
      <div class="empty-state-card" style="text-align: center; padding: 48px 20px; background: var(--bg-card); border: 1px dashed var(--border); border-radius: var(--radius-md);">
        <div style="font-size: 2.8rem; margin-bottom: 12px;">💬</div>
        <h4 style="font-size: 1.1rem; margin-bottom: 6px; color: var(--text-main);">暂无会话专属提示词规则</h4>
        <p style="font-size: 0.9rem; color: var(--text-muted); max-width: 460px; margin: 0 auto 16px;">
          ${searchKeyword || chatTypeFilter !== "all" || statusFilter !== "all" ? "未找到符合当前过滤条件的规则，请尝试调整筛选条件。" : "您可以点击「从 AstrBot 对话抓取」直接挑选已产生对话的群聊或私聊一键配置，也可以手动点击「添加专属规则」。"}
        </p>
        <div style="display: flex; gap: 10px; justify-content: center;">
          <button class="btn btn-secondary" onclick="openDiscoverModal()">🔍 从 AstrBot 对话抓取</button>
          <button class="btn btn-primary" onclick="openUmoRuleModal('')">➕ 手动添加规则</button>
        </div>
      </div>
    `;
    return;
  }

  listEl.innerHTML = filtered
    .map((rule) => {
      const isGroup = rule.chat_type === "group";
      const typeBadge = isGroup
        ? `<span class="tag-chat-group">👥 群聊 ${rule.group_id ? "#" + escapeHtml(rule.group_id) : ""}</span>`
        : `<span class="tag-chat-private">👤 私聊会话</span>`;

      const platformBadge = rule.platform_name_cn
        ? `<span class="tag-platform-pill">${escapeHtml(rule.platform_name_cn)}</span>`
        : "";

      const modeBadge = `<span class="badge badge-gray" style="font-size:0.75rem;">模式: ${escapeHtml(rule.inject_mode || "system_prompt")}</span>`;
      const statusClass = rule.enabled ? "enabled" : "disabled";
      const toggleChecked = rule.enabled ? "checked" : "";

      const promptSnippet = escapeHtml(rule.prompt || "（无内容）");

      return `
        <div class="umo-rule-card ${statusClass}">
          <div class="rule-card-header">
            <div class="rule-title-group">
              <span class="rule-name-text">${escapeHtml(rule.name || rule.display_badge || "未命名会话")}</span>
              ${typeBadge}
              ${platformBadge}
              ${modeBadge}
            </div>
            <div class="rule-actions-group">
              <label class="toggle-control" title="启用/禁用此规则">
                <input type="checkbox" ${toggleChecked} onchange="toggleUmoRule('${escapeHtml(rule.umo)}', this.checked)" />
                <span class="toggle-track"></span>
              </label>
              <button class="btn btn-secondary btn-sm" onclick="openUmoRuleModal('${escapeHtml(rule.umo)}')">✏️ 编辑</button>
              <button class="btn btn-danger btn-sm" onclick="deleteUmoRule('${escapeHtml(rule.umo)}')">🗑️ 删除</button>
            </div>
          </div>

          <div class="rule-umo-row">
            <span>🏷️ UMO:</span>
            <code class="rule-umo-code">${escapeHtml(rule.umo)}</code>
            <button class="btn-copy-umo" onclick="copyToClipboard('${escapeHtml(rule.umo)}')" title="复制 UMO 字符串">📋 复制</button>
          </div>

          <div class="rule-prompt-box">${promptSnippet}</div>

          <div class="rule-card-footer">
            <span>更新时间：${escapeHtml(rule.updated_at ? rule.updated_at.replace("T", " ").slice(0, 19) : "最近")}</span>
            <span>提示词长度：${(rule.prompt || "").length} 字符</span>
          </div>
        </div>
      `;
    })
    .join("");
}

// ----------------------------------------------------------------------------
// Discover Conversations Modal
// ----------------------------------------------------------------------------

async function openDiscoverModal() {
  const modal = document.getElementById("modal-discover-umos");
  if (!modal) return;
  modal.classList.add("active");
  const searchInput = document.getElementById("discover-search-input");
  if (searchInput) searchInput.value = "";
  await loadDiscoveredUmos();
}

function closeDiscoverModal() {
  const modal = document.getElementById("modal-discover-umos");
  if (modal) modal.classList.remove("active");
}

async function loadDiscoveredUmos() {
  const container = document.getElementById("discover-list-container");
  if (!container) return;

  container.innerHTML = '<div class="loading-box">正在从 AstrBot「数据与日志-对话」及别名库中抓取全部会话...</div>';

  try {
    const res = await apiGet("prompt-injector/discovered-umos");
    if (res && Array.isArray(res.conversations)) {
      state.discoveredUmos = res.conversations;
    } else {
      state.discoveredUmos = [];
    }
    renderDiscoveredTable("");
  } catch (err) {
    console.error("loadDiscoveredUmos failed:", err);
    container.innerHTML = `<div class="loading-box" style="color:var(--danger)">抓取会话数据失败：${escapeHtml(err.message || String(err))}</div>`;
  }
}

function renderDiscoveredTable(filterText) {
  const container = document.getElementById("discover-list-container");
  if (!container) return;

  const kw = (filterText || "").toLowerCase().trim();
  const list = state.discoveredUmos.filter((item) => {
    if (!kw) return true;
    const matchName = (item.chat_name || item.auto_name || item.user_alias || "").toLowerCase().includes(kw);
    const matchUmo = (item.umo || "").toLowerCase().includes(kw);
    const matchGroup = (item.group_id || item.target_id || "").toLowerCase().includes(kw);
    const matchPlatform = (item.platform_name_cn || item.platform || "").toLowerCase().includes(kw);
    return matchName || matchUmo || matchGroup || matchPlatform;
  });

  if (list.length === 0) {
    container.innerHTML = `
      <div class="loading-box" style="padding:30px;">
        ${kw ? "未找到包含关键词的会话" : "未从 AstrBot 历史中检测到任何会话记录。您也可以在主界面点击「添加专属规则」手动输入 UMO。"}
      </div>
    `;
    return;
  }

  const rows = list
    .map((item) => {
      const isGroup = item.chat_type === "group";
      const typeTag = isGroup
        ? `<span class="tag-chat-group">群聊</span>`
        : `<span class="tag-chat-private">私聊</span>`;

      const idDisplay = item.group_id
        ? `<span class="tag-id-pill">群号: ${escapeHtml(item.group_id)}</span>`
        : (item.target_id ? `<span class="tag-platform-pill">用户: ${escapeHtml(item.target_id)}</span>` : "");

      const ruleBtn = item.has_rule
        ? `<button class="btn btn-secondary btn-sm" onclick="selectDiscoveredUmo('${escapeHtml(item.umo)}')">✏️ 修改专属规则</button>`
        : `<button class="btn btn-primary btn-sm" onclick="selectDiscoveredUmo('${escapeHtml(item.umo)}')">➕ 一键配置提示词</button>`;

      const ruleStatus = item.has_rule
        ? `<span style="color:var(--success); font-weight:600; font-size:0.8rem;">已配置（${item.rule_enabled ? "生效中" : "已禁用"}）</span>`
        : `<span style="color:var(--text-muted); font-size:0.8rem;">未配置</span>`;

      return `
        <tr>
          <td>
            <div class="chat-name-cell">
              <div class="chat-name-title">${escapeHtml(item.chat_name || item.display_badge || "未命名")}</div>
              <div class="chat-name-sub">
                ${typeTag}
                <span class="tag-platform-pill">${escapeHtml(item.platform_name_cn || item.platform)}</span>
                ${idDisplay}
              </div>
            </div>
          </td>
          <td>
            <div style="font-family: monospace; font-size: 0.8rem; color: var(--text-muted); word-break: break-all;">
              ${escapeHtml(item.umo)}
            </div>
          </td>
          <td>${ruleStatus}</td>
          <td style="font-size:0.8rem; color:var(--text-muted); white-space:nowrap;">${escapeHtml(item.last_active || "—")}</td>
          <td style="text-align: right; white-space:nowrap;">
            ${ruleBtn}
          </td>
        </tr>
      `;
    })
    .join("");

  container.innerHTML = `
    <table class="discover-table">
      <thead>
        <tr>
          <th>会话名称 / 类型</th>
          <th>统一消息来源 (UMO)</th>
          <th>规则状态</th>
          <th>最近活跃</th>
          <th style="text-align: right;">操作</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
}

function selectDiscoveredUmo(umo) {
  closeDiscoverModal();
  openUmoRuleModal(umo);
}

// ----------------------------------------------------------------------------
// Edit/Add UMO Rule Modal
// ----------------------------------------------------------------------------

function openUmoRuleModal(umo) {
  const modal = document.getElementById("modal-umo-rule");
  if (!modal) return;

  const isEdit = !!umo;
  const titleEl = document.getElementById("modal-umo-rule-title");
  if (titleEl) titleEl.textContent = isEdit ? "编辑会话专属提示词" : "添加会话专属提示词";

  const umoInput = document.getElementById("modal-rule-umo");
  const nameInput = document.getElementById("modal-rule-name");
  const modeSelect = document.getElementById("modal-rule-mode");
  const promptInput = document.getElementById("modal-rule-prompt");
  const enabledInput = document.getElementById("modal-rule-enabled");
  const templateSelect = document.getElementById("modal-rule-template-select");

  if (templateSelect) templateSelect.value = "";

  if (isEdit) {
    const existing = state.umoRules.find((r) => r.umo === umo);
    const discovered = state.discoveredUmos.find((d) => d.umo === umo);

    if (umoInput) {
      umoInput.value = umo;
      umoInput.readOnly = true;
    }
    if (nameInput) {
      nameInput.value = existing?.name || discovered?.chat_name || "";
    }
    if (modeSelect) {
      modeSelect.value = existing?.inject_mode || state.umoConfig?.default_inject_mode || "system_prompt";
    }
    if (promptInput) {
      promptInput.value = existing?.prompt || "";
    }
    if (enabledInput) {
      enabledInput.checked = existing ? !!existing.enabled : true;
    }
  } else {
    if (umoInput) {
      umoInput.value = "";
      umoInput.readOnly = false;
    }
    if (nameInput) nameInput.value = "";
    if (modeSelect) modeSelect.value = state.umoConfig?.default_inject_mode || "system_prompt";
    if (promptInput) promptInput.value = "";
    if (enabledInput) enabledInput.checked = true;
  }

  modal.classList.add("active");
}

function closeUmoRuleModal() {
  const modal = document.getElementById("modal-umo-rule");
  if (modal) modal.classList.remove("active");
}

async function saveUmoRuleModal() {
  const umoInput = document.getElementById("modal-rule-umo");
  const nameInput = document.getElementById("modal-rule-name");
  const modeSelect = document.getElementById("modal-rule-mode");
  const promptInput = document.getElementById("modal-rule-prompt");
  const enabledInput = document.getElementById("modal-rule-enabled");

  const umo = (umoInput?.value || "").trim();
  if (!umo) {
    showToast("请输入或选择有效的 UMO 标识！", "error");
    if (umoInput) umoInput.focus();
    return;
  }

  const prompt = (promptInput?.value || "").trim();
  if (!prompt) {
    showToast("个性化专属提示词内容不能为空！", "error");
    if (promptInput) promptInput.focus();
    return;
  }

  const name = (nameInput?.value || "").trim();
  const inject_mode = modeSelect?.value || "system_prompt";
  const enabled = enabledInput ? enabledInput.checked : true;

  try {
    const res = await apiPost("prompt-injector/rule/save", {
      umo,
      name,
      prompt,
      inject_mode,
      enabled,
    });

    if (res && res.saved) {
      showToast(res.message || "专属提示词保存成功！", "success");
      closeUmoRuleModal();
      await loadUmoConfigAndRules();
    } else {
      showToast("保存失败：" + (res?.message || "未知原因"), "error");
    }
  } catch (err) {
    showToast("保存出错：" + (err.message || String(err)), "error");
  }
}

async function toggleUmoRule(umo, enabled) {
  try {
    const res = await apiPost("prompt-injector/rule/toggle", { umo, enabled });
    if (res && res.enabled !== undefined) {
      showToast(res.message || `已${res.enabled ? "启用" : "禁用"}此会话规则`, "success");
      await loadUmoConfigAndRules();
    } else {
      showToast("切换状态失败", "error");
    }
  } catch (err) {
    showToast("切换出错：" + (err.message || String(err)), "error");
  }
}

async function deleteUmoRule(umo) {
  if (!confirm(`确定要删除 UMO 为「${umo}」的专属提示词规则吗？删除后该会话将不再注入个性化提示词。`)) {
    return;
  }

  try {
    const res = await apiPost("prompt-injector/rule/delete", { umo });
    if (res && res.deleted) {
      showToast("已成功删除该会话规则", "success");
      await loadUmoConfigAndRules();
    } else {
      showToast("删除失败：" + (res?.message || "未找到该规则"), "error");
    }
  } catch (err) {
    showToast("删除出错：" + (err.message || String(err)), "error");
  }
}

async function toggleUmoGlobalEnabled(enabled) {
  try {
    const res = await apiPost("prompt-injector/config/save", { enabled });
    if (res && res.saved) {
      showToast(`专属提示词功能已全局${enabled ? "开启" : "关闭"}！`, "success");
      if (state.umoConfig) state.umoConfig.enabled = enabled;
    } else {
      showToast("保存全局开关失败", "error");
    }
  } catch (err) {
    showToast("保存开关出错：" + (err.message || String(err)), "error");
  }
}

function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(
      () => showToast("UMO 字符串已复制到剪贴板！", "success"),
      () => fallbackCopy(text)
    );
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
    showToast("UMO 已复制到剪贴板！", "success");
  } catch (e) {
    showToast("复制失败，请手动选取复制", "error");
  }
  document.body.removeChild(ta);
}

function bindUmoDomEvents() {
  // Global enabled switch
  const globalToggle = document.getElementById("umo-global-enabled-toggle");
  if (globalToggle) {
    globalToggle.addEventListener("change", (e) => {
      toggleUmoGlobalEnabled(e.target.checked);
    });
  }

  // Buttons
  const btnDiscover = document.getElementById("btn-discover-umos");
  if (btnDiscover) btnDiscover.addEventListener("click", openDiscoverModal);

  const btnAdd = document.getElementById("btn-add-umo-rule");
  if (btnAdd) btnAdd.addEventListener("click", () => openUmoRuleModal(""));

  const btnRefresh = document.getElementById("btn-refresh-umo-rules");
  if (btnRefresh) btnRefresh.addEventListener("click", loadUmoConfigAndRules);

  // Search & Filter
  const searchInput = document.getElementById("umo-search-input");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      state.umoFilter.search = e.target.value;
      renderUmoRules();
    });
  }

  const typeFilter = document.getElementById("umo-chat-type-filter");
  if (typeFilter) {
    typeFilter.addEventListener("change", (e) => {
      state.umoFilter.chatType = e.target.value;
      renderUmoRules();
    });
  }

  const statusFilter = document.getElementById("umo-status-filter");
  if (statusFilter) {
    statusFilter.addEventListener("change", (e) => {
      state.umoFilter.status = e.target.value;
      renderUmoRules();
    });
  }

  // Discover Modal Events
  const discoverClose = document.getElementById("modal-discover-close");
  const discoverCancel = document.getElementById("modal-discover-cancel");
  const btnReDiscover = document.getElementById("btn-re-discover-umos");
  const discoverSearch = document.getElementById("discover-search-input");

  if (discoverClose) discoverClose.addEventListener("click", closeDiscoverModal);
  if (discoverCancel) discoverCancel.addEventListener("click", closeDiscoverModal);
  if (btnReDiscover) btnReDiscover.addEventListener("click", loadDiscoveredUmos);
  if (discoverSearch) {
    discoverSearch.addEventListener("input", (e) => {
      renderDiscoveredTable(e.target.value);
    });
  }

  // Rule Modal Events
  const ruleClose = document.getElementById("modal-umo-rule-close");
  const ruleCancel = document.getElementById("modal-umo-rule-cancel");
  const ruleSave = document.getElementById("modal-umo-rule-save");
  const templateSelect = document.getElementById("modal-rule-template-select");

  if (ruleClose) ruleClose.addEventListener("click", closeUmoRuleModal);
  if (ruleCancel) ruleCancel.addEventListener("click", closeUmoRuleModal);
  if (ruleSave) ruleSave.addEventListener("click", saveUmoRuleModal);

  if (templateSelect) {
    templateSelect.addEventListener("change", (e) => {
      const key = e.target.value;
      if (key && PROMPT_PRESETS[key]) {
        const promptInput = document.getElementById("modal-rule-prompt");
        if (promptInput) {
          promptInput.value = PROMPT_PRESETS[key];
        }
      }
    });
  }
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ============================================================================
// Initialization Entry
// ============================================================================
async function init() {
  setupGlobalWindowHandlers();
  bindDomEvents();

  // Clock tick
  updateClock();
  setInterval(updateClock, 1000);

  // Sync Bridge Theme & wait ready
  const b = await getBridge();
  if (b && typeof b.onContext === "function") {
    b.onContext((ctx) => {
      if (ctx && ctx.theme) {
        document.documentElement.setAttribute("data-theme", ctx.theme);
      }
    });
  }

  // Default load: Live board
  loadTodayLive();
}

// Start on DOMContentLoaded
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
