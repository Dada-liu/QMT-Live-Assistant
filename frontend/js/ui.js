import { getState, setState, getStoredToken } from './state.js';

export const UI = {

    updateServerInfo(data) {
        const grid = document.getElementById('server-info-grid');
        if (!grid) return;

        const statusText = data.running ? '运行中' : '已停止';
        const statusClass = data.running ? 'running' : 'stopped';

        grid.innerHTML = `
          <div class="server-info-item">
            <div class="server-info-label">状态</div>
            <div class="server-info-value"><span class="status-dot ${statusClass}"></span>${statusText}</div>
          </div>
          <div class="server-info-item">
            <div class="server-info-label">账户ID</div>
            <div class="server-info-value">${data.account_id || '--'}</div>
          </div>
          <div class="server-info-item">
            <div class="server-info-label">QMT 路径</div>
            <div class="server-info-value">${data.qmt_path || '--'}</div>
          </div>
          <div class="server-info-item">
            <div class="server-info-label">服务器地址</div>
            <div class="server-info-value">${data.host || '--'}:${data.port || '--'}</div>
          </div>
        `;

        const storedToken = data.token || getStoredToken();
        if (storedToken) {
            document.getElementById('token-display').textContent = storedToken;
            if (data.token) setState('token', data.token);
        }
    },

    resetServerInfo() {
        const grid = document.getElementById('server-info-grid');
        if (grid) grid.innerHTML = '';
        const tokenEl = document.getElementById('token-display');
        if (tokenEl) tokenEl.textContent = '--';
        setState('token', null);
        setState('signals', []);
        this.renderSignals();
    },

    renderSignals() {
        const list = document.getElementById('signal-list');
        if (!list) return;

        const signals = getState('signals');

        if (signals.length === 0) {
            list.innerHTML = '<div class="signal-empty">暂无信号记录</div>';
            return;
        }

        const header = `
          <div class="signal-item header">
            <span>时间</span>
            <span>信号ID</span>
            <span>方向</span>
            <span>内容</span>
            <span>数量</span>
            <span>状态</span>
          </div>
        `;

        const rows = signals.slice().reverse().map(s => {
            const time = s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : '--';
            const signalId = s.signal_id || '--';
            const direction = s.direction || s.order_type || '--';
            const msg = s.message || '--';
            const volume = s.quantity || s.volume || '--';
            const status = s.status || '--';

            let directionBadge = '';
            if (direction === 'buy' || direction.includes('买入')) {
                directionBadge = '<span class="badge badge-buy">买入</span>';
            } else if (direction === 'sell' || direction.includes('卖出')) {
                directionBadge = '<span class="badge badge-sell">卖出</span>';
            } else {
                directionBadge = `<span class="badge badge-info">${direction}</span>`;
            }

            let statusBadge = '';
            if (status === 'submitted') statusBadge = '<span class="badge badge-info">已提交</span>';
            else if (status === 'filled') statusBadge = '<span class="badge badge-success">已成交</span>';
            else if (status === 'error') statusBadge = '<span class="badge badge-error">失败</span>';
            else statusBadge = `<span>${status}</span>`;

            return `
              <div class="signal-item">
                <span class="signal-time">${time}</span>
                <span class="signal-code">${signalId}</span>
                <span class="signal-direction">${directionBadge}</span>
                <span class="signal-msg">${msg}</span>
                <span>${volume}</span>
                <span>${statusBadge}</span>
              </div>
            `;
        }).join('');

        list.innerHTML = header + rows;
    },

    addSignal(signal) {
        const signals = getState('signals');
        signals.push(signal);
        if (signals.length > 200) signals.shift();
        setState('signals', signals);
        this.renderSignals();
    },

    clearSignals() {
        setState('signals', []);
        this.renderSignals();
    },

    updateDashboard(data) {
        const formatCurrency = (value) => {
            if (value === undefined || value === null) return '--';
            const num = parseFloat(value);
            return '¥ ' + num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        };

        const setValue = (id, text) => {
            const el = document.getElementById(id);
            el.textContent = text;
            el.title = text;
        };

        setValue('dash-cash', formatCurrency(data.cash));
        setValue('dash-market-value', formatCurrency(data.market_value));
        setValue('dash-total-asset', formatCurrency(data.total_asset));

        const dailyProfit = document.getElementById('dash-daily-profit');
        if (data.daily_profit !== undefined) {
            const profit = parseFloat(data.daily_profit);
            const text = (profit >= 0 ? '+ ' : '- ') + formatCurrency(Math.abs(profit)).replace('¥ ', '');
            dailyProfit.textContent = text;
            dailyProfit.title = text;
            dailyProfit.className = 'dashboard-card-value dashboard-card-change ' + (profit >= 0 ? 'up' : 'down');
        } else {
            dailyProfit.title = dailyProfit.textContent;
        }
    },

    disableForm(disable) {
        const inputs = document.querySelectorAll('#config-form input');
        inputs.forEach(input => { input.disabled = disable; });
        document.getElementById('btn-start').disabled = disable;
        document.getElementById('btn-stop').disabled = !disable;
    },

    toggleTheme() {
        const html = document.documentElement;
        const current = html.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
        document.getElementById('theme-toggle').textContent = next === 'dark' ? '☀️' : '🌙';
        setState('theme', next);
    },

    initTheme() {
        const saved = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', saved);
        document.getElementById('theme-toggle').textContent = saved === 'dark' ? '☀️' : '🌙';
        setState('theme', saved);
    },

    showConnectPrompt() {
        document.getElementById('account-empty-content').classList.add('hidden');
        document.getElementById('account-connect').classList.remove('hidden');
    },

    hideConnectPrompt() {
        document.getElementById('account-empty-content').classList.remove('hidden');
        document.getElementById('account-connect').classList.add('hidden');
    },

    showSection(sectionId) {
        document.getElementById(sectionId).classList.remove('hidden');
    },

    hideSection(sectionId) {
        document.getElementById(sectionId).classList.add('hidden');
    },

    switchTab(tabName) {
        const sections = ['account-empty', 'config', 'server-info', 'dashboard', 'monitor', 'converter'];

        sections.forEach(id => this.hideSection(id));

        switch (tabName) {
            case 'account':
                if (getState('serverRunning')) {
                    if (getStoredToken()) {
                        this.showSection('dashboard');
                        this.hideConnectPrompt();
                    } else {
                        this.showSection('account-empty');
                        this.showConnectPrompt();
                    }
                } else {
                    this.showSection('account-empty');
                    this.hideConnectPrompt();
                }
                break;
            case 'trade':
                this.showSection('monitor');
                break;
            case 'config':
                this.showSection('config');
                if (getState('serverRunning')) {
                    this.showSection('server-info');
                }
                break;
            case 'converter':
                this.showSection('converter');
                break;
        }

        document.querySelectorAll('.top-nav-links a').forEach(link => {
            link.classList.remove('active');
            if (link.getAttribute('href') === '#' + tabName) {
                link.classList.add('active');
            }
        });
    },

    resetDashboard() {
        ['dash-cash', 'dash-market-value', 'dash-total-asset', 'dash-daily-profit'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = '--';
                el.title = '--';
                el.className = 'dashboard-card-value';
            }
        });
    },
};
