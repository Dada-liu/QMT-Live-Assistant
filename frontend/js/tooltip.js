/** 自定义全局 tooltip 组件。
 *
 * 通过 data-tooltip 属性触发：
 *   <span data-tooltip="提示文本">hover me</span>
 *
 * 使用方式：
 *   import { Tooltip } from './tooltip.js';
 *   Tooltip.init();
 */

const Tooltip = {
    _el: null,
    _visible: false,

    init(container = document.body) {
        if (this._el) return;

        const el = document.createElement('div');
        el.className = 'custom-tooltip';
        el.setAttribute('role', 'tooltip');
        el.style.visibility = 'hidden';
        container.appendChild(el);
        this._el = el;

        container.addEventListener('mouseover', (e) => this._onMouseOver(e));
        container.addEventListener('mouseout', (e) => this._onMouseOut(e));
        container.addEventListener('mousemove', (e) => this._onMouseMove(e));

        // 滚动或 resize 时隐藏，避免定位错乱
        window.addEventListener('scroll', () => this.hide(), { passive: true });
        window.addEventListener('resize', () => this.hide());
    },

    _onMouseOver(e) {
        const target = e.target.closest('[data-tooltip]');
        if (!target) return;

        const text = target.dataset.tooltip;
        if (!text || !text.trim()) return;

        this._currentTarget = target;
        this.show(target, text);
    },

    _onMouseOut(e) {
        const target = e.target.closest('[data-tooltip]');
        if (!target) return;
        this.hide();
    },

    _onMouseMove(e) {
        if (!this._visible) return;
        this._positionAt(e.clientX, e.clientY);
    },

    show(element, text) {
        if (!this._el) return;
        this._el.textContent = text;
        this._el.classList.add('visible');
        this._visible = true;

        const rect = element.getBoundingClientRect();
        // 默认显示在元素上方居中
        const x = rect.left + rect.width / 2;
        const y = rect.top;
        this._positionAt(x, y, true);
    },

    hide() {
        if (!this._el) return;
        this._el.classList.remove('visible');
        this._visible = false;
        this._currentTarget = null;
    },

    _positionAt(x, y, preferAbove = false) {
        if (!this._el) return;

        const padding = 8;
        const tooltipRect = this._el.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        let left = x - tooltipRect.width / 2;
        let top;

        if (preferAbove) {
            top = y - tooltipRect.height - padding;
            // 上方空间不足时放到下方
            if (top < padding) {
                top = y + padding;
            }
        } else {
            top = y + padding;
        }

        // 左右边界检测
        if (left < padding) {
            left = padding;
        } else if (left + tooltipRect.width > vw - padding) {
            left = vw - tooltipRect.width - padding;
        }

        this._el.style.left = `${left}px`;
        this._el.style.top = `${top}px`;
        this._el.style.visibility = 'visible';
    },
};

export { Tooltip };
