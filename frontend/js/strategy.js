import { api } from './api.js';
import { getState } from './state.js';
import { UI } from './ui.js';
import { Toast } from './toast.js';
import { Confirm } from './confirm.js';
import { applyOrderFilters, fetchOrders } from './monitor.js';
import { getLotSize, getQuantityUnit, getSecurityTypeName, getPriceDecimalPlaces, isTickAlignedPrice } from './security-utils.js';

let _strategies = [];
let _originalStrategyPositions = null;

export function getStrategies() {
    return _strategies;
}

export function getStrategyById(id) {
    return _strategies.find(s => s.id === id) || null;
}

let _loadInFlight = null;
let _lastLoadAt = 0;
// 略大于 monitor.js 的 5s 状态轮询间隔，保证轮询的重复触发落在冷却窗口内
const LOAD_COOLDOWN_MS = 6000;

export async function loadStrategies({ force = false } = {}) {
    const token = getState('token');
    if (!token) return;

    // 并发重复调用合并为同一请求；冷却期内跳过重复加载
    // （连接处理器与状态轮询会同时触发首次加载，此处统一去重）
    if (_loadInFlight) return _loadInFlight;
    if (!force && Date.now() - _lastLoadAt < LOAD_COOLDOWN_MS) return;

    _loadInFlight = (async () => {
        try {
            const result = await api.getStrategies(token);
            if (result.success) {
                _strategies = result.data || [];
                renderStrategyList();
                UI.renderStrategyOverview(_strategies);
                _updateStrategyOrderButtons();
                populateStrategyDropdown();
            }
        } catch (error) {
            // Silently ignore
        }
    })();

    try {
        await _loadInFlight;
    } finally {
        _loadInFlight = null;
        _lastLoadAt = Date.now();
    }
}

export async function refreshStrategies() {
    const token = getState('token');
    if (!token) return;

    try {
        const result = await api.refreshStrategies(token);
        if (result.success) {
            _strategies = result.data || [];
            renderStrategyList();
            UI.renderStrategyOverview(_strategies);
            _updateStrategyOrderButtons();
            populateStrategyDropdown();
        }
    } catch (error) {
        Toast.error(`刷新失败: ${error.message}`);
    }
}

