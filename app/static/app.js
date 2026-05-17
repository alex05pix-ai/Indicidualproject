/* ============================================
   Квартира-Компаратор — Frontend JS
   Vanilla JS, no frameworks
   ============================================ */

(function () {
    'use strict';

    // -------------------------------------------
    // Theme Toggle (auto-detect + localStorage)
    // -------------------------------------------
    const THEME_KEY = 'kc-theme';

    function getPreferredTheme() {
        const stored = localStorage.getItem(THEME_KEY);
        if (stored) return stored;
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-bs-theme', theme);
        const btn = document.getElementById('btnThemeToggle');
        if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
    }

    function initTheme() {
        applyTheme(getPreferredTheme());
        const btn = document.getElementById('btnThemeToggle');
        if (btn) {
            btn.addEventListener('click', function () {
                const current = document.documentElement.getAttribute('data-bs-theme');
                const next = current === 'dark' ? 'light' : 'dark';
                localStorage.setItem(THEME_KEY, next);
                applyTheme(next);
            });
        }
        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
            if (!localStorage.getItem(THEME_KEY)) {
                applyTheme(e.matches ? 'dark' : 'light');
            }
        });
    }

    // -------------------------------------------
    // Price Formatting
    // -------------------------------------------
    function formatPrice(value) {
        const num = value.replace(/\D/g, '');
        if (!num) return '';
        return Number(num).toLocaleString('ru-RU');
    }

    function initPriceInputs() {
        document.addEventListener('input', function (e) {
            if (e.target.classList.contains('price-input')) {
                const pos = e.target.selectionStart;
                const oldLen = e.target.value.length;
                e.target.value = formatPrice(e.target.value);
                const newLen = e.target.value.length;
                e.target.setSelectionRange(pos + (newLen - oldLen), pos + (newLen - oldLen));
            }
        });
    }

    // -------------------------------------------
    // Mode Switching (Manual / Auto)
    // -------------------------------------------
    function initModeSwitching() {
        const tabManual = document.getElementById('tab-manual');
        const tabAuto = document.getElementById('tab-auto');
        const formMode = document.getElementById('formMode');
        const submitText = document.getElementById('submitText');

        if (tabManual) {
            tabManual.addEventListener('shown.bs.tab', function () {
                if (formMode) formMode.value = 'manual';
                if (submitText) submitText.textContent = 'Рассчитать';
            });
        }
        if (tabAuto) {
            tabAuto.addEventListener('shown.bs.tab', function () {
                if (formMode) formMode.value = 'auto';
                if (submitText) submitText.textContent = 'Найти аналоги';
            });
        }
    }

    // -------------------------------------------
    // Dynamic Analog Rows (Manual Mode)
    // -------------------------------------------
    function initAnalogRows() {
        const container = document.getElementById('analogsContainer');
        const btnAdd = document.getElementById('btnAddAnalog');

        if (!container || !btnAdd) return;

        btnAdd.addEventListener('click', function () {
            const row = document.createElement('div');
            row.className = 'analog-row row g-2 mb-2 align-items-end';
            row.innerHTML = `
                <div class="col">
                    <label class="form-label small">Цена, ₽</label>
                    <input type="text" class="form-control form-control-sm price-input" name="analog_price[]" placeholder="4 800 000">
                </div>
                <div class="col">
                    <label class="form-label small">Площадь, м²</label>
                    <input type="number" class="form-control form-control-sm" name="analog_area[]" placeholder="60" step="0.1" min="1">
                </div>
                <div class="col-auto">
                    <button type="button" class="btn btn-sm btn-outline-danger btn-remove-analog" title="Удалить">✕</button>
                </div>
            `;
            container.appendChild(row);
        });

        // Event delegation for remove buttons
        container.addEventListener('click', function (e) {
            if (e.target.classList.contains('btn-remove-analog')) {
                const rows = container.querySelectorAll('.analog-row');
                if (rows.length > 1) {
                    e.target.closest('.analog-row').remove();
                }
            }
        });
    }

    // -------------------------------------------
    // Form Submission
    // -------------------------------------------
    function initFormSubmission() {
        const form = document.getElementById('searchForm');
        if (!form) return;

        form.addEventListener('submit', function (e) {
            e.preventDefault();

            const submitBtn = document.getElementById('btnSubmit');
            const spinner = document.getElementById('submitSpinner');
            const submitText = document.getElementById('submitText');

            // Disable button, show spinner
            if (submitBtn) submitBtn.disabled = true;
            if (spinner) spinner.classList.remove('d-none');
            if (submitText) submitText.textContent = 'Обработка...';

            // Collect form data
            const formData = new FormData(form);

            // Clean price values (remove spaces)
            const priceFields = ['price'];
            priceFields.forEach(function (field) {
                const val = formData.get(field);
                if (val) formData.set(field, val.replace(/\s/g, ''));
            });

            // Clean analog prices
            const analogPrices = formData.getAll('analog_price[]');
            formData.delete('analog_price[]');
            analogPrices.forEach(function (p) {
                formData.append('analog_price[]', p.replace(/\s/g, ''));
            });

            fetch('/search', {
                method: 'POST',
                body: formData
            })
                .then(function (response) {
                    return response.json();
                })
                .then(function (data) {
                    if (data.status === 'processing' && data.id) {
                        // Show processing modal and start polling
                        showProcessingModal();
                        pollStatus(data.id);
                    } else if (data.redirect) {
                        // Immediate redirect (manual mode)
                        window.location.href = data.redirect;
                    } else if (data.error) {
                        showError(data.error);
                        resetSubmitButton();
                    } else {
                        // Fallback: try redirect
                        if (data.id) {
                            window.location.href = '/results/' + data.id;
                        } else {
                            resetSubmitButton();
                        }
                    }
                })
                .catch(function (err) {
                    console.error('Submit error:', err);
                    showError('Ошибка соединения. Попробуйте ещё раз.');
                    resetSubmitButton();
                });
        });
    }

    function resetSubmitButton() {
        const submitBtn = document.getElementById('btnSubmit');
        const spinner = document.getElementById('submitSpinner');
        const submitText = document.getElementById('submitText');
        if (submitBtn) submitBtn.disabled = false;
        if (spinner) spinner.classList.add('d-none');
        if (submitText) {
            const mode = document.getElementById('formMode');
            submitText.textContent = mode && mode.value === 'auto' ? 'Найти аналоги' : 'Рассчитать';
        }
    }

    function showError(message) {
        // Create temporary alert
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-5';
        alert.style.zIndex = '9999';
        alert.innerHTML = `
            <strong>Ошибка:</strong> ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        document.body.appendChild(alert);
        setTimeout(function () {
            alert.remove();
        }, 5000);
    }

    // -------------------------------------------
    // Processing Modal & Polling
    // -------------------------------------------
    function showProcessingModal() {
        const modalEl = document.getElementById('processingModal');
        if (modalEl) {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
        }
    }

    function pollStatus(searchId) {
        const statusEl = document.getElementById('processingStatus');
        let attempts = 0;
        const maxAttempts = 100; // ~5 minutes max

        const interval = setInterval(function () {
            attempts++;
            if (attempts > maxAttempts) {
                clearInterval(interval);
                showError('Превышено время ожидания. Попробуйте ещё раз.');
                hideProcessingModal();
                resetSubmitButton();
                return;
            }

            fetch('/status/' + searchId)
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (statusEl && data.message) {
                        statusEl.textContent = data.message;
                    }

                    if (data.status === 'done') {
                        clearInterval(interval);
                        window.location.href = '/results/' + searchId;
                    } else if (data.status === 'error') {
                        clearInterval(interval);
                        hideProcessingModal();
                        showError(data.message || 'Ошибка при поиске аналогов');
                        resetSubmitButton();
                    }
                })
                .catch(function () {
                    // Network error — keep polling
                });
        }, 3000);
    }

    function hideProcessingModal() {
        const modalEl = document.getElementById('processingModal');
        if (modalEl) {
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();
        }
    }

    // -------------------------------------------
    // History Modal
    // -------------------------------------------
    function initHistory() {
        const historyModal = document.getElementById('historyModal');
        if (!historyModal) return;

        historyModal.addEventListener('show.bs.modal', function () {
            const body = document.getElementById('historyBody');
            if (!body) return;
            body.innerHTML = '<div class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm"></div> Загрузка...</div>';

            fetch('/history')
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!data || data.length === 0) {
                        body.innerHTML = '<div class="text-center text-muted py-4">История пуста</div>';
                        return;
                    }
                    let html = '<div class="list-group list-group-flush">';
                    data.forEach(function (item) {
                        html += `
                            <a href="/results/${item.id}" class="list-group-item list-group-item-action">
                                <div class="d-flex justify-content-between align-items-center">
                                    <div>
                                        <div class="fw-semibold">${item.address || '—'}</div>
                                        <small class="text-muted">${item.rooms || '—'} комн. · ${item.date || ''}</small>
                                    </div>
                                    <span class="badge bg-primary rounded-pill">${item.total || 0} аналогов</span>
                                </div>
                            </a>
                        `;
                    });
                    html += '</div>';
                    body.innerHTML = html;
                })
                .catch(function () {
                    body.innerHTML = '<div class="text-center text-danger py-4">Ошибка загрузки</div>';
                });
        });
    }

    // -------------------------------------------
    // CSV Export
    // -------------------------------------------
    function initExportCSV() {
        const btn = document.getElementById('btnExportCSV');
        if (!btn) return;

        btn.addEventListener('click', function () {
            const table = document.getElementById('analogsTable');
            if (!table) return;

            const rows = table.querySelectorAll('tr');
            let csv = '\uFEFF'; // BOM for Excel UTF-8

            rows.forEach(function (row) {
                const cells = row.querySelectorAll('th, td');
                const rowData = [];
                cells.forEach(function (cell, idx) {
                    if (idx === cells.length - 1) return; // skip link column
                    let text = cell.textContent.trim().replace(/"/g, '""');
                    rowData.push('"' + text + '"');
                });
                csv += rowData.join(';') + '\n';
            });

            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'analogi_' + new Date().toISOString().slice(0, 10) + '.csv';
            a.click();
            URL.revokeObjectURL(url);
        });
    }

    // -------------------------------------------
    // Share Button
    // -------------------------------------------
    function initShare() {
        const btn = document.getElementById('btnShare');
        if (!btn) return;

        btn.addEventListener('click', function () {
            const url = window.location.href;

            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(url).then(function () {
                    showToast('Ссылка скопирована!');
                });
            } else {
                // Fallback
                const input = document.createElement('input');
                input.value = url;
                document.body.appendChild(input);
                input.select();
                document.execCommand('copy');
                document.body.removeChild(input);
                showToast('Ссылка скопирована!');
            }
        });
    }

    function showToast(message) {
        const toast = document.createElement('div');
        toast.className = 'position-fixed bottom-0 end-0 p-3';
        toast.style.zIndex = '9999';
        toast.innerHTML = `
            <div class="toast show align-items-center text-bg-success border-0" role="alert">
                <div class="d-flex">
                    <div class="toast-body">${message}</div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
            </div>
        `;
        document.body.appendChild(toast);
        setTimeout(function () { toast.remove(); }, 3000);
    }

    // -------------------------------------------
    // Histogram (Chart.js)
    // -------------------------------------------
    window.renderHistogram = function (labels, values) {
        const canvas = document.getElementById('histogramChart');
        if (!canvas) return;

        const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
        const textColor = isDark ? '#ccc' : '#666';
        const gridColor = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.05)';

        new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Количество объектов',
                    data: values,
                    backgroundColor: 'rgba(13, 110, 253, 0.6)',
                    borderColor: 'rgba(13, 110, 253, 1)',
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: function (ctx) { return ctx[0].label + ' ₽/м²'; },
                            label: function (ctx) { return ctx.raw + ' объектов'; }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: textColor, font: { size: 11 } },
                        grid: { display: false },
                        title: { display: true, text: 'Цена за м², ₽', color: textColor }
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { color: textColor, stepSize: 1 },
                        grid: { color: gridColor },
                        title: { display: true, text: 'Количество', color: textColor }
                    }
                }
            }
        });
    };

    // -------------------------------------------
    // Init
    // -------------------------------------------
    document.addEventListener('DOMContentLoaded', function () {
        initTheme();
        initPriceInputs();
        initModeSwitching();
        initAnalogRows();
        initFormSubmission();
        initHistory();
        initExportCSV();
        initShare();
    });

})();
