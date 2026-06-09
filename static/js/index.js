// ───── Tab switching ─────
const THEME_STORAGE_KEY = 'iptv-theme';
let latestHistoryRuns = [];
let initialHistoryRuns = [];
let currentRunLogEntries = [];
let currentRunLogText = '';
let currentRunLogRunId = '';

function getCurrentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

function getThemePalette() {
  const styles = getComputedStyle(document.documentElement);
  return {
    chartText: styles.getPropertyValue('--chart-text').trim() || '#374151',
    chartMuted: styles.getPropertyValue('--chart-muted').trim() || '#9ca3af',
    chartGrid: styles.getPropertyValue('--chart-grid').trim() || '#f3f4f6',
    chartGridStrong: styles.getPropertyValue('--chart-grid-strong').trim() || '#e5e7eb'
  };
}

function updateThemeToggle(theme) {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;

  const icon = document.getElementById('themeToggleIcon');
  const text = document.getElementById('themeToggleText');
  const isDark = theme === 'dark';

  btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
  btn.title = isDark ? '切换到浅色模式' : '切换到深色模式';
  if (icon) icon.textContent = isDark ? '☀' : '☾';
  if (text) text.textContent = isDark ? '浅色模式' : '深色模式';
}

function rerenderThemeSensitiveViews() {
  const runs = latestHistoryRuns.length ? latestHistoryRuns : initialHistoryRuns;
  if (runs.length) {
    renderOverview(runs);
  }
}

function setTheme(theme) {
  const nextTheme = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', nextTheme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
  } catch (e) {}
  updateThemeToggle(nextTheme);
  rerenderThemeSensitiveViews();
  if (typeof applyScanGridTheme === 'function') {
    applyScanGridTheme();
  }
  window.dispatchEvent(new CustomEvent('iptv-theme-change', {detail: {theme: nextTheme}}));
}

function toggleTheme() {
  setTheme(getCurrentTheme() === 'dark' ? 'light' : 'dark');
}

function ensureThemeToggle() {
  const header = document.querySelector('.header');
  const meta = document.getElementById('headerMeta');
  if (!header || !meta) return;

  let actions = header.querySelector('.header-actions');
  if (!actions) {
    actions = document.createElement('div');
    actions.className = 'header-actions';
    header.appendChild(actions);
  }

  let btn = document.getElementById('themeToggle');
  if (!btn) {
    btn = document.createElement('button');
    btn.id = 'themeToggle';
    btn.type = 'button';
    btn.className = 'theme-toggle';
    btn.setAttribute('aria-label', 'Toggle theme');
    btn.innerHTML =
      '<span class="theme-toggle-icon" id="themeToggleIcon">☾</span>' +
      '<span class="theme-toggle-text" id="themeToggleText">深色模式</span>';
  }

  if (!actions.contains(btn)) {
    actions.insertBefore(btn, actions.firstChild);
  }
  if (!actions.contains(meta)) {
    actions.appendChild(meta);
  }
  if (!btn.dataset.bound) {
    btn.addEventListener('click', toggleTheme);
    btn.dataset.bound = '1';
  }

  updateThemeToggle(getCurrentTheme());
}

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.add('active');
    if (tab.dataset.tab === 'scanner' && typeof loadScanConfig === 'function') {
      loadScanConfig();
    }
    if (tab.dataset.tab === 'scan-config' && typeof loadScanConfig === 'function') {
      loadScanConfig();
      if (typeof loadKeyList === 'function') loadKeyList();
    }
    if (tab.dataset.tab === 'scan-results' && typeof loadScanResults === 'function') {
      loadScanResults();
    }
  });
});

function loadInitialRunsData() {
  const el = document.getElementById('initialRunsData');
  if (!el) return [];
  try {
    const runs = JSON.parse(el.textContent || '[]');
    return Array.isArray(runs) ? runs : [];
  } catch (e) {
    return [];
  }
}

// ───── Channel search + filter ─────
const channelSearch = document.getElementById('channelSearch');
const channelFilter = document.getElementById('channelFilter');
function filterChannels() {
  const q = (channelSearch ? channelSearch.value : '').toLowerCase();
  const f = channelFilter ? channelFilter.value : 'all';
  document.querySelectorAll('.ch-card').forEach(card => {
    const ch = card.dataset.channel || '';
    const passed = parseInt(card.dataset.passed || '0');
    let show = true;
    if (q && !ch.toLowerCase().includes(q)) show = false;
    if (f === 'pass' && passed === 0) show = false;
    if (f === 'fail' && passed > 0) show = false;
    card.style.display = show ? '' : 'none';
  });
}
if (channelSearch) channelSearch.addEventListener('input', filterChannels);
if (channelFilter) channelFilter.addEventListener('change', filterChannels);

function toggleChannel(header) {
  const body = header.nextElementSibling;
  const arrow = header.querySelector('.arrow');
  body.classList.toggle('open');
  arrow.classList.toggle('open');
}

// ───── Toast notification ─────
function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type;
  setTimeout(() => t.classList.add('show'), 10);
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ───── Config management ─────
const CONFIG_FIELDS = [
  'min_width', 'min_height', 'min_bandwidth_MBps', 'bandwidth_compensation_MBps',
  'h265_bandwidth_ratio', 'test_duration', 'max_workers', 'max_ffmpeg_workers', 'max_urls_per_channel',
  'system_bandwidth_limit_MBps', 'system_memory_limit_percent', 'run_mode', 'run_times', 'run_interval_minutes',
  'show_update_time', 'update_time_position'
];

function loadConfig() {
  fetch('/api/config')
    .then(r => r.json())
    .then(cfg => applyConfigToForm(cfg))
    .catch(e => showToast('加载配置失败: ' + e, 'error'));
}

function saveConfig() {
  const data = {};
  CONFIG_FIELDS.forEach(key => {
    const el = document.getElementById('cfg_' + key);
    if (!el) return;
    let val = el.value;
    if (key === 'run_times') {
      data[key] = val;  // 原始字符串，后端会规范化
    } else if (key === 'show_update_time') {
      data[key] = val === 'true';
    } else if (['min_width', 'min_height', 'test_duration', 'max_workers', 'max_ffmpeg_workers', 'max_urls_per_channel', 'run_interval_minutes', 'system_memory_limit_percent'].includes(key)) {
      data[key] = parseInt(val) || 0;
    } else if (['min_bandwidth_MBps', 'bandwidth_compensation_MBps', 'h265_bandwidth_ratio', 'system_bandwidth_limit_MBps'].includes(key)) {
      data[key] = parseFloat(val) || 0;
    } else {
      data[key] = val;
    }
  });

  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  })
  .then(r => r.json())
  .then(res => {
    if (res.ok) {
      showToast('配置已保存', 'success');
      // 用后端返回的规范化配置更新表单
      if (res.config) {
        applyConfigToForm(res.config);
      }
    } else {
      showToast('保存失败: ' + (res.error || ''), 'error');
    }
  })
  .catch(e => showToast('保存失败: ' + e, 'error'));
}

