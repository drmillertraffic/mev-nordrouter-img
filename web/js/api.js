/**
 * API client — communicates with the FastAPI backend.
 * All requests go to /api/* on the same origin.
 */
const API = {
  _token: null,

  setToken(token) { this._token = token; },

  async _fetch(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...opts.headers };
    if (this._token) headers['Authorization'] = `Bearer ${this._token}`;
    const resp = await fetch(`/api${path}`, { ...opts, headers });
    if (resp.status === 401) {
      App.logout();
      throw new Error('Unauthorized');
    }
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Request failed');
    }
    return resp.json();
  },

  // Auth
  async login(password) {
    const data = await this._fetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    });
    this._token = data.token;
    return data;
  },

  // Models catalog
  async getModels() {
    return this._fetch('/models');
  },

  // Generate
  async generate(params) {
    // params: { prompt, models[], variants, aspect_ratio, resolution, format, enhance_prompt, comment, references[] (base64 data URLs) }
    return this._fetch('/generate', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  // Get generation status
  async getGenerationStatus(genId) {
    return this._fetch(`/generate/${genId}/status`);
  },

  // Retry single model
  async retrySingle(params) {
    return this._fetch('/generate/retry', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  // Get image file URL
  imageUrl(imageId) {
    return `/api/images/${imageId}`;
  },

  // History
  async getHistory(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this._fetch(`/history${qs ? '?' + qs : ''}`);
  },

  async deleteHistory(id) {
    return this._fetch(`/history/${id}`, { method: 'DELETE' });
  },

  // Templates
  async getTemplates() {
    return this._fetch('/templates');
  },

  async createTemplate(data) {
    return this._fetch('/templates', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async updateTemplate(id, data) {
    return this._fetch(`/templates/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async deleteTemplate(id) {
    return this._fetch(`/templates/${id}`, { method: 'DELETE' });
  },

  async duplicateTemplate(id) {
    return this._fetch(`/templates/${id}/duplicate`, { method: 'POST' });
  },

  // Favorites
  async getFavorites() {
    return this._fetch('/favorites');
  },

  async toggleFavorite(modelId) {
    return this._fetch(`/favorites/${modelId}`, { method: 'POST' });
  },
};