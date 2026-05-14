/* Avito Comparator — клиентский JS
 *
 * Что делает:
 * 1) Регистрирует service worker (PWA).
 * 2) Управляет переключателем темы (auto / light / dark).
 * 3) Подключается к SocketIO и слушает события прогресса парсинга.
 * 4) Перехватывает submit формы поиска, отправляет multipart/form-data на /search,
 *    показывает прогресс-бар и при `done` редиректит на /result/<share_id>.
 * 5) Авто-подсказывает район по выбранному микрорайону.
 * 6) Конвертирует слайдер area_tolerance_pct -> поле area_tolerance (доля).
 */

(function () {
  'use strict';

  // ---------- 1. Service Worker (PWA) ----------
  if ('serviceWorker' in navigator && location.protocol !== 'file:') {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch((err) => {
        console.debug('SW registration failed:', err);
      });
    });
  }

  // ---------- 2. Theme toggle ----------
  const THEME_KEY = 'avito-cmp-theme';

  function applyTheme(theme) {
    const html = document.documentElement;
    if (theme === 'auto') {
      const dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      html.setAttribute('data-bs-theme', dark ? 'dark' : 'light');
    } else {
      html.setAttribute('data-bs-theme', theme);
    }
    const lightIcon = document.querySelector('[data-theme-icon-light]');
    const darkIcon = document.querySelector('[data-theme-icon-dark]');
    if (lightIcon && darkIcon) {
      const isDark = html.getAttribute('data-bs-theme') === 'dark';
      lightIcon.hidden = isDark;
      darkIcon.hidden = !isDark;
    }
  }

  const savedTheme = localStorage.getItem(THEME_KEY) || 'auto';
  applyTheme(savedTheme);

  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if ((localStorage.getItem(THEME_KEY) || 'auto') === 'auto') applyTheme('auto');
    });
  }

  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-bs-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });

  // ---------- 3. Form helpers ----------
  const districtSelect = document.getElementById('district');
  const districtHint = document.getElementById('district-hint');
  districtSelect?.addEventListener('change', () => {
    const opt = districtSelect.options[districtSelect.selectedIndex];
    const parentDistrict = opt?.dataset?.district;
    if (parentDistrict) {
      districtHint.textContent = `Микрорайон относится к ${parentDistrict} району.`;
    } else {
      districtHint.textContent = '';
    }
  });

  const tolPct = document.getElementById('area_tolerance_pct');
  const tolHidden = document.getElementById('area_tolerance');
  const tolLabel = document.getElementById('area_tolerance_v');
  if (tolPct && tolHidden && tolLabel) {
    const sync = () => {
      const pct = Number(tolPct.value || 15);
      tolLabel.textContent = String(pct);
      tolHidden.value = (pct / 100).toFixed(2);
    };
    tolPct.addEventListener('input', sync);
    sync();
  }

  const radius = document.getElementById('radius_km');
  const radiusLabel = document.getElementById('radius_v');
  if (radius && radiusLabel) {
    const sync = () => { radiusLabel.textContent = Number(radius.value).toFixed(1); };
    radius.addEventListener('input', sync);
    sync();
  }

  // Простая нормализация цены: убираем пробелы перед сабмитом.
  const priceInput = document.getElementById('price');
  priceInput?.addEventListener('blur', () => {
    const digits = (priceInput.value || '').replace(/[^\d]/g, '');
    if (digits) {
      priceInput.value = Number(digits).toLocaleString('ru-RU');
    }
  });

  // ---------- 4. SocketIO + form submit ----------
  const form = document.getElementById('search-form');
  const progressCard = document.getElementById('progress-card');
  const progressBar = document.getElementById('progress-bar');
  const progressMsg = document.getElementById('progress-message');
  const errorCard = document.getElementById('error-card');
  const errorMsg = document.getElementById('error-message');
  const submitBtn = document.getElementById('submit-btn');

  let socket = null;
  function connectSocket(sid) {
    if (socket || typeof io === 'undefined') return;
    socket = io({ transports: ['websocket', 'polling'] });
    socket.on('connect', () => {
      socket.emit('subscribe', { sid });
    });
    socket.on('progress', (data) => {
      if (!progressBar) return;
      const pct = Math.max(0, Math.min(100, Number(data.percent || 0)));
      progressBar.style.width = `${pct}%`;
      progressBar.textContent = `${pct}%`;
      progressBar.setAttribute('aria-valuenow', String(pct));
      if (progressMsg) progressMsg.textContent = data.message || '';
    });
    socket.on('done', (data) => {
      if (data && data.redirect) {
        window.location.href = data.redirect;
      }
    });
    socket.on('error', (data) => showError((data && data.message) || 'Неизвестная ошибка'));
    socket.on('connect_error', () => showError('Сервер недоступен. Проверьте подключение.'));
  }

  function showError(msg) {
    if (!errorCard || !errorMsg) {
      alert(msg);
      return;
    }
    errorMsg.textContent = msg;
    errorCard.classList.remove('d-none');
    if (progressCard) progressCard.hidden = true;
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Найти аналоги';
    }
  }

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      return;
    }

    // Очистим цену от пробелов перед отправкой
    if (priceInput) {
      priceInput.value = (priceInput.value || '').replace(/\s+/g, '');
    }

    if (errorCard) errorCard.classList.add('d-none');
    if (progressCard) progressCard.hidden = false;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Идёт парсинг…';
    }

    const formData = new FormData(form);
    const sid = formData.get('sid');
    connectSocket(sid);

    const csrfToken = formData.get('csrf_token');

    try {
      const res = await fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
        credentials: 'same-origin',
      });
      if (res.status === 429) {
        showError('Слишком много запросов. Подождите минуту и попробуйте снова.');
        return;
      }
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const data = await res.json();
          if (data && data.error) msg = data.error;
        } catch (_) { /* ignore */ }
        showError(msg);
        return;
      }
      // Успешно — теперь ждём событий по сокету.
    } catch (err) {
      console.error(err);
      showError('Не удалось отправить форму: ' + (err.message || err));
    }
  });
})();
