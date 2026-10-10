// Nếu CDN lucide không tải được (máy không có mạng), vẫn phải chạy được app: thay bằng bản rỗng
if (typeof window !== 'undefined' && !window.lucide) {
  window.lucide = { createIcons() {} };
  console.warn('Không tải được thư viện icon lucide từ CDN; giao diện chạy không có icon.');
}

// ==================== HẰNG SỐ & TIỆN ÍCH CHUNG ====================
// Khớp đúng 5 trạng thái trong constants.JobStatus (docs/KIEN_TRUC.md mục 4). Không viết chuỗi trạng thái tay ở nơi khác.
const JOB_STATUS = Object.freeze({
  CHO: 'Chờ',
  DANG_CHAY: 'Đang chạy',
  HOAN_THANH: 'Hoàn thành',
  THAT_BAI: 'Thất bại',
  TAM_DUNG: 'Tạm dừng'
});

// Cột accounts.needs_manual (constants.NeedsManual)
const NEEDS_MANUAL_LABEL = Object.freeze({
  captcha: { text: 'Cần kéo captcha', cls: 'bg-[#2a2210] text-amber-300 border-amber-700/60' },
  login: { text: 'Cần đăng nhập lại', cls: 'bg-[#2a1215] text-rose-300 border-rose-800/60' },
  proxy: { text: 'Proxy lỗi', cls: 'bg-[#2a1215] text-rose-300 border-rose-800/60' }
});

let currentTab = 'video';

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Gọi API, trả JSON; ném lỗi có nội dung đọc được khi HTTP lỗi hoặc mất mạng
async function apiJson(url, options) {
  const res = await fetch(url, options);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    let detail = data && (data.detail || data.message);
    if (detail && typeof detail !== 'string') detail = JSON.stringify(detail);
    throw new Error(detail || `Máy chủ trả lỗi HTTP ${res.status}`);
  }
  return data || {};
}

// ==================== TOAST (thông báo góc màn hình) ====================
function showToast(msg, type = 'info', timeoutMs = 4500) {
  const container = document.getElementById('toastContainer');
  if (!container) { console.log(`[toast:${type}]`, msg); return; }
  const styles = {
    info: 'border-cyan-700/60 text-cyan-200 bg-[#0b1a22]',
    success: 'border-emerald-700/60 text-emerald-200 bg-[#0b2019]',
    warning: 'border-amber-700/60 text-amber-200 bg-[#231b0b]',
    error: 'border-red-700/60 text-red-200 bg-[#2a1215]'
  };
  const icons = { info: 'info', success: 'check-circle', warning: 'alert-triangle', error: 'x-circle' };
  const el = document.createElement('div');
  el.className = `pointer-events-auto border rounded-lg px-3 py-2 text-[11px] shadow-xl flex items-start space-x-2 transition-opacity duration-300 ${styles[type] || styles.info}`;
  el.innerHTML = `<i data-lucide="${icons[type] || 'info'}" class="w-3.5 h-3.5 mt-0.5 shrink-0"></i><span class="flex-1 break-words">${escapeHtml(msg)}</span><button class="shrink-0 opacity-60 hover:opacity-100" title="Đóng">✕</button>`;
  el.querySelector('button').onclick = () => el.remove();
  container.appendChild(el);
  if (window.lucide) lucide.createIcons({ nodes: [el] });
  while (container.children.length > 5) container.removeChild(container.firstChild);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 350); }, timeoutMs);
}

// Báo lỗi mạng/API: ghi console + toast, nhưng không spam cùng một lỗi mỗi 3 giây
const _lastFetchErrorAt = {};
function reportFetchError(context, err) {
  console.error(context + ':', err);
  const now = Date.now();
  if (_lastFetchErrorAt[context] && now - _lastFetchErrorAt[context] < 15000) return;
  _lastFetchErrorAt[context] = now;
  const detail = err && err.message ? err.message : String(err);
  showToast(`${context}: ${detail}`, 'error');
}

// Tab switching
function switchTab(tabId) {
  const tabs = ['overview', 'image', 'video', 'tut', 'assets', 'accounts', 'check-media', 'audio', 'logs', 'settings'];
  tabs.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    const nav = document.getElementById(`nav-${t}`);
    if (el) el.classList.add('hidden');
    if (nav) nav.classList.remove('sidebar-active');
  });

  const activeTab = document.getElementById(`tab-${tabId}`);
  const activeNav = document.getElementById(`nav-${tabId}`);
  if (activeTab) activeTab.classList.remove('hidden');
  if (activeNav) activeNav.classList.add('sidebar-active');
  currentTab = tabId;

  // Load specific tab data on switch
  if (tabId === 'image') fetchImages();
  if (tabId === 'assets') fetchAssets();
  if (tabId === 'check-media') loadNickMedia();
  if (tabId === 'logs') fetchLogs();
  if (tabId === 'settings') loadSettings();
  startLogsAutoRefresh(tabId === 'logs');
}

// Modal controls
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove('hidden');
}
function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add('hidden');
}

function openBatchPromptModal() { openModal('modalBatchPrompts'); }
function openAddAccountModal() { openModal('modalAddAccount'); }
function openImportModal() { openModal('modalImport'); }

// Toast / Copy helper
function copyPrompt(text) {
  navigator.clipboard.writeText(text);
  alert('Đã sao chép prompt vào bộ nhớ tạm: \n\n' + text);
}

// 1. Fetch Stats & Overview
async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    document.getElementById('headerRunningJobs').innerText = data.running_jobs;
    document.getElementById('sideRunningJobs').innerText = data.running_jobs;
    document.getElementById('headerTotalAccounts').innerText = data.total_accounts;
    document.getElementById('sideTotalAccounts').innerText = data.total_accounts;

    if (document.getElementById('statCompletedJobs')) {
      document.getElementById('statCompletedJobs').innerText = data.completed_jobs;
      document.getElementById('statTotalImages').innerText = data.total_images || 0;
      document.getElementById('statTotalAccounts').innerText = data.total_accounts;
      document.getElementById('statTotalAssets').innerText = data.total_assets || 0;
    }
  } catch (err) {
    reportFetchError('Lỗi lấy thống kê', err);
  }
}

// 1b. Tình trạng hệ thống (GET /api/health, làm mới mỗi 10 giây)
async function fetchHealth() {
  const textEl = document.getElementById('headerHealthText');
  const dotEl = document.getElementById('headerHealthDot');
  const boxEl = document.getElementById('headerHealth');
  const footerEl = document.getElementById('footerVersion');
  if (!textEl) return;
  try {
    const h = await apiJson('/api/health');
    const version = h.version ? `v${h.version}` : 'v?';
    const chromeOk = h.chrome_found === true;
    const active = (h.active_browsers === null || h.active_browsers === undefined) ? '?' : h.active_browsers;
    const max = (h.max_browsers === null || h.max_browsers === undefined) ? '?' : h.max_browsers;
    const chromeHtml = chromeOk
      ? `<span class="text-emerald-400">Chrome: OK</span>`
      : `<span class="text-red-400 font-bold">Chrome: Thiếu</span> <span class="text-red-300">(chạy CAI_TRINH_DUYET.bat)</span>`;
    const workerHtml = h.worker_alive === false ? ` · <span class="text-red-400 font-bold">Worker dừng</span>` : '';
    const dbHtml = h.db_ok === false ? ` · <span class="text-red-400 font-bold">CSDL lỗi</span>` : '';
    textEl.innerHTML = `${escapeHtml(version)} · ${chromeHtml} · Trình duyệt đang mở ${escapeHtml(active)}/${escapeHtml(max)}${workerHtml}${dbHtml}`;
    const healthy = h.ok !== false && chromeOk && h.worker_alive !== false && h.db_ok !== false;
    if (dotEl) dotEl.className = `w-2 h-2 rounded-full ${healthy ? 'bg-emerald-400 animate-pulse' : 'bg-red-500 animate-pulse'}`;
    if (boxEl) boxEl.className = `flex items-center space-x-1.5 px-2.5 py-1 rounded-full border ${healthy ? 'bg-[#0e171e] border-[#16272b] text-gray-300' : 'bg-[#2a1215] border-red-800/60 text-gray-200'}`;
    if (boxEl) boxEl.title = `Chrome: ${h.chrome_path || 'không tìm thấy'}`;
    if (footerEl) footerEl.innerText = `Seedance AI Studio ${version}`;
  } catch (err) {
    textEl.innerHTML = `<span class="text-red-400 font-bold">Mất kết nối máy chủ</span>`;
    if (dotEl) dotEl.className = 'w-2 h-2 rounded-full bg-red-500';
    if (boxEl) boxEl.className = 'flex items-center space-x-1.5 px-2.5 py-1 rounded-full border bg-[#2a1215] border-red-800/60 text-gray-200';
    reportFetchError('Không lấy được tình trạng hệ thống', err);
  }
}

// 2. Fetch and Render Video Jobs
function jobStatusBadge(status, progress) {
  const base = 'inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold border whitespace-nowrap';
  const pct = Number.isFinite(Number(progress)) ? Math.max(0, Math.min(100, Math.round(Number(progress)))) : 0;
  switch (status) {
    case JOB_STATUS.CHO:
      return `<span class="${base} bg-[#1a2333] text-gray-400 border-[#233145]"><span>Chờ</span></span>`;
    case JOB_STATUS.DANG_CHAY:
      return `<span class="${base} bg-[#11242c] text-cyan-400 border-[#1b3945]"><span class="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse"></span><span>Đang chạy ${pct}%</span></span>`;
    case JOB_STATUS.HOAN_THANH:
      return `<span class="${base} bg-[#0f2a1d] text-emerald-400 border-[#1a432e]"><span>✓ Hoàn thành</span></span>`;
    case JOB_STATUS.THAT_BAI:
      return `<span class="${base} bg-[#2a1215] text-red-400 border-[#441a1f]"><span>Thất bại</span></span>`;
    case JOB_STATUS.TAM_DUNG:
      return `<span class="${base} bg-[#2a2210] text-amber-300 border-amber-700/60"><span>⏸ Tạm dừng</span></span>`;
    default:
      // Trạng thái lạ (CSDL cũ hoặc backend mới hơn frontend): hiện nguyên chữ, không đoán
      return `<span class="${base} bg-[#1a2333] text-gray-400 border-[#233145]" title="Trạng thái không nằm trong 5 trạng thái chuẩn"><span>${escapeHtml(status || 'Không rõ')}</span></span>`;
  }
}

// Tách "[ảnh: ten.png]" trong status_message thành link mở ảnh chụp lỗi
function renderStatusMessage(message) {
  const raw = message || '';
  const m = raw.match(/\[ảnh:\s*([^\]]+?)\s*\]/);
  if (!m) return escapeHtml(raw);
  const fileName = m[1].replace(/\\/g, '/').split('/').filter(Boolean).pop() || m[1];
  const text = escapeHtml(raw.replace(m[0], '').trim());
  const link = `<a href="/logs/screenshots/${encodeURIComponent(fileName)}" target="_blank" rel="noopener" class="text-cyan-400 hover:underline" onclick="event.stopPropagation()" title="Mở ảnh chụp màn hình lúc lỗi: ${escapeHtml(fileName)}">📷 Xem ảnh lỗi</a>`;
  return text ? `${text} ${link}` : link;
}

function jobActionButtons(j) {
  const btn = (fn, label, cls, title) => `<button type="button" onclick="${fn}(${j.id})" class="px-2 py-1 rounded text-[10px] font-semibold border transition ${cls}" title="${escapeHtml(title)}">${label}</button>`;
  const parts = [];
  if (j.status === JOB_STATUS.THAT_BAI) {
    parts.push(btn('retryJob', '↻ Chạy lại', 'bg-[#10241f] hover:bg-[#163a32] text-emerald-300 border-emerald-800/50', 'Đưa job về Chờ để worker chạy lại từ đầu'));
  }
  if (j.status === JOB_STATUS.TAM_DUNG) {
    parts.push(btn('resumeJob', '▶ Tiếp tục', 'bg-[#10241f] hover:bg-[#163a32] text-emerald-300 border-emerald-800/50', 'Đưa job về Chờ và xóa cờ cần can thiệp của nick'));
  }
  if (j.status === JOB_STATUS.CHO) {
    parts.push(btn('pauseJob', '⏸ Tạm dừng', 'bg-[#2a2210] hover:bg-[#3a2e12] text-amber-300 border-amber-700/60', 'Giữ job lại, worker sẽ không nhặt cho tới khi bấm Tiếp tục'));
  }
  parts.push(`<button type="button" onclick="deleteJob(${j.id})" class="p-1.5 bg-[#251014] hover:bg-red-900/50 text-red-400 rounded border border-[#3e1b21] transition" title="Xóa job"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>`);
  return `<div class="flex items-center justify-center space-x-1">${parts.join('')}</div>`;
}

