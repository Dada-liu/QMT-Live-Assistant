import { api } from './api.js';
import { UI } from './ui.js';
import { getState, setState } from './state.js';
import { startPolling, stopPolling } from './monitor.js';
import { refreshDashboard } from './dashboard.js';
import { Toast } from './toast.js';

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
            Toast.warning('请输入券商账户ID');
            return;
        }
        if (!config.qmt_path) {
            Toast.warning('请输入miniQMT路径');
            return;
        }

        try {
            const result = await api.startServer(config);
            const data = result.data;

            UI.updateServerInfo(data);
            UI.disableForm(true);
            setState('serverRunning', true);
            setState('token', data.token);

            Toast.success('服务器启动成功！');
            UI.switchTab('account');
            refreshDashboard();
            startPolling();
        } catch (error) {
            Toast.error(`启动失败: ${error.message}`);
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
            Toast.info('服务器已停止');
        } catch (error) {
            Toast.error(`停止失败: ${error.message}`);
        }
    });

    document.getElementById('btn-test-connection').addEventListener('click', async () => {
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
            Toast.error(`连接测试失败: ${error.message}`);
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
                Toast.success('Token 已复制到剪贴板');
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
