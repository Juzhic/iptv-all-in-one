// ───── Tab switching ─────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.add('active');
  });
});

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
  'system_bandwidth_limit_MBps', 'run_mode', 'run_times', 'run_interval_minutes',
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
    } else if (['min_width', 'min_height', 'test_duration', 'max_workers', 'max_ffmpeg_workers', 'max_urls_per_channel', 'run_interval_minutes'].includes(key)) {
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
let completionConfirmCount = 0;

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

    const total = Number(data.total) || 0;
    const processed = Number(data.processed) || 0;
    const pct = total > 0 ? Math.max(0, Math.min(100, Math.round(processed / total * 100))) : 0;
    const fill = document.getElementById('progressFill');
    const pctEl = document.getElementById('progressPercent');
    const labelEl = document.getElementById('progressLabel');
    if (fill) fill.style.width = pct + '%';
    if (pctEl) pctEl.textContent = pct + '%';
    if (labelEl) labelEl.textContent = total > 0 ? ('进度 ' + processed + ' / ' + total) : '准备中...';
    const procEl = document.getElementById('progProcessed');
    const passEl = document.getElementById('progPassed');
    const failEl = document.getElementById('progFailed');
    const timeEl = document.getElementById('progElapsed');
    if (procEl) procEl.textContent = processed;
    if (passEl) passEl.textContent = data.passed;
    if (failEl) failEl.textContent = data.failed;
    if (timeEl) timeEl.textContent = Math.round(data.elapsed || 0);

    // Web 触发的运行有日志行
    if (data.source === 'web' && data.lines && data.lines.length > 0) {
      isWebRun = true;
      const panel = document.getElementById('logPanel');
      if (panel) {
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
    }

  } else if (testStarted) {
    if (isWebRun && completionConfirmCount < 1) {
      return;
    }
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
        completionConfirmCount = 0;
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
          completionConfirmCount += 1;
          if (completionConfirmCount < 2) {
            setTimeout(pollGlobalProgress, 2000);
            return;
          }
          if (data.error) showToast('测试异常: ' + data.error, 'error');
          else showToast('测试已完成', 'success');
          isWebRun = false;
          testStarted = false;
          completionConfirmCount = 0;
        }
      }
    })
    .catch(() => {});
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
        completionConfirmCount = 0;
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
        completionConfirmCount = 0;
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
      renderHistoryChart(runs);
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
  const wrap = document.getElementById('historyChartWrap');
  const svg = document.getElementById('historyChart');
  const title = document.getElementById('historyChartTitle');
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
    svg.innerHTML += '<text x="' + x + '" y="200" text-anchor="middle" font-size="9" fill="#9ca3af">' + run.finished_at.substring(5, 16) + '</text>';
    svg.innerHTML += '<text x="' + x + '" text-anchor="middle" font-size="10" fill="#374151" y="' + (y - 8) + '">' + run.summary.pass_rate + '%</text>';
  });
  svg.innerHTML += '<polyline points="' + points.join(' ') + '" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linejoin="round"/>';
  svg.innerHTML += '<line x1="20" y1="20" x2="780" y2="20" stroke="#f3f4f6" stroke-width="1"/>';
  svg.innerHTML += '<line x1="20" y1="105" x2="780" y2="105" stroke="#f3f4f6" stroke-width="1"/>';
  svg.innerHTML += '<line x1="20" y1="190" x2="780" y2="190" stroke="#e5e7eb" stroke-width="1"/>';
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
  fetch('/api/run/' + runId + '/logs?limit=500')
    .then(r => r.json())
    .then(logs => {
      if (!logs || !logs.length) {
        container.innerHTML = '<div style="color:#9ca3af;padding:8px">暂无日志记录</div>';
        return;
      }
      let html = '<pre style="background:#111827;color:#d1d5db;padding:12px;border-radius:8px;max-height:400px;overflow-y:auto;font-size:12px;line-height:1.6;margin:0">';
      logs.forEach(l => {
        const lvl = l.level === 'ERROR' ? '🔴' : l.level === 'WARNING' ? '🟡' : '⚪';
        html += '<span style="color:#6b7280">' + l.ts + '</span> ' + lvl + ' ' + _escapeHtml(l.message) + '\n';
      });
      html += '</pre>';
      container.innerHTML = html;
    })
    .catch(e => {
      container.innerHTML = '<div style="color:#ef4444;padding:8px">加载失败: ' + e + '</div>';
    });
}
function _escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

// ───── Copy link ─────
function copyLink(fmt, btn) {
  const url = location.origin + '/api/download/' + fmt;
  navigator.clipboard.writeText(url).then(() => {
    btn.textContent = '已复制';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '复制'; btn.classList.remove('copied'); }, 2000);
  }).catch(() => {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = url;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.textContent = '已复制';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '复制'; btn.classList.remove('copied'); }, 2000);
  });
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
  navigator.clipboard.writeText(previewRawContent).then(() => {
    btn.textContent = '已复制';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '复制全部'; btn.classList.remove('copied'); }, 2000);
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = previewRawContent;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.textContent = '已复制';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '复制全部'; btn.classList.remove('copied'); }, 2000);
  });
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
        showToast('已删除', 'success');
      }
    })
    .catch(e => showToast('删除失败: ' + e, 'error'));
}

// ───── Init ─────
loadConfig();
loadTextFile();