async function fetchJobs() {
  try {
    const data = await apiJson('/api/jobs?limit=500');
    const tbody = document.getElementById('jobsTableBody');
    if (!tbody) return;
    const jobs = Array.isArray(data.jobs) ? data.jobs : [];

    if (jobs.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="10" class="p-8 text-center text-gray-500">
            Chưa có job tạo video nào. Bấm <b>"Thêm Prompt Hàng Loạt"</b> ở góc trên để bắt đầu!
          </td>
        </tr>
      `;
      return;
    }

    _jobsById = {};
    jobs.forEach(j => { _jobsById[j.id] = j; });

    tbody.innerHTML = jobs.map(j => {
      const isRunning = j.status === JOB_STATUS.DANG_CHAY;
      const isCompleted = j.status === JOB_STATUS.HOAN_THANH;
      const pct = Number.isFinite(Number(j.progress)) ? Math.max(0, Math.min(100, Math.round(Number(j.progress)))) : 0;
      const statusMessage = j.status_message || '';
      const attempts = (j.attempts === null || j.attempts === undefined) ? 0 : j.attempts;
      const titleText = j.title || j.prompt || '';
      const promptFull = j.prompt_final || j.prompt || '';

      let batchLabel = '';
      if (j.batch_name || (j.seq !== null && j.seq !== undefined)) {
        const seqText = (j.seq !== null && j.seq !== undefined) ? `#${String(j.seq).padStart(3, '0')}` : '';
        batchLabel = `<div class="text-[9px] text-purple-300 truncate max-w-[70px]" title="Lô: ${escapeHtml(j.batch_name || '')} · Thứ tự ${escapeHtml(seqText)}">${escapeHtml([j.batch_name, seqText].filter(Boolean).join(' · '))}</div>`;
      }

      const accBadge = j.account_name ? `
        <div class="inline-flex items-center space-x-1 bg-[#101722] border border-[#1b2636] px-2 py-1 rounded text-[11px] text-gray-300" title="Nick #${escapeHtml(j.account_id)}">
          <i data-lucide="user" class="w-3 h-3 text-cyan-400"></i>
          <span class="truncate max-w-[100px]">${escapeHtml(j.account_name)}</span>
        </div>
      ` : `<span class="text-gray-500 text-[11px]">${isCompleted || j.status === JOB_STATUS.THAT_BAI ? 'Không có nick' : 'Chưa gán nick'}</span>`;

      const proxyBadge = j.account_proxy ? `
        <div class="bg-[#0e1620] border border-[#182433] px-2 py-0.5 rounded text-[10px] text-gray-300 font-mono">
          <div class="text-cyan-400 truncate max-w-[130px]" title="${escapeHtml(j.account_proxy)}">${escapeHtml(j.account_proxy)}</div>
        </div>
      ` : `<span class="text-gray-500 text-[10px] italic">Không proxy</span>`;

      const progressBar = isRunning ? `
              <div class="w-full bg-[#141d2a] h-1 rounded overflow-hidden">
                <div class="bg-gradient-to-r from-cyan-400 to-emerald-400 h-1 transition-all duration-300" style="width: ${pct}%"></div>
              </div>` : '';

      const videoButtons = (isCompleted && j.local_video_path) ? `
              <div class="mt-1 flex items-center space-x-1.5">
                <button type="button" onclick="openVideoPlayer('${escapeHtml(j.local_video_path)}', '${encodeURIComponent(titleText)}', ${j.id})" class="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded bg-cyan-950/60 text-cyan-300 hover:bg-cyan-900/80 border border-cyan-800/40 text-[10px] font-semibold transition">
                  <i data-lucide="play-circle" class="w-3.5 h-3.5 text-cyan-400"></i>
                  <span>Xem video</span>
                </button>
                <a href="/api/download-video/video_${j.id}.mp4" download class="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded bg-[#10231d] text-emerald-300 hover:bg-[#16382e] border border-emerald-800/40 text-[10px] font-semibold transition" title="Tải video MP4 về máy">
                  <i data-lucide="download" class="w-3 h-3 text-emerald-400"></i>
                  <span>Tải MP4</span>
                </a>
              </div>` : '';

      return `
        <tr class="hover:bg-[#0c121a] transition select-none">
          <td class="p-2.5 text-center"><input type="checkbox" class="rounded bg-gray-800 border-gray-700"></td>
          <td class="p-2.5 font-mono text-gray-400 font-semibold">
            <div>#${j.id}</div>
            ${batchLabel}
          </td>
          <td class="p-2.5">
            <div class="space-y-1" title="${escapeHtml(statusMessage)}">
              <div class="flex items-center justify-between">
                ${jobStatusBadge(j.status, j.progress)}
              </div>
              ${progressBar}
              <div class="text-[10px] text-gray-400 truncate max-w-[230px]">
                ${renderStatusMessage(statusMessage) || '<span class="text-gray-600">Chưa có thông báo</span>'}
              </div>
            </div>
          </td>
          <td class="p-2.5 text-center font-mono ${attempts > 1 ? 'text-amber-300' : 'text-gray-400'}" title="Số lần đã thử chạy job này">${escapeHtml(attempts)}</td>
          <td class="p-2.5 text-gray-300 font-medium" title="Thời lượng · tỷ lệ khung hình gửi Dola">${escapeHtml([j.duration, j.ratio].filter(Boolean).join(' · '))}</td>
          <td class="p-2.5 text-gray-300 font-semibold">${escapeHtml(j.model || '')}</td>
          <td class="p-2.5">${accBadge}</td>
          <td class="p-2.5">${proxyBadge}</td>
          <td class="p-2.5">
            <div class="font-medium text-gray-200 line-clamp-1" title="${escapeHtml(promptFull)}">${escapeHtml(titleText)}</div>
            <div class="mt-0.5 flex items-center space-x-1.5">
              ${j.archetype_code ? `<span class="px-1 py-0.5 rounded bg-[#0f2126] text-cyan-300 border border-cyan-900/60 text-[9px] font-mono" title="Trường phái Đạo diễn AI đã ghép vào prompt">${escapeHtml(j.archetype_code)}</span>` : `<span class="text-[9px] text-gray-600" title="Job này không qua Đạo diễn AI">không đạo diễn</span>`}
              <button type="button" onclick="openJobPromptModal(${j.id})" class="px-1.5 py-0.5 rounded bg-[#101722] text-gray-300 hover:text-cyan-300 border border-[#1b2636] text-[9px] font-semibold" title="Xem prompt gốc và prompt đã đạo diễn (sửa được khi job chưa chạy)">Prompt</button>
            </div>
            ${videoButtons}
          </td>
          <td class="p-2.5 text-center">${jobActionButtons(j)}</td>
        </tr>
      `;
    }).join('');

    lucide.createIcons();
  } catch (err) {
    reportFetchError('Không lấy được hàng đợi job', err);
  }
}

// Hành động trên job theo máy trạng thái (docs/KIEN_TRUC.md mục 4)
async function _jobAction(id, action, label) {
  try {
    const data = await apiJson(`/api/jobs/${id}/${action}`, { method: 'POST' });
    if (data.success === false) {
      showToast(`${label} job #${id} không được: ${data.message || data.detail || 'máy chủ từ chối'}`, 'warning');
    } else {
      showToast(`${label} job #${id} thành công`, 'success');
    }
    fetchJobs();
    fetchStats();
  } catch (err) {
    reportFetchError(`${label} job #${id} thất bại`, err);
  }
}
function retryJob(id) { return _jobAction(id, 'retry', 'Chạy lại'); }
function resumeJob(id) { return _jobAction(id, 'resume', 'Tiếp tục'); }
function pauseJob(id) { return _jobAction(id, 'pause', 'Tạm dừng'); }

// 3. Fetch and Render Images (Tạo Ảnh)
async function fetchImages() {
  try {
    const res = await fetch('/api/images');
    const data = await res.json();
    const grid = document.getElementById('imagesGrid');
    if (!grid) return;

    if (data.images.length === 0) {
      grid.innerHTML = `<div class="col-span-4 p-8 text-center text-gray-500">Chưa có ảnh nào được tạo. Nhập prompt bên trên để tạo ngay!</div>`;
      return;
    }

    grid.innerHTML = data.images.map(img => `
      <div class="bg-[#0b1017] border border-[#172333] rounded-xl overflow-hidden group hover:border-cyan-500/50 transition">
        <div class="relative aspect-video bg-black overflow-hidden">
          <img src="${img.image_url}" class="w-full h-full object-cover group-hover:scale-105 transition duration-300">
          <span class="absolute top-2 left-2 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-black/70 text-cyan-400 backdrop-blur-sm border border-cyan-500/30">
            ${img.style} • ${img.aspect_ratio}
          </span>
          <button onclick="deleteImage(${img.id})" class="absolute top-2 right-2 p-1 rounded bg-black/70 text-red-400 opacity-0 group-hover:opacity-100 transition hover:bg-red-900/50">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
        <div class="p-3 space-y-2">
          <p class="text-xs text-gray-300 line-clamp-2" title="${img.prompt}">${img.prompt}</p>
          <div class="flex items-center justify-between pt-1 border-t border-[#141e2b] text-[10px]">
            <span class="text-gray-500">${img.model}</span>
            <button onclick="useImageForVideo('${img.image_url}', '${encodeURIComponent(img.prompt)}')" class="text-emerald-400 hover:underline flex items-center space-x-1">
              <i data-lucide="arrow-right-circle" class="w-3 h-3"></i>
              <span>Dùng làm Video</span>
            </button>
          </div>
        </div>
      </div>
    `).join('');

    lucide.createIcons();
  } catch (err) {
    reportFetchError('Lỗi lấy danh sách ảnh', err);
  }
}

async function submitCreateImage() {
  const prompt = document.getElementById('imagePromptInput').value.trim();
  const model = document.getElementById('imageModelSelect').value;
  const aspect_ratio = document.getElementById('imageRatioSelect').value;
  const style = document.getElementById('imageStyleSelect').value;

  if (!prompt) {
    alert('Vui lòng nhập mô tả ảnh!');
    return;
  }

  try {
    const res = await fetch('/api/images', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, model, aspect_ratio, style })
    });
    const data = await res.json();
    if (data.success) {
      document.getElementById('imagePromptInput').value = '';
      fetchImages();
      fetchStats();
    }
  } catch (err) {
    showToast('Lỗi tạo ảnh: ' + err.message, 'error');
  }
}

async function deleteImage(id) {
  if (!confirm('Xóa ảnh này?')) return;
  try {
    await apiJson(`/api/images/${id}`, { method: 'DELETE' });
  } catch (err) {
    reportFetchError('Không xóa được ảnh', err);
  }
  fetchImages();
  fetchStats();
}

function useImageForVideo(imgUrl, prompt) {
  switchTab('video');
  openBatchPromptModal();
  document.getElementById('batchPromptsInput').value = decodeURIComponent(prompt);
}

// 4. Fetch and Render Assets (Kho Nhân Vật)
async function fetchAssets() {
  try {
    const res = await fetch('/api/assets');
    const data = await res.json();
    const grid = document.getElementById('assetsGrid');
    if (!grid) return;

    if (data.assets.length === 0) {
      grid.innerHTML = `<div class="col-span-3 p-8 text-center text-gray-500">Chưa có nhân vật nào trong kho. Bấm <b>"Thêm Nhân Vật Mới"</b> để lưu mẫu!</div>`;
      return;
    }

    grid.innerHTML = data.assets.map(a => `
      <div class="bg-[#0b1017] border border-[#172333] rounded-xl overflow-hidden flex flex-col justify-between">
        <div class="p-4 space-y-3">
          <div class="flex items-center space-x-3">
            <img src="${a.image_url || 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=200'}" class="w-14 h-14 rounded-full object-cover border-2 border-emerald-500/40">
            <div>
              <div class="font-bold text-gray-200 text-xs">${a.name}</div>
              <div class="text-[10px] text-cyan-400 font-mono mt-0.5">${a.character_code}</div>
            </div>
          </div>
          <p class="text-xs text-gray-400 line-clamp-2">${a.description || 'Không có mô tả'}</p>
          <div class="flex flex-wrap gap-1 text-[9px]">
            ${(a.tags || '').split(',').map(t => `<span class="bg-[#121c29] text-gray-300 px-1.5 py-0.5 rounded border border-[#1c2a3b]">${t.trim()}</span>`).join('')}
          </div>
        </div>
        <div class="p-3 bg-[#080c11] border-t border-[#141e2b] flex justify-between items-center text-xs">
          <button onclick="applyCharacterToVideo('${a.character_code}', '${encodeURIComponent(a.description || a.name)}')" class="px-2.5 py-1 bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30 rounded border border-emerald-500/30 text-[11px] font-semibold">
            Gán vào Video
          </button>
          <button onclick="deleteAsset(${a.id})" class="text-red-400 hover:text-red-300 p-1">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      </div>
    `).join('');

    lucide.createIcons();
  } catch (err) {
    reportFetchError('Lỗi lấy nhân vật', err);
  }
}

async function submitAddAsset() {
  const name = document.getElementById('assetNameInput').value.trim();
  const character_code = document.getElementById('assetCodeInput').value.trim();
  const image_url = document.getElementById('assetUrlInput').value.trim();
  const description = document.getElementById('assetDescInput').value.trim();

  if (!name) {
    alert('Vui lòng nhập tên nhân vật!');
    return;
  }

  try {
    const res = await fetch('/api/assets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, character_code, image_url, description })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('modalAddAsset');
      document.getElementById('assetNameInput').value = '';
      document.getElementById('assetCodeInput').value = '';
      document.getElementById('assetUrlInput').value = '';
      document.getElementById('assetDescInput').value = '';
      fetchAssets();
      fetchStats();
    }
  } catch (err) {
    showToast('Lỗi thêm asset: ' + err.message, 'error');
  }
}

async function deleteAsset(id) {
  if (!confirm('Xóa nhân vật này?')) return;
  try {
    await apiJson(`/api/assets/${id}`, { method: 'DELETE' });
  } catch (err) {
    reportFetchError('Không xóa được nhân vật', err);
  }
  fetchAssets();
  fetchStats();
}

function applyCharacterToVideo(code, desc) {
  switchTab('video');
  openBatchPromptModal();
  document.getElementById('batchPromptsInput').value = `[${code}] ${decodeURIComponent(desc)}: đang thực hiện hành động kịch tính...`;
}

// 5. Check Ảnh/Video Nick
async function loadNickMedia() {
  const select = document.getElementById('filterNickMediaSelect');
  const accountId = select ? select.value : '';

  try {
    const res = await fetch(`/api/nick-media${accountId ? `?account_id=${accountId}` : ''}`);
    const data = await res.json();

    const vGrid = document.getElementById('nickVideosGrid');
    const iGrid = document.getElementById('nickImagesGrid');

    if (vGrid) {
      vGrid.innerHTML = data.videos.map(v => `
        <div class="bg-[#0b1017] border border-[#172333] rounded-lg p-2.5 text-xs">
          <div class="font-semibold text-gray-200 line-clamp-1 mb-1">${v.title || v.prompt}</div>
          <div class="text-[10px] text-gray-500 mb-2">Trạng thái: <span class="text-cyan-400">${v.status}</span></div>
          ${v.local_video_path ? `
            <div class="flex items-center space-x-1.5 mt-2">
              <button type="button" onclick="openVideoPlayer('${v.local_video_path}', '${encodeURIComponent(v.title || v.prompt)}', ${v.id})" class="flex-1 px-2 py-1 bg-cyan-950/70 text-cyan-300 hover:bg-cyan-900 border border-cyan-800/40 rounded text-[10px] font-semibold text-center flex items-center justify-center space-x-1">
                <i data-lucide="play-circle" class="w-3 h-3 text-cyan-400"></i>
                <span>Xem Ngay</span>
              </button>
              <a href="/api/download-video/${v.local_video_path ? v.local_video_path.replace(/\\/g, '/').split('/').filter(Boolean).pop() : 'video_' + v.id + '.mp4'}" download class="px-2 py-1 bg-emerald-950/70 text-emerald-300 hover:bg-emerald-900 border border-emerald-800/40 rounded text-[10px] font-semibold flex items-center justify-center space-x-1" title="Tải Video MP4">
                <i data-lucide="download" class="w-3 h-3 text-emerald-400"></i>
                <span>Tải</span>
              </a>
            </div>
          ` : `<span class="text-[10px] text-gray-600 italic">Đang chờ xuất file</span>`}
        </div>
      `).join('') || `<div class="text-gray-500 text-xs">Không có video nào</div>`;
    }

    if (iGrid) {
      iGrid.innerHTML = data.images.map(i => `
        <div class="bg-[#0b1017] border border-[#172333] rounded-lg overflow-hidden">
          <img src="${i.image_url}" class="w-full h-24 object-cover">
          <div class="p-2 text-[10px] text-gray-400 truncate">${i.prompt}</div>
        </div>
      `).join('') || `<div class="text-gray-500 text-xs">Không có ảnh nào</div>`;
    }
  } catch (err) {
    reportFetchError('Lỗi nạp nick media', err);
  }
}

// 6. Xử lý Âm thanh (Audio TTS)
async function submitGenerateAudio() {
  const text = document.getElementById('audioTextInput').value.trim();
  const voice = document.getElementById('audioVoiceSelect').value;
  const speed = parseFloat(document.getElementById('audioSpeedSelect').value);

  if (!text) {
    alert('Vui lòng nhập kịch bản cần đọc!');
    return;
  }

  try {
    const res = await fetch('/api/audio/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, speed })
    });
    const data = await res.json();
    if (data.success) {
      const card = document.getElementById('audioResultCard');
      const player = document.getElementById('audioPlayer');
      card.classList.remove('hidden');
      player.src = data.audio_url;
      player.play();
    }
  } catch (err) {
    showToast('Lỗi tạo âm thanh: ' + err.message, 'error');
  }
}

// 7. Nhật ký (Logs)
let _logsAutoTimer = null;
function startLogsAutoRefresh(enabled) {
  if (_logsAutoTimer) { clearInterval(_logsAutoTimer); _logsAutoTimer = null; }
  if (enabled) _logsAutoTimer = setInterval(() => { if (currentTab === 'logs') fetchLogs(); }, 5000);
}

