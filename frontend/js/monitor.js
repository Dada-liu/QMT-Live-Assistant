import { api } from './api.js';
import { UI } from './ui.js';
import { getState, setState, getStoredToken } from './state.js';
import { refreshDashboard } from './dashboard.js';
import { loadStrategies, populateStrategyDropdown } from './strategy.js';
import { Toast } from './toast.js';

let currentFilters = {};
let currentSignalLogFilters = { status: 'error' };

export function setFilters(filters) {
    currentFilters = { ...filters };
}

export function getCurrentFilters() {
    return { ...currentFilters };
}

export function setSignalLogFilters(filters) {
    currentSignalLogFilters = { ...filters };
}

export function getCurrentSignalLogFilters() {
    return { ...currentSignalLogFilters };
}

export async function fetchOrders() {
    const filters = getCurrentFilters();
    const hasFilters = filters.strategy_name || filters.start_date || filters.end_date || filters.status;
    try {
        const result = hasFilters
            ? await api.getOrders(getState('token'), filters)
            : await api.getOrders(getState('token'));
        if (result.success && result.data) {
            setState('orders', result.data);
            UI.renderOrders();
        }
    } catch (error) {
        // silently ignore polling errors
    }
}

export async function fetchSignalLogs() {
    const token = getState('token');
    if (!token) return;
    const filters = getCurrentSignalLogFilters();
    try {
        const result = await api.getSignalLogs(token, filters);
        if (result.success && result.data) {
            setState('signalLogs', result.data);
            UI.renderSignalLogs();
        }
    } catch (error) {
        // silently ignore polling errors
    }
}

export function applyOrderFilters(filters) {
    const startDateInput = document.getElementById('filter-start-date');
    const endDateInput = document.getElementById('filter-end-date');
    const strategyInput = document.getElementById('filter-strategy');
    const statusInput = document.getElementById('filter-status');

    if (startDateInput) startDateInput.value = filters.start_date || '';
    if (endDateInput) endDateInput.value = filters.end_date || '';
    if (strategyInput) strategyInput.value = filters.strategy_name || '';
    if (statusInput) statusInput.value = filters.status || '';

    setFilters({
        start_date: filters.start_date || '',
        end_date: filters.end_date || '',
        strategy_name: filters.strategy_name || '',
        status: filters.status || ''
    });

    UI.switchTab('trade');
    fetchOrders();
}

export function initMonitor() {
    const btnApply = document.getElementById('btn-apply-filters');
    const btnReset = document.getElementById('btn-reset-filters');
    const btnClear = document.getElementById('btn-clear-orders');

    if (btnApply) {
        btnApply.addEventListener('click', () => {
            const startDate = document.getElementById('filter-start-date').value;
            const endDate = document.getElementById('filter-end-date').value;
            const strategyName = document.getElementById('filter-strategy').value;
            const status = document.getElementById('filter-status').value;
            setFilters({ start_date: startDate, end_date: endDate, strategy_name: strategyName, status });
            fetchOrders();
        });
    }

    if (btnReset) {
        btnReset.addEventListener('click', () => {
            document.getElementById('filter-start-date').value = '';
            document.getElementById('filter-end-date').value = '';
            document.getElementById('filter-strategy').value = '';
            document.getElementById('filter-status').value = '';
            setFilters({});
            fetchOrders();
        });
    }

    if (btnClear) {
        btnClear.addEventListener('click', () => {
            UI.clearOrders();
        });
    }

    initOrderActionDelegation();
    initSignalLogMonitor();
}

function initOrderActionDelegation() {
    const orderList = document.getElementById('order-list');
    if (!orderList) return;

    orderList.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;

        const action = btn.dataset.action;
        const orderId = btn.dataset.orderId;
        const token = getState('token');
        if (!token || !orderId) return;

        btn.disabled = true;
        try {
            if (action === 'cancel') {
                await api.cancelOrder(orderId, token);
                Toast.success('撤销成功');
            } else if (action === 'resend') {
                await api.resendOrder(orderId, token);
                Toast.success('重发成功');
            }
            fetchOrders();
        } catch (error) {
            Toast.error(error.message || '操作失败');
        } finally {
            btn.disabled = false;
        }
    });
}

