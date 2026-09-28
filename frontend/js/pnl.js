import { api } from './api.js';
import { getState } from './state.js';
import { getStrategies } from './strategy.js';
import { Toast } from './toast.js';

let _scope = 'account';
let _period = 'day';
let _anchor = new Date();
let _lastData = null;
let _curveChart = null;
let _calendarChart = null;

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

function calendarRange() {
    if (_period === 'year') {
        return String(_anchor.getFullYear());
    }
    const first = new Date(_anchor.getFullYear(), _anchor.getMonth(), 1);
    const last = new Date(_anchor.getFullYear(), _anchor.getMonth() + 1, 0);
    return [fmtDate(first), fmtDate(last)];
}

function renderCalendar(payload) {
    const chartEl = document.getElementById('pnl-calendar-chart');
    const emptyEl = document.getElementById('pnl-calendar-empty');
    if (!chartEl || !emptyEl) return;

    const daily = (payload && payload.daily_returns) || [];
    if (daily.length === 0) {
        disposeChart('pnl-calendar-chart');
        _calendarChart = null;
        chartEl.classList.add('hidden');
        emptyEl.classList.remove('hidden');
        return;
    }
    chartEl.classList.remove('hidden');
    emptyEl.classList.add('hidden');
    chartEl.classList.toggle('year-view', _period === 'year');

    const colors = getThemeColors();
    const data = daily.map(d => [d.date, d.return, d.pnl]);
    const maxAbs = Math.max(...daily.map(d => Math.abs(d.return || 0)), 0.0001);

    const chart = getChart('pnl-calendar-chart');
    if (!chart) return;
    _calendarChart = chart;

    chart.setOption({
        animation: false,
        tooltip: {
            ...baseTooltip(colors),
            formatter(params) {
                const v = params.value;
                if (!v) return '';
                return `${v[0]}<br/>盈亏：${fmtMoney(v[2], true)}<br/>收益率：${fmtPercent(v[1])}`;
            },
        },
        visualMap: {
            type: 'continuous',
            min: -maxAbs,
            max: maxAbs,
            dimension: 1,
            calculable: false,
            orient: 'horizontal',
            left: 'center',
            bottom: 0,
            itemWidth: 12,
            itemHeight: 100,
            textStyle: { color: colors.body },
            formatter: v => (v * 100).toFixed(1) + '%',
            inRange: {
                color: [colors.down, colors.surfaceSoft, colors.up],
            },
        },
        calendar: {
            top: _period === 'year' ? 40 : 30,
            left: 48,
            right: 24,
            bottom: 48,
            cellSize: ['auto', 'auto'],
            range: calendarRange(),
            orient: 'horizontal',
            splitLine: { lineStyle: { color: colors.hairline, width: 1 } },
            itemStyle: { color: colors.surfaceSoft, borderColor: colors.canvas, borderWidth: 2 },
            dayLabel: {
                firstDay: 1,
                nameMap: ['日', '一', '二', '三', '四', '五', '六'],
                color: colors.body,
            },
            monthLabel: {
                nameMap: ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月'],
                color: colors.ink,
            },
            yearLabel: { show: false },
        },
        series: [{
            type: 'heatmap',
            coordinateSystem: 'calendar',
            data,
            label: {
                show: true,
                color: colors.ink,
                fontSize: 10,
                formatter(params) {
                    return String(parseInt(params.value[0].slice(8, 10), 10));
                },
            },
            emphasis: {
                itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0, 0, 0, 0.25)' },
            },
        }],
    }, true);
    chart.resize();
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
            renderCalendar(_lastData);
        }
    }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    window.addEventListener('resize', () => {
        if (_curveChart) _curveChart.resize();
        if (_calendarChart) _calendarChart.resize();
    });
}