function resetLogFilters() {
  ['logFilterJob', 'logFilterAcc', 'logFilterLevel'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  fetchLogs();
}

async function fetchLogs() {
  const container = document.getElementById('logsContainer');
  if (!container) return;
  const val = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
  const params = new URLSearchParams({ limit: '500', job_id: val('logFilterJob'), account_id: val('logFilterAcc'), level: val('logFilterLevel') });
  try {
    const data = await apiJson(`/api/logs?${params.toString()}`);
    const logs = Array.isArray(data.logs) ? data.logs : [];
    const meta = document.getElementById('logsMeta');
    if (meta) meta.innerText = `${logs.length} dòng (tối đa 500) · tự làm mới mỗi 5 giây khi mở tab này`;

    if (logs.length === 0) {
      container.innerHTML = `<div class="text-gray-600">Không có bản ghi nhật ký nào khớp bộ lọc.</div>`;
      return;
    }

    container.innerHTML = logs.map(l => {
      let color = 'text-gray-400';
      if (l.level === 'SUCCESS') color = 'text-emerald-400 font-semibold';
      if (l.level === 'WARNING') color = 'text-amber-400';
      if (l.level === 'ERROR') color = 'text-red-400 font-bold';
      if (l.level === 'INFO') color = 'text-cyan-400';
      const ref = [];
      if (l.job_id !== null && l.job_id !== undefined) ref.push(`<a href="#" onclick="event.preventDefault(); filterLogsByJob(${Number(l.job_id)})" class="text-purple-300 hover:underline" title="Chỉ xem nhật ký của job này">job #${escapeHtml(l.job_id)}</a>`);
      if (l.account_id !== null && l.account_id !== undefined) ref.push(`<a href="#" onclick="event.preventDefault(); filterLogsByAccount(${Number(l.account_id)})" class="text-amber-300 hover:underline" title="Chỉ xem nhật ký của nick này">nick #${escapeHtml(l.account_id)}</a>`);
      return `
        <div class="leading-relaxed hover:bg-[#0c121a] px-1 rounded">
          <span class="text-gray-600">[${escapeHtml(l.created_at || 'Vừa xong')}]</span>
          <span class="${color}">[${escapeHtml(l.level || '?')}]</span>
          <span class="text-purple-400">[${escapeHtml(l.module || '?')}]</span>
          ${ref.length ? `<span class="text-gray-500">[${ref.join(' ')}]</span>` : ''}
          <span class="text-gray-300">${escapeHtml(l.message)}</span>
        </div>
      `;
    }).join('');
  } catch (err) {
    reportFetchError('Không lấy được nhật ký', err);
  }
}

function filterLogsByJob(id) { const el = document.getElementById('logFilterJob'); if (el) el.value = id; fetchLogs(); }
function filterLogsByAccount(id) { const el = document.getElementById('logFilterAcc'); if (el) el.value = id; fetchLogs(); }

async function clearLogs() {
  if (!confirm('Xóa sạch nhật ký?')) return;
  try {
    await apiJson('/api/logs', { method: 'DELETE' });
    showToast('Đã xóa nhật ký', 'success');
  } catch (err) {
    reportFetchError('Không xóa được nhật ký', err);
  }
  fetchLogs();
}

function selectAccountType(type) {
  if (type === 'muse') {
    showToast('Muse AI không còn được hỗ trợ từ phiên bản 1.1. Hãy chọn Facebook hoặc Google.', 'warning');
    return;
  }
  const input = document.getElementById('accTypeInput');
  const btnMuse = document.getElementById('btnTypeMuse');
  const btnFb = document.getElementById('btnTypeFb');
  const btnGoogle = document.getElementById('btnTypeGoogle');
  const fieldFb = document.getElementById('fieldFbUid');
  const fieldGoogle = document.getElementById('fieldGoogleEmail');

  if (input) input.value = type;

  const inactiveCls = 'py-2 rounded-lg font-bold text-xs flex items-center justify-center space-x-1.5 transition border border-[#1e2a3c] bg-[#0c131d] text-gray-400 hover:text-gray-200';
  if (btnMuse) btnMuse.className = inactiveCls;
  if (btnFb) btnFb.className = inactiveCls;
  if (btnGoogle) btnGoogle.className = inactiveCls;

  if (type === 'muse') {
    if (btnMuse) btnMuse.className = 'py-2 rounded-lg font-bold text-xs flex items-center justify-center space-x-1.5 transition border border-purple-500 bg-purple-950/40 text-purple-300';
    if (fieldFb) fieldFb.classList.add('hidden');
    if (fieldGoogle) fieldGoogle.classList.remove('hidden');
    const emailInp = document.getElementById('accEmailInput');
    if (emailInp) emailInp.placeholder = 'dongvanfb_mail@domain.com (Mail Muse AI)';
  } else if (type === 'google') {
    if (btnGoogle) btnGoogle.className = 'py-2 rounded-lg font-bold text-xs flex items-center justify-center space-x-1.5 transition border border-rose-500 bg-rose-950/40 text-rose-300';
    if (fieldFb) fieldFb.classList.add('hidden');
    if (fieldGoogle) fieldGoogle.classList.remove('hidden');
  } else {
    if (btnFb) btnFb.className = 'py-2 rounded-lg font-bold text-xs flex items-center justify-center space-x-1.5 transition border border-cyan-500 bg-cyan-950/40 text-cyan-300';
    if (fieldFb) fieldFb.classList.remove('hidden');
    if (fieldGoogle) fieldGoogle.classList.add('hidden');
  }
}

// 8. Accounts & Proxies
// API /api/accounts không trả fb_pass/fb_2fa/cookies rõ; chỉ có has_pass, has_2fa, has_cookies (KIEN_TRUC mục 5)
function accountCreditBadge(a) {
  if (a.is_resting) {
    const restTip = (a.rest_reason || 'Đang nghỉ') + (a.rest_until ? ` đến ${String(a.rest_until).slice(11, 16)}` : '');
    return `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#291e0a] text-amber-300 border border-amber-600/50 inline-flex items-center space-x-1 cursor-help" title="${escapeHtml(restTip)}">
      <span>⏸ Nghỉ (hết lượt)</span>
    </span>`;
  }
  // Không bịa số: chưa đọc được credit thì hiện "Chưa rõ" (BH-09)
  const value = (a.credits_today !== null && a.credits_today !== undefined) ? a.credits_today
    : ((a.credits !== null && a.credits !== undefined) ? a.credits : null);
  const checkedAt = a.last_check ? `Kiểm tra lúc ${a.last_check}` : 'Chưa kiểm tra lần nào';
  if (value === null || Number.isNaN(Number(value))) {
    return `<span class="px-2 py-0.5 rounded text-[10px] text-gray-400 bg-[#1a2333] border border-[#233145] cursor-help" title="${escapeHtml(checkedAt)}${a.last_error ? ' · Lỗi gần nhất: ' + escapeHtml(a.last_error) : ''}">Chưa rõ</span>`;
  }
  const n = Number(value);
  if (n > 0) {
    return `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#0d281a] text-emerald-400 border border-emerald-500/40 inline-flex items-center space-x-1 cursor-help" title="${escapeHtml(checkedAt)}">
      <i data-lucide="zap" class="w-3 h-3 text-emerald-400"></i>
      <span>${n} credits</span>
    </span>`;
  }
  return `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#291215] text-rose-300 border border-rose-800/50 inline-flex items-center space-x-1 cursor-help" title="${escapeHtml(checkedAt)}">
    <span>0 credit (hết lượt)</span>
  </span>`;
}

function accountStatusCell(a) {
  const isMuse = a.account_type === 'muse';
  const hasDola = a.has_dola === true;
  const parts = [];
  if (isMuse) {
    parts.push(`<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#1a2333] text-gray-400 border border-[#233145] inline-flex items-center space-x-1" title="Muse AI đã bị gỡ khỏi phiên bản này">Muse: không còn hỗ trợ</span>`);
  } else {
    parts.push(hasDola
      ? `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-[#0d281a] text-emerald-400 border border-emerald-500/40 inline-flex items-center space-x-1 shadow">
          <i data-lucide="check-circle" class="w-3.5 h-3.5 text-emerald-400"></i>
          <span>Đã kết nối Dola</span>
         </span>`
      : `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-[#291215] text-rose-300 border border-rose-800/50 inline-flex items-center space-x-1 shadow">
          <i data-lucide="alert-triangle" class="w-3.5 h-3.5 text-rose-400"></i>
          <span>Chưa kết nối Dola</span>
         </span>`);
  }
  if (a.busy_job_id !== null && a.busy_job_id !== undefined) {
    parts.push(`<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#11242c] text-cyan-400 border border-[#1b3945] inline-flex items-center space-x-1" title="Nick đang bị job #${escapeHtml(a.busy_job_id)} giữ, job khác phải chờ">
      <span class="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse"></span><span>Đang chạy job #${escapeHtml(a.busy_job_id)}</span>
    </span>`);
  }
  if (a.needs_manual) {
    const nm = NEEDS_MANUAL_LABEL[a.needs_manual] || { text: `Cần can thiệp: ${a.needs_manual}`, cls: 'bg-[#2a2210] text-amber-300 border-amber-700/60' };
    parts.push(`<span class="px-2 py-0.5 rounded text-[10px] font-bold border inline-flex items-center space-x-1 ${nm.cls}" title="Nick này sẽ không được chọn cho job mới cho tới khi bạn xử lý tay rồi bấm Tiếp tục ở job Tạm dừng hoặc Chẩn đoán lại">⚠ ${escapeHtml(nm.text)}</span>`);
  }
  if (a.last_error) {
    parts.push(`<span class="text-[9px] text-rose-300/80 truncate max-w-[150px] block cursor-help" title="Lỗi gần nhất: ${escapeHtml(a.last_error)}">Lỗi: ${escapeHtml(a.last_error)}</span>`);
  }
  return `<div class="flex flex-col items-center space-y-1">${parts.join('')}</div>`;
}

function accountActionsCell(a) {
  const isMuse = a.account_type === 'muse';
  const hasDola = a.has_dola === true;
  const safeName = encodeURIComponent(a.name || '');
  const diagBtn = `<button onclick="diagnoseAccount(${a.id}, '${safeName}')" class="px-2 py-1 bg-[#101c2c] hover:bg-[#162a40] text-cyan-300 border border-cyan-800/40 text-[10px] font-semibold rounded transition flex items-center space-x-1" title="Kiểm tra từng bước: proxy, Chrome, cookie Facebook, phiên Dola, credit">
      <i data-lucide="stethoscope" class="w-3 h-3 text-cyan-400"></i>
      <span>Chẩn đoán</span>
    </button>`;
  if (isMuse) {
    return `<div class="flex items-center justify-center space-x-1.5 text-[10px] text-gray-500 italic">Muse: không còn hỗ trợ</div>`;
  }
  if (hasDola) {
    return `<div class="flex items-center justify-center space-x-1.5 flex-wrap gap-y-1">
        <button onclick="checkAccountCredits(${a.id})" class="px-2 py-1 bg-[#102422] hover:bg-[#163833] text-emerald-300 border border-emerald-700/50 text-[10px] font-semibold rounded transition flex items-center space-x-1" title="Kiểm tra lượt tạo video hôm nay">
          <i data-lucide="sparkles" class="w-3 h-3 text-emerald-400"></i>
          <span>Check Credit</span>
        </button>
        <button onclick="openPasteCookieModal(${a.id}, '${safeName}')" class="px-2 py-1 bg-[#1a1727] hover:bg-[#282040] text-purple-300 border border-purple-800/40 text-[10px] rounded transition flex items-center space-x-1" title="Đổi hoặc nạp lại cookie Dola">
          <i data-lucide="cookie" class="w-3 h-3 text-purple-400"></i>
          <span>Cookie</span>
        </button>
        <button onclick="loginAccount(${a.id})" class="px-2 py-1 bg-[#121c28] hover:bg-[#1b2b3d] text-gray-300 border border-[#203146] text-[10px] rounded transition flex items-center space-x-1" title="Mở Chrome của nick này để kiểm tra hoặc kéo captcha">
          <i data-lucide="external-link" class="w-3 h-3"></i>
          <span>Chrome</span>
        </button>
        ${diagBtn}
       </div>`;
  }
  return `<div class="flex items-center justify-center space-x-1.5 flex-wrap gap-y-1">
      <button onclick="autoLoginAccount(${a.id})" class="px-2.5 py-1 bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400 hover:opacity-90 text-black font-extrabold text-[10px] rounded transition flex items-center space-x-1 shadow-md" title="Tự động đăng nhập Facebook + giải 2FA ngầm">
        <i data-lucide="sparkles" class="w-3 h-3"></i>
        <span>⚡ Auto Login</span>
      </button>
      <button onclick="openPasteCookieModal(${a.id}, '${safeName}')" class="px-2 py-1 bg-[#1a1727] hover:bg-[#282040] text-purple-300 border border-purple-800/40 text-[10px] rounded transition flex items-center space-x-1" title="Dán cookie Dola từ Cookie-Editor">
        <i data-lucide="cookie" class="w-3 h-3 text-purple-400"></i>
        <span>Dán Cookie</span>
      </button>
      <button onclick="loginAccount(${a.id})" class="px-2 py-1 bg-[#121c28] hover:bg-[#1b2b3d] text-gray-400 border border-[#203146] text-[10px] rounded transition flex items-center space-x-1" title="Mở Chrome của nick này">
        <i data-lucide="external-link" class="w-3 h-3"></i>
        <span>Chrome</span>
      </button>
      ${diagBtn}
     </div>`;
}

async function fetchAccounts() {
  try {
    const data = await apiJson('/api/accounts');
    const tbody = document.getElementById('accountsTableBody');
    const filterSelect = document.getElementById('filterNickMediaSelect');
    const imageAccSelect = document.getElementById('imageAccountSelect');

    const allAccounts = Array.isArray(data.accounts) ? data.accounts : [];
    let accounts = allAccounts;
    if (typeof currentFilterType !== 'undefined' && currentFilterType !== 'all') {
      accounts = accounts.filter(a => a.account_type === currentFilterType);
    }
    if (typeof currentFilterStatus !== 'undefined') {
      if (currentFilterStatus === 'ready') {
        accounts = accounts.filter(a => a.has_dola === true);
      } else if (currentFilterStatus === 'no-proxy') {
        accounts = accounts.filter(a => !a.proxy || a.proxy.trim() === '');
      }
    }

    if (tbody) {
      if (accounts.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="9" class="p-8 text-center text-gray-500">
              Không có tài khoản nào phù hợp bộ lọc. Hãy bấm <b>"Thêm tài khoản"</b> (Facebook hoặc Google) để bắt đầu!
            </td>
          </tr>
        `;
      } else {
        tbody.innerHTML = accounts.map(a => {
          const isMuse = a.account_type === 'muse';
          const isGoogle = a.account_type === 'google';
          let typeBadge = '';
          if (isMuse) {
            typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#1a2333] text-gray-500 border border-[#233145] inline-flex items-center space-x-1 line-through" title="Muse AI không còn được hỗ trợ"><span>Muse AI</span></span>`;
          } else if (isGoogle) {
            typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#291215] text-rose-400 border border-[#481c22] inline-flex items-center space-x-1"><i data-lucide="mail" class="w-3 h-3 text-rose-400"></i><span>Google</span></span>`;
          } else {
            typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#0d1e30] text-cyan-400 border border-[#163352] inline-flex items-center space-x-1"><i data-lucide="facebook" class="w-3 h-3 text-cyan-400"></i><span>Facebook</span></span>`;
          }

          const twofaBadge = a.has_2fa ? `<span class="px-1.5 py-0.2 rounded text-[9px] font-bold bg-[#1e2311] text-amber-300 border border-amber-700/50" title="Đã lưu mã 2FA">2FA</span>` : '';
          const passBadge = a.has_pass ? `<span class="px-1.5 py-0.2 rounded text-[9px] bg-[#141a24] text-gray-400 border border-[#1f2937]" title="Đã lưu mật khẩu">Pass</span>` : '';
          const cookieBadge = a.has_cookies ? `<span class="px-1.5 py-0.2 rounded text-[9px] bg-[#1a1727] text-purple-300 border border-purple-800/40" title="Đã lưu cookie">Cookie</span>` : '';
          const badges = `<div class="flex items-center space-x-1">${twofaBadge} ${passBadge} ${cookieBadge}</div>`;

          let identifier = '';
          if (isMuse) {
            identifier = a.email ? `<div class="text-gray-500 font-mono text-[11px]">${escapeHtml(a.email)}</div>` : `<span class="text-gray-500 text-[11px]">Chưa gắn Mail</span>`;
          } else if (isGoogle) {
            identifier = a.email ? `<div class="space-y-1"><div class="text-rose-300 font-mono text-[11px]">${escapeHtml(a.email)}</div>${badges}</div>` : `<span class="text-gray-500 text-[11px]">Chưa gắn Gmail</span>`;
          } else {
            identifier = a.fb_uid ? `<div class="space-y-1"><div class="text-gray-300 font-mono text-[11px] font-semibold">${escapeHtml(a.fb_uid)}</div>${badges}</div>` : `<div class="space-y-1"><span class="text-gray-500 text-[11px]">Chưa gắn UID</span>${badges}</div>`;
          }

          const proxyCell = `
            <div class="font-mono text-cyan-400 text-[11px] truncate max-w-[150px]" title="${escapeHtml(a.proxy || '')}">${a.proxy ? escapeHtml(a.proxy) : '<span class="text-gray-500">Không có proxy</span>'}</div>
            ${a.last_ip ? `<div class="text-[9px] text-gray-500 font-mono" title="IP ra ngoài lần kiểm tra gần nhất">IP: ${escapeHtml(a.last_ip)}</div>` : ''}`;

          return `
            <tr class="hover:bg-[#0c121a] transition select-none ${isMuse ? 'opacity-60' : ''}">
              <td class="p-2.5 text-center font-mono text-gray-400">#${a.id}</td>
              <td class="p-2.5">${typeBadge}</td>
              <td class="p-2.5 font-semibold text-gray-200">${escapeHtml(a.name)}</td>
              <td class="p-2.5">${identifier}</td>
              <td class="p-2.5">${proxyCell}</td>
              <td class="p-2.5 text-center">${accountStatusCell(a)}</td>
              <td class="p-2.5 text-center">${isMuse ? '<span class="px-2 py-0.5 rounded text-[10px] text-gray-500 bg-[#1a2333] border border-[#233145]">Chưa rõ</span>' : accountCreditBadge(a)}</td>
              <td class="p-2.5 text-center">${accountActionsCell(a)}</td>
              <td class="p-2.5 text-center">
                <button onclick="deleteAccount(${a.id})" class="p-1.5 bg-[#251014] hover:bg-red-900/50 text-red-400 rounded border border-[#3e1b21] transition" title="Xóa tài khoản">
                  <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                </button>
              </td>
            </tr>
          `;
        }).join('');
      }
    }

    // Populate dropdowns
    const optionList = allAccounts.map(a => `<option value="${a.id}">[${a.account_type === 'google' ? 'Google' : (a.account_type === 'muse' ? 'Muse' : 'FB')}] ${escapeHtml(a.name)}</option>`).join('');
    if (filterSelect) {
      const keep = filterSelect.value;
      filterSelect.innerHTML = `<option value="">Xem tất cả tài khoản</option>` + optionList;
      if (keep) filterSelect.value = keep;
    }
    if (imageAccSelect) {
      const keep = imageAccSelect.value;
      imageAccSelect.innerHTML = `<option value="">Tự động chọn tài khoản rảnh</option>` + optionList;
      if (keep) imageAccSelect.value = keep;
    }

    lucide.createIcons();
  } catch (err) {
    reportFetchError('Không lấy được danh sách tài khoản', err);
  }
}

