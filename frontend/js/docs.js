import { api } from './api.js';

export const Docs = {
  _requestId: 0,

  async init() {
    await this.loadDocList();
  },

  _slugify(text) {
    return text
      .trim()
      .replace(/\s+/g, '-')
      .replace(/[^\w一-鿿-]/g, '')
      .replace(/-+/g, '-');
  },

  removeAllSubItems() {
    const nav = document.getElementById('docs-nav');
    if (!nav) return;
    nav.querySelectorAll('.docs-sub-nav').forEach((el) => el.remove());
  },

  renderSubItems(docId) {
    const nav = document.getElementById('docs-nav');
    if (!nav) return;

    const activeBtn = nav.querySelector(`[data-doc-id="${docId}"]`);
    if (!activeBtn) return;
    const parentLi = activeBtn.closest('li');
    if (!parentLi) return;

    parentLi.querySelector('.docs-sub-nav')?.remove();

    const article = document.querySelector('#docs-content .docs-article');
    if (!article) return;
    const h2s = article.querySelectorAll('h2');
    if (h2s.length === 0) return;

    const subNav = document.createElement('ul');
    subNav.className = 'docs-sub-nav';

    h2s.forEach((h2, idx) => {
      if (!h2.id) {
        h2.id = this._slugify(h2.textContent) || `section-${idx}`;
      }

      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.className = 'docs-sub-item';
      btn.textContent = h2.textContent.trim();
      btn.addEventListener('click', () => {
        const target = document.getElementById(h2.id);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
      li.appendChild(btn);
      subNav.appendChild(li);
    });

    parentLi.appendChild(subNav);
  },

  loadFirstDoc() {
    const firstBtn = document.querySelector('#docs-nav .docs-nav-item');
    if (firstBtn) {
      firstBtn.click();
    }
  },

  async loadDoc(docId) {
    const content = document.getElementById('docs-content');
    if (!content) return;

    const requestId = ++this._requestId;
    this.removeAllSubItems();

    content.innerHTML = '<div class="docs-placeholder">加载中...</div>';

    try {
      const result = await api.getDoc(docId);

      if (requestId !== this._requestId) return;

      const html = marked.parse(result.data.content);
      content.innerHTML = `<div class="docs-article">${html}</div>`;
      this.renderSubItems(docId);
    } catch (error) {
      if (requestId === this._requestId) {
        content.innerHTML = `<div class="docs-placeholder">加载文档失败: ${error.message}</div>`;
      }
    }
  },

  async loadDocList() {
    const nav = document.getElementById('docs-nav');
    if (!nav) return;

    try {
      const result = await api.getDocList();
      const docs = result.data || [];

      nav.innerHTML = docs.map((doc) => `
        <li>
          <button class="docs-nav-item" data-doc-id="${doc.id}">
            ${doc.title}
          </button>
        </li>
      `).join('');

      nav.querySelectorAll('.docs-nav-item').forEach((btn) => {
        btn.addEventListener('click', () => {
          nav.querySelectorAll('.docs-nav-item').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          this.loadDoc(btn.dataset.docId);
        });
      });
    } catch (error) {
      nav.innerHTML = '<li style="color:var(--color-muted);padding:var(--spacing-sm) var(--spacing-base);">加载文档列表失败</li>';
    }
  }
};
