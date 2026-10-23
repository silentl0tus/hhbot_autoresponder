// Job Hunter Dashboard Client

let autoRefreshTimer = null;
let currentVacanciesPage = 1;
let currentVacancyStatus = 'ALL';
let currentVacancySearch = '';

document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  refreshAllData();
  setupAutoRefresh();
});

function initEventListeners() {
  // Tabs navigation
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const targetId = btn.getAttribute('data-tab');
      document.getElementById(targetId).classList.add('active');

      if (targetId === 'tab-vacancies') loadVacancies();
      if (targetId === 'tab-applications') loadApplications();
      if (targetId === 'tab-messages') loadMessages();
      if (targetId === 'tab-logs') loadLogs();
    });
  });

  // Filter chips in vacancies
  document.querySelectorAll('.filter-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      currentVacancyStatus = chip.getAttribute('data-status');
      currentVacanciesPage = 1;
      loadVacancies();
    });
  });

  // Search input with debounce
  const searchInput = document.getElementById('vacSearchInput');
  if (searchInput) {
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        currentVacancySearch = e.target.value;
        currentVacanciesPage = 1;
        loadVacancies();
      }, 350);
    });
  }

  // Refresh interval select
  const refreshSelect = document.getElementById('refreshInterval');
  if (refreshSelect) {
    refreshSelect.addEventListener('change', () => {
      setupAutoRefresh();
    });
  }

  // Manual refresh button
  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      refreshAllData();
    });
  }

  // Logs level filter
  const logFilter = document.getElementById('logLevelFilter');
  if (logFilter) {
    logFilter.addEventListener('change', () => {
      loadLogs();
    });
  }

  // Reset rejected modal
  const openResetBtn = document.getElementById('btnResetRejected');
  const modal = document.getElementById('resetModal');
  const cancelResetBtn = document.getElementById('btnCancelReset');
  const confirmResetBtn = document.getElementById('btnConfirmReset');

  if (openResetBtn && modal) {
    openResetBtn.addEventListener('click', () => modal.classList.add('active'));
  }
  if (cancelResetBtn && modal) {
    cancelResetBtn.addEventListener('click', () => modal.classList.remove('active'));
  }
  if (confirmResetBtn && modal) {
    confirmResetBtn.addEventListener('click', async () => {
      confirmResetBtn.disabled = true;
      confirmResetBtn.textContent = 'Сброс...';
      try {
        const resp = await fetch('/api/actions/reset_rejected', { method: 'POST' });
        const res = await resp.json();
        if (res.success) {
          alert(`Успешно сброшено ${res.count} вакансий в статус NEW!`);
          modal.classList.remove('active');
          refreshAllData();
        } else {
          alert(`Ошибка: ${res.error}`);
        }
      } catch (e) {
        alert(`Ошибка сети: ${e.message}`);
      } finally {
        confirmResetBtn.disabled = false;
        confirmResetBtn.textContent = 'Да, сбросить';
      }
    });
  }
}

function setupAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  const select = document.getElementById('refreshInterval');
  const sec = parseInt(select ? select.value : 10, 10);
  if (sec > 0) {
    autoRefreshTimer = setInterval(() => {
      refreshAllData();
    }, sec * 1000);
  }
}

function refreshAllData() {
  loadStats();
  const activeTab = document.querySelector('.tab-content.active');
  if (activeTab) {
    if (activeTab.id === 'tab-vacancies') loadVacancies();
    if (activeTab.id === 'tab-applications') loadApplications();
    if (activeTab.id === 'tab-messages') loadMessages();
    if (activeTab.id === 'tab-logs') loadLogs();
  }
}

// ── Load Stats & Render Dashboard ──────────────────────────
async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderSessions(data.sessions);
    renderKPIs(data.summary);
    renderFunnel(data.funnel);
    renderTimelineChart(data.timeline);
    renderReasons(data.reasons);
  } catch (err) {
    console.error('Error loading stats:', err);
  }
}

function renderSessions(sessions) {
  if (!sessions) return;

  const hhPill = document.getElementById('hhSessionPill');
  if (hhPill && sessions.hh) {
    hhPill.className = `status-pill ${sessions.hh.status}`;
    const txt = sessions.hh.status === 'valid' ? 'HH: Активна' : sessions.hh.status === 'warning' ? 'HH: Истекает' : 'HH: Протухла';
    hhPill.querySelector('.status-text').textContent = `${txt} (${sessions.hh.age_hours ? sessions.hh.age_hours + 'ч' : 'нет'})`;
  }

  const habrPill = document.getElementById('habrSessionPill');
  if (habrPill && sessions.habr) {
    habrPill.className = `status-pill ${sessions.habr.status}`;
    const txt = sessions.habr.exists ? 'Хабр: Сессия есть' : 'Хабр: Нет';
    habrPill.querySelector('.status-text').textContent = txt;
  }
}