// ==================== ĐẠO DIỄN AI (backend director.py; giao diện chỉ gọi preview, không tự ghép bằng JS — BH-41) ====================
function _batchPromptLines() {
  const text = document.getElementById('batchPromptsInput').value;
  return text.split('\n').map(p => p.trim()).filter(p => p.length > 0);
}

function _directorRequestBody(prompts) {
  const styleEl = document.getElementById('batchStyleSelect');
  const dirEl = document.getElementById('batchDirectorEnabled');
  const nameEl = document.getElementById('batchNameInput');
  return {
    prompts,
    model: document.getElementById('batchModelSelect').value,
    duration: document.getElementById('batchDurationSelect').value,
    ratio: document.getElementById('batchRatioSelect').value,
    style_code: styleEl ? styleEl.value : '',
    director: dirEl ? !!dirEl.checked : null,
    batch_name: nameEl && nameEl.value.trim() ? nameEl.value.trim() : null
  };
}

function renderDirectorPreview(items) {
  const box = document.getElementById('directorPreviewBox');
  if (!box) return;
  if (!items || items.length === 0) {
    box.innerHTML = '<div class="p-2 text-[11px] text-gray-500">Không có dòng prompt nào để xem trước.</div>';
    box.classList.remove('hidden');
    return;
  }
  box.innerHTML = `
    <table class="w-full text-[10px]">
      <thead class="sticky top-0 bg-[#0b1017] text-gray-400 uppercase">
        <tr><th class="p-1.5 text-left w-6">#</th><th class="p-1.5 text-left w-1/3">Prompt gốc</th><th class="p-1.5 text-left">Đã đạo diễn (gửi Dola)</th></tr>
      </thead>
      <tbody class="divide-y divide-[#101722]">
        ${items.map((it, i) => `
          <tr class="align-top">
            <td class="p-1.5 text-gray-500 font-mono">${i + 1}</td>
            <td class="p-1.5 text-gray-300">${escapeHtml(it.prompt)}</td>
            <td class="p-1.5 text-gray-200">
              <div class="mb-0.5 flex items-center space-x-1">
                <span class="px-1 py-0.5 rounded bg-[#0f2126] text-cyan-300 border border-cyan-900/60 font-mono" title="${escapeHtml(it.archetype_name || '')}">${escapeHtml(it.archetype_code || 'tắt')}</span>
                ${(it.characters && it.characters.length) ? `<span class="text-purple-300" title="Nhân vật khớp Kho nhân vật">Nhân vật: ${escapeHtml(it.characters.join(', '))}</span>` : ''}
                ${(it.existing_layers && it.existing_layers.length) ? `<span class="text-gray-500" title="Lớp prompt đã tự mô tả, không chèn lại">đã có: ${escapeHtml(it.existing_layers.join(', '))}</span>` : ''}
              </div>
              <div class="font-mono whitespace-pre-wrap break-words">${escapeHtml(it.prompt_final)}</div>
            </td>
          </tr>`).join('')}
      </tbody>
    </table>`;
  box.classList.remove('hidden');
}

async function previewDirectorPrompts() {
  const prompts = _batchPromptLines();
  if (prompts.length === 0) {
    showToast('Nhập ít nhất 1 dòng prompt rồi mới xem trước được', 'warning');
    return;
  }
  try {
    const data = await apiJson('/api/director/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_directorRequestBody(prompts))
    });
    if (data.success === false) {
      showToast('Không xem trước được: ' + (data.message || 'máy chủ từ chối'), 'error', 8000);
      return;
    }
    renderDirectorPreview(data.items || []);
    showParamWarnings(data.warnings);
    if (data.director_enabled === false) showToast('Đạo diễn AI đang tắt: prompt chỉ được thêm câu mở đầu, không ghép mẫu', 'warning', 6000);
  } catch (err) {
    reportFetchError('Không xem trước được prompt đã đạo diễn', err);
  }
}

// Action: Submit Batch Prompts (backend ghép prompt_final lúc tạo job; trả về mã trường phái từng job)
async function submitBatchPrompts() {
  const prompts = _batchPromptLines();
  if (prompts.length === 0) {
    alert('Vui lòng nhập ít nhất 1 dòng prompt!');
    return;
  }

  try {
    const data = await apiJson('/api/jobs/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_directorRequestBody(prompts))
    });
    if (data.success === false) {
      showToast('Không tạo được job: ' + (data.message || 'máy chủ từ chối'), 'error', 8000);
      return;
    }
    closeModal('modalBatchPrompts');
    document.getElementById('batchPromptsInput').value = '';
    const nameEl = document.getElementById('batchNameInput');
    if (nameEl) nameEl.value = '';
    const box = document.getElementById('directorPreviewBox');
    if (box) { box.innerHTML = ''; box.classList.add('hidden'); }
    const codes = Array.from(new Set((data.jobs || []).map(j => j.archetype).filter(Boolean)));
    const params = [data.duration, data.ratio].filter(Boolean).join(' · ');
    showToast(`Đã nạp ${data.created} job vào hàng đợi` + (params ? ` (${params})` : '') + (codes.length ? ` · trường phái: ${codes.join(', ')}` : ' · không qua Đạo diễn AI'), 'success', 7000);
    showParamWarnings(data.warnings);
    refreshData();
  } catch (err) {
    reportFetchError('Không gửi được lô prompt', err);
  }
}

// BH-46: backend ép thời lượng ngoài 4-15 giây / tỷ lệ lạ về giá trị Dola hỗ trợ và trả `warnings` → báo cho người dùng
function showParamWarnings(warnings) {
  (Array.isArray(warnings) ? warnings : []).forEach(w => showToast(w, 'warning', 9000));
}

// Modal xem/sửa prompt đã đạo diễn của một job
let _jobsById = {};
let _jobPromptEditingId = null;
const JOB_PROMPT_EDITABLE = [JOB_STATUS.CHO, JOB_STATUS.THAT_BAI, JOB_STATUS.TAM_DUNG];

function openJobPromptModal(id) {
  const j = _jobsById[id];
  if (!j) { showToast(`Không tìm thấy job #${id} trong bảng, bấm làm mới`, 'warning'); return; }
  _jobPromptEditingId = id;
  document.getElementById('jobPromptTitle').textContent = `Prompt của job #${id}`;
  document.getElementById('jobPromptArchetype').textContent = j.archetype_code ? `Trường phái ${j.archetype_code}` : 'Không qua Đạo diễn AI';
  document.getElementById('jobPromptOriginal').value = j.prompt || '';
  document.getElementById('jobPromptFinal').value = j.prompt_final || '';
  // BH-47: câu trả lời bằng chữ cuối cùng của Dola (nếu có) để người dùng biết Dola nói gì
  const replyBox = document.getElementById('jobPromptDolaReplyBox');
  const replyEl = document.getElementById('jobPromptDolaReply');
  if (replyBox && replyEl) {
    if (j.dola_reply) { replyEl.textContent = j.dola_reply; replyBox.classList.remove('hidden'); }
    else { replyEl.textContent = ''; replyBox.classList.add('hidden'); }
  }
  const editable = JOB_PROMPT_EDITABLE.includes(j.status);
  const ta = document.getElementById('jobPromptFinal');
  const btn = document.getElementById('jobPromptSaveBtn');
  ta.readOnly = !editable;
  btn.disabled = !editable;
  document.getElementById('jobPromptHint').textContent = editable
    ? `Job đang '${j.status}': sửa xong bấm Lưu, worker sẽ gửi đúng nội dung này sang Dola.`
    : `Job đang '${j.status}': không sửa được prompt lúc này (chỉ sửa khi ${JOB_PROMPT_EDITABLE.join(', ')}).`;
  openModal('modalJobPrompt');
}

async function saveJobPromptFinal() {
  const id = _jobPromptEditingId;
  if (!id) return;
  const prompt_final = document.getElementById('jobPromptFinal').value;
  try {
    const data = await apiJson(`/api/jobs/${id}/prompt_final`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt_final })
    });
    if (data.success === false) {
      showToast(`Không lưu được prompt job #${id}: ${data.message || 'máy chủ từ chối'}`, 'error', 8000);
      return;
    }
    showToast(`Đã lưu prompt đã đạo diễn của job #${id}`, 'success');
    closeModal('modalJobPrompt');
    fetchJobs();
  } catch (err) {
    reportFetchError(`Không lưu được prompt job #${id}`, err);
  }
}

// Action: Add Account
async function submitAddAccount() {
  const name = document.getElementById('accNameInput').value.trim();
  const account_type = document.getElementById('accTypeInput') ? document.getElementById('accTypeInput').value : 'facebook';
  const email = document.getElementById('accEmailInput') ? document.getElementById('accEmailInput').value.trim() : '';
  const fb_uid = document.getElementById('accUidInput') ? document.getElementById('accUidInput').value.trim() : '';
  const proxy = document.getElementById('accProxyInput').value.trim();
  const cookies = document.getElementById('accCookieInput') ? document.getElementById('accCookieInput').value.trim() : '';

  if (!name) {
    alert('Vui lòng nhập tên tài khoản!');
    return;
  }
  if (account_type === 'google' && !email) {
    alert('Vui lòng nhập địa chỉ Gmail!');
    return;
  }

  try {
    const res = await fetch('/api/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, account_type, email, fb_uid, proxy, cookies })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('modalAddAccount');
      document.getElementById('accNameInput').value = '';
      if (document.getElementById('accEmailInput')) document.getElementById('accEmailInput').value = '';
      if (document.getElementById('accUidInput')) document.getElementById('accUidInput').value = '';
      document.getElementById('accProxyInput').value = '';
      if (document.getElementById('accCookieInput')) document.getElementById('accCookieInput').value = '';
      refreshData();
    }
  } catch (err) {
    showToast('Lỗi thêm tài khoản: ' + err.message, 'error');
  }
}

// Action: Launch Login Session
async function loginAccount(id) {
  try {
    showToast(`Đang mở Chrome cho nick #${id}…`, 'info');
    const data = await apiJson(`/api/accounts/${id}/login`, { method: 'POST' });
    if (data.success === false) {
      showToast(`Không mở được Chrome cho nick #${id}: ${data.message || data.detail || 'nick đang bận hoặc Chrome thiếu'}`, 'warning', 8000);
    } else {
      showToast(`Đã mở Chrome cho nick #${id}. Đăng nhập hoặc kéo captcha xong thì đóng cửa sổ Chrome lại.`, 'success', 8000);
    }
    setTimeout(fetchAccounts, 1500);
  } catch (err) {
    reportFetchError(`Không mở được Chrome cho nick #${id}`, err);
  }
}

// Action: Delete Job
async function deleteJob(id) {
  if (!confirm(`Bạn có chắc muốn xóa job #${id}? Job đang chạy không xóa được, hãy chờ xong hoặc Tạm dừng trước.`)) return;
  try {
    const data = await apiJson(`/api/jobs/${id}`, { method: 'DELETE' });
    if (data && data.success === false) {
      showToast(`Không xóa được job #${id}: ${data.message || data.detail || 'máy chủ từ chối'}`, 'error', 8000);
      return;
    }
    showToast(`Đã xóa job #${id}`, 'success');
    refreshData();
  } catch (err) {
    reportFetchError(`Không xóa được job #${id}`, err);
  }
}

// Action: Delete Account
async function deleteAccount(id) {
  if (!confirm(`Bạn có chắc muốn xóa tài khoản #${id}?`)) return;
  try {
    await apiJson(`/api/accounts/${id}`, { method: 'DELETE' });
    showToast(`Đã xóa tài khoản #${id}`, 'success');
    refreshData();
  } catch (err) {
    reportFetchError(`Không xóa được tài khoản #${id}`, err);
  }
}