function renderStrategyList() {
    const list = document.getElementById('strategy-list');
    const total = document.getElementById('strategy-total');
    if (!list || !total) return;

    total.textContent = `共 ${_strategies.length} 个策略`;

    if (_strategies.length === 0) {
        list.innerHTML = '<div class="strategy-empty">暂无策略，点击「添加策略」创建第一个策略。</div>';
        return;
    }

    list.innerHTML = _strategies.map(s => `
        <div class="strategy-item">
            <div class="strategy-item-info">
                <div>
                    <div class="strategy-name">
                        <span class="status-dot ${s.enabled ? 'running' : 'stopped'}" style="margin-left:6px;"></span>
                        ${escapeHtml(s.name)}
                        <span class="strategy-type-tag strategy-type-tag-${s.security_type === 'convertible_bond' ? 'bond' : 'stock'}">${getSecurityTypeName(s.security_type)}</span>
                    </div>
                    ${s.description ? `<div class="strategy-desc">${escapeHtml(s.description)}</div>` : ''}
                </div>
                <div class="strategy-token-row">
                    <span class="strategy-label">Token:</span>
                    <span class="strategy-token-value" title="${escapeHtml(s.token)}">${escapeHtml(s.token.substring(0, 16))}...</span>
                    <button class="btn-sm btn-sm-copy" data-token="${escapeHtml(s.token)}" title="复制Token">复制</button>
                </div>
            </div>
            <div class="strategy-item-meta">
                <span>分配: ${formatMoney(s.allocated_funds)}</span>
                <span>可用: ${formatMoney(s.available_cash)}</span>
                <span>冻结: ${formatMoney(s.frozen_cash || 0)}</span>
                <span class="strategy-count strategy-order-count" data-strategy-name="${escapeHtml(s.name)}">${s.order_count || 0} 订单</span>
            </div>
            <div class="strategy-item-status">
                <button class="btn-sm btn-sm-toggle ${s.enabled ? 'enabled' : ''}" data-id="${s.id}" data-action="toggle">
                    ${s.enabled ? '已启用' : '已禁用'}
                </button>
            </div>
            <div class="strategy-item-actions">
                <button class="btn-sm btn-sm-edit" data-id="${s.id}" data-action="edit">编辑</button>
                <button class="btn-sm btn-sm-delete" data-id="${s.id}" data-action="delete">删除</button>
            </div>
        </div>
    `).join('');

    // Toggle
    list.querySelectorAll('[data-action="toggle"]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            try {
                const result = await api.toggleStrategy(id, getState('token'));
                if (result.success) {
                    await loadStrategies({ force: true });
                    Toast.info(`策略已${result.data.enabled ? '启用' : '禁用'}`);
                }
            } catch (error) {
                Toast.error(`切换失败: ${error.message}`);
            }
        });
    });

    // Edit
    list.querySelectorAll('[data-action="edit"]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            try {
                await loadStrategies({ force: true });
            } catch (error) {
                // 继续尝试使用本地已缓存数据
            }
            const strategy = _strategies.find(s => s.id === id);
            if (strategy) showStrategyModal(strategy);
        });
    });

    // Delete
    list.querySelectorAll('[data-action="delete"]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            const confirmed = await Confirm.show({
                title: '删除策略',
                message: '确定要删除该策略吗？此操作不可撤销。',
                confirmText: '删除',
                type: 'danger',
            });
            if (!confirmed) return;
            try {
                await api.deleteStrategy(id, getState('token'));
                Toast.success('策略已删除');
                await loadStrategies({ force: true });
            } catch (error) {
                Toast.error(`删除失败: ${error.message}`);
            }
        });
    });

    // Copy token
    list.querySelectorAll('[data-action]:not([data-action])').forEach(btn => {
        // handled above
    });
    list.querySelectorAll('.btn-sm-copy').forEach(btn => {
        btn.addEventListener('click', () => {
            const token = btn.dataset.token;
            copyToClipboard(token);
        });
    });

    // Navigate to orders filtered by strategy
    list.querySelectorAll('.strategy-order-count').forEach(el => {
        el.addEventListener('click', () => {
            const strategyName = el.dataset.strategyName;
            if (strategyName) {
                applyOrderFilters({ strategy_name: strategyName });
            }
        });
    });
}

