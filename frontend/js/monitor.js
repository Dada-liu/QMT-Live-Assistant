import { api } from './api.js';
import { UI } from './ui.js';
import { getState, setState, getStoredToken } from './state.js';
import { refreshDashboard } from './dashboard.js';

let pollingTimer = null;

export function startPolling() {
    stopPolling();
    pollingTimer = setInterval(async () => {
        try {
            const result = await api.getSignals(getState('token'));
            if (result.success && result.data) {
                setState('signals', result.data);
                UI.renderSignals();
            }
        } catch (error) {
            // silently ignore polling errors
        }
    }, 5000);
}

export function stopPolling() {
    if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
    }
}

export function initMonitor() {
    // Monitor is driven by polling and UI.addSignal calls from other modules
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
