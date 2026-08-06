import { api } from './api.js';
import { UI } from './ui.js';
import { getState } from './state.js';

export function initDashboard() {
    UI.initDashboardInteraction();
}

let _refreshInFlight = null;
let _lastRefreshAt = 0;
// 略大于 monitor.js 的 5s 状态轮询间隔，保证轮询的重复触发落在冷却窗口内
const REFRESH_COOLDOWN_MS = 6000;

export async function refreshDashboard({ force = false } = {}) {
    const token = getState('token');
    if (!token) return;

    // 并发重复调用合并为同一请求；冷却期内跳过重复刷新
    // （连接处理器与状态轮询会同时触发首次加载，此处统一去重）
    if (_refreshInFlight) return _refreshInFlight;
    if (!force && Date.now() - _lastRefreshAt < REFRESH_COOLDOWN_MS) return;

    UI.showDashboardLoading();

    _refreshInFlight = (async () => {
        try {
            const result = await api.getAccountAsset(token);
            if (result.success && result.data) {
                UI.updateDashboard(result.data);
            } else {
                UI.hideDashboardLoading();
            }
        } catch (error) {
            UI.hideDashboardLoading();
        }
    })();

    try {
        await _refreshInFlight;
    } finally {
        _refreshInFlight = null;
        _lastRefreshAt = Date.now();
    }
}