function renderKPIs(summary) {
  if (!summary) return;

  document.getElementById('kpiTotalVacancies').textContent = summary.total_vacancies.toLocaleString();
  document.getElementById('kpiNewVacancies').textContent = summary.new_vacancies.toLocaleString();
  document.getElementById('kpiApprovedVacancies').textContent = summary.approved_vacancies.toLocaleString();
  document.getElementById('kpiRejectedVacancies').textContent = summary.rejected_vacancies.toLocaleString();

  document.getElementById('kpiTodaySent').textContent = summary.sent_today;
  document.getElementById('kpiTodayFailed').textContent = summary.failed_today;

  document.getElementById('kpiTotalSent').textContent = summary.total_sent;
  document.getElementById('kpiTotalViewed').textContent = summary.total_viewed;
  document.getElementById('kpiTotalInvited').textContent = summary.total_invited;

  const viewRate = summary.total_sent > 0 ? Math.round((summary.total_viewed / summary.total_sent) * 100) : 0;
  const invRate = summary.total_sent > 0 ? Math.round((summary.total_invited / summary.total_sent) * 100) : 0;

  document.getElementById('kpiViewRate').textContent = `${viewRate}%`;
  document.getElementById('kpiInvRate').textContent = `${invRate}%`;

  document.getElementById('kpiAvgScore').textContent = summary.avg_ai_score ? `${summary.avg_ai_score}` : '—';
}

function renderFunnel(funnel) {
  const container = document.getElementById('funnelList');
  if (!container || !funnel) return;

  container.innerHTML = '';
  const maxCount = funnel.length > 0 ? funnel[0].count || 1 : 1;

  funnel.forEach(step => {
    const pct = Math.max(8, Math.min(100, Math.round((step.count / maxCount) * 100)));
    const el = document.createElement('div');
    el.className = 'funnel-step';
    el.innerHTML = `
      <div class="funnel-step-bar" style="width: ${pct}%"></div>
      <div class="funnel-step-content">
        <span class="funnel-step-label">${step.stage}</span>
        <div class="funnel-step-numbers">
          <span class="funnel-step-count">${step.count.toLocaleString()}</span>
          <span class="funnel-step-rate">${step.rate}</span>
        </div>
      </div>
    `;
    container.appendChild(el);
  });
}

function renderReasons(reasons) {
  const container = document.getElementById('reasonsList');
  if (!container || !reasons) return;

  container.innerHTML = '';
  if (reasons.length === 0) {
    container.innerHTML = '<div class="empty-box">Нет данных по отказам</div>';
    return;
  }

  const maxCount = reasons[0].count || 1;
  reasons.forEach(r => {
    const pct = Math.round((r.count / maxCount) * 100);
    const item = document.createElement('div');
    item.style.marginBottom = '10px';
    item.innerHTML = `
      <div style="display: flex; justify-content: space-between; font-size: 0.82rem; margin-bottom: 4px;">
        <span style="color: var(--text-muted);">${r.reason}</span>
        <strong style="color: var(--text-main); font-family: var(--font-mono);">${r.count}</strong>
      </div>
      <div style="background: rgba(255,255,255,0.06); height: 6px; border-radius: 3px; overflow: hidden;">
        <div style="background: linear-gradient(90deg, #f59e0b, #ef4444); height: 100%; width: ${pct}%; border-radius: 3px;"></div>
      </div>
    `;
    container.appendChild(item);
  });
}

