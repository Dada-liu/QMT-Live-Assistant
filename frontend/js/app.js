import { UI } from './ui.js';
import { api } from './api.js';
import { getState, setState, getStoredToken } from './state.js';
import { initConfigPanel } from './config-panel.js';
import { initMonitor, startPolling, stopPolling, startStatusCheck, stopStatusCheck } from './monitor.js';
import { initDashboard, refreshDashboard } from './dashboard.js';
import { Toast } from './toast.js';

async function initApp() {
    UI.initTheme();
    initConfigPanel();
    initMonitor();
    initDashboard();
    initJqConverter();
    initTabNavigation();
    startStatusCheck();

    UI.switchTab('account');

    await checkServerStatus();

    document.getElementById('btn-goto-config').addEventListener('click', () => {
        UI.switchTab('config');
    });

    document.getElementById('btn-connect-token').addEventListener('click', async () => {
        const tokenInput = document.getElementById('connect-token-input');
        const token = tokenInput.value.trim();
        if (!token) {
            Toast.warning('请输入 Token');
            return;
        }
        try {
            await api.testConnection(token);
            setState('token', token);
            setState('serverRunning', true);
            UI.updateServerInfo({ running: true });
            UI.disableForm(true);
            UI.showSection('server-info');
            UI.showSection('dashboard');
            UI.showSection('monitor');
            refreshDashboard();
            startPolling();
            Toast.success('连接成功！');
        } catch (error) {
            Toast.error(`连接失败: ${error.message}`);
        }
    });
}

async function checkServerStatus() {
    const storedToken = getStoredToken();
    try {
        const result = await api.getServerInfo();
        if (result.data && result.data.running) {
            setState('serverRunning', true);
            UI.updateServerInfo(result.data);
            UI.disableForm(true);

            if (storedToken) {
                setState('token', storedToken);
                refreshDashboard();
                startPolling();
                UI.switchTab('account');
            } else {
                UI.switchTab('account');
                UI.showConnectPrompt();
            }
        }
    } catch (error) {
        // Server not running, normal state
    }
}

function initTabNavigation() {
    document.querySelectorAll('.top-nav-links a').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.getAttribute('href').substring(1);
            UI.switchTab(targetId);
        });
    });
}

function initJqConverter() {
    function jqToQmt(code) {
        if (code.endsWith('.XSHE')) return code.replace('.XSHE', '.SZ');
        if (code.endsWith('.XSHG')) return code.replace('.XSHG', '.SH');
        if (code.endsWith('.XBJ')) return code.replace('.XBJ', '.BJ');
        return code;
    }

    function qmtToJq(code) {
        if (code.endsWith('.SZ')) return code.replace('.SZ', '.XSHE');
        if (code.endsWith('.SH')) return code.replace('.SH', '.XSHG');
        if (code.endsWith('.BJ')) return code.replace('.BJ', '.XBJ');
        return code;
    }

    const jqInput = document.getElementById('jq-code');
    const qmtInput = document.getElementById('qmt-code');

    let debounceTimer;

    jqInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const code = jqInput.value.trim();
        if (!code) { qmtInput.value = ''; return; }
        debounceTimer = setTimeout(() => {
            qmtInput.value = jqToQmt(code);
        }, 200);
    });

    qmtInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const code = qmtInput.value.trim();
        if (!code) { jqInput.value = ''; return; }
        debounceTimer = setTimeout(() => {
            jqInput.value = qmtToJq(code);
        }, 200);
    });
}

document.addEventListener('DOMContentLoaded', initApp);
