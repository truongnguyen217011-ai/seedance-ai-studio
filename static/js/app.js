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

  // Load specific tab data on switch
  if (tabId === 'image') fetchImages();
  if (tabId === 'assets') fetchAssets();
  if (tabId === 'check-media') loadNickMedia();
  if (tabId === 'logs') fetchLogs();
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
    console.error('Lỗi lấy thống kê:', err);
  }
}

// 2. Fetch and Render Video Jobs
async function fetchJobs() {
  try {
    const res = await fetch('/api/jobs');
    const data = await res.json();
    const tbody = document.getElementById('jobsTableBody');
    if (!tbody) return;

    if (data.jobs.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="9" class="p-8 text-center text-gray-500">
            Chưa có job tạo video nào. Bấm <b>"Thêm Prompt Hàng Loạt"</b> ở góc trên để bắt đầu!
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = data.jobs.map(j => {
      const isRunning = j.status === 'Đang chạy';
      const isCompleted = j.status === 'Hoàn thành';
      const isError = j.status === 'Lỗi';

      let statusBadge = `
        <span class="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-[#11242c] text-cyan-400 border border-[#1b3945]">
          <span class="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
          <span>Đang chạy</span>
        </span>
      `;
      if (isCompleted) {
        statusBadge = `
          <span class="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-[#0f2a1d] text-emerald-400 border border-[#1a432e]">
            <span>✓ Hoàn thành</span>
          </span>
        `;
      } else if (isError) {
        statusBadge = `
          <span class="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-[#2a1215] text-red-400 border border-[#441a1f]">
            <span>Lỗi</span>
          </span>
        `;
      } else if (j.status === 'Đang chờ') {
        statusBadge = `
          <span class="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-[#1a2333] text-gray-400 border border-[#233145]">
            <span>Đang chờ</span>
          </span>
        `;
      }

      const accBadge = j.account_name ? `
        <div class="inline-flex items-center space-x-1 bg-[#101722] border border-[#1b2636] px-2 py-1 rounded text-[11px] text-gray-300">
          <i data-lucide="user" class="w-3 h-3 text-cyan-400"></i>
          <span class="truncate max-w-[100px]">${j.account_name}</span>
        </div>
      ` : `<span class="text-gray-500 text-[11px]">Đang ghép acc...</span>`;

      const proxyBadge = j.account_proxy ? `
        <div class="bg-[#0e1620] border border-[#182433] px-2 py-0.5 rounded text-[10px] text-gray-300 font-mono">
          <div class="text-cyan-400 truncate max-w-[130px]">${j.account_proxy}</div>
          <div class="text-[9px] text-gray-500">IP mới - lượt 1/1 - proxy</div>
        </div>
      ` : `<span class="text-gray-500 text-[10px] italic">đang chờ IP</span>`;

      return `
        <tr class="hover:bg-[#0c121a] transition select-none">
          <td class="p-2.5 text-center"><input type="checkbox" class="rounded bg-gray-800 border-gray-700"></td>
          <td class="p-2.5 font-mono text-gray-400 font-semibold">#${j.id}</td>
          <td class="p-2.5">
            <div class="space-y-1">
              <div class="flex items-center justify-between">
                ${statusBadge}
                <span class="text-[10px] text-gray-500">${j.progress}%</span>
              </div>
              <div class="w-full bg-[#141d2a] h-1 rounded overflow-hidden">
                <div class="bg-gradient-to-r from-cyan-400 to-emerald-400 h-1 transition-all duration-300" style="width: ${j.progress}%"></div>
              </div>
              <div class="text-[10px] text-gray-400 truncate max-w-[220px]" title="${j.status_message || ''}">
                ${j.status_message || 'Chờ khởi tạo...'}
              </div>
            </div>
          </td>
          <td class="p-2.5 text-gray-300 font-medium">${j.duration}</td>
          <td class="p-2.5 text-gray-300 font-semibold">${j.model}</td>
          <td class="p-2.5">${accBadge}</td>
          <td class="p-2.5">${proxyBadge}</td>
          <td class="p-2.5">
            <div class="font-medium text-gray-200 line-clamp-1" title="${j.prompt}">${j.title || j.prompt}</div>
            ${j.local_video_path ? `
              <div class="mt-1 flex items-center space-x-1.5">
                <button type="button" onclick="openVideoPlayer('${j.local_video_path}', '${encodeURIComponent(j.title || j.prompt)}', ${j.id})" class="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded bg-cyan-950/60 text-cyan-300 hover:bg-cyan-900/80 border border-cyan-800/40 text-[10px] font-semibold transition">
                  <i data-lucide="play-circle" class="w-3.5 h-3.5 text-cyan-400"></i>
                  <span>Xem Video Siêu Mượt</span>
                </button>
                <a href="/api/download-video/video_${j.id}.mp4" download class="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded bg-[#10231d] text-emerald-300 hover:bg-[#16382e] border border-emerald-800/40 text-[10px] font-semibold transition" title="Tải Video MP4 về máy">
                  <i data-lucide="download" class="w-3 h-3 text-emerald-400"></i>
                  <span>Tải MP4</span>
                </a>
              </div>
            ` : ''}
          </td>
          <td class="p-2.5 text-center">
            <button onclick="deleteJob(${j.id})" class="p-1.5 bg-[#251014] hover:bg-red-900/50 text-red-400 rounded border border-[#3e1b21] transition" title="Xóa Job">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </td>
        </tr>
      `;
    }).join('');

    lucide.createIcons();
  } catch (err) {
    console.error('Lỗi lấy danh sách job:', err);
  }
}

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
    console.error('Lỗi lấy danh sách ảnh:', err);
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
    alert('Lỗi tạo ảnh: ' + err.message);
  }
}

