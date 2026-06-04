import { api } from './api.js';

export const Docs = {
  async init() {
    await this.loadDocList();
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
  },

  async loadDoc(docId) {
    const content = document.getElementById('docs-content');
    if (!content) return;

    content.innerHTML = '<div class="docs-placeholder">加载中...</div>';

    try {
      const result = await api.getDoc(docId);
      const html = marked.parse(result.data.content);
      content.innerHTML = `<div class="docs-article">${html}</div>`;
    } catch (error) {
      content.innerHTML = `<div class="docs-placeholder">加载文档失败: ${error.message}</div>`;
    }
  }
};
