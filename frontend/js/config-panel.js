import { api } from './api.js';
import { UI } from './ui.js';
import { getState, setState } from './state.js';
import { startPolling, stopPolling } from './monitor.js';

export function initConfigPanel() {
    const form = document.getElementById('config-form');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(form);
        const config = {
            account_id: formData.get('account_id').trim(),
            qmt_path: formData.get('qmt_path').trim(),
            host: formData.get('host').trim(),
            port: parseInt(formData.get('port')) || 8000,
        };

        if (!config.account_id) {
            alert('请输入券商账户ID');
            return;
        }
        if (!config.qmt_path) {
            alert('请输入miniQMT路径');
            return;
        }

        UI.clearMessage('connection-result');

        try {
            const result = await api.startServer(config);
            const data = result.data;

            UI.updateServerInfo(data);
            UI.disableForm(true);
            setState('serverRunning', true);
            setState('token', data.token);

            UI.showMessage('connection-result', '服务器启动成功！', 'success');
            UI.switchTab('account');
            startPolling();
        } catch (error) {
            UI.showMessage('connection-result', `启动失败: ${error.message}`, 'error');
        }
    });

    document.getElementById('btn-stop').addEventListener('click', async () => {
        try {
            await api.stopServer();
            setState('serverRunning', false);
            UI.disableForm(false);
            UI.resetServerInfo();
            UI.clearSignals();
            UI.resetDashboard();
            stopPolling();
            UI.switchTab('account');
            UI.showMessage('connection-result', '服务器已停止', 'info');
        } catch (error) {
            alert(`停止失败: ${error.message}`);
        }
    });

    document.getElementById('btn-test-connection').addEventListener('click', async () => {
        const token = getState('token');
        if (!token) {
            UI.showMessage('connection-result', '请先启动服务器', 'error');
            return;
        }

        UI.clearMessage('connection-result');

        try {
            const result = await api.testConnection(token);
            const data = result.data;

            UI.updateDashboard(data);
            UI.showMessage('connection-result', '连接测试成功！资产数据已更新。', 'success');

            UI.addSignal({
                type: 'test',
                signal_id: 'conn-test',
                direction: 'info',
                quantity: 0,
                status: 'success',
                timestamp: new Date().toISOString(),
                message: '连接测试成功',
            });
        } catch (error) {
            UI.showMessage('connection-result', `连接测试失败: ${error.message}`, 'error');
            UI.addSignal({
                type: 'test',
                signal_id: 'conn-test',
                direction: 'error',
                quantity: 0,
                status: 'error',
                timestamp: new Date().toISOString(),
                message: `连接测试失败: ${error.message}`,
            });
        }
    });

    document.getElementById('btn-copy-token').addEventListener('click', () => {
        const token = getState('token');
        if (token) {
            navigator.clipboard.writeText(token).then(() => {
                const btn = document.getElementById('btn-copy-token');
                const originalText = btn.textContent;
                btn.textContent = '已复制!';
                setTimeout(() => { btn.textContent = originalText; }, 2000);
            });
        }
    });

    document.getElementById('btn-clear-signals').addEventListener('click', () => {
        UI.clearSignals();
    });

    document.getElementById('theme-toggle').addEventListener('click', () => {
        UI.toggleTheme();
    });
}
