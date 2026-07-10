import { api } from './api.js';
import { getState, setState, getStoredToken } from './state.js';
import { Docs } from './docs.js';

export const UI = {

    _positionSortMode: null,
    _positionData: [],
    _selectedStrategyId: null,
    _orderFilterHandler: null,

    setOrderFilterHandler(handler) {
        this._orderFilterHandler = handler;
    },

    initDashboardInteraction() {
        const dashboard = document.getElementById('dashboard');
        if (!dashboard) return;

        dashboard.addEventListener('click', async (e) => {
            const card = e.target.closest('.dashboard-card.clickable');
            if (!card) return;

            const sortMode = card.dataset.sort;
            if (UI._positionSortMode === sortMode) {
                UI._positionSortMode = null;
                UI._renderPositionList();
                return;
            }

            UI._positionSortMode = sortMode;
            const token = getStoredToken();
            if (token) {
                try {
                    const result = await api.getAccountPositions(token);
                    if (result.success && result.data) {
                        UI._positionData = result.data;
                    }
                } catch (error) {
                    // 静默忽略，使用已有持仓数据渲染
                }
            }
            UI._renderPositionList();
        });
    },

    updateServerInfo(data) {
        if (!data) return;
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
        setState('serverInfo', null);
        setState('orders', []);
        this.renderOrders();
    },

    renderOrders() {
        const list = document.getElementById('order-list');
        const footer = document.getElementById('order-list-footer');
        if (!list) return;

        const orders = getState('orders');

        if (orders.length === 0) {
            list.innerHTML = '<div class="signal-empty">暂无订单记录，下单后将在此显示。</div>';
            if (footer) footer.textContent = '共 0 条订单';
            return;
        }

        const header = `
          <div class="signal-item header">
            <span>时间</span>
            <span>订单ID</span>
            <span>方向</span>
            <span>股票</span>
            <span>成交/委托</span>
            <span>状态</span>
          </div>
        `;

        const rows = orders.map(o => {
            const time = o.placed_at ? new Date(o.placed_at).toLocaleTimeString() : '--';
            const orderId = o.order_id || '--';
            const direction = o.direction || '--';
            const stockCode = o.jq_code || o.stock_code || '--';
            const volume = `${o.filled_quantity || 0}/${o.quantity || '--'}`;
            const status = o.status || '--';

            let directionBadge = '';
            if (direction === 'buy') {
                directionBadge = '<span class="badge badge-buy">买入</span>';
            } else if (direction === 'sell') {
                directionBadge = '<span class="badge badge-sell">卖出</span>';
            } else {
                directionBadge = `<span class="badge badge-warning">${direction}</span>`;
            }

            let statusBadge = '';
            if (status === 'pending') statusBadge = '<span class="badge badge-info">待成交</span>';
            else if (status === 'partial') statusBadge = '<span class="badge badge-warning">部分成交</span>';
            else if (status === 'filled') statusBadge = '<span class="badge badge-success">已成交</span>';
            else if (status === 'failed') statusBadge = '<span class="badge badge-error">失败</span>';
            else statusBadge = `<span class="badge badge-warning">${status}</span>`;

            return `
              <div class="signal-item">
                <span class="signal-time">${time}</span>
                <span class="signal-code">${orderId}</span>
                <span class="signal-direction">${directionBadge}</span>
                <span class="signal-msg">${stockCode}</span>
                <span>${volume}</span>
                <span>${statusBadge}</span>
              </div>
            `;
        }).join('');

        list.innerHTML = header + rows;
        if (footer) footer.textContent = `共 ${orders.length} 条订单`;
    },

    renderSignalLogs() {
        const list = document.getElementById('signal-log-list');
        const footer = document.getElementById('signal-log-footer');
        if (!list) return;

        const logs = getState('signalLogs') || [];

        if (logs.length === 0) {
            list.innerHTML = '<div class="signal-empty">暂无信号日志。</div>';
            if (footer) footer.textContent = '共 0 条信号';
            return;
        }

        const header = `
          <div class="signal-log-item header">
            <span>时间</span>
            <span>策略</span>
            <span>端点</span>
            <span>代码</span>
            <span>方向/数量</span>
            <span>状态</span>
          </div>
        `;

        const rows = logs.map(log => {
            const time = log.received_at ? new Date(log.received_at).toLocaleString() : '--';
            const strategyName = log.strategy_name || '--';
            const endpoint = log.endpoint || '--';
            const payload = log.payload || {};
            const security = payload.security || '--';
            const amount = payload.amount || 0;
            const side = payload.side || '--';
            const directionAmount = `${side} / ${amount}`;
            const status = log.status || '--';
            const errorMsg = log.error_msg || '';

            let statusBadge = '';
            if (status === 'error') statusBadge = '<span class="badge badge-error">异常</span>';
            else if (status === 'success') statusBadge = '<span class="badge badge-success">正常</span>';
            else statusBadge = `<span class="badge badge-warning">${status}</span>`;

            const errorTip = errorMsg ? `<span class="signal-log-error" title="${escapeHtml(errorMsg)}">${escapeHtml(errorMsg)}</span>` : '';

            return `
              <div class="signal-log-item">
                <span class="signal-time">${time}</span>
                <span>${escapeHtml(strategyName)}</span>
                <span>${escapeHtml(endpoint)}</span>
                <span class="signal-msg">${escapeHtml(security)}</span>
                <span>${escapeHtml(directionAmount)}</span>
                <span>${statusBadge}${errorTip}</span>
              </div>
            `;
        }).join('');

        list.innerHTML = header + rows;
        if (footer) footer.textContent = `共 ${logs.length} 条信号`;
    },

    addOrder(order) {
        const orders = getState('orders');
        orders.push(order);
        if (orders.length > 200) orders.shift();
        setState('orders', orders);
        this.renderOrders();
    },

    clearOrders() {
        setState('orders', []);
        this.renderOrders();
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

        // 存储持仓数据用于排序展示
        this._positionData = data.positions || [];
        this._renderPositionList();

        // 标记可点击卡片
        const mvCard = document.getElementById('dash-market-value').closest('.dashboard-card');
        const dpCard = dailyProfit.closest('.dashboard-card');
        if (mvCard) {
            mvCard.classList.add('clickable');
            mvCard.dataset.sort = 'market_value';
        }
        if (dpCard) {
            dpCard.classList.add('clickable');
            dpCard.dataset.sort = 'daily_pnl';
        }
    },

    _renderPositionList() {
        const container = document.getElementById('position-list-container');
        const list = document.getElementById('position-list');
        const hint = document.getElementById('position-sort-hint');
        if (!container || !list || !hint) return;

        const positions = this._positionData;
        const sortMode = this._positionSortMode;

        if (!sortMode || !positions || positions.length === 0) {
            container.classList.add('hidden');
            this._highlightActiveSortCard(null);
            return;
        }

        // 排序
        const sorted = [...positions].sort((a, b) => {
            if (sortMode === 'market_value') {
                return (b.market_value || 0) - (a.market_value || 0);
            }
            return (a.daily_pnl || 0) - (b.daily_pnl || 0);
        });

        hint.textContent = sortMode === 'market_value' ? '按市值排序' : '按盈亏排序（亏损在前）';

        const norm = sorted.map(p => ({
            stock_code: p.stock_code,
            stock_name: p.stock_name || '',
            volume: p.volume || 0,
            canUse: p.can_use_volume || 0,
            openPrice: p.open_price || 0,
            currentPrice: p.market_value && p.volume ? p.market_value / p.volume : 0,
            marketValue: p.market_value || 0,
            totalPnl: p.total_pnl || 0,
            dailyPnl: p.daily_pnl || 0,
        }));

        list.innerHTML = _buildPositionRows(norm, { showTotalPnl: true, showCanUse: true });
        container.classList.remove('hidden');
        this._highlightActiveSortCard(sortMode);
    },

    _renderStrategyPositionList(strategy) {
        const container = document.getElementById('strategy-position-list-container');
        const list = document.getElementById('strategy-position-list');
        const title = document.getElementById('strategy-position-title');
        if (!container || !list || !title) return;

        const positions = strategy.positions || [];
        title.textContent = `${strategy.name} - 持仓明细`;

        if (positions.length === 0) {
            list.innerHTML = '<div class="position-empty">暂无持仓</div>';
            container.classList.remove('hidden');
            return;
        }

        const norm = positions.map(p => {
            const qty = p.quantity || 0;
            const availableQty = p.available_quantity || 0;
            const mv = p.market_value || 0;
            const currentPrice = p.current_price || (qty > 0 ? mv / qty : 0);
            return {
                stock_code: p.stock_code,
                stock_name: p.stock_name || '',
                volume: qty,
                canUse: availableQty,
                openPrice: p.avg_cost || 0,
                currentPrice: currentPrice,
                marketValue: mv,
                totalPnl: p.total_pnl || 0,
                dailyPnl: p.daily_pnl || 0,
            };
        });

        list.innerHTML = _buildPositionRows(norm, { showTotalPnl: true, showCanUse: true });
        container.classList.remove('hidden');
    },

    _hideStrategyPositionList() {
        const container = document.getElementById('strategy-position-list-container');
        if (container) container.classList.add('hidden');
    },

    _highlightActiveSortCard(activeSort) {
        document.querySelectorAll('#dashboard .dashboard-card.clickable').forEach(card => {
            if (activeSort && card.dataset.sort === activeSort) {
                card.classList.add('active');
            } else {
                card.classList.remove('active');
            }
        });
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

    showLoading() {
        const el = document.getElementById('page-loading');
        if (el) el.classList.remove('hidden');
    },

    hideLoading() {
        const el = document.getElementById('page-loading');
        if (el) el.classList.add('hidden');
    },

    switchTab(tabName) {
        const sections = ['account-empty', 'config', 'server-info', 'dashboard', 'strategy-overview', 'strategy-management', 'monitor', 'converter','docs'];

        sections.forEach(id => this.hideSection(id));

        switch (tabName) {
            case 'account':
                if (getState('serverRunning')) {
                    if (getStoredToken()) {
                        this.showSection('dashboard');
                        this.showSection('strategy-overview');
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
                    if (getStoredToken()) {
                        this.showSection('strategy-management');
                    }
                }
                break;
            case 'converter':
                this.showSection('converter');
                break;
            case 'docs':
                this.showSection('docs');
                Docs.loadFirstDoc();
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
        this._positionSortMode = null;
        this._positionData = [];
        const container = document.getElementById('position-list-container');
        if (container) container.classList.add('hidden');
        this._highlightActiveSortCard(null);
    },

    renderStrategyOverview(strategies) {
        const grid = document.getElementById('strategy-overview-grid');
        if (!grid) return;

        if (!strategies || strategies.length === 0) {
            grid.innerHTML = '<div class="card strategy-overview-card" style="grid-column:1/-1;"><div class="strategy-empty" style="padding:var(--spacing-xl);">暂无策略，请先在「<a href="#" class="js-goto-config-strategy">配置</a>」tab 中添加策略。</div></div>';
            this._hideStrategyPositionList();
            return;
        }

        const formatCurrency = (value) => {
            if (value === undefined || value === null) return '--';
            const num = parseFloat(value);
            return '¥ ' + num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        };

        const formatPnl = (value) => {
            if (value === undefined || value === null) return '--';
            const num = parseFloat(value);
            const prefix = num >= 0 ? '+ ' : '- ';
            return prefix + formatCurrency(Math.abs(num)).replace('¥ ', '');
        };

        const selectedId = this._selectedStrategyId;

        grid.innerHTML = strategies.map(s => {
            const pnlClass = (s.daily_pnl || 0) >= 0 ? 'up' : 'down';
            const positionCount = s.positions ? s.positions.length : 0;
            const isActive = selectedId === s.id;
            return `
            <div class="card strategy-overview-card clickable${isActive ? ' active' : ''}"
                 data-strategy-id="${s.id}">
                <div class="strategy-overview-header">
                    <span class="strategy-overview-name">${escapeHtml(s.name)}</span>
                    <span class="status-dot ${s.enabled ? 'running' : 'stopped'}"></span>
                </div>
                <div class="strategy-overview-metrics">
                    <div class="strategy-metric">
                        <span class="strategy-metric-label">可用资金</span>
                        <span class="strategy-metric-value">${formatCurrency(s.available_cash)}</span>
                    </div>
                    <div class="strategy-metric">
                        <span class="strategy-metric-label">总资产</span>
                        <span class="strategy-metric-value">${formatCurrency(s.total_asset)}</span>
                    </div>
                    <div class="strategy-metric">
                        <span class="strategy-metric-label">当日盈亏</span>
                        <span class="strategy-metric-value ${pnlClass}">${formatPnl(s.daily_pnl)}</span>
                    </div>
                </div>
                <div class="strategy-overview-footer">
                    <span class="strategy-meta">持仓 ${positionCount} 只</span>
                    <span class="strategy-meta strategy-order-count" data-strategy-name="${escapeHtml(s.name)}">订单 ${s.order_count || 0} 笔</span>
                </div>
            </div>
            `;
        }).join('');

        // 事件委托：点击策略卡片
        grid.onclick = async (e) => {
            const orderCount = e.target.closest('.strategy-order-count');
            if (orderCount) {
                e.stopPropagation();
                const strategyName = orderCount.dataset.strategyName;
                if (strategyName && this._orderFilterHandler) {
                    this._orderFilterHandler(strategyName);
                }
                return;
            }

            const card = e.target.closest('.strategy-overview-card.clickable');
            if (!card) return;
            const sid = card.dataset.strategyId;
            if (this._selectedStrategyId === sid) {
                this._selectedStrategyId = null;
                this._hideStrategyPositionList();
                this.renderStrategyOverview(strategies);
            } else {
                this._selectedStrategyId = sid;
                const { loadStrategies } = await import('./strategy.js');
                await loadStrategies();
            }
        };

        // 保持选中策略的持仓列表
        if (selectedId) {
            const strategy = strategies.find(s => s.id === selectedId);
            if (strategy) {
                this._renderStrategyPositionList(strategy);
            } else {
                this._hideStrategyPositionList();
            }
        }
    },
};

function _buildPositionRows(positions, opts = {}) {
    const { showTotalPnl = true, showCanUse = true } = opts;

    const fmt = (v) => {
        if (v === undefined || v === null) return '--';
        return parseFloat(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };

    const fmtPnl = (v) => {
        if (v === undefined || v === null) return '--';
        const n = parseFloat(v);
        return (n >= 0 ? '+' : '') + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };

    return positions.map(pos => {
        const vol = pos.volume || 0;
        const canUse = pos.canUse || 0;
        const mv = pos.marketValue || 0;
        const openPrice = pos.openPrice || 0;
        const dailyPnl = pos.dailyPnl || 0;
        const totalPnl = pos.totalPnl || 0;
        const currentPrice = pos.currentPrice || 0;

        const dailyClass = dailyPnl >= 0 ? 'up' : 'down';
        const totalClass = totalPnl >= 0 ? 'up' : 'down';

        const codeDisplay = pos.stock_name
            ? `${escapeHtml(pos.stock_name)}(${escapeHtml(pos.stock_code)})`
            : escapeHtml(pos.stock_code);

        let row = `<div class="position-table-row">`;
        row += `<span class="position-cell-code">${codeDisplay}</span>`;

        if (showCanUse) {
            row += `<span class="position-cell-stacked">
                <span class="position-cell-main">${vol}</span>
                <span class="position-cell-sub">${canUse}</span>
            </span>`;
        } else {
            row += `<span>${vol}</span>`;
        }

        row += `<span class="position-cell-stacked">
            <span class="position-cell-main">${fmt(openPrice)}</span>
            <span class="position-cell-sub">${fmt(currentPrice)}</span>
        </span>`;

        row += `<span>${fmt(mv)}</span>`;

        if (showTotalPnl) {
            const costBasis = openPrice * vol;
            const pnlPct = costBasis > 0
                ? ((totalPnl >= 0 ? '+' : '') + (totalPnl / costBasis * 100).toFixed(2) + '%')
                : null;
            row += `<span class="position-cell-pnl position-cell-stacked ${totalClass}">
                <span class="position-cell-main ${totalClass}">${fmtPnl(totalPnl)}</span>
                ${pnlPct ? `<span class="position-cell-sub ${totalClass}">${pnlPct}</span>` : ''}
            </span>`;
        }

        const prevDay = mv - dailyPnl;
        const dailyPct = prevDay > 0
            ? ((dailyPnl >= 0 ? '+' : '') + (dailyPnl / prevDay * 100).toFixed(2) + '%')
            : null;
        row += `<span class="position-cell-pnl position-cell-stacked ${dailyClass}">
            <span class="position-cell-main ${dailyClass}">${fmtPnl(dailyPnl)}</span>
            ${dailyPct ? `<span class="position-cell-sub ${dailyClass}">${dailyPct}</span>` : ''}
        </span>`;

        row += `</div>`;
        return row;
    }).join('');
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}