function applyConfigToForm(cfg) {
  CONFIG_FIELDS.forEach(key => {
    const el = document.getElementById('cfg_' + key);
    if (!el) return;
    const val = cfg[key];
    if (key === 'run_times' && Array.isArray(val)) {
      el.value = val.join(', ');
      // 显示规范化提示
      const hint = document.getElementById('cfg_run_times_hint');
      if (hint) {
        if (val.length > 0) {
          hint.textContent = '已规范化为：' + val.join(', ');
        } else {
          hint.textContent = '';
        }
      }
    } else if (key === 'show_update_time') {
      el.value = val ? 'true' : 'false';
    } else {
      el.value = val !== undefined ? val : '';
    }
  });
}

function normalizeRunTimesInput() {
  const el = document.getElementById('cfg_run_times');
  const hint = document.getElementById('cfg_run_times_hint');
  if (!el || !hint) return;
  const raw = el.value.trim();
  if (!raw) { hint.textContent = ''; return; }
  // 解析各种格式：逗号、分号、空格、中文逗号分隔
  const parts = raw.replace(/;/g, ',').replace(/，/g, ',').split(/[\s,]+/).filter(Boolean);
  const valid = [];
  for (const t of parts) {
    const m = t.match(/^(\d{1,2}):(\d{1,2})$/);
    if (m) {
      const h = parseInt(m[1]), mi = parseInt(m[2]);
      if (h >= 0 && h <= 23 && mi >= 0 && mi <= 59) {
        valid.push(String(h).padStart(2, '0') + ':' + String(mi).padStart(2, '0'));
      }
    }
    // 纯数字视为小时（如 "6" -> "06:00"）
    const m2 = t.match(/^(\d{1,2})$/);
    if (m2) {
      const h = parseInt(m2[1]);
      if (h >= 0 && h <= 23) {
        valid.push(String(h).padStart(2, '0') + ':00');
      }
    }
  }
  const unique = [...new Set(valid)].sort();
  if (unique.length > 0) {
    el.value = unique.join(', ');
    hint.textContent = '已规范化为：' + unique.join(', ');
  } else if (raw) {
    hint.textContent = '未识别到有效时间，请使用 HH:MM 格式';
    hint.style.color = '#dc2626';
    setTimeout(() => { hint.style.color = '#2563eb'; }, 2000);
  }
}

// ───── Text file editor ─────
let currentFile = 'subscribe';
document.querySelectorAll('.file-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.file-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentFile = tab.dataset.file;
    document.getElementById('btnResetDemo').style.display = currentFile === 'demo' ? '' : 'none';
    loadTextFile();
  });
});

function loadTextFile() {
  document.getElementById('fileStatus').textContent = '加载中...';
  fetch('/api/text/' + currentFile)
    .then(r => r.json())
    .then(data => {
      document.getElementById('fileEditor').value = data.content || '';
      document.getElementById('fileStatus').textContent = '';
    })
    .catch(e => {
      document.getElementById('fileStatus').textContent = '加载失败';
      showToast('加载文件失败: ' + e, 'error');
    });
}

function saveTextFile() {
  const content = document.getElementById('fileEditor').value;
  document.getElementById('fileStatus').textContent = '保存中...';
  fetch('/api/text/' + currentFile, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content: content})
  })
  .then(r => r.json())
  .then(res => {
    if (res.ok) {
      document.getElementById('fileStatus').textContent = '已保存';
      showToast(currentFile + ' 已保存', 'success');
    } else {
      document.getElementById('fileStatus').textContent = '保存失败';
      showToast('保存失败: ' + (res.error || ''), 'error');
    }
  })
  .catch(e => {
    document.getElementById('fileStatus').textContent = '保存失败';
    showToast('保存失败: ' + e, 'error');
  });
}

function resetDemo() {
  if (!confirm('确定恢复为默认频道模板？当前修改将丢失。')) return;
  fetch('/api/reset-demo', {method: 'POST'})
    .then(r => r.json())
    .then(res => {
      if (res.ok) {
        showToast('已恢复默认模板', 'success');
        loadTextFile();
      } else {
        showToast('恢复失败', 'error');
      }
    })
    .catch(e => showToast('恢复失败: ' + e, 'error'));
}

// ───── Global progress polling (header + testing tab) ─────
let globalPollTimer = null;
let isWebRun = false;
let testStarted = false;
let lastLogSeq = 0;
let autoScroll = true;

function appendProgressLogs(data) {
  if (data.source !== 'web' || !data.lines || data.lines.length === 0) return;

  isWebRun = true;
  const panel = document.getElementById('logPanel');
  if (!panel) return;

  data.lines.forEach(line => {
    const div = document.createElement('div');
    div.className = 'log-line';
    let cls = 'log-info';
    if (line.msg.includes('通过') || line.msg.includes('pass')) cls = 'log-pass';
    else if (line.msg.includes('拒绝') || line.msg.includes('失败')) cls = 'log-fail';
    div.innerHTML = '<span class="log-time">[' + line.time + ']</span><span class="' + cls + '">' + escapeHtml(line.msg) + '</span>';
    panel.appendChild(div);
    lastLogSeq = line.seq;
  });

  if (autoScroll) panel.scrollTop = panel.scrollHeight;
}

function renderProgressNumbers(data) {
  const total = Number(data.total) || 0;
  const processed = Number(data.processed) || 0;
  const pct = total > 0 ? Math.max(0, Math.min(100, Math.round(processed / total * 100))) : 0;
  const fill = document.getElementById('progressFill');
  const pctEl = document.getElementById('progressPercent');
  const labelEl = document.getElementById('progressLabel');
  const procEl = document.getElementById('progProcessed');
  const passEl = document.getElementById('progPassed');
  const failEl = document.getElementById('progFailed');
  const timeEl = document.getElementById('progElapsed');

  if (fill) fill.style.width = pct + '%';
  if (pctEl) pctEl.textContent = pct + '%';
  if (labelEl) labelEl.textContent = total > 0 ? ('进度 ' + processed + ' / ' + total) : '准备中...';
  if (procEl) procEl.textContent = processed;
  if (passEl) passEl.textContent = data.passed || 0;
  if (failEl) failEl.textContent = data.failed || 0;
  if (timeEl) timeEl.textContent = Math.round(data.elapsed || 0);
}

