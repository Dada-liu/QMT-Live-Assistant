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

function showStrategyModal(strategy = null) {
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
    if (nameInput) nameInput.focus();
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

        const data = { name, description, allocated_funds };
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
