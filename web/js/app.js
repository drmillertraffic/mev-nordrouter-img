/**
 * NordRouter Web UI — Main Application
 */
const App = {
  // State
  state: {
    screen: 'generate',
    models: [],
    selectedModels: [],
    favorites: [],
    variants: 1,
    aspectRatio: '1:1',
    resolution: '1k',
    format: 'png',
    enhancePrompt: false,
    references: [],       // [{file, dataUrl, width, height}]
    templates: [],
    styleTemplates: [],
    selectedStyles: [],   // ids of checked style templates
    activeTemplate: null,
    generations: [],      // feed blocks
    historyItems: [],     // last loaded history items (for lightbox/copy/regen)
    lightboxImages: [],
    lightboxIndex: 0,
    pollingTimers: {},
  },

  // ---- Init ----
  async init() {
    // Check saved token
    const token = sessionStorage.getItem('nr_token');
    if (token) {
      API.setToken(token);
      this.showApp();
      await this.loadModels();
      await this.loadTemplates();
      await this.loadFavorites();
      this.buildAspectMenu();
      this.updateGenCalc();
      await this.restoreFeed();
    }

    // Prompt auto-resize
    const promptEl = document.getElementById('gen-prompt');
    promptEl.addEventListener('input', () => {
      promptEl.style.height = 'auto';
      promptEl.style.height = promptEl.scrollHeight + 'px';
      this.updateGenBtn();
    });

    // Ctrl+Enter to generate
    promptEl.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        this.generate();
      }
    });

    // Close dropdowns on outside click
    document.addEventListener('click', (e) => {
      document.querySelectorAll('.dropdown__menu.open').forEach(menu => {
        if (!menu.parentElement.contains(e.target)) {
          menu.classList.remove('open');
        }
      });
      // Close model panel when clicking outside the models form-section
      const modelPanel = document.getElementById('model-panel');
      if (modelPanel && modelPanel.classList.contains('open')) {
        const modelsSection = document.getElementById('models-trigger')?.closest('.form-section');
        if (!modelsSection || !modelsSection.contains(e.target)) {
          modelPanel.classList.remove('open');
        }
      }
    });

    // Keyboard for lightbox & reset dialog
    document.addEventListener('keydown', (e) => {
      // Reset dialog shortcuts
      const resetDialog = document.getElementById('reset-dialog');
      if (resetDialog && resetDialog.classList.contains('open')) {
        if (e.key === 'Escape') this.closeResetDialog();
        return;
      }
      if (!document.getElementById('lightbox').classList.contains('open')) return;
      if (e.key === 'Escape') this.closeLightbox();
      if (e.key === 'ArrowLeft') this.lightboxNav(-1);
      if (e.key === 'ArrowRight') this.lightboxNav(1);
    });

    // Paste image from clipboard → add to references
    document.addEventListener('paste', (e) => this.handlePaste(e));
  },

  // ---- Auth ----
  async login() {
    const pw = document.getElementById('login-password').value;
    const errEl = document.getElementById('login-error');
    try {
      const data = await API.login(pw);
      sessionStorage.setItem('nr_token', data.token);
      API.setToken(data.token);
      errEl.classList.remove('visible');
      this.showApp();
      await this.loadModels();
      await this.loadTemplates();
      await this.loadFavorites();
      this.buildAspectMenu();
      this.updateGenCalc();
      await this.restoreFeed();
    } catch (e) {
      errEl.classList.add('visible');
    }
  },

  logout() {
    sessionStorage.removeItem('nr_token');
    API._token = null;
    const feed = document.getElementById('gen-feed'); if (feed) feed.innerHTML = '';
    const emptyEl = document.getElementById('feed-empty'); if (emptyEl) emptyEl.style.display = '';
    this.state.generations = [];
    this.state.historyItems = [];
    document.getElementById('app-main').classList.add('hidden');
    document.getElementById('screen-login').style.display = '';
    // Stop all polling
    Object.values(this.state.pollingTimers).forEach(t => clearInterval(t));
    this.state.pollingTimers = {};
  },

  showApp() {
    document.getElementById('screen-login').style.display = 'none';
    document.getElementById('app-main').classList.remove('hidden');
  },

  // ---- Navigation ----
  navigate(screen) {
    this.state.screen = screen;
    ['generate', 'history', 'templates'].forEach(s => {
      const el = document.getElementById(`screen-${s}`);
      if (s === screen) {
        el.classList.remove('hidden');
        el.style.display = '';
      } else {
        el.classList.add('hidden');
      }
    });
    // Update nav buttons
    document.querySelectorAll('[data-screen]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.screen === screen);
    });
    // Load data for screen
    if (screen === 'history') this.loadHistory();
    if (screen === 'templates') this.renderTemplates();
  },

  // ---- Models ----
  async loadModels() {
    try {
      const data = await API.getModels();
      this.state.models = data.models || [];
      // Default: select GPT Image 2 if nothing selected yet
      if (!this.state.selectedModels.length && this.state.models.find(m => m.id === 'gpt-image-2')) {
        this.state.selectedModels = ['gpt-image-2'];
      }
      this.renderModelChips();
      this.renderModelList();
      this.updateGenCalc();
    } catch (e) {
      this.toast('Ошибка загрузки моделей: ' + e.message, 'error');
    }
  },

  async loadFavorites() {
    try {
      const data = await API.getFavorites();
      this.state.favorites = data.favorites || [];
      this.renderModelList();
    } catch (e) { /* silent */ }
  },

  renderModelList(filter = '') {
    const list = document.getElementById('model-list');
    const favs = this.state.favorites;
    let models = this.state.models.filter(m =>
      !filter || m.name.toLowerCase().includes(filter.toLowerCase()) || m.id.toLowerCase().includes(filter.toLowerCase())
    );
    models.sort((a, b) => (favs.includes(a.id) ? 0 : 1) - (favs.includes(b.id) ? 0 : 1));

    list.innerHTML = models.map(m => {
      const checked = this.state.selectedModels.includes(m.id);
      const isFav = favs.includes(m.id);
      const canEdit = (m.modes || []).includes('edit');
      const maxRefs = m.max_i2i_images || 1;
      const multiRef = maxRefs > 1;
      const priceUsd = m.price && m.price.usd ? m.price.usd : '';
      const priceRub = m.price && m.price.rub ? m.price.rub : '';
      const priceLabel = priceUsd && priceRub ? `${priceUsd} (${priceRub})` : (priceRub || priceUsd || '');
      const refBadge = canEdit
        ? (multiRef
            ? `<span class="badge badge--green text-caption">до ${maxRefs} фото</span>`
            : `<span class="badge badge--blue text-caption">текст+фото</span>`)
        : `<span class="badge badge--blue text-caption">только текст</span>`;
      return `<div class="model-item" onclick="App.toggleModel('${m.id}')">
        <div class="model-item__checkbox ${checked ? 'checked' : ''}">${checked ? '✓' : ''}</div>
        <span class="model-item__name">${m.name}${priceLabel ? ` <span class="model-item__price text-muted text-caption">${this._escapeHtml(priceLabel)}</span>` : ''}</span>
        ${refBadge}
        <span class="model-item__star ${isFav ? 'active' : ''}" onclick="event.stopPropagation();App.toggleFav('${m.id}')">★</span>
      </div>`;
    }).join('');
  },

  filterModels(val) { this.renderModelList(val); },

  toggleModel(id) {
    const idx = this.state.selectedModels.indexOf(id);
    if (idx >= 0) this.state.selectedModels.splice(idx, 1);
    else this.state.selectedModels.push(id);
    this.renderModelList(document.getElementById('model-search').value);
    this.renderModelChips();
    this.updateGenCalc();
    this.updateGenBtn();
  },

  async toggleFav(id) {
    try {
      await API.toggleFavorite(id);
      const idx = this.state.favorites.indexOf(id);
      if (idx >= 0) this.state.favorites.splice(idx, 1);
      else this.state.favorites.push(id);
      this.renderModelList(document.getElementById('model-search').value);
    } catch (e) { /* silent */ }
  },

  renderModelChips() {
    const container = document.getElementById('model-chips');
    container.innerHTML = this.state.selectedModels.map(id => {
      const m = this.state.models.find(x => x.id === id);
      return `<span class="chip">${m ? m.name : id} <span class="chip__remove" onclick="App.toggleModel('${id}')">×</span></span>`;
    }).join('');
    const count = this.state.selectedModels.length;
    document.getElementById('models-label').textContent = count > 0 ? `Выбрано: ${count}` : 'Выбрать модели';
  },

  toggleModelPanel() {
    document.getElementById('model-panel').classList.toggle('open');
  },

  // ---- Variants ----
  stepVariants(delta) {
    this.state.variants = Math.max(1, Math.min(8, this.state.variants + delta));
    document.getElementById('variants-value').textContent = this.state.variants;
    this.updateGenCalc();
  },

  // ---- Aspect Ratio ----
  buildAspectMenu() {
    const ratios = [
      { value: 'auto', label: 'Авто', w: 20, h: 20 },
      { value: '1:1', label: '1:1', w: 18, h: 18 },
      { value: '4:5', label: '4:5', w: 16, h: 20 },
      { value: '3:4', label: '3:4', w: 15, h: 20 },
      { value: '5:4', label: '5:4', w: 20, h: 16 },
      { value: '4:3', label: '4:3', w: 20, h: 15 },
      { value: '9:16', label: '9:16', w: 12, h: 20 },
      { value: '16:9', label: '16:9', w: 20, h: 12 },
      { value: '21:9', label: '21:9', w: 20, h: 9 },
    ];
    const menu = document.getElementById('aspect-menu');
    menu.innerHTML = ratios.map(r => {
      const disabled = r.value === 'auto' && this.state.references.length === 0;
      const selected = this.state.aspectRatio === r.value;
      const ox = (24 - r.w) / 2, oy = (24 - r.h) / 2;
      return `<div class="aspect-option ${selected ? 'selected' : ''} ${disabled ? 'disabled' : ''}"
                   onclick="${disabled ? '' : `App.setAspect('${r.value}')`}">
        <svg class="aspect-icon" width="24" height="24" viewBox="0 0 24 24">
          <rect x="${ox}" y="${oy}" width="${r.w}" height="${r.h}" rx="2"/>
        </svg>
        <span>${r.label}${r.value === 'auto' && this.state.references.length > 0 ? this._autoRatioLabel() : ''}</span>
      </div>`;
    }).join('');
    this._updateAspectPreview();
  },

  _autoRatioLabel() {
    if (!this.state.references.length) return '';
    const ref = this.state.references[0];
    if (!ref.width || !ref.height) return '';
    const g = this._gcd(ref.width, ref.height);
    return ` (${ref.width / g}:${ref.height / g})`;
  },

  _gcd(a, b) { return b === 0 ? a : this._gcd(b, a % b); },

  _updateAspectPreview() {
    const map = { auto:[20,20], '1:1':[18,18], '4:5':[16,20], '3:4':[15,20], '5:4':[20,16], '4:3':[20,15], '9:16':[12,20], '16:9':[20,12], '21:9':[20,9] };
    const [w, h] = map[this.state.aspectRatio] || [18, 18];
    const ox = (24-w)/2, oy = (24-h)/2;
    document.getElementById('aspect-icon-preview').innerHTML =
      `<svg width="24" height="24" viewBox="0 0 24 24"><rect x="${ox}" y="${oy}" width="${w}" height="${h}" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
    let label = this.state.aspectRatio;
    if (label === 'auto') label = 'Авто' + this._autoRatioLabel();
    document.getElementById('aspect-text').textContent = label;
  },

  setAspect(value) {
    this.state.aspectRatio = value;
    this.buildAspectMenu();
    this.closeAllDropdowns();
  },

  // ---- Resolution / Format / Enhance ----
  setResolution(res) {
    this.state.resolution = res;
    document.querySelectorAll('#resolution-segmented .segmented__btn').forEach(b => b.classList.toggle('active', b.dataset.res === res));
  },

  setFormat(fmt) {
    this.state.format = fmt;
    document.querySelectorAll('#format-segmented .segmented__btn').forEach(b => b.classList.toggle('active', b.dataset.fmt === fmt));
  },

  toggleEnhance() {
    this.state.enhancePrompt = !this.state.enhancePrompt;
    document.getElementById('enhance-toggle').classList.toggle('active', this.state.enhancePrompt);
  },

  // ---- Reset form ----
  confirmReset() {
    const dialog = document.getElementById('reset-dialog');
    if (!dialog) return;
    dialog.classList.add('open');
    // Focus the "Да" button so Enter confirms
    setTimeout(() => {
      const yesBtn = document.getElementById('reset-yes');
      if (yesBtn) yesBtn.focus();
    }, 50);
  },

  closeResetDialog(event) {
    const dialog = document.getElementById('reset-dialog');
    if (!dialog) return;
    // Close only if clicking on overlay (not inside the box) or called programmatically
    if (event && event.target !== dialog) return;
    dialog.classList.remove('open');
  },

  resetForm() {
    // Close dialog first
    const dialog = document.getElementById('reset-dialog');
    if (dialog) dialog.classList.remove('open');

    // Reset state to defaults
    this.state.selectedModels = [];
    this.state.variants = 1;
    this.state.aspectRatio = '1:1';
    this.state.resolution = '1k';
    this.state.format = 'png';
    this.state.enhancePrompt = false;
    this.state.references = [];
    this.state.selectedStyles = [];
    this.state.activeTemplate = null;

    // Reset DOM elements
    document.getElementById('gen-prompt').value = '';
    document.getElementById('gen-prompt').style.height = 'auto';
    document.getElementById('gen-comment').value = '';
    document.getElementById('variants-value').textContent = '1';
    document.getElementById('model-search').value = '';

    // Reset template
    if (typeof this.resetTemplate === 'function') this.resetTemplate();

    // Reset styles checkboxes
    this._renderStyleCheckboxes();

    // Reset references
    this.renderRefThumbs();

    // Reset model selection — default to GPT Image 2 if available
    if (this.state.models.find(m => m.id === 'gpt-image-2')) {
      this.state.selectedModels = ['gpt-image-2'];
    }
    this.renderModelChips();
    this.renderModelList('');

    // Reset aspect ratio
    this.setAspect('1:1');

    // Reset resolution
    this.setResolution('1k');

    // Reset format
    this.setFormat('png');

    // Reset enhance toggle
    document.getElementById('enhance-toggle').classList.remove('active');

    // Update calculations and button state
    this.updateGenCalc();
    this.updateGenBtn();

    this.toast('Все параметры сброшены', 'info');
  },

  toggleCollapsible(name) {
    document.getElementById(`${name}-body`).classList.toggle('open');
  },

  toggleDropdown(id) {
    const menu = document.querySelector(`#${id} .dropdown__menu`);
    const wasOpen = menu.classList.contains('open');
    this.closeAllDropdowns();
    if (!wasOpen) menu.classList.add('open');
  },

  closeAllDropdowns() {
    document.querySelectorAll('.dropdown__menu.open').forEach(m => m.classList.remove('open'));
  },

  // ---- References ----
  handlePaste(e) {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    const imageFiles = [];
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const blob = item.getAsFile();
        if (blob) {
          // Convert Blob to File with a meaningful name
          const ext = blob.type.split('/')[1] || 'png';
          const file = new File([blob], `pasted-${Date.now()}.${ext}`, { type: blob.type });
          imageFiles.push(file);
        }
      }
    }
    if (imageFiles.length > 0) {
      e.preventDefault(); // Prevent pasting image data into text fields
      this._addReferences(imageFiles);
      this.toast(`Добавлено референсов: ${imageFiles.length}`, 'success');
    }
  },

  handleRefDrop(e) {
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
    this._addReferences(files);
  },

  handleRefFiles(fileList) {
    this._addReferences(Array.from(fileList));
    document.getElementById('ref-input').value = '';
  },

  _addReferences(files) {
    files.forEach(file => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        const img = new Image();
        img.onload = () => {
          this.state.references.push({ file, dataUrl: ev.target.result, width: img.naturalWidth, height: img.naturalHeight });
          this.renderRefThumbs();
          this.buildAspectMenu();
        };
        img.src = ev.target.result;
      };
      reader.readAsDataURL(file);
    });
  },

  removeRef(index) {
    this.state.references.splice(index, 1);
    this.renderRefThumbs();
    this.buildAspectMenu();
  },

  renderRefThumbs() {
    document.getElementById('ref-thumbs').innerHTML = this.state.references.map((ref, i) =>
      `<div class="ref-thumb"><img src="${ref.dataUrl}" alt="ref ${i+1}"><span class="ref-thumb__num">${i+1}</span><span class="ref-thumb__remove" onclick="App.removeRef(${i})">×</span></div>`
    ).join('');
  },

  // ---- Prompt helpers ----
  updateGenBtn() {
    const hasContent = (document.getElementById('gen-prompt').value || '').trim().length > 0;
    document.getElementById('gen-btn').disabled = !hasContent || this.state.selectedModels.length === 0;
  },

  updateGenCalc() {
    const m = this.state.selectedModels.length;
    const v = this.state.variants;
    const s = Math.max(1, this.state.selectedStyles.length);
    const t = m * v * s;
    const el = document.getElementById('gen-calc');
    if (m > 0) {
      let text = `${m} ${this._plural(m,'модель','модели','моделей')} × ${v} ${this._plural(v,'вариант','варианта','вариантов')} × ${s} ${this._plural(s,'стиль','стиля','стилей')} = ${t} ${this._plural(t,'изображение','изображения','изображений')}`;
      if (t > 10) text += ' ⚠️';
      el.textContent = text;
    } else { el.textContent = ''; }
    this.updateGenBtn();
  },

  _plural(n, one, few, many) {
    const m10 = n%10, m100 = n%100;
    if (m100 >= 11 && m100 <= 14) return many;
    if (m10 === 1) return one;
    if (m10 >= 2 && m10 <= 4) return few;
    return many;
  },

  _escapeHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },

  _aspectToCSS(r) {
    const map = {'1:1':'1','4:5':'4/5','3:4':'3/4','5:4':'5/4','4:3':'4/3','9:16':'9/16','16:9':'16/9','21:9':'21/9'};
    return map[r] || '1';
  },

  // ---- Generate action ----
  async generate() {
    const basePrompt = (document.getElementById('gen-prompt').value || '').trim();
    if (!basePrompt || this.state.selectedModels.length === 0) return;

    // Warn if multiple references are attached but selected models only support one image.
    if (this.state.references.length > 1) {
      const limitedModels = this.state.selectedModels.filter(id => {
        const m = this.state.models.find(x => x.id === id);
        return m && (m.max_i2i_images || 1) < this.state.references.length;
      });
      if (limitedModels.length > 0) {
        const names = limitedModels.map(id => {
          const m = this.state.models.find(x => x.id === id);
          return m ? m.name : id;
        }).join(', ');
        const proceed = confirm(
          '⚠️ Вы прикрепили ' + this.state.references.length + ' изображений, а модели ' + names + ' принимают только 1 входное фото.\n\n' +
          'Для них все прикреплённые изображения будут автоматически объединены в один лист с подписями «Изображение 1», «Изображение 2» и т.д., чтобы модель понимала, на что вы ссылаетесь в промпте.\n\n' +
          'Модели с поддержкой нескольких фото (например, Qwen Image 3 Pro) получат их как есть.\n\n' +
          'Продолжить?'
        );
        if (!proceed) return;
      }
    }

    let aspectRatio = this.state.aspectRatio;
    if (aspectRatio === 'auto' && this.state.references.length > 0) {
      const ref = this.state.references[0];
      if (ref.width && ref.height) { const g=this._gcd(ref.width,ref.height); aspectRatio=`${ref.width/g}:${ref.height/g}`; }
      else aspectRatio='1:1';
    } else if (aspectRatio==='auto') aspectRatio='1:1';

    // Determine style templates to apply
    const styles = this.getSelectedStyleTemplates();
    const prompts = [];
    const styleNames = [];
    if (styles.length === 0) {
      prompts.push(basePrompt);
      styleNames.push(null);
    } else {
      for (const st of styles) {
        const styled = (st.prompt_template || '').replace('{content}', basePrompt);
        prompts.push(styled);
        styleNames.push(st.name);
      }
    }

    const comment = document.getElementById('gen-comment').value.trim()||null;
    const refs = this.state.references.map(r=>r.dataUrl);

    // Create one generation per style
    for (let si = 0; si < prompts.length; si++) {
      const prompt = prompts[si];
      const sName = styleNames[si];
      const params = { prompt, models:this.state.selectedModels, variants:this.state.variants,
        aspect_ratio:aspectRatio, resolution:this.state.resolution, format:this.state.format,
        enhance_prompt:this.state.enhancePrompt, comment, references:refs,
        style_name:sName };

      const genId='gen_'+Date.now()+'_'+si, totalCards=params.models.length*params.variants;
      this._createFeedBlock(genId,params,totalCards,sName);
      this.state.generations.push({id:genId, params, cards: new Array(totalCards).fill(null)});
      const emptyEl=document.getElementById('feed-empty'); if(emptyEl)emptyEl.style.display='none';
    }

    const btnText=document.getElementById('gen-btn-text');
    document.getElementById('gen-btn').disabled=true;
    const totalAll = prompts.length * this.state.selectedModels.length * this.state.variants;
    btnText.textContent=`Генерация... 0 из ${totalAll}`;

    try {
      // Send all prompts as batch (or sequentially)
      for (let si = 0; si < prompts.length; si++) {
        const params = { prompt:prompts[si], models:this.state.selectedModels, variants:this.state.variants,
          aspect_ratio:aspectRatio, resolution:this.state.resolution, format:this.state.format,
          enhance_prompt:this.state.enhancePrompt, comment, references:refs,
          style_name:styleNames[si] };
        const genId='gen_'+Date.now()+'_'+si;
        // Find the matching block
        const block = this.state.generations.find(g => g.params.style_name === styleNames[si] && g.params.prompt === prompts[si]);
        const localGenId = block ? block.id : genId;
        const result = await API.generate(params);
        this._startPolling(localGenId, result.generation_id, params.models.length * params.variants);
      }
    } catch(e) {
      this.toast('Ошибка запуска: '+e.message,'error');
      document.getElementById('gen-btn').disabled=false; btnText.textContent='Сгенерировать';
    }
  },

  _createFeedBlock(genId, params, totalCards, styleName) {
    const feed = document.getElementById('gen-feed');
    const now = new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
    const modelNames = params.models.map(id=>{const m=this.state.models.find(x=>x.id===id);return m?m.name:id;});
    const block = document.createElement('div');
    block.className='gen-block'; block.id=`block-${genId}`;
    const styleLabel = styleName ? ` · 🎨 ${this._escapeHtml(styleName)}` : '';
    block.innerHTML=`
      <div class="gen-block__header"><span>${now}</span>
        <span>${modelNames.length} ${this._plural(modelNames.length,'модель','модели','моделей')} × ${params.variants} ${this._plural(params.variants,'вариант','варианта','вариантов')}${styleLabel}</span>
        <span class="badge badge--blue">${params.aspect_ratio}</span>
        ${params.comment?`<span class="badge badge--green">${params.comment}</span>`:''}
      </div>
      <div class="gen-block__grid" id="grid-${genId}">
        ${Array.from({length:totalCards},(_,i)=>{
          const mi=Math.floor(i/params.variants), mn=modelNames[mi]||params.models[mi];
          return `<div class="result-card" id="card-${genId}-${i}">
            <div class="result-card__preview skeleton" style="aspect-ratio:${this._aspectToCSS(params.aspect_ratio)}"></div>
            <div class="result-card__badge">${mn}</div>
            <div class="result-card__status"><div class="spinner"></div><span>Генерация...</span></div>
          </div>`;
        }).join('')}
      </div>
      <div class="gen-block__prompt collapsed" id="prompt-${genId}">${this._escapeHtml(params.prompt)}
        <div style="margin-top:var(--space-2);display:flex;gap:var(--space-2)">
          <button class="btn btn--ghost text-caption" onclick="App.copyText(App.state.generations.find(g=>g.id==='${genId}').params.prompt);App.toast('Промт скопирован','success')">Копировать промт</button>
        </div>
      </div>
      ${params.references.length?`<div class="gen-block__refs">${params.references.map((r,i)=>`<img src="${r}" alt="ref" onclick="App.openLightbox(['${r}'],0)">`).join('')}</div>`:''}
    `;
    feed.appendChild(block);
    block.scrollIntoView({behavior:'smooth'});
  },

  _finalizeCard(localId, i, card) {
    const el=document.getElementById(`card-${localId}-${i}`); if(!el||el.dataset.final)return;
    el.dataset.final='1';
    el.querySelector('.result-card__preview').classList.remove('skeleton');
    const st=el.querySelector('.result-card__status');if(st)st.remove();
    const a=document.createElement('div');a.className='result-card__actions';
    if(card.status==='done'){
      el.querySelector('.result-card__preview').innerHTML=`<img src="${API.imageUrl(card.image_id)}" alt="result" onclick="App.openLightboxFromBlock('${localId}',${i})">`;
      a.innerHTML=`<button class="btn btn--ghost btn--icon" title="Скачать" onclick="App.downloadImage('${card.image_id}','${card.model}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></button>
        <button class="btn btn--ghost btn--icon" title="Копировать промт" onclick="App.copyText(App.state.generations.find(g=>g.id==='${localId}').params.prompt);App.toast('Промт скопирован','success')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
        <button class="btn btn--ghost btn--icon" title="Перегенерировать" onclick="App.regenerateFromCard('${localId}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></button>
        <button class="btn btn--ghost btn--icon" title="Вариации" onclick="App.showVariationForm('${localId}',${i},this)">✨</button>`;
    } else {
      el.querySelector('.result-card__preview').innerHTML=`<div style="padding:var(--space-3);text-align:center;color:var(--accent-red);font-size:0.786rem">${this._escapeHtml(card.error||'Ошибка')}</div>`;
      a.innerHTML=`<button class="btn btn--danger text-caption" onclick="App.retryCard('${localId}',${i})">Повторить</button>`;
    }
    el.appendChild(a);
  },

  async restoreFeed() {
    try {
      const d = await API.getHistory();
      const items = (d.items||[]).slice(0,8).reverse();
      for (const item of items) this._rebuildFeedBlock(item);
      if (items.length) {
        const emptyEl=document.getElementById('feed-empty'); if(emptyEl) emptyEl.style.display='none';
      }
    } catch(e){}
  },

  _rebuildFeedBlock(item) {
    if (document.getElementById(`block-${item.id}`)) return;
    if (!this.state.generations.find(g=>g.id===item.id)) {
      this.state.generations.push({id:item.id, params:item.params, cards:[...(cards||[])]});
    }
    const params=item.params, cards=item.cards||[];
    const feed=document.getElementById('gen-feed');
    const now=new Date(item.created_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
    const modelNames=params.models.map(id=>{const m=this.state.models.find(x=>x.id===id);return m?m.name:id;});
    const block=document.createElement('div');
    block.className='gen-block'; block.id=`block-${item.id}`;
    block.innerHTML=`
      <div class="gen-block__header"><span>${now}</span>
        <span>${modelNames.length} ${this._plural(modelNames.length,'модель','модели','моделей')} × ${params.variants} ${this._plural(params.variants,'вариант','варианта','вариантов')}</span>
        <span class="badge badge--blue">${params.aspect_ratio}</span>
        ${params.comment?`<span class="badge badge--green">${params.comment}</span>`:''}
      </div>
      <div class="gen-block__grid" id="grid-${item.id}">
        ${cards.map((c,i)=>{
          const mi=Math.floor(i/params.variants), mn=modelNames[mi]||params.models[mi];
          return `<div class="result-card" id="card-${item.id}-${i}">
            <div class="result-card__preview skeleton" style="aspect-ratio:${this._aspectToCSS(params.aspect_ratio)}"></div>
            <div class="result-card__badge">${mn}</div>
            <div class="result-card__status"><div class="spinner"></div><span>Генерация...</span></div>
          </div>`;
        }).join('')}
      </div>
      <div class="gen-block__prompt collapsed" id="prompt-${item.id}">${this._escapeHtml(params.prompt)}
        <div style="margin-top:var(--space-2);display:flex;gap:var(--space-2)">
          <button class="btn btn--ghost text-caption" onclick="App.copyText(App.state.generations.find(g=>g.id==='${item.id}').params.prompt);App.toast('Промт скопирован','success')">Копировать промт</button>
        </div>
      </div>
      ${(params.references||[]).length?`<div class="gen-block__refs">${params.references.map(r=>`<img src="${r}" alt="ref" onclick="App.openLightbox(['${r}'],0)">`).join('')}</div>`:''}
    `;
    feed.appendChild(block);
    cards.forEach((c,i)=>{ if(c.status==='done'||c.status==='error') this._finalizeCard(item.id,i,c); });
    if (item.status==='generating') this._startPolling(item.id, item.id, cards.length);
  },

  _startPolling(localId, serverGenId, totalCards) {
    const btnText=document.getElementById('gen-btn-text');
    const timer=setInterval(async()=>{
      try {
        const status=await API.getGenerationStatus(serverGenId);
        let completed=0;
        status.cards.forEach((card,i)=>{
          if(card.status==='done'||card.status==='error'){
            completed++;
            this._finalizeCard(localId,i,card);
            // Update state
            const gen = this.state.generations.find(g=>g.id===localId);
            if(gen && gen.cards) gen.cards[i] = card;
          }
        });
        btnText.textContent=`Генерация... ${completed} из ${totalCards}`;
        if(completed>=totalCards){
          clearInterval(timer);delete this.state.pollingTimers[localId];
          btnText.textContent='Сгенерировать';document.getElementById('gen-btn').disabled=false;
          this.toast('Генерация завершена','success');
        }
      }catch(e){}
    },2000);
    this.state.pollingTimers[localId]=timer;
  },

  // ---- Lightbox ----
  openLightbox(images, index) {
    this.state.lightboxImages = images;
    this.state.lightboxIndex = index;
    document.getElementById('lightbox-img').src = images[index];
    const dl = document.getElementById('lightbox-download');
    dl.href = images[index]; dl.download = `image_${index+1}.png`;
    document.getElementById('lightbox').classList.add('open');
  },

  openLightboxFromBlock(genId, cardIndex) {
    const block = document.getElementById(`block-${genId}`); if(!block)return;
    const imgs = Array.from(block.querySelectorAll('.result-card__preview img')).map(img=>img.src);
    if(imgs.length===0)return;
    this.openLightbox(imgs, cardIndex<imgs.length?cardIndex:0);
  },

  closeLightbox(e) {
    if(e && e.target!==document.getElementById('lightbox'))return;
    document.getElementById('lightbox').classList.remove('open');
  },

  lightboxNav(dir) {
    const imgs=this.state.lightboxImages; if(imgs.length<=1)return;
    let idx=this.state.lightboxIndex+dir;
    if(idx<0)idx=imgs.length-1; if(idx>=imgs.length)idx=0;
    this.state.lightboxIndex=idx;
    document.getElementById('lightbox-img').src=imgs[idx];
    document.getElementById('lightbox-download').href=imgs[idx];
  },

  // ---- Download ----
  async downloadImage(imageId, modelName) {
    try {
      const resp=await fetch(API.imageUrl(imageId));
      const blob=await resp.blob();
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=url; a.download=`${new Date().toISOString().slice(0,10)}_${modelName.replace(/\s+/g,'-').toLowerCase()}_v1.png`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    } catch(e){this.toast('Ошибка скачивания','error');}
  },

  copyText(text) {
    navigator.clipboard.writeText(text).catch(()=>{
      const ta=document.createElement('textarea');ta.value=text;
      document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);
    });
  },

  regenerateFromCard(genId) {
    const gen=this.state.generations.find(g=>g.id===genId); if(!gen)return;
    this._fillFormFromParams(gen.params);
    this.navigate('generate');
    this.toast('Параметры загружены в форму','info');
  },

  async retryCard(genId, cardIndex) {
    const gen = this.state.generations.find(g => g.id === genId);
    if (!gen) return;
    const params = gen.params;
    const model = params.models[cardIndex % params.models.length] || params.models[0];
    // Find the actual card index in the full cards array
    // cards are ordered: model0_v0, model0_v1, ..., model1_v0, ...
    // cardIndex is the flat index
    const variantIdx = cardIndex % params.variants;
    const modelIdx = Math.floor(cardIndex / params.variants);
    const actualModel = params.models[modelIdx] || params.models[0];

    const el = document.getElementById(`card-${genId}-${cardIndex}`);
    if (el) {
      // Show loading state
      const preview = el.querySelector('.result-card__preview');
      if (preview) {
        preview.innerHTML = '<div class="skeleton" style="width:100%;height:100%;border-radius:var(--radius-md)"></div>';
      }
      const actions = el.querySelector('.result-card__actions');
      if (actions) actions.remove();
    }

    try {
      const result = await API.retrySingle({
        prompt: params.prompt,
        model: actualModel,
        aspect_ratio: params.aspect_ratio,
        resolution: params.resolution,
        format: params.format,
        references: params.references || [],
      });

      if (result.image_id) {
        // Update the generation data
        if (gen.cards && gen.cards[cardIndex]) {
          gen.cards[cardIndex].status = 'done';
          gen.cards[cardIndex].image_id = result.image_id;
          gen.cards[cardIndex].error = null;
        }
        // Re-render the card
        if (el) {
          el.dataset.final = '';
          this._finalizeCard(genId, cardIndex, { status: 'done', image_id: result.image_id, model: actualModel });
        }
        this.toast('Генерация завершена', 'success');
      } else {
        throw new Error(result.error || 'Ошибка генерации');
      }
    } catch (e) {
      if (el) {
        el.dataset.final = '';
        this._finalizeCard(genId, cardIndex, { status: 'error', error: e.message, model: actualModel });
      }
      this.toast('Ошибка: ' + e.message, 'error');
    }
  },

  showVariationForm(genId, cardIndex, btn) {
    const gen = this.state.generations.find(g => g.id === genId);
    if (!gen) return;
    const card = gen.cards[cardIndex];
    if (!card || card.status !== 'done') return;

    // Check if form already open
    const cardEl = btn.closest('.result-card');
    const existing = cardEl.querySelector('.variation-form');
    if (existing) { existing.remove(); return; }

    const form = document.createElement('div');
    form.className = 'variation-form';
    form.innerHTML = `
      <input class="input variation-form__input" type="text" placeholder="Что изменить? (напр. другой фон, ярче цвета...)" autofocus>
      <div class="variation-form__actions">
        <button class="btn btn--primary text-caption" onclick="App.runVariation('${genId}',${cardIndex},this)">Создать</button>
        <button class="btn btn--ghost text-caption" onclick="this.closest('.variation-form').remove()">Отмена</button>
      </div>
    `;
    cardEl.appendChild(form);
    form.querySelector('.variation-form__input').focus();
    form.querySelector('.variation-form__input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') App.runVariation(genId, cardIndex, form.querySelector('.btn--primary'));
    });
  },

  async runVariation(genId, cardIndex, btn) {
    const gen = this.state.generations.find(g => g.id === genId);
    if (!gen) return;
    const card = gen.cards[cardIndex];
    if (!card || card.status !== 'done') return;

    const form = btn.closest('.variation-form');
    const instruction = form.querySelector('.variation-form__input').value.trim();
    if (!instruction) { this.toast('Введите инструкцию','error'); return; }

    // Get the reference image URL
    const refImageUrl = API.imageUrl(card.image_id);

    // Build edit prompt
    const editPrompt = `${gen.params.prompt}\n\nИзменение: ${instruction}`;

    // Create new generation with reference image
    const params = {
      prompt: editPrompt,
      models: [card.model],
      variants: 1,
      aspect_ratio: gen.params.aspect_ratio || '1:1',
      resolution: gen.params.resolution || '1k',
      format: gen.params.format || 'png',
      enhance_prompt: false,
      comment: `Вариация: ${instruction}`,
      references: [refImageUrl],
      style_name: gen.style_name || null,
    };

    const newGenId = 'gen_' + Date.now();
    this._createFeedBlock(newGenId, params, 1, gen.style_name || null);
    this.state.generations.push({id:newGenId, params, cards:[null]});

    form.remove();

    try {
      const result = await API.generate(params);
      this._startPolling(newGenId, result.generation_id, 1);
    } catch(e) {
      this.toast('Ошибка вариации: '+e.message,'error');
    }
  },

  _fillFormFromParams(params) {
    document.getElementById('gen-prompt').value = params.prompt || '';
    document.getElementById('gen-comment').value=params.comment||'';
    this.state.selectedModels=[...(params.models||[])];
    this.state.variants=params.variants||1;
    this.state.aspectRatio=params.aspect_ratio||'1:1';
    this.state.resolution=params.resolution||'1k';
    this.state.format=params.format||'png';
    this.state.enhancePrompt=params.enhance_prompt||false;
    this.state.references=(params.references||[]).map(r=>({file:null,dataUrl:r,width:0,height:0}));
    this.renderRefThumbs();
    this.renderModelChips();
    this.renderModelList(document.getElementById('model-search').value);
    document.getElementById('variants-value').textContent=this.state.variants;
    this.buildAspectMenu();
    this.setResolution(this.state.resolution);
    this.setFormat(this.state.format);
    document.getElementById('enhance-toggle').classList.toggle('active',this.state.enhancePrompt);
    this.updateGenCalc();
  },

  // ---- Toast ----
  toast(msg, type='info') {
    const c=document.getElementById('toast-container');
    const el=document.createElement('div');
    el.className=`toast toast--${type}`; el.textContent=msg;
    c.appendChild(el);
    setTimeout(()=>{el.style.opacity='0';setTimeout(()=>el.remove(),300);},3000);
  },

  // ---- History ----
  async loadHistory() {
    const list=document.getElementById('history-list');
    list.innerHTML='<div class="text-muted text-center" style="padding:var(--space-8)">Загрузка...</div>';
    try {
      const d=await API.getHistory();
      this._renderHistoryList(d.items||[]);
    } catch(e){
      list.innerHTML='<div class="text-muted text-center" style="padding:var(--space-8)">Ошибка загрузки истории</div>';
    }
  },

  filterHistory() {
    const s=document.getElementById('history-search').value.toLowerCase();
    document.querySelectorAll('.history-item').forEach(i=>{
      i.style.display=(i.dataset.prompt||'').toLowerCase().includes(s)?'':'none';
    });
  },

  _renderHistoryList(items) {
    this.state.historyItems = items;
    const list=document.getElementById('history-list');
    if(!items.length){list.innerHTML='<div class="text-muted text-center" style="padding:var(--space-8)">История пуста</div>';return;}
    list.innerHTML=items.map(item=>{
      const cards=item.cards||[];
      const tiles=cards.map((c,i)=>{
        if(c.status==='done') return `<div class="history-item__tile"><img src="${API.imageUrl(c.image_id)}" alt="" loading="lazy" onclick="event.stopPropagation();App.openLightboxFromHistory('${item.id}',${i})"></div>`;
        if(c.status==='error') return `<div class="history-item__tile history-item__tile--status"><span class="text-caption" style="color:var(--accent-red)">Ошибка</span></div>`;
        return `<div class="history-item__tile history-item__tile--status"><div class="spinner"></div><span class="text-caption">Генерация...</span></div>`;
      }).join('');
      const statusBadge = item.status==='generating' ? '<span class="badge badge--blue">генерация</span>' : (item.status==='error' ? '<span class="badge badge--red">ошибка</span>' : '');
      return `<div class="history-item" data-prompt="${this._escapeHtml(item.prompt)}" data-id="${item.id}">
        <div class="history-item__grid">${tiles}</div>
        <div class="history-item__info">
          <div class="history-item__prompt">${this._escapeHtml(item.prompt)}</div>
          <div class="history-item__meta">
            <span>${new Date(item.created_at).toLocaleDateString('ru-RU')}</span>
            <span>${item.models_count} ${this._plural(item.models_count,'модель','модели','моделей')}</span>
            ${statusBadge}
            ${item.comment?`<span class="badge badge--green">${this._escapeHtml(item.comment)}</span>`:''}
          </div>
        </div>
        <div class="history-item__actions">
          <button class="btn btn--ghost text-caption" onclick="event.stopPropagation();App.copyHistoryPrompt('${item.id}')">Копировать промт</button>
          <button class="btn btn--secondary text-caption" onclick="event.stopPropagation();App.regenerateFromHistory('${item.id}')">Перегенерировать</button>
          <button class="btn btn--danger text-caption" onclick="event.stopPropagation();App.deleteHistoryItem('${item.id}')">Удалить</button>
        </div>
      </div>`;
    }).join('');
  },

  copyHistoryPrompt(id){
    const it=(this.state.historyItems||[]).find(x=>x.id===id);
    if(it){this.copyText(it.prompt);this.toast('Промт скопирован','success');}
  },

  openLightboxFromHistory(id, cardIndex){
    const it=(this.state.historyItems||[]).find(x=>x.id===id); if(!it)return;
    const cards=it.cards||[];
    const before=cards.slice(0,cardIndex).filter(c=>c.status==='done').length;
    const imgs=cards.filter(c=>c.status==='done').map(c=>API.imageUrl(c.image_id));
    if(imgs.length) this.openLightbox(imgs, Math.min(before, imgs.length-1));
  },

  regenerateFromHistory(id) {
    const it=(this.state.historyItems||[]).find(x=>x.id===id);
    if(!it||!it.params)return;
    this._fillFormFromParams(it.params);
    this.navigate('generate');
    this.toast('Параметры загружены из истории','info');
  },

  async deleteHistoryItem(id) {
    if(!confirm('Удалить запись истории?'))return;
    try{await API.deleteHistory(id);await this.loadHistory();this.toast('Запись удалена','success');}
    catch(e){this.toast('Ошибка удаления','error');}
  },

  // ---- Templates ----
  async loadTemplates() {
    try{
      const d=await API.getTemplates();
      const all=d.templates||[];
      this.state.templates=all.filter(t=>t.type!=='style');
      this.state.styleTemplates=all.filter(t=>t.type==='style');
      this._renderTemplateDropdown();
      this._renderStyleCheckboxes();
    }catch(e){}
  },

  _renderTemplateDropdown() {
    document.getElementById('template-menu').innerHTML=this.state.templates.map(t=>`<div class="dropdown__item" onclick="App.applyTemplate(${t.id})">${t.name}</div>`).join('');
  },

  _renderStyleCheckboxes() {
    const container = document.getElementById('style-checkboxes');
    if (!container) return;
    if (!this.state.styleTemplates.length) {
      container.innerHTML = '<span class="text-caption text-muted">Нет доступных стилей</span>';
      return;
    }
    container.innerHTML = this.state.styleTemplates.map(t => {
      const checked = this.state.selectedStyles.includes(t.id);
      const icon = t.icon ? `<span class="style-chip__icon">${t.icon}</span>` : '';
      return `<label class="style-chip ${checked ? 'active' : ''}" data-style-id="${t.id}" title="${this._escapeHtml(t.description || '')}">
        <input type="checkbox" ${checked ? 'checked' : ''} onchange="App.toggleStyle(${t.id}, this)">
        ${icon}<span>${this._escapeHtml(t.name)}</span>
      </label>`;
    }).join('');
    this._updateStyleCountLabel();
  },

  toggleStyle(id, checkboxEl) {
    const idx = this.state.selectedStyles.indexOf(id);
    const label = checkboxEl ? checkboxEl.closest('.style-chip') : null;
    if (idx >= 0) {
      this.state.selectedStyles.splice(idx, 1);
      if (label) label.classList.remove('active');
    } else {
      this.state.selectedStyles.push(id);
      if (label) label.classList.add('active');
    }
    this._updateStyleCountLabel();
    this.updateGenCalc();
  },

  _updateStyleCountLabel() {
    const label = document.getElementById('style-count-label');
    if (!label) return;
    const n = this.state.selectedStyles.length;
    label.textContent = n > 0 ? `${n} выбрано` : '';
  },

  getSelectedStyleTemplates() {
    return this.state.selectedStyles
      .map(id => this.state.styleTemplates.find(t => t.id === id))
      .filter(Boolean);
  },

  renderTemplates() {
    // Render prompt templates (non-style)
    const promptTemplates = this.state.templates.filter(t => t.type !== 'style');
    const g = document.getElementById('templates-grid');
    if (!promptTemplates.length) {
      g.innerHTML = '<div class="text-muted text-center" style="padding:var(--space-8);grid-column:1/-1">Шаблонов пока нет</div>';
    } else {
      g.innerHTML = promptTemplates.map(t => `<div class="template-card">
        <div class="template-card__icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg></div>
        <div class="template-card__name">${this._escapeHtml(t.name)}</div>
        <div class="template-card__category">${this._escapeHtml(t.category||'')}</div>
        <div class="template-card__desc">${this._escapeHtml(t.description||'')}</div>
        <div class="template-card__actions">
          <button class="btn btn--secondary text-caption" onclick="App.applyTemplate(${t.id})">Использовать</button>
          <button class="btn btn--ghost text-caption" onclick="App.duplicateTemplate(${t.id})">Дублировать</button>
          <button class="btn btn--ghost text-caption" onclick="App.deleteTemplate(${t.id})">Удалить</button>
        </div></div>`).join('');
    }
    this._renderStylesGrid();
  },

  _renderStylesGrid() {
    const styles = this.state.styleTemplates;
    const container = document.getElementById('styles-grid');
    if (!container) return;
    if (!styles.length) {
      container.innerHTML = '<div class="text-muted text-center" style="padding:var(--space-8);grid-column:1/-1">Стилей пока нет</div>';
      return;
    }
    container.innerHTML = styles.map(t => `<div class="style-card" id="style-card-${t.id}">
      <div class="style-card__header">
        <span class="style-card__icon">${t.icon || '🎨'}</span>
        <span class="style-card__name">${this._escapeHtml(t.name)}</span>
      </div>
      <div class="style-card__prompt">${this._escapeHtml(t.prompt_template || '')}</div>
      <div class="style-card__actions">
        <button class="btn btn--secondary text-caption" onclick="App.editStyle(${t.id})">Редактировать</button>
        <button class="btn btn--ghost text-caption" onclick="App.deleteStyle(${t.id})">Удалить</button>
      </div>
    </div>`).join('');
  },

  applyTemplate(id) {
    const t=this.state.templates.find(x=>x.id===id);if(!t)return;
    this.state.activeTemplate=t;
    document.getElementById('template-label').textContent=t.name;
    document.getElementById('template-reset').classList.remove('hidden');
    document.getElementById('gen-prompt').value=t.prompt_template||t.prompt_skeleton||t.prompt||'';
    const vc=document.getElementById('template-vars');
    if(t.variables&&t.variables.length>0){vc.classList.remove('hidden');vc.innerHTML=t.variables.map(v=>`<div class="input-group"><label class="input-label">${this._escapeHtml(v.label||v.name)}</label><input class="input template-var-input" data-var="${v.name}" placeholder="${this._escapeHtml(v.example||'')}"></div>`).join('');}else vc.classList.add('hidden');
    if(t.recommended_models){this.state.selectedModels=t.recommended_models.filter(m=>this.state.models.find(x=>x.id===m));this.renderModelChips();this.renderModelList(document.getElementById('model-search').value);}
    if(t.aspect_ratio)this.setAspect(t.aspect_ratio);
    if(t.resolution)this.setResolution(t.resolution);
    this.updateGenCalc();this.closeAllDropdowns();this.navigate('generate');
  },

  resetTemplate() {
    this.state.activeTemplate=null;document.getElementById('template-label').textContent='Без шаблона';
    document.getElementById('template-reset').classList.add('hidden');
    document.getElementById('template-vars').classList.add('hidden');document.getElementById('template-vars').innerHTML='';
  },

  async duplicateTemplate(id) {try{await API.duplicateTemplate(id);await this.loadTemplates();this.renderTemplates();this.toast('Шаблон дублирован','success');}catch(e){this.toast('Ошибка','error');}},

  async deleteTemplate(id) {if(!confirm('Удалить шаблон?'))return;try{await API.deleteTemplate(id);await this.loadTemplates();this.renderTemplates();this.toast('Шаблон удалён','success');}catch(e){this.toast('Ошибка','error');}},

  // ---- Style CRUD ----
  createStyle() {
    const container = document.getElementById('styles-grid');
    const formId = 'style-new-form';
    if (document.getElementById(formId)) return;
    const div = document.createElement('div');
    div.className = 'style-card'; div.id = formId;
    div.innerHTML = `<div class="style-edit-form">
      <div class="style-edit-form__row">
        <input class="input style-edit-form__icon-input" id="${formId}-icon" placeholder="🎨" maxlength="4">
        <input class="input" id="${formId}-name" placeholder="Название стиля">
      </div>
      <textarea class="input" id="${formId}-prompt" placeholder="Шаблон промта с {content}..." rows="4"></textarea>
      <div class="style-edit-form__actions">
        <button class="btn btn--ghost text-caption" onclick="document.getElementById('${formId}').remove()">Отмена</button>
        <button class="btn btn--primary text-caption" onclick="App.saveNewStyle('${formId}')">Сохранить</button>
      </div></div>`;
    container.prepend(div);
    div.querySelector(`#${formId}-name`).focus();
  },

  async saveNewStyle(formId) {
    const icon = document.getElementById(`${formId}-icon`).value.trim() || '🎨';
    const name = document.getElementById(`${formId}-name`).value.trim();
    const prompt = document.getElementById(`${formId}-prompt`).value.trim();
    if (!name || !prompt) { this.toast('Заполните название и шаблон', 'error'); return; }
    try {
      await API.createTemplate({ name, icon, category: 'Стиль', description: '', prompt_template: prompt, type: 'style' });
      await this.loadTemplates(); this.renderTemplates(); this._renderStyleCheckboxes();
      this.toast('Стиль создан', 'success');
    } catch(e) { this.toast('Ошибка: '+e.message, 'error'); }
  },

  editStyle(id) {
    const t = this.state.styleTemplates.find(s => s.id === id);
    if (!t) return;
    const card = document.getElementById(`style-card-${id}`);
    if (!card) return;
    const fid = `style-edit-${id}`;
    card.innerHTML = `<div class="style-edit-form" id="${fid}">
      <div class="style-edit-form__row">
        <input class="input style-edit-form__icon-input" id="${fid}-icon" value="${this._escapeHtml(t.icon||'')}" maxlength="4">
        <input class="input" id="${fid}-name" value="${this._escapeHtml(t.name)}">
      </div>
      <textarea class="input" id="${fid}-prompt" rows="4">${this._escapeHtml(t.prompt_template||'')}</textarea>
      <div class="style-edit-form__actions">
        <button class="btn btn--ghost text-caption" onclick="App._renderStylesGrid()">Отмена</button>
        <button class="btn btn--primary text-caption" onclick="App.saveEditStyle(${id},'${fid}')">Сохранить</button>
      </div></div>`;
    card.querySelector(`#${fid}-name`).focus();
  },

  async saveEditStyle(id, fid) {
    const icon = document.getElementById(`${fid}-icon`).value.trim() || '🎨';
    const name = document.getElementById(`${fid}-name`).value.trim();
    const prompt = document.getElementById(`${fid}-prompt`).value.trim();
    if (!name || !prompt) { this.toast('Заполните название и шаблон', 'error'); return; }
    try {
      await API.updateTemplate(id, { name, icon, category: 'Стиль', description: '', prompt_template: prompt, type: 'style' });
      await this.loadTemplates(); this.renderTemplates(); this._renderStyleCheckboxes();
      this.toast('Стиль обновлён', 'success');
    } catch(e) { this.toast('Ошибка: '+e.message, 'error'); }
  },

  async deleteStyle(id) {
    if (!confirm('Удалить этот стиль?')) return;
    try {
      await API.deleteTemplate(id);
      this.state.selectedStyles = this.state.selectedStyles.filter(sid => sid !== id);
      await this.loadTemplates(); this.renderTemplates(); this._renderStyleCheckboxes();
      this.updateGenCalc();
      this.toast('Стиль удалён', 'success');
    } catch(e) { this.toast('Ошибка', 'error'); }
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());