// ── HTML5 Canvas Timeline Chart ────────────────────────────
function renderTimelineChart(timeline) {
  const canvas = document.getElementById('timelineChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  // Handle high-DPI displays
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;

  ctx.clearRect(0, 0, w, h);

  if (!timeline || timeline.length === 0) {
    ctx.fillStyle = '#64748b';
    ctx.font = '13px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Нет данных за последние 14 дней', w / 2, h / 2);
    return;
  }

  const padLeft = 36;
  const padRight = 20;
  const padBottom = 26;
  const padTop = 16;
  const plotW = w - padLeft - padRight;
  const plotH = h - padTop - padBottom;

  const maxVal = Math.max(10, ...timeline.map(d => Math.max(d.sent || 0, d.failed || 0, d.viewed || 0)));

  // Grid lines
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padTop + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(w - padRight, y);
    ctx.stroke();

    const val = Math.round(maxVal - (maxVal / 4) * i);
    ctx.fillStyle = '#64748b';
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.textAlign = 'right';
    ctx.fillText(val, padLeft - 8, y + 3);
  }

  const stepX = timeline.length > 1 ? plotW / (timeline.length - 1) : plotW;

  // Draw series helper
  function drawLine(key, strokeColor, fillColor) {
    ctx.beginPath();
    timeline.forEach((pt, idx) => {
      const x = padLeft + idx * stepX;
      const y = padTop + plotH - ((pt[key] || 0) / maxVal) * plotH;
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });

    if (fillColor) {
      ctx.lineTo(padLeft + (timeline.length - 1) * stepX, padTop + plotH);
      ctx.lineTo(padLeft, padTop + plotH);
      ctx.fillStyle = fillColor;
      ctx.fill();
    }

    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = 2.5;
    ctx.stroke();

    // Draw dots
    timeline.forEach((pt, idx) => {
      const x = padLeft + idx * stepX;
      const y = padTop + plotH - ((pt[key] || 0) / maxVal) * plotH;
      ctx.fillStyle = strokeColor;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  // Draw Sent Series (Emerald)
  drawLine('sent', '#10b981', 'rgba(16, 185, 129, 0.1)');
  // Draw Failed Series (Rose)
  drawLine('failed', '#ef4444', null);
  // Draw Viewed Series (Cyan)
  drawLine('viewed', '#06b6d4', null);

  // X Axis dates
  ctx.fillStyle = '#64748b';
  ctx.font = '10px JetBrains Mono, monospace';
  ctx.textAlign = 'center';
  timeline.forEach((pt, idx) => {
    if (idx % 2 === 0 || idx === timeline.length - 1) {
      const x = padLeft + idx * stepX;
      const label = pt.date.slice(5); // MM-DD
      ctx.fillText(label, x, h - 6);
    }
  });
}

// ── Load Vacancies Tab ──────────────────────────────────────
async function loadVacancies() {
  const container = document.getElementById('vacanciesList');
  if (!container) return;

  container.innerHTML = '<div class="empty-box">Загрузка вакансий...</div>';

  try {
    const params = new URLSearchParams({
      page: currentVacanciesPage,
      limit: 20,
      status: currentVacancyStatus,
      search: currentVacancySearch,
    });

    const res = await fetch(`/api/vacancies?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!data.items || data.items.length === 0) {
      container.innerHTML = '<div class="empty-box">Вакансий по заданным фильтрам не найдено.</div>';
      renderPagination(0, 1);
      return;
    }

    container.innerHTML = '';
    data.items.forEach(v => {
      const item = document.createElement('div');
      item.className = 'vacancy-item';

      let salaryText = '';
      if (v.salary_from || v.salary_to) {
        salaryText = `💰 ${v.salary_from ? 'от ' + v.salary_from.toLocaleString() : ''} ${v.salary_to ? 'до ' + v.salary_to.toLocaleString() : ''} ${v.salary_currency || 'RUB'}`;
      }

      let scoreClass = 'low';
      if (v.ai_score >= 60) scoreClass = 'high';
      else if (v.ai_score >= 35) scoreClass = 'medium';

      item.innerHTML = `
        <div class="vac-main">
          <div class="vac-title">
            <a href="${v.url}" target="_blank" rel="noopener noreferrer">${v.title} ↗</a>
          </div>
          <div class="vac-meta">
            <span>🏢 <strong>${v.company_name}</strong></span>
            <span>📍 ${v.location || (v.is_remote ? 'Удалённо' : 'Не указан')}</span>
            ${salaryText ? `<span>${salaryText}</span>` : ''}
            <span>🕒 ${v.created_at || '—'}</span>
          </div>
          ${v.ai_reason ? `<div class="vac-reason">${v.ai_reason}</div>` : ''}
        </div>
        <div class="vac-side">
          <span class="score-badge ${scoreClass}">${v.ai_score !== null ? v.ai_score : '—'}</span>
          <span class="status-tag ${v.status.toLowerCase()}">${v.status}</span>
        </div>
      `;
      container.appendChild(item);
    });

    renderPagination(data.total, data.pages);
  } catch (err) {
    container.innerHTML = `<div class="empty-box" style="color: var(--danger);">Ошибка загрузки: ${err.message}</div>`;
  }
}

function renderPagination(total, pages) {
  const infoEl = document.getElementById('pagInfo');
  const prevBtn = document.getElementById('pagPrev');
  const nextBtn = document.getElementById('pagNext');

  if (infoEl) infoEl.textContent = `Страница ${currentVacanciesPage} из ${pages || 1} (Всего: ${total})`;
  if (prevBtn) {
    prevBtn.disabled = currentVacanciesPage <= 1;
    prevBtn.onclick = () => {
      if (currentVacanciesPage > 1) {
        currentVacanciesPage--;
        loadVacancies();
      }
    };
  }
  if (nextBtn) {
    nextBtn.disabled = currentVacanciesPage >= pages;
    nextBtn.onclick = () => {
      if (currentVacanciesPage < pages) {
        currentVacanciesPage++;
        loadVacancies();
      }
    };
  }
}

// ── Load Applications Tab ───────────────────────────────────
async function loadApplications() {
  const container = document.getElementById('applicationsList');
  if (!container) return;

  container.innerHTML = '<div class="empty-box">Загрузка откликов...</div>';

  try {
    const res = await fetch('/api/applications?limit=50');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!data.items || data.items.length === 0) {
      container.innerHTML = '<div class="empty-box">Откликов пока нет.</div>';
      return;
    }

    container.innerHTML = '';
    data.items.forEach(a => {
      const item = document.createElement('div');
      item.className = 'vacancy-item';

      let statusColor = 'info';
      if (a.status === 'sent') statusColor = 'status-tag applied';
      else if (a.status === 'viewed') statusColor = 'status-tag approved';
      else if (a.status === 'invited') statusColor = 'status-tag approved';
      else if (a.status === 'rejected') statusColor = 'status-tag rejected';
      else if (a.status === 'failed') statusColor = 'status-tag rejected';

      item.innerHTML = `
        <div class="vac-main">
          <div class="vac-title">
            <a href="${a.vacancy_url}" target="_blank" rel="noopener noreferrer">${a.vacancy_title} ↗</a>
          </div>
          <div class="vac-meta">
            <span>🏢 ${a.company_name}</span>
            <span>🌐 Платформа: <strong>${a.platform.toUpperCase()}</strong></span>
            <span>🕒 Дата: ${a.created_at || '—'}</span>
            <span>Попыток: ${a.attempt_count}</span>
          </div>
          ${a.error_message ? `<div class="vac-reason" style="color: var(--danger);">⚠️ ${a.error_message}</div>` : ''}
        </div>
        <div class="vac-side">
          <span class="${statusColor}">${a.status.toUpperCase()}</span>
        </div>
      `;
      container.appendChild(item);
    });
  } catch (err) {
    container.innerHTML = `<div class="empty-box" style="color: var(--danger);">Ошибка: ${err.message}</div>`;
  }
}

// ── Load Messages Tab ───────────────────────────────────────
async function loadMessages() {
  const container = document.getElementById('messagesList');
  if (!container) return;

  container.innerHTML = '<div class="empty-box">Загрузка сообщений...</div>';

  try {
    const res = await fetch('/api/messages?limit=30');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!data.items || data.items.length === 0) {
      container.innerHTML = '<div class="empty-box">Сообщений от рекрутеров пока нет.</div>';
      return;
    }

    container.innerHTML = '';
    data.items.forEach(m => {
      const item = document.createElement('div');
      item.className = 'vacancy-item';
      item.innerHTML = `
        <div class="vac-main">
          <div class="vac-title" style="font-size: 0.95rem;">
            ${m.sender_name} <span style="font-size: 0.8rem; color: var(--text-muted); font-weight: 400;">(${m.sender_company})</span>
          </div>
          <div style="background: rgba(0,0,0,0.3); padding: 10px 14px; border-radius: var(--radius-sm); margin: 8px 0; font-size: 0.88rem; color: #e2e8f0;">
            ${m.text || '<i>[Без текста]</i>'}
          </div>
          <div class="vac-meta">
            <span>🌐 ${m.platform.toUpperCase()}</span>
            <span>🕒 ${m.created_at || '—'}</span>
          </div>
        </div>
      `;
      container.appendChild(item);
    });
  } catch (err) {
    container.innerHTML = `<div class="empty-box" style="color: var(--danger);">Ошибка: ${err.message}</div>`;
  }
}

// ── Load Logs Tab ───────────────────────────────────────────
async function loadLogs() {
  const container = document.getElementById('logsContainer');
  if (!container) return;

  const levelSelect = document.getElementById('logLevelFilter');
  const level = levelSelect ? levelSelect.value : 'all';

  try {
    const res = await fetch(`/api/logs?lines=120&level=${level}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!data.items || data.items.length === 0) {
      container.innerHTML = '<div class="empty-box">Логов нет или файл пуст.</div>';
      return;
    }

    container.innerHTML = '';
    data.items.forEach(log => {
      const lineEl = document.createElement('div');
      lineEl.className = `log-line ${log.level}`;
      lineEl.textContent = log.text;
      container.appendChild(lineEl);
    });
  } catch (err) {
    container.innerHTML = `<div class="empty-box" style="color: var(--danger);">Ошибка: ${err.message}</div>`;
  }
}
