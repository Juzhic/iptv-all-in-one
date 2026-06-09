// ───── Scan Module State ─────
var keyListGridApi = null;
var scanResultGridApi = null;
var scanPollTimer = null;
var scanIsRunning = false;
var scanLogEntries = [];
var scanLastLogSeq = 0;
var scanAutoScroll = true;
var scanTriggerPending = false;  // 等待后端确认扫描已启动
var scannerTabInitialized = false;
var scanResultsTabInitialized = false;
var scanResultsPage = 1;
var scanResultsTotal = 0;
var scanResultsPerPage = 50;

function getAgTheme() {
  var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  return isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine';
}

function applyAgThemeToElement(el) {
  if (!el) return;
  el.classList.remove('ag-theme-alpine', 'ag-theme-alpine-dark');
  el.classList.add(getAgTheme());
}

function applyScanGridTheme() {
  applyAgThemeToElement(document.getElementById('keyListGrid'));
  applyAgThemeToElement(document.getElementById('scanResultGrid'));
}

function ensureAgGridStyles() {
  var styles = [
    {id: 'ag-grid-core-styles', href: 'https://cdn.jsdelivr.net/npm/ag-grid-community@35.3.1/styles/ag-grid.css'},
    {id: 'ag-grid-alpine-styles', href: 'https://cdn.jsdelivr.net/npm/ag-grid-community@35.3.1/styles/ag-theme-alpine.css'}
  ];
  styles.forEach(function (item) {
    if (document.getElementById(item.id) || document.querySelector('link[href="' + item.href + '"]')) return;
    var link = document.createElement('link');
    link.id = item.id;
    link.rel = 'stylesheet';
    link.href = item.href;
    document.head.appendChild(link);
  });
}

if (typeof window !== 'undefined') {
  window.applyScanGridTheme = applyScanGridTheme;
  window.addEventListener('iptv-theme-change', applyScanGridTheme);
}

ensureAgGridStyles();

// ───── Inject scan-specific CSS ─────
(function () {
  var styleId = 'scan-module-styles';
  if (document.getElementById(styleId)) return;
  var style = document.createElement('style');
  style.id = styleId;
  style.textContent =
    /* Province checkboxes grid */
    '.scan-province-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:4px 8px;max-height:200px;overflow-y:auto;border:1px solid var(--input-border,#d1d5db);border-radius:6px;padding:8px;background:var(--input-bg,#fff)}' +
    '.scan-province-item{display:flex;align-items:center;gap:4px;font-size:13px;cursor:pointer;user-select:none;padding:2px 0}' +
    '.scan-province-item input[type="checkbox"]{margin:0;cursor:pointer}' +

    /* Platform checkboxes row */
    '.scan-platform-row{display:flex;gap:16px;flex-wrap:wrap;align-items:center}' +
    '.scan-platform-item{display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer;user-select:none}' +

    /* API key row */
    '.scan-apikeys{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}' +

    /* Scan config grid */
    '.scan-config-row{display:grid;grid-template-columns:1fr 1fr;gap:16px}' +
    '@media(max-width:768px){.scan-config-row{grid-template-columns:1fr}}' +

    /* Stability bar in results table */
    '.scan-stability-bar{display:flex;align-items:center;gap:6px;min-width:80px}' +
    '.scan-stability-bar div:first-child{height:8px;border-radius:4px;flex:1;min-width:40px;max-width:100px}' +
    '.scan-stability-text{font-size:11px;color:var(--text-muted,#6b7280);white-space:nowrap}' +

    /* Pagination */
    '.scan-pagination{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px;flex-wrap:wrap}' +
    '.scan-pagination-info{font-size:12px;color:var(--text-muted,#6b7280)}' +
    '.scan-pagination-btns{display:flex;gap:4px;flex-wrap:wrap}' +

    /* Quick stats */
    '.scan-quick-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:16px}' +

    /* Results toolbar */
    '.scan-results-toolbar{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center}' +
    '.scan-results-toolbar input,.scan-results-toolbar select{padding:6px 12px;border:1px solid var(--input-border,#d1d5db);border-radius:6px;font-size:13px;outline:none;background:var(--input-bg,#fff);color:var(--text-primary,#1a1a2e)}' +
    '.scan-results-toolbar input:focus,.scan-results-toolbar select:focus{border-color:#2563eb;box-shadow:0 0 0 2px rgba(37,99,235,.15)}' +
    '.scan-results-toolbar input{flex:1;min-width:160px}' +

    /* Province button group */
    '.scan-province-actions{display:flex;gap:6px;margin-bottom:6px}' +

    /* AG Grid dark-mode fallback */
    ':root[data-theme="dark"] .ag-theme-alpine,:root[data-theme="dark"] .ag-theme-alpine-dark{--ag-background-color:var(--surface,#0f172a);--ag-foreground-color:var(--text-primary,#e5e7eb);--ag-secondary-foreground-color:var(--text-secondary,#d1d5db);--ag-header-foreground-color:var(--text-secondary,#d1d5db);--ag-border-color:var(--border,#334155);--ag-secondary-border-color:var(--border-light,#1f2937);--ag-header-background-color:var(--surface-subtle,#111827);--ag-odd-row-background-color:var(--surface-subtle,#111827);--ag-row-hover-color:var(--surface-hover,#172033);--ag-selected-row-background-color:var(--surface-selected-strong,#1d2a3f);--ag-control-panel-background-color:var(--surface,#0f172a);--ag-subheader-background-color:var(--surface,#0f172a);--ag-tooltip-background-color:var(--surface,#0f172a);color-scheme:dark}' +
    ':root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-root-wrapper,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-root,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-body,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-body-viewport,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-center-cols-clipper,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-center-cols-viewport,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-center-cols-container,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-paging-panel{background-color:var(--ag-background-color)!important;color:var(--ag-foreground-color)!important;border-color:var(--ag-border-color)!important}' +
    ':root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-header,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-header-viewport,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-header-container,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-header-row,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-header-cell,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-header-group-cell{background-color:var(--ag-header-background-color)!important;color:var(--ag-header-foreground-color)!important;border-color:var(--ag-border-color)!important}' +
    ':root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-row,:root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-cell{background-color:var(--ag-background-color)!important;color:var(--ag-foreground-color)!important;border-color:var(--ag-secondary-border-color)!important}' +
    ':root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-row-odd{background-color:var(--ag-odd-row-background-color)!important}' +
    ':root[data-theme="dark"] [class*="ag-theme-alpine"] .ag-row-hover{background-color:var(--ag-row-hover-color)!important}';

  document.head.appendChild(style);
})();

