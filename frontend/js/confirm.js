/**
 * 全局 Confirm 弹窗组件
 *
 * 提供 Promise 风格的确认弹窗，替代浏览器原生 `confirm()`。
 * 支持自定义标题、消息、按钮文案及危险/警告/信息三种视觉类型。
 */

const TYPE_CLASS_MAP = {
    primary: 'btn-primary',
    danger: 'btn-danger',
    warning: 'btn-warning',
    info: 'btn-primary',
};

let _modal = null;
let _titleEl = null;
let _messageEl = null;
let _okBtn = null;
let _cancelBtn = null;
let _closeBtn = null;
let _currentResolve = null;
let _keydownHandler = null;
let _initialized = false;

function getElements() {
    if (!_modal) _modal = document.getElementById('confirm-modal');
    if (!_titleEl) _titleEl = document.getElementById('confirm-title');
    if (!_messageEl) _messageEl = document.getElementById('confirm-message');
    if (!_okBtn) _okBtn = document.getElementById('btn-confirm-ok');
    if (!_cancelBtn) _cancelBtn = document.getElementById('btn-confirm-cancel');
    if (!_closeBtn) _closeBtn = document.getElementById('btn-confirm-close');
    return { _modal, _titleEl, _messageEl, _okBtn, _cancelBtn, _closeBtn };
}

function closeModal() {
    const { _modal } = getElements();
    if (!_modal) return;
    _modal.style.display = 'none';
    document.removeEventListener('keydown', _keydownHandler);
    _keydownHandler = null;
}

function resolveAndClose(value) {
    if (_currentResolve) {
        _currentResolve(value);
        _currentResolve = null;
    }
    closeModal();
}

function handleKeydown(event) {
    if (event.key === 'Escape') {
        event.preventDefault();
        resolveAndClose(false);
    }
}

function bindEvents() {
    if (_initialized) return;
    const { _modal, _okBtn, _cancelBtn, _closeBtn } = getElements();
    if (!_modal || !_okBtn || !_cancelBtn || !_closeBtn) return;

    _okBtn.addEventListener('click', () => resolveAndClose(true));
    _cancelBtn.addEventListener('click', () => resolveAndClose(false));
    _closeBtn.addEventListener('click', () => resolveAndClose(false));
    _modal.addEventListener('click', (event) => {
        if (event.target === _modal) resolveAndClose(false);
    });

    _initialized = true;
}

/**
 * 显示确认弹窗。
 *
 * @param {Object} options
 * @param {string} [options.title='确认'] - 弹窗标题
 * @param {string} [options.message=''] - 提示消息（支持 HTML 字符串，调用方需自行转义）
 * @param {string} [options.confirmText='确定'] - 确认按钮文案
 * @param {string} [options.cancelText='取消'] - 取消按钮文案
 * @param {'primary'|'danger'|'warning'|'info'} [options.type='primary'] - 确认按钮视觉类型
 * @returns {Promise<boolean>} 用户点击确认返回 true，取消/关闭返回 false
 */
export function show(options = {}) {
    const {
        title = '确认',
        message = '',
        confirmText = '确定',
        cancelText = '取消',
        type = 'primary',
    } = options;

    bindEvents();
    const { _modal, _titleEl, _messageEl, _okBtn, _cancelBtn } = getElements();
    if (!_modal || !_titleEl || !_messageEl || !_okBtn || !_cancelBtn) {
        console.error('[Confirm] confirm-modal DOM 未找到，回退到原生 confirm');
        return Promise.resolve(window.confirm(message));
    }

    _titleEl.textContent = title;
    _messageEl.textContent = message;
    _okBtn.textContent = confirmText;
    _cancelBtn.textContent = cancelText;

    _okBtn.className = `btn ${TYPE_CLASS_MAP[type] || TYPE_CLASS_MAP.primary}`;

    _modal.style.display = 'flex';
    _cancelBtn.focus();

    _keydownHandler = handleKeydown;
    document.addEventListener('keydown', _keydownHandler);

    return new Promise((resolve) => {
        _currentResolve = resolve;
    });
}

export const Confirm = { show };
