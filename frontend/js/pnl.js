import { api } from './api.js';
import { getState } from './state.js';
import { getStrategies } from './strategy.js';
import { Toast } from './toast.js';

let _scope = 'account';
let _period = 'day';
let _anchor = new Date();
let _lastData = null;
let _curveChart = null;

function pad2(n) {
    return String(n).padStart(2, '0');
}

function fmtDate(d) {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function fmtMonth(d) {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function fmtMoney(value, signed = false) {
    if (value === undefined || value === null || isNaN(parseFloat(value))) return '--';
    const num = parseFloat(value);
    const abs = Math.abs(num).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (!signed) return '¥ ' + abs;
    return (num >= 0 ? '+ ¥ ' : '- ¥ ') + abs;
}

function fmtPercent(value, signed = true) {
    if (value === undefined || value === null || isNaN(parseFloat(value))) return '--';
    const num = parseFloat(value) * 100;
    const sign = signed ? (num >= 0 ? '+' : '-') : '';
    return sign + Math.abs(num).toFixed(2) + '%';
}

function pnlClass(value) {
    const num = parseFloat(value);
    if (isNaN(num) || num === 0) return '';
    return num > 0 ? 'up' : 'down';
}

function getThemeColors() {
    const style = getComputedStyle(document.documentElement);
    const pick = (name, fallback) => style.getPropertyValue(name).trim() || fallback;
    return {
        up: pick('--color-pnl-up', '#cf202f'),
        down: pick('--color-pnl-down', '#05b169'),
        ink: pick('--color-ink', '#0a0b0d'),
        body: pick('--color-body', '#5b616e'),
        hairline: pick('--color-hairline', '#dee1e6'),
        hairlineSoft: pick('--color-hairline-soft', '#eef0f3'),
        canvas: pick('--color-canvas', '#ffffff'),
        surfaceCard: pick('--color-surface-card', '#ffffff'),
        surfaceSoft: pick('--color-surface-soft', '#f7f7f7'),
        mutedSoft: pick('--color-muted-soft', '#a8acb3'),
    };
}

function hexToRgba(hex, alpha) {
    const m = hex.replace('#', '');
    if (m.length !== 6) return hex;
    const r = parseInt(m.slice(0, 2), 16);
    const g = parseInt(m.slice(2, 4), 16);
    const b = parseInt(m.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function updateDateLabel() {
    const label = document.getElementById('pnl-date-label');
    if (!label) return;
    if (_period === 'day') label.textContent = fmtDate(_anchor);
    else if (_period === 'month') label.textContent = fmtMonth(_anchor);
    else label.textContent = String(_anchor.getFullYear());
}

function stepAnchor(direction) {
    const d = new Date(_anchor.getTime());
    if (_period === 'day') d.setDate(d.getDate() + direction);
    else if (_period === 'month') d.setMonth(d.getMonth() + direction);
    else d.setFullYear(d.getFullYear() + direction);
    _anchor = d;
}

function populateStrategySelect() {
    const select = document.getElementById('pnl-strategy-select');
    if (!select) return;
    const current = select.value;
    const strategies = getStrategies();
    select.innerHTML = '';
    strategies.forEach(s => {
        const option = document.createElement('option');
        option.value = s.id;
        option.textContent = s.name;
        select.appendChild(option);
    });
    if (current && strategies.some(s => String(s.id) === String(current))) {
        select.value = current;
    }
}

function setSegActive(groupId, attr, value) {
    const group = document.getElementById(groupId);
    if (!group) return;
    group.querySelectorAll('.seg-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset[attr] === value);
    });
}

function getChart(domId) {
    const el = document.getElementById(domId);
    if (!el || !window.echarts) return null;
    let chart = window.echarts.getInstanceByDom(el);
    if (!chart) chart = window.echarts.init(el);
    return chart;
}

function disposeChart(domId) {
    const el = document.getElementById(domId);
    if (!el || !window.echarts) return;
    const chart = window.echarts.getInstanceByDom(el);
    if (chart) chart.dispose();
}

function baseTooltip(colors) {
    return {
        backgroundColor: colors.surfaceCard,
        borderColor: colors.hairline,
        textStyle: { color: colors.ink, fontSize: 13 },
    };
}

function renderSummary(summary) {
    const fields = [
        ['pnl-total-asset', summary && summary.total_asset, v => fmtMoney(v), false],
        ['pnl-today-pnl', summary && summary.today_pnl, v => fmtMoney(v, true), true],
        ['pnl-cum-return', summary && summary.cum_return, v => fmtPercent(v), true],
        ['pnl-period-return', summary && summary.period_return, v => fmtPercent(v), true],
    ];
    fields.forEach(([id, value, formatter, colored]) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove('up', 'down');
        if (!summary || value === undefined || value === null) {
            el.textContent = '--';
            return;
        }
        el.textContent = formatter(value);
        if (colored) {
            const cls = pnlClass(value);
            if (cls) el.classList.add(cls);
        }
    });
}

function renderCurve(payload) {
    const chartEl = document.getElementById('pnl-curve-chart');
    const emptyEl = document.getElementById('pnl-curve-empty');
    if (!chartEl || !emptyEl) return;

    const curve = (payload && payload.curve) || [];
    if (curve.length === 0) {
        disposeChart('pnl-curve-chart');
        _curveChart = null;
        chartEl.classList.add('hidden');
        emptyEl.classList.remove('hidden');
        return;
    }
    chartEl.classList.remove('hidden');
    emptyEl.classList.add('hidden');

    const colors = getThemeColors();
    const labels = curve.map(p => (_period === 'day' ? String(p.t).slice(11) : String(p.t).slice(5)));
    const values = curve.map(p => p.return);
    const last = values[values.length - 1];
    const lineColor = (last || 0) >= 0 ? colors.up : colors.down;

    const chart = getChart('pnl-curve-chart');
    if (!chart) return;
    _curveChart = chart;

    chart.setOption({
        animation: false,
        grid: { left: 56, right: 24, top: 24, bottom: 36 },
        tooltip: {
            ...baseTooltip(colors),
            trigger: 'axis',
            formatter(params) {
                const p = params[0];
                const point = curve[p.dataIndex];
                if (!point) return '';
                return `${point.t}<br/>总资产：${fmtMoney(point.total_asset)}<br/>收益率：${fmtPercent(point.return)}`;
            },
        },
        xAxis: {
            type: 'category',
            data: labels,
            boundaryGap: false,
            axisLine: { lineStyle: { color: colors.hairline } },
            axisTick: { show: false },
            axisLabel: { color: colors.body },
        },
        yAxis: {
            type: 'value',
            scale: true,
            axisLabel: {
                color: colors.body,
                formatter: v => (v * 100).toFixed(1) + '%',
            },
            splitLine: { lineStyle: { color: colors.hairlineSoft } },
        },
        series: [{
            type: 'line',
            data: values,
            showSymbol: false,
            smooth: true,
            lineStyle: { color: lineColor, width: 2 },
            itemStyle: { color: lineColor },
            areaStyle: {
                color: {
                    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [
                        { offset: 0, color: hexToRgba(lineColor, 0.25) },
                        { offset: 1, color: hexToRgba(lineColor, 0.02) },
                    ],
                },
            },
            markLine: {
                silent: true,
                symbol: 'none',
                label: { show: false },
                lineStyle: { color: colors.mutedSoft, type: 'dashed' },
                data: [{ yAxis: 0 }],
            },
        }],
    }, true);
    chart.resize();
}

function fmtSignedAmount(value) {
    return fmtMoney(value, true).replace(' ¥ ', '');
}

function pnlAlphaPct(value, maxAbs) {
    const ratio = Math.min(Math.abs(parseFloat(value) || 0) / (maxAbs || 1), 1);
    return Math.round(8 + 30 * ratio);
}

function createCalCell({ label, pnl, ret, titlePrefix = '', highlight = false, maxAbs = 1 }) {
    const cell = document.createElement('div');
    cell.className = 'pnl-cal-cell';

    const num = document.createElement('div');
    num.className = 'pnl-cal-label';
    num.textContent = label;
    cell.appendChild(num);

    if (pnl === undefined || pnl === null) {
        cell.classList.add('muted');
    } else {
        cell.classList.add('has-data', pnl >= 0 ? 'up' : 'down');
        cell.style.setProperty('--pnl-pct', String(pnlAlphaPct(pnl, maxAbs)));
        const amount = document.createElement('div');
        amount.className = 'pnl-cal-pnl';
        amount.textContent = fmtSignedAmount(pnl);
        cell.appendChild(amount);
        if (ret !== undefined && ret !== null) {
            cell.title = `${titlePrefix ? titlePrefix + ' ' : ''}收益率：${fmtPercent(ret)}`;
        }
    }

    if (highlight) cell.classList.add('current');
    return cell;
}

function renderDayCalendar(container, daily) {
    const year = _anchor.getFullYear();
    const month = _anchor.getMonth();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const offset = (new Date(year, month, 1).getDay() + 6) % 7;
    const dataMap = new Map(daily.map(d => [d.date, d]));
    const maxAbs = Math.max(...daily.map(d => Math.abs(d.pnl || 0)), 1);
    const todayStr = fmtDate(new Date());

    const header = document.createElement('div');
    header.className = 'pnl-cal-grid pnl-cal-weekdays';
    ['一', '二', '三', '四', '五', '六', '日'].forEach(name => {
        const el = document.createElement('div');
        el.className = 'pnl-cal-weekday';
        el.textContent = name;
        header.appendChild(el);
    });
    container.appendChild(header);

    const grid = document.createElement('div');
    grid.className = 'pnl-cal-grid pnl-cal-days';
    for (let i = 0; i < offset; i++) {
        const blank = document.createElement('div');
        blank.className = 'pnl-cal-cell blank';
        grid.appendChild(blank);
    }
    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${year}-${pad2(month + 1)}-${pad2(d)}`;
        const rec = dataMap.get(dateStr);
        grid.appendChild(createCalCell({
            label: String(d),
            pnl: rec ? rec.pnl : null,
            ret: rec ? rec.return : null,
            titlePrefix: dateStr,
            highlight: dateStr === todayStr,
            maxAbs,
        }));
    }
    container.appendChild(grid);
}

function renderMonthCalendar(container, monthly) {
    const year = _anchor.getFullYear();
    const dataMap = new Map(monthly.map(m => [m.month, m]));
    const maxAbs = Math.max(...monthly.map(m => Math.abs(m.pnl || 0)), 1);
    const now = new Date();
    const isCurrentYear = year === now.getFullYear();

    const grid = document.createElement('div');
    grid.className = 'pnl-cal-grid pnl-cal-months';
    for (let m = 1; m <= 12; m++) {
        const key = `${year}-${pad2(m)}`;
        const rec = dataMap.get(key);
        grid.appendChild(createCalCell({
            label: `${m}月`,
            pnl: rec ? rec.pnl : null,
            ret: rec ? rec.return : null,
            titlePrefix: key,
            highlight: isCurrentYear && m === now.getMonth() + 1,
            maxAbs,
        }));
    }
    container.appendChild(grid);
}

function renderYearCalendar(container, yearly) {
    const maxAbs = Math.max(...yearly.map(y => Math.abs(y.pnl || 0)), 1);
    const currentYear = new Date().getFullYear();

    const row = document.createElement('div');
    row.className = 'pnl-cal-years';
    yearly.forEach(rec => {
        row.appendChild(createCalCell({
            label: rec.year,
            pnl: rec.pnl,
            ret: rec.return,
            titlePrefix: rec.year,
            highlight: parseInt(rec.year, 10) === currentYear,
            maxAbs,
        }));
    });
    container.appendChild(row);
}

function renderCalendar(payload) {
    const container = document.getElementById('pnl-calendar-chart');
    const emptyEl = document.getElementById('pnl-calendar-empty');
    if (!container || !emptyEl) return;
    container.innerHTML = '';

    let list;
    let renderer;
    if (_period === 'day') {
        list = payload && payload.daily_returns;
        renderer = renderDayCalendar;
    } else if (_period === 'month') {
        list = payload && payload.monthly_returns;
        renderer = renderMonthCalendar;
    } else {
        list = payload && payload.yearly_returns;
        renderer = renderYearCalendar;
    }

    if (!list || list.length === 0) {
        container.classList.add('hidden');
        emptyEl.classList.remove('hidden');
        return;
    }
    container.classList.remove('hidden');
    emptyEl.classList.add('hidden');
    renderer(container, list);
}

function renderAll(payload) {
    _lastData = payload;
    renderSummary(payload && payload.summary);
    renderCurve(payload);
    renderCalendar(payload);
}

export async function loadPnl() {
    const token = getState('token');
    if (!token) {
        renderAll(null);
        return;
    }

    if (_scope === 'strategy') {
        populateStrategySelect();
        const select = document.getElementById('pnl-strategy-select');
        const strategyId = select && select.value;
        if (!strategyId) {
            renderAll(null);
            return;
        }
    }

    const params = {
        scope: _scope,
        period: _period,
        date: fmtDate(_anchor),
    };
    if (_scope === 'strategy') {
        params.strategy_id = document.getElementById('pnl-strategy-select').value;
    }

    try {
        const result = await api.getPnlOverview(token, params);
        renderAll(result && result.data !== undefined ? result.data : result);
    } catch (error) {
        renderAll(null);
        Toast.error(`收益数据加载失败: ${error.message}`);
    }
}

export function initPnl() {
    updateDateLabel();

    const scopeGroup = document.getElementById('pnl-scope-group');
    if (scopeGroup) {
        scopeGroup.querySelectorAll('.seg-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                _scope = btn.dataset.scope;
                setSegActive('pnl-scope-group', 'scope', _scope);
                const strategyGroup = document.getElementById('pnl-strategy-group');
                if (strategyGroup) strategyGroup.classList.toggle('hidden', _scope !== 'strategy');
                if (_scope === 'strategy') populateStrategySelect();
                loadPnl();
            });
        });
    }

    const strategySelect = document.getElementById('pnl-strategy-select');
    if (strategySelect) {
        strategySelect.addEventListener('change', () => loadPnl());
    }

    const periodGroup = document.getElementById('pnl-period-group');
    if (periodGroup) {
        periodGroup.querySelectorAll('.seg-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                _period = btn.dataset.period;
                setSegActive('pnl-period-group', 'period', _period);
                updateDateLabel();
                loadPnl();
            });
        });
    }

    document.getElementById('pnl-date-prev')?.addEventListener('click', () => {
        stepAnchor(-1);
        updateDateLabel();
        loadPnl();
    });
    document.getElementById('pnl-date-next')?.addEventListener('click', () => {
        stepAnchor(1);
        updateDateLabel();
        loadPnl();
    });

    new MutationObserver(() => {
        if (_lastData) {
            renderCurve(_lastData);
        }
    }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    window.addEventListener('resize', () => {
        if (_curveChart) _curveChart.resize();
    });
}