async function showStrategyModal(strategy = null) {
    const modal = document.getElementById('strategy-modal');
    if (!modal) return;
    const title = document.getElementById('strategy-modal-title');
    const editId = document.getElementById('strategy-edit-id');
    const nameInput = document.getElementById('strategy-name');
    const descInput = document.getElementById('strategy-desc');
    const securityTypeInput = document.getElementById('strategy-security-type');
    const fundsInput = document.getElementById('strategy-funds');
    const fundsPolicyInput = document.getElementById('strategy-funds-policy');
    const marketPriceTypeInput = document.getElementById('strategy-market-price-type');
    const deferBuyInput = document.getElementById('strategy-defer-buy');
    const barkNotifyInput = document.getElementById('strategy-bark-notify');
    const tokenResult = document.getElementById('strategy-token-result');

    if (strategy) {
        if (title) title.textContent = '编辑策略';
        if (editId) editId.value = strategy.id;
        if (nameInput) nameInput.value = strategy.name || '';
        if (descInput) descInput.value = strategy.description || '';
        if (securityTypeInput) securityTypeInput.value = strategy.security_type || 'stock';
        if (fundsInput) fundsInput.value = strategy.allocated_funds || 0;
        if (fundsPolicyInput) fundsPolicyInput.value = strategy.insufficient_funds_policy || 'reject';
        if (marketPriceTypeInput) marketPriceTypeInput.value = String(strategy.default_market_price_type ?? 5);
        if (deferBuyInput) deferBuyInput.checked = strategy.defer_buy_on_insufficient_funds === true;
        if (barkNotifyInput) barkNotifyInput.checked = strategy.bark_notify_enabled !== false;
        if (tokenResult) tokenResult.classList.add('hidden');
        _originalStrategyPositions = JSON.stringify(strategy.positions || []);
    } else {
        if (title) title.textContent = '添加策略';
        if (editId) editId.value = '';
        if (nameInput) nameInput.value = '';
        if (descInput) descInput.value = '';
        if (securityTypeInput) securityTypeInput.value = 'stock';
        if (fundsInput) fundsInput.value = '';
        if (fundsPolicyInput) fundsPolicyInput.value = 'reject';
        if (marketPriceTypeInput) marketPriceTypeInput.value = '5';
        if (deferBuyInput) deferBuyInput.checked = false;
        if (barkNotifyInput) barkNotifyInput.checked = true;
        if (tokenResult) tokenResult.classList.add('hidden');
        _originalStrategyPositions = null;
    }

    modal.style.display = 'flex';

    // 加载账户持仓用于分配
    await loadAccountPositionsForAssign(strategy);
    _syncMarketPriceTypeLock();

    if (nameInput) nameInput.focus();
}

async function loadAccountPositionsForAssign(strategy) {
    const group = document.getElementById('strategy-positions-group');
    const loading = document.getElementById('strategy-positions-loading');
    const empty = document.getElementById('strategy-positions-empty');
    const tableWrapper = document.getElementById('strategy-positions-table-wrapper');
    const tbody = document.getElementById('strategy-positions-tbody');

    if (!group || !tbody) return;

    group.style.display = '';
    loading.style.display = '';
    if (empty) empty.style.display = 'none';
    if (tableWrapper) tableWrapper.style.display = 'none';

    const token = getState('token');
    if (!token) {
        loading.style.display = 'none';
        return;
    }

    try {
        const result = await api.getAccountAsset(token);
        if (!result.success || !result.data) {
            loading.style.display = 'none';
            return;
        }

        const accountPositions = result.data.positions || [];
        if (accountPositions.length === 0) {
            loading.style.display = 'none';
            if (empty) empty.style.display = '';
            return;
        }

        // 当前策略已有持仓映射（编辑模式）
        const strategyPosMap = {};
        if (strategy && strategy.positions) {
            strategy.positions.forEach(p => {
                strategyPosMap[p.stock_code] = p.quantity;
            });
        }

        // 计算其他策略已分配的数量
        const assignedByOthers = {};
        const allStrategies = getStrategies();
        allStrategies.forEach(s => {
            if (strategy && s.id === strategy.id) return;
            if (s.positions) {
                s.positions.forEach(p => {
                    assignedByOthers[p.stock_code] = (assignedByOthers[p.stock_code] || 0) + p.quantity;
                });
            }
        });

        tbody.innerHTML = accountPositions.map(pos => {
            const code = pos.stock_code || '';
            const name = pos.stock_name || '';
            const totalVolume = pos.volume || 0;
            const alreadyAssigned = assignedByOthers[code] || 0;
            const available = Math.max(0, totalVolume - alreadyAssigned);
            const currentAssigned = strategyPosMap[code] || 0;
            const price = pos.current_price || pos.open_price || 0;

            return `
                <tr class="position-assign-row" data-stock-code="${escapeHtml(code)}">
                    <td>
                        <span class="position-assign-name">${escapeHtml(name || code)}</span>
                        <span class="position-assign-code">${escapeHtml(code)}</span>
                    </td>
                    <td class="position-assign-available">${available.toLocaleString()}</td>
                    <td>
                        <input type="number"
                               class="form-input position-assign-qty-input"
                               data-stock-code="${escapeHtml(code)}"
                               data-stock-name="${escapeHtml(name)}"
                               data-current-price="${price}"
                               data-max="${available}"
                               value="${currentAssigned || ''}"
                               placeholder="0"
                               min="0"
                               max="${available}"
                               step="${getLotSize(code)}">
                    </td>
                </tr>
            `;
        }).join('');

        loading.style.display = 'none';
        if (tableWrapper) tableWrapper.style.display = '';
    } catch (error) {
        loading.style.display = 'none';
    }
}

