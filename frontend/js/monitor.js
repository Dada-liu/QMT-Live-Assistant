import { api } from './api.js';
import { UI } from './ui.js';
import { getState, setState, getStoredToken } from './state.js';
import { refreshDashboard } from './dashboard.js';
import { loadStrategies, populateStrategyDropdown } from './strategy.js';
import { Toast } from './toast.js';
import { getLotSize, getQuantityUnit, getPriceDecimalPlaces, isTickAlignedPrice } from './security-utils.js';

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
    initResendModal();
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

        if (action === 'resend') {
            const orders = getState('orders') || [];
            const order = orders.find(o => String(o.order_id) === String(orderId));
            if (!order) {
                Toast.error('未找到订单数据，请刷新后重试');
                return;
            }
            openResendModal(order);
            return;
        }

        btn.disabled = true;
        try {
            if (action === 'cancel') {
                await api.cancelOrder(orderId, token);
                Toast.success('撤销成功');
            }
            fetchOrders();
        } catch (error) {
            Toast.error(error.message || '操作失败');
        } finally {
            btn.disabled = false;
        }
    });
}

// ---- 重发订单弹窗 ----

function openResendModal(order) {
    const modal = document.getElementById('resend-modal');
    const form = document.getElementById('resend-form');
    if (!modal || !form) return;

    form.dataset.direction = order.direction || '';
    form.dataset.stockCode = order.stock_code || '';

    document.getElementById('resend-order-id').value = order.order_id;
    document.getElementById('resend-stock').value = order.stock_name
        ? `${order.stock_name}(${order.stock_code})`
        : (order.stock_code || '');
    document.getElementById('resend-direction').value = order.direction === 'buy' ? '买入' : '卖出';
    // 数量按整手步进（股票 100 股 / 可转债 10 张）；买入最低一手，卖出允许零股（可手动输入）
    const resendQuantityInput = document.getElementById('resend-quantity');
    const resendLotSize = getLotSize(order.stock_code);
    resendQuantityInput.step = resendLotSize;
    resendQuantityInput.min = order.direction === 'buy' ? resendLotSize : 0;
    resendQuantityInput.value = order.quantity || '';

    const priceType = document.getElementById('resend-price-type');
    const priceGroup = document.getElementById('resend-price-group');
    const priceInput = document.getElementById('resend-price');
    // 默认沿用原订单的报价方式；历史订单无 price_type 时按价格推导
    const originalPriceType = order.price_type ?? (order.price > 0 ? 11 : 5);
    priceType.value = String(originalPriceType);
    if (originalPriceType === 11 && order.price > 0) {
        priceInput.value = order.price;
        priceGroup.style.display = '';
    } else {
        priceInput.value = '';
        priceGroup.style.display = 'none';
    }
    modal.style.display = 'flex';
}

function hideResendModal() {
    const modal = document.getElementById('resend-modal');
    if (modal) modal.style.display = 'none';
}

function initResendModal() {
    const modal = document.getElementById('resend-modal');
    const form = document.getElementById('resend-form');
    if (!modal || !form) return;

    const priceType = document.getElementById('resend-price-type');
    const priceGroup = document.getElementById('resend-price-group');
    const priceInput = document.getElementById('resend-price');
    const quantityInput = document.getElementById('resend-quantity');
    const submitBtn = document.getElementById('btn-resend-submit');

    document.getElementById('btn-resend-modal-close').addEventListener('click', hideResendModal);
    document.getElementById('btn-resend-cancel').addEventListener('click', hideResendModal);
    priceType.addEventListener('change', () => {
        priceGroup.style.display = priceType.value === '11' ? '' : 'none';
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const orderId = document.getElementById('resend-order-id').value;
        const direction = form.dataset.direction;
        const stockCode = form.dataset.stockCode;
        const token = getState('token');
        if (!token || !orderId) return;

        const qtyStr = quantityInput.value.trim();
        const quantity = Number(qtyStr);
        if (!qtyStr || !Number.isInteger(quantity) || quantity <= 0) {
            Toast.warning('请输入有效的委托数量（正整数）');
            return;
        }
        // 买入须整手（股票 100 股 / 可转债 10 张；期货后缀不校验，与后端规则一致）；卖出允许零股
        const isStock = /\.(SH|SZ|BJ)$/.test(stockCode);
        const lotSize = getLotSize(stockCode);
        if (direction === 'buy' && isStock && quantity % lotSize !== 0) {
            Toast.warning(`买入数量须为${lotSize}的整数倍（${getQuantityUnit(stockCode)}）`);
            return;
        }

        let price = 0;
        if (priceType.value === '11') {
            const priceStr = priceInput.value.trim();
            price = parseFloat(priceStr);
            if (!priceStr || !(price > 0)) {
                Toast.warning('请输入有效的限价价格（大于0）');
                return;
            }
            // 按券种校验最小变动价位（股票 2 位、可转债 3 位小数）；epsilon 比较避免浮点误差误判
            if (!isTickAlignedPrice(price, stockCode)) {
                Toast.warning(`价格最多保留${getPriceDecimalPlaces(stockCode)}位小数`);
                return;
            }
        }

        submitBtn.disabled = true;
        try {
            await api.resendOrder(orderId, { quantity, price, price_type: Number(priceType.value) }, token);
            Toast.success('重发成功');
            hideResendModal();
            fetchOrders();
        } catch (error) {
            Toast.error(error.message || '重发失败');
        } finally {
            submitBtn.disabled = false;
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
