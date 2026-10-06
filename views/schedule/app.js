/**
 * Personated Companion Dashboard - Schedule Module Controller
 * Communicates with AstrBot Core via window.AstrBotPluginView (Bridge SDK)
 */

// 1. Initialize AstrBot Bridge (with graceful fallback for direct browser inspection)
const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;

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
};

// ============================================================================
// API Helper
// ============================================================================
async function apiGet(endpoint, params = {}) {
  if (bridge && typeof bridge.apiGet === "function") {
    try {
      return await bridge.apiGet(endpoint, params);
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
  if (bridge && typeof bridge.apiPost === "function") {
    try {
      return await bridge.apiPost(endpoint, body);
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
      timelineEl.innerHTML = '<div class="loading-box">无法连接到插件服务</div>';
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

  // Sync Bridge Theme if bridge is present
  if (bridge && typeof bridge.onContext === "function") {
    bridge.onContext((ctx) => {
      if (ctx && ctx.theme) {
        document.documentElement.setAttribute("data-theme", ctx.theme);
      }
    });
  }

  // Wait bridge ready if present
  if (bridge && typeof bridge.ready === "function") {
    try {
      await bridge.ready();
    } catch (e) {
      console.warn("bridge.ready error:", e);
    }
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