function initSignalLogMonitor() {
    const btnApply = document.getElementById('btn-apply-signal-log-filters');
    const btnReset = document.getElementById('btn-reset-signal-log-filters');

    if (btnApply) {
        btnApply.addEventListener('click', () => {
            const startDate = document.getElementById('signal-log-start-date').value;
            const endDate = document.getElementById('signal-log-end-date').value;
            const strategyName = document.getElementById('signal-log-strategy').value;
            const status = document.getElementById('signal-log-status').value;
            setSignalLogFilters({ start_date: startDate, end_date: endDate, strategy_name: strategyName, status });
            fetchSignalLogs();
        });
    }

    if (btnReset) {
        btnReset.addEventListener('click', () => {
            document.getElementById('signal-log-start-date').value = '';
            document.getElementById('signal-log-end-date').value = '';
            document.getElementById('signal-log-strategy').value = '';
            document.getElementById('signal-log-status').value = 'error';
            setSignalLogFilters({ status: 'error' });
            fetchSignalLogs();
        });
    }
}

// 定期检查服务器/QMT 连接状态，支持断连检测、恢复提示与自动重连展示
let statusTimer = null;

export function startStatusCheck() {
    stopStatusCheck();
    let lastState = 'unknown';
    let failureCount = 0;

    const check = async () => {
        try {
            const result = await api.getServerInfo();
            failureCount = 0;
            const data = result.data || {};
            const serverRunning = !!data.running;
            const qmtConnected = !!data.qmt_connected;
            const connectionState = data.connection_state || 'disconnected';
            const lastError = data.last_connection_error || null;

            setState('serverRunning', serverRunning);
            setState('qmtConnected', qmtConnected);
            setState('connectionState', connectionState);
            setState('lastConnectionError', lastError);
            UI.updateServerInfo(data);

            if (!serverRunning) {
                if (lastState !== 'stopped' && lastState !== 'unknown') {
                    Toast.warning('服务器已停止');
                    setState('token', null);
                    setState('serverInfo', null);
                    UI.hideReconnectingBanner();
                    UI.resetServerInfo();
                    UI.disableForm(false);
                    UI.switchTab('account');
                }
                lastState = 'stopped';
                return;
            }

            UI.disableForm(true);

            if (qmtConnected) {
                if (lastState === 'reconnecting' || lastState === 'server-down') {
                    Toast.success('QMT 连接已恢复');
                    UI.hideReconnectingBanner();
                }

                const storedToken = getStoredToken();
                if (!storedToken) {
                    if (lastState !== 'waiting-token') {
                        UI.showSection('account-empty');
                        UI.showConnectPrompt();
                    }
                    lastState = 'waiting-token';
                } else {
                    if (lastState !== 'connected') {
                        setState('token', storedToken);
                        UI.switchTab('account');
                        refreshDashboard();
                        loadStrategies().then(populateStrategyDropdown);
                    }
                    lastState = 'connected';
                }
            } else {
                const msg = lastError
                    ? `QMT 连接断开：${lastError}`
                    : 'QMT 连接断开，正在重连...';
                if (lastState !== 'reconnecting') {
                    Toast.warning(msg);
                }
                UI.showReconnectingBanner(msg);
                lastState = 'reconnecting';
            }
        } catch (error) {
            failureCount += 1;
            if (failureCount >= 2 && lastState !== 'server-down') {
                lastState = 'server-down';
                setState('serverRunning', false);
                setState('qmtConnected', false);
                setState('connectionState', 'disconnected');
                setState('lastConnectionError', error.message || '网络请求失败');
                setState('token', null);
                UI.hideReconnectingBanner();
                UI.resetServerInfo();
                UI.disableForm(false);
                UI.switchTab('account');
                Toast.error('与服务器的连接已断开');
            }
        }
    };

    check();
    statusTimer = setInterval(check, 5000);
}

export function stopStatusCheck() {
    if (statusTimer) {
        clearInterval(statusTimer);
        statusTimer = null;
    }
}
