import { getState, getStoredToken } from './state.js';

function getBaseUrl() {
    const path = window.location.pathname;
    if (path.endsWith('/index.html')) {
        return path.slice(0, -'index.html'.length);
    }
    if (path.endsWith('/')) {
        return path;
    }
    return path + '/';
}

class APIClient {
    async request(url, options = {}) {
        const config = {
            ...options,
            headers: { 'Content-Type': 'application/json', ...options.headers },
        };

        try {
            const base = getBaseUrl();
            const cleanUrl = url.startsWith('/') ? url.slice(1) : url;
            const response = await fetch(base + cleanUrl, config);
            const data = await response.json();

            if (!response.ok) {
                const detail = data.detail || data.message || '请求失败';
                throw new Error(detail);
            }
            return data;
        } catch (error) {
            if (error instanceof TypeError && error.message === 'Failed to fetch') {
                throw new Error('网络连接失败，请检查服务器是否运行');
            }
            throw error;
        }
    }

    async startServer(config) {
        return this.request('api/start-server', {
            method: 'POST',
            body: JSON.stringify(config),
        });
    }

    async stopServer() {
        const token = getStoredToken();
        const headers = {};
        if (token) headers['X-Token'] = token;
        return this.request('api/stop-server', {
            method: 'POST',
            headers,
        });
    }

    async getServerInfo() {
        return this.request('api/server-info');
    }

    async testConnection(token) {
        return this.request('api/test-connection', {
            headers: { 'X-Token': token },
        });
    }

    async getAccountAsset(token) {
        return this.request('api/account-asset', {
            headers: { 'X-Token': token },
        });
    }

    async getAccountPositions(token) {
        return this.request('api/account-positions', {
            headers: { 'X-Token': token },
        });
    }

    async getPnlOverview(token, params = {}) {
        const search = new URLSearchParams();
        if (params.scope) search.append('scope', params.scope);
        if (params.strategy_id) search.append('strategy_id', params.strategy_id);
        if (params.period) search.append('period', params.period);
        if (params.date) search.append('date', params.date);
        const query = search.toString();
        return this.request(`api/pnl/overview${query ? '?' + query : ''}`, {
            headers: { 'X-Token': token },
        });
    }

    async healthCheck() {
        return this.request('health');
    }

    // --- 获取文档 ---
    async getDocList() {
        return this.request('api/docs');
    }

    async getDoc(docId) {
        return this.request(`api/docs/${docId}`);
    }

    // --- 策略管理 ---

    async getStrategies(token) {
        return this.request('api/strategies', {
            headers: { 'X-Token': token },
        });
    }

    async createStrategy(data, token) {
        return this.request('api/strategies', {
            method: 'POST',
            headers: { 'X-Token': token },
            body: JSON.stringify(data),
        });
    }

    async updateStrategy(id, data, token) {
        return this.request(`api/strategies/${id}`, {
            method: 'PUT',
            headers: { 'X-Token': token },
            body: JSON.stringify(data),
        });
    }

    async deleteStrategy(id, token) {
        return this.request(`api/strategies/${id}`, {
            method: 'DELETE',
            headers: { 'X-Token': token },
        });
    }

    async toggleStrategy(id, token) {
        return this.request(`api/strategies/${id}/toggle`, {
            method: 'POST',
            headers: { 'X-Token': token },
        });
    }

    async refreshStrategies(token) {
        return this.request('api/strategies/refresh', {
            method: 'POST',
            headers: { 'X-Token': token },
        });
    }

    // --- Bark 推送配置 ---

    async getBarkConfig(token) {
        return this.request('api/bark-config', {
            headers: { 'X-Token': token },
        });
    }

    async updateBarkConfig(data, token) {
        return this.request('api/bark-config', {
            method: 'PUT',
            headers: { 'X-Token': token },
            body: JSON.stringify(data),
        });
    }

    async testBarkConfig(data, token) {
        return this.request('api/bark-config/test', {
            method: 'POST',
            headers: { 'X-Token': token },
            body: JSON.stringify(data),
        });
    }

    async getOrders(token, filters = {}) {
        const params = new URLSearchParams();
        if (filters.status) params.append('status', filters.status);
        if (filters.strategy_name) params.append('strategy_name', filters.strategy_name);
        if (filters.start_date) params.append('start_date', filters.start_date);
        if (filters.end_date) params.append('end_date', filters.end_date);
        const query = params.toString();
        return this.request(`api/orders${query ? '?' + query : ''}`, {
            headers: { 'X-Token': token },
        });
    }

    async getSignalLogs(token, filters = {}) {
        const params = new URLSearchParams();
        if (filters.status) params.append('status', filters.status);
        if (filters.strategy_name) params.append('strategy_name', filters.strategy_name);
        if (filters.start_date) params.append('start_date', filters.start_date);
        if (filters.end_date) params.append('end_date', filters.end_date);
        const query = params.toString();
        return this.request(`api/signal-logs${query ? '?' + query : ''}`, {
            headers: { 'X-Token': token },
        });
    }

    async cancelOrder(orderId, token) {
        return this.request(`api/orders/${encodeURIComponent(orderId)}/cancel`, {
            method: 'POST',
            headers: { 'X-Token': token },
        });
    }

    async resendOrder(orderId, overrides = {}, token) {
        return this.request(`api/orders/${encodeURIComponent(orderId)}/resend`, {
            method: 'POST',
            headers: { 'X-Token': token },
            body: JSON.stringify(overrides),
        });
    }

    async placeStrategyOrder(strategyId, data, token) {
        return this.request(`api/strategies/${encodeURIComponent(strategyId)}/order`, {
            method: 'POST',
            headers: { 'X-Token': token },
            body: JSON.stringify(data),
        });
    }
}

export const api = new APIClient();