function updateHeaderStatus(data) {
  const statusWrap = document.getElementById('headerRunStatus');
  const lastUpdateWrap = document.getElementById('headerLastUpdate');
  const statusText = document.getElementById('headerRunText');
  const schedWrap = document.getElementById('headerSchedulerStatus');
  const schedText = document.getElementById('headerSchedulerText');
  if (!statusWrap) return;

  if (data.running) {
    statusWrap.style.display = '';
    if (lastUpdateWrap) lastUpdateWrap.style.display = 'none';
    const pct = data.total > 0 ? Math.round(data.processed / data.total * 100) : 0;
    statusText.textContent = '测试运行中... ' + data.processed + '/' + (data.total || '?') +
      ' 已测 | 通过 ' + data.passed + ' | ' + Math.round(data.elapsed || 0) + 's';
  } else {
    statusWrap.style.display = 'none';
    if (lastUpdateWrap) lastUpdateWrap.style.display = '';
  }

  // 调度器状态
  if (schedWrap && schedText) {
    if (data.scheduler_running && data.next_scheduled_run) {
      schedWrap.style.display = '';
      schedText.textContent = '下次执行：' + data.next_scheduled_run;
    } else {
      schedWrap.style.display = 'none';
    }
  }
}

function updateTestingTab(data) {
  const progressWrap = document.getElementById('progressWrap');
  const testStatusText = document.getElementById('testStatusText');
  const btn = document.getElementById('btnTrigger');
  const stopBtn = document.getElementById('btnStop');
  if (!progressWrap) return;

  if (data.running) {
    testStarted = true;
    progressWrap.style.display = '';
    if (testStatusText) testStatusText.textContent = '运行中...';
    if (btn) { btn.disabled = true; btn.textContent = '运行中...'; }
    if (stopBtn) stopBtn.style.display = '';

    renderProgressNumbers(data);
    appendProgressLogs(data);

  } else if (testStarted) {
    renderProgressNumbers(data);
    appendProgressLogs(data);
    if (testStatusText) testStatusText.textContent = '已完成';
    const labelEl = document.getElementById('progressLabel');
    if (labelEl) labelEl.textContent = '测试完成';
    resetTestBtn();
  }
}

function pollGlobalProgress() {
  fetch('/api/progress?after=' + lastLogSeq)
    .then(r => r.json())
    .then(data => {
      updateHeaderStatus(data);
      updateTestingTab(data);

      if (data.running) {
        // 测试进行中，确保轮询在运行
        if (!globalPollTimer) {
          globalPollTimer = setInterval(pollGlobalProgress, 2000);
        }
      } else {
        // 没有运行中的测试
        if (globalPollTimer) { clearInterval(globalPollTimer); globalPollTimer = null; }

        // 调度器运行中，低频轮询更新下次执行时间
        if (data.scheduler_running) {
          globalPollTimer = setInterval(pollGlobalProgress, 30000);
        }

        if (isWebRun) {
          if (data.error) showToast('测试异常: ' + data.error, 'error');
          else showToast('测试已完成', 'success');
          isWebRun = false;
          testStarted = false;
        }
      }
    })
    .catch(() => {
      if (!globalPollTimer) {
        globalPollTimer = setInterval(pollGlobalProgress, 5000);
      }
    });
}

// ───── Trigger test ─────
function triggerTest() {
  const btn = document.getElementById('btnTrigger');
  btn.disabled = true;
  btn.textContent = '启动中...';
  document.getElementById('testStatusText').textContent = '正在启动...';

  fetch('/api/trigger', {method: 'POST'})
    .then(r => r.json())
    .then(res => {
      if (res.ok) {
        showToast('测试已启动', 'success');
        const panel = document.getElementById('logPanel');
        if (panel) panel.innerHTML = '';
        lastLogSeq = 0;
        isWebRun = true;
        document.getElementById('progressWrap').style.display = '';
        document.getElementById('testStatusText').textContent = '运行中...';
        btn.textContent = '运行中...';
        const stopBtn = document.getElementById('btnStop');
        if (stopBtn) stopBtn.style.display = '';
        // 启动全局轮询（清除可能残留的定时器）
        if (globalPollTimer) clearInterval(globalPollTimer);
        lastLogSeq = 0;
        isWebRun = true;
        testStarted = true;
        globalPollTimer = setInterval(pollGlobalProgress, 2000);
      } else {
        showToast(res.error || '启动失败', 'error');
        resetTestBtn();
      }
    })
    .catch(e => {
      showToast('启动失败: ' + e, 'error');
      resetTestBtn();
    });
}

function resetTestBtn() {
  const btn = document.getElementById('btnTrigger');
  const stopBtn = document.getElementById('btnStop');
  btn.disabled = false;
  btn.textContent = '立即测试';
  if (stopBtn) {
    stopBtn.disabled = false;
    stopBtn.style.display = 'none';
    stopBtn.textContent = '终止测试';
  }
}

function stopTest() {
  const stopBtn = document.getElementById('btnStop');
  if (stopBtn) {
    stopBtn.disabled = true;
    stopBtn.textContent = '终止中...';
  }
  fetch('/api/stop', {method: 'POST'})
    .then(r => r.json())
    .then(res => {
      if (res.ok) {
        showToast(res.message || '已请求终止', 'success');
        isWebRun = false;
        testStarted = false;
        resetTestBtn();
        if (globalPollTimer) { clearInterval(globalPollTimer); globalPollTimer = null; }
      } else {
        showToast(res.error || '终止失败', 'error');
        resetTestBtn();
      }
    })
    .catch(e => {
      showToast('终止失败: ' + e, 'error');
      resetTestBtn();
    });
}

function toggleAutoScroll() {
  autoScroll = !autoScroll;
  const btn = document.getElementById('btnAutoScroll');
  btn.className = 'btn-scroll' + (autoScroll ? ' active' : '');
}

