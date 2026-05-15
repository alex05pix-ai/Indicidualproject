/**
 * Квартира-Компаратор — Клиентский JavaScript
 * Vanilla JS, без зависимостей (кроме Bootstrap, SocketIO, Chart.js)
 */

'use strict';

// === Тема (тёмная/светлая) ===
(function initTheme() {
    const saved = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-bs-theme', theme);
    updateThemeIcon(theme);
})();

function updateThemeIcon(theme) {
    const btn = document.getElementById('themeToggle');
    if (!btn) return;
    const icon = btn.querySelector('i');
    if (icon) {
        icon.className = theme === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
    }
}

document.addEventListener('DOMContentLoaded', function () {
    // Переключатель темы
    const themeBtn = document.getElementById('themeToggle');
    if (themeBtn) {
        themeBtn.addEventListener('click', function () {
            const current = document.documentElement.getAttribute('data-bs-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-bs-theme', next);
            localStorage.setItem('theme', next);
            updateThemeIcon(next);
        });
    }

    // Форма поиска
    const searchForm = document.getElementById('searchForm');
    if (searchForm) {
        searchForm.addEventListener('submit', handleSearchSubmit);
    }

    // Автозаполнение
    const autofillBtn = document.getElementById('autofillBtn');
    if (autofillBtn) {
        autofillBtn.addEventListener('click', handleAutofill);
    }

    // История
    const historyBtn = document.getElementById('historyBtn');
    if (historyBtn) {
        historyBtn.addEventListener('click', loadHistory);
    }

    // Поделиться
    const shareBtn = document.getElementById('shareBtn');
    if (shareBtn) {
        shareBtn.addEventListener('click', handleShare);
    }

    // Форматирование цены при вводе
    const priceInput = document.getElementById('price');
    if (priceInput) {
        priceInput.addEventListener('input', function (e) {
            let value = e.target.value.replace(/[^\d]/g, '');
            if (value) {
                e.target.value = Number(value).toLocaleString('ru-RU');
            }
        });
    }

    // Регистрация Service Worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(function (err) {
            console.log('SW registration failed:', err);
        });
    }
});

/**
 * Обработка отправки формы поиска
 */
async function handleSearchSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const submitBtn = document.getElementById('submitBtn');

    // Валидация
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }

    // Блокируем кнопку
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Запуск...';

    // Собираем данные
    const formData = {
        address: document.getElementById('address').value.trim(),
        district: document.getElementById('district').value,
        rooms: document.getElementById('rooms').value,
        price: document.getElementById('price').value.replace(/[^\d]/g, ''),
        total_area: document.getElementById('total_area').value || null,
        kitchen_area: document.getElementById('kitchen_area').value || null,
        floor: document.getElementById('floor').value || null,
        total_floors: document.getElementById('total_floors').value || null,
        year_built: document.getElementById('year_built').value || null,
        area_tolerance: (parseFloat(document.getElementById('area_tolerance').value) || 15) / 100,
        max_distance: parseFloat(document.getElementById('max_distance').value) || 2.0,
        search_depth: parseInt(document.getElementById('search_depth').value) || 10,
    };

    try {
        const response = await fetch('/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData),
        });

        const data = await response.json();

        if (response.ok && data.query_id) {
            // Переходим на страницу результатов
            window.location.href = '/results/' + data.query_id;
        } else {
            showAlert(data.error || 'Произошла ошибка');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="bi bi-search"></i> Найти аналоги и сравнить';
        }
    } catch (err) {
        showAlert('Ошибка сети. Проверьте подключение.');
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="bi bi-search"></i> Найти аналоги и сравнить';
    }
}

/**
 * Автозаполнение из ссылки Avito
 */
async function handleAutofill() {
    const urlInput = document.getElementById('avitoUrl');
    const url = urlInput.value.trim();
    const btn = document.getElementById('autofillBtn');

    if (!url) {
        showAlert('Вставьте ссылку на объявление Avito');
        return;
    }

    if (!url.includes('avito.ru')) {
        showAlert('Ссылка должна быть с сайта avito.ru');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
        const response = await fetch('/autofill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url }),
        });

        const data = await response.json();

        if (response.ok) {
            // Заполняем форму
            if (data.address) document.getElementById('address').value = data.address;
            if (data.rooms) {
                const roomsSelect = document.getElementById('rooms');
                const roomsValue = data.rooms === 'studio' ? 'studio' :
                    (parseInt(data.rooms) >= 4 ? '4+' : data.rooms);
                roomsSelect.value = roomsValue;
            }
            if (data.price) {
                document.getElementById('price').value = Number(data.price).toLocaleString('ru-RU');
            }
            if (data.total_area) document.getElementById('total_area').value = data.total_area;
            if (data.kitchen_area) document.getElementById('kitchen_area').value = data.kitchen_area;
            if (data.floor) document.getElementById('floor').value = data.floor;
            if (data.total_floors) document.getElementById('total_floors').value = data.total_floors;
            if (data.year_built) document.getElementById('year_built').value = data.year_built;

            showAlert('Данные заполнены из объявления!', 'success');
        } else {
            showAlert(data.error || 'Не удалось получить данные');
        }
    } catch (err) {
        showAlert('Ошибка сети при автозаполнении');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-magic"></i> Заполнить';
    }
}

/**
 * Отслеживание прогресса парсинга через WebSocket
 */