// ───── Province list ─────
const PROVINCES = [
  '北京', '天津', '上海', '重庆',
  '河北', '山西', '辽宁', '吉林', '黑龙江',
  '江苏', '浙江', '安徽', '福建', '江西', '山东',
  '河南', '湖北', '湖南', '广东', '海南',
  '四川', '贵州', '云南', '陕西', '甘肃', '青海',
  '台湾', '内蒙古', '广西', '西藏', '宁夏', '新疆',
  '香港', '澳门'
];

// ───── Tab Init ─────
function initScannerTab() {
  if (scannerTabInitialized) return;
  scannerTabInitialized = true;

  buildProvinceCheckboxes();
  loadScanConfig();

  // Bind button events
  var btnStart = document.getElementById('btnStartScan');
  var btnStop = document.getElementById('btnStopScan');
  var btnHealth = document.getElementById('btnHealthCheck');
  var btnForceClear = document.getElementById('btnForceClearScan');
  var btnSave = null; // HTML uses onclick
  var btnAutoScroll = document.getElementById('btnScanAutoScroll');

  if (btnStart) btnStart.addEventListener('click', triggerScan);
  if (btnStop) btnStop.addEventListener('click', stopScan);
  if (btnHealth) btnHealth.addEventListener('click', scanHealthCheck);
  if (btnForceClear) btnForceClear.addEventListener('click', forceClearScan);
  if (btnSave) btnSave.addEventListener('click', saveScanConfig);
  if (btnAutoScroll) {
    btnAutoScroll.classList.add('active');
    btnAutoScroll.addEventListener('click', toggleScanAutoScroll);
  }

  // Check if scan is already running
  pollScanStatus();
  scanPollTimer = setInterval(pollScanStatus, 2000);
}

function initScanResultsTab() {
  if (scanResultsTabInitialized) return;
  scanResultsTabInitialized = true;

  loadScanHistory();
  loadScanResults(1);

  // Bind events
  var historySelect = document.getElementById('scanHistorySelect');
  if (historySelect) historySelect.addEventListener('change', function () {
    scanResultsPage = 1;
    loadScanResults(1);
  });

  var categoryFilter = document.getElementById('scanCategoryFilter');
  if (categoryFilter) categoryFilter.addEventListener('change', function () {
    scanResultsPage = 1;
    loadScanResults(1);
  });

  var provinceFilter = document.getElementById('scanProvinceFilter');
  if (provinceFilter) provinceFilter.addEventListener('change', function () {
    scanResultsPage = 1;
    loadScanResults(1);
  });

  var searchInput = document.getElementById('scanResultSearch');
  if (searchInput) {
    var debounceTimer = null;
    searchInput.addEventListener('input', function () {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        scanResultsPage = 1;
        loadScanResults(1);
      }, 400);
    });
  }

  var btnSelectAll = document.getElementById('scanSelectAll');
  if (btnSelectAll) btnSelectAll.addEventListener('change', toggleScanSelectAll);

  var btnFeed = document.getElementById('btnScanFeedToTest');
  if (btnFeed) btnFeed.addEventListener('click', feedSelectedToTest);
}

// ───── Province Checkboxes ─────
function buildProvinceCheckboxes() {
  var container = document.getElementById('scanProvince');
  if (!container) return;
  container.className = 'scan-province-grid';
  var html = '';
  PROVINCES.forEach(function (prov) {
    html += '<label class="scan-province-item">' +
      '<input type="checkbox" name="scan_province" value="' + prov + '"> ' + prov +
      '</label>';
  });
  container.innerHTML = html;
}

function getSelectedProvinces() {
  var checkboxes = document.querySelectorAll('#scanProvince input[name="scan_province"]:checked');
  var result = [];
  checkboxes.forEach(function (cb) { result.push(cb.value); });
  return result;
}

function setSelectedProvinces(provinces) {
  var checkboxes = document.querySelectorAll('#scanProvince input[name="scan_province"]');
  var provSet = {};
  (provinces || []).forEach(function (p) { provSet[p] = true; });
  checkboxes.forEach(function (cb) {
    cb.checked = !!provSet[cb.value];
  });
}

function selectAllProvinces() {
  var checkboxes = document.querySelectorAll('#scanProvince input[name="scan_province"]');
  checkboxes.forEach(function (cb) { cb.checked = true; });
}

function clearAllProvinces() {
  var checkboxes = document.querySelectorAll('#scanProvince input[name="scan_province"]');
  checkboxes.forEach(function (cb) { cb.checked = false; });
}

// ───── Scan Config ─────
function loadScanConfig() {
  fetch('/api/scan/config')
    .then(function (r) { return r.json(); })
    .then(function (cfg) {
      applyScanConfig(cfg);
    })
    .catch(function (e) { showToast('加载扫描配置失败: ' + e, 'error'); });
}