function clearLog() {
  document.getElementById('logPanel').innerHTML = '';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ───── Check if test is running on page load ─────
(function() {
  // 初始化自动滚动按钮样式
  const scrollBtn = document.getElementById('btnAutoScroll');
  if (scrollBtn) scrollBtn.classList.add('active');

  // 立即检查一次运行状态
  pollGlobalProgress();
  // 启动全局轮询（2 秒间隔）
  globalPollTimer = setInterval(pollGlobalProgress, 2000);
})();

// ───── History: date range query + expandable rows ─────
(function() {
  // 默认最近 7 天
  const now = new Date();
  const weekAgo = new Date(now - 7 * 86400000);
  const fmt = d => d.toISOString().split('T')[0];
  const startEl = document.getElementById('historyStartDate');
  const endEl = document.getElementById('historyEndDate');
  if (startEl) startEl.value = fmt(weekAgo);
  if (endEl) endEl.value = fmt(now);
})();

function queryHistory() {
  const start = document.getElementById('historyStartDate').value;
  const end = document.getElementById('historyEndDate').value;
  const params = new URLSearchParams();
  if (start) params.set('start', start);
  if (end) params.set('end', end);

  fetch('/api/runs?' + params.toString())
    .then(r => r.json())
    .then(runs => {
      renderHistoryTable(runs);
      renderOverview(runs);
    })
    .catch(e => showToast('查询失败: ' + e, 'error'));
}

function resetHistoryDate() {
  const now = new Date();
  const weekAgo = new Date(now - 7 * 86400000);
  const fmt = d => d.toISOString().split('T')[0];
  document.getElementById('historyStartDate').value = fmt(weekAgo);
  document.getElementById('historyEndDate').value = fmt(now);
  queryHistory();
}

function resetHistoryAll() {
  document.getElementById('historyStartDate').value = '';
  document.getElementById('historyEndDate').value = '';
  queryHistory();
}

function renderHistoryTable(runs) {
  latestHistoryRuns = Array.isArray(runs) ? runs : [];
  const tbody = document.getElementById('historyBody');
  const noData = document.getElementById('historyNoData');
  tbody.innerHTML = '';
  if (!runs || runs.length === 0) {
    noData.style.display = '';
    return;
  }
  noData.style.display = 'none';
  runs.forEach(run => {
    const s = run.summary;
    const rateColor = s.pass_rate >= 50 ? '#22c55e' : '#ef4444';
    const mins = Math.round(run.duration_seconds / 60);
    // Main row
    const tr = document.createElement('tr');
    tr.className = 'history-row';
    tr.dataset.runid = run.run_id;
    tr.onclick = function() { toggleHistoryDetail(this, run.run_id); };
    tr.innerHTML =
      '<td>' + run.finished_at + '</td>' +
      '<td>' + s.total_tested + '</td>' +
      '<td style="color:#16a34a;font-weight:600">' + s.total_passed + '</td>' +
      '<td style="color:#dc2626">' + s.total_failed + '</td>' +
      '<td><div class="history-rate"><span>' + s.pass_rate + '%</span><div class="mini-bar"><div class="mini-fill" style="width:' + s.pass_rate + '%;background:' + rateColor + '"></div></div></div></td>' +
      '<td>' + s.unique_channels_passed + '/' + s.unique_channels_total + '</td>' +
      '<td>' + mins + ' 分钟</td>' +
      '<td><button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteRun(\'' + run.run_id + '\')">删除</button></td>';
    const actionCell = tr.lastElementChild;
    if (actionCell) {
      actionCell.innerHTML =
        '<div class="history-actions">' +
        '<button class="btn btn-outline btn-sm" onclick="event.stopPropagation();openRunLogModal(\'' + run.run_id + '\')">日志</button>' +
        '<button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteRun(\'' + run.run_id + '\')">删除</button>' +
        '</div>';
    }
    tbody.appendChild(tr);
    // Detail row
    const detailTr = document.createElement('tr');
    detailTr.className = 'history-detail-row';
    detailTr.id = 'detail-' + run.run_id;
    detailTr.innerHTML = '<td colspan="8"><div class="no-data" style="padding:12px">点击加载详情（含搜索筛选）...</div></td>';
    tbody.appendChild(detailTr);
  });
}

function renderHistoryChart(runs) {
  latestHistoryRuns = Array.isArray(runs) ? runs : [];
  const wrap = document.getElementById('historyChartWrap');
  const svg = document.getElementById('historyChart');
  const title = document.getElementById('historyChartTitle');
  const palette = getThemePalette();
  if (!runs || runs.length < 2) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = '';
  title.textContent = '通过率趋势（' + runs.length + ' 轮）';
  svg.innerHTML = '';
  const sorted = [...runs].reverse();
  const n = sorted.length;
  const points = [];
  sorted.forEach((run, i) => {
    const x = (i / (n - 1)) * 760 + 20;
    const y = 190 - (run.summary.pass_rate / 100 * 170);
    points.push(x + ',' + y);
    const color = run.summary.pass_rate >= 50 ? '#22c55e' : '#ef4444';
    svg.innerHTML += '<circle cx="' + x + '" cy="' + y + '" r="4" fill="' + color + '"/>';
    svg.innerHTML += '<text x="' + x + '" y="200" text-anchor="middle" font-size="9" fill="' + palette.chartMuted + '">' + run.finished_at.substring(5, 16) + '</text>';
    svg.innerHTML += '<text x="' + x + '" text-anchor="middle" font-size="10" fill="' + palette.chartText + '" y="' + (y - 8) + '">' + run.summary.pass_rate + '%</text>';
  });
  svg.innerHTML += '<polyline points="' + points.join(' ') + '" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linejoin="round"/>';
  svg.innerHTML += '<line x1="20" y1="20" x2="780" y2="20" stroke="' + palette.chartGrid + '" stroke-width="1"/>';
  svg.innerHTML += '<line x1="20" y1="105" x2="780" y2="105" stroke="' + palette.chartGrid + '" stroke-width="1"/>';
  svg.innerHTML += '<line x1="20" y1="190" x2="780" y2="190" stroke="' + palette.chartGridStrong + '" stroke-width="1"/>';
}

function toggleHistoryDetail(row, runId) {
  const detailRow = document.getElementById('detail-' + runId);
  if (!detailRow) return;
  // Toggle
  if (detailRow.classList.contains('open')) {
    detailRow.classList.remove('open');
    row.classList.remove('expanded');
    return;
  }
  // Close all other open details
  document.querySelectorAll('.history-detail-row.open').forEach(r => r.classList.remove('open'));
  document.querySelectorAll('.history-row.expanded').forEach(r => r.classList.remove('expanded'));

  row.classList.add('expanded');
  detailRow.classList.add('open');
  // Load detail if not already loaded
  const content = detailRow.querySelector('.no-data');
  if (content && content.textContent.startsWith('点击加载详情')) {
    content.textContent = '加载中...';
    fetch('/api/run/' + runId)
      .then(r => r.json())
      .then(data => {
        if (data.error) { content.textContent = data.error; return; }
        // Build search/filter toolbar + table
        let html = '<div style="padding:12px">';
        html += '<div class="toolbar" style="margin-bottom:8px">';
        html += '<input type="text" class="detail-inline-search" placeholder="搜索频道名或 URL..." data-runid="' + runId + '">';
        html += '<select class="detail-inline-filter" data-runid="' + runId + '">';
        html += '<option value="all">全部</option><option value="pass">仅通过</option><option value="fail">仅失败</option><option value="h265">仅 H.265</option>';
        html += '</select></div>';
        html += '<div class="table-wrap" style="margin:0;box-shadow:none"><table class="detail-inline-table" data-runid="' + runId + '" style="font-size:12px"><thead><tr>';
        html += '<th>频道</th><th>URL</th><th>分辨率</th><th>带宽(MB/s)</th><th>延迟</th><th>评分</th><th>编码</th><th>采样(秒)</th><th>耗时(秒)</th><th>状态</th><th>原因</th></tr></thead><tbody>';
        (data.results || []).forEach(r => {
          const cls = r.passed ? 'pass' : 'fail';
          const h265 = r.is_h265 ? '1' : '0';
          const passed = r.passed ? '1' : '0';
          let codec = '-';
          if (r.is_h265) codec = '<span class="badge h265">H.265</span>';
          else if (r.codec) codec = '<span class="badge h264">' + r.codec.toUpperCase() + '</span>';
          const status = r.passed ? '<span class="badge pass">通过</span>' : '<span class="badge fail">失败</span>';
          const latency = r.connection_latency_ms == null ? '-' : Math.round(r.connection_latency_ms) + ' ms';
          const score = r.quality_score == null ? '-' : Number(r.quality_score).toFixed(2);
          html += '<tr class="' + cls + '" data-channel="' + r.channel + '" data-passed="' + passed + '" data-h265="' + h265 + '">';
          html += '<td class="ch-name"><strong>' + r.channel + '</strong></td>';
          html += '<td><div class="url-cell" title="' + r.url + '">' + r.url + '</div></td>';
          html += '<td>' + r.resolution + '</td>';
          html += '<td>' + r.bandwidth_MBps + '</td>';
          html += '<td>' + latency + '</td>';
          html += '<td>' + score + '</td>';
          html += '<td>' + codec + '</td>';
          html += '<td>' + r.sample_seconds + '</td>';
          html += '<td>' + r.cost_seconds + '</td>';
          html += '<td>' + status + '</td>';
          html += '<td style="font-size:11px;color:#6b7280">' + (r.reason || '') + '</td>';
          html += '</tr>';
        });
        html += '</tbody></table></div>';
        html += '<div style="margin-top:10px"><button class="btn btn-sm" onclick="loadRunLogs(\'' + runId + '\', this)">查看运行日志</button>';
        html += '<div class="run-log-viewer" id="logs-' + runId + '" style="display:none;margin-top:8px"></div></div>';
        html += '</div>';
        detailRow.querySelector('td').innerHTML = html;
        const legacyLogWrap = detailRow.querySelector('.run-log-viewer');
        if (legacyLogWrap && legacyLogWrap.parentElement) {
          legacyLogWrap.parentElement.remove();
        }
        // Bind search/filter events
        const searchInput = detailRow.querySelector('.detail-inline-search');
        const filterSelect = detailRow.querySelector('.detail-inline-filter');
        const filterFn = function() {
          const q = searchInput.value.toLowerCase();
          const f = filterSelect.value;
          detailRow.querySelectorAll('.detail-inline-table tbody tr').forEach(tr => {
            const ch = (tr.dataset.channel || '').toLowerCase();
            const url = tr.querySelector('.url-cell') ? tr.querySelector('.url-cell').textContent.toLowerCase() : '';
            const p = tr.dataset.passed;
            const h = tr.dataset.h265;
            let show = true;
            if (q && !ch.includes(q) && !url.includes(q)) show = false;
            if (f === 'pass' && p !== '1') show = false;
            if (f === 'fail' && p !== '0') show = false;
            if (f === 'h265' && h !== '1') show = false;
            tr.style.display = show ? '' : 'none';
          });
        };
        searchInput.addEventListener('input', filterFn);
        filterSelect.addEventListener('change', filterFn);
      })
      .catch(e => { content.textContent = '加载失败: ' + e; });
  }
}

// ───── Run Logs ─────
function loadRunLogs(runId, btn) {
  const container = document.getElementById('logs-' + runId);
  if (!container) return;
  if (container.style.display !== 'none') {
    container.style.display = 'none';
    btn.textContent = '查看运行日志';
    return;
  }
  container.style.display = 'block';
  container.innerHTML = '<div style="color:#9ca3af;padding:8px">加载日志中...</div>';
  btn.textContent = '收起日志';
  fetch('/api/run/' + runId + '/logs')
    .then(r => r.json())
    .then(logs => {
      logs = Array.isArray(logs) ? logs : ((logs && logs.logs) || []);
      if (!logs || !logs.length) {
        container.innerHTML = '<div style="color:#9ca3af;padding:8px">暂无日志记录</div>';
        return;
      }
      let html = '<pre class="run-log-pre">';
      logs.forEach(l => {
        const lvl = l.level === 'ERROR' ? '[ERROR]' : l.level === 'WARNING' ? '[WARN]' : '[INFO]';
        html += '<span class="run-log-time">' + l.ts + '</span> ' + lvl + ' ' + _escapeHtml(l.message) + '\n';
      });
      html += '</pre>';
      container.innerHTML = html;
    })
    .catch(e => {
      container.innerHTML = '<div style="color:#ef4444;padding:8px">加载失败: ' + e + '</div>';
    });
}
function formatRunDateLabel(run) {
  if (!run || !run.finished_at) return '-';
  return run.finished_at.substring(5, 16);
}

function formatDurationMinutes(seconds) {
  const mins = Number(seconds || 0) / 60;
  return mins.toFixed(mins >= 10 ? 0 : 1) + ' min';
}

function getCoverageRate(summary) {
  if (!summary || !summary.unique_channels_total) return 0;
  return (summary.unique_channels_passed / summary.unique_channels_total) * 100;
}

function renderOverview(runs) {
  latestHistoryRuns = Array.isArray(runs) ? runs : [];
  renderOverviewStats(latestHistoryRuns);
  renderOverviewPassRateChart(latestHistoryRuns);
  renderOverviewVolumeChart(latestHistoryRuns);
  renderOverviewInsights(latestHistoryRuns);
}

function renderOverviewStats(runs) {
  const root = document.getElementById('overviewStats');
  if (!root) return;
  if (!runs || !runs.length) {
    root.innerHTML = '';
    return;
  }

  const totalRuns = runs.length;
  const avgPassRate = runs.reduce((sum, run) => sum + Number(run.summary.pass_rate || 0), 0) / totalRuns;
  const avgCoverage = runs.reduce((sum, run) => sum + getCoverageRate(run.summary), 0) / totalRuns;
  const avgDurationMins = runs.reduce((sum, run) => sum + Number(run.duration_seconds || 0), 0) / totalRuns / 60;
  const latest = runs[0];
  const latestDelta = Number(latest.summary.pass_rate || 0) - avgPassRate;
  const bestRun = runs.reduce((best, run) => {
    if (!best) return run;
    return Number(run.summary.pass_rate || 0) > Number(best.summary.pass_rate || 0) ? run : best;
  }, null);

  const cards = [
    {
      label: '历史轮次',
      value: totalRuns,
      sub: '当前数据集中共 ' + totalRuns + ' 轮',
      klass: ''
    },
    {
      label: '平均通过率',
      value: avgPassRate.toFixed(1) + '%',
      sub: '最近一次 ' + latest.summary.pass_rate + '%',
      klass: avgPassRate >= 50 ? 'green' : 'red'
    },
    {
      label: '相对均值',
      value: (latestDelta >= 0 ? '+' : '') + latestDelta.toFixed(1) + ' pt',
      sub: '对比历史平均通过率',
      klass: latestDelta >= 0 ? 'green' : 'red'
    },
    {
      label: '平均频道覆盖',
      value: avgCoverage.toFixed(1) + '%',
      sub: '通过频道 / 总频道',
      klass: 'blue'
    },
    {
      label: '平均耗时',
      value: avgDurationMins.toFixed(avgDurationMins >= 10 ? 0 : 1),
      sub: '分钟 / 轮',
      klass: 'purple'
    },
    {
      label: '最佳一轮',
      value: bestRun ? (bestRun.summary.pass_rate + '%') : '-',
      sub: bestRun ? bestRun.finished_at : '暂无',
      klass: 'green'
    }
  ];

  root.innerHTML = cards.map(card =>
    '<div class="card">' +
    '<div class="label">' + card.label + '</div>' +
    '<div class="value ' + card.klass + '">' + card.value + '</div>' +
    '<div class="sub">' + card.sub + '</div>' +
    '</div>'
  ).join('');
}

function renderOverviewPassRateChart(runs) {
  const svg = document.getElementById('overviewPassRateChart');
  const empty = document.getElementById('overviewPassRateEmpty');
  const subtitle = document.getElementById('overviewPassRateSubtitle');
  if (!svg || !empty || !subtitle) return;

  if (!runs || runs.length < 2) {
    svg.innerHTML = '';
    empty.style.display = '';
    subtitle.textContent = runs && runs.length ? '仅有 1 轮记录' : '暂无历史记录';
    return;
  }

  empty.style.display = 'none';
  subtitle.textContent = '最近 ' + runs.length + ' 轮，最新一轮在最右侧';

  const palette = getThemePalette();
  const ordered = [...runs].reverse();
  const maxX = 860;
  const minX = 40;
  const maxY = 24;
  const minY = 214;
  const step = ordered.length > 1 ? (maxX - minX) / (ordered.length - 1) : 0;
  const avgPassRate = ordered.reduce((sum, run) => sum + Number(run.summary.pass_rate || 0), 0) / ordered.length;
  const labelEvery = Math.max(1, Math.ceil(ordered.length / 8));

  const points = ordered.map((run, index) => {
    const rate = Number(run.summary.pass_rate || 0);
    const x = minX + step * index;
    const y = minY - (rate / 100) * (minY - maxY);
    return { x, y, rate, label: formatRunDateLabel(run) };
  });

  let html = '';
  [0, 25, 50, 75, 100].forEach(level => {
    const y = minY - (level / 100) * (minY - maxY);
    html += '<line x1="' + minX + '" y1="' + y + '" x2="' + maxX + '" y2="' + y + '" stroke="' + (level === 0 ? palette.chartGridStrong : palette.chartGrid) + '" stroke-width="1"/>';
    html += '<text x="8" y="' + (y + 4) + '" font-size="10" fill="' + palette.chartMuted + '">' + level + '%</text>';
  });

  const avgY = minY - (avgPassRate / 100) * (minY - maxY);
  html += '<line x1="' + minX + '" y1="' + avgY + '" x2="' + maxX + '" y2="' + avgY + '" stroke="#a855f7" stroke-width="1.5" stroke-dasharray="5 4"/>';
  html += '<text x="' + maxX + '" y="' + (avgY - 6) + '" text-anchor="end" font-size="10" fill="#a855f7">平均 ' + avgPassRate.toFixed(1) + '%</text>';

  html += '<polyline points="' + points.map(point => point.x + ',' + point.y).join(' ') + '" fill="none" stroke="#2563eb" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>';

  points.forEach((point, index) => {
    const color = point.rate >= 50 ? '#22c55e' : '#ef4444';
    html += '<circle cx="' + point.x + '" cy="' + point.y + '" r="4" fill="' + color + '"/>';
    if (index % labelEvery === 0 || index === points.length - 1) {
      html += '<text x="' + point.x + '" y="234" text-anchor="middle" font-size="10" fill="' + palette.chartMuted + '">' + point.label + '</text>';
      html += '<text x="' + point.x + '" y="' + (point.y - 10) + '" text-anchor="middle" font-size="10" fill="' + palette.chartText + '">' + point.rate + '%</text>';
    }
  });

  svg.innerHTML = html;
}

function renderOverviewVolumeChart(runs) {
  const svg = document.getElementById('overviewVolumeChart');
  const empty = document.getElementById('overviewVolumeEmpty');
  const subtitle = document.getElementById('overviewVolumeSubtitle');
  if (!svg || !empty || !subtitle) return;

  if (!runs || !runs.length) {
    svg.innerHTML = '';
    empty.style.display = '';
    subtitle.textContent = '暂无历史记录';
    return;
  }

  empty.style.display = 'none';
  subtitle.textContent = '绿色为通过地址，红色为失败地址';

  const palette = getThemePalette();
  const ordered = [...runs].reverse();
  const maxTotal = Math.max(...ordered.map(run => Number(run.summary.total_tested || 0)), 1);
  const chartHeight = 170;
  const baseY = 210;
  const left = 24;
  const right = 500;
  const slotWidth = (right - left) / Math.max(ordered.length, 1);
  const barWidth = Math.max(8, Math.min(28, slotWidth * 0.58));
  const labelEvery = Math.max(1, Math.ceil(ordered.length / 8));

  let html = '';
  [0, maxTotal / 2, maxTotal].forEach(value => {
    const y = baseY - (value / maxTotal) * chartHeight;
    html += '<line x1="' + left + '" y1="' + y + '" x2="' + right + '" y2="' + y + '" stroke="' + (value === 0 ? palette.chartGridStrong : palette.chartGrid) + '" stroke-width="1"/>';
    html += '<text x="0" y="' + (y + 4) + '" font-size="10" fill="' + palette.chartMuted + '">' + Math.round(value) + '</text>';
  });

  ordered.forEach((run, index) => {
    const total = Number(run.summary.total_tested || 0);
    const passed = Number(run.summary.total_passed || 0);
    const x = left + slotWidth * index + (slotWidth - barWidth) / 2;
    const totalHeight = (total / maxTotal) * chartHeight;
    const passedHeight = total > 0 ? totalHeight * (passed / total) : 0;
    const failedHeight = Math.max(0, totalHeight - passedHeight);
    const y = baseY - totalHeight;

    html += '<rect x="' + x + '" y="' + y + '" width="' + barWidth + '" height="' + failedHeight + '" rx="4" fill="#ef4444"/>';
    html += '<rect x="' + x + '" y="' + (baseY - passedHeight) + '" width="' + barWidth + '" height="' + passedHeight + '" rx="4" fill="#22c55e"/>';

    if (index % labelEvery === 0 || index === ordered.length - 1) {
      html += '<text x="' + (x + barWidth / 2) + '" y="234" text-anchor="middle" font-size="10" fill="' + palette.chartMuted + '">' + formatRunDateLabel(run) + '</text>';
    }
  });

  svg.innerHTML = html;
}

function renderOverviewInsights(runs) {
  const highlights = document.getElementById('overviewHighlights');
  const watchlist = document.getElementById('overviewWatchlist');
  if (!highlights || !watchlist) return;

  if (!runs || !runs.length) {
    highlights.innerHTML = '<div class="insight-item"><div class="meta"><div class="desc">暂无历史记录</div></div></div>';
    watchlist.innerHTML = '<div class="insight-item"><div class="meta"><div class="desc">暂无历史记录</div></div></div>';
    return;
  }

  const latest = runs[0];
  const previous = runs[1] || null;
  const bestRun = runs.reduce((best, run) => !best || Number(run.summary.pass_rate || 0) > Number(best.summary.pass_rate || 0) ? run : best, null);
  const worstRuns = [...runs]
    .sort((a, b) => Number(a.summary.pass_rate || 0) - Number(b.summary.pass_rate || 0))
    .slice(0, Math.min(4, runs.length));

  let stableStreak = 0;
  for (const run of runs) {
    if (Number(run.summary.pass_rate || 0) >= 50) stableStreak += 1;
    else break;
  }

  const highlightItems = [
    {
      name: '最近一次测试',
      desc: latest.finished_at + '，覆盖 ' + latest.summary.unique_channels_passed + '/' + latest.summary.unique_channels_total + ' 个频道',
      value: latest.summary.pass_rate + '%',
      klass: Number(latest.summary.pass_rate || 0) >= 50 ? 'good' : 'warn'
    },
    {
      name: '与上一轮对比',
      desc: previous ? (previous.finished_at + ' 作为参考') : '暂无上一轮数据',
      value: previous ? ((Number(latest.summary.pass_rate || 0) - Number(previous.summary.pass_rate || 0) >= 0 ? '+' : '') + (Number(latest.summary.pass_rate || 0) - Number(previous.summary.pass_rate || 0)).toFixed(1) + ' pt') : '-',
      klass: !previous || Number(latest.summary.pass_rate || 0) >= Number(previous.summary.pass_rate || 0) ? 'good' : 'warn'
    },
    {
      name: '最好的一轮',
      desc: bestRun ? bestRun.finished_at : '暂无',
      value: bestRun ? bestRun.summary.pass_rate + '%' : '-',
      klass: 'good'
    },
    {
      name: '稳定连续轮次',
      desc: '通过率 >= 50% 的连续轮次',
      value: stableStreak + ' 轮',
      klass: stableStreak >= 3 ? 'good' : ''
    }
  ];

  highlights.innerHTML = highlightItems.map(item =>
    '<div class="insight-item">' +
    '<div class="meta"><div class="name">' + item.name + '</div><div class="desc">' + item.desc + '</div></div>' +
    '<div class="value ' + (item.klass || '') + '">' + item.value + '</div>' +
    '</div>'
  ).join('');

  watchlist.innerHTML = worstRuns.map(run => {
    const coverage = getCoverageRate(run.summary).toFixed(1);
    return (
      '<div class="insight-item">' +
      '<div class="meta"><div class="name">' + run.finished_at + '</div>' +
      '<div class="desc">通过 ' + run.summary.total_passed + '/' + run.summary.total_tested + '，频道覆盖 ' + coverage + '%</div></div>' +
      '<div class="value warn">' + run.summary.pass_rate + '%</div>' +
      '</div>'
    );
  }).join('');
}

function findRunById(runId) {
  return (latestHistoryRuns || []).find(run => run.run_id === runId)
    || (initialHistoryRuns || []).find(run => run.run_id === runId)
    || null;
}

function openRunLogModal(runId) {
  const modal = document.getElementById('runLogModal');
  const meta = document.getElementById('runLogModalMeta');
  const body = document.getElementById('runLogBody');
  const search = document.getElementById('runLogSearch');
  if (!modal || !meta || !body || !search) return;

  currentRunLogRunId = runId;
  currentRunLogEntries = [];
  currentRunLogText = '';
  search.value = '';
  updateRunLogCount(0, 0, false);

  const run = findRunById(runId);
  if (run) {
    meta.textContent = run.finished_at + ' | 通过率 ' + run.summary.pass_rate + '% | ' + run.summary.total_passed + '/' + run.summary.total_tested + ' 地址';
  } else {
    meta.textContent = '加载日志中...';
  }

  body.innerHTML = '<div class="log-line" style="color:#6b7280">加载日志中...</div>';
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';

  fetch('/api/run/' + runId + '/logs')
    .then(r => r.json())
    .then(payload => {
      const logs = Array.isArray(payload) ? payload : (payload.logs || []);
      currentRunLogEntries = logs;
      currentRunLogText = logs.map(log => {
        const lvl = log.level === 'ERROR' ? '[ERROR]' : log.level === 'WARNING' ? '[WARN]' : '[INFO]';
        return (log.ts || '-') + ' ' + lvl + ' ' + (log.message || '');
      }).join('\n');
      renderRunLogEntries(logs);
      updateRunLogCount(logs.length, payload.total || logs.length, Boolean(payload.truncated));
    })
    .catch(e => {
      body.innerHTML = '<div class="log-line" style="color:#ef4444">加载失败: ' + _escapeHtml(String(e)) + '</div>';
      updateRunLogCount(0, 0, false);
    });
}

function closeRunLogModal() {
  const modal = document.getElementById('runLogModal');
  if (!modal) return;
  modal.classList.remove('open');
  document.body.style.overflow = '';
}

function updateRunLogCount(visibleCount, totalCount, truncated) {
  const el = document.getElementById('runLogCount');
  if (!el) return;
  let text = '显示 ' + visibleCount + ' / ' + totalCount + ' 条';
  if (truncated) text += '（已截断）';
  el.textContent = text;
}

function renderRunLogEntries(entries) {
  const body = document.getElementById('runLogBody');
  if (!body) return;

  const keyword = ((document.getElementById('runLogSearch') || {}).value || '').toLowerCase();
  const filtered = (entries || []).filter(log => {
    if (!keyword) return true;
    return ((log.ts || '') + ' ' + (log.level || '') + ' ' + (log.message || '')).toLowerCase().includes(keyword);
  });

  if (!filtered.length) {
    body.innerHTML = '<div class="log-line" style="color:#6b7280">没有匹配的日志内容</div>';
    updateRunLogCount(0, entries.length, false);
    return;
  }

  body.innerHTML = filtered.map(log => {
    const level = log.level === 'ERROR' ? '[ERROR]' : log.level === 'WARNING' ? '[WARN]' : '[INFO]';
    let cls = 'log-info';
    if (log.level === 'ERROR' || /失败|异常|error/i.test(log.message || '')) cls = 'log-fail';
    else if (/通过|完成|pass/i.test(log.message || '')) cls = 'log-pass';

    return (
      '<div class="run-log-line">' +
      '<span class="run-log-time">' + _escapeHtml(log.ts || '-') + '</span> ' +
      '<span class="run-log-level">' + level + '</span> ' +
      '<span class="' + cls + '">' + _escapeHtml(log.message || '') + '</span>' +
      '</div>'
    );
  }).join('');
  updateRunLogCount(filtered.length, entries.length, false);
}

function filterRunLogLines() {
  renderRunLogEntries(currentRunLogEntries);
}

function copyRunLogContent(btn) {
  if (!currentRunLogText) return;
  copyText(currentRunLogText)
    .then(() => setCopyButtonState(btn, '已复制', '复制日志'))
    .catch(() => showToast('复制日志失败，请手动复制', 'error'));
}

function _escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

// ───── Copy link ─────
function setCopyButtonState(btn, copiedText, resetText) {
  if (!btn) return;
  btn.textContent = copiedText;
  btn.classList.add('copied');
  setTimeout(() => {
    btn.textContent = resetText;
    btn.classList.remove('copied');
  }, 2000);
}

function fallbackCopyText(text) {
  return new Promise((resolve, reject) => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-9999px';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);

    try {
      const copied = document.execCommand('copy');
      document.body.removeChild(ta);
      if (copied) resolve();
      else reject(new Error('execCommand copy returned false'));
    } catch (e) {
      document.body.removeChild(ta);
      reject(e);
    }
  });
}

