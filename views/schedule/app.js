/**
 * Personated Schedule Management App
 * AstrBot Plugin View JavaScript Controller
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

let currentSegments = [];
let todayScheduleData = null;

// ============================================================================
// API Helper
// ============================================================================
async function apiGet(endpoint, params = {}) {
  if (bridge && typeof bridge.apiGet === "function") {
    return await bridge.apiGet(endpoint, params);
  }
  // Fallback for standalone preview / debugging
  console.warn(`[MockBridge] GET ${endpoint}`, params);
  return null;
}

async function apiPost(endpoint, body = {}) {
  if (bridge && typeof bridge.apiPost === "function") {
    return await bridge.apiPost(endpoint, body);
  }
  // Fallback for standalone preview / debugging
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

  setTimeout(() => {
    toast.className = "toast";
  }, 3500);
}

function updateClock() {
  const now = new Date();
  const timeEl = document.getElementById("clock-time");
  const dateEl = document.getElementById("clock-date");

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
    dateEl.textContent = `${year}年${month}月${date}日 星期${weekdays[now.getDay()]}`;
  }
}

// ============================================================================
// Tab Navigation
// ============================================================================
function initTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTabId = btn.getAttribute("data-tab");
      tabBtns.forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

      btn.classList.add("active");
      const targetContent = document.getElementById(targetTabId);
      if (targetContent) targetContent.classList.add("active");
    });
  });
}

// ============================================================================
// Load & Render Data: Today's Schedule
// ============================================================================
async function loadTodaySchedule() {
  try {
    const res = await apiGet("schedule/today");
    if (!res) return;

    todayScheduleData = res;
    renderTodayView(res);
  } catch (err) {
    console.error("Failed to load today schedule:", err);
    showToast(`获取今日日程失败: ${err.message || err}`, "error");
  }
}

function renderTodayView(data) {
  const activeSegment = data.active_segment;
  const activeDescEl = document.getElementById("current-active-desc");
  const nowBadge = document.getElementById("now-segment-badge");
  const nowActivity = document.getElementById("now-activity");
  const nowState = document.getElementById("now-state");

  const infoProvider = document.getElementById("info-provider");
  const infoGenTime = document.getElementById("info-gentime");

  if (infoProvider) infoProvider.textContent = data.schedule_provider_id || "(默认对话模型)";
  if (infoGenTime) infoGenTime.textContent = data.daily_generate_time || "04:00";

  if (activeSegment) {
    if (activeDescEl) {
      activeDescEl.innerHTML = `🟢 <strong>当前生效时段：</strong>【${escapeHtml(activeSegment.name)}】 (${activeSegment.start} ~ ${activeSegment.end})`;
    }
    if (nowBadge) nowBadge.textContent = `${activeSegment.name} (${activeSegment.start}~${activeSegment.end})`;
    if (nowActivity) nowActivity.textContent = activeSegment.activity || "正在进行日常事务";
    if (nowState) nowState.textContent = activeSegment.state || "精神平和自然";
  } else {
    if (activeDescEl) {
      activeDescEl.textContent = `⚪ 当前时间未落在任何已定义的日程时间段内`;
    }
    if (nowBadge) nowBadge.textContent = "无匹配时段";
    if (nowActivity) nowActivity.textContent = "自由活动 / 未在计划时段";
    if (nowState) nowState.textContent = "自然状态";
  }

  // Render Timeline
  const container = document.getElementById("timeline-container");
  if (!container) return;

  const schedule = data.today_schedule;
  if (!schedule || !schedule.items || schedule.items.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        今日尚未生成日程或无安排条目。<br/>
        您可以点击上方 <strong>“重新生成今日日程”</strong> 立即生成。
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  schedule.items.forEach((item, index) => {
    const isActive = activeSegment && activeSegment.id === item.id;
    const card = document.createElement("div");
    card.className = `timeline-card ${isActive ? "is-active" : ""}`;

    const isCrossMidnight = isCrossMidnightTime(item.start, item.end);

    card.innerHTML = `
      <div class="timeline-header">
        <div class="timeline-title-wrap">
          <span class="timeline-name">${index + 1}. 【${escapeHtml(item.name)}】</span>
          <span class="timeline-time-pill">${item.start} ~ ${item.end}</span>
          ${isCrossMidnight ? '<span class="tag-cross-midnight">🌙 跨夜</span>' : ""}
          ${isActive ? '<span class="badge active-badge">进行中</span>' : ""}
        </div>
      </div>
      <div class="timeline-body">
        <div class="timeline-activity">
          <strong>活动内容：</strong>${escapeHtml(item.activity)}
        </div>
        <div class="timeline-state">
          <strong>心理状态：</strong>${escapeHtml(item.state)}
        </div>
      </div>
      <div class="timeline-footer">
        <button class="btn btn-secondary btn-sm btn-edit-item" data-id="${escapeHtml(item.id)}">✏️ 编辑该时段</button>
      </div>
    `;

    // Hook edit button
    const editBtn = card.querySelector(".btn-edit-item");
    if (editBtn) {
      editBtn.addEventListener("click", () => openEditModal(item));
    }

    container.appendChild(card);
  });
}

function isCrossMidnightTime(start, end) {
  if (!start || !end) return false;
  const [sH, sM] = start.split(":").map(Number);
  const [eH, eM] = end.split(":").map(Number);
  const startM = sH * 60 + sM;
  const endM = eH * 60 + eM;
  return startM > endM;
}

// ============================================================================
// Load & Render Config (Settings Tab)
// ============================================================================
async function loadConfig() {
  try {
    const config = await apiGet("schedule/config");
    if (!config) return;

    // 1. Daily generation time
    const genTimeInput = document.getElementById("input-gen-time");
    if (genTimeInput && config.daily_generate_time) {
      genTimeInput.value = config.daily_generate_time;
    }

    // 2. Providers dropdown
    const provSelect = document.getElementById("select-provider");
    if (provSelect) {
      provSelect.innerHTML = '<option value="">(留空自动回退对话模型)</option>';
      if (Array.isArray(config.available_providers)) {
        config.available_providers.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.id;
          opt.textContent = p.name || p.id;
          if (p.id === config.schedule_provider_id) {
            opt.selected = true;
          }
          provSelect.appendChild(opt);
        });
      }
      if (config.schedule_provider_id && !provSelect.value) {
        const customOpt = document.createElement("option");
        customOpt.value = config.schedule_provider_id;
        customOpt.textContent = `${config.schedule_provider_id} (已保存)`;
        customOpt.selected = true;
        provSelect.appendChild(customOpt);
      }
    }

    // 3. Inject enabled & mode
    const injectEnabled = document.getElementById("checkbox-inject-enabled");
    if (injectEnabled) {
      injectEnabled.checked = Boolean(config.inject_context_enabled);
    }

    const injectMode = document.getElementById("select-inject-mode");
    if (injectMode && config.inject_mode) {
      injectMode.value = config.inject_mode;
    }

    // 4. Segments table
    currentSegments = Array.isArray(config.schedule_segments) ? config.schedule_segments : DEFAULT_SEGMENTS_PRESET;
    renderSegmentsTable();

  } catch (err) {
    console.error("Failed to load config:", err);
    showToast(`获取设置失败: ${err.message || err}`, "error");
  }
}

function renderSegmentsTable() {
  const tbody = document.getElementById("segments-table-body");
  if (!tbody) return;

  tbody.innerHTML = "";

  currentSegments.forEach((seg, index) => {
    const tr = document.createElement("tr");

    const isCross = isCrossMidnightTime(seg.start, seg.end);

    tr.innerHTML = `
      <td><strong>${index + 1}</strong></td>
      <td>
        <input type="text" class="table-input seg-id" value="${escapeHtml(seg.id)}" placeholder="时段ID" />
      </td>
      <td>
        <input type="text" class="table-input seg-name" value="${escapeHtml(seg.name)}" placeholder="时段名称" />
      </td>
      <td>
        <input type="time" class="table-input seg-start" value="${seg.start}" />
      </td>
      <td>
        <input type="time" class="table-input seg-end" value="${seg.end}" />
      </td>
      <td>
        ${isCross ? '<span class="tag-cross-midnight">🌙 跨夜</span>' : '<span style="color:var(--text-muted);font-size:0.8rem">白天</span>'}
      </td>
      <td>
        <div style="display:flex;gap:4px;">
          <button class="btn btn-secondary btn-sm btn-move-up" title="上移">⬆️</button>
          <button class="btn btn-secondary btn-sm btn-move-down" title="下移">⬇️</button>
          <button class="btn-danger-text btn-delete-seg" title="删除">🗑️</button>
        </div>
      </td>
    `;

    // Hook inputs to update currentSegments array in-place
    tr.querySelector(".seg-id").addEventListener("input", (e) => {
      seg.id = e.target.value.trim();
    });
    tr.querySelector(".seg-name").addEventListener("input", (e) => {
      seg.name = e.target.value.trim();
    });
    tr.querySelector(".seg-start").addEventListener("change", (e) => {
      seg.start = e.target.value;
      renderSegmentsTable();
    });
    tr.querySelector(".seg-end").addEventListener("change", (e) => {
      seg.end = e.target.value;
      renderSegmentsTable();
    });

    // Move Up
    tr.querySelector(".btn-move-up").addEventListener("click", () => {
      if (index > 0) {
        const tmp = currentSegments[index - 1];
        currentSegments[index - 1] = currentSegments[index];
        currentSegments[index] = tmp;
        renderSegmentsTable();
      }
    });

    // Move Down
    tr.querySelector(".btn-move-down").addEventListener("click", () => {
      if (index < currentSegments.length - 1) {
        const tmp = currentSegments[index + 1];
        currentSegments[index + 1] = currentSegments[index];
        currentSegments[index] = tmp;
        renderSegmentsTable();
      }
    });

    // Delete
    tr.querySelector(".btn-delete-seg").addEventListener("click", () => {
      if (currentSegments.length <= 1) {
        showToast("至少需保留一个时间段", "error");
        return;
      }
      currentSegments.splice(index, 1);
      renderSegmentsTable();
    });

    tbody.appendChild(tr);
  });
}

// ============================================================================
// Save Configuration
// ============================================================================
async function saveAllConfig() {
  const saveBtn = document.getElementById("btn-save-settings");
  const saveMsg = document.getElementById("save-status-msg");

  const genTime = document.getElementById("input-gen-time")?.value || "04:00";
  const providerId = document.getElementById("select-provider")?.value || "";
  const injectEnabled = document.getElementById("checkbox-inject-enabled")?.checked ?? true;
  const injectMode = document.getElementById("select-inject-mode")?.value || "extra_user_content";

  // Validate time format
  const timeRegex = /^([01]?\d|2[0-3]):[0-5]\d$/;
  if (!timeRegex.test(genTime)) {
    showToast("每日生成时间必须为 HH:MM 格式 (00:00 - 23:59)", "error");
    return;
  }

  // Validate and collect segments
  const validSegments = [];
  for (let i = 0; i < currentSegments.length; i++) {
    const s = currentSegments[i];
    if (!s.name) {
      showToast(`第 ${i + 1} 个时间段名称不能为空`, "error");
      return;
    }
    if (!timeRegex.test(s.start) || !timeRegex.test(s.end)) {
      showToast(`时间段【${s.name}】的起止时间格式无效，请输入有效时间`, "error");
      return;
    }
    validSegments.push({
      id: s.id || `seg_${i + 1}`,
      name: s.name,
      start: s.start,
      end: s.end,
    });
  }

  const payload = {
    daily_generate_time: genTime,
    schedule_provider_id: providerId,
    inject_context_enabled: injectEnabled,
    inject_mode: injectMode,
    schedule_segments: validSegments,
  };

  try {
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = "保存中...";
    }

    const res = await apiPost("schedule/config/save", payload);
    showToast("配置保存成功！", "success");
    if (saveMsg) {
      saveMsg.textContent = "✅ 配置已成功保存并立即生效";
      setTimeout(() => { saveMsg.textContent = ""; }, 4000);
    }

    // Refresh today's status
    await loadTodaySchedule();
  } catch (err) {
    console.error("Save config error:", err);
    showToast(`保存失败: ${err.message || err}`, "error");
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "💾 保存所有配置";
    }
  }
}

// ============================================================================
// Modal & Actions: Regenerate & Edit Single Item
// ============================================================================
async function triggerRegenerate() {
  const btn = document.getElementById("btn-regenerate");
  if (!confirm("确定要立即重新生成今日的日程安排吗？这将覆盖今日现有的作息记录。")) {
    return;
  }

  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "⏳ 正在生成今日日程...";
    }

    const res = await apiPost("schedule/generate", {});
    showToast("今日日程已成功重新生成！", "success");
    await loadTodaySchedule();
  } catch (err) {
    console.error("Regenerate error:", err);
    showToast(`重新生成失败: ${err.message || err}`, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "✨ 重新生成今日日程";
    }
  }
}

function openEditModal(item) {
  const modal = document.getElementById("edit-modal");
  if (!modal) return;

  document.getElementById("edit-item-id").value = item.id;
  document.getElementById("edit-item-meta").textContent = `【${item.name}】(${item.start} ~ ${item.end})`;
  document.getElementById("edit-item-activity").value = item.activity || "";
  document.getElementById("edit-item-state").value = item.state || "";

  modal.classList.add("show");
}

function closeEditModal() {
  const modal = document.getElementById("edit-modal");
  if (modal) modal.classList.remove("show");
}

async function saveEditItem() {
  const id = document.getElementById("edit-item-id").value;
  const activity = document.getElementById("edit-item-activity").value.trim();
  const state = document.getElementById("edit-item-state").value.trim();

  if (!activity) {
    showToast("活动内容不能为空", "error");
    return;
  }

  try {
    await apiPost("schedule/item/update", { id, activity, state });
    showToast("时段安排修改成功！", "success");
    closeEditModal();
    await loadTodaySchedule();
  } catch (err) {
    console.error("Update item error:", err);
    showToast(`修改失败: ${err.message || err}`, "error");
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ============================================================================
// Main Bootstrap
// ============================================================================
async function initApp() {
  // Start clock
  updateClock();
  setInterval(updateClock, 1000);

  // Tab events
  initTabs();

  // Wait for Bridge if present
  if (bridge && typeof bridge.ready === "function") {
    try {
      const ctx = await bridge.ready();
      console.log("[ScheduleView] Bridge ready context:", ctx);

      if (ctx && ctx.isDark !== undefined) {
        document.documentElement.setAttribute("data-theme", ctx.isDark ? "dark" : "light");
      }

      if (typeof bridge.onContext === "function") {
        bridge.onContext((newCtx) => {
          if (newCtx && newCtx.isDark !== undefined) {
            document.documentElement.setAttribute("data-theme", newCtx.isDark ? "dark" : "light");
          }
        });
      }
    } catch (e) {
      console.warn("Bridge ready failed:", e);
    }
  }

  // Hook global buttons
  document.getElementById("btn-refresh-view")?.addEventListener("click", () => {
    loadTodaySchedule();
    showToast("已刷新今日数据", "info");
  });

  document.getElementById("btn-regenerate")?.addEventListener("click", triggerRegenerate);
  document.getElementById("btn-save-settings")?.addEventListener("click", saveAllConfig);

  // Add segment
  document.getElementById("btn-add-segment")?.addEventListener("click", () => {
    const newIdx = currentSegments.length + 1;
    currentSegments.push({
      id: `seg_custom_${Date.now().toString().slice(-4)}`,
      name: `新时段 ${newIdx}`,
      start: "12:00",
      end: "13:00",
    });
    renderSegmentsTable();
  });

  // Reset preset
  document.getElementById("btn-reset-segments")?.addEventListener("click", () => {
    if (confirm("确定要恢复默认的 6 段标准作息预设吗？")) {
      currentSegments = JSON.parse(JSON.stringify(DEFAULT_SEGMENTS_PRESET));
      renderSegmentsTable();
    }
  });

  // Modal events
  document.getElementById("modal-close")?.addEventListener("click", closeEditModal);
  document.getElementById("modal-cancel")?.addEventListener("click", closeEditModal);
  document.getElementById("modal-save")?.addEventListener("click", saveEditItem);

  // Load initial data
  await loadTodaySchedule();
  await loadConfig();
}

window.addEventListener("DOMContentLoaded", initApp);