function applyScanConfig(cfg) {
  if (!cfg) return;

  // 平台现在通过 Key 管理自动检测，不再需要手动勾选

  // API keys 现在通过 /api/scan/keys 独立管理，不再从 config 加载

  // Provinces
  setSelectedProvinces(cfg.selected_provinces || []);

  // Other fields
  var op = document.getElementById('scanOperator');
  var sz = document.getElementById('scanSize');
  var cm = document.getElementById('scanCMode');
  if (op) op.value = cfg.operator || '';
  if (sz) sz.value = cfg.quake_size || 100;
  if (cm) cm.value = cfg.enable_c_scan ? 'true' : 'false';

  // Scheduling fields
  var updateTime = document.getElementById('scanUpdateTime');
  var dailyFull = document.getElementById('scanDailyFull');
  var weekdays = document.querySelectorAll('.scan-weekday');
  if (updateTime) updateTime.value = cfg.update_time || '03:00';
  if (dailyFull) dailyFull.checked = !!cfg.daily_full_update;
  var updateDays = cfg.update_days || [0,1,2,3,4,5,6];
  weekdays.forEach(function (cb) {
    cb.checked = updateDays.indexOf(parseInt(cb.value)) >= 0;
  });
  updateWeekdayEnable();
  startScanCountdown();
  loadKeyList();
}

function saveScanConfig() {
  var updateDays = [];
  document.querySelectorAll('.scan-weekday:checked').forEach(function (cb) {
    updateDays.push(parseInt(cb.value));
  });
  var dailyFull = document.getElementById('scanDailyFull').checked;
  if (dailyFull) updateDays = [0,1,2,3,4,5,6];

  var data = {
    selected_provinces: getSelectedProvinces(),
    operator: (document.getElementById('scanOperator') || {}).value || '',
    quake_size: parseInt((document.getElementById('scanSize') || {}).value) || 100,
    enable_c_scan: (document.getElementById('scanCMode') || {}).value === 'true',
    update_time: (document.getElementById('scanUpdateTime') || {}).value || '03:00',
    update_days: updateDays,
    daily_full_update: dailyFull
  };

  fetch('/api/scan/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast('扫描配置已保存', 'success');
        if (res.config) applyScanConfig(res.config);
      } else {
        showToast('保存失败: ' + (res.error || ''), 'error');
      }
    })
    .catch(function (e) { showToast('保存失败: ' + e, 'error'); });
}

// ───── Scheduling Logic ─────
var scanCountdownTimer = null;

function updateWeekdayEnable() {
  var dailyFull = document.getElementById('scanDailyFull');
  var weekdays = document.querySelectorAll('.scan-weekday');
  if (dailyFull && dailyFull.checked) {
    weekdays.forEach(function (cb) { cb.checked = false; cb.disabled = true; });
  } else {
    weekdays.forEach(function (cb) { cb.disabled = false; });
  }
  setScanNextUpdateTarget();
}

function setScanNextUpdateTarget() {
  var timeInput = document.getElementById('scanUpdateTime');
  var dailyFull = document.getElementById('scanDailyFull');
  var display = document.getElementById('scanNextUpdate');
  if (!timeInput || !display) return;

  var parts = timeInput.value.split(':');
  var hour = parseInt(parts[0]) || 3;
  var minute = parseInt(parts[1]) || 0;

  var updateDays = [];
  if (dailyFull && dailyFull.checked) {
    updateDays = [0,1,2,3,4,5,6];
  } else {
    document.querySelectorAll('.scan-weekday:checked').forEach(function (cb) {
      updateDays.push(parseInt(cb.value));
    });
  }

  if (updateDays.length === 0) {
    display.textContent = '未设置扫描日';
    return null;
  }

  var now = new Date();
  var target = null;
  for (var d = 0; d < 8; d++) {
    var cand = new Date(now);
    cand.setDate(cand.getDate() + d);
    cand.setHours(hour, minute, 0, 0);
    // JS weekday: 0=Sun,1=Mon,...,6=Sat → our format: 0=Mon,...,6=Sun
    var jsDay = cand.getDay();
    var ourDay = (jsDay === 0) ? 6 : jsDay - 1;
    if (updateDays.indexOf(ourDay) >= 0 && cand > now) {
      target = cand;
      break;
    }
  }

  if (target) {
    display.dataset.target = target.getTime();
  } else {
    display.textContent = '未找到匹配时间';
    display.dataset.target = '';
  }
  return target;
}

function updateScanCountdown() {
  var display = document.getElementById('scanNextUpdate');
  if (!display || !display.dataset.target) return;
  var targetMs = parseInt(display.dataset.target);
  if (!targetMs) return;

  var diff = targetMs - Date.now();
  if (diff <= 0) {
    display.textContent = '即将扫描...';
    return;
  }
  var sec = Math.floor(diff / 1000);
  var days = Math.floor(sec / 86400);
  sec %= 86400;
  var h = Math.floor(sec / 3600);
  var m = Math.floor((sec % 3600) / 60);
  var s = sec % 60;
  var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
  if (days > 0) {
    display.textContent = '下次扫描: ' + days + '天 ' + pad(h) + ':' + pad(m) + ':' + pad(s);
  } else {
    display.textContent = '下次扫描: ' + pad(h) + ':' + pad(m) + ':' + pad(s);
  }
}

function loadQuakeCredits() {
  var box = document.getElementById('quakeCredits');
  var text = document.getElementById('quakeCreditsText');
  if (!box || !text) return;
  box.style.display = 'block';
  text.textContent = '查询中...';
  fetch('/api/scan/quake-credits')
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok && res.keys && res.keys.length > 0) {
        var html = '';
        res.keys.forEach(function (k) {
          if (k.error) {
            html += '<div>Key ' + k.key_suffix + ': <span style="color:#ef4444">' + k.error + '</span></div>';
          } else {
            var creditNum = toFiniteNumber(k.credit);
            var warn = creditNum !== null && creditNum < 500 ? ' <span style="color:#ef4444">⚠️ 不足</span>' : '';
            html += '<div>Key ' + k.key_suffix + ': <b>' + formatCreditText(k.credit, k.role_limit) + '</b>' + warn + '</div>';
          }
        });
        text.innerHTML = html;
      } else if (res.keys && res.keys.length === 0) {
        text.textContent = '未配置 Quake Key';
      } else {
        text.textContent = res.error || '查询失败';
      }
    })
    .catch(function () { text.textContent = '查询失败'; });
}