function copyText(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    return navigator.clipboard.writeText(text);
  }
  return fallbackCopyText(text);
}

function copyLink(fmt, btn) {
  const url = location.origin + '/api/download/' + fmt;
  copyText(url)
    .then(() => setCopyButtonState(btn, '已复制', '复制'))
    .catch(() => showToast('复制失败，请手动复制链接', 'error'));
}

// ───── Preview result ─────
let previewRawContent = '';
function previewResult(fmt) {
  const panel = document.getElementById('previewPanel');
  const content = document.getElementById('previewContent');
  const title = document.getElementById('previewTitle');
  const stats = document.getElementById('previewStats');
  panel.style.display = '';
  content.textContent = '加载中...';
  stats.textContent = '';
  title.textContent = fmt.toUpperCase() + ' 预览';

  fetch('/api/download/' + fmt)
    .then(r => {
      if (!r.ok) throw new Error('加载失败');
      return r.text();
    })
    .then(text => {
      previewRawContent = text;
      content.textContent = text;
      // 统计信息
      const lines = text.split('\n').filter(l => l.trim());
      const channelLines = lines.filter(l => !l.startsWith('#') && !l.includes('#genre#'));
      const genres = lines.filter(l => l.includes('#genre#'));
      if (fmt === 'txt') {
        stats.textContent = '共 ' + genres.length + ' 个分类，' + channelLines.length + ' 条频道记录，' + text.length + ' 字符';
      } else {
        const channels = lines.filter(l => l.startsWith('#EXTINF'));
        stats.textContent = '共 ' + channels.length + ' 个频道，' + text.length + ' 字符';
      }
    })
    .catch(e => {
      content.textContent = '加载失败: ' + e.message;
      previewRawContent = '';
    });
}