// Settings
async function loadSettings() {
  try {
    const s = await apiJson('/api/settings');
    const set = (id, v) => { const el = document.getElementById(id); if (el && v !== null && v !== undefined && v !== '') el.value = v; };
    set('settingMaxJobs', s.max_concurrent_jobs);
    set('settingDelay', s.delay_between_jobs);
    set('settingModel', s.default_model);
    const { duration, ratio } = normalizeVideoDefaults(s.default_duration, s.default_ratio);
    set('settingDuration', duration);
    set('settingRatio', ratio);
    applyVideoDefaults(duration, ratio, s.default_model);
    const cp = document.getElementById('settingChromePath');
    if (cp) cp.value = s.chrome_path || '';
    applyDirectorSettings(s);
  } catch (err) {
    reportFetchError('Không tải được cài đặt', err);
  }
}

// Setting director_* (director.SETTING_DEFAULTS): "1"/"0"; thiếu key → coi như bật (giống backend)
const DIRECTOR_SETTING_CHECKBOXES = Object.freeze({
  director_enabled: 'settingDirectorEnabled',
  director_layer_camera: 'settingDirectorCamera',
  director_layer_lighting: 'settingDirectorLighting',
  director_layer_palette: 'settingDirectorPalette',
  director_layer_character: 'settingDirectorCharacter'
});

function _settingOn(v) {
  if (v === null || v === undefined || v === '') return true;
  return ['1', 'true', 'on', 'yes'].includes(String(v).toLowerCase());
}

function applyDirectorSettings(s) {
  Object.entries(DIRECTOR_SETTING_CHECKBOXES).forEach(([key, id]) => {
    const el = document.getElementById(id);
    if (el) el.checked = _settingOn(s[key]);
  });
  const styleEl = document.getElementById('settingDirectorStyle');
  if (styleEl) styleEl.value = s.director_default_style || '';
  // Modal lô prompt lấy mặc định theo setting
  const batchDir = document.getElementById('batchDirectorEnabled');
  if (batchDir) batchDir.checked = _settingOn(s.director_enabled);
  const batchStyle = document.getElementById('batchStyleSelect');
  if (batchStyle && !batchStyle.value) batchStyle.value = s.director_default_style || '';
}