function initProgressTracking(queryId) {
    const socket = io();
    const progressBar = document.getElementById('progressBar');
    const progressMsg = document.getElementById('progressMessage');
    let pollInterval = null;

    socket.on('connect', function () {
        socket.emit('subscribe', { query_id: queryId });
    });

    socket.on('progress', function (data) {
        if (data.query_id === queryId) {
            const pct = Math.round((data.current / data.total) * 100);
            if (progressBar) progressBar.style.width = pct + '%';
            if (progressMsg) progressMsg.textContent = data.message;
        }
    });

    socket.on('completed', function (data) {
        if (data.query_id === queryId) {
            window.location.reload();
        }
    });

    socket.on('error', function (data) {
        if (data.query_id === queryId) {
            window.location.reload();
        }
    });

    // Fallback: polling каждые 5 секунд
    pollInterval = setInterval(async function () {
        try {
            const resp = await fetch('/status/' + queryId);
            const status = await resp.json();
            if (status.status === 'completed' || status.status === 'error') {
                clearInterval(pollInterval);
                window.location.reload();
            }
        } catch (e) { /* игнорируем */ }
    }, 5000);
}

/**
 * Загрузка истории запросов
 */
async function loadHistory() {
    const modal = new bootstrap.Modal(document.getElementById('historyModal'));
    modal.show();

    const listEl = document.getElementById('historyList');
    listEl.innerHTML = '<p class="text-muted text-center">Загрузка...</p>';

    try {
        const response = await fetch('/history');
        const data = await response.json();

        if (data.length === 0) {
            listEl.innerHTML = '<p class="text-muted text-center">История пуста</p>';
            return;
        }

        listEl.innerHTML = data.map(function (item) {
            const date = item.created_at ? new Date(item.created_at).toLocaleString('ru-RU') : '';
            const price = item.price ? Number(item.price).toLocaleString('ru-RU') + ' ₽' : '';
            return '<a href="/results/' + item.id + '" class="list-group-item list-group-item-action">' +
                '<div class="d-flex justify-content-between align-items-center">' +
                '<div><strong>' + escapeHtml(item.address) + '</strong>' +
                '<br><small class="text-muted">' + item.rooms + '-комн. | ' + price +
                ' | Аналогов: ' + item.analogs_count + '</small></div>' +
                '<small class="text-muted">' + date + '</small></div></a>';
        }).join('');
    } catch (err) {
        listEl.innerHTML = '<p class="text-danger text-center">Ошибка загрузки</p>';
    }
}

/**
 * Поделиться результатом
 */
function handleShare() {
    const btn = document.getElementById('shareBtn');
    const queryId = btn.getAttribute('data-query-id');
    const shareUrl = window.location.origin + '/shared/' + queryId;

    if (navigator.clipboard) {
        navigator.clipboard.writeText(shareUrl).then(function () {
            const toast = new bootstrap.Toast(document.getElementById('shareToast'));
            toast.show();
        });
    } else {
        // Fallback
        const input = document.createElement('input');
        input.value = shareUrl;
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        document.body.removeChild(input);
        alert('Ссылка скопирована: ' + shareUrl);
    }
}

/**
 * Рендеринг гистограммы цен
 */
function renderHistogram(data, userPrice) {
    const canvas = document.getElementById('priceChart');
    if (!canvas || !data || data.length === 0) return;

    const ctx = canvas.getContext('2d');
    const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';

    const labels = data.map(function (_, i) { return 'Аналог ' + (i + 1); });
    const colors = data.map(function (val) {
        if (userPrice && Math.abs(val - userPrice) / userPrice < 0.05) return '#ffc107';
        return val > (userPrice || Infinity) ? '#dc3545' : '#198754';
    });

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Цена за м² (₽)',
                data: data,
                backgroundColor: colors,
                borderRadius: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
                annotation: userPrice ? {
                    annotations: {
                        line1: {
                            type: 'line',
                            yMin: userPrice,
                            yMax: userPrice,
                            borderColor: '#0d6efd',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            label: {
                                content: 'Ваша цена/м²',
                                enabled: true,
                            }
                        }
                    }
                } : {}
            },
            scales: {
                y: {
                    beginAtZero: false,
                    grid: { color: isDark ? '#333' : '#eee' },
                    ticks: {
                        callback: function (val) {
                            return val.toLocaleString('ru-RU') + ' ₽';
                        }
                    }
                },
                x: {
                    grid: { display: false }
                }
            }
        }
    });

    // Добавляем линию "ваша цена" вручную если нет плагина аннотаций
    if (userPrice) {
        const chartArea = canvas.getBoundingClientRect();
        // Рисуем подпись под графиком
        const legend = document.createElement('div');
        legend.className = 'text-center mt-2 small';
        legend.innerHTML = '<span class="badge bg-primary">—</span> Ваша цена: ' +
            userPrice.toLocaleString('ru-RU') + ' ₽/м² | ' +
            '<span class="badge bg-success">■</span> Ниже | ' +
            '<span class="badge bg-danger">■</span> Выше';
        canvas.parentNode.appendChild(legend);
    }
}

/**
 * Показать alert-уведомление
 */
function showAlert(message, type) {
    type = type || 'danger';
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-' + type + ' alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-5';
    alertDiv.style.zIndex = '9999';
    alertDiv.style.maxWidth = '90%';
    alertDiv.innerHTML = message +
        '<button type="button" class="btn-close" data-bs-dismiss="alert"></button>';
    document.body.appendChild(alertDiv);

    setTimeout(function () {
        if (alertDiv.parentNode) alertDiv.remove();
    }, 5000);
}

/**
 * Экранирование HTML
 */
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