function hideStrategyModal() {
    const modal = document.getElementById('strategy-modal');
    if (modal) modal.style.display = 'none';
}

function _syncMarketPriceTypeLock() {
    const securityTypeInput = document.getElementById('strategy-security-type');
    const marketPriceTypeInput = document.getElementById('strategy-market-price-type');
    const helpIcon = document.getElementById('market-price-type-help');
    if (!securityTypeInput || !marketPriceTypeInput) return;

    const isBond = securityTypeInput.value === 'convertible_bond';
    if (isBond) {
        marketPriceTypeInput.value = '5';
        marketPriceTypeInput.disabled = true;
    } else {
        marketPriceTypeInput.disabled = false;
    }

    if (helpIcon) {
        helpIcon.classList.toggle('hidden', !isBond);
    }
}

export function initStrategyPanel() {
    const el = (id) => {
        const e = document.getElementById(id);
        if (!e) console.error('[strategy] Element not found: #' + id);
        return e;
    };

    // Add strategy button
    const btnAdd = el('btn-add-strategy');
    if (btnAdd) btnAdd.addEventListener('click', () => { showStrategyModal(null); });

    // Refresh button
    const btnRefresh = el('btn-refresh-strategies');
    if (btnRefresh) btnRefresh.addEventListener('click', async () => {
        await refreshStrategies();
        Toast.success('行情已刷新');
    });

    // Cancel button
    const btnCancel = el('btn-strategy-cancel');
    if (btnCancel) btnCancel.addEventListener('click', () => { hideStrategyModal(); });

    // Close button (top-left ×)
    const btnClose = el('btn-strategy-modal-close');
    if (btnClose) btnClose.addEventListener('click', () => { hideStrategyModal(); });

    // Security type change: lock market price type to latest price for convertible bonds
    const securityTypeInput = el('strategy-security-type');
    if (securityTypeInput) securityTypeInput.addEventListener('change', _syncMarketPriceTypeLock);

    // Strategy form submit
    const form = el('strategy-form');
    if (form) form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const editIdEl = document.getElementById('strategy-edit-id');
        const nameEl = document.getElementById('strategy-name');
        const descEl = document.getElementById('strategy-desc');
        const fundsEl = document.getElementById('strategy-funds');
        const fundsPolicyEl = document.getElementById('strategy-funds-policy');

        const editId = editIdEl ? editIdEl.value : '';
        const name = nameEl ? nameEl.value.trim() : '';
        const description = descEl ? descEl.value.trim() : '';
        const securityTypeEl = document.getElementById('strategy-security-type');
        const security_type = securityTypeEl ? securityTypeEl.value : 'stock';
        const fundsStr = fundsEl ? fundsEl.value.trim() : '';
        const allocated_funds = parseFloat(fundsStr) || 0;
        const insufficient_funds_policy = fundsPolicyEl ? fundsPolicyEl.value : 'reject';
        const marketPriceTypeEl = document.getElementById('strategy-market-price-type');
        let default_market_price_type = marketPriceTypeEl ? Number(marketPriceTypeEl.value) : 5;
        if (security_type === 'convertible_bond') {
            default_market_price_type = 5;
        }
        const barkNotifyEl = document.getElementById('strategy-bark-notify');
        const bark_notify_enabled = barkNotifyEl ? barkNotifyEl.checked : true;
        const deferBuyEl = document.getElementById('strategy-defer-buy');
        const defer_buy_on_insufficient_funds = deferBuyEl ? deferBuyEl.checked : false;

        if (!name) {
            Toast.warning('请输入策略名称');
            return;
        }

        if (!fundsStr || allocated_funds <= 0) {
            Toast.warning('请输入有效的分配金额（必须大于0）');
            return;
        }

        // 收集分配的持仓
        const positions = [];
        const qtyInputs = document.querySelectorAll('.position-assign-qty-input');
        for (const input of qtyInputs) {
            const qty = parseInt(input.value, 10) || 0;
            if (qty > 0) {
                const lotSize = getLotSize(input.dataset.stockCode);
                if (qty % lotSize !== 0) {
                    const label = input.dataset.stockName || input.dataset.stockCode;
                    Toast.warning(`${label} 分配数量须为${lotSize}的整数倍（${getQuantityUnit(input.dataset.stockCode)}）`);
                    return;
                }
                const max = parseInt(input.dataset.max, 10) || 0;
                if (qty > max) {
                    const label = input.dataset.stockName || input.dataset.stockCode;
                    Toast.warning(`${label} 分配数量不可超过可用数量(${max})`);
                    return;
                }
                positions.push({
                    stock_code: input.dataset.stockCode,
                    stock_name: input.dataset.stockName || '',
                    quantity: qty,
                    current_price: parseFloat(input.dataset.currentPrice) || 0,
                });
            }
        }

        // 校验持仓总成本不超过分配金额
        if (positions.length > 0) {
            const totalCost = positions.reduce((sum, p) => sum + p.quantity * p.current_price, 0);
            if (totalCost > allocated_funds) {
                Toast.warning(`持仓总成本(${totalCost.toFixed(2)})超过分配金额(${allocated_funds.toFixed(2)})，请调整`);
                return;
            }
        }

        const data = { name, description, security_type, allocated_funds, insufficient_funds_policy, default_market_price_type, bark_notify_enabled, defer_buy_on_insufficient_funds };
        const positionsChanged = editId
            ? (JSON.stringify(positions) !== _originalStrategyPositions)
            : (positions.length > 0);
        if (positionsChanged) {
            data.positions = positions;
        }
        const token = getState('token');

        try {
            if (editId) {
                await api.updateStrategy(editId, data, token);
                Toast.success('策略已更新');
                hideStrategyModal();
                await loadStrategies({ force: true });
            } else {
                const result = await api.createStrategy(data, token);
                if (result.success && result.data) {
                    const strategyToken = result.data.token;
                    const tokenResult = document.getElementById('strategy-token-result');
                    if (tokenResult) {
                        tokenResult.textContent = `策略 Token: ${strategyToken}`;
                        tokenResult.classList.remove('hidden');
                    }
                    Toast.success('策略已创建，请复制并保存 Token');
                    hideStrategyModal();
                    await loadStrategies({ force: true });
                }
            }
        } catch (error) {
            Toast.error(`保存失败: ${error.message}`);
        }
    });

    initStrategyOrderModal();
}