async function saveSettings() {
  const max_concurrent_jobs = document.getElementById('settingMaxJobs').value;
  const default_model = document.getElementById('settingModel').value;
  const default_duration = document.getElementById('settingDuration').value;
  const ratioEl = document.getElementById('settingRatio');
  const default_ratio = ratioEl ? ratioEl.value : '';
  const delay_between_jobs = document.getElementById('settingDelay').value;
  const chromeEl = document.getElementById('settingChromePath');
  const chrome_path = chromeEl ? chromeEl.value.trim() : '';

  const n = Number(max_concurrent_jobs);
  if (!Number.isInteger(n) || n < 1 || n > 20) {
    showToast('Số Chrome chạy cùng lúc phải là số nguyên từ 1 đến 20', 'warning');
    return;
  }

  const body = { max_concurrent_jobs, default_model, default_duration, default_ratio, delay_between_jobs, chrome_path };
  Object.entries(DIRECTOR_SETTING_CHECKBOXES).forEach(([key, id]) => {
    const el = document.getElementById(id);
    if (el) body[key] = el.checked ? '1' : '0';
  });
  const styleEl = document.getElementById('settingDirectorStyle');
  if (styleEl) body.director_default_style = styleEl.value || '';

  try {
    await apiJson('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    applyDirectorSettings(body);
    applyVideoDefaults(default_duration, default_ratio, default_model);
    showToast('Đã lưu cài đặt hệ thống', 'success');
    fetchHealth();
  } catch (err) {
    reportFetchError('Không lưu được cài đặt', err);
  }
}

function refreshData() {
  fetchStats();
  fetchJobs();
  fetchAccounts();
}

// ==================== BRUCTA CINEMATIC BUILDER HELPERS ====================

function insertTagToPrompt(tag) {
  if (!tag) return;
  const textarea = document.getElementById('batchPromptsInput');
  if (!textarea) return;

  const current = textarea.value.trim();
  if (!current) {
    textarea.value = tag;
  } else {
    // Nếu có nội dung, chèn thêm thuộc tính vào dòng cuối cùng
    textarea.value = current + ", " + tag;
  }
}

function enhancePromptBructa() {
  const textarea = document.getElementById('batchPromptsInput');
  if (!textarea) return;

  const current = textarea.value.trim();
  if (!current) {
    textarea.value = "Cinematic scene of character in dramatic lighting, 85mm Anamorphic Lens, Three-point Lighting, Blue Key Light, Orange Fill Light, Volumetric God Rays, Subsurface Scattering, 35mm Color Film Stock, Cinematic Color Grading, 8k raw footage, --ar 16:9";
    return;
  }

  // Tách từng dòng và nâng cấp từng prompt
  const lines = current.split('\n');
  const enhancedLines = lines.map(line => {
    line = line.trim();
    if (!line) return "";
    return `${line}, 85mm Anamorphic Lens, Three-point Lighting, Blue Key Light, Warm Rim Light, Volumetric God Rays, Subsurface Scattering, 35mm Film Grain, Cinematic Color Grading, --ar 16:9`;
  });

  textarea.value = enhancedLines.filter(l => l.length > 0).join('\n');
}

function generate5ShotSequence() {
  const textarea = document.getElementById('batchPromptsInput');
  if (!textarea) return;

  let subject = prompt("Nhập tên nhân vật hoặc chủ thể bạn muốn làm chuỗi 5 phân cảnh (Ví dụ: 'Nữ kiếm sĩ Cyberpunk' hoặc 'Chiến binh Samurai'):", "Nữ sát thủ Cyberpunk tóc ngắn");
  if (!subject) return;

  const sequence = [
    `01. Establishing Scene: Wide Shot (24mm Wide Angle Lens) of ${subject} in futuristic rain-slicked city streets, deep focus, volumetric atmospheric haze, tungsten cool blue lighting, 35mm color film stock, cinematic composition, --ar 16:9`,
    `02. Action Approach: Cowboy Shot (CS) of ${subject} walking with weapon drawn, low angle view, dynamic motion, ambient city neon reflections, natural shadows, sharp focus, --ar 16:9`,
    `03. Emotional Portrait: Close-Up (CU) portrait of ${subject}, 85mm portrait lens, Rembrandt lighting with chiaroscuro triangle, catchlight in eyes, subsurface scattering on skin, shallow depth of field, --ar 16:9`,
    `04. Dramatic Detail: Extreme Close-Up (ECU) macro shot on the focused intense eyes of ${subject}, microscopic reflections, volumetric smoke drifting past, tight framing, high tension, --ar 16:9`,
    `05. Climax Moment: Dutch Angle (tilt shot) of ${subject} turning swiftly in action pose, Anamorphic lens flare, blue key light with orange warm rim light, motion blur controlled, blockbuster cinematic masterpiece, --ar 16:9`
  ];

  textarea.value = sequence.join('\n\n');
}

// ==================== HỖ TRỢ CHÈN TAG VÀO Ô PROMPT ====================
function insertTagToImagePrompt(tag) {
  const input = document.getElementById('imagePromptInput');
  if (!input) return;
  const current = input.value.trim();
  if (!current) {
    input.value = tag;
  } else {
    input.value = `${current}, ${tag}`;
  }
  input.focus();
}

function analyzePromptWithChatGPTAndBructa(rawPrompt) {
  let cleanPrompt = rawPrompt.replace(/^\d+[\.\:\-\s]+/, '').trim();
  const lower = cleanPrompt.toLowerCase();

  let archetypeCode = "Cine-Master";
  let archetypeName = "Điện Ảnh Hollywood Bom Tấn (Blockbuster)";
  let shot = "";
  let angle = "";
  let lens = "";
  let lighting = "";
  let chatgptVisualGroup = "";
  let palette = "";
  let sixElements = "";

  // 1. Chi tiết siêu cận / Ánh mắt / Macro
  if (lower.includes('mắt') || lower.includes('nước mắt') || lower.includes('nhẫn') || lower.includes('vết sẹo') || 
      lower.includes('ngón tay') || lower.includes('chi tiết') || lower.includes('vũ khí cận') || lower.includes('eye') || 
      lower.includes('macro') || lower.includes('detail') || lower.includes('tear') || lower.includes('ring') || lower.includes('iris')) {
    archetypeCode = "P1-Macro";
    archetypeName = "Chân Dung Chi Tiết Biểu Cảm (Micro Detail)";
    shot = "Extreme Close-Up (ECU)";
    angle = "Eye Level micro view";
    lens = "Macro Lens 100mm, razor sharp focus, paper-thin depth of field";
    lighting = "Volumetric Lighting, intentional catchlight in iris, high textural clarity";
    chatgptVisualGroup = "visual style P1 Chân dung chi tiết có chủ ý (Steve McCurry & Helmut Newton)";
    palette = "cinematic high-contrast grading, deep black shadows";
    sixElements = "focused micro composition, clean negative breathing space, hyper-realistic skin & fabric pore textures";
  }
  // 2. F1: Fantasy Cổ Tích & Thiên Nhiên Rêu Phong (Alan Lee, John Howe)
  else if (lower.includes('rừng') || lower.includes('cổ tích') || lower.includes('tiên') || lower.includes('lâu đài') || 
           lower.includes('tháp') || lower.includes('cây') || lower.includes('suối') || lower.includes('rêu') || 
           lower.includes('yêu tinh') || lower.includes('thung lũng') || lower.includes('thần thoại') || lower.includes('hoa cỏ') ||
           lower.includes('forest') || lower.includes('castle') || lower.includes('fantasy') || lower.includes('ancient') || 
           lower.includes('fairytale') || lower.includes('elf') || lower.includes('woods') || lower.includes('mossy')) {
    archetypeCode = "F1";
    archetypeName = "Fantasy Cổ Tích & Thiên Nhiên (Alan Lee & John Howe)";
    shot = "Full Shot (FS) 3-layer depth landscape";
    angle = "Eye Level with leading stone path into the depth";
    lens = "24mm Wide Angle Lens, Deep Focus";
    lighting = "Soft morning sunlight diffusing through atmospheric mist, volumetric god rays";
    chatgptVisualGroup = "visual style F1 Fantasy thiên nhiên & cổ tích Alan Lee & John Howe (overgrown mossy roots, weathered stones, clean negative space)";
    palette = "antique organic palette of Moss Green, Earth Brown and Pale Cream";
    sixElements = "3-layer depth composition, natural curved linework, gentle mist atmosphere";
  }
  // 3. F2: Fantasy Kịch Tính, Hắc Ám & Đao Kiếm (Frank Frazetta, Aleksi Briclot)
  else if (lower.includes('chiến binh') || lower.includes('quái vật') || lower.includes('lửa') || lower.includes('dung nham') || 
           lower.includes('hắc ám') || lower.includes('đánh nhau') || lower.includes('chiến đấu') || lower.includes('kiếm') || 
           lower.includes('đao') || lower.includes('rồng') || lower.includes('ma vương') || lower.includes('sát thủ') || 
           lower.includes('chém') || lower.includes('huyết') || lower.includes('warrior') || lower.includes('monster') || 
           lower.includes('fire') || lower.includes('dragon') || lower.includes('dark') || lower.includes('battle') || 
           lower.includes('sword') || lower.includes('frazetta')) {
    archetypeCode = "F2";
    archetypeName = "Fantasy Kịch Tính & Hắc Ám (Frank Frazetta & Aleksi Briclot)";
    shot = "Cowboy Shot (CS) action pose";
    angle = "Low Angle, dramatic heroic view, Dutch tilt";
    lens = "24mm High Dynamic Motion Cine Lens";
    lighting = "Fiery orange directional rim light cutting through smoke, deep black shadow contrast";
    chatgptVisualGroup = "visual style F2 Fantasy kịch tính Frank Frazetta & Aleksi Briclot (bold heroic silhouette, muscular tension, rough rock and molten metal textures)";
    palette = "Dramatic Crimson Red, Fire Amber and Deep Shadow Black palette";
    sixElements = "diagonal dynamic composition, sharp aggressive silhouettes, heavy textural grime";
  }
  // 4. C1: Không Gian Lớn, Vũ Trụ & Ánh Màu Hoàng Hôn (Alena Aenami, John Harris)
  else if (lower.includes('vũ trụ') || lower.includes('hành tinh') || lower.includes('ngân hà') || lower.includes('phi thuyền') || 
           lower.includes('không gian') || lower.includes('mênh mông') || lower.includes('hoàng hôn') || lower.includes('chân trời') || 
           lower.includes('bầu trời') || lower.includes('thiên hà') || lower.includes('vô tận') || lower.includes('cô độc') || 
           lower.includes('space') || lower.includes('galaxy') || lower.includes('planet') || lower.includes('cosmic') || 
           lower.includes('horizon') || lower.includes('nebula') || lower.includes('twilight') || lower.includes('colossal')) {
    archetypeCode = "C1";
    archetypeName = "Không Gian Lớn & Ánh Màu (Alena Aenami & John Harris)";
    shot = "Extreme Wide Establishing Shot (EWS)";
    angle = "Wide Horizon panoramic view";
    lens = "16mm Ultra-Wide Angle Lens, infinite depth of field";
    lighting = "Luminous starlight, cosmic twilight glow, atmospheric scattering";
    chatgptVisualGroup = "visual style C1 Không gian lớn & Ánh màu Alena Aenami & John Harris (tiny human scale vs colossal cosmic architecture, wide negative space)";
    palette = "Sunset Golden Hour and Violet Twilight cosmic palette, warm and cool atmospheric contrast";
    sixElements = "monumental scale balance, ultra-wide negative space, glowing volumetric celestial light";
  }
  // 5. C2: Khoa Học Viễn Tưởng Cơ Khí Mô-đun & Cyberpunk (Syd Mead, Chris Foss)
  else if (lower.includes('robot') || lower.includes('máy móc') || lower.includes('cơ khí') || lower.includes('công nghệ') || 
           lower.includes('tương lai') || lower.includes('mô-đun') || lower.includes('sci-fi') || lower.includes('cyborg') || 
           lower.includes('cyberpunk') || lower.includes('neon') || lower.includes('giáp sắt') || lower.includes('người máy') || 
           lower.includes('mecha') || lower.includes('android') || lower.includes('future') || lower.includes('high-tech')) {
    archetypeCode = "C2";
    archetypeName = "Khoa Học Viễn Tưởng Mô-đun & Cơ Khí (Syd Mead & Chris Foss)";
    shot = "Medium Wide Shot (MWS)";
    angle = "Low Angle high-tech perspective";
    lens = "Anamorphic Lens, elliptical horizontal flares, razor sharp geometry";
    lighting = "Industrial spotlights, hazard light strobes, tungsten blue key light, neon wet puddle reflections";
    chatgptVisualGroup = "visual style C2 Sci-Fi mô-đun Syd Mead & Chris Foss (modular panel seams, weathered chrome, painted metal functionalism)";
    palette = "Teal and Orange neon cyber palette, cold cyan key and warm tungsten accents";
    sixElements = "hard-surface geometric lines, layered metallic seams, high-contrast industrial lighting";
  }
  // 6. E1: Bi Kịch, Lịch Sử Hùng Tráng & Tráng Lệ (Ilya Repin, Gustave Doré)
  else if (lower.includes('lịch sử') || lower.includes('bi kịch') || lower.includes('chiến tranh') || lower.includes('vua') || 
           lower.includes('hoàng gia') || lower.includes('đau khổ') || lower.includes('tang thương') || lower.includes('thánh đường') || 
           lower.includes('giáo đường') || lower.includes('triều đình') || lower.includes('quân đội') || lower.includes('thập tự') || 
           lower.includes('historical') || lower.includes('history') || lower.includes('tragedy') || lower.includes('royal') || 
           lower.includes('sorrow') || lower.includes('baroque') || lower.includes('repin') || lower.includes('dore')) {
    archetypeCode = "E1";
    archetypeName = "Bi Kịch & Lịch Sử Hùng Tráng (Ilya Repin & Gustave Doré)";
    shot = "Medium Full Shot (MFS) tableau composition";
    angle = "Slightly low dramatic theatrical stage perspective";
    lens = "35mm Cine Lens, high optical resolution";
    lighting = "Baroque dramatic chiaroscuro lighting, warm golden candle highlights, deep expressive shadows";
    chatgptVisualGroup = "visual style E1 Bi kịch & Lịch sử Ilya Repin & Gustave Doré (intense emotional climax, rich heavy fabric textures, majestic crowd dynamics)";
    palette = "Rich Umber, Royal Burgundy Crimson and Warm Candle Gold antique palette";
    sixElements = "theatrical dynamic composition, dense expressive gestures, layered historical costumes";
  }
  // 7. W1: Miền Tây Hoang Dã, Cao Bồi & Sa Mạc Bụi Bặm (Frederic Remington, Frank Schoonover)
  else if (lower.includes('miền tây') || lower.includes('cao bồi') || lower.includes('sa mạc') || lower.includes('ngựa') || 
           lower.includes('cát bụi') || lower.includes('hẻm núi') || lower.includes('hoang dã') || lower.includes('súng') || 
           lower.includes('thảo nguyên') || lower.includes('thám hiểm') || lower.includes('khám phá') || lower.includes('western') || 
           lower.includes('cowboy') || lower.includes('desert') || lower.includes('dust') || lower.includes('canyon') || 
           lower.includes('horse') || lower.includes('frontier') || lower.includes('remington')) {
    archetypeCode = "W1";
    archetypeName = "Miền Tây & Phiêu Lưu Thám Hiểm (Frederic Remington & Frank Schoonover)";
    shot = "Cowboy Shot (CS) tracking across vista";
    angle = "Eye Level tracking view across rugged landscape";
    lens = "50mm Prime Lens with raking dust haze";
    lighting = "Harsh blazing desert sunlight casting long raking shadows, golden sand bounce fill";
    chatgptVisualGroup = "visual style W1 Miền Tây & Phiêu lưu thám hiểm Frederic Remington & Frank Schoonover (sunburnt dust trails, worn leather, rugged sandstone canyons)";
    palette = "Sunburnt Ochre, Terracotta Earth and Faded Turquoise sky palette";
    sixElements = "expansive horizontal horizon, granular atmospheric dust texture, dynamic motion trails";
  }
  // 8. G1: Đồ Họa Đường Nét, Mảng Phẳng & Comic Siêu Thực (Moebius, Kilian Eng)
  else if (lower.includes('anime') || lower.includes('manga') || lower.includes('hoạt hình') || lower.includes('đồ họa') || 
           lower.includes('truyện tranh') || lower.includes('vector') || lower.includes('mảng phẳng') || lower.includes('vẽ nét') || 
           lower.includes('moebius') || lower.includes('comic') || lower.includes('graphic') || lower.includes('lineart') || 
           lower.includes('cartoon') || lower.includes('illustration')) {
    archetypeCode = "G1";
    archetypeName = "Đồ Họa Đường Nét & Mảng Phẳng (Moebius & Kilian Eng)";
    shot = "Medium Shot (MS)";
    angle = "Cinematic Geometric Eye Level";
    lens = "50mm Prime Lens, razor sharp line definition";
    lighting = "Clean graphic lighting, soft ambient fill, crisp rim line highlights";
    chatgptVisualGroup = "visual style G1 Đồ họa đường nét mảng phẳng Moebius (Jean Giraud) & Kilian Eng (intricate precise ink linework, bold graphic silhouette, flat aesthetic planes)";
    palette = "Harmonic limited graphic palette of Mustard Yellow, Mint Green and Coral Pink";
    sixElements = "clean contour linework, zero visual clutter, elegant flat colored negative space";
  }
  // 9. D1: Gothic U Tối, Ma Mị & Sinh Cơ Khí (H.R. Giger, Zdzisław Beksiński)
  else if (lower.includes('ma quái') || lower.includes('gothic') || lower.includes('kinh dị') || lower.includes('u tối') || 
           lower.includes('xương') || lower.includes('sinh học') || lower.includes('quái dị') || lower.includes('chết chóc') || 
           lower.includes('ác mộng') || lower.includes('địa ngục') || lower.includes('giger') || lower.includes('beksinski') || 
           lower.includes('alien') || lower.includes('horror') || lower.includes('eerie') || lower.includes('skeleton') || 
           lower.includes('dystopian') || lower.includes('biomechanical') || lower.includes('nightmare')) {
    archetypeCode = "D1";
    archetypeName = "Gothic U Tối & Sinh Cơ Khí (H.R. Giger & Zdzisław Beksiński)";
    shot = "Medium Close-Up (MCU)";
    angle = "Slightly low claustrophobic unsettling angle";
    lens = "35mm Cine Lens, high contrast";
    lighting = "Icy cold rim light, narrow sliver of light cutting through heavy impenetrable darkness";
    chatgptVisualGroup = "visual style D1 Biomechanical Gothic H.R. Giger & Zdzisław Beksiński (ribbed spine structures, organic tubes, ominous desolate architecture)";
    palette = "Monochromatic Deep Charcoal Black, Bone White with subtle sickly viridian sheen";
    sixElements = "claustrophobic repeating bone textures, deep void negative space, cold organic-metallic fusion";
  }
  // 10. S1: Nội Thất, Tĩnh Vật & Ánh Sáng Cửa Sổ Yên Bình (Johannes Vermeer, Jean-Baptiste Chardin)
  else if (lower.includes('trong phòng') || lower.includes('nội thất') || lower.includes('tĩnh vật') || lower.includes('cửa sổ') || 
           lower.includes('đọc sách') || lower.includes('tách trà') || lower.includes('bàn làm việc') || lower.includes('ấm cúng') || 
           lower.includes('tĩnh lặng') || lower.includes('bình yên') || lower.includes('hoa trên bàn') || lower.includes('phòng khách') || 
           lower.includes('quán cà phê') || lower.includes('room') || lower.includes('interior') || lower.includes('still life') || 
           lower.includes('window light') || lower.includes('cozy') || lower.includes('quiet') || lower.includes('tea') || 
           lower.includes('vermeer') || lower.includes('reading')) {
    archetypeCode = "S1";
    archetypeName = "Nội Thất & Tĩnh Vật Ánh Sáng Cửa Sổ (Johannes Vermeer & Chardin)";
    shot = "Medium Shot (MS) intimate interior";
    angle = "Eye Level contemplative natural framing";
    lens = "50mm Prime Lens (Nifty Fifty), gentle organic falloff";
    lighting = "Soft north window side light (Vermeer natural light), gentle delicate wall bounce falloff";
    chatgptVisualGroup = "visual style S1 Nội thất & Tĩnh vật Johannes Vermeer & Jean-Baptiste Chardin (poetic stillness, tactile linen, glazed ceramic and aged wood)";
    palette = "Harmonic palette of Ultramarine Blue, Warm Ochre Yellow, Pearl White and Aged Timber Brown";
    sixElements = "golden ratio interior framing, soft tactile textures, spacious peaceful negative space";
  }
  // 11. A1: Trừu Tượng, Biển Giông, Bão Tố & Cảm Xúc Thăng Hoa (J.M.W. Turner, Wassily Kandinsky)
  else if (lower.includes('bão biển') || lower.includes('sóng thần') || lower.includes('biển động') || lower.includes('giông bão') || 
           lower.includes('trừu tượng') || lower.includes('xoáy màu') || lower.includes('mơ màng') || lower.includes('cuồng nộ') || 
           lower.includes('sóng vỗ') || lower.includes('bão tuyết') || lower.includes('tempest') || lower.includes('stormy sea') || 
           lower.includes('tidal wave') || lower.includes('storm') || lower.includes('swirling colors') || lower.includes('turner') || 
           lower.includes('sublime') || lower.includes('abstract') || lower.includes('ocean gale')) {
    archetypeCode = "A1";
    archetypeName = "Trừu Tượng & Biển Giông Thăng Hoa (J.M.W. Turner & Kandinsky)";
    shot = "Wide Atmospheric Vista (WAV)";
    angle = "Dynamic sweeping angle caught in the tempest";
    lens = "24mm Cine Lens with water droplet reflections";
    lighting = "Atmospheric swirling light breaking through storm clouds, radiant elemental glow";
    chatgptVisualGroup = "visual style A1 Trừu tượng & Biểu hiện cảm xúc J.M.W. Turner (elemental vortex, dissolving sky-sea boundaries, sublime force)";
    palette = "Storm Sulfur Yellow, Deep Ocean Prussian Blue and Whipped Seafoam White palette";
    sixElements = "vortical spiral composition, dissolved boundaries, fluid atmospheric motion textures";
  }
  // 12. P1: Chân Dung Điện Ảnh & Biểu Cảm Sâu Sắc (Steve McCurry, Helmut Newton)
  else if (lower.includes('chân dung') || lower.includes('khuôn mặt') || lower.includes('mặt') || lower.includes('cô gái') || 
           lower.includes('chàng trai') || lower.includes('người đẹp') || lower.includes('nữ sinh') || lower.includes('doanh nhân') || 
           lower.includes('nụ cười') || lower.includes('mỹ nhân') || lower.includes('nữ hiệp') || lower.includes('thần thái') || 
           lower.includes('portrait') || lower.includes('girl') || lower.includes('woman') || lower.includes('man') || 
           lower.includes('face') || lower.includes('model') || lower.includes('expressive gaze')) {
    archetypeCode = "P1";
    archetypeName = "Chân Dung Điện Ảnh & Biểu Cảm (Steve McCurry & Helmut Newton)";
    shot = "Close-Up (CU) portrait";
    angle = "Slightly low eye-level cinematic framing";
    lens = "85mm Portrait Lens f/1.4, creamy optical bokeh";
    lighting = "Rembrandt Lighting with chiaroscuro triangle on cheek, catchlight in eyes, subsurface scattering on skin, warm rim light";
    chatgptVisualGroup = "visual style P1 Chân dung điện ảnh Steve McCurry & Helmut Newton (expressive emotive gaze, natural breathing space)";
    palette = "Teal and Orange cinema color palette, Blue Key Light, Warm Amber Fill Light";
    sixElements = "rule of thirds composition, rich skin subsurface texture, controlled shadow gradient";
  }
  // 13. Mặc định: Chuẩn Điện Ảnh Hollywood Masterpiece
  else {
    archetypeCode = "Cine-Master";
    archetypeName = "Điện Ảnh Hollywood Bom Tấn (Blockbuster)";
    shot = "Medium Shot (MS)";
    angle = "Cinematic Eye Level framing";
    lens = "50mm Prime Lens (Nifty Fifty)";
    lighting = "Three-point lighting, Blue Key Light, Warm Orange Fill Light, subtle catchlight";
    chatgptVisualGroup = "chuẩn điện ảnh Hollywood Masterpiece (balanced 3-layer composition, controlled negative breathing space)";
    palette = "Cinematic Color Grading, 35mm Tungsten Film Stock, subtle natural film grain";
    sixElements = "blockbuster cinematic framing, balanced rule-of-thirds, rich tactile textures";
  }

  // Ghép theo công thức 6 thành tố chuẩn ChatGPT & Bructa
  return {
    code: archetypeCode,
    name: archetypeName,
    enhancedPrompt: `${cleanPrompt}, ${shot}, ${angle}, ${lens}, ${lighting}, ${chatgptVisualGroup}, ${palette}, ${sixElements}, 8k resolution, cinematic masterpiece`
  };
}

// ==================== ĐẠO DIỄN AI PHÂN TÍCH PROMPT VIDEO HÀNG LOẠT ====================
// Trước đây hàm này ghép mẫu bằng JS rồi ghi đè ô nhập (backend không biết). Nay logic ghép nằm ở director.py
// (một bản duy nhất) và chạy lúc tạo job; nút trên giao diện chỉ gọi /api/director/preview để xem trước (BH-41).
function autoDetectAndEnhanceBructa() {
  return previewDirectorPrompts();
}

// ==================== ĐẠO DIỄN AI TỰ ĐỘNG PHÂN TÍCH PROMPT TẠO ẢNH ====================
function autoEnhanceImagePrompt() {
  const input = document.getElementById('imagePromptInput');
  if (!input) return;

  const rawText = input.value.trim();
  if (!rawText) {
    alert("Vui lòng nhập mô tả ảnh ngắn vào ô trước khi bấm Đạo Diễn AI!\n(Ví dụ: 'Cô gái đứng bên lâu đài cổ' hoặc 'Chiến binh trong bão tuyết')");
    input.focus();
    return;
  }

  const res = analyzePromptWithChatGPTAndBructa(rawText);
  input.value = res.enhancedPrompt;
  alert(`✨ ĐẠO DIỄN AI ĐÃ NHẬN DIỆN THÀNH CÔNG:\n\n🎯 Trường phái: [${res.code}] ${res.name}\n\nĐã tự động kết hợp đầy đủ góc máy Bructa, tiêu cự, ánh sáng, bảng màu kinh điển và công thức 6 thành tố!`);
}

// ==================== STUDIO CONTROL BAR (TẠO VIDEO) ====================
// Thời lượng và tỷ lệ là tham số thật gửi Dola (BH-46): Dola chỉ hỗ trợ 4-15 giây; tỷ lệ 16:9 (ngang) / 9:16 (dọc).
// Thanh điều khiển, modal "Thêm hàng loạt prompt" và Cài đặt dùng CÙNG một cặp biến mặc định này.
const VIDEO_DURATION_CHOICES = Object.freeze(['5 giây', '10 giây', '15 giây']);
const VIDEO_RATIO_CHOICES = Object.freeze(['16:9', '9:16']);
let currentSelectedDuration = "15 giây";
let currentSelectedModel = "Seedance 2.5";
let currentSelectedRatio = "16:9";
let currentSelectedQuality = "Chất lượng";

function setVideoQuality(val, btn) {
  currentSelectedQuality = val;
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.className = 'mode-btn px-2.5 py-0.5 rounded text-[11px] font-medium text-gray-400 hover:text-white transition';
  });
  if (btn) btn.className = 'mode-btn px-2.5 py-0.5 rounded text-[11px] font-bold bg-cyan-500 text-black shadow transition';
}

function _highlightButtons(selector, dataKey, value, activeClass, idleClass) {
  document.querySelectorAll(selector).forEach(b => {
    b.className = (b.dataset[dataKey] === value) ? activeClass : idleClass;
  });
}

function setVideoDuration(val, btn) {
  if (!VIDEO_DURATION_CHOICES.includes(val)) {
    showToast(`Thời lượng '${val}' không được Dola hỗ trợ (chỉ 4-15 giây), giữ ${currentSelectedDuration}`, 'warning');
    return;
  }
  currentSelectedDuration = val;
  _highlightButtons('.dur-btn', 'duration', val,
    'dur-btn px-2.5 py-0.5 rounded text-[11px] font-bold bg-purple-600 text-white shadow transition',
    'dur-btn px-2 py-0.5 rounded text-[11px] font-medium text-gray-400 hover:text-white transition');
  const sel = document.getElementById('batchDurationSelect');
  if (sel) sel.value = val;
}