function startScanCountdown() {
  if (scanCountdownTimer) clearInterval(scanCountdownTimer);
  setScanNextUpdateTarget();
  updateScanCountdown();
  scanCountdownTimer = setInterval(function () {
    setScanNextUpdateTarget();
    updateScanCountdown();
  }, 1000);
}

// Bind "每天" checkbox to toggle weekday enable
document.addEventListener('DOMContentLoaded', function () {
  applyScanGridTheme();
  buildProvinceCheckboxes();
  loadKeyList();
});

document.addEventListener('DOMContentLoaded', function () {
  var dailyFull = document.getElementById('scanDailyFull');
  if (dailyFull) dailyFull.addEventListener('change', updateWeekdayEnable);
  document.querySelectorAll('.scan-weekday').forEach(function (cb) {
    cb.addEventListener('change', setScanNextUpdateTarget);
  });
  var timeInput = document.getElementById('scanUpdateTime');
  if (timeInput) timeInput.addEventListener('change', setScanNextUpdateTarget);
});

// ───── Scan Control ─────
function triggerScan() {
  var btn = document.getElementById('btnStartScan');
  if (btn) { btn.disabled = true; btn.textContent = '启动中...'; }

  var data = {
    provinces: getSelectedProvinces()
  };

  scanTriggerPending = true;

  fetch('/api/scan/trigger', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast('扫描已启动', 'success');
        var panel = document.getElementById('scanLogPanel');
        if (panel) panel.innerHTML = '';
        scanLastLogSeq = 0;
        scanIsRunning = true;
        showScanProgress(true);
        updateScanBtnState(true);
        // 确保轮询定时器在运行
        if (scanPollTimer) clearInterval(scanPollTimer);
        scanPollTimer = setInterval(pollScanStatus, 2000);
        // 10 秒后如果后端仍未确认 running，解除 pending 保护
        setTimeout(function () { scanTriggerPending = false; }, 10000);
      } else {
        showToast(res.error || '启动失败', 'error');
        scanTriggerPending = false;
        resetScanBtn();
      }
    })
    .catch(function (e) {
      showToast('启动失败: ' + e, 'error');
      scanTriggerPending = false;
      resetScanBtn();
    });
}

function stopScan() {
  var btn = document.getElementById('btnStopScan');
  if (btn) { btn.disabled = true; btn.textContent = '终止中...'; }

  fetch('/api/scan/stop', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast(res.message || '已请求终止', 'success');
        scanIsRunning = false;
        resetScanBtn();
        if (scanPollTimer) { clearInterval(scanPollTimer); scanPollTimer = null; }
      } else {
        showToast(res.error || '终止失败', 'error');
        resetScanBtn();
      }
    })
    .catch(function (e) {
      showToast('终止失败: ' + e, 'error');
      resetScanBtn();
    });
}

function forceClearScan() {
  if (!confirm('确定要强制清除扫描状态？这会终止当前扫描。')) return;
  fetch('/api/scan/force-clear', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast(res.message || '已清除', 'success');
        scanIsRunning = false;
        resetScanBtn();
        if (scanPollTimer) { clearInterval(scanPollTimer); scanPollTimer = null; }
        showScanProgress(false);
      } else {
        showToast(res.error || '清除失败', 'error');
      }
    })
    .catch(function (e) { showToast('清除失败: ' + e, 'error'); });
}

function scanHealthCheck() {
  fetch('/api/scan/health', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast(res.message || '健康检查已启动', 'success');
        scanIsRunning = true;
        showScanProgress(true);
        updateScanBtnState(true);
        if (scanPollTimer) clearInterval(scanPollTimer);
        scanPollTimer = setInterval(pollScanStatus, 2000);
      } else {
        showToast(res.error || '健康检查启动失败', 'error');
      }
    })
    .catch(function (e) { showToast('健康检查请求失败: ' + e, 'error'); });
}

function resetScanBtn() {
  var btn = document.getElementById('btnStartScan');
  var stopBtn = document.getElementById('btnStopScan');
  if (btn) { btn.disabled = false; btn.textContent = '开始扫描'; }
  if (stopBtn) { stopBtn.disabled = false; stopBtn.style.display = 'none'; stopBtn.textContent = '终止扫描'; }
}

function updateScanBtnState(running) {
  var btn = document.getElementById('btnStartScan');
  var stopBtn = document.getElementById('btnStopScan');
  if (running) {
    if (btn) { btn.disabled = true; btn.textContent = '扫描中...'; }
    if (stopBtn) { stopBtn.style.display = ''; stopBtn.disabled = false; }
  } else {
    resetScanBtn();
  }
}

function showScanProgress(show) {
  var wrap = document.getElementById('scanProgressWrap');
  if (wrap) wrap.style.display = show ? '' : 'none';
}

// ───── Scan Progress Polling ─────
function pollScanStatus() {
  fetch('/api/scan/status')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      updateScanProgress(data);

      if (data.running) {
        // 后端确认扫描已启动，解除 pending 保护
        scanTriggerPending = false;
        scanIsRunning = true;
        updateScanBtnState(true);
        showScanProgress(true);

        appendScanLogs(data);

        if (!scanPollTimer) {
          scanPollTimer = setInterval(pollScanStatus, 2000);
        }
      } else {
        // 后端说未运行

        // 如果刚点了扫描按钮、后端还没来得及写 DB，保持 UI 不变
        if (scanTriggerPending) {
          return;
        }

        if (scanPollTimer) { clearInterval(scanPollTimer); scanPollTimer = null; }

        // Final log update
        appendScanLogs(data);

        if (scanIsRunning) {
          if (data.error) {
            showToast('扫描异常: ' + data.error, 'error');
          } else {
            showToast('扫描已完成', 'success');
          }
          scanIsRunning = false;
        }
        updateScanBtnState(false);

        // Update quick stats even when idle
        updateScanQuickStats(data);
      }
    })
    .catch(function () {
      // 网络错误时不重置 UI，只保底确保轮询存活
      if (!scanPollTimer) {
        scanPollTimer = setInterval(pollScanStatus, 5000);
      }
    });
}