export function populateStrategyDropdown() {
    const selects = [
        document.getElementById('filter-strategy'),
        document.getElementById('signal-log-strategy'),
    ];
    selects.forEach(select => {
        if (!select) return;
        const currentValue = select.value;
        select.innerHTML = '<option value="">全部策略</option>';
        _strategies.forEach(s => {
            select.innerHTML += `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`;
        });
        select.value = currentValue;
    });
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatMoney(value) {
    if (value === undefined || value === null) return '--';
    const num = parseFloat(value);
    return '¥ ' + num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            Toast.success('Token 已复制到剪贴板');
        }).catch(() => {
            Toast.error('复制失败');
        });
        return;
    }
    // Fallback for non-secure context
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        Toast.success('Token 已复制到剪贴板');
    } catch (e) {
        Toast.error('复制失败');
    }
    document.body.removeChild(textarea);
}

// ---- 手动下单弹窗（买入/卖出共用） ----

// 卖出下拉选中持仓的映射（stock_code → position），打开弹窗时建立
let _orderModalPositions = {};

function _getSelectedStrategy() {
    const sid = UI._selectedStrategyId;
    return sid ? getStrategyById(sid) : null;
}

function _updateStrategyOrderButtons() {
    const sellBtn = document.getElementById('btn-strategy-sell');
    if (!sellBtn) return;
    const strategy = _getSelectedStrategy();
    const hasPositions = !!(strategy && strategy.positions && strategy.positions.length > 0);
    sellBtn.disabled = !hasPositions;
    sellBtn.title = hasPositions ? '' : '当前策略暂无持仓';
}

