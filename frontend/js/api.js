import { getState } from './state.js';

const BASE_URL = '/';

class APIClient {
    async request(url, options = {}) {
        const config = {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        };

        try {
            const response = await fetch(`${BASE_URL}${url.replace(/^\//, '')}`, config);
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
        return this.request('api/stop-server', {
            method: 'POST',
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

    async getSignals(token) {
        return this.request('api/signals', {
            headers: { 'X-Token': token },
        });
    }

    async getAccountAsset(token) {
        return this.request('api/account-asset', {
            headers: { 'X-Token': token },
        });
    }

    async convertJqToQmt(code) {
        return this.request('api/convert/jq-to-qmt', {
            method: 'POST',
            body: JSON.stringify({ code }),
        });
    }

    async convertQmtToJq(code) {
        return this.request('api/convert/qmt-to-jq', {
            method: 'POST',
            body: JSON.stringify({ code }),
        });
    }

    async healthCheck() {
        return this.request('health');
    }
}

export const api = new APIClient();