function updateScanProgress(data) {
  var total = Number(data.total) || 0;
  var processed = Number(data.processed) || 0;
  var pct = total > 0 ? Math.max(0, Math.min(100, Math.round(processed / total * 100))) : 0;

  var fill = document.getElementById('scanProgressFill');
  var pctEl = document.getElementById('scanProgressPercent');
  var labelEl = document.getElementById('scanProgressLabel');
  var phaseEl = document.getElementById('scanStatusText');
  var scannedEl = document.getElementById('scanStatRaw');
  var channelsEl = document.getElementById('scanStatFiltered');
  var ipsEl = document.getElementById('scanStatDeep');
  var timeEl = document.getElementById('scanStatElapsed');

  if (fill) fill.style.width = pct + '%';
  if (pctEl) pctEl.textContent = pct + '%';
  if (labelEl) labelEl.textContent = total > 0 ? ('进度 ' + processed + ' / ' + total) : '准备中...';
  if (phaseEl) phaseEl.textContent = data.phase || '空闲';
  if (scannedEl) scannedEl.textContent = data.scanned || 0;
  if (channelsEl) channelsEl.textContent = data.channels_found || 0;
  if (ipsEl) ipsEl.textContent = data.ips_scanned || 0;
  if (timeEl) timeEl.textContent = Math.round(data.elapsed || 0);

  updateScanQuickStats(data);
}

function updateScanQuickStats(data) {
  var statsWrap = document.getElementById('scanQuickStats');
  if (!statsWrap) return;

  var categories = data.categories || {};
  var totalChannels = data.channels_found || 0;

  // Build category stat cards
  var statsData = [
    { label: '频道总数', value: totalChannels, color: '#2563eb' },
    { label: 'CCTV', value: categories['央视频道'] || categories['CCTV'] || 0, color: '#16a34a' },
    { label: '卫视', value: categories['卫视频道'] || 0, color: '#7c3aed' },
    { label: '地方台', value: categories['地方频道'] || 0, color: '#ea580c' },
    { label: 'IP数', value: data.ips_scanned || 0, color: '#0891b2' },
    { label: '已扫描', value: data.scanned || 0, color: '#6b7280' }
  ];

  var html = '';
  statsData.forEach(function (s) {
    html += '<div class="card">' +
      '<div class="label">' + s.label + '</div>' +
      '<div class="value" style="color:' + s.color + '">' + s.value + '</div>' +
      '</div>';
  });
  statsWrap.innerHTML = html;
}

// ───── Scan Log ─────
function appendScanLogs(data) {
  if (!data.lines || data.lines.length === 0) return;

  var panel = document.getElementById('scanLogPanel');
  if (!panel) return;

  data.lines.forEach(function (line) {
    // 增量：跳过已经显示过的行
    if (line.seq !== undefined && line.seq <= scanLastLogSeq) return;

    var div = document.createElement('div');
    div.className = 'log-line';
    var cls = 'log-info';
    if (line.msg && (line.msg.includes('发现') || line.msg.includes('频道') || line.msg.includes('成功') || line.msg.includes('完成'))) cls = 'log-pass';
    else if (line.msg && (line.msg.includes('失败') || line.msg.includes('错误') || line.msg.includes('超时') || line.msg.includes('异常'))) cls = 'log-fail';
    div.innerHTML = '<span class="log-time">[' + escapeHtml(line.time || '') + ']</span><span class="' + cls + '">' + escapeHtml(line.msg || '') + '</span>';
    panel.appendChild(div);
    if (line.seq !== undefined) scanLastLogSeq = line.seq;
  });

  if (scanAutoScroll) panel.scrollTop = panel.scrollHeight;
}

function toggleScanAutoScroll() {
  scanAutoScroll = !scanAutoScroll;
  var btn = document.getElementById('btnScanAutoScroll');
  if (btn) btn.className = 'btn-scroll' + (scanAutoScroll ? ' active' : '');
}

function clearScanLog() {
  var panel = document.getElementById('scanLogPanel');
  if (panel) panel.innerHTML = '';
}

// ───── Scan Results ─────
function loadScanHistory() {
  var select = document.getElementById('scanHistorySelect');
  if (!select) return;

  fetch('/api/scan/history')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var runs = data.history || data || [];
      var html = '<option value="">全部扫描记录</option>';
      runs.forEach(function (run) {
        var label = (run.started_at || run.run_id || '') +
          (run.channels_found !== undefined ? ' - ' + run.channels_found + ' 频道' : '');
        html += '<option value="' + (run.run_id || run.id || '') + '">' + escapeHtml(label) + '</option>';
      });
      select.innerHTML = html;
    })
    .catch(function (e) {
      showToast('加载扫描历史失败: ' + e, 'error');
    });
}

function loadScanResults(page) {
  scanResultsPage = page || 1;
  var params = new URLSearchParams();
  params.set('page', scanResultsPage);
  params.set('per_page', scanResultsPerPage);

  var historySelect = document.getElementById('scanHistorySelect');
  var categoryFilter = document.getElementById('scanCategoryFilter');
  var provinceFilter = document.getElementById('scanProvinceFilter');
  var searchInput = document.getElementById('scanResultSearch');

  if (historySelect && historySelect.value) params.set('run_id', historySelect.value);
  if (categoryFilter && categoryFilter.value) params.set('category', categoryFilter.value);
  if (provinceFilter && provinceFilter.value) params.set('province', provinceFilter.value);
  if (searchInput && searchInput.value.trim()) params.set('q', searchInput.value.trim());

  fetch('/api/scan/results?' + params.toString())
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var results = data.results || data || [];
      scanResultsTotal = data.total || results.length;
      renderScanResults(results);
      populateScanFilterOptions(data);
    })
    .catch(function (e) {
      if (scanResultGridApi) scanResultGridApi.setGridOption('rowData', []);
    });
}

