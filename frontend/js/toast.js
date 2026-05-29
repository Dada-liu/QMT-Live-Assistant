const ICONS = {
    success: '✓',
    error: '✕',
    info: 'ℹ',
    warning: '⚠',
};

const DURATIONS = {
    success: 3000,
    error: 5000,
    info: 4000,
    warning: 4000,
};

let _container = null;

function getContainer() {
    if (!_container) {
        _container = document.getElementById('toast-container');
    }
    return _container;
}

function createToast(message, type) {
    const container = getContainer();
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${ICONS[type]}</span>
        <span class="toast-msg">${message}</span>
        <button class="toast-close" aria-label="关闭">&times;</button>
    `;

    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => dismiss(toast));

    container.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add('toast-enter'));

    const duration = DURATIONS[type];
    toast._timer = setTimeout(() => dismiss(toast), duration);
}

function dismiss(toast) {
    clearTimeout(toast._timer);
    toast.classList.remove('toast-enter');
    toast.classList.add('toast-exit');
    toast.addEventListener('transitionend', () => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, { once: true });
}

export const Toast = {
    success(message) { createToast(message, 'success'); },
    error(message) { createToast(message, 'error'); },
    info(message) { createToast(message, 'info'); },
    warning(message) { createToast(message, 'warning'); },
};
