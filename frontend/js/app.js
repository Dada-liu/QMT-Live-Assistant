import { UI } from './ui.js';
import { api } from './api.js';
import { getState, setState, getStoredToken } from './state.js';
import { initConfigPanel, refreshBarkConfig } from './config-panel.js';
import { initMonitor, fetchOrders, fetchSignalLogs, startStatusCheck, stopStatusCheck, applyOrderFilters } from './monitor.js';
import { initDashboard, refreshDashboard } from './dashboard.js';
import { initStrategyPanel, loadStrategies, getStrategies, populateStrategyDropdown } from './strategy.js';
import { Toast } from './toast.js';
import { Docs } from './docs.js';
import { Tooltip } from './tooltip.js';
import { initPnl, loadPnl } from './pnl.js';

async function initApp() {
    UI.initTheme();
    try { Tooltip.init(); } catch (e) { console.error('[init] Tooltip.init failed:', e); }

    try { initConfigPanel(); } catch (e) { console.error('[init] initConfigPanel failed:', e); }
    try { initMonitor(); } catch (e) { console.error('[init] initMonitor failed:', e); }
    try { initDashboard(); } catch (e) { console.error('[init] initDashboard failed:', e); }
    try { initStrategyPanel(); } catch (e) { console.error('[init] initStrategyPanel failed:', e); }
    try { initPnl(); } catch (e) { console.error('[init] initPnl failed:', e); }

    Docs.init();

    UI.setOrderFilterHandler((strategyName) => {
        applyOrderFilters({ strategy_name: strategyName });
    });

    try { initTabNavigation(); } catch (e) { console.error('[init] initTabNavigation failed:', e); }

    startStatusCheck();

    UI.switchTab('account');

    await checkServerStatus();

    document.getElementById('btn-goto-config')?.addEventListener('click', () => {
        UI.switchTab('config');
    });

    document.addEventListener('click', (e) => {
        const link = e.target.closest('.js-goto-config-strategy');
        if (!link) return;
        e.preventDefault();
        UI.switchTab('config');
        const target = document.getElementById('strategy-management');
        if (target) target.scrollIntoView({ behavior: 'smooth' });
    });

    const btnDocsTutorial = document.getElementById('btn-docs-tutorial');
    if (btnDocsTutorial) {
        btnDocsTutorial.addEventListener('click', () => {
            UI.switchTab('docs');
            const nav = document.getElementById('docs-nav');
            if (nav) {
                const btn = nav.querySelector('[data-doc-id="jq-send-signal-to-qmt"]');
                if (btn) btn.click();
            }
        });
    }

    document.getElementById('btn-connect-token')?.addEventListener('click', handleTokenConnect);
    document.getElementById('connect-token-input')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleTokenConnect();
        }
    });
}

async function handleTokenConnect() {
    const tokenInput = document.getElementById('connect-token-input');
    if (!tokenInput) return;

    const token = tokenInput.value.trim();
    if (!token) {
        Toast.warning('请输入 Token');
        return;
    }

    const btnConnect = document.getElementById('btn-connect-token');
    if (btnConnect) btnConnect.disabled = true;

    try {
        await api.testConnection(token);

        setState('token', token);
        setState('serverRunning', true);

        const serverInfoResult = await api.getServerInfo();
        const serverData = serverInfoResult?.data || { running: true };
        setState('serverInfo', { ...(getState('serverInfo') || {}), ...serverData });
        UI.updateServerInfo(serverData);
        UI.disableForm(true);

        UI.switchTab('account');

        await refreshDashboard();
        await loadStrategies();
        populateStrategyDropdown();
        refreshBarkConfig();

        tokenInput.value = '';
        Toast.success('连接成功！');
    } catch (error) {
        tokenInput.value = '';
        Toast.error(`连接失败: ${error.message}`);
    } finally {
        if (btnConnect) btnConnect.disabled = false;
    }
}

async function checkServerStatus() {
    const storedToken = getStoredToken();
    try {
        const result = await api.getServerInfo();
        const data = result.data || {};
        const serverRunning = !!data.running;
        const qmtConnected = !!data.qmt_connected;

        setState('serverRunning', serverRunning);
        setState('qmtConnected', qmtConnected);
        setState('connectionState', data.connection_state || 'disconnected');
        setState('lastConnectionError', data.last_connection_error || null);
        UI.updateServerInfo(data);

        if (serverRunning) {
            UI.disableForm(true);
            if (qmtConnected) {
                UI.hideReconnectingBanner();
                if (storedToken) {
                    setState('token', storedToken);
                    await refreshDashboard();
                    await loadStrategies();
                    populateStrategyDropdown();
                    refreshBarkConfig();
                    UI.switchTab('account');
                } else {
                    UI.switchTab('account');
                    UI.showConnectPrompt();
                }
            } else {
                const msg = data.last_connection_error
                    ? `QMT 连接断开：${data.last_connection_error}`
                    : 'QMT 连接断开，正在重连...';
                UI.showReconnectingBanner(msg);
            }
        }
    } catch (error) {
        // Server not running, normal state
    } finally {
        UI.hideLoading();
    }
}

function initTabNavigation() {
    const navLinks = document.querySelector('.top-nav-links');
    const menuToggle = document.getElementById('mobile-menu-toggle');

    function setMobileMenuOpen(open) {
        if (!navLinks || !menuToggle) return;
        navLinks.classList.toggle('open', open);
        menuToggle.setAttribute('aria-expanded', String(open));
    }

    if (menuToggle && navLinks) {
        menuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = navLinks.classList.contains('open');
            setMobileMenuOpen(!isOpen);
        });
    }

    document.querySelectorAll('.top-nav-links a').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.getAttribute('href').substring(1);
            UI.switchTab(targetId);
            setMobileMenuOpen(false);
            if (targetId === 'trade') {
                fetchOrders();
                fetchSignalLogs();
            }
            if (targetId === 'pnl') {
                loadPnl();
            }
        });
    });

    document.addEventListener('click', (e) => {
        if (!navLinks || !menuToggle) return;
        const target = e.target;
        if (!navLinks.contains(target) && !menuToggle.contains(target)) {
            setMobileMenuOpen(false);
        }
    });
}

document.addEventListener('DOMContentLoaded', initApp);