function openStrategyOrderModal(direction) {
    const modal = document.getElementById('order-modal');
    const form = document.getElementById('order-form');
    if (!modal || !form) return;

    const strategy = _getSelectedStrategy();
    if (!strategy) {
        Toast.error('未找到策略数据，请刷新后重试');
        return;
    }
    if (!strategy.enabled) {
        Toast.warning('策略已禁用，无法下单');
        return;
    }

    form.dataset.direction = direction;
    form.dataset.strategyId = strategy.id;
    _orderModalPositions = {};
    (strategy.positions || []).forEach(p => { _orderModalPositions[p.stock_code] = p; });

    const isBuy = direction === 'buy';
    document.getElementById('order-modal-title').textContent = isBuy ? '买入' : '卖出';
    document.getElementById('btn-order-submit').textContent = isBuy ? '确认买入' : '确认卖出';

    // 买入自由输入代码；卖出从策略持仓下拉选择
    document.getElementById('order-stock-input-group').style.display = isBuy ? '' : 'none';
    document.getElementById('order-stock-select-group').style.display = isBuy ? 'none' : '';

    const codeInput = document.getElementById('order-stock-code');
    codeInput.value = '';
    const stockSelect = document.getElementById('order-stock-select');
    if (!isBuy) {
        stockSelect.innerHTML = (strategy.positions || []).map(p => {
            const label = p.stock_name ? `${p.stock_name}(${p.stock_code})` : p.stock_code;
            return `<option value="${escapeHtml(p.stock_code)}">${escapeHtml(label)}</option>`;
        }).join('');
    }

    // 数量按整手步进（股票 100 股 / 可转债 10 张）；买入最低一手，卖出允许零股（可手动输入）
    const quantityInput = document.getElementById('order-quantity');
    quantityInput.step = getLotSize(isBuy ? '' : stockSelect.value);
    quantityInput.min = isBuy ? getLotSize('') : 0;
    quantityInput.value = '';
    // 买入模式：代码输入时按券种动态调整数量步进与提示单位
    codeInput.oninput = () => {
        const lot = getLotSize(codeInput.value.trim().toUpperCase());
        quantityInput.step = lot;
        quantityInput.min = lot;
    };
    // 报价方式预选策略配置的默认市价方式（5 最新价 / 44 对手方最优 / 45 本方最优）
    document.getElementById('order-price-type').value = String(strategy.default_market_price_type ?? 5);
    document.getElementById('order-price-group').style.display = 'none';
    document.getElementById('order-price').value = '';
    // 重置字段后再预填选中持仓的限价与可用提示
    if (!isBuy) {
        _onOrderStockChange();
    }
    modal.style.display = 'flex';
}

function hideStrategyOrderModal() {
    const modal = document.getElementById('order-modal');
    if (modal) modal.style.display = 'none';
}