function closePreview() {
  document.getElementById('previewPanel').style.display = 'none';
  previewRawContent = '';
}

function copyPreviewContent(btn) {
  if (!previewRawContent) return;
  copyText(previewRawContent)
    .then(() => setCopyButtonState(btn, '已复制', '复制全部'))
    .catch(() => showToast('复制失败，请手动复制内容', 'error'));
}

// ───── Init download links ─────
(function() {
  const base = location.origin;
  document.getElementById('linkTxt').textContent = base + '/api/download/txt';
  document.getElementById('linkM3u').textContent = base + '/api/download/m3u';
})();

// ───── Delete run ─────
function deleteRun(runId) {
  if (!confirm('确定删除该轮记录？')) return;
  fetch('/api/run/' + runId, {method: 'DELETE'})
    .then(r => r.json())
    .then(res => {
      if (res.ok) {
        const row = document.querySelector('tr.history-row[data-runid="' + runId + '"]');
        const detail = document.getElementById('detail-' + runId);
        if (row) row.remove();
        if (detail) detail.remove();
        latestHistoryRuns = (latestHistoryRuns || []).filter(run => run.run_id !== runId);
        initialHistoryRuns = (initialHistoryRuns || []).filter(run => run.run_id !== runId);
        renderOverview(latestHistoryRuns);
        const noData = document.getElementById('historyNoData');
        if (noData && !document.querySelector('#historyBody tr.history-row')) {
          noData.style.display = '';
        }
        if (currentRunLogRunId === runId) {
          closeRunLogModal();
        }
        showToast('已删除', 'success');
      }
    })
    .catch(e => showToast('删除失败: ' + e, 'error'));
}

// ───── Init ─────
ensureThemeToggle();
initialHistoryRuns = loadInitialRunsData();
latestHistoryRuns = initialHistoryRuns.slice();
renderOverview(initialHistoryRuns);
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeRunLogModal();
});
loadConfig();
loadTextFile();
