import { api } from './api.js';
import { UI } from './ui.js';
import { getState, setState } from './state.js';
import { stopStatusCheck } from './monitor.js';
import { refreshDashboard } from './dashboard.js';
import { loadStrategies, populateStrategyDropdown } from './strategy.js';
import { Toast } from './toast.js';

// --- Bark 推送设置 ---

function _barkEl(id) {
    return document.getElementById(id);
}

function _setBarkFormDisabled(disabled) {
    const form = _barkEl('bark-config-form');
    if (!form) return;
    form.querySelectorAll('input, button').forEach(ctrl => { ctrl.disabled = disabled; });
}

function _collectBarkForm() {
    const keyInput = _barkEl('bark-key');
    const serverInput = _barkEl('bark-server');
    const enabledInput = _barkEl('bark-enabled');
    const staleInput = _barkEl('bark-stale-minutes');
    const stale = parseInt(staleInput && staleInput.value, 10);
    return {
        enabled: !!(enabledInput && enabledInput.checked),
        device_key: keyInput ? keyInput.value.trim() : '',
        server_url: (serverInput && serverInput.value.trim()) || 'https://api.day.app',
        stale_minutes: Number.isInteger(stale) && stale > 0 ? stale : 5,
    };
}

/** 拉取后端 Bark 配置并填充表单；无 token 或接口不可用时禁用表单并显示提示。 */
export async function refreshBarkConfig() {
    const form = _barkEl('bark-config-form');
    if (!form) return;
    const hint = _barkEl('bark-config-hint');
    const token = getState('token');
    if (!token) {
        _setBarkFormDisabled(true);
        if (hint) hint.style.display = '';
        return;
    }
    try {
        const result = await api.getBarkConfig(token);
        const cfg = result.data || {};
        const keyInput = _barkEl('bark-key');
        const serverInput = _barkEl('bark-server');
        const enabledInput = _barkEl('bark-enabled');
        const staleInput = _barkEl('bark-stale-minutes');
        if (keyInput) keyInput.value = cfg.device_key || '';
        if (serverInput) serverInput.value = cfg.server_url || '';
        if (enabledInput) enabledInput.checked = !!cfg.enabled;
        if (staleInput) staleInput.value = cfg.stale_minutes || 5;
        _setBarkFormDisabled(false);
        if (hint) hint.style.display = 'none';
    } catch (error) {
        _setBarkFormDisabled(true);
        if (hint) hint.style.display = '';
    }
}

export function initConfigPanel() {
    const el = (id) => {
        const e = document.getElementById(id);
        if (!e) console.error('[config-panel] Element not found: #' + id);
        return e;
    };

    const form = el('config-form');
    if (form) form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(form);
        const hostValue = formData.get('host').trim();
        const portValue = formData.get('port').trim();
        const config = {
            account_id: formData.get('account_id').trim(),
            qmt_path: formData.get('qmt_path').trim(),
            host: hostValue || undefined,
            port: portValue ? parseInt(portValue) : undefined,
        };

        if (!config.account_id) {
            Toast.warning('请输入券商账户ID');
            return;
        }
        if (!config.qmt_path) {
            Toast.warning('请输入miniQMT路径');
            return;
        }

        try {
            const result = await api.startServer(config);
            if (!result.success) {
                Toast.error(result.detail || '服务器启动失败');
                return;
            }
            const data = result.data;

            UI.updateServerInfo(data);
            UI.disableForm(true);
            setState('serverRunning', true);
            setState('token', data.token);

            Toast.success('服务器启动成功！');
            await loadStrategies();
            populateStrategyDropdown();
            UI.switchTab('account');
            refreshDashboard();
            refreshBarkConfig();
        } catch (error) {
            Toast.error(`启动失败: ${error.message}`);
        }
    });

    if (form) {
        form.querySelectorAll('input').forEach(input => {
            input.addEventListener('input', () => UI.updateConfigButtons());
        });
    }
    UI.updateConfigButtons();

    const btnStop = el('btn-stop');
    if (btnStop) btnStop.addEventListener('click', async () => {
        if (!confirm('确定要停止服务器吗？停止后所有连接将断开。')) return;

        let stopError = null;
        try {
            await api.stopServer();
        } catch (error) {
            stopError = error;
        } finally {
            setState('serverRunning', false);
            UI.disableForm(false);
            UI.resetServerInfo();
            UI.clearOrders();
            UI.resetDashboard();
            stopStatusCheck();
            UI.switchTab('account');
            if (stopError) {
                Toast.error(`停止失败: ${stopError.message}`);
            } else {
                Toast.info('服务器已停止');
            }
        }
    });

    const btnTest = el('btn-test-connection');
    if (btnTest) btnTest.addEventListener('click', async () => {
        const token = getState('token');
        if (!token) {
            Toast.warning('请先启动服务器');
            return;
        }

        try {
            const result = await api.testConnection(token);
            const data = result.data;

            UI.updateDashboard(data);
            Toast.success('连接测试成功！资产数据已更新。');
        } catch (error) {
            Toast.error(`连接测试失败: ${error.message}`);
        }
    });

    const btnCopy = el('btn-copy-token');
    if (btnCopy) btnCopy.addEventListener('click', () => {
        const token = getState('token');
        if (!token) {
            Toast.warning('暂无可复制的 Token');
            return;
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(token).then(() => {
                Toast.success('Token 已复制到剪贴板');
            }).catch(() => {
                copyFallback(token);
            });
        } else {
            copyFallback(token);
        }
    });

    function copyFallback(text) {
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

    const btnClear = el('btn-clear-orders');
    if (btnClear) btnClear.addEventListener('click', () => {
        UI.clearOrders();
    });

    // --- Bark 推送设置事件 ---
    const barkForm = el('bark-config-form');
    if (barkForm) barkForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const token = getState('token');
        if (!token) {
            Toast.warning('请先启动服务器');
            return;
        }
        try {
            await api.updateBarkConfig(_collectBarkForm(), token);
            Toast.success('推送设置已保存');
        } catch (error) {
            Toast.error(`保存失败: ${error.message}`);
        }
    });

    const btnBarkTest = el('btn-bark-test');
    if (btnBarkTest) btnBarkTest.addEventListener('click', async () => {
        const token = getState('token');
        if (!token) {
            Toast.warning('请先启动服务器');
            return;
        }
        const config = _collectBarkForm();
        if (!config.device_key) {
            Toast.warning('请输入 Bark Key');
            return;
        }
        try {
            await api.testBarkConfig(config, token);
            Toast.success('测试推送已发送，请查看手机');
        } catch (error) {
            Toast.error(`测试推送失败: ${error.message}`);
        }
    });

    refreshBarkConfig();

    const themeToggle = el('theme-toggle');
    if (themeToggle) themeToggle.addEventListener('click', () => {
        UI.toggleTheme();
    });
}
