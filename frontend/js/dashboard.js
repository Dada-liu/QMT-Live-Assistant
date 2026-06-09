import { api } from './api.js';
import { UI } from './ui.js';
import { getState } from './state.js';

export function initDashboard() {
    UI.initDashboardInteraction();
}

export async function refreshDashboard() {
    const token = getState('token');
    if (!token) return;

    try {
        const result = await api.getAccountAsset(token);
        if (result.success && result.data) {
            UI.updateDashboard(result.data);
        }
    } catch (error) {
        // silently ignore
    }
}
