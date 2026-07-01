import { api } from './api.js';
import { UI } from './ui.js';
import { getState, setState, getStoredToken } from './state.js';
import { refreshDashboard } from './dashboard.js';

let currentFilters = {};

export function setFilters(filters) {
    currentFilters = { ...filters };
}

export function getCurrentFilters() {
    return { ...currentFilters };
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

export function initMonitor() {
    const btnApply = document.getElementById('btn-apply-filters');
    const btnReset = document.getElementById('btn-reset-filters');
    const btnClear = document.getElementById('btn-clear-orders');

    if (btnApply) {
        btnApply.addEventListener('click', () => {
            const startDate = document.getElementById('filter-start-date').value;
            const endDate = document.getElementById('filter-end-date').value;
            const strategyName = document.getElementById('filter-strategy').value;
            setFilters({ start_date: startDate, end_date: endDate, strategy_name: strategyName });
            fetchOrders();
        });
    }

    if (btnReset) {
        btnReset.addEventListener('click', () => {
            document.getElementById('filter-start-date').value = '';
            document.getElementById('filter-end-date').value = '';
            document.getElementById('filter-strategy').value = '';
            setFilters({});
            fetchOrders();
        });
    }

    if (btnClear) {
        btnClear.addEventListener('click', () => {
            UI.clearOrders();
        });
    }
}

// Also check server status periodically for auto-recovery
let statusTimer = null;

export function startStatusCheck() {
    stopStatusCheck();
    statusTimer = setInterval(async () => {
        try {
            const result = await api.getServerInfo();
            if (result.data && result.data.running && !getState('serverRunning')) {
                const storedToken = getStoredToken();
                setState('serverRunning', true);
                UI.updateServerInfo(result.data);
                UI.disableForm(true);

                if (storedToken) {
                    setState('token', storedToken);
                    UI.showSection('server-info');
                    UI.showSection('dashboard');
                    UI.showSection('monitor');
                    UI.showSection('strategy-overview');
                    UI.showSection('strategy-management');
                    refreshDashboard();
                } else {
                    UI.showSection('account-empty');
                    UI.showConnectPrompt();
                }
            }
        } catch (error) {
            // ignore
        }
    }, 5000);
}

export function stopStatusCheck() {
    if (statusTimer) {
        clearInterval(statusTimer);
        statusTimer = null;
    }
}
