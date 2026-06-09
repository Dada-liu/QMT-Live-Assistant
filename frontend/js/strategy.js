import { api } from './api.js';
import { getState } from './state.js';
import { UI } from './ui.js';
import { Toast } from './toast.js';

let _strategies = [];

export function getStrategies() {
    return _strategies;
}

export function getStrategyById(id) {
    return _strategies.find(s => s.id === id) || null;
}

export async function loadStrategies() {
    const token = getState('token');
    if (!token) return;

    try {
        const result = await api.getStrategies(token);
        if (result.success) {
            _strategies = result.data || [];
            renderStrategyList();
            UI.renderStrategyOverview(_strategies);
            populateStrategyDropdown();
        }
    } catch (error) {
        // Silently ignore
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
                        ${escapeHtml(s.name)}
                        <span class="status-dot ${s.enabled ? 'running' : 'stopped'}" style="margin-left:6px;"></span>
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
                <span class="strategy-count">${s.signal_count || 0} 信号</span>
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
                    await loadStrategies();
                    Toast.info(`策略已${result.data.enabled ? '启用' : '禁用'}`);
                }
            } catch (error) {
                Toast.error(`切换失败: ${error.message}`);
            }
        });
    });

    // Edit
    list.querySelectorAll('[data-action="edit"]').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.id;
            const strategy = _strategies.find(s => s.id === id);
            if (strategy) showStrategyModal(strategy);
        });
    });

    // Delete
    list.querySelectorAll('[data-action="delete"]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            if (!confirm('确定要删除该策略吗？此操作不可撤销。')) return;
            try {
                await api.deleteStrategy(id, getState('token'));
                Toast.success('策略已删除');
                await loadStrategies();
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
}

async function showStrategyModal(strategy = null) {
    const modal = document.getElementById('strategy-modal');
    if (!modal) return;
    const title = document.getElementById('strategy-modal-title');
    const editId = document.getElementById('strategy-edit-id');
    const nameInput = document.getElementById('strategy-name');
    const descInput = document.getElementById('strategy-desc');
    const fundsInput = document.getElementById('strategy-funds');
    const tokenResult = document.getElementById('strategy-token-result');

    if (strategy) {
        if (title) title.textContent = '编辑策略';
        if (editId) editId.value = strategy.id;
        if (nameInput) nameInput.value = strategy.name || '';
        if (descInput) descInput.value = strategy.description || '';
        if (fundsInput) fundsInput.value = strategy.allocated_funds || 0;
        if (tokenResult) tokenResult.classList.add('hidden');
    } else {
        if (title) title.textContent = '添加策略';
        if (editId) editId.value = '';
        if (nameInput) nameInput.value = '';
        if (descInput) descInput.value = '';
        if (fundsInput) fundsInput.value = '';
        if (tokenResult) tokenResult.classList.add('hidden');
    }

    modal.style.display = 'flex';

    // 加载账户持仓用于分配
    await loadAccountPositionsForAssign(strategy);

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
                               step="100">
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

    // Strategy form submit
    const form = el('strategy-form');
    if (form) form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const editIdEl = document.getElementById('strategy-edit-id');
        const nameEl = document.getElementById('strategy-name');
        const descEl = document.getElementById('strategy-desc');
        const fundsEl = document.getElementById('strategy-funds');

        const editId = editIdEl ? editIdEl.value : '';
        const name = nameEl ? nameEl.value.trim() : '';
        const description = descEl ? descEl.value.trim() : '';
        const fundsStr = fundsEl ? fundsEl.value.trim() : '';
        const allocated_funds = parseFloat(fundsStr) || 0;

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
                if (qty % 100 !== 0) {
                    const label = input.dataset.stockName || input.dataset.stockCode;
                    Toast.warning(`${label} 分配数量须为100的整数倍`);
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

        const data = { name, description, allocated_funds, positions };
        const token = getState('token');

        try {
            if (editId) {
                await api.updateStrategy(editId, data, token);
                Toast.success('策略已更新');
                hideStrategyModal();
                await loadStrategies();
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
                    await loadStrategies();
                }
            }
        } catch (error) {
            Toast.error(`保存失败: ${error.message}`);
        }
    });
}

export function populateStrategyDropdown() {
    const select = document.getElementById('filter-strategy');
    if (!select) return;
    const currentValue = select.value;
    select.innerHTML = '<option value="">全部策略</option>';
    _strategies.forEach(s => {
        select.innerHTML += `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`;
    });
    select.value = currentValue;
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
