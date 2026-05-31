import { api } from './api.js';
import { UI } from './ui.js';
import { getState, setState, getStoredToken } from './state.js';
import { refreshDashboard } from './dashboard.js';

let pollingTimer = null;
let currentFilters = {};

export function setFilters(filters) {
    currentFilters = { ...filters };
}

export function getCurrentFilters() {
    return { ...currentFilters };
}

async function fetchSignals() {
    const filters = getCurrentFilters();
    const hasFilters = filters.strategy_name || filters.start_date || filters.end_date;
    try {
        const result = hasFilters
            ? await api.getFilteredSignals(getState('token'), filters)
            : await api.getSignals(getState('token'));
        if (result.success && result.data) {
            setState('signals', result.data);
            UI.renderSignals();
        }
    } catch (error) {
        // silently ignore polling errors
    }
}

export function startPolling() {
    stopPolling();
    fetchSignals();
    pollingTimer = setInterval(fetchSignals, 5000);
}

export function stopPolling() {
    if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
    }
}

export function initMonitor() {
    const btnApply = document.getElementById('btn-apply-filters');
    const btnReset = document.getElementById('btn-reset-filters');

    if (btnApply) {
        btnApply.addEventListener('click', () => {
            const startDate = document.getElementById('filter-start-date').value;
            const endDate = document.getElementById('filter-end-date').value;
            const strategyName = document.getElementById('filter-strategy').value;
            setFilters({ start_date: startDate, end_date: endDate, strategy_name: strategyName });
            fetchSignals();
        });
    }

    if (btnReset) {
        btnReset.addEventListener('click', () => {
            document.getElementById('filter-start-date').value = '';
            document.getElementById('filter-end-date').value = '';
            document.getElementById('filter-strategy').value = '';
            setFilters({});
            fetchSignals();
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
                    startPolling();
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