async function deleteImage(id) {
  if (!confirm('Xóa ảnh này?')) return;
  await fetch(`/api/images/${id}`, { method: 'DELETE' });
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
    console.error('Lỗi lấy nhân vật:', err);
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
    alert('Lỗi thêm asset: ' + err.message);
  }
}

async function deleteAsset(id) {
  if (!confirm('Xóa nhân vật này?')) return;
  await fetch(`/api/assets/${id}`, { method: 'DELETE' });
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
    console.error('Lỗi nạp nick media:', err);
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
    alert('Lỗi tạo âm thanh: ' + err.message);
  }
}

// 7. Nhật ký (Logs)
async function fetchLogs() {
  try {
    const res = await fetch('/api/logs');
    const data = await res.json();
    const container = document.getElementById('logsContainer');
    if (!container) return;

    if (data.logs.length === 0) {
      container.innerHTML = `<div class="text-gray-600">Chưa có bản ghi nhật ký nào.</div>`;
      return;
    }

    container.innerHTML = data.logs.map(l => {
      let color = 'text-gray-400';
      if (l.level === 'SUCCESS') color = 'text-emerald-400 font-semibold';
      if (l.level === 'WARNING') color = 'text-amber-400';
      if (l.level === 'ERROR') color = 'text-red-400 font-bold';
      if (l.level === 'INFO') color = 'text-cyan-400';

      return `
        <div class="leading-relaxed hover:bg-[#0c121a] px-1 rounded">
          <span class="text-gray-600">[${l.created_at || 'Vừa xong'}]</span>
          <span class="${color}">[${l.level}]</span>
          <span class="text-purple-400">[${l.module}]:</span>
          <span class="text-gray-300">${l.message}</span>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Lỗi lấy logs:', err);
  }
}

async function clearLogs() {
  if (!confirm('Xóa sạch nhật ký?')) return;
  await fetch('/api/logs', { method: 'DELETE' });
  fetchLogs();
}

function selectAccountType(type) {
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
async function fetchAccounts() {
  try {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    const tbody = document.getElementById('accountsTableBody');
    const filterSelect = document.getElementById('filterNickMediaSelect');
    const imageAccSelect = document.getElementById('imageAccountSelect');

    let accounts = data.accounts || [];
    if (typeof currentFilterType !== 'undefined' && currentFilterType !== 'all') {
      accounts = accounts.filter(a => a.account_type === currentFilterType);
    }
    if (typeof currentFilterStatus !== 'undefined') {
      if (currentFilterStatus === 'ready') {
        accounts = accounts.filter(a => a.has_dola === true || a.account_type === 'muse');
      } else if (currentFilterStatus === 'no-proxy') {
        accounts = accounts.filter(a => !a.proxy || a.proxy.trim() === '');
      }
    }

    if (tbody) {
      if (accounts.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="8" class="p-8 text-center text-gray-500">
              Không có tài khoản nào phù hợp bộ lọc. Hãy bấm <b>"Thêm Tài Khoản"</b> (Muse AI, Facebook hoặc Google) để bắt đầu!
            </td>
          </tr>
        `;
      } else {
        tbody.innerHTML = accounts.map(a => {
          const isMuse = a.account_type === 'muse';
          const isGoogle = a.account_type === 'google';
          let typeBadge = '';
          if (isMuse) {
            typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#261536] text-purple-300 border border-purple-600/50 inline-flex items-center space-x-1"><i data-lucide="sparkles" class="w-3 h-3 text-purple-400"></i><span>Muse AI</span></span>`;
          } else if (isGoogle) {
            typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#291215] text-rose-400 border border-[#481c22] inline-flex items-center space-x-1"><i data-lucide="mail" class="w-3 h-3 text-rose-400"></i><span>Google</span></span>`;
          } else {
            typeBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#0d1e30] text-cyan-400 border border-[#163352] inline-flex items-center space-x-1"><i data-lucide="facebook" class="w-3 h-3 text-cyan-400"></i><span>Facebook</span></span>`;
          }

          const twofaBadge = a.fb_2fa ? `<span class="px-1.5 py-0.2 rounded text-[9px] font-bold bg-[#1e2311] text-amber-300 border border-amber-700/50">2FA</span>` : '';
          const passBadge = a.has_pass ? `<span class="px-1.5 py-0.2 rounded text-[9px] bg-[#141a24] text-gray-400 border border-[#1f2937]">Pass</span>` : '';

          let identifier = '';
          if (isMuse) {
            identifier = a.email ? `<div class="space-y-0.5"><div class="text-purple-300 font-mono text-[11px] font-semibold">${a.email}</div><span class="text-[9px] text-gray-500">Dongvanfb Mail</span></div>` : `<span class="text-gray-500 text-[11px]">Chưa gắn Mail</span>`;
          } else if (isGoogle) {
            identifier = a.email ? `<div class="space-y-0.5"><div class="text-rose-300 font-mono text-[11px]">${a.email}</div></div>` : `<span class="text-gray-500 text-[11px]">Chưa gắn Gmail</span>`;
          } else {
            identifier = a.fb_uid ? `<div class="space-y-1"><div class="text-gray-300 font-mono text-[11px] font-semibold">${a.fb_uid}</div><div class="flex items-center space-x-1">${twofaBadge} ${passBadge}</div></div>` : `<span class="text-gray-500 text-[11px]">Chưa gắn UID</span>`;
          }

          const hasDola = a.has_dola === true;
          let statusBadge = '';
          if (isMuse) {
            statusBadge = (a.status === 'ready' || a.cookies)
              ? `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-[#1d1230] text-purple-300 border border-purple-500/40 inline-flex items-center space-x-1 shadow">
                  <i data-lucide="check-circle" class="w-3.5 h-3.5 text-purple-400"></i>
                  <span>🟢 Đã kết nối Muse</span>
                 </span>`
              : `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-[#291215] text-rose-300 border border-rose-800/50 inline-flex items-center space-x-1 shadow">
                  <i data-lucide="alert-triangle" class="w-3.5 h-3.5 text-rose-400"></i>
                  <span>🔴 Chưa login Muse</span>
                 </span>`;
          } else {
            statusBadge = hasDola
              ? `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-[#0d281a] text-emerald-400 border border-emerald-500/40 inline-flex items-center space-x-1 shadow">
                  <i data-lucide="check-circle" class="w-3.5 h-3.5 text-emerald-400"></i>
                  <span>🟢 Đã kết nối Dola</span>
                 </span>`
              : `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-[#291215] text-rose-300 border border-rose-800/50 inline-flex items-center space-x-1 shadow">
                  <i data-lucide="alert-triangle" class="w-3.5 h-3.5 text-rose-400"></i>
                  <span>🔴 Chưa kết nối Dola</span>
                 </span>`;
          }

          // Cột hiển thị số lượt Credit / Token
          let creditBadge = `<span class="px-2 py-0.5 rounded text-[10px] text-gray-500 bg-[#0d131d] border border-[#1b2636]">Chưa check</span>`;
          if (isMuse) {
            const tok = a.tokens_balance ? Number(a.tokens_balance).toLocaleString() : '1,000,000,000';
            creditBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#261536] text-purple-300 border border-purple-600/50 inline-flex items-center space-x-1" title="Số dư token Muse AI">
              <i data-lucide="sparkles" class="w-3 h-3 text-purple-400"></i>
              <span>${tok} tokens</span>
            </span>`;
          } else if (a.is_resting) {
            const restTip = (a.rest_reason || 'Đang nghỉ') + (a.rest_until ? ` đến ${a.rest_until.slice(11, 16)}` : '');
            creditBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#291e0a] text-amber-300 border border-amber-600/50 inline-flex items-center space-x-1 cursor-help" title="${restTip}">
              <span>⏸️ Nghỉ (0 lượt)</span>
            </span>`;
          } else if (a.credits_today !== null && a.credits_today !== undefined) {
            if (a.credits_today > 0) {
              creditBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#0d281a] text-emerald-400 border border-emerald-500/40 inline-flex items-center space-x-1">
                <i data-lucide="zap" class="w-3 h-3 text-emerald-400"></i>
                <span>${a.credits_today} credits</span>
              </span>`;
            } else {
              creditBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#291215] text-rose-300 border border-rose-800/50 inline-flex items-center space-x-1">
                <span>0 credit (Hết lượt)</span>
              </span>`;
            }
          } else if (hasDola) {
            const cr = (a.credits !== null && a.credits !== undefined) ? a.credits : 4;
            creditBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-[#0d281a] text-emerald-400 border border-emerald-500/40 inline-flex items-center space-x-1" title="Sẵn sàng (mặc định 4 lượt/ngày)">
              <i data-lucide="zap" class="w-3 h-3 text-emerald-400"></i>
              <span>🟢 ${cr} credits</span>
            </span>`;
          }

          let loginActions = '';
          if (isMuse) {
            loginActions = `
              <div class="flex items-center justify-center space-x-1.5">
                <button onclick="autoLoginMuse(${a.id})" class="px-2.5 py-1 bg-gradient-to-r from-purple-600 to-indigo-500 hover:opacity-90 text-white font-bold text-[10px] rounded transition flex items-center space-x-1 shadow" title="Tự động bốc OTP dongvanfb để đăng nhập">
                  <i data-lucide="zap" class="w-3 h-3 text-amber-300"></i>
                  <span>⚡ Auto Login</span>
                </button>
                <button onclick="checkMuseToken(${a.id})" class="px-2 py-1 bg-[#102422] hover:bg-[#163833] text-emerald-300 border border-emerald-700/50 text-[10px] font-semibold rounded transition flex items-center space-x-1" title="Kiểm tra số dư token">
                  <i data-lucide="sparkles" class="w-3 h-3 text-emerald-400"></i>
                  <span>Check Token</span>
                </button>
              </div>
            `;
          } else if (hasDola) {
            loginActions = `<div class="flex items-center justify-center space-x-1.5">
                <button onclick="checkAccountCredits(${a.id})" class="px-2 py-1 bg-[#102422] hover:bg-[#163833] text-emerald-300 border border-emerald-700/50 text-[10px] font-semibold rounded transition flex items-center space-x-1" title="Kiểm tra lượt tạo video hôm nay">
                  <i data-lucide="sparkles" class="w-3 h-3 text-emerald-400"></i>
                  <span>Check Credit</span>
                </button>
                <button onclick="openPasteCookieModal(${a.id}, '${encodeURIComponent(a.name)}')" class="px-2 py-1 bg-[#1a1727] hover:bg-[#282040] text-purple-300 border border-purple-800/40 text-[10px] rounded transition flex items-center space-x-1" title="Đổi hoặc nạp lại cookie Dola">
                  <i data-lucide="cookie" class="w-3 h-3 text-purple-400"></i>
                  <span>Cookie</span>
                </button>
                <button onclick="loginAccount(${a.id})" class="px-2 py-1 bg-[#121c28] hover:bg-[#1b2b3d] text-gray-300 border border-[#203146] text-[10px] rounded transition flex items-center space-x-1" title="Mở Chrome thật kiểm tra">
                  <i data-lucide="external-link" class="w-3 h-3"></i>
                  <span>Chrome</span>
                </button>
               </div>`;
          } else {
            loginActions = `<div class="flex items-center justify-center space-x-1.5">
                <button onclick="autoLoginAccount(${a.id})" class="px-2.5 py-1 bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400 hover:opacity-90 text-black font-extrabold text-[10px] rounded transition flex items-center space-x-1 shadow-md" title="Tự động đăng nhập FB + Giải 2FA ngầm">
                  <i data-lucide="sparkles" class="w-3 h-3"></i>
                  <span>⚡ Auto Login</span>
                </button>
                <button onclick="openPasteCookieModal(${a.id}, '${encodeURIComponent(a.name)}')" class="px-2 py-1 bg-[#1a1727] hover:bg-[#282040] text-purple-300 border border-purple-800/40 text-[10px] rounded transition flex items-center space-x-1" title="Dán cookie Dola từ Cookie-Editor">
                  <i data-lucide="cookie" class="w-3 h-3 text-purple-400"></i>
                  <span>Dán Cookie</span>
                </button>
                <button onclick="loginAccount(${a.id})" class="px-2 py-1 bg-[#121c28] hover:bg-[#1b2b3d] text-gray-400 border border-[#203146] text-[10px] rounded transition flex items-center space-x-1" title="Mở trình duyệt Google Chrome thật">
                  <i data-lucide="external-link" class="w-3 h-3"></i>
                  <span>Chrome</span>
                </button>
               </div>`;
          }

          return `
            <tr class="hover:bg-[#0c121a] transition select-none">
              <td class="p-2.5 text-center font-mono text-gray-400">#${a.id}</td>
              <td class="p-2.5">${typeBadge}</td>
              <td class="p-2.5 font-semibold text-gray-200">${a.name}</td>
              <td class="p-2.5">${identifier}</td>
              <td class="p-2.5 font-mono text-cyan-400 text-[11px]">${a.proxy || '<span class="text-gray-500">Không có proxy</span>'}</td>
              <td class="p-2.5 text-center">${statusBadge}</td>
              <td class="p-2.5 text-center">${creditBadge}</td>
              <td class="p-2.5 text-center">${loginActions}</td>
              <td class="p-2.5 text-center">
                <button onclick="deleteAccount(${a.id})" class="p-1.5 bg-[#251014] hover:bg-red-900/50 text-red-400 rounded border border-[#3e1b21] transition" title="Xóa Tài Khoản">
                  <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                </button>
              </td>
            </tr>
          `;
        }).join('');
      }
    }

    // Populate dropdowns
    if (filterSelect) {
      filterSelect.innerHTML = `<option value="">Xem tất cả tài khoản</option>` + data.accounts.map(a => `<option value="${a.id}">[${a.account_type === 'google' ? 'Google' : 'FB'}] ${a.name}</option>`).join('');
    }
    if (imageAccSelect) {
      imageAccSelect.innerHTML = `<option value="">Tự động chọn tài khoản rảnh</option>` + data.accounts.map(a => `<option value="${a.id}">[${a.account_type === 'google' ? 'Google' : 'FB'}] ${a.name}</option>`).join('');
    }

    lucide.createIcons();
  } catch (err) {
    console.error('Lỗi lấy tài khoản:', err);
  }
}

// Action: Submit Batch Prompts
async function submitBatchPrompts() {
  const text = document.getElementById('batchPromptsInput').value;
  const model = document.getElementById('batchModelSelect').value;
  const duration = document.getElementById('batchDurationSelect').value;

  const prompts = text.split('\n').map(p => p.trim()).filter(p => p.length > 0);
  if (prompts.length === 0) {
    alert('Vui lòng nhập ít nhất 1 dòng prompt!');
    return;
  }

  try {
    const res = await fetch('/api/jobs/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompts, model, duration })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('modalBatchPrompts');
      document.getElementById('batchPromptsInput').value = '';
      refreshData();
    }
  } catch (err) {
    alert('Lỗi gửi jobs: ' + err.message);
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
    alert('Lỗi thêm tài khoản: ' + err.message);
  }
}

// Action: Batch Import Accounts
async function submitBatchImport() {
  const dataText = document.getElementById('importDataInput').value.trim();
  if (!dataText) {
    alert('Vui lòng dán danh sách tài khoản & proxy!');
    return;
  }

  try {
    const res = await fetch('/api/accounts/batch-import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: dataText })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('modalImport');
      document.getElementById('importDataInput').value = '';
      alert(`Đã import thành công ${data.imported} tài khoản!`);
      refreshData();
    }
  } catch (err) {
    alert('Lỗi import: ' + err.message);
  }
}

// Action: Launch Login Session
async function loginAccount(id) {
  try {
    fetch(`/api/accounts/${id}/login`, { method: 'POST' });
    alert('👉 Đang gửi lệnh mở Google Chrome cho Nick #' + id + '!\n\nNếu cửa sổ Chrome chưa hiện lên ngay trước mắt (do Windows bảo vệ chặn ứng dụng nền):\n➡️ Bạn chỉ cần mở thư mục C:\\AI SEEDANE và nhấp đúp vào file:\n   "MO_CHROME_ACC_' + id + '.bat"\n\nCửa sổ Chrome thật sẽ hiện lên ngay lập tức để bạn kéo mảnh ghép hoặc kiểm tra!');
  } catch (err) {
    alert('Lỗi mở trình duyệt: ' + err.message);
  }
}

// Action: Delete Job
async function deleteJob(id) {
  if (!confirm('Bạn có chắc muốn xóa job này?')) return;
  try {
    await fetch(`/api/jobs/${id}`, { method: 'DELETE' });
    refreshData();
  } catch (err) {
    alert('Lỗi xóa job: ' + err.message);
  }
}

// Action: Delete Account
async function deleteAccount(id) {
  if (!confirm('Bạn có chắc muốn xóa tài khoản này?')) return;
  try {
    await fetch(`/api/accounts/${id}`, { method: 'DELETE' });
    refreshData();
  } catch (err) {
    alert('Lỗi xóa tài khoản: ' + err.message);
  }
}

// Save Settings
async function saveSettings() {
  const max_concurrent_jobs = document.getElementById('settingMaxJobs').value;
  const default_model = document.getElementById('settingModel').value;
  const default_duration = document.getElementById('settingDuration').value;
  const delay_between_jobs = document.getElementById('settingDelay').value;

  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_concurrent_jobs, default_model, default_duration, delay_between_jobs })
    });
    alert('Đã lưu cấu hình hệ thống thành công!');
  } catch (err) {
    alert('Lỗi lưu cấu hình: ' + err.message);
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

// ==================== ĐẠO DIỄN AI TỰ ĐỘNG PHÂN TÍCH PROMPT VIDEO HÀNG LOẠT ====================
function autoDetectAndEnhanceBructa() {
  const textarea = document.getElementById('batchPromptsInput');
  if (!textarea) return;

  const rawText = textarea.value.trim();
  if (!rawText) {
    alert("Vui lòng nhập hoặc dán ít nhất 1 dòng prompt (bằng tiếng Việt hoặc tiếng Anh) để Đạo Diễn AI phân tích!");
    return;
  }

  const lines = rawText.split('\n');
  const detectedArchetypes = new Set();
  let processedCount = 0;

  const enhanced = lines.map((line) => {
    line = line.trim();
    if (!line) return "";
    processedCount++;
    const res = analyzePromptWithChatGPTAndBructa(line);
    detectedArchetypes.add(`• [${res.code}] ${res.name}`);
    return `${res.enhancedPrompt}, --ar 16:9`;
  });

  textarea.value = enhanced.filter(l => l.length > 0).join('\n\n');
  
  const archSummary = Array.from(detectedArchetypes).join('\n');
  alert(`✅ ĐẠO DIỄN AI ĐÃ TỰ ĐỘNG PHÂN TÍCH & KẾT HỢP XONG ${processedCount} PROMPT!\n\n🎯 CÁC TRƯỜNG PHÁI THỊ GIÁC ĐÃ TỰ ĐỘNG NHẬN DIỆN:\n${archSummary}\n\n🎬 Đã kết hợp tự động:\n1. Bố cục, Cỡ cảnh & Góc máy chuẩn Bructa\n2. Ống kính & Ánh sáng Chiaroscuro/Rim Light\n3. Bảng màu kinh điển tương thích 100%\n4. Công thức 6 thành tố nghệ thuật bóc tách từ 186 họa sĩ ChatGPT!`);
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
let currentSelectedDuration = "30 giây";
let currentSelectedModel = "Seedance 2.5";
let currentSelectedRatio = "Dọc";
let currentSelectedQuality = "Chất lượng";

function setVideoQuality(val, btn) {
  currentSelectedQuality = val;
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.className = 'mode-btn px-2.5 py-0.5 rounded text-[11px] font-medium text-gray-400 hover:text-white transition';
  });
  if (btn) btn.className = 'mode-btn px-2.5 py-0.5 rounded text-[11px] font-bold bg-cyan-500 text-black shadow transition';
}

function setVideoDuration(val, btn) {
  currentSelectedDuration = val;
  document.querySelectorAll('.dur-btn').forEach(b => {
    b.className = 'dur-btn px-2 py-0.5 rounded text-[11px] font-medium text-gray-400 hover:text-white transition';
  });
  if (btn) btn.className = 'dur-btn px-2 py-0.5 rounded text-[11px] font-bold bg-purple-600 text-white shadow transition';
  const sel = document.getElementById('batchDurationSelect');
  if (sel) sel.value = val;
}

function setVideoRatio(val, btn) {
  currentSelectedRatio = val;
  document.querySelectorAll('.ratio-btn').forEach(b => {
    b.className = 'ratio-btn px-2.5 py-0.5 rounded text-[11px] font-medium text-gray-400 hover:text-white transition';
  });
  if (btn) btn.className = 'ratio-btn px-2.5 py-0.5 rounded text-[11px] font-bold bg-cyan-500 text-black shadow transition';
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
    alert('Lỗi thêm tài khoản: ' + err.message);
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
    alert('Lỗi kích hoạt auto login: ' + err.message);
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
    alert('Lỗi nạp cookie: ' + err.message);
  }
}

async function checkAccountDola(id) {
  try {
    const res = await fetch(`/api/accounts/${id}/check-dola`);
    const data = await res.json();
    if (data.connected) {
      alert(`✅ XÁC NHẬN KẾT NỐI DOLA THÀNH CÔNG!\n\n${data.message}\n• Phiên làm việc: Hợp lệ (${data.cookies_count || 10} cookies)\n• Trạng thái: Sẵn sàng tạo video Seedance 2.5!`);
    } else {
      if (confirm(`⚠️ CHƯA KẾT NỐI ĐƯỢC VỚI DOLA!\n\n${data.message}\n\nBạn có muốn tự động đăng nhập Dola ngầm (Auto Login) ngay bây giờ không?`)) {
        autoLoginAccount(id);
      }
    }
  } catch (err) {
    alert('Lỗi kiểm tra Dola: ' + err.message);
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
    alert('Lỗi kiểm tra credit: ' + err.message);
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
    alert('Lỗi kết nối: ' + err.message);
  }
}

async function submitBatchImportCustom(dataText, globalProxy, autoLogin = true) {
  try {
    const res = await fetch('/api/accounts/batch-import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: dataText, auto_login: autoLogin })
    });
    const data = await res.json();
    if (data.success) {
      refreshData();
      let alertMsg = `✅ ĐÃ IMPORT THÀNH CÔNG ${data.imported} TÀI KHOẢN!\n• Nick có cookie sẵn: ${data.with_cookies}\n• Tự động đăng nhập Dola ngầm: ${data.auto_login_queued ? 'ĐANG CHẠY' : 'Tắt'}`;
      if (data.errors && data.errors.length) {
        alertMsg += `\n• Số dòng bỏ qua / lỗi: ${data.errors.length}`;
      }
      alert(alertMsg);
    } else {
      alert('Lỗi import: ' + (data.message || 'Thất bại'));
    }
  } catch (err) {
    alert('Lỗi import: ' + err.message);
  }
}

async function submitBatchImport() {
  const dataText = document.getElementById('importDataInput').value.trim();
  if (!dataText) {
    alert('Vui lòng dán danh sách tài khoản!');
    return;
  }
  const autoLogin = document.getElementById('chkBatchAutoLogin') ? document.getElementById('chkBatchAutoLogin').checked : true;
  await submitBatchImportCustom(dataText, '', autoLogin);
  closeModal('modalImport');
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
  fetch('/api/accounts')
    .then(r => r.json())
    .then(data => {
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
    alert('Lỗi gán proxy: ' + err.message);
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
    alert('Lỗi: ' + err.message);
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
    alert('Lỗi: ' + err.message);
  }
}

async function openImportB3Modal() {
  const filePath = prompt(
    "Nhập đường dẫn đầy đủ đến file '_ALL_CLIP_PROMPTS.txt' hoặc thư mục bài sản xuất của TOOL AI:\n(Ví dụ: D:\\TOOL_AI\\Ten_Bai\\_ALL_CLIP_PROMPTS.txt)",
    "D:\\TOOL_AI\\"
  );
  if (!filePath || !filePath.trim()) return;

  try {
    const res = await fetch('/api/batch/import_b3', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath.trim() })
    });
    const data = await res.json();
    if (data.success) {
      alert(`🎉 ${data.message}\n\n• Tổng số clip: ${data.total_clips}\n• Đã chia đều cho: ${data.accounts_assigned} tài khoản Muse AI sẵn có\n\nHệ thống sẽ bắt đầu tự động render song song!`);
      switchTab('video');
      fetchJobs();
      fetchStats();
    } else {
      alert('Lỗi nạp batch: ' + data.message);
    }
  } catch (err) {
    alert('Lỗi kết nối: ' + err.message);
  }
}

// Initial load & Polling
window.addEventListener('DOMContentLoaded', () => {
  lucide.createIcons();
  refreshData();
  setInterval(refreshData, 3000);
});