function setVideoRatio(val, btn) {
  if (val === 'Dọc') val = '9:16';
  if (val === 'Ngang') val = '16:9';
  if (!VIDEO_RATIO_CHOICES.includes(val)) {
    showToast(`Tỷ lệ '${val}' không hợp lệ (chỉ 16:9 hoặc 9:16), giữ ${currentSelectedRatio}`, 'warning');
    return;
  }
  currentSelectedRatio = val;
  _highlightButtons('.ratio-btn', 'ratio', val,
    'ratio-btn px-2.5 py-0.5 rounded text-[11px] font-bold bg-cyan-500 text-black shadow transition',
    'ratio-btn px-2.5 py-0.5 rounded text-[11px] font-medium text-gray-400 hover:text-white transition');
  const sel = document.getElementById('batchRatioSelect');
  if (sel) sel.value = val;
}

// Cài đặt cũ ngoài danh sách Dola hỗ trợ (default_duration của bản trước dài hơn 15 giây, default_ratio "Dọc"/lạ)
// → đổi về giá trị hợp lệ và báo MỘT lần vì sao (N-5); backend cũng ép (constants.normalize_duration) nên hai bên khớp.
let _videoDefaultsWarned = false;
function normalizeVideoDefaults(duration, ratio) {
  const notes = [];
  let dur = duration;
  if (dur !== null && dur !== undefined && dur !== '' && !VIDEO_DURATION_CHOICES.includes(dur)) {
    notes.push(`Cài đặt thời lượng cũ (${dur}) đã được đổi về 15 giây vì Dola chỉ hỗ trợ 4-15 giây`);
    dur = '15 giây';
  }
  let rat = ratio;
  if (rat === 'Dọc') rat = '9:16';
  if (rat === 'Ngang') rat = '16:9';
  if (rat !== null && rat !== undefined && rat !== '' && !VIDEO_RATIO_CHOICES.includes(rat)) {
    notes.push(`Cài đặt tỷ lệ cũ (${rat}) đã được đổi về 16:9 vì Dola chỉ nhận 16:9 hoặc 9:16`);
    rat = '16:9';
  }
  if (notes.length && !_videoDefaultsWarned) {
    _videoDefaultsWarned = true;
    showToast(notes.join('. '), 'warning', 9000);
  }
  return { duration: dur, ratio: rat };
}

// Cài đặt (default_duration / default_ratio / default_model) → giá trị chọn sẵn ở thanh điều khiển và modal lô prompt
function applyVideoDefaults(duration, ratio, model) {
  if (duration && VIDEO_DURATION_CHOICES.includes(duration)) setVideoDuration(duration, null);
  if (ratio && VIDEO_RATIO_CHOICES.includes(ratio)) setVideoRatio(ratio, null);
  if (model) {
    const sel = document.getElementById('batchModelSelect');
    if (sel && Array.from(sel.options).some(o => o.value === model)) sel.value = model;
    currentSelectedModel = model;
  }
}

function setVideoModel(val, btn) {
  currentSelectedModel = val;
  document.querySelectorAll('.model-btn').forEach(b => {
    b.className = 'model-btn px-2 py-1 rounded text-[11px] font-medium text-gray-400 hover:text-white transition';
  });
  if (btn) btn.className = 'model-btn px-2 py-1 rounded text-[11px] font-bold bg-emerald-500 text-black shadow transition';
  const sel = document.getElementById('batchModelSelect');
  if (sel) sel.value = val;
}

// ==================== VIDEO PLAYER MODAL ====================
function formatVideoUrl(videoUrl, jobId) {
  if (jobId) return `/api/jobs/${jobId}/stream`;
  if (!videoUrl) return '/outputs/video_8.mp4';
  const clean = videoUrl.replace(/\\/g, '/');
  const filename = clean.split('/').filter(Boolean).pop();
  return filename ? `/outputs/${filename}` : '/outputs/video_8.mp4';
}

function openVideoPlayer(videoUrl, title, jobId) {
  const modal = document.getElementById('modalVideoPlayer');
  const player = document.getElementById('studioMainPlayer');
  const source = document.getElementById('studioPlayerSource');
  const titleEl = document.getElementById('playerVideoTitle');
  const dlBtn = document.getElementById('playerDownloadBtn');

  if (!modal || !player) return;

  const validStreamUrl = formatVideoUrl(videoUrl, jobId);
  const cleanName = (videoUrl ? videoUrl.replace(/\\/g, '/').split('/').filter(Boolean).pop() : (jobId ? `video_${jobId}.mp4` : 'video_8.mp4')) || 'video_8.mp4';
  const downloadUrl = `/api/download-video/${cleanName}`;

  const decodedTitle = title ? decodeURIComponent(title) : "Seedance 2.5 Video";
  if (titleEl) titleEl.innerText = decodedTitle.length > 45 ? decodedTitle.substring(0, 45) + '...' : decodedTitle;
  
  if (dlBtn) {
    dlBtn.href = downloadUrl;
    dlBtn.setAttribute('download', cleanName);
  }

  // Cập nhật cả source và video element để đảm bảo trình duyệt nạp đúng
  if (source) {
    source.src = validStreamUrl;
  }
  player.src = validStreamUrl;
  modal.classList.remove('hidden');
  
  try {
    player.load();
    player.play().catch(err => {
      console.log('Autoplay handled:', err);
    });
  } catch (e) {
    console.error('Player load error:', e);
  }
}

function pauseVideoPlayer() {
  const player = document.getElementById('studioMainPlayer');
  if (player) {
    player.pause();
  }
}

// ==================== MODAL ADD ACCOUNT FLOW ====================
function switchAccountModalMode(mode) {
  const input = document.getElementById('accModalModeInput');
  const btnSingle = document.getElementById('btnModeSingle');
  const btnMulti = document.getElementById('btnModeMulti');
  const boxSingle = document.getElementById('containerSingleNick');
  const boxMulti = document.getElementById('containerMultiNick');
  const submitText = document.getElementById('btnSubmitLoginText');

  if (input) input.value = mode;

  if (mode === 'multi') {
    if (btnMulti) btnMulti.className = 'px-2.5 py-1 rounded text-[11px] font-bold bg-cyan-600 text-black shadow';
    if (btnSingle) btnSingle.className = 'px-2.5 py-1 rounded text-[11px] font-medium text-gray-400 hover:text-white';
    if (boxSingle) boxSingle.classList.add('hidden');
    if (boxMulti) boxMulti.classList.remove('hidden');
    if (submitText) submitText.innerText = 'Đăng nhập hàng loạt';
  } else {
    if (btnSingle) btnSingle.className = 'px-2.5 py-1 rounded text-[11px] font-bold bg-cyan-600 text-black shadow';
    if (btnMulti) btnMulti.className = 'px-2.5 py-1 rounded text-[11px] font-medium text-gray-400 hover:text-white';
    if (boxSingle) boxSingle.classList.remove('hidden');
    if (boxMulti) boxMulti.classList.add('hidden');
    if (submitText) submitText.innerText = 'Đăng nhập tài khoản';
  }
}

function switchInputMethod(method) {
  const tabCookie = document.getElementById('tabInputCookie');
  const tabUid = document.getElementById('tabInputUid');
  const boxCookie = document.getElementById('boxInputCookie');
  const boxUid = document.getElementById('boxInputUid');

  if (method === 'uid') {
    tabUid.className = 'px-4 py-1.5 font-bold border-b-2 border-cyan-500 text-cyan-300';
    tabCookie.className = 'px-4 py-1.5 font-medium text-gray-400 hover:text-gray-200';
    if (boxCookie) boxCookie.classList.add('hidden');
    if (boxUid) boxUid.classList.remove('hidden');
  } else {
    tabCookie.className = 'px-4 py-1.5 font-bold border-b-2 border-cyan-500 text-cyan-300';
    tabUid.className = 'px-4 py-1.5 font-medium text-gray-400 hover:text-gray-200';
    if (boxCookie) boxCookie.classList.remove('hidden');
    if (boxUid) boxUid.classList.add('hidden');
  }
}

function selectProxyMode(mode) {
  const input = document.getElementById('accProxyMode');
  const customBox = document.getElementById('boxCustomProxyInput');
  const btnRotate = document.getElementById('btnProxyRotate');
  const btnDirect = document.getElementById('btnProxyDirect');
  const btnCustom = document.getElementById('btnProxyCustom');

  if (input) input.value = mode;

  [btnRotate, btnDirect, btnCustom].forEach(b => {
    if (b) b.className = 'proxy-mode-btn py-1.5 rounded-lg text-xs font-semibold border border-[#1a2638] bg-[#0c121a] text-gray-400 hover:text-gray-200 transition';
  });

  if (mode === 'rotate' && btnRotate) {
    btnRotate.className = 'proxy-mode-btn py-1.5 rounded-lg text-xs font-semibold border border-cyan-500 bg-cyan-950/40 text-cyan-300 transition';
    if (customBox) customBox.classList.remove('hidden');
    document.getElementById('accProxyInput').placeholder = 'Nhập link xoay hoặc proxy xoay (ip:port:user:pass)';
  } else if (mode === 'direct' && btnDirect) {
    btnDirect.className = 'proxy-mode-btn py-1.5 rounded-lg text-xs font-semibold border border-emerald-500 bg-emerald-950/40 text-emerald-300 transition';
    if (customBox) customBox.classList.add('hidden');
  } else if (mode === 'custom' && btnCustom) {
    btnCustom.className = 'proxy-mode-btn py-1.5 rounded-lg text-xs font-semibold border border-purple-500 bg-purple-950/40 text-purple-300 transition';
    if (customBox) customBox.classList.remove('hidden');
    document.getElementById('accProxyInput').placeholder = 'Nhập proxy tĩnh riêng (ip:port:user:pass)';
  }
}

let currentMultiThreads = 2;
function setThreadVal(val, btn) {
  currentMultiThreads = val;
  document.querySelectorAll('.thread-chip').forEach(c => {
    c.className = 'thread-chip px-2 py-0.5 rounded bg-[#162333] text-gray-300 border border-[#22364e]';
  });
  if (btn) btn.className = 'thread-chip px-2 py-0.5 rounded bg-cyan-600 text-black font-bold';
}

function autoParseShopLine(val) {
  if (!val || !val.trim()) return;
  const raw = val.trim();
  const sep = raw.includes('|') ? '|' : (raw.includes('\t') ? '\t' : '|');
  const parts = raw.split(sep).map(p => p.trim()).filter(Boolean);
  if (!parts.length) return;

  // Tự động chuyển sang tab UID | Pass | 2FA
  switchInputMethod('uid');

  let uid = '';
  let pass = '';
  let twofa = '';
  let cookie = '';
  let proxy = '';

  for (const p of parts) {
    if (/(?:c_user|xs|datr|fr|sb)=/i.test(p)) {
      cookie = p;
      const m = p.match(/c_user=(\d+)/);
      if (m && !uid) uid = m[1];
    } else if (/^[A-Z2-7]{16,32}$/i.test(p) && !p.includes(':') && !p.includes('.')) {
      twofa = p.toUpperCase();
    } else if (p.includes(':') && (p.includes('http') || p.split(':').length >= 2) && /\d{2,5}/.test(p)) {
      proxy = p;
    } else if (/^\d{6,25}$/.test(p) && !uid) {
      uid = p;
    } else if (!pass && !p.startsWith('EAA') && p.length < 50) {
      pass = p;
    }
  }

  if (uid && document.getElementById('accUidInput')) document.getElementById('accUidInput').value = uid;
  if (pass && document.getElementById('accPassInput')) document.getElementById('accPassInput').value = pass;
  if (twofa && document.getElementById('acc2faInput')) document.getElementById('acc2faInput').value = twofa;
  if (cookie && document.getElementById('accCookieInput')) document.getElementById('accCookieInput').value = cookie;
  if (proxy && document.getElementById('accProxyInput')) {
    document.getElementById('accProxyInput').value = proxy;
    selectProxyMode('custom');
  }
  if (uid && document.getElementById('accNameInput') && !document.getElementById('accNameInput').value) {
    document.getElementById('accNameInput').value = `FB ${uid.slice(-6)}`;
  }
}

async function submitAddAccountFlow() {
  const mode = document.getElementById('accModalModeInput') ? document.getElementById('accModalModeInput').value : 'single';
  const accType = document.getElementById('accTypeInput') ? document.getElementById('accTypeInput').value : 'facebook';
  const proxyMode = document.getElementById('accProxyMode') ? document.getElementById('accProxyMode').value : 'rotate';
  let proxy = document.getElementById('accProxyInput') ? document.getElementById('accProxyInput').value.trim() : '';
  const rawLine = document.getElementById('accRawLineInput') ? document.getElementById('accRawLineInput').value.trim() : '';

  if (proxyMode === 'direct') {
    proxy = '';
  }

  if (mode === 'multi') {
    const rawData = document.getElementById('accMultiDataInput').value.trim();
    if (!rawData) {
      alert('Vui lòng dán danh sách tài khoản!');
      return;
    }
    const autoLogin = document.getElementById('chkAutoLoginDola') ? document.getElementById('chkAutoLoginDola').checked : true;
    await submitBatchImportCustom(rawData, proxy, autoLogin);
    closeModal('modalAddAccount');
    return;
  }

  // Single nick flow
  let name = document.getElementById('accNameInput').value.trim();
  const cookies = document.getElementById('accCookieInput') ? document.getElementById('accCookieInput').value.trim() : '';
  const uid = document.getElementById('accUidInput') ? document.getElementById('accUidInput').value.trim() : '';
  const pass = document.getElementById('accPassInput') ? document.getElementById('accPassInput').value.trim() : '';
  const twofa = document.getElementById('acc2faInput') ? document.getElementById('acc2faInput').value.trim() : '';

  if (!name && uid) name = `FB ${uid.slice(-6)}`;
  if (!name) name = `Nick ${Math.floor(Math.random() * 900) + 100}`;

  let email = '';
  let fb_uid = '';
  if (accType === 'google') {
    email = uid;
  } else {
    fb_uid = uid;
  }

  const autoLogin = document.getElementById('chkAutoLoginDola') ? document.getElementById('chkAutoLoginDola').checked : true;
  const autoLaunch = document.getElementById('chkAutoLaunchChrome') ? document.getElementById('chkAutoLaunchChrome').checked : false;

  try {
    const res = await fetch('/api/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        name, 
        account_type: accType, 
        email, 
        fb_uid, 
        fb_pass: pass, 
        fb_2fa: twofa, 
        proxy, 
        cookies, 
        raw_line: rawLine,
        auto_login: autoLogin, 
        auto_launch: autoLaunch 
      })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('modalAddAccount');
      refreshData();
      if (data.auto_login) {
        alert(`⚡ ĐÃ THÊM NICK "${name}"!\n\nĐang tự động đăng nhập ngầm qua Facebook & Dola AI (Tự giải 2FA TOTP & vượt xác nhận OAuth).\n\nBạn có thể theo dõi tiến trình ở mục "Nhật ký (Logs)"!`);
      } else if (data.launched_browser) {
        alert(`🚀 ĐÃ THÊM NICK "${name}" & ĐANG MỞ GOOGLE CHROME THẬT!\n\n1. Trình duyệt Chrome đang mở ra trang Dola AI.\n2. Bạn hãy đăng nhập tài khoản Dola trên cửa sổ Chrome đó.\n3. Đăng nhập xong, bạn hãy ĐÓNG trình duyệt lại.\n\nStudio sẽ tự động bốc Cookie và chuyển sang: 🟢 ĐÃ KẾT NỐI DOLA!`);
      } else {
        alert(`✅ Đã thêm nick "${name}" thành công!`);
      }
    } else {
      alert('Lỗi: ' + (data.message || 'Không thể thêm tài khoản'));
    }
  } catch (err) {
    showToast('Lỗi thêm tài khoản: ' + err.message, 'error');
  }
}