function renderScanResults(results) {
  var container = document.getElementById('scanResultGrid');
  if (!container) return;
  applyAgThemeToElement(container);

  if (!scanResultGridApi) {
    var colDefs = [
      {headerName: '', field: 'selected', width: 40, headerCheckboxSelection: true, checkboxSelection: true},
      {headerName: '\u9891\u9053\u540d', field: 'name', width: 160},
      {headerName: '\u5206\u7c7b', field: 'category', width: 110},
      {headerName: '\u7701\u4efd', field: 'province', width: 90},
      {headerName: '\u5206\u8fa8\u7387', field: 'resolution', width: 110},
      {headerName: '\u7a33\u5b9a\u6027', field: 'stability', width: 120, comparator: function(a,b){return (a||0)-(b||0);},
        cellRenderer: function(p) {
          var v = p.value != null ? p.value : 0;
          var color = v >= 70 ? '#22c55e' : v >= 40 ? '#f59e0b' : '#ef4444';
          return '<div style="display:flex;align-items:center;gap:6px"><div style="flex:1;height:8px;border-radius:4px;background:#e5e7eb"><div style="width:'+v+'%;height:100%;border-radius:4px;background:'+color+'"></div></div><span style="font-size:11px;color:#6b7280">'+v+'%</span></div>';
        }
      },
      {headerName: '\u5ef6\u8fdf(ms)', field: 'delay', width: 100, comparator: function(a,b){return (a||9999)-(b||9999);}},
      {headerName: '\u5e26\u5bbd(KB/s)', field: 'bandwidth', width: 120, comparator: function(a,b){return (b||0)-(a||0);}},
      {headerName: '\u6765\u6e90IP', field: 'source_ip', width: 140, cellStyle: {fontFamily: 'monospace', fontSize: '12px'}}
    ];
    scanResultGridApi = agGrid.createGrid(container, {
      theme: 'legacy',
      columnDefs: colDefs, rowData: [], rowSelection: 'multiple',
      pagination: true, paginationPageSize: 50, paginationPageSizeSelector: [20, 50, 100, 200],
      domLayout: 'normal', suppressCellFocus: true
    });
  }

  var rows = (results || []).map(function (r) {
    return {
      name: r.name || '', category: r.category || '', province: r.province || '',
      resolution: r.resolution || '', stability: Math.round((r.stability || 0)),
      delay: r.delay != null ? Math.round(r.delay) : null,
      bandwidth: r.bandwidth != null ? Math.round(r.bandwidth) : null,
      source_ip: r.source_ip || ''
    };
  });
  scanResultGridApi.setGridOption('rowData', rows);
}

function renderScanPagination(total, page, perPage) {
  var wrap = document.getElementById('scanPagination');
  if (!wrap) return;

  var totalPages = Math.max(1, Math.ceil(total / Math.max(1, perPage)));
  if (total <= 0) { wrap.innerHTML = ''; return; }

  var html = '<div class="scan-pagination-info">共 ' + total + ' 条，第 ' + page + ' / ' + totalPages + ' 页</div>';
  html += '<div class="scan-pagination-btns">';

  // Previous
  html += '<button class="btn btn-outline btn-sm" ' +
    (page <= 1 ? 'disabled' : 'onclick="loadScanResults(' + (page - 1) + ')"') +
    '>上一页</button>';

  // Page numbers (show up to 7 pages around current)
  var startPage = Math.max(1, page - 3);
  var endPage = Math.min(totalPages, startPage + 6);
  if (endPage - startPage < 6) startPage = Math.max(1, endPage - 6);

  for (var i = startPage; i <= endPage; i++) {
    if (i === page) {
      html += '<button class="btn btn-primary btn-sm" disabled>' + i + '</button>';
    } else {
      html += '<button class="btn btn-outline btn-sm" onclick="loadScanResults(' + i + ')">' + i + '</button>';
    }
  }

  // Next
  html += '<button class="btn btn-outline btn-sm" ' +
    (page >= totalPages ? 'disabled' : 'onclick="loadScanResults(' + (page + 1) + ')"') +
    '>下一页</button>';

  html += '</div>';
  wrap.innerHTML = html;
}

function populateScanFilterOptions(data) {
  // Populate category filter from results if available
  if (data.categories && data.categories.length) {
    var catSelect = document.getElementById('scanCategoryFilter');
    if (catSelect && catSelect.options.length <= 1) {
      data.categories.forEach(function (cat) {
        var opt = document.createElement('option');
        opt.value = cat;
        opt.textContent = cat;
        catSelect.appendChild(opt);
      });
    }
  }

  // Populate province filter from results if available
  if (data.provinces && data.provinces.length) {
    var provSelect = document.getElementById('scanProvinceFilter');
    if (provSelect && provSelect.options.length <= 1) {
      data.provinces.forEach(function (prov) {
        var opt = document.createElement('option');
        opt.value = prov;
        opt.textContent = prov;
        provSelect.appendChild(opt);
      });
    }
  }
}

// ───── Select All / Feed to Test ─────
function toggleScanSelectAll() {
  var selectAll = document.getElementById('scanSelectAll');
  var checked = selectAll ? selectAll.checked : false;
  document.querySelectorAll('.scan-result-cb').forEach(function (cb) {
    cb.checked = checked;
  });
}

function feedSelectedToTest() {
  var selected = [];
  document.querySelectorAll('.scan-result-cb:checked').forEach(function (cb) {
    var name = cb.dataset.name;
    if (name && selected.indexOf(name) === -1) {
      selected.push(name);
    }
  });

  if (selected.length === 0) {
    showToast('请先选择要送测的频道', 'error');
    return;
  }

  fetch('/api/scan/feed-to-test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channels: selected })
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast('已将 ' + selected.length + ' 个频道送入测试', 'success');
        // Switch to testing tab
        switchToTestingTab();
      } else {
        showToast('送测失败: ' + (res.error || ''), 'error');
      }
    })
    .catch(function (e) { showToast('送测请求失败: ' + e, 'error'); });
}