// 卖出切换股票时：预填限价（现价）、更新可用数量提示与数量步进
function _onOrderStockChange() {
    const stockSelect = document.getElementById('order-stock-select');
    const hint = document.getElementById('order-quantity-hint');
    const priceInput = document.getElementById('order-price');
    const quantityInput = document.getElementById('order-quantity');
    const pos = _orderModalPositions[stockSelect.value];
    if (quantityInput) {
        quantityInput.step = getLotSize(stockSelect.value);
    }
    if (!pos) {
        hint.style.display = 'none';
        return;
    }
    const available = pos.available_quantity ?? pos.quantity ?? 0;
    hint.textContent = `可用 ${available} ${getQuantityUnit(stockSelect.value)}`;
    hint.style.display = '';
    if (pos.current_price > 0) {
        priceInput.value = pos.current_price;
    }
}

function initStrategyOrderModal() {
    const modal = document.getElementById('order-modal');
    const form = document.getElementById('order-form');
    if (!modal || !form) return;

    const priceType = document.getElementById('order-price-type');
    const priceGroup = document.getElementById('order-price-group');
    const priceInput = document.getElementById('order-price');
    const quantityInput = document.getElementById('order-quantity');
    const submitBtn = document.getElementById('btn-order-submit');
    const stockSelect = document.getElementById('order-stock-select');

    document.getElementById('btn-strategy-buy').addEventListener('click', () => openStrategyOrderModal('buy'));
    document.getElementById('btn-strategy-sell').addEventListener('click', () => openStrategyOrderModal('sell'));
    document.getElementById('btn-order-modal-close').addEventListener('click', hideStrategyOrderModal);
    document.getElementById('btn-order-cancel').addEventListener('click', hideStrategyOrderModal);
    priceType.addEventListener('change', () => {
        priceGroup.style.display = priceType.value === '11' ? '' : 'none';
    });
    stockSelect.addEventListener('change', _onOrderStockChange);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const direction = form.dataset.direction;
        const strategyId = form.dataset.strategyId;
        const token = getState('token');
        if (!token || !strategyId) return;

        const isBuy = direction === 'buy';
        let stockCode = '';
        if (isBuy) {
            stockCode = document.getElementById('order-stock-code').value.trim().toUpperCase();
            if (!/^\d{6}\.(SH|SZ|BJ|XSHG|XSHE|XBJ)$/.test(stockCode)) {
                Toast.warning('请输入有效的股票代码（如 000001.SZ 或 000001.XSHE）');
                return;
            }
        } else {
            stockCode = stockSelect.value;
            if (!stockCode) {
                Toast.warning('请选择要卖出的股票');
                return;
            }
        }

        const qtyStr = quantityInput.value.trim();
        const quantity = Number(qtyStr);
        if (!qtyStr || !Number.isInteger(quantity) || quantity <= 0) {
            Toast.warning('请输入有效的委托数量（正整数）');
            return;
        }
        // 买入须整手（股票 100 股 / 可转债 10 张；期货后缀不校验，与后端规则一致）；卖出允许零股
        const isStock = /\.(SH|SZ|BJ|XSHG|XSHE|XBJ)$/.test(stockCode);
        const lotSize = getLotSize(stockCode);
        if (isBuy && isStock && quantity % lotSize !== 0) {
            Toast.warning(`买入数量须为${lotSize}的整数倍（${getQuantityUnit(stockCode)}）`);
            return;
        }
        if (!isBuy) {
            const pos = _orderModalPositions[stockCode];
            const available = pos ? (pos.available_quantity ?? pos.quantity ?? 0) : 0;
            if (quantity > available) {
                Toast.warning(`卖出数量不可超过可用数量（${available} ${getQuantityUnit(stockCode)}）`);
                return;
            }
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
            await api.placeStrategyOrder(
                strategyId,
                { stock_code: stockCode, direction, quantity, price, price_type: Number(priceType.value) },
                token
            );
            Toast.success('下单成功');
            hideStrategyOrderModal();
            await loadStrategies({ force: true });
            fetchOrders();
        } catch (error) {
            Toast.error(error.message || '下单失败');
        } finally {
            submitBtn.disabled = false;
        }
    });
}