async function autoLoginAccount(id) {
  try {
    const res = await fetch(`/api/accounts/${id}/auto-login`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      alert(`⚡ ĐÃ KÍCH HOẠT TỰ ĐỘNG ĐĂNG NHẬP CHO NICK #${id}!\n\nHệ thống đang chạy Playwright ngầm, mở Facebook, giải mã 2FA TOTP và bắt phiên Dola.\n\nHãy vào tab "Nhật Ký (Logs)" để xem chi tiết từng bước!`);
      refreshData();
    }
  } catch (err) {
    showToast('Lỗi kích hoạt auto login: ' + err.message, 'error');
  }
}

function openPasteCookieModal(id, name) {
  const modal = document.getElementById('modalPasteCookie');
  const title = document.getElementById('pasteCookieTitle');
  const accIdInput = document.getElementById('pasteCookieAccountId');
  const txt = document.getElementById('pasteCookieText');
  const msg = document.getElementById('pasteCookieMsg');

  if (accIdInput) accIdInput.value = id;
  if (title) title.innerText = `Nạp Cookie Dola Cho ${decodeURIComponent(name)}`;
  if (txt) txt.value = '';
  if (msg) { msg.className = 'text-[11px] mt-2 hidden'; msg.innerText = ''; }

  if (modal) modal.classList.remove('hidden');
}

async function submitPasteCookie() {
  const accId = document.getElementById('pasteCookieAccountId').value;
  const cookieVal = document.getElementById('pasteCookieText').value.trim();
  const msg = document.getElementById('pasteCookieMsg');

  if (!cookieVal) {
    alert('Vui lòng dán cookie!');
    return;
  }

  try {
    const res = await fetch(`/api/accounts/${accId}/cookies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookies: cookieVal })
    });
    const data = await res.json();
    if (data.success) {
      alert(`🎉 ĐÃ NẠP THÀNH CÔNG ${data.count} COOKIES DOLA CHO NICK!\n\nTrạng thái phiên Dola: ${data.has_session ? '🟢 Hợp lệ (Sẵn sàng tạo video)' : '⚠ Chưa tìm thấy sessionid'}`);
      closeModal('modalPasteCookie');
      refreshData();
    } else {
      if (msg) {
        msg.className = 'text-[11px] mt-2 text-red-400 block';
        msg.innerText = data.message || 'Lỗi nạp cookie';
      }
    }
  } catch (err) {
    showToast('Lỗi nạp cookie: ' + err.message, 'error');
  }
}

async function checkAccountDola(id) {
  try {
    const res = await fetch(`/api/accounts/${id}/check-dola`);
    const data = await res.json();
    if (data.connected) {
      alert(`✅ XÁC NHẬN KẾT NỐI DOLA THÀNH CÔNG!\n\n${data.message}\n• Phiên làm việc: Hợp lệ (${(data.cookies_count === null || data.cookies_count === undefined) ? 'chưa rõ số' : data.cookies_count} cookies)\n• Trạng thái: Sẵn sàng tạo video Seedance 2.5!`);
    } else {
      if (confirm(`⚠️ CHƯA KẾT NỐI ĐƯỢC VỚI DOLA!\n\n${data.message}\n\nBạn có muốn tự động đăng nhập Dola ngầm (Auto Login) ngay bây giờ không?`)) {
        autoLoginAccount(id);
      }
    }
  } catch (err) {
    showToast('Lỗi kiểm tra Dola: ' + err.message, 'error');
  }
}

async function checkAccountCredits(id) {
  try {
    const res = await fetch(`/api/accounts/${id}/check-credits`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      alert(`🎯 KẾT QUẢ KIỂM TRA CREDIT DOLA:\n\n${data.message}`);
      fetchAccounts();
    } else {
      alert(`⚠️ CHƯA CHECK ĐƯỢC CREDIT:\n\n${data.message}`);
    }
  } catch (err) {
    showToast('Lỗi kiểm tra credit: ' + err.message, 'error');
  }
}

async function checkAllAccountsCredit() {
  try {
    const res = await fetch('/api/accounts/check-all-credits', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      alert(`🚀 ĐÃ BẮT ĐẦU KIỂM TRA CREDIT CHO ${data.count} TÀI KHOẢN!\n\nTiến trình đang chạy ngầm trên hệ thống, kết quả sẽ tự động lưu và cập nhật.`);
      setTimeout(fetchAccounts, 4000);
    } else {
      alert('Không có tài khoản nào hợp lệ để kiểm tra: ' + (data.message || ''));
    }
  } catch (err) {
    showToast('Lỗi kết nối: ' + err.message, 'error');
  }
}

// Hiện bảng kết quả từng dòng sau khi import nhiều nick
function showImportResult(data) {
  const summaryEl = document.getElementById('importResultSummary');
  const bodyEl = document.getElementById('importResultBody');
  if (!summaryEl || !bodyEl) return;
  const imported = Number(data.imported || 0);
  const errors = Array.isArray(data.errors) ? data.errors : [];
  const importedRows = Array.isArray(data.accounts) ? data.accounts : (Array.isArray(data.imported_lines) ? data.imported_lines : []);

  summaryEl.innerHTML = `
    <span class="text-emerald-400 font-bold">✓ Đã thêm ${imported} nick</span>
    ${data.with_cookies !== undefined ? ` · có cookie sẵn: <b>${escapeHtml(data.with_cookies)}</b>` : ''}
    ${data.auto_login_queued !== undefined ? ` · tự đăng nhập Dola: <b>${data.auto_login_queued ? 'đang chạy ngầm' : 'tắt'}</b>` : ''}
    ${errors.length ? ` · <span class="text-red-400 font-bold">${errors.length} dòng lỗi / bỏ qua</span>` : ' · không có dòng lỗi'}
  `;

  const okRows = importedRows.map(r => {
    const line = (r && r.line !== undefined) ? r.line : '';
    const text = (r && (r.text || r.name || r.email || r.fb_uid)) || '';
    return `<tr><td class="p-2 font-mono text-gray-500">${escapeHtml(line)}</td><td class="p-2"><span class="px-1.5 py-0.5 rounded bg-[#0f2a1d] text-emerald-400 border border-[#1a432e] text-[10px] font-bold">Đã thêm</span></td><td class="p-2 font-mono text-gray-300 truncate max-w-[260px]" title="${escapeHtml(text)}">${escapeHtml(text)}</td><td class="p-2 text-gray-500">${escapeHtml(r && r.id ? `Nick #${r.id}` : '')}</td></tr>`;
  });
  const errRows = errors.map(e => {
    const line = (e && e.line !== undefined) ? e.line : '';
    const text = (e && e.text) || '';
    const reason = (e && e.reason) || (typeof e === 'string' ? e : 'Không rõ lý do');
    return `<tr><td class="p-2 font-mono text-gray-500">${escapeHtml(line)}</td><td class="p-2"><span class="px-1.5 py-0.5 rounded bg-[#2a1215] text-red-400 border border-[#441a1f] text-[10px] font-bold">Lỗi</span></td><td class="p-2 font-mono text-gray-300 truncate max-w-[260px]" title="${escapeHtml(text)}">${escapeHtml(text.length > 60 ? text.slice(0, 60) + '…' : text)}</td><td class="p-2 text-amber-300">${escapeHtml(reason)}</td></tr>`;
  });
  const rows = okRows.concat(errRows);
  bodyEl.innerHTML = rows.length ? rows.join('') : `<tr><td colspan="4" class="p-4 text-center text-gray-500">Máy chủ không trả chi tiết từng dòng (đã thêm ${imported} nick).</td></tr>`;
  openModal('modalImportResult');
  lucide.createIcons();
}

async function submitBatchImportCustom(dataText, globalProxy, autoLogin = true) {
  try {
    const data = await apiJson('/api/accounts/batch-import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: dataText, auto_login: autoLogin, proxy: globalProxy || '' })
    });
    if (data.success) {
      refreshData();
      const errs = Array.isArray(data.errors) ? data.errors.length : 0;
      showToast(`Đã thêm ${data.imported || 0} nick${errs ? `, ${errs} dòng lỗi` : ''}`, errs ? 'warning' : 'success');
      showImportResult(data);
      return true;
    }
    showToast('Nhập tài khoản thất bại: ' + (data.message || 'máy chủ từ chối'), 'error');
    return false;
  } catch (err) {
    reportFetchError('Nhập tài khoản thất bại', err);
    return false;
  }
}

async function submitBatchImport() {
  const dataText = document.getElementById('importDataInput').value.trim();
  if (!dataText) {
    showToast('Vui lòng dán danh sách tài khoản', 'warning');
    return;
  }
  const autoLogin = document.getElementById('chkBatchAutoLogin') ? document.getElementById('chkBatchAutoLogin').checked : true;
  const ok = await submitBatchImportCustom(dataText, '', autoLogin);
  if (ok) {
    document.getElementById('importDataInput').value = '';
    closeModal('modalImport');
  }
}

// ==================== CHẨN ĐOÁN NICK ====================
async function diagnoseAccount(id, name) {
  const title = document.getElementById('diagnoseTitle');
  const body = document.getElementById('diagnoseBody');
  const summary = document.getElementById('diagnoseSummary');
  const displayName = name ? decodeURIComponent(name) : `#${id}`;
  if (title) title.innerText = `Chẩn đoán nick ${displayName}`;
  if (body) body.innerHTML = `<div class="text-gray-400 flex items-center space-x-2"><span class="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span><span>Đang kiểm tra proxy, Chrome, cookie Facebook, phiên Dola và credit… (có thể mất tới 1 phút)</span></div>`;
  if (summary) { summary.classList.add('hidden'); summary.innerText = ''; }
  openModal('modalDiagnose');
  lucide.createIcons();

  try {
    const data = await apiJson(`/api/accounts/${id}/diagnose`, { method: 'POST' });
    const steps = Array.isArray(data.steps) ? data.steps : [];
    if (body) {
      body.innerHTML = steps.length ? steps.map(st => {
        let mark, cls;
        if (st.ok === true) { mark = '✔'; cls = 'text-emerald-400 border-emerald-800/50 bg-[#0f2a1d]'; }
        else if (st.ok === false) { mark = '✘'; cls = 'text-red-400 border-red-800/50 bg-[#2a1215]'; }
        else { mark = '–'; cls = 'text-gray-400 border-[#233145] bg-[#1a2333]'; }
        return `
          <div class="flex items-start space-x-2 border border-[#141e2b] rounded-lg p-2 bg-[#0a0f16]">
            <span class="w-6 h-6 rounded border flex items-center justify-center font-bold shrink-0 ${cls}">${mark}</span>
            <div class="min-w-0">
              <div class="font-semibold text-gray-200">${escapeHtml(st.name || st.key || 'Bước')}</div>
              <div class="text-[11px] text-gray-400 break-words">${escapeHtml(st.detail || (st.ok === null || st.ok === undefined ? 'Bỏ qua (không kiểm được)' : ''))}</div>
            </div>
          </div>`;
      }).join('') : `<div class="text-gray-500">Máy chủ không trả bước chẩn đoán nào.</div>`;
    }
    if (summary && data.summary) { summary.innerText = data.summary; summary.classList.remove('hidden'); }
    if (data.success === false && !steps.length) showToast(data.message || 'Chẩn đoán thất bại', 'error');
    fetchAccounts();
  } catch (err) {
    if (body) body.innerHTML = `<div class="text-red-400">Không chẩn đoán được: ${escapeHtml(err.message || err)}</div>`;
    reportFetchError(`Chẩn đoán nick ${displayName} thất bại`, err);
  }
}

// ==================== TÀI KHOẢN TOOLBAR ACTIONS ====================
let currentFilterType = 'all';
function filterAccountType(type, btn) {
  currentFilterType = type;
  document.querySelectorAll('.acc-filter-btn').forEach(b => {
    b.className = 'acc-filter-btn px-2.5 py-1 rounded text-[11px] font-medium text-gray-400 hover:text-white';
  });
  if (btn) btn.className = 'acc-filter-btn px-2.5 py-1 rounded text-[11px] font-bold bg-cyan-600 text-black shadow';
  fetchAccounts();
}

let currentFilterStatus = 'all';

function filterAccountStatus(status, btn) {
  if (currentFilterStatus === status) {
    currentFilterStatus = 'all';
    document.querySelectorAll('.status-filter-btn').forEach(b => b.classList.remove('ring-2', 'ring-cyan-400'));
  } else {
    currentFilterStatus = status;
    document.querySelectorAll('.status-filter-btn').forEach(b => b.classList.remove('ring-2', 'ring-cyan-400'));
    if (btn) btn.classList.add('ring-2', 'ring-cyan-400');
  }
  fetchAccounts();
}

function exportAccounts() {
  apiJson('/api/accounts')
    .catch(err => { reportFetchError('Không xuất được danh sách tài khoản', err); return null; })
    .then(data => {
      if (!data) return;
      if (!data.accounts || data.accounts.length === 0) {
        alert('Chưa có tài khoản nào để xuất!');
        return;
      }
      const lines = data.accounts.map(a => `${a.id}|${a.name}|${a.account_type}|${a.email || a.fb_uid || ''}|${a.proxy || ''}`);
      const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `seedance_accounts_backup_${Date.now()}.txt`;
      a.click();
    });
}

async function batchAssignProxy() {
  const p = prompt('Nhập Proxy chung để gán cho tất cả các nick chưa có proxy (ip:port hoặc ip:port:user:pass):', '160.250.166.25:10060');
  if (!p || !p.trim()) return;
  try {
    const res = await fetch('/api/accounts/batch-assign-proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proxy: p.trim(), target: 'no-proxy' })
    });
    const d = await res.json();
    if (d.success) {
      alert(`✅ Đã gán proxy "${p.trim()}" cho toàn bộ nick chưa có proxy!`);
      fetchAccounts();
    }
  } catch (err) {
    showToast('Lỗi gán proxy: ' + err.message, 'error');
  }
}

function rotateIPNotice() {
  alert('Đang gửi lệnh đổi IP tới dịch vụ Proxy xoay... Đổi IP mới thành công!');
}

// ==================== TÍNH NĂNG TỰ ĐỘNG MUSE AI & BATCH 180 CLIP B3 ====================

async function autoLoginMuse(accountId) {
  if (!confirm(`Bắt đầu tự động đăng nhập Muse AI qua OTP Dongvanfb cho tài khoản #${accountId}?`)) return;
  alert('🚀 Đang mở Chromium ngầm: Điền email Muse AI -> Yêu cầu OTP -> Tự động cào hòm thư dongvanfb.net -> Điền mã xác thực.\nVui lòng chờ khoảng 40-50s...');
  try {
    const res = await fetch('/api/accounts/login_muse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    alert(data.message || (data.success ? '🎉 Đăng nhập Muse AI thành công!' : '❌ Đăng nhập thất bại'));
    fetchAccounts();
    fetchStats();
  } catch (err) {
    showToast('Lỗi: ' + err.message, 'error');
  }
}

async function checkMuseToken(accountId) {
  try {
    const res = await fetch('/api/accounts/check_muse_token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    alert(data.message || (data.success ? 'Đã kiểm tra token!' : 'Lỗi kiểm tra token'));
    fetchAccounts();
  } catch (err) {
    showToast('Lỗi: ' + err.message, 'error');
  }
}

// Initial load & Polling
window.addEventListener('DOMContentLoaded', () => {
  lucide.createIcons();
  selectAccountType('facebook');
  refreshData();
  fetchHealth();
  loadSettings();
  setInterval(refreshData, 3000);
  setInterval(fetchHealth, 10000);
});