function switchToTestingTab() {
  var tabs = document.querySelectorAll('.tab');
  var contents = document.querySelectorAll('.tab-content');
  tabs.forEach(function (t) {
    t.classList.remove('active');
    if (t.dataset.tab === 'testing') t.classList.add('active');
  });
  contents.forEach(function (c) { c.classList.remove('active'); });
  var testingEl = document.getElementById('testing');
  if (testingEl) testingEl.classList.add('active');
}

// ───── Escape HTML (reuse from index.js if already loaded) ─────
if (typeof window.escapeHtml !== 'function') {
  window.escapeHtml = function (str) {
    var div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  };
}

// ───── Tab switch integration ─────
// Hook into existing tab switching to init scan tabs on first show
(function () {
  var tabs = document.querySelectorAll('.tab');
  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      var tabId = tab.dataset.tab;
      if (tabId === 'scanner') {
        initScannerTab();
      } else if (tabId === 'scan-results') {
        initScanResultsTab();
      }
    });
  });

  // If scanner tab is active on load, init immediately
  var activeTab = document.querySelector('.tab.active');
  if (activeTab) {
    var activeTabId = activeTab.dataset.tab;
    if (activeTabId === 'scanner') initScannerTab();
    else if (activeTabId === 'scan-results') initScanResultsTab();
  }
})();

// ───── Scan Results Missing Functions ─────

function scanSelectAll() {
  if (!scanResultGridApi) return;
  var sel = scanResultGridApi.getSelectedRows();
  if (sel.length > 0) {
    scanResultGridApi.deselectAll();
  } else {
    scanResultGridApi.selectAll();
  }
}

function scanToggleAll(headerCb) {
  if (!scanResultGridApi) return;
  if (headerCb.checked) scanResultGridApi.selectAll();
  else scanResultGridApi.deselectAll();
}

function scanSendToSpeedTest() {
  if (!scanResultGridApi) return;
  var selected = [];
  scanResultGridApi.getSelectedRows().forEach(function (r) {
    if (r.name && selected.indexOf(r.name) < 0) selected.push(r.name);
  });
  if (selected.length === 0) {
    showToast('请先勾选频道', 'error');
    return;
  }
  var scanId = (document.getElementById('scanHistorySelect') || {}).value || '';
  if (!scanId) {
    showToast('请先选择一条扫描记录', 'error');
    return;
  }
  if (!confirm('将 ' + selected.length + ' 个频道送入测速？')) return;

  fetch('/api/scan/feed-to-test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scan_id: scanId, channel_names: selected })
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast(res.message || '已送入测速', 'success');
        // 切换到系统测速 tab
        document.querySelectorAll('.tab').forEach(function (t) {
          if (t.dataset.tab === 'testing') t.click();
        });
      } else {
        showToast(res.error || '送入失败', 'error');
      }
    })
    .catch(function (e) { showToast('送入失败: ' + e, 'error'); });
}

function scanExportM3U() {
  var scanId = (document.getElementById('scanHistorySelect') || {}).value || '';
  if (!scanId) {
    showToast('请先选择一条扫描记录', 'error');
    return;
  }
  // 通过 API 获取结果并生成 M3U 下载
  fetch('/api/scan/results?scan_id=' + scanId + '&size=9999')
    .then(function (r) { return r.json(); })
    .then(function (res) {
      var items = res.items || [];
      if (items.length === 0) {
        showToast('没有可导出的频道', 'error');
        return;
      }
      var m3u = '#EXTM3U\n';
      items.forEach(function (ch) {
        m3u += '#EXTINF:-1 group-title="' + (ch.category || '') + '",' + (ch.name || '') + '\n';
        m3u += (ch.url || '') + '\n';
      });
      var blob = new Blob([m3u], { type: 'audio/x-mpegurl' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'scan_result.m3u';
      a.click();
      URL.revokeObjectURL(url);
      showToast('已导出 ' + items.length + ' 个频道', 'success');
    })
    .catch(function (e) { showToast('导出失败: ' + e, 'error'); });
}

// ───── Key Management ─────
var PLATFORM_LABELS = {quake: 'Quake 360', hunter: 'Hunter 鹰图', daydaymap: 'DayDayMap'};

function toFiniteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number') return isFinite(value) ? value : null;
  var text = String(value).replace(/,/g, '').trim();
  var lowered = text.toLowerCase();
  if (!text || lowered === 'invalid number' || lowered === 'nan' || lowered === 'none' ||
      lowered === 'null' || lowered === 'undefined' || lowered === 'inf' || lowered === 'infinity') {
    return null;
  }
  var num = Number(text);
  return isFinite(num) ? num : null;
}

function formatCreditValue(value) {
  var num = toFiniteNumber(value);
  if (num === null) return '-';
  return num.toLocaleString('zh-CN', {maximumFractionDigits: 2});
}

function formatCreditText(credit, roleLimit) {
  var creditText = formatCreditValue(credit);
  var limitNum = toFiniteNumber(roleLimit);
  if (limitNum !== null) creditText += ' / ' + formatCreditValue(limitNum);
  return creditText;
}

function loadKeyList() {
  fetch('/api/scan/keys?t=' + Date.now(), {cache: 'no-cache'})
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (!res.ok) return;
      renderKeyList(res.keys || []);
    })
    .catch(function (e) { console.error('[KeyList] load failed:', e); });
}

function renderKeyList(keys) {
  var container = document.getElementById('keyListGrid');
  if (!container) return;
  applyAgThemeToElement(container);

  if (!keyListGridApi) {
    var colDefs = [
      {headerName: '\u5e73\u53f0', field: 'platform', width: 120,
       valueFormatter: function(p) { return PLATFORM_LABELS[p.value] || p.value; }},
      {headerName: 'Key', field: 'key_suffix', width: 150,
       cellStyle: {fontFamily: 'monospace', fontSize: '12px'}},
      {headerName: '\u4f59\u989d', field: 'credit', width: 130},
      {headerName: '\u72b6\u6001', field: 'status', width: 140,
       cellRenderer: function(p) {
         var v = p.value || '';
         var color;
         if (v === '\u6b63\u5e38') color = '#22c55e';
         else if (v === '\u504f\u4f4e') color = '#f59e0b';
         else if (v === '\u4f59\u989d\u672a\u77e5' || v.indexOf('\u6709\u6548') >= 0) color = '#3b82f6';
         else color = '#ef4444';
         return '<span style="color:'+color+'">'+v+'</span>';
       }},
      {headerName: '\u64cd\u4f5c', field: 'key', width: 160,
       cellRenderer: function(p) {
         if (!p.value) return '';
         return '<button class="btn btn-outline btn-sm" style="margin-right:6px" onclick="editKey(\''+p.data.platform+'\',\''+p.value.replace(/'/g,"\\'")+'\')">\u7f16\u8f91</button>' +
           '<button class="btn btn-outline btn-sm" style="color:#ef4444" onclick="deleteKey(\''+p.data.platform+'\',\''+p.value.replace(/'/g,"\\'")+'\')">\u5220\u9664</button>';
       }}
    ];
    keyListGridApi = agGrid.createGrid(container, {
      theme: 'legacy',
      columnDefs: colDefs, rowData: [], domLayout: 'autoHeight', suppressCellFocus: true
    });
  }

  var rows = (keys || []).map(function (k) {
    var status = '\u6b63\u5e38';
    var creditNum = toFiniteNumber(k.credit);
    if (k.error) status = k.error;
    else if (creditNum === null) {
      // \u6ca1\u6709\u4f59\u989d\u6570\u636e\uff1a\u5982\u679c\u6709 role \u4fe1\u606f\u8bf4\u660e key \u6709\u6548\u4f46\u65e0\u6cd5\u67e5\u4f59\u989d
      status = k.role ? k.role : '\u4f59\u989d\u672a\u77e5';
    }
    else if (creditNum < 100) status = '\u4f59\u989d\u4e0d\u8db3';
    else if (creditNum < 300) status = '\u504f\u4f4e';
    var creditText = formatCreditText(k.credit, k.role_limit);
    return {platform: k.platform, key_suffix: k.key_suffix, credit: creditText, status: status, key: k.key};
  });
  keyListGridApi.setGridOption('rowData', rows);
}

function openAddKeyModal() {
  var modal = document.getElementById('addKeyModal');
  if (modal) modal.style.display = 'flex';
  var input = document.getElementById('addKeyValue');
  if (input) input.value = '';
  var platformSelect = document.getElementById('addKeyPlatform');
  if (platformSelect) platformSelect.disabled = false;
  // 重置标题和按钮为添加模式
  if (modal) modal.querySelector('h3').textContent = '添加 API Key';
  var submitBtn = modal ? modal.querySelector('.btn-primary') : null;
  if (submitBtn) {
    submitBtn.textContent = '添加';
    submitBtn.onclick = submitAddKey;
  }
}

function closeAddKeyModal() {
  var modal = document.getElementById('addKeyModal');
  if (modal) modal.style.display = 'none';
  var platformSelect = document.getElementById('addKeyPlatform');
  if (platformSelect) platformSelect.disabled = false;
  // 重置为添加模式
  if (modal) modal.querySelector('h3').textContent = '添加 API Key';
  var submitBtn = modal ? modal.querySelector('.btn-primary') : null;
  if (submitBtn) { submitBtn.textContent = '添加'; submitBtn.onclick = submitAddKey; }
}

function submitAddKey() {
  var platform = (document.getElementById('addKeyPlatform') || {}).value || '';
  var key = (document.getElementById('addKeyValue') || {}).value.trim();
  if (!key) { showToast('请输入 Key', 'error'); return; }
  fetch('/api/scan/keys', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({platform: platform, key: key})
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast('Key 已添加', 'success');
        closeAddKeyModal();
        loadKeyList();
      } else {
        showToast(res.error || '添加失败', 'error');
      }
    })
    .catch(function (e) { showToast('添加失败: ' + e, 'error'); });
}

function deleteKey(platform, key) {
  if (!confirm('确定删除这个 Key？')) return;
  fetch('/api/scan/keys', {
    method: 'DELETE',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({platform: platform, key: key})
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.ok) {
        showToast('Key 已删除', 'success');
        loadKeyList();
      } else {
        showToast(res.error || '删除失败', 'error');
      }
    })
    .catch(function (e) { showToast('删除失败: ' + e, 'error'); });
}

function editKey(platform, key) {
  var modal = document.getElementById('addKeyModal');
  var platformSelect = document.getElementById('addKeyPlatform');
  var keyInput = document.getElementById('addKeyValue');
  if (!modal || !platformSelect || !keyInput) return;

  // 复用添加弹窗，平台不可改
  platformSelect.value = platform;
  platformSelect.disabled = true;
  keyInput.value = key;

  // 修改标题和按钮
  modal.querySelector('h3').textContent = '编辑 API Key';
  var submitBtn = modal.querySelector('.btn-primary');
  submitBtn.textContent = '保存';
  submitBtn.onclick = function () {
    var newKey = keyInput.value.trim();
    if (!newKey) { showToast('请输入 Key', 'error'); return; }
    if (newKey === key) { closeAddKeyModal(); return; }
    fetch('/api/scan/keys', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({platform: platform, old_key: key, new_key: newKey})
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.ok) {
          showToast('Key 已更新', 'success');
          closeAddKeyModal();
          loadKeyList();
        } else {
          showToast(res.error || '更新失败', 'error');
        }
      })
      .catch(function (e) { showToast('更新失败: ' + e, 'error'); });
  };

  modal.style.display = 'flex';
}

function refreshKeyCredits() {
  var btn = event.target;
  if (btn) { btn.disabled = true; btn.textContent = '查询中...'; }
  loadKeyList();
  setTimeout(function () {
    if (btn) { btn.disabled = false; btn.textContent = '刷新余额'; }
  }, 2000);
}
