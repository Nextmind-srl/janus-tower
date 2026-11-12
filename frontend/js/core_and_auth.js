    let globalScanData = null;
    let currentTab = 'dashboard';

    function escapeHtml(val) {
      if (val === null || val === undefined) return '';
      return String(val)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }
    window.escapeHtml = escapeHtml;

    // Argomento stringa sicuro per gli attributi data-jt-click/change/input/keydown: letterale JSON, poi escape HTML
    function jsArg(val) {
      return escapeHtml(JSON.stringify(val === null || val === undefined ? '' : String(val)));
    }
    window.jsArg = jsArg;

    function _getCssToken(name, fallback) {
      try {
        const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return val || fallback;
      } catch (_e) {
        return fallback;
      }
    }
    const JT_COLORS = {
      get navy() { return _getCssToken('--jt-navy', '#0F2A4A'); },
      get navy800() { return _getCssToken('--jt-navy-800', '#0B2140'); },
      get navy700() { return _getCssToken('--jt-navy-700', '#1F4470'); },
      get navy600() { return _getCssToken('--jt-navy-600', '#2E5A8C'); },
      get amber() { return _getCssToken('--jt-amber', '#F2B544'); },
      get amber700() { return _getCssToken('--jt-amber-700', '#B07A12'); },
      get info() { return _getCssToken('--jt-info', '#2E5A8C'); },
      get success() { return _getCssToken('--jt-success', '#22A55B'); },
      get warning() { return _getCssToken('--jt-warning', '#B07A12'); },
      get danger() { return _getCssToken('--jt-danger', '#C2362B'); },
      get text() { return _getCssToken('--jt-text', '#0F2A4A'); },
      get text2() { return _getCssToken('--jt-text-2', '#3A4B60'); },
      get text3() { return _getCssToken('--jt-text-3', '#5B6B80'); },
      get border() { return _getCssToken('--jt-border', '#E3E7EE'); },
      get divider() { return _getCssToken('--jt-divider', '#EDF0F4'); }
    };
    window.JT_COLORS = JT_COLORS;

    const TONE_BADGE_MAP = {
      green: 'green', emerald: 'green', teal: 'green', ok: 'green', success: 'green',
      amber: 'amber', yellow: 'amber', orange: 'amber', warn: 'amber', warning: 'amber',
      red: 'red', rose: 'red', danger: 'red', error: 'red',
      blue: 'blue', indigo: 'blue', sky: 'blue', cyan: 'blue', info: 'blue',
      gray: 'gray', neutral: 'gray', slate: 'gray',
      navy: 'navy',
      purple: 'purple', violet: 'purple'
    };

    function toneBadge(tone, text, opts = {}) {
      const normTone = TONE_BADGE_MAP[String(tone || 'gray').toLowerCase()] || 'gray';
      const baseCls = opts.chip ? 'jt-chip' : 'jt-badge';
      const toneCls = `${baseCls}--${normTone}`;
      const monoCls = opts.mono ? ' mono' : '';
      const extraCls = opts.className ? ` ${opts.className}` : '';
      const titleAttr = opts.title ? ` title="${escapeHtml(opts.title)}"` : '';
      const idAttr = opts.id ? ` id="${escapeHtml(opts.id)}"` : '';
      const inner = opts.rawHtml ? String(text ?? '') : escapeHtml(text ?? '');
      return `<span${idAttr} class="${baseCls} ${toneCls}${monoCls}${extraCls}"${titleAttr}>${inner}</span>`;
    }
    window.toneBadge = toneBadge;

    // Chip compatto: etichetta breve nel badge, dettaglio completo nel tooltip (globale, riusabile in ogni tabella).
    function jtTipChip(toneCls, iconId, label, tip, attrs = '') {
      const icon = iconId ? `<svg class="jt-ico" aria-hidden="true"><use href="#${escapeHtml(iconId)}"/></svg> ` : '';
      const tipTxt = String(tip || '').trim();
      const tipAttrs = tipTxt ? ` data-jt-tip="${escapeHtml(tipTxt)}" aria-label="${escapeHtml(tipTxt)}" role="note" tabindex="0"` : '';
      return `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold ${toneCls}"${tipAttrs}${attrs ? ' ' + attrs : ''}>${icon}${escapeHtml(label)}</span>`;
    }
    window.jtTipChip = jtTipChip;

    // Lista compatta: mostra i primi `visible` elementi (HTML gia' sicuro) e un pulsante "+N altri" che espande sul posto.
    // Con `stack: true` gli elementi vanno uno sotto l'altro (blocchi), altrimenti affiancati. `key` conserva lo stato aperto.
    const jtExpandOpen = new Set();
    function jtExpandList(items, opts = {}) {
      const list = (items || []).filter(Boolean);
      const visible = opts.visible ?? 2;
      const noun = opts.noun || 'more';
      const stack = Boolean(opts.stack);
      const key = opts.key || '';
      if (list.length <= visible + 1) return stack ? list.join('') : `<div class="jt-expand__shown">${list.join(' ')}</div>`;
      const hiddenCount = list.length - visible;
      const open = Boolean(key) && jtExpandOpen.has(key);
      const cls = stack ? 'jt-expand__stack' : '';
      const keyAttr = key ? ` data-jt-expand-key="${escapeHtml(key)}"` : '';
      return `<div class="jt-expand" data-jt-expand-root${keyAttr}>
        <div class="jt-expand__shown ${cls}">${list.slice(0, visible).join(stack ? '' : ' ')}</div>
        <div class="jt-expand__more ${cls}${open ? '' : ' jt-collapsed'}"${open ? '' : ' inert aria-hidden="true"'}>${list.slice(visible).join(stack ? '' : ' ')}</div>
        <button type="button" class="jt-expand__btn" data-jt-more-label="+${hiddenCount} ${escapeHtml(noun)}" aria-expanded="${open ? 'true' : 'false'}">${open ? 'Show less' : `+${hiddenCount} ${escapeHtml(noun)}`}</button>
      </div>`;
    }
    window.jtExpandList = jtExpandList;
    document.addEventListener('click', (e) => {
      const btn = e.target && e.target.closest ? e.target.closest('.jt-expand__btn') : null;
      if (!btn) return;
      const root = btn.closest('[data-jt-expand-root]');
      const more = root && root.querySelector('.jt-expand__more');
      if (!more) return;
      const nowOpen = more.classList.contains('jt-collapsed');
      more.classList.toggle('jt-collapsed', !nowOpen);
      if (nowOpen) { more.removeAttribute('inert'); more.removeAttribute('aria-hidden'); }
      else { more.setAttribute('inert', ''); more.setAttribute('aria-hidden', 'true'); }
      btn.setAttribute('aria-expanded', nowOpen ? 'true' : 'false');
      btn.textContent = nowOpen ? 'Show less' : (btn.getAttribute('data-jt-more-label') || '+more');
      const key = root.getAttribute('data-jt-expand-key');
      if (key) { if (nowOpen) jtExpandOpen.add(key); else jtExpandOpen.delete(key); }
    });

    (function initJtTooltips() {
      let tipEl = null;
      const ensure = () => {
        if (!tipEl) {
          tipEl = document.createElement('div');
          tipEl.className = 'jt-tip';
          tipEl.setAttribute('role', 'tooltip');
          document.body.appendChild(tipEl);
        }
        return tipEl;
      };
      const hide = () => { if (tipEl) tipEl.style.display = 'none'; };
      const show = (target) => {
        const txt = target.getAttribute('data-jt-tip');
        if (!txt) return;
        const el = ensure();
        el.textContent = txt;
        el.style.display = 'block';
        const r = target.getBoundingClientRect();
        const left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - el.offsetWidth - 8));
        let top = r.top - el.offsetHeight - 6;
        if (top < 8) top = r.bottom + 6;
        el.style.left = `${left}px`;
        el.style.top = `${top}px`;
      };
      const tipTarget = (e) => (e.target && e.target.closest ? e.target.closest('[data-jt-tip]') : null);
      document.addEventListener('mouseover', (e) => { const t = tipTarget(e); if (t) show(t); else hide(); });
      document.addEventListener('mouseout', (e) => { const t = tipTarget(e); if (t && !t.contains(e.relatedTarget)) hide(); });
      document.addEventListener('focusin', (e) => { const t = tipTarget(e); if (t) show(t); });
      document.addEventListener('focusout', hide);
      document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });
      window.addEventListener('scroll', hide, true);
    })();

    const JT_EMOJI_ICO_MAP = {'🛡️': 'ico-shield', '🛡': 'ico-shield', '🔑': 'ico-key', '🎫': 'ico-key', '🪪': 'ico-key', '🔐': 'ico-lock', '🔒': 'ico-lock', '🔓': 'ico-lock', '🤖': 'ico-bot', '🧠': 'ico-bot', '🧟': 'ico-bot', '✨': 'ico-bot', '🌱': 'ico-bot', '🟣': 'ico-bot', '🔹': 'ico-bot', '🔵': 'ico-bot', '⚡': 'ico-bolt', '🚀': 'ico-bolt', '🆕': 'ico-bolt', '🆓': 'ico-bolt', '🧩': 'ico-puzzle', '🔌': 'ico-puzzle', '🔗': 'ico-puzzle', '📡': 'ico-puzzle', '🛰️': 'ico-puzzle', '🛰': 'ico-puzzle', '🚨': 'ico-alert', '⚠️': 'ico-alert', '⚠': 'ico-alert', '🔥': 'ico-alert', '🔴': 'ico-alert', '🟡': 'ico-alert', '📊': 'ico-chart', '📈': 'ico-chart', '💰': 'ico-chart', '💳': 'ico-chart', '🪙': 'ico-chart', '🧾': 'ico-chart', '💧': 'ico-chart', '🏆': 'ico-chart', '👤': 'ico-user', '👥': 'ico-user', '📇': 'ico-user', '🕵️': 'ico-user', '🕵': 'ico-user', '👨\u200d💻': 'ico-user', '🧑\u200d💻': 'ico-user', '🖐️': 'ico-user', '🖐': 'ico-user', '💻': 'ico-terminal', '🖥️': 'ico-terminal', '🖥': 'ico-terminal', '🛠️': 'ico-terminal', '🛠': 'ico-terminal', '⚙️': 'ico-terminal', '⚙': 'ico-terminal', '🔧': 'ico-terminal', '🎛️': 'ico-terminal', '🎛': 'ico-terminal', '🧪': 'ico-terminal', '🔬': 'ico-terminal', '🐍': 'ico-terminal', '📐': 'ico-terminal', '🎨': 'ico-terminal', '🔤': 'ico-terminal', '🏛️': 'ico-globe', '🏛': 'ico-globe', '🌐': 'ico-globe', '🌍': 'ico-globe', '🌎': 'ico-globe', '🇪🇺': 'ico-globe', '🇮🇹': 'ico-globe', '🏢': 'ico-globe', '☁️': 'ico-globe', '☁': 'ico-globe', '🔍': 'ico-search', '🔎': 'ico-search', '📓': 'ico-doc', '📋': 'ico-doc', '📂': 'ico-doc', '📁': 'ico-doc', '🗂️': 'ico-doc', '🗂': 'ico-doc', '🗄️': 'ico-doc', '🗄': 'ico-doc', '📦': 'ico-doc', '💬': 'ico-doc', '📧': 'ico-doc', '💡': 'ico-doc', '📥': 'ico-doc', '📅': 'ico-doc', '🗓️': 'ico-doc', '🗓': 'ico-doc', '🔄': 'ico-refresh', '⏱️': 'ico-refresh', '⏱': 'ico-refresh', '⏳': 'ico-refresh', '💤': 'ico-refresh', '⏸️': 'ico-refresh', '⏸': 'ico-refresh', '✅': 'ico-check', '✓': 'ico-check', '✔️': 'ico-check', '🟢': 'ico-check', '✕': 'ico-close', '❌': 'ico-close', '⚪': 'ico-close'};
    const JT_EMOJI_KEYS = Object.keys(JT_EMOJI_ICO_MAP).sort((a, b) => b.length - a.length);
    const JT_EMOJI_RE = new RegExp(JT_EMOJI_KEYS.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g');

    // Replaces decorative emoji in text nodes with the matching SVG icons from the sprite.
    function jtReplaceEmojiWithIcons(root) {
      if (!root) return;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
      const textNodes = [];
      let node = walker.nextNode();
      while (node) {
        textNodes.push(node);
        node = walker.nextNode();
      }
      for (let idx = 0; idx < textNodes.length; idx++) {
        const tn = textNodes[idx];
        let v = tn.nodeValue;
        if (!v) continue;
        JT_EMOJI_RE.lastIndex = 0;
        if (JT_EMOJI_RE.test(v)) {
          const parentTag = (tn.parentNode && tn.parentNode.nodeName) ? tn.parentNode.nodeName.toUpperCase() : '';
          if (parentTag === 'OPTION' || parentTag === 'SCRIPT' || parentTag === 'STYLE' || parentTag === 'TEXTAREA') {
            tn.nodeValue = v.replace(JT_EMOJI_RE, '').replace(/\uFE0F/g, '').replace(/^\s+/, '');
          } else if (tn.parentNode) {
            const frag = document.createDocumentFragment();
            let lastIdx = 0;
            JT_EMOJI_RE.lastIndex = 0;
            let m;
            while ((m = JT_EMOJI_RE.exec(v)) !== null) {
              const before = v.slice(lastIdx, m.index).replace(/\uFE0F/g, '');
              if (before) frag.appendChild(document.createTextNode(before));
              const icoId = JT_EMOJI_ICO_MAP[m[0]];
              if (icoId) {
                const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svgEl.setAttribute('class', 'jt-ico');
                svgEl.setAttribute('aria-hidden', 'true');
                const useEl = document.createElementNS('http://www.w3.org/2000/svg', 'use');
                useEl.setAttribute('href', '#' + icoId);
                svgEl.appendChild(useEl);
                frag.appendChild(svgEl);
              }
              lastIdx = m.index + m[0].length;
            }
            const after = v.slice(lastIdx).replace(/\uFE0F/g, '');
            if (after) frag.appendChild(document.createTextNode(after));
            tn.parentNode.replaceChild(frag, tn);
          }
        }
      }
    }

    // Defense in depth, a LISTA BIANCA: i template escapano già i dati con escapeHtml/jsArg; qui resta solo ciò che
    // l'interfaccia usa davvero. Tag o attributi non in elenco vengono tolti; ogni attributo on* viene tolto
    // (le azioni passano da data-jt-click/change/input/keydown, validate da ui_actions.js al momento del clic).
    const SANITIZE_ALLOWED_TAGS = new Set([
      'a', 'abbr', 'aside', 'b', 'blockquote', 'br', 'button', 'canvas', 'caption', 'code', 'col', 'colgroup',
      'dd', 'details', 'div', 'dl', 'dt', 'em', 'figcaption', 'figure', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'header', 'hr', 'i', 'img', 'input', 'kbd', 'label', 'legend', 'li', 'main', 'mark', 'nav', 'ol', 'optgroup',
      'option', 'p', 'pre', 's', 'section', 'select', 'small', 'span', 'strong', 'sub', 'summary', 'sup', 'table',
      'tbody', 'td', 'textarea', 'tfoot', 'th', 'thead', 'tr', 'u', 'ul', 'wbr',
      // SVG (icone e grafici inline)
      'svg', 'g', 'path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon', 'text', 'tspan', 'symbol',
      'use', 'defs', 'lineargradient', 'stop', 'clippath', 'title'
    ]);
    const SANITIZE_ALLOWED_ATTRS = new Set([
      'class', 'id', 'style', 'title', 'role', 'tabindex', 'lang', 'dir', 'hidden', 'inert',
      'alt', 'href', 'src', 'rel', 'target', 'type', 'value', 'checked', 'disabled', 'selected', 'readonly',
      'placeholder', 'name', 'for', 'min', 'max', 'step', 'rows', 'cols', 'colspan', 'rowspan', 'scope', 'open',
      'maxlength', 'autocomplete', 'width', 'height', 'viewbox', 'preserveaspectratio', 'xmlns', 'xlink:href',
      'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'fill-rule',
      'clip-rule', 'opacity', 'd', 'cx', 'cy', 'r', 'rx', 'ry', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'points',
      'transform', 'offset', 'stop-color', 'gradientunits'
    ]);
    const SANITIZE_URL_ATTRS = new Set(['href', 'src', 'xlink:href']);

    function _sanitizeUrlAllowed(tag, value) {
      const v = String(value).replace(/[\s\u0000-\u001F\u007F]+/g, '');
      if (tag === 'use') return v.startsWith('#');
      if (tag === 'img') return /^(https?:|\/|data:image\/(png|jpeg|gif|webp);base64,)/i.test(v);
      return v === '' || v.startsWith('#') || v.startsWith('/') || /^(https?:|mailto:)/i.test(v);
    }

    function sanitizeFragment(frag) {
      frag.querySelectorAll('*').forEach(node => {
        const tag = node.localName.toLowerCase();
        if (!SANITIZE_ALLOWED_TAGS.has(tag)) {
          node.remove();
          return;
        }
        for (const attr of Array.from(node.attributes)) {
          const name = attr.name.toLowerCase();
          let keep = name.startsWith('data-') || name.startsWith('aria-') || SANITIZE_ALLOWED_ATTRS.has(name);
          if (name.startsWith('on')) keep = false;
          if (keep && SANITIZE_URL_ATTRS.has(name) && !_sanitizeUrlAllowed(tag, attr.value)) keep = false;
          if (keep && name === 'style' && /(url\s*\(|expression\s*\(|@import|javascript:|behavior\s*:)/i.test(attr.value)) keep = false;
          if (!keep) node.removeAttribute(attr.name);
        }
        if (node.getAttribute('target') && tag === 'a') node.setAttribute('rel', 'noopener noreferrer');
      });
    }

    function setSafeHtml(el, htmlStr) {
      if (!el) return;
      if (!htmlStr) {
        el.replaceChildren();
        return;
      }
      // <template> parses inertly: nothing loads or runs before sanitizeFragment() has cleaned it.
      const tpl = document.createElement('template');
      tpl.innerHTML = String(htmlStr);
      sanitizeFragment(tpl.content);
      jtReplaceEmojiWithIcons(tpl.content);
      el.replaceChildren(tpl.content);
    }
    window.setSafeHtml = setSafeHtml;

    let chartCostInstance = null;
    let chartUsageInstance = null;
    let chartCredInstance = null;

    let currentSyncFilterMode = 'ALL';

    const VIEW_TITLES = {
      dashboard: 'Executive Dashboard',
      projects: 'Projects & IAM',
      sync: 'Synced Projects',
      daily: 'Daily Spend',
      credentials: 'API Keys & SAs',
      users: 'Cost by User',
      'ai-tools': 'AI Studio & Notebooks',
      models: 'AI Models',
      pricing: 'Pricing & Rates',
      features: 'Apps, Regions & FinOps',
      security: 'AI Security & Posture'
    };

    const VIEW_SUBTITLES = {
      dashboard: 'Real-time AI spend, token throughput, model mix and governance telemetry across Google Cloud.',
      projects: 'Active GCP projects, enabled AI APIs, billing status and IAM permission coverage.',
      sync: 'Smart cache perimeter, scan rules, manual overrides and newly discovered GCP projects.',
      daily: 'Day-by-day net AI cost, invoice correlation, token volume and model breakdown.',
      credentials: 'Inventory and usage telemetry of API Keys, Service Accounts and OAuth 2.0 clients.',
      users: 'Attributed AI spend, request volume and active credentials per user principal.',
      'ai-tools': 'Google AI Studio keys, Vertex AI Workbench, Colab Enterprise and NotebookLM activity.',
      models: 'Deployed foundation models, Model Garden endpoints, token pricing and app configurations.',
      pricing: 'Model rates in USD per 1M tokens, Cloud Billing SKU sync, billing discounts and coverage.',
      features: 'Discovery Engine apps, regional data residency (EU/GDPR), FinOps quotas and Model Armor.',
      security: 'Security posture findings, audit log forensics, key hygiene and guardrails.'
    };

    const LS_SIDEBAR_COLLAPSED_KEY = 'jt_sidebar_collapsed';

    function applySidebarCollapseState(collapsed) {
      const aside = document.getElementById('jt-sidebar');
      const btn = document.getElementById('btn-sidebar-collapse');
      const isCollapsed = Boolean(collapsed);
      if (aside) {
        aside.classList.toggle('jt-sidebar--collapsed', isCollapsed);
      }
      if (btn) {
        const label = isCollapsed ? 'Expand menu' : 'Collapse menu';
        btn.setAttribute('title', label);
        btn.setAttribute('aria-label', label);
        btn.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
        const lblSpan = btn.querySelector('.jt-collapse-label');
        if (lblSpan) lblSpan.textContent = label;
      }
    }

    function initSidebarCollapseState() {
      let collapsed = false;
      try {
        collapsed = localStorage.getItem(LS_SIDEBAR_COLLAPSED_KEY) === '1';
      } catch (err) {
        ignoreStorageError(err);
      }
      applySidebarCollapseState(collapsed);
    }

    function toggleSidebarCollapse() {
      const aside = document.getElementById('jt-sidebar');
      if (aside && aside.classList.contains('jt-sidebar--mobile-open')) {
        closeMobileSidebar();
        return;
      }
      const nextCollapsed = !(aside && aside.classList.contains('jt-sidebar--collapsed'));
      try {
        localStorage.setItem(LS_SIDEBAR_COLLAPSED_KEY, nextCollapsed ? '1' : '0');
      } catch (err) {
        ignoreStorageError(err);
      }
      applySidebarCollapseState(nextCollapsed);
    }
    window.toggleSidebarCollapse = toggleSidebarCollapse;
    initSidebarCollapseState();

    function applyMobileSidebarState(open) {
      const aside = document.getElementById('jt-sidebar');
      const backdrop = document.getElementById('jt-sidebar-backdrop');
      const btn = document.getElementById('btn-mobile-sidebar');
      const isOpen = Boolean(open);
      if (aside) {
        aside.classList.toggle('jt-sidebar--mobile-open', isOpen);
      }
      if (backdrop) {
        backdrop.classList.toggle('is-open', isOpen);
      }
      if (btn) {
        btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      }
    }

    function toggleMobileSidebar(forceOpen) {
      const aside = document.getElementById('jt-sidebar');
      const nextOpen = typeof forceOpen === 'boolean'
        ? forceOpen
        : !(aside && aside.classList.contains('jt-sidebar--mobile-open'));
      applyMobileSidebarState(nextOpen);
    }

    function closeMobileSidebar() {
      applyMobileSidebarState(false);
    }
    window.toggleMobileSidebar = toggleMobileSidebar;
    window.closeMobileSidebar = closeMobileSidebar;

    // =========================================================================
    // SESSIONE ISOLATA PER SCHEDA BROWSER (ZERO-TRUST CON SCADENZA GIORNALIERA)
    // =========================================================================
    const SS_ACTIVE_ACC_KEY = 'gcp_tower_browser_active_account';
    const SS_BROWSER_ACCS_KEY = 'gcp_tower_browser_accounts';
    const SS_SESSION_DATE_KEY = 'gcp_tower_session_date';
    const SS_SESSION_SID_KEY = 'gcp_tower_session_sid';
    const SS_UI_TAB_KEY = 'gcp_tower_ui_tab';
    const SS_UI_DAYS_KEY = 'gcp_tower_ui_days';
    const SS_UI_START_DATE_KEY = 'gcp_tower_ui_start_date';
    const SS_UI_END_DATE_KEY = 'gcp_tower_ui_end_date';
    const SS_UI_PROJ_KEY = 'gcp_tower_ui_project';

    function getTodaySolarDateStr() {
      const d = new Date();
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    }

    function getYesterdaySolarDateStr() {
      const d = new Date();
      d.setDate(d.getDate() - 1);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    }

    function ignoreStorageError(err) {
      return Boolean(err);
    }

    function enforceDailyZeroTrustStorageHygiene() {
      // Rimuove sempre eventuali residui legacy in localStorage
      try {
        localStorage.removeItem('gcp_tower_browser_active_account');
        localStorage.removeItem('gcp_tower_browser_accounts');
        localStorage.removeItem('gcp_tower_session_sid');
        localStorage.removeItem('gcp_tower_session_date');
      } catch (e) {
        ignoreStorageError(e);
      }

      // Verifica scadenza giornaliera in sessionStorage
      try {
        const todayStr = getTodaySolarDateStr();
        const savedDate = sessionStorage.getItem(SS_SESSION_DATE_KEY);
        if (savedDate && savedDate !== todayStr) {
          sessionStorage.removeItem(SS_ACTIVE_ACC_KEY);
          sessionStorage.removeItem(SS_BROWSER_ACCS_KEY);
          sessionStorage.removeItem(SS_SESSION_SID_KEY);
          sessionStorage.removeItem(SS_SESSION_DATE_KEY);
        }
      } catch (e) {
        ignoreStorageError(e);
      }
    }

    // Esegui pulizia Zero-Trust immediatamente all'avvio dello script
    enforceDailyZeroTrustStorageHygiene();

    function getBrowserSessionSid() {
      enforceDailyZeroTrustStorageHygiene();
      return sessionStorage.getItem(SS_SESSION_SID_KEY) || '';
    }

    function saveBrowserSessionSid(sid) {
      if (!sid) return;
      sessionStorage.setItem(SS_SESSION_SID_KEY, sid);
      sessionStorage.setItem(SS_SESSION_DATE_KEY, getTodaySolarDateStr());
    }

    function getBrowserActiveAccount() {
      enforceDailyZeroTrustStorageHygiene();
      const savedDate = sessionStorage.getItem(SS_SESSION_DATE_KEY);
      if (savedDate !== getTodaySolarDateStr()) return '';
      return sessionStorage.getItem(SS_ACTIVE_ACC_KEY) || '';
    }

    function getBrowserAccountsList() {
      enforceDailyZeroTrustStorageHygiene();
      const savedDate = sessionStorage.getItem(SS_SESSION_DATE_KEY);
      if (savedDate !== getTodaySolarDateStr()) return [];
      try {
        const raw = sessionStorage.getItem(SS_BROWSER_ACCS_KEY);
        const arr = raw ? JSON.parse(raw) : [];
        return Array.isArray(arr) ? arr : [];
      } catch (e) {
        return [];
      }
    }

    function saveBrowserAccountSession(email) {
      if (!email) return;
      const todayStr = getTodaySolarDateStr();
      sessionStorage.setItem(SS_SESSION_DATE_KEY, todayStr);
      sessionStorage.setItem(SS_ACTIVE_ACC_KEY, email);
      const list = getBrowserAccountsList();
      if (!list.includes(email)) {
        list.push(email);
        sessionStorage.setItem(SS_BROWSER_ACCS_KEY, JSON.stringify(list));
      }
    }

    function clearBrowserAccountSession() {
      try {
        localStorage.removeItem('gcp_tower_browser_active_account');
        localStorage.removeItem('gcp_tower_browser_accounts');
        sessionStorage.removeItem(SS_ACTIVE_ACC_KEY);
        sessionStorage.removeItem(SS_BROWSER_ACCS_KEY);
        sessionStorage.removeItem(SS_SESSION_SID_KEY);
        sessionStorage.removeItem(SS_SESSION_DATE_KEY);
      } catch (e) {
        ignoreStorageError(e);
      }
    }

    function getBrowserAuthHeaders(extra = {}) {
      const headers = { ...extra };
      const act = getBrowserActiveAccount();
      const list = getBrowserAccountsList();
      const sid = getBrowserSessionSid();
      if (act) headers['X-GCP-Account'] = act;
      if (list.length > 0) headers['X-GCP-Browser-Accounts'] = list.join(',');
      if (sid) headers['X-GCP-Session-Token'] = sid;
      return headers;
    }

    function fmtNum(n) {
      return Number(n || 0).toLocaleString('en-US');
    }

    function fmtTok(n) {
      const v = Number(n || 0);
      if (v >= 1_000_000_000) return (v / 1_000_000_000).toFixed(2) + 'B';
      if (v >= 1_000_000) return (v / 1_000_000).toFixed(2) + 'M';
      if (v >= 1_000) return (v / 1_000).toFixed(1) + 'K';
      return String(v);
    }

    function fmtBytes(b) {
      const v = Number(b || 0);
      if (v >= 1_000_000_000) return (v / 1_000_000_000).toFixed(2) + ' GB';
      if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + ' MB';
      if (v >= 1_000) return (v / 1_000).toFixed(1) + ' KB';
      return v + ' B';
    }

    function fmtUsd(n) {
      const v = Number(n || 0);
      if (v > 0 && v < 0.01) return '$' + v.toFixed(4);
      return '$' + v.toFixed(2);
    }

    // EUR per 1 USD for display only; configurable in Pricing & Rates > Billing settings (served via auth status)
    let jtUsdToEur = 0.92;
    function setUsdToEurRate(rate) {
      const n = Number(rate);
      if (!Number.isFinite(n) || n < 0.5 || n > 1.5 || n === jtUsdToEur) return false;
      jtUsdToEur = n;
      return true;
    }
    window.setUsdToEurRate = setUsdToEurRate;
    function fmtEur(usd) {
      const v = Number(usd || 0) * jtUsdToEur;
      if (v > 0 && v < 0.01) return '€' + v.toFixed(4);
      return '€' + v.toFixed(2);
    }

    function toggleChartsSection(show) {
      const el = document.getElementById('charts-section-wrap');
      if (el) el.classList.toggle('hidden', !show);
    }

    // =========================================================================
    // LOGIN SCREEN
    // =========================================================================
    let loginScreenOpenedManually = false;
    let lastKnownAuth = null;

    // Demo mode flags from /api/auth/status (top-level `demo` and `oauthConfigured`).
    let jtAuthFlags = { demo: false, oauthConfigured: true, needsLogin: false };

    // JT-AUTH-UI-STATE-BEGIN (pure function, executed by tests/test_demo_ui.py)
    function jtAuthUiState(status) {
      const st = status || {};
      const demo = st.demo === true;
      // An older backend does not send oauthConfigured: only an explicit false counts as "not configured".
      const oauthConfigured = st.oauthConfigured !== false;
      return {
        showDemoBanner: demo,
        showDemoInvite: demo,
        showGoogleButton: !demo && oauthConfigured,
        showOauthHelp: !demo && !oauthConfigured
      };
    }
    // JT-AUTH-UI-STATE-END

    function applyAuthUiFlags() {
      const ui = jtAuthUiState(jtAuthFlags);
      const setHidden = (id, hidden) => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('hidden', hidden);
      };
      setHidden('demo-banner', !ui.showDemoBanner);
      setHidden('login-demo-invite', !ui.showDemoInvite);
      setHidden('login-google-wrap', !ui.showGoogleButton);
      setHidden('login-oauth-help', !ui.showOauthHelp);
    }

    function updateAuthFlagsFromStatus(data) {
      const src = data || {};
      const auth = src.auth || {};
      jtAuthFlags = {
        demo: (src.demo !== undefined ? src.demo : auth.demo) === true,
        oauthConfigured: (src.oauthConfigured !== undefined ? src.oauthConfigured : auth.oauthConfigured),
        needsLogin: Boolean(auth.needsLogin)
      };
      applyAuthUiFlags();
    }

    async function enterDemo() {
      closeLoginScreen();
      if (typeof globalScanData !== 'undefined' && globalScanData) return;
      await checkAuthAndInitialLoad();
    }

    function openLoginScreen(manual = true) {
      loginScreenOpenedManually = manual;
      const scr = document.getElementById('janus-login-screen');
      if (scr) scr.classList.remove('hidden');
      applyAuthUiFlags();
      if (lastKnownAuth) renderLoginScreenState(lastKnownAuth);
    }

    function closeLoginScreen() {
      loginScreenOpenedManually = false;
      const scr = document.getElementById('janus-login-screen');
      if (scr) scr.classList.add('hidden');
    }

    async function enterWithSavedAccount(account) {
      loginScreenOpenedManually = false;
      closeLoginScreen();
      await switchGoogleAccount(account);
    }

    function renderLoginScreenState(auth) {
      const statusBox = document.getElementById('login-screen-status-box');
      const savedWrap = document.getElementById('login-saved-sessions-wrap');
      const savedList = document.getElementById('login-saved-sessions-list');
      const closeBtn = document.getElementById('btn-close-login-screen');
      const primaryLbl = document.getElementById('login-primary-btn-label');

      const accounts = (auth && auth.accounts) ? auth.accounts : [];
      const isValid = Boolean(auth && auth.tokenValid);

      if (closeBtn) closeBtn.classList.toggle('hidden', !isValid);
      if (primaryLbl) {
        primaryLbl.textContent = accounts.length > 0
          ? 'Switch Google Account'
          : 'Sign in with Google';
      }

      if (statusBox) {
        if (isValid && auth.activeAccount) {
          statusBox.className = 'rounded-xl bg-emerald-50 border border-emerald-200 p-3.5 text-xs text-emerald-900';
          setSafeHtml(statusBox, `
            <div class="flex items-center justify-between gap-2">
              <div>
                <div class="font-bold text-emerald-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Connected</div>
                <div class="mono text-[11px] text-emerald-700 mt-0.5">${escapeHtml(auth.activeAccount)}</div>
              </div>
              <button type="button" data-jt-click="closeLoginScreen()" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs cursor-pointer shrink-0">
                Open →
              </button>
            </div>
          `);
        } else {
          statusBox.className = 'hidden';
          setSafeHtml(statusBox, '');
        }
      }

      if (savedWrap && savedList) {
        if (accounts.length === 0) {
          savedWrap.classList.add('hidden');
          setSafeHtml(savedList, '');
        } else {
          savedWrap.classList.remove('hidden');
          setSafeHtml(savedList, accounts.map(acc => {
            const isAct = Boolean(acc.active && isValid);
            const initials = escapeHtml((acc.account || 'G').slice(0, 2).toUpperCase());
            return `
              <div class="flex items-center justify-between gap-3 p-2.5 rounded-xl border ${isAct ? 'bg-blue-50/60 border-blue-300' : 'bg-white border-slate-200'}">
                <div class="flex items-center gap-2.5 min-w-0">
                  <div class="w-8 h-8 rounded-full ${isAct ? 'bg-[#0F2A4A] text-white' : 'bg-slate-100 text-slate-700'} font-bold text-xs flex items-center justify-center shrink-0">
                    ${initials}
                  </div>
                  <div class="min-w-0">
                    <div class="text-xs font-bold text-slate-800 truncate mono">${escapeHtml(acc.account)}</div>
                  </div>
                </div>
                <button type="button" data-jt-click="enterWithSavedAccount(${jsArg(acc.account || '')})" class="px-3 py-1.5 rounded-lg ${isAct ? 'bg-[#0F2A4A] text-white' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'} font-bold text-xs transition cursor-pointer shrink-0">
                  ${isAct ? 'Enter' : 'Use'}
                </button>
              </div>
            `;
          }).join(''));
        }
      }
    }

    async function checkAuthAndInitialLoad() {
      enforceDailyZeroTrustStorageHygiene();
      const urlParams = new URLSearchParams(window.location.search);
      const autoStart = urlParams.get('autostart') === '1';
      const authError = urlParams.get('auth_error');

      if (autoStart) {
        // Back from Google login: the new session is in the HttpOnly cookie set by the server.
        // Drop this tab's previous account/session id so its headers don't take precedence over it.
        try {
          sessionStorage.removeItem(SS_ACTIVE_ACC_KEY);
          sessionStorage.removeItem(SS_SESSION_SID_KEY);
        } catch (e) {
          ignoreStorageError(e);
        }
        loginScreenOpenedManually = false;
      }
      if (autoStart || authError || urlParams.has('sid') || urlParams.has('logged_in_account')) {
        window.history.replaceState({}, document.title, '/');
      }
      if (authError) {
        alert('Google login error: ' + authError);
      }

      try {
        const res = await fetch('/api/auth/status', {
          headers: getBrowserAuthHeaders(),
          signal: AbortSignal.timeout(30000)
        });
        const data = await res.json();
        updateAuthFlagsFromStatus(data);
        if (data.auth) {
          if (data.auth.sessionToken) {
            saveBrowserSessionSid(data.auth.sessionToken);
          }
          if (data.auth.tokenValid && data.auth.activeAccount) {
            saveBrowserAccountSession(data.auth.activeAccount);
          } else if (!data.auth.tokenValid) {
            globalScanData = null;
          }
          updateAuthUI(data.auth);
        }
        if (data.auth && data.auth.tokenValid) {
          closeLoginScreen();
          // Restore period, custom dates and active tab after F5
          try {
            const savedDays = sessionStorage.getItem(SS_UI_DAYS_KEY);
            const savedStart = sessionStorage.getItem(SS_UI_START_DATE_KEY);
            const savedEnd = sessionStorage.getItem(SS_UI_END_DATE_KEY);
            const singleInput = document.getElementById('period-single-date');
            const startInput = document.getElementById('period-start-date');
            const endInput = document.getElementById('period-end-date');
            if (singleInput && savedStart) singleInput.value = savedStart;
            if (startInput && savedStart) startInput.value = savedStart;
            if (endInput && savedEnd) endInput.value = savedEnd;

            const daysSel = document.getElementById('days-select');
            if (savedDays && daysSel && [...daysSel.options].some(o => o.value === savedDays)) {
              daysSel.value = savedDays;
            }
            if (daysSel && typeof syncCustomDateControlsVisibility === 'function') {
              syncCustomDateControlsVisibility(daysSel.value);
            }
            const savedTab = sessionStorage.getItem(SS_UI_TAB_KEY);
            if (savedTab && VIEW_TITLES[savedTab]) {
              switchTab(savedTab, false);
            }
          } catch (err) {
            ignoreStorageError(err);
          }

          await runScan(true, 'smart');
          if (data.scanProgress && data.scanProgress.active) {
            attachToRunningScanPolling(data.scanProgress);
          }
        } else {
          globalScanData = null;
          openLoginScreen(false);
        }
      } catch (e) {
        console.error(e);
        openLoginScreen(false);
      }
    }

    function closeJtMenus(restoreFocus = false) {
      const activeBtn = restoreFocus ? document.querySelector('[data-jt-menu][aria-expanded="true"]') : null;
      document.querySelectorAll('.jt-menu').forEach(m => { m.hidden = true; });
      document.querySelectorAll('[data-jt-menu]').forEach(btn => { btn.setAttribute('aria-expanded', 'false'); });
      if (activeBtn && typeof activeBtn.focus === 'function') {
        activeBtn.focus();
      }
    }
    window.closeJtMenus = closeJtMenus;

    document.addEventListener('click', (e) => {
      const t = e.target.closest('[data-jt-menu]');
      if (t) {
        const m = document.getElementById(t.dataset.jtMenu);
        if (m) {
          const was = m.hidden;
          closeJtMenus();
          m.hidden = !was;
          t.setAttribute('aria-expanded', String(was));
          e.stopPropagation();
        }
        return;
      }
      if (!e.target.closest('.jt-menu')) closeJtMenus();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeJtMenus(true);
    });

    function initCollapsibleDetailsMemory() {
      document.querySelectorAll('details[data-jt-collapse]').forEach(det => {
        const key = 'jt_collapse_' + det.getAttribute('data-jt-collapse');
        try {
          const saved = sessionStorage.getItem(key);
          if (saved === 'closed') det.removeAttribute('open');
          else det.setAttribute('open', '');
        } catch (err) {
          ignoreStorageError(err);
        }
        if (!det.dataset.jtCollapseBound) {
          det.dataset.jtCollapseBound = '1';
          det.addEventListener('toggle', () => {
            try {
              sessionStorage.setItem(key, det.open ? 'open' : 'closed');
            } catch (err) {
              ignoreStorageError(err);
            }
          });
        }
      });
    }
    document.addEventListener('DOMContentLoaded', initCollapsibleDetailsMemory);

    const _jtDrawerOpeners = {};
    const _JT_DRAWER_IDS = ['pricing-model-modal', 'gemini-inspector-modal', 'user-modal', 'project-modal'];
    const _JT_FOCUSABLE_SEL = 'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    function _getDrawerFocusableElements(drawerEl) {
      if (!drawerEl) return [];
      return Array.from(drawerEl.querySelectorAll(_JT_FOCUSABLE_SEL)).filter(el => {
        if (el.closest('.hidden')) return false;
        return el.offsetParent !== null || el.getClientRects().length > 0;
      });
    }

    function _getTopOpenDrawer() {
      for (const id of _JT_DRAWER_IDS) {
        const el = document.getElementById(id);
        if (el && !el.classList.contains('hidden')) return el;
      }
      return null;
    }

    function jtActivateDrawerFocus(drawerId) {
      const modalEl = document.getElementById(drawerId);
      if (!modalEl) return;
      const prev = document.activeElement;
      if (prev && prev !== document.body && !modalEl.contains(prev)) {
        _jtDrawerOpeners[drawerId] = prev;
      }
      const focusables = _getDrawerFocusableElements(modalEl);
      if (focusables.length > 0) {
        focusables[0].focus();
      } else {
        const titleEl = modalEl.querySelector('.jt-drawer__title');
        if (titleEl) {
          if (!titleEl.hasAttribute('tabindex')) titleEl.setAttribute('tabindex', '-1');
          titleEl.focus();
        }
      }
    }
    window.jtActivateDrawerFocus = jtActivateDrawerFocus;

    function jtDeactivateDrawerFocus(drawerId) {
      const opener = _jtDrawerOpeners[drawerId];
      delete _jtDrawerOpeners[drawerId];
      if (opener && typeof opener.focus === 'function' && document.contains(opener)) {
        opener.focus();
      }
    }
    window.jtDeactivateDrawerFocus = jtDeactivateDrawerFocus;

    window._jtDrawerEscBound = true;
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        const prModal = document.getElementById('pricing-model-modal');
        if (prModal && !prModal.classList.contains('hidden')) {
          ev.preventDefault();
          if (typeof window.closePricingModelDrawer === 'function') window.closePricingModelDrawer();
          return;
        }
        const geModal = document.getElementById('gemini-inspector-modal');
        if (geModal && !geModal.classList.contains('hidden')) {
          ev.preventDefault();
          if (typeof window.closeGeminiInspectorModal === 'function') window.closeGeminiInspectorModal();
          return;
        }
        const uModal = document.getElementById('user-modal');
        if (uModal && !uModal.classList.contains('hidden')) {
          ev.preventDefault();
          if (typeof window.closeUserModal === 'function') window.closeUserModal();
          return;
        }
        const pModal = document.getElementById('project-modal');
        if (pModal && !pModal.classList.contains('hidden')) {
          ev.preventDefault();
          if (typeof closeProjectModal === 'function') closeProjectModal();
          return;
        }
        const aside = document.getElementById('jt-sidebar');
        if (aside && aside.classList.contains('jt-sidebar--mobile-open')) {
          ev.preventDefault();
          closeMobileSidebar();
          return;
        }
        return;
      }
      if (ev.key === 'Tab') {
        const topDrawer = _getTopOpenDrawer();
        if (!topDrawer) return;
        const focusables = _getDrawerFocusableElements(topDrawer);
        if (focusables.length === 0) {
          ev.preventDefault();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        if (ev.shiftKey) {
          if (!topDrawer.contains(active) || active === first) {
            ev.preventDefault();
            last.focus();
          }
        } else {
          if (!topDrawer.contains(active) || active === last) {
            ev.preventDefault();
            first.focus();
          }
        }
      }
    });

    function setHeaderTotalCostDisplay(usdAmount) {
      const hdrCost = document.getElementById('header-total-cost');
      if (!hdrCost) return;
      const num = Number(usdAmount) || 0;
      setSafeHtml(hdrCost, `<b>${escapeHtml(fmtUsd(num))}</b><span>${escapeHtml(fmtEur(num))}</span>`);
    }

    function getRangeButtonLabel(valStr) {
      const map = {
        today: 'Today',
        yesterday: 'Yesterday',
        '1': 'Last 24 hours',
        '7': 'Last 7 days',
        '14': 'Last 14 days',
        '15': 'Last 15 days',
        '28': 'Last 28 days',
        '30': 'Last 30 days',
        '90': 'Last 90 days',
        single: 'Single Date…',
        custom: 'Custom range…'
      };
      return map[String(valStr)] || `Last ${parseInt(valStr, 10) || 30} days`;
    }

    function getSpendReadoutPeriodShort(valStr) {
      const s = String(valStr || '30');
      if (s === 'today' || s === 'yesterday' || s === 'single') return '1D';
      if (s === '1') return '24H';
      if (s === 'custom') return 'CUSTOM';
      return `${parseInt(s, 10) || 30}D`;
    }

    function syncPageActiveScopePill() {
      const pill = document.getElementById('jt-page-active-scope-pill');
      if (!pill) return;
      const projLbl = (document.getElementById('jt-project-label')?.textContent || 'All visible projects').trim();
      const projCnt = (document.getElementById('jt-project-count')?.textContent || '').trim();
      const rangeLbl = (document.getElementById('jt-range-label')?.textContent || 'Last 30 days').trim();
      const scopePart = (projLbl === 'All visible projects' && projCnt) ? `${projLbl} (${projCnt})` : projLbl;
      pill.textContent = `Active filters: ${scopePart} · ${rangeLbl}`;
      pill.className = 'jt-scope-pill hidden';
      pill.hidden = true;
    }

    function syncHeaderRangeUi(valOpt = null) {
      const sel = document.getElementById('days-select');
      const valStr = String(valOpt || (sel && sel.value) || '30');
      const lblEl = document.getElementById('jt-range-label');
      if (lblEl) lblEl.textContent = getRangeButtonLabel(valStr);
      const spendLbl = document.getElementById('jt-spend-label');
      if (spendLbl) spendLbl.textContent = `AI spend · ${getSpendReadoutPeriodShort(valStr)}`;
      const menu = document.getElementById('jt-m-range');
      if (menu) {
        menu.querySelectorAll('[data-range-val]').forEach(btn => {
          btn.setAttribute('aria-checked', btn.getAttribute('data-range-val') === valStr ? 'true' : 'false');
        });
      }
      syncPageActiveScopePill();
      if (typeof updateFilterbarUi === 'function') updateFilterbarUi();
    }
    window.syncHeaderRangeUi = syncHeaderRangeUi;

    function syncHeaderScopeUi() {
      const projSel = document.getElementById('filter-project');
      const curVal = (projSel && projSel.value) ? projSel.value : 'ALL';
      const lblEl = document.getElementById('jt-project-label');
      const cntEl = document.getElementById('jt-project-count');
      const allProjects = (globalScanData && Array.isArray(globalScanData.projects)) ? globalScanData.projects : [];
      const visibleProjects = allProjects.filter(isProjectVisibleByToggles);

      if (curVal === 'ALL') {
        if (lblEl) lblEl.textContent = 'All visible projects';
        if (cntEl) cntEl.textContent = String(visibleProjects.length);
      } else {
        const found = visibleProjects.find(p => p.projectId === curVal) || allProjects.find(p => p.projectId === curVal);
        if (lblEl) lblEl.textContent = found ? (found.name || found.projectId) : curVal;
        if (cntEl) cntEl.textContent = '1';
      }

      const menu = document.getElementById('jt-m-projects');
      if (menu) {
        menu.querySelectorAll('[data-proj-val]').forEach(btn => {
          btn.setAttribute('aria-checked', btn.getAttribute('data-proj-val') === curVal ? 'true' : 'false');
        });
      }
      syncPageActiveScopePill();
      if (typeof updateFilterbarUi === 'function') updateFilterbarUi();
    }
    window.syncHeaderScopeUi = syncHeaderScopeUi;

    function selectHeaderProjectFilter(projVal) {
      closeJtMenus();
      const projSel = document.getElementById('filter-project');
      if (projSel) {
        projSel.value = projVal || 'ALL';
      }
      syncHeaderScopeUi();
      onProjectFilterChanged();
    }
    window.selectHeaderProjectFilter = selectHeaderProjectFilter;

    async function selectHeaderPeriodFilter(val) {
      closeJtMenus();
      await onPeriodDaysChanged(val);
    }
    window.selectHeaderPeriodFilter = selectHeaderPeriodFilter;

    function updateAuthUI(auth) {
      lastKnownAuth = auth;
      if (auth && setUsdToEurRate(auth.usdToEurRate) && typeof globalScanData !== 'undefined' && globalScanData && typeof refreshDashboardView === 'function') {
        refreshDashboardView();
      }
      const dot = document.getElementById('auth-status-dot');
      const sel = document.getElementById('account-select');
      const banner = document.getElementById('auth-alert-banner');
      const bannerMsg = document.getElementById('auth-alert-msg');
      const logoutBtn = document.getElementById('btn-logout-browser');
      const purgeBtn = document.getElementById('btn-purge-local-data');
      const dangerSep = document.getElementById('jt-user-danger-sep');
      const avatarEl = document.getElementById('jt-user-avatar');
      const avatarBtn = document.getElementById('jt-user-avatar-btn');
      const emailEl = document.getElementById('jt-user-email');
      const statusTxtEl = document.getElementById('jt-user-status-text');
      const switcherWrap = document.getElementById('jt-account-switcher-wrap');

      setSafeHtml(sel, '');
      const accounts = (auth && auth.accounts) ? auth.accounts : [];
      const isValid = Boolean(auth && auth.tokenValid);
      const activeEmail = (auth && auth.activeAccount) || (accounts.find(a => a.active)?.account) || '';

      // The purge API checks the session server-side too; the button is only a shortcut.
      if (purgeBtn) purgeBtn.classList.toggle('hidden', !isValid);
      if (dangerSep) dangerSep.classList.toggle('hidden', !isValid);
      if (switcherWrap) switcherWrap.classList.toggle('hidden', accounts.length <= 1);

      if (avatarEl) {
        avatarEl.textContent = activeEmail ? activeEmail.trim().charAt(0).toUpperCase() : 'G';
      }
      if (avatarBtn) {
        avatarBtn.title = activeEmail || 'Account';
      }
      if (emailEl) {
        emailEl.textContent = activeEmail || 'Not signed in';
      }
      if (statusTxtEl) {
        statusTxtEl.textContent = isValid ? 'Connected · read-only access' : 'Not connected';
      }

      if (accounts.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'No account';
        sel.appendChild(opt);
        logoutBtn.classList.add('hidden');
      } else {
        accounts.forEach(acc => {
          const opt = document.createElement('option');
          opt.value = acc.account;
          opt.textContent = acc.account;
          if (acc.active) opt.selected = true;
          sel.appendChild(opt);
        });
        logoutBtn.classList.remove('hidden');
      }

      renderLoginScreenState(auth);

      if (isValid) {
        if (dot) dot.style.background = 'var(--jt-success)';
        banner.classList.add('hidden');
        if (!loginScreenOpenedManually) closeLoginScreen();
      } else {
        if (dot) dot.style.background = 'var(--jt-warning)';
        banner.classList.remove('hidden');
        if (bannerMsg) bannerMsg.textContent = 'Sign in to view data.';
        globalScanData = null;
        setHeaderTotalCostDisplay(0);
        openLoginScreen(false);
      }
    }

    async function switchGoogleAccount(account) {
      if (!account) return;
      saveBrowserAccountSession(account);
      try {
        const res = await fetch('/api/auth/switch', {
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ account }),
          signal: AbortSignal.timeout(30000)
        });
        const data = await res.json();
        if (data.auth) {
          if (data.auth.sessionToken) saveBrowserSessionSid(data.auth.sessionToken);
          loginScreenOpenedManually = false;
          updateAuthUI(data.auth);
          if (data.auth.tokenValid) {
            closeLoginScreen();
            await runScan(true, 'smart');
          }
        }
      } catch (e) {
        alert('Error switching account: ' + e.message);
      }
    }

    async function logoutThisBrowser() {
      const authHeaders = getBrowserAuthHeaders();
      clearBrowserAccountSession();
      globalScanData = null;
      setHeaderTotalCostDisplay(0);
      try {
        // The demo session lives on the server and cannot be closed (the endpoint answers 403): only this browser is detached,
        // and the login screen offers "Explore the demo" again.
        if (!jtAuthFlags.demo) {
          const res = await fetch('/api/auth/logout', {
            method: 'POST',
            headers: authHeaders,
            signal: AbortSignal.timeout(30000)
          });
          const data = await res.json();
          if (data.auth) updateAuthUI(data.auth);
        }
      } catch (e) {
        console.error(e);
      }
      const pTbody = document.getElementById('projects-tbody');
      if (pTbody) setSafeHtml(pTbody, `<tr><td colspan="8" class="py-10 text-center text-slate-400">Session disconnected.</td></tr>`);
      openLoginScreen(false);
    }

    async function purgeLocalData() {
      const acc = getBrowserActiveAccount() || 'this account';
      const ok = confirm(
        `Delete the local scan data of ${acc} from this computer?\n\n` +
        `This removes the cached scan results in the data/ folder (they can contain personal data: ` +
        `user emails from audit logs, Agentspace licenses and session metadata) and the project sync list.\n\n` +
        `Your Google login and your budgets are kept. Other accounts' data is not touched.\n\n` +
        `Note: reloading the page or changing the period starts a new scan, which downloads the data again.`
      );
      if (!ok) return;
      try {
        const res = await fetch('/api/data/purge', {
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: '{}',
          signal: AbortSignal.timeout(30000)
        });
        const data = await res.json();
        if (data.needsLogin) {
          _handleNeedsLoginRedirect();
          return;
        }
        if (!data.success) {
          alert('Local data not deleted: ' + (data.error || 'Unknown error'));
          return;
        }
        globalScanData = null;
        setHeaderTotalCostDisplay(0);
        const pTbody = document.getElementById('projects-tbody');
        if (pTbody) setSafeHtml(pTbody, `<tr><td colspan="8" class="py-10 text-center text-slate-400">Local data deleted. Run a new scan to load data again.</td></tr>`);
        alert(`Local data deleted: ${data.deletedFiles} cache file(s)` + (data.registryEntryRemoved ? ' and the project sync list.' : '.'));
      } catch (e) {
        alert('Network error while deleting local data: ' + e.message);
      }
    }

    function triggerGoogleLogin(forceAccountChooser = true) {
      const selAccount = document.getElementById('account-select').value;
      const hint = (!forceAccountChooser && selAccount) ? `?login_hint=${encodeURIComponent(selAccount)}` : '';
      window.location.href = `/auth/google/start${hint}`;
    }

    function syncCustomDateControlsVisibility(val) {
      const wrap = document.getElementById('custom-date-controls');
      const singleInput = document.getElementById('period-single-date');
      const rangeWrap = document.getElementById('period-range-inputs');
      const startInput = document.getElementById('period-start-date');
      const endInput = document.getElementById('period-end-date');
      syncHeaderRangeUi(val);
      if (!wrap) return;

      const todayStr = getTodaySolarDateStr();
      const yesterdayStr = getYesterdaySolarDateStr();

      if (val === 'single') {
        wrap.classList.remove('hidden');
        wrap.classList.add('flex');
        if (singleInput) {
          singleInput.classList.remove('hidden');
          if (!singleInput.value) singleInput.value = todayStr;
        }
        if (rangeWrap) {
          rangeWrap.classList.add('hidden');
          rangeWrap.classList.remove('flex');
        }
      } else if (val === 'custom') {
        wrap.classList.remove('hidden');
        wrap.classList.add('flex');
        if (singleInput) singleInput.classList.add('hidden');
        if (rangeWrap) {
          rangeWrap.classList.remove('hidden');
          rangeWrap.classList.add('flex');
        }
        if (startInput && !startInput.value) {
          const d7 = new Date();
          d7.setDate(d7.getDate() - 6);
          startInput.value = `${d7.getFullYear()}-${String(d7.getMonth() + 1).padStart(2, '0')}-${String(d7.getDate()).padStart(2, '0')}`;
        }
        if (endInput && !endInput.value) {
          endInput.value = todayStr;
        }
      } else {
        wrap.classList.add('hidden');
        wrap.classList.remove('flex');
        if (singleInput) singleInput.classList.add('hidden');
        if (rangeWrap) {
          rangeWrap.classList.add('hidden');
          rangeWrap.classList.remove('flex');
        }
        if (val === 'today') {
          if (singleInput) singleInput.value = todayStr;
        } else if (val === 'yesterday') {
          if (singleInput) singleInput.value = yesterdayStr;
        }
      }
    }

    function getSelectedPeriodParams() {
      const sel = document.getElementById('days-select');
      const rawVal = (sel && sel.value) ? String(sel.value) : '30';
      const todayStr = getTodaySolarDateStr();
      const yesterdayStr = getYesterdaySolarDateStr();

      if (rawVal === 'today') {
        return {
          days: 1,
          preset: 'today',
          startDate: todayStr,
          endDate: todayStr,
          label: `Today (${todayStr})`,
          querySuffix: `&preset=today&startDate=${encodeURIComponent(todayStr)}&endDate=${encodeURIComponent(todayStr)}`
        };
      }
      if (rawVal === 'yesterday') {
        return {
          days: 1,
          preset: 'yesterday',
          startDate: yesterdayStr,
          endDate: yesterdayStr,
          label: `Yesterday (${yesterdayStr})`,
          querySuffix: `&preset=yesterday&startDate=${encodeURIComponent(yesterdayStr)}&endDate=${encodeURIComponent(yesterdayStr)}`
        };
      }
      if (rawVal === 'single') {
        const singleInput = document.getElementById('period-single-date');
        const dStr = (singleInput && singleInput.value) ? singleInput.value.slice(0, 10) : todayStr;
        return {
          days: 1,
          preset: 'single',
          startDate: dStr,
          endDate: dStr,
          label: `Date ${dStr}`,
          querySuffix: `&preset=single&startDate=${encodeURIComponent(dStr)}&endDate=${encodeURIComponent(dStr)}`
        };
      }
      if (rawVal === 'custom') {
        const startInput = document.getElementById('period-start-date');
        const endInput = document.getElementById('period-end-date');
        let sStr = (startInput && startInput.value) ? startInput.value.slice(0, 10) : yesterdayStr;
        let eStr = (endInput && endInput.value) ? endInput.value.slice(0, 10) : todayStr;
        if (sStr > eStr) {
          const tmp = sStr;
          sStr = eStr;
          eStr = tmp;
          if (startInput) startInput.value = sStr;
          if (endInput) endInput.value = eStr;
        }
        const diffMs = Math.max(0, new Date(eStr + 'T00:00:00Z').getTime() - new Date(sStr + 'T00:00:00Z').getTime());
        const calcDays = Math.max(1, Math.round(diffMs / 86400000) + 1);
        return {
          days: calcDays,
          preset: 'custom',
          startDate: sStr,
          endDate: eStr,
          label: `${sStr} → ${eStr} (${calcDays}d)`,
          querySuffix: `&preset=custom&startDate=${encodeURIComponent(sStr)}&endDate=${encodeURIComponent(eStr)}`
        };
      }

      const numDays = Math.max(1, parseInt(rawVal, 10) || 30);
      return {
        days: numDays,
        preset: String(numDays),
        startDate: '',
        endDate: '',
        label: `${numDays}d`,
        querySuffix: `&preset=${encodeURIComponent(String(numDays))}`
      };
    }

    async function onPeriodDaysChanged(newVal) {
      const sel = document.getElementById('days-select');
      const valStr = String(newVal || (sel ? sel.value : '30'));
      if (sel && newVal) {
        sel.value = valStr;
      }
      syncCustomDateControlsVisibility(valStr);
      const pParams = getSelectedPeriodParams();
      try {
        sessionStorage.setItem(SS_UI_DAYS_KEY, valStr);
        if (pParams.startDate) sessionStorage.setItem(SS_UI_START_DATE_KEY, pParams.startDate);
        if (pParams.endDate) sessionStorage.setItem(SS_UI_END_DATE_KEY, pParams.endDate);
      } catch (err) {
        ignoreStorageError(err);
      }
      await runScan(true, 'smart');
    }

    async function applyCustomDateFilter() {
      const sel = document.getElementById('days-select');
      const valStr = (sel && sel.value) ? String(sel.value) : 'single';
      const pParams = getSelectedPeriodParams();
      try {
        sessionStorage.setItem(SS_UI_DAYS_KEY, valStr);
        if (pParams.startDate) sessionStorage.setItem(SS_UI_START_DATE_KEY, pParams.startDate);
        if (pParams.endDate) sessionStorage.setItem(SS_UI_END_DATE_KEY, pParams.endDate);
      } catch (err) {
        ignoreStorageError(err);
      }
      await runScan(true, 'smart');
    }

    let scanTimerInterval = null;
    let scanCompletedBannerTimeout = null;
    let isLiveScanPolling = false;

    function setScanButtonsLocked(locked, labelText = 'Scan') {
      const btn = document.getElementById('btn-scan');
      const icon = document.getElementById('scan-icon');
      const lbl = document.getElementById('scan-label');
      const btnSyncSmart = document.getElementById('btn-sync-scan-smart');
      const btnSyncSmartLbl = document.getElementById('btn-sync-scan-smart-label');
      const btnSyncFull = document.getElementById('btn-sync-scan-full');
      const btnSyncFullLbl = document.getElementById('btn-sync-scan-full-label');

      if (btn) btn.disabled = Boolean(locked);
      if (icon) icon.classList.toggle('animate-spin', Boolean(locked));
      const normalizedLbl = (!locked && (!labelText || labelText === 'Scan Active')) ? 'Scan' : (labelText || (locked ? 'Scanning...' : 'Scan'));
      if (lbl) lbl.textContent = normalizedLbl;
      if (btnSyncSmart) btnSyncSmart.disabled = Boolean(locked);
      if (btnSyncSmartLbl) {
        btnSyncSmartLbl.textContent = locked
          ? `Scanning (${normalizedLbl})...`
          : 'Scan "To Scan" (+ New)';
      }
      if (btnSyncFull) btnSyncFull.disabled = Boolean(locked);
      if (btnSyncFullLbl) {
        btnSyncFullLbl.textContent = locked ? 'Scanning...' : 'Rescan All';
      }
    }

    function renderScanProgressBanner(prog, fallbackMode = 'smart', days = '30') {
      const loading = document.getElementById('loading-banner');
      const spinnerEl = document.getElementById('loading-banner-spinner');
      const elapsedEl = document.getElementById('loading-elapsed-badge');
      const etaEl = document.getElementById('loading-eta-badge');
      const pctEl = document.getElementById('loading-pct-badge');
      const barEl = document.getElementById('loading-progress-bar');
      const stepBadgeEl = document.getElementById('loading-step-badge');
      const stepDescEl = document.getElementById('loading-banner-step');
      const titleEl = document.getElementById('loading-banner-title');
      const cacheTxt = document.getElementById('cache-status-text');
      const cachePill = document.getElementById('cache-status-pill');

      if (scanCompletedBannerTimeout) {
        clearTimeout(scanCompletedBannerTimeout);
        scanCompletedBannerTimeout = null;
      }

      if (loading) {
        loading.classList.remove('hidden', 'border-emerald-300', 'bg-emerald-50/40');
        loading.classList.add('border-blue-200', 'bg-white');
      }
      if (spinnerEl) {
        setSafeHtml(spinnerEl, '<svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg>');
        spinnerEl.className = 'w-8 h-8 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center animate-spin text-base shrink-0';
      }

      const mode = (prog && prog.mode) || fallbackMode || 'smart';
      const scanDays = (prog && prog.days) || days || '30';
      const estSeconds = mode === 'full' ? 28 : 16;
      const sec = Math.max(0, Math.round(Number((prog && prog.elapsedSeconds) || 0)));
      const comp = Number((prog && prog.completedProjects) || 0);
      const tot = Number((prog && prog.totalProjects) || 0);

      let pct = Number((prog && prog.pct) || 8);
      if (tot > 0) {
        const ratio = comp / tot;
        const timeBlend = Math.min(0.88, (sec / Math.max(12, estSeconds)) * 0.75);
        const effectiveRatio = Math.max(ratio, timeBlend);
        pct = Math.min(97, Math.max(pct, Math.round(14 + effectiveRatio * 82)));
      } else {
        pct = Math.min(92, Math.max(8, Math.round((sec / estSeconds) * 84) + 8));
      }

      let phaseTxt = (prog && prog.currentPhase) || 'Phase 1/4';
      let stepTxt = (prog && prog.currentStep) || 'Keep-Alive connection and checking accessible Google Cloud projects...';
      if (tot === 0) {
        if (sec < 4) {
          phaseTxt = 'Phase 1/4';
          stepTxt = 'Checking Google Cloud projects, Billing status, and IAM permissions in parallel...';
        } else if (sec < 10) {
          phaseTxt = 'Phase 2/4';
          stepTxt = 'Parallel Cloud Monitoring extraction: Vertex AI calls, Gemini API, and Token consumption...';
        } else {
          phaseTxt = 'Phase 3/4';
          stepTxt = 'Parallel audit of API Keys, Service Accounts, Agentspace Apps, MCP, Model Armor, and User Logs...';
        }
      }

      if (titleEl) {
        setSafeHtml(titleEl, mode === 'full'
          ? `<svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> Full GCP Scan (${escapeHtml(scanDays)} days) in progress — No reload needed (F5 safe)`
          : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> Parallel Scan of active AI projects (${escapeHtml(scanDays)} days) in progress — No reload needed (F5 safe)`);
      }
      if (stepBadgeEl) {
        stepBadgeEl.textContent = phaseTxt;
        stepBadgeEl.className = 'px-2 py-0.5 rounded-full bg-blue-50 text-[#0F2A4A] border border-blue-200 text-[10px] font-extrabold mono';
      }
      if (stepDescEl) stepDescEl.textContent = stepTxt;
      if (elapsedEl) setSafeHtml(elapsedEl, `<svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> ${escapeHtml(sec)}s`);
      if (etaEl) {
        etaEl.textContent = tot > 0
          ? `Live projects: ${comp}/${tot} (~${estSeconds}s)`
          : `ETA: ~${estSeconds}s`;
      }
      if (pctEl) pctEl.textContent = `${pct}%`;
      if (barEl) {
        barEl.style.width = `${pct}%`;
        barEl.className = 'h-full bg-[#3D92F7] transition-all duration-500 rounded-full';
      }

      setScanButtonsLocked(true, `${sec}s • ${pct}%`);

      const statusDot = document.getElementById('jt-status-dot');
      const statusDetail = document.getElementById('jt-status-detail');
      if (statusDot) statusDot.className = 'jt-dot jt-dot--busy';
      if (cacheTxt) {
        cacheTxt.textContent = `Scanning · ${pct}%`;
      }
      if (statusDetail) {
        statusDetail.textContent = tot > 0 ? `${sec}s · ${comp}/${tot}` : `${sec}s · ${scanDays}d`;
      }
    }

    function showCompletedScanBanner(finProg) {
      const loading = document.getElementById('loading-banner');
      const spinnerEl = document.getElementById('loading-banner-spinner');
      const elapsedEl = document.getElementById('loading-elapsed-badge');
      const etaEl = document.getElementById('loading-eta-badge');
      const pctEl = document.getElementById('loading-pct-badge');
      const barEl = document.getElementById('loading-progress-bar');
      const stepBadgeEl = document.getElementById('loading-step-badge');
      const stepDescEl = document.getElementById('loading-banner-step');
      const titleEl = document.getElementById('loading-banner-title');

      const dur = (finProg && finProg.lastElapsedSeconds) || (globalScanData && globalScanData.elapsedSeconds) || 0;
      const finTime = (finProg && finProg.finishedAtLocal) || new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const tot = (finProg && finProg.totalProjects) || (globalScanData && globalScanData.summary && globalScanData.summary.scannedLiveProjects) || 0;

      if (!loading) return;
      loading.classList.remove('hidden', 'border-blue-200', 'bg-white');
      loading.classList.add('border-emerald-300', 'bg-emerald-50/40');
      if (spinnerEl) {
        setSafeHtml(spinnerEl, `<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg>`);
        spinnerEl.className = 'w-8 h-8 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center text-base shrink-0';
      }
      if (titleEl) setSafeHtml(titleEl, `<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Scan completed at ${escapeHtml(finTime)} (in ${escapeHtml(dur)}s) — Dashboard automatically updated`);
      if (stepBadgeEl) {
        stepBadgeEl.textContent = 'COMPLETED 100%';
        stepBadgeEl.className = 'px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300 text-[10px] font-extrabold mono';
      }
      if (stepDescEl) {
        stepDescEl.textContent = tot > 0
          ? `All ${tot} projects have been analyzed and saved to the instant cache.`
          : 'All data is up to date and saved to the instant cache.';
      }
      if (elapsedEl) setSafeHtml(elapsedEl, `<svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> ${escapeHtml(dur)}s`);
      if (etaEl) etaEl.textContent = `Finished at ${finTime}`;
      if (pctEl) pctEl.textContent = '100%';
      if (barEl) {
        barEl.style.width = '100%';
        barEl.className = 'h-full bg-emerald-500 transition-all duration-500 rounded-full';
      }

      if (scanCompletedBannerTimeout) clearTimeout(scanCompletedBannerTimeout);
      scanCompletedBannerTimeout = setTimeout(() => {
        if (!isLiveScanPolling && loading) {
          loading.classList.add('hidden');
        }
      }, 6500);
    }

    function attachToRunningScanPolling(initialProg = null, fallbackDays = '30') {
      const pParams = getSelectedPeriodParams();
      const days = pParams.days || fallbackDays || '30';
      renderScanProgressBanner(initialProg || { active: true, elapsedSeconds: 0, pct: 8 }, 'smart', days);

      if (isLiveScanPolling && scanTimerInterval) {
        return;
      }
      isLiveScanPolling = true;
      if (scanTimerInterval) {
        clearInterval(scanTimerInterval);
        scanTimerInterval = null;
      }

      scanTimerInterval = setInterval(async () => {
        try {
          const pRes = await fetch('/api/scan/progress', {
            headers: getBrowserAuthHeaders(),
            signal: AbortSignal.timeout(15000)
          });
          if (!pRes.ok) return;
          const pJson = await pRes.json();
          const prog = (pJson && pJson.progress) || null;
          if (!prog) return;

          if (prog.active) {
            renderScanProgressBanner(prog, prog.mode || 'smart', prog.days || days);
          } else {
            clearInterval(scanTimerInterval);
            scanTimerInterval = null;
            isLiveScanPolling = false;
            setScanButtonsLocked(false, 'Scan Active');

            if (prog.lastError) {
              const loading = document.getElementById('loading-banner');
              if (loading) loading.classList.add('hidden');
              alert('Error during scan: ' + prog.lastError);
              return;
            }

            // Instantly reload new data saved by the background thread
            await runScan(true, 'smart', true);
            showCompletedScanBanner(prog);
          }
        } catch (err) {
          console.warn('Polling scan progress warning:', err);
        }
      }, 1000);
    }

    function _syncScanResponseAuth(auth) {
      if (!auth) return;
      if (auth.sessionToken) saveBrowserSessionSid(auth.sessionToken);
      if (auth.tokenValid && auth.activeAccount) saveBrowserAccountSession(auth.activeAccount);
      updateAuthUI(auth);
    }

    function _handleScanResponseDataLoaded(data) {
      globalScanData = data;
      if (typeof resetAllTablesFrontendPagination === 'function') {
        resetAllTablesFrontendPagination();
      }
      updateCacheAndSyncBadges(data);
      populateFilterDropdowns();
      refreshDashboardView();
    }

    function _handleNeedsLoginRedirect() {
      clearBrowserAccountSession();
      globalScanData = null;
      document.getElementById('auth-alert-banner').classList.remove('hidden');
      openLoginScreen(false);
    }

    async function _runLiveScanRequest(days, scanMode, pParams = null) {
      if (isLiveScanPolling) {
        const loading = document.getElementById('loading-banner');
        if (loading) {
          loading.classList.remove('hidden');
          loading.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        return;
      }

      const periodInfo = pParams || getSelectedPeriodParams();
      const numDays = periodInfo.days || Number(days) || 30;
      const querySuffix = periodInfo.querySuffix || '';
      renderScanProgressBanner({ active: true, mode: scanMode, days: numDays, elapsedSeconds: 0, pct: 8 }, scanMode, numDays);
      try {
        const res = await fetch(`/api/scan?days=${encodeURIComponent(numDays)}&cached=0&mode=${encodeURIComponent(scanMode)}&async=1${querySuffix}`, {
          headers: getBrowserAuthHeaders(),
          signal: AbortSignal.timeout(60000)
        });
        const data = await res.json();
        _syncScanResponseAuth(data.auth);
        if (!data.success) {
          isLiveScanPolling = false;
          setScanButtonsLocked(false, 'Scan Active');
          document.getElementById('loading-banner')?.classList.add('hidden');
          if (data.needsLogin) {
            _handleNeedsLoginRedirect();
          } else {
            alert('Error starting scan: ' + (data.error || 'Unknown error'));
          }
          return;
        }
        if (data.scanInProgress || (data.progress && data.progress.active)) {
          attachToRunningScanPolling(data.progress, numDays);
          return;
        }
        _handleScanResponseDataLoaded(data);
        setScanButtonsLocked(false, 'Scan Active');
        showCompletedScanBanner(data.scanProgress || null);
      } catch (e) {
        isLiveScanPolling = false;
        setScanButtonsLocked(false, 'Scan Active');
        document.getElementById('loading-banner')?.classList.add('hidden');
        alert('Network error while starting scan: ' + e.message);
      }
    }

    async function _runCachedScanRequest(days, scanMode, fromCompletedPoll, pParams = null) {
      const periodInfo = pParams || getSelectedPeriodParams();
      const numDays = periodInfo.days || Number(days) || 30;
      const querySuffix = periodInfo.querySuffix || '';
      const cacheTxt = document.getElementById('cache-status-text');
      const statusDot = document.getElementById('jt-status-dot');
      if (!isLiveScanPolling && cacheTxt && !fromCompletedPoll) {
        if (statusDot) statusDot.className = 'jt-dot jt-dot--busy';
        cacheTxt.textContent = `Loading ${periodInfo.label || (numDays + 'd')}…`;
      }

      try {
        const res = await fetch(`/api/scan?days=${encodeURIComponent(numDays)}&cached=1&mode=${encodeURIComponent(scanMode)}${querySuffix}`, {
          headers: getBrowserAuthHeaders(),
          signal: AbortSignal.timeout(30000)
        });
        const data = await res.json();
        _syncScanResponseAuth(data.auth);
        if (!data.success) {
          if (data.needsLogin) {
            _handleNeedsLoginRedirect();
          } else if (data.noCacheYet) {
            if (data.scanProgress && data.scanProgress.active) {
              attachToRunningScanPolling(data.scanProgress, numDays);
              return;
            }
            return await _runLiveScanRequest(numDays, 'smart', periodInfo);
          } else {
            alert('Error loading data: ' + (data.error || 'Unknown error'));
          }
          return;
        }

        _handleScanResponseDataLoaded(data);
        if (data.scanProgress && data.scanProgress.active) {
          attachToRunningScanPolling(data.scanProgress, numDays);
        } else if (!fromCompletedPoll) {
          setScanButtonsLocked(false, 'Scan Active');
        }
      } catch (e) {
        console.error('Cache read error:', e);
      }
    }

    async function runScan(useCache = true, scanMode = 'smart', fromCompletedPoll = false) {
      const pParams = getSelectedPeriodParams();
      if (!useCache) {
        await _runLiveScanRequest(pParams.days, scanMode, pParams);
        return;
      }
      await _runCachedScanRequest(pParams.days, scanMode, fromCompletedPoll, pParams);
    }

    // =========================================================================
    // PROJECT VISIBILITY & FILTERS
    // =========================================================================
    function isProjectVisibleByToggles(p) {
      const showNoBilling = document.getElementById('toggle-show-no-billing').checked;
      const showNoAi = document.getElementById('toggle-show-no-ai').checked;

      const isAiStudioWithData = Boolean(
        p.isAiStudioProject && (
          p.aiActive || (p.inferenceRequests || 0) > 0 || (p.totalRequests || 0) > 0 || (p.apiKeys || []).length > 0
        )
      );
      // Not verified because Google rate-limited the scan: always visible, never hidden as "no billing / no AI"
      if (p.transientError) return true;
      if (p.skippedNoBilling || !p.billingEnabled) {
        if (isAiStudioWithData) return true;
        return showNoBilling;
      }
      if (p.scanStatus === 'NO_PERMISSIONS_403') return true;
      if (!p.aiActive) return showNoAi;
      return true;
    }

    function onVisibilityTogglesChanged() {
      populateFilterDropdowns();
      refreshDashboardView();
    }

    function populateFilterDropdowns() {
      if (!globalScanData || !globalScanData.projects) return;
      const allProjects = globalScanData.projects;

      const hiddenNoAi = allProjects.filter(p => p.billingEnabled && !p.aiActive && p.scanStatus !== 'NO_PERMISSIONS_403').length;
      const hiddenNoBilling = allProjects.filter(p => (p.skippedNoBilling || !p.billingEnabled) && !(p.isAiStudioProject && (p.aiActive || (p.apiKeys || []).length > 0))).length;
      document.getElementById('count-hidden-no-ai').textContent = hiddenNoAi;
      document.getElementById('count-hidden-no-billing').textContent = hiddenNoBilling;

      const visibleProjects = allProjects.filter(isProjectVisibleByToggles);

      const projSel = document.getElementById('filter-project');
      let savedProj = 'ALL';
      try {
        savedProj = sessionStorage.getItem(SS_UI_PROJ_KEY) || 'ALL';
      } catch (err) {
        ignoreStorageError(err);
      }
      const prevProj = (projSel.value && projSel.value !== 'ALL') ? projSel.value : savedProj;
      setSafeHtml(projSel, `<option value="ALL">All visible projects (${visibleProjects.length})</option>`);
      visibleProjects.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.projectId;
        const perms = p.permissions || {};
        const monArea = (perms.areas && perms.areas.monitoring) || {};
        if ((p.skippedNoBilling || !p.billingEnabled) && p.isAiStudioProject) {
          opt.textContent = `${p.name} (${p.projectId}) — [AI Studio Free-Tier]`;
        } else if (p.skippedNoBilling) {
          opt.textContent = `${p.name} — [No Billing]`;
        } else if (p.scanStatus === 'NO_PERMISSIONS_403' || monArea.granted === false) {
          opt.textContent = `${p.name} (${p.projectId}) — [403 Access Denied]`;
        } else {
          opt.textContent = `${p.name} (${p.projectId}) • ${fmtUsd(p.estimatedCostUsd)}`;
        }
        projSel.appendChild(opt);
      });
      if ([...projSel.options].some(o => o.value === prevProj)) {
        projSel.value = prevProj;
      } else {
        projSel.value = 'ALL';
      }

      const projMenu = document.getElementById('jt-m-projects');
      if (projMenu) {
        const itemsHtml = [
          `<button type="button" class="jt-menu-item" role="menuitemradio" data-proj-val="ALL" aria-checked="${projSel.value === 'ALL' ? 'true' : 'false'}" data-jt-click="selectHeaderProjectFilter('ALL')">
            <span>All visible projects</span>
            <span class="jt-menu-meta">${visibleProjects.length}</span>
          </button>`
        ];
        if (visibleProjects.length > 0) {
          itemsHtml.push('<div class="jt-menu-sep"></div>');
          visibleProjects.forEach(p => {
            const checked = projSel.value === p.projectId ? 'true' : 'false';
            const perms = p.permissions || {};
            const monArea = (perms.areas && perms.areas.monitoring) || {};
            let metaTxt = fmtUsd(p.estimatedCostUsd);
            if ((p.skippedNoBilling || !p.billingEnabled) && p.isAiStudioProject) {
              metaTxt = 'AI Studio';
            } else if (p.skippedNoBilling) {
              metaTxt = 'No Billing';
            } else if (p.scanStatus === 'NO_PERMISSIONS_403' || monArea.granted === false) {
              metaTxt = '403';
            }
            itemsHtml.push(
              `<button type="button" class="jt-menu-item" role="menuitemradio" data-proj-val="${escapeHtml(p.projectId)}" aria-checked="${checked}" data-jt-click="selectHeaderProjectFilter(${jsArg(p.projectId)})">
                <span class="truncate max-w-[200px]">${escapeHtml(p.name || p.projectId)}</span>
                <span class="jt-menu-meta">${escapeHtml(metaTxt)}</span>
              </button>`
            );
          });
        }
        setSafeHtml(projMenu, itemsHtml.join(''));
      }
      syncHeaderScopeUi();

      populateCredentialAndModelDropdowns();
    }

    function populateCredentialAndModelDropdowns() {
      if (!globalScanData || !globalScanData.projects) return;
      const selProj = document.getElementById('filter-project').value;
      const selType = document.getElementById('filter-cred-type').value;

      const credSel = document.getElementById('filter-cred-id');
      const prevCred = credSel.value || 'ALL';
      setSafeHtml(credSel, `<option value="ALL">All Keys & SAs</option>`);

      const modelSel = document.getElementById('filter-model');
      const prevModel = modelSel.value || 'ALL';
      setSafeHtml(modelSel, `<option value="ALL">All AI Models</option>`);

      const credsItems = [];
      const modelsMap = new Map();

      (globalScanData.projects || []).forEach(p => {
        if (!isProjectVisibleByToggles(p)) return;
        if (selProj !== 'ALL' && p.projectId !== selProj) return;

        (p.credentialsUsage || []).forEach(c => {
          const cType = c.resolvedType || 'OAUTH_CLIENT';
          if (selType !== 'ALL' && cType !== selType) return;
          credsItems.push({
            key: `${p.projectId}||${c.credentialId}`,
            projectId: p.projectId,
            name: c.resolvedName || c.credentialId,
            type: cType,
            costUsd: c.estimatedCostUsd || 0,
            infReqs: c.inferenceRequests || 0,
            totalReqs: c.requests || 0
          });
        });

        (p.models || []).forEach(m => {
          const prev = modelsMap.get(m.modelId) || { costUsd: 0, tokens: 0 };
          prev.costUsd += (m.costUsd || 0);
          prev.tokens += (m.totalTokens || 0);
          modelsMap.set(m.modelId, prev);
        });
      });

      credsItems.sort((a, b) => (b.costUsd - a.costUsd) || (b.infReqs - a.infReqs));
      credsItems.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.key;
        opt.textContent = `${item.name} (${item.projectId}) — ${fmtUsd(item.costUsd)}`;
        credSel.appendChild(opt);
      });

      if ([...credSel.options].some(o => o.value === prevCred)) credSel.value = prevCred;

      const sortedModels = [...modelsMap.entries()].sort((a, b) => b[1].costUsd - a[1].costUsd);
      sortedModels.forEach(([mId, info]) => {
        const opt = document.createElement('option');
        opt.value = mId;
        opt.textContent = `${mId} — ${fmtUsd(info.costUsd)}`;
        modelSel.appendChild(opt);
      });

      if ([...modelSel.options].some(o => o.value === prevModel)) modelSel.value = prevModel;
    }

    function onProjectFilterChanged() {
      try {
        sessionStorage.setItem(SS_UI_PROJ_KEY, document.getElementById('filter-project').value || 'ALL');
      } catch (err) {
        ignoreStorageError(err);
      }
      if (typeof resetAllTablesFrontendPagination === 'function') resetAllTablesFrontendPagination();
      syncHeaderScopeUi();
      populateCredentialAndModelDropdowns();
      refreshDashboardView();
    }

    function onCredTypeFilterChanged() {
      if (typeof resetAllTablesFrontendPagination === 'function') resetAllTablesFrontendPagination();
      document.getElementById('filter-cred-id').value = 'ALL';
      populateCredentialAndModelDropdowns();
      refreshDashboardView();
    }

    function onSpecificCredChanged() {
      if (typeof resetAllTablesFrontendPagination === 'function') resetAllTablesFrontendPagination();
      if (document.getElementById('filter-cred-id').value !== 'ALL') {
        document.getElementById('filter-model').value = 'ALL';
      }
      refreshDashboardView();
    }

    function onModelFilterChanged() {
      if (typeof resetAllTablesFrontendPagination === 'function') resetAllTablesFrontendPagination();
      if (document.getElementById('filter-model').value !== 'ALL') {
        document.getElementById('filter-cred-id').value = 'ALL';
        document.getElementById('filter-cred-type').value = 'ALL';
      }
      refreshDashboardView();
    }

    function onFiltersChanged() {
      if (typeof resetAllTablesFrontendPagination === 'function') resetAllTablesFrontendPagination();
      refreshDashboardView();
    }

    function resetAllFilters() {
      try {
        sessionStorage.setItem(SS_UI_PROJ_KEY, 'ALL');
      } catch (err) {
        ignoreStorageError(err);
      }
      if (typeof resetAllTablesFrontendPagination === 'function') resetAllTablesFrontendPagination();
      document.getElementById('toggle-show-no-ai').checked = false;
      document.getElementById('toggle-show-no-billing').checked = false;
      document.getElementById('filter-only-active').checked = false;
      document.getElementById('filter-project').value = 'ALL';
      document.getElementById('filter-cred-type').value = 'ALL';
      populateFilterDropdowns();
      document.getElementById('filter-cred-id').value = 'ALL';
      document.getElementById('filter-model').value = 'ALL';
      document.getElementById('filter-exclude-system').checked = true;
      document.getElementById('search-input').value = '';
      syncHeaderScopeUi();
      refreshDashboardView();
      updateFilterbarUi();
    }
    window.resetAllFilters = resetAllFilters;

    const VIEW_APPLICABLE_FILTERS = {
      'dashboard':   ['filter-project', 'days-select', 'filter-cred-type', 'filter-cred-id', 'filter-model', 'toggle-show-no-ai', 'toggle-show-no-billing', 'filter-exclude-system', 'search-input'],
      'daily':       ['filter-project', 'days-select', 'filter-cred-type', 'filter-cred-id', 'filter-model', 'filter-only-active', 'toggle-show-no-ai', 'toggle-show-no-billing', 'filter-exclude-system', 'search-input'],
      'credentials': ['filter-project', 'days-select', 'filter-cred-type', 'filter-cred-id', 'filter-only-active', 'toggle-show-no-ai', 'toggle-show-no-billing', 'search-input'],
      'models':      ['filter-project', 'days-select', 'filter-model', 'toggle-show-no-ai', 'toggle-show-no-billing', 'search-input'],
      'projects':    ['filter-project', 'days-select', 'filter-only-active', 'toggle-show-no-ai', 'toggle-show-no-billing', 'search-input'],
      'users':       ['filter-project', 'days-select', 'toggle-show-no-ai', 'toggle-show-no-billing', 'search-input'],
      'ai-tools':    ['filter-project', 'days-select', 'toggle-show-no-ai', 'toggle-show-no-billing', 'search-input'],
      'features':    ['filter-project', 'days-select', 'toggle-show-no-ai', 'toggle-show-no-billing', 'search-input'],
      'security':    ['filter-project', 'days-select', 'toggle-show-no-ai', 'toggle-show-no-billing', 'search-input'],
      'sync':        ['days-select', 'search-input'],
      'pricing':     []
    };
    window.VIEW_APPLICABLE_FILTERS = VIEW_APPLICABLE_FILTERS;

    function syncFilterbarForView(tab) {
      const activeTab = tab || currentTab || 'dashboard';
      const applicableList = Object.prototype.hasOwnProperty.call(VIEW_APPLICABLE_FILTERS, activeTab)
        ? VIEW_APPLICABLE_FILTERS[activeTab]
        : VIEW_APPLICABLE_FILTERS['dashboard'];
      const applicable = new Set(applicableList);

      const filterControls = [
        'filter-cred-type',
        'filter-cred-id',
        'filter-model',
        'filter-only-active',
        'toggle-show-no-ai',
        'toggle-show-no-billing',
        'filter-exclude-system',
        'search-input'
      ];

      filterControls.forEach(id => {
        const isApp = applicable.has(id);
        const el = document.getElementById(id);
        if (el) {
          el.disabled = !isApp;
          el.setAttribute('aria-disabled', isApp ? 'false' : 'true');
        }
        document.querySelectorAll(`[data-filter-key="${id}"]`).forEach(wrap => {
          wrap.classList.toggle('is-disabled', !isApp);
        });
        document.querySelectorAll(`[data-filter-na-for="${id}"]`).forEach(na => {
          na.classList.toggle('hidden', isApp);
        });
      });

      const projApplicable = applicable.has('filter-project');
      document.querySelectorAll('[data-jt-menu="jt-m-projects"]').forEach(btn => {
        btn.disabled = !projApplicable;
        btn.setAttribute('aria-disabled', projApplicable ? 'false' : 'true');
        btn.classList.toggle('opacity-60', !projApplicable);
      });

      const rangeApplicable = applicable.has('days-select');
      document.querySelectorAll('[data-jt-menu="jt-m-range"]').forEach(btn => {
        btn.disabled = !rangeApplicable;
        btn.setAttribute('aria-disabled', rangeApplicable ? 'false' : 'true');
        btn.classList.toggle('opacity-60', !rangeApplicable);
      });
    }
    window.syncFilterbarForView = syncFilterbarForView;

    function updateFilterbarUi() {
      const activeTab = currentTab || 'dashboard';
      const applicableList = Object.prototype.hasOwnProperty.call(VIEW_APPLICABLE_FILTERS, activeTab)
        ? VIEW_APPLICABLE_FILTERS[activeTab]
        : VIEW_APPLICABLE_FILTERS['dashboard'];
      const applicable = new Set(applicableList);

      const activeChips = [];

      const projEl = document.getElementById('filter-project');
      const projVal = projEl ? projEl.value : 'ALL';
      const projNonDefault = Boolean(projVal && projVal !== 'ALL');
      if (applicable.has('filter-project') && projNonDefault) {
        activeChips.push({ key: 'filter-project', label: 'Project: ' + projVal });
      }

      const credTypeEl = document.getElementById('filter-cred-type');
      const credTypeVal = credTypeEl ? credTypeEl.value : 'ALL';
      if (applicable.has('filter-cred-type') && credTypeVal && credTypeVal !== 'ALL') {
        activeChips.push({ key: 'filter-cred-type', label: 'Type: ' + credTypeVal });
      }

      const credIdEl = document.getElementById('filter-cred-id');
      const credIdVal = credIdEl ? credIdEl.value : 'ALL';
      if (applicable.has('filter-cred-id') && credIdVal && credIdVal !== 'ALL') {
        activeChips.push({ key: 'filter-cred-id', label: 'Key/SA: ' + credIdVal });
      }

      const modelEl = document.getElementById('filter-model');
      const modelVal = modelEl ? modelEl.value : 'ALL';
      if (applicable.has('filter-model') && modelVal && modelVal !== 'ALL') {
        activeChips.push({ key: 'filter-model', label: 'Model: ' + modelVal });
      }

      const onlyActiveEl = document.getElementById('filter-only-active');
      if (applicable.has('filter-only-active') && onlyActiveEl && onlyActiveEl.checked === true) {
        activeChips.push({ key: 'filter-only-active', label: 'Active traffic only (>0 calls)' });
      }

      const showNoAiEl = document.getElementById('toggle-show-no-ai');
      if (applicable.has('toggle-show-no-ai') && showNoAiEl && showNoAiEl.checked === true) {
        activeChips.push({ key: 'toggle-show-no-ai', label: 'Include projects without AI' });
      }

      const showNoBillingEl = document.getElementById('toggle-show-no-billing');
      if (applicable.has('toggle-show-no-billing') && showNoBillingEl && showNoBillingEl.checked === true) {
        activeChips.push({ key: 'toggle-show-no-billing', label: 'Include projects without Billing' });
      }

      const excludeSysEl = document.getElementById('filter-exclude-system');
      if (applicable.has('filter-exclude-system') && excludeSysEl && excludeSysEl.checked === false) {
        activeChips.push({ key: 'filter-exclude-system', label: 'System callers included' });
      }

      const searchEl = document.getElementById('search-input');
      const searchVal = (searchEl && searchEl.value) ? searchEl.value.trim() : '';
      if (applicable.has('search-input') && searchVal !== '') {
        activeChips.push({ key: 'search-input', label: 'Search: "' + searchVal + '"' });
      }

      const countEl = document.getElementById('jt-filterbar-count');
      if (countEl) {
        if (activeChips.length > 0) {
          countEl.textContent = String(activeChips.length);
          countEl.classList.remove('hidden');
        } else {
          countEl.textContent = '0';
          countEl.classList.add('hidden');
        }
      }

      const resetBtn = document.getElementById('jt-filterbar-reset-btn');
      if (resetBtn) {
        const hasAnyFilterActive = projNonDefault || activeChips.length > 0
          || Boolean(credTypeVal && credTypeVal !== 'ALL')
          || Boolean(credIdVal && credIdVal !== 'ALL')
          || Boolean(modelVal && modelVal !== 'ALL')
          || Boolean(onlyActiveEl && onlyActiveEl.checked === true)
          || Boolean(showNoAiEl && showNoAiEl.checked === true)
          || Boolean(showNoBillingEl && showNoBillingEl.checked === true)
          || Boolean(excludeSysEl && excludeSysEl.checked === false)
          || Boolean(searchVal !== '');
        resetBtn.classList.toggle('hidden', !hasAnyFilterActive);
      }

      const chipsEl = document.getElementById('jt-filterbar-chips');
      if (chipsEl) {
        if (activeChips.length === 0) {
          setSafeHtml(chipsEl, '');
          chipsEl.classList.add('hidden');
        } else {
          chipsEl.classList.remove('hidden');
          const html = activeChips.map(c =>
            `<span class="jt-filter-chip" data-chip-key="${escapeHtml(c.key)}">` +
              `<span class="jt-filter-chip__label">${escapeHtml(c.label)}</span>` +
              `<button type="button" class="jt-filter-chip__remove" data-jt-click="clearFilterbarChip(${jsArg(c.key)})" aria-label="Remove filter ${escapeHtml(c.label)}" title="Remove filter">✕</button>` +
            `</span>`
          ).join('');
          setSafeHtml(chipsEl, html);
        }
      }
    }
    window.updateFilterbarUi = updateFilterbarUi;

    function clearFilterbarChip(filterKey) {
      if (filterKey === 'filter-project') {
        selectHeaderProjectFilter('ALL');
      } else if (filterKey === 'filter-cred-type') {
        const el = document.getElementById('filter-cred-type');
        if (el) el.value = 'ALL';
        onCredTypeFilterChanged();
      } else if (filterKey === 'filter-cred-id') {
        const el = document.getElementById('filter-cred-id');
        if (el) el.value = 'ALL';
        onSpecificCredChanged();
      } else if (filterKey === 'filter-model') {
        const el = document.getElementById('filter-model');
        if (el) el.value = 'ALL';
        onModelFilterChanged();
      } else if (filterKey === 'filter-only-active') {
        const el = document.getElementById('filter-only-active');
        if (el) el.checked = false;
        renderCurrentTab();
      } else if (filterKey === 'toggle-show-no-ai') {
        const el = document.getElementById('toggle-show-no-ai');
        if (el) el.checked = false;
        onVisibilityTogglesChanged();
      } else if (filterKey === 'toggle-show-no-billing') {
        const el = document.getElementById('toggle-show-no-billing');
        if (el) el.checked = false;
        onVisibilityTogglesChanged();
      } else if (filterKey === 'filter-exclude-system') {
        const el = document.getElementById('filter-exclude-system');
        if (el) el.checked = true;
        onFiltersChanged();
      } else if (filterKey === 'search-input') {
        const el = document.getElementById('search-input');
        if (el) el.value = '';
        renderCurrentTab();
      }
      updateFilterbarUi();
    }
    window.clearFilterbarChip = clearFilterbarChip;

    function selectSingleCredentialFilter(projectId, credentialId) {
      document.getElementById('filter-project').value = projectId;
      try {
        sessionStorage.setItem(SS_UI_PROJ_KEY, projectId || 'ALL');
      } catch (err) {
        ignoreStorageError(err);
      }
      document.getElementById('filter-cred-type').value = 'ALL';
      syncHeaderScopeUi();
      populateCredentialAndModelDropdowns();
      const targetKey = `${projectId}||${credentialId}`;
      const credSel = document.getElementById('filter-cred-id');
      if ([...credSel.options].some(o => o.value === targetKey)) credSel.value = targetKey;
      document.getElementById('filter-model').value = 'ALL';
      refreshDashboardView();
    }

    function selectSingleProjectFilter(projectId) {
      const projSel = document.getElementById('filter-project');
      projSel.value = (projSel.value === projectId) ? 'ALL' : projectId;
      try {
        sessionStorage.setItem(SS_UI_PROJ_KEY, projSel.value || 'ALL');
      } catch (err) {
        ignoreStorageError(err);
      }
      document.getElementById('filter-cred-type').value = 'ALL';
      syncHeaderScopeUi();
      populateCredentialAndModelDropdowns();
      document.getElementById('filter-cred-id').value = 'ALL';
      document.getElementById('filter-model').value = 'ALL';
      refreshDashboardView();
    }

    function selectSingleModelFilter(projectId, modelId) {
      if (projectId) document.getElementById('filter-project').value = projectId;
      document.getElementById('filter-cred-type').value = 'ALL';
      syncHeaderScopeUi();
      populateCredentialAndModelDropdowns();
      document.getElementById('filter-cred-id').value = 'ALL';
      document.getElementById('filter-model').value = modelId;
      refreshDashboardView();
    }

    // =========================================================================
    // AGGREGAZIONE DATI FILTRATI
    // =========================================================================
    function _addDayPointToDailyMap(dailyMap, dayStr, src) {
      const d = dailyMap[dayStr] || {
        date: dayStr, requests: 0, inferenceRequests: 0, systemRequests: 0, errors429: 0,
        inputTokens: 0, outputTokens: 0, cachedTokens: 0, tokens: 0, costUsd: 0
      };
      d.requests += (src.requests || 0);
      d.inferenceRequests += (src.inferenceRequests || 0);
      d.systemRequests += (src.systemRequests || 0);
      d.errors429 += (src.errors429 || 0);
      d.inputTokens += (src.inputTokens || 0);
      d.outputTokens += (src.outputTokens || 0) + (src.thinkingTokens || 0);
      d.cachedTokens += (src.cachedTokens || 0);
      d.tokens += (src.tokens || 0);
      d.costUsd += (src.costUsd || 0);
      dailyMap[dayStr] = d;
    }

    function _addServiceCostAndRequests(acc, service, cost, reqs) {
      if (service === 'generativelanguage.googleapis.com') {
        acc.geminiCost += cost;
        acc.geminiApiRequests += reqs;
      } else if (service === 'aiplatform.googleapis.com') {
        acc.vertexCost += cost;
        acc.vertexRequests += reqs;
      } else {
        acc.otherAiCost += cost;
        acc.vertexRequests += reqs;
      }
    }

    function _aggregateProjectModelFilter(acc, p, selModel) {
      (p.models || []).forEach(m => {
        if (m.modelId !== selModel) return;
        const mCost = m.costUsd || 0;
        const mInv = m.invocations || 0;
        acc.totalCost += mCost;
        acc.totalGrossCost += (m.grossCostUsd || mCost);
        acc.totalCacheSavings += (m.cacheSavingsUsd || 0);
        _addServiceCostAndRequests(acc, m.service, mCost, mInv);

        acc.infRequests += mInv;
        acc.totalRequests += mInv;
        acc.inputTokens += (m.inputTokens || 0);
        acc.outputTokens += (m.outputTokens || 0) + (m.thinkingTokens || 0);
        acc.thinkingTokens += (m.thinkingTokens || 0);
        acc.cachedTokens += (m.cachedTokens || 0);
        acc.totalTokens += (m.totalTokens || 0);

        Object.entries(m.dailySeries || {}).forEach(([dayStr, dVal]) => _addDayPointToDailyMap(acc.dailyMap, dayStr, dVal));
        acc.credBreakdown.push({
          label: `${m.modelId} (${p.projectId})`,
          costUsd: mCost,
          requests: mInv,
          tokens: m.totalTokens || 0,
          type: 'MODEL'
        });
      });
    }

    function _aggregateProjectCredentialFilter(acc, p, selType, selCred, excludeSys) {
      (p.credentialsUsage || []).forEach(c => {
        const cType = c.resolvedType || 'OAUTH_CLIENT';
        const compKey = `${p.projectId}||${c.credentialId}`;
        if (selType !== 'ALL' && cType !== selType) return;
        if (selCred !== 'ALL' && compKey !== selCred) return;

        const cCost = c.estimatedCostUsd || 0;
        const cInf = c.inferenceRequests || 0;
        acc.totalCost += cCost;
        acc.totalGrossCost += (c.grossCostUsd || cCost);
        acc.totalCacheSavings += (c.cacheSavingsUsd || 0);
        _addServiceCostAndRequests(acc, c.service, cCost, cInf);

        acc.infRequests += cInf;
        acc.sysRequests += (c.systemRequests || 0);
        acc.totalRequests += (c.requests || 0);
        acc.errors429 += (c.errors429 || 0);
        acc.inputTokens += (c.inputTokens || 0);
        acc.outputTokens += (c.outputTokens || 0);
        acc.cachedTokens += (c.cachedTokens || 0);
        acc.totalTokens += (c.totalTokens || 0);

        Object.entries(c.dailySeries || {}).forEach(([dayStr, dVal]) => _addDayPointToDailyMap(acc.dailyMap, dayStr, dVal));
        acc.credBreakdown.push({
          label: `${c.resolvedName || c.credentialId}`,
          projectId: p.projectId,
          costUsd: cCost,
          requests: excludeSys ? cInf : (c.requests || 0),
          tokens: c.totalTokens || 0,
          type: cType
        });
      });
    }

    function _aggregateProjectFullTotals(acc, p, excludeSys) {
      acc.totalCost += (p.estimatedCostUsd || 0);
      acc.vertexCost += (p.vertexCostUsd || 0);
      acc.geminiCost += (p.geminiCostUsd || 0);
      acc.otherAiCost += (p.otherAiCostUsd || 0);
      const pAiGross = (p.vertexGrossCostUsd || p.vertexCostUsd || 0) + (p.geminiGrossCostUsd || p.geminiCostUsd || 0) + (p.otherAiGrossCostUsd || p.otherAiCostUsd || 0);
      const pAiSav = (p.vertexCacheSavingsUsd || 0) + (p.geminiCacheSavingsUsd || 0) + (p.otherAiCacheSavingsUsd || 0);
      acc.totalGrossCost += pAiGross;
      acc.totalCacheSavings += pAiSav;
      acc.infraGrossCost += (p.infraGrossCostUsd || 0);
      acc.infraSavings += (p.infraSavingsUsd || 0);
      acc.infraCost += (p.infraCostUsd || 0);
      acc.excludedNonAiInfraCost += (p.excludedNonAiInfraCostUsd || (p.finopsExtended && p.finopsExtended.excludedNonAiInfraCostUsd) || 0);
      acc.totalBillGross += (p.totalBillGrossUsd || (pAiGross + (p.infraGrossCostUsd || 0)));
      acc.totalBillSavings += (p.totalBillSavingsUsd || (pAiSav + (p.infraSavingsUsd || 0)));
      acc.totalBillCost += (p.totalBillCostUsd || ((p.estimatedCostUsd || 0) + (p.infraCostUsd || 0)));
      acc.infRequests += (p.inferenceRequests || 0);
      acc.sysRequests += (p.systemRequests || 0);
      acc.totalRequests += (p.totalRequests || 0);
      acc.vertexRequests += (p.vertexRequests || 0);
      acc.geminiApiRequests += (p.geminiApiRequests || 0);
      acc.errors429 += (p.errors429 || 0);
      acc.inputTokens += (p.inputTokens || 0);
      acc.outputTokens += (p.outputTokens || 0) + (p.thinkingTokens || 0);
      acc.thinkingTokens += (p.thinkingTokens || 0);
      acc.cachedTokens += (p.cachedTokens || 0);
      acc.totalTokens += (p.totalTokens || 0);

      Object.entries(p.dailySeries || {}).forEach(([dayStr, dVal]) => _addDayPointToDailyMap(acc.dailyMap, dayStr, dVal));

      (p.credentialsUsage || []).forEach(c => {
        if ((c.estimatedCostUsd || 0) > 0 || (c.inferenceRequests || 0) > 0 || (!excludeSys && (c.requests || 0) > 0)) {
          acc.credBreakdown.push({
            label: `${c.resolvedName || c.credentialId}`,
            projectId: p.projectId,
            costUsd: c.estimatedCostUsd || 0,
            requests: excludeSys ? (c.inferenceRequests || 0) : (c.requests || 0),
            tokens: c.totalTokens || 0,
            type: c.resolvedType || 'OAUTH_CLIENT'
          });
        }
      });
    }

    function getFilteredAggregation() {
      const selProj = document.getElementById('filter-project').value;
      // Un filtro disabilitato (non applicabile alla vista) viene ignorato: valore neutro.
      const _fv = (id, neutral) => { const el = document.getElementById(id); return (!el || el.disabled) ? neutral : el.value; };
      const selType = _fv('filter-cred-type', 'ALL');
      const selCred = _fv('filter-cred-id', 'ALL');
      const selModel = _fv('filter-model', 'ALL');
      const _exEl = document.getElementById('filter-exclude-system');
      const excludeSys = (!_exEl || _exEl.disabled) ? true : _exEl.checked;

      const acc = {
        dailyMap: {},
        credBreakdown: [],
        totalCost: 0, vertexCost: 0, geminiCost: 0, otherAiCost: 0,
        totalGrossCost: 0, totalCacheSavings: 0,
        infraGrossCost: 0, infraSavings: 0, infraCost: 0, excludedNonAiInfraCost: 0,
        totalBillGross: 0, totalBillSavings: 0, totalBillCost: 0,
        infRequests: 0, sysRequests: 0, totalRequests: 0, errors429: 0,
        vertexRequests: 0, geminiApiRequests: 0,
        inputTokens: 0, outputTokens: 0, thinkingTokens: 0, cachedTokens: 0, totalTokens: 0,
        matchedProjects: 0, matchedApiKeys: 0, matchedSa: 0,
        matchedDeployedRes: 0, matchedFeatures: 0, matchedModelArmorProjs: 0
      };

      (globalScanData.projects || []).forEach(p => {
        if (!isProjectVisibleByToggles(p)) return;
        if (selProj !== 'ALL' && p.projectId !== selProj) return;
        acc.matchedProjects++;
        acc.matchedApiKeys += (p.apiKeys || []).length;
        acc.matchedSa += (p.serviceAccounts || []).length;
        acc.matchedDeployedRes += (p.deployedAiResources || []).length;
        acc.matchedFeatures += (p.vertexFeatures || []).length;
        if (p.modelArmorEnabled) acc.matchedModelArmorProjs++;

        if (selModel !== 'ALL') {
          _aggregateProjectModelFilter(acc, p, selModel);
        } else if (selCred !== 'ALL' || selType !== 'ALL') {
          _aggregateProjectCredentialFilter(acc, p, selType, selCred, excludeSys);
        } else {
          _aggregateProjectFullTotals(acc, p, excludeSys);
        }
      });

      if (Object.keys(acc.dailyMap).length === 0 && globalScanData) {
        const pStart = globalScanData.periodStart || (globalScanData.periodRange && globalScanData.periodRange.startDate) || '';
        const pEnd = globalScanData.periodEnd || (globalScanData.periodRange && globalScanData.periodRange.endDate) || pStart;
        if (pStart) {
          _addDayPointToDailyMap(acc.dailyMap, pStart, {});
          if (pEnd && pEnd !== pStart) {
            _addDayPointToDailyMap(acc.dailyMap, pEnd, {});
          }
        }
      }

      const timeline = Object.keys(acc.dailyMap).sort().map(k => {
        const item = acc.dailyMap[k];
        item.costUsd = Number(item.costUsd.toFixed(4));
        return item;
      });

      acc.credBreakdown.sort((a, b) => (b.costUsd - a.costUsd) || (b.requests - a.requests));

      return {
        selProj, selType, selCred, selModel, excludeSys,
        totalCost: acc.totalCost, vertexCost: acc.vertexCost, geminiCost: acc.geminiCost, otherAiCost: acc.otherAiCost,
        totalGrossCost: acc.totalGrossCost, totalCacheSavings: acc.totalCacheSavings,
        infraGrossCost: acc.infraGrossCost, infraSavings: acc.infraSavings, infraCost: acc.infraCost, excludedNonAiInfraCost: acc.excludedNonAiInfraCost,
        totalBillGross: acc.totalBillGross, totalBillSavings: acc.totalBillSavings, totalBillCost: acc.totalBillCost,
        infRequests: acc.infRequests, sysRequests: acc.sysRequests, totalRequests: acc.totalRequests,
        vertexRequests: acc.vertexRequests, geminiApiRequests: acc.geminiApiRequests,
        displayedRequests: excludeSys ? acc.infRequests : acc.totalRequests,
        errors429: acc.errors429, inputTokens: acc.inputTokens, outputTokens: acc.outputTokens, thinkingTokens: acc.thinkingTokens, cachedTokens: acc.cachedTokens, totalTokens: acc.totalTokens,
        matchedProjects: acc.matchedProjects, matchedApiKeys: acc.matchedApiKeys, matchedSa: acc.matchedSa,
        matchedDeployedRes: acc.matchedDeployedRes, matchedFeatures: acc.matchedFeatures, matchedModelArmorProjs: acc.matchedModelArmorProjs,
        timeline, credBreakdown: acc.credBreakdown
      };
    }

    // =========================================================================
    // AGGIORNAMENTO DASHBOARD (KPI + GRAFICI + TABELLE)
    // =========================================================================
    function refreshDashboardView() {
      syncFilterbarForView(currentTab);
      updateFilterbarUi();
      if (!globalScanData) return;
      const agg = getFilteredAggregation();
      const s = globalScanData.summary || {};

      const badge = document.getElementById('active-filter-badge');
      const parts = [];
      if (agg.selProj !== 'ALL') parts.push(`Project: ${escapeHtml(agg.selProj)}`);
      if (agg.selType !== 'ALL') parts.push(`Type: ${escapeHtml(agg.selType)}`);
      if (agg.selCred !== 'ALL') parts.push(`Filtered Key/SA`);
      if (agg.selModel !== 'ALL') parts.push(`Model: ${escapeHtml(agg.selModel)}`);

      if (badge) {
        if (parts.length > 0) {
          setSafeHtml(badge, `${parts.join(' • ')} <button type="button" data-jt-click="resetAllFilters()" class="ml-1.5 text-blue-900 font-extrabold hover:underline cursor-pointer"><svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg></button>`);
        } else {
          setSafeHtml(badge, '');
        }
        badge.classList.add('hidden');
        badge.hidden = true;
      }

      document.getElementById('kpi-total-cost').textContent = fmtUsd(agg.totalCost);
      const eurEl = document.getElementById('kpi-total-cost-eur');
      if (eurEl) eurEl.textContent = `(${fmtEur(agg.totalCost)})`;
      setHeaderTotalCostDisplay(agg.totalCost);
      syncHeaderScopeUi();
      syncHeaderRangeUi();

      const recLine = document.getElementById('kpi-bill-reconciliation-line');
      if (recLine) {
        const exclVal = agg.excludedNonAiInfraCost || s.excludedNonAiInfraCostUsd || (s.finopsExtended && s.finopsExtended.excludedNonAiInfraCostUsd) || 0;
        const exclBadge = exclVal > 0 ? ` · ${toneBadge('green', `Excluded Non-AI SQL: -${fmtUsd(exclVal)}`, { chip: true, mono: true, title: 'Cloud SQL on projects with 0 AI calls excluded from AI TCO' })}` : '';
        if ((agg.infraCost || 0) > 0) {
          setSafeHtml(recLine, `<span class="text-[#0F2A4A] font-extrabold">Total Invoice (11 srv): ${fmtEur(agg.totalBillCost)}</span> (${fmtUsd(agg.totalBillCost)}) · List: <b>${fmtEur(agg.totalBillGross)}</b> · Discounts: <b class="text-emerald-700">-${fmtEur(agg.totalBillSavings)}</b>${exclBadge}`);
        } else {
          setSafeHtml(recLine, `Gross AI: <b>${fmtEur(agg.totalGrossCost)}</b> · Cache Savings: <b class="text-emerald-700">-${fmtEur(agg.totalCacheSavings)}</b>${exclBadge}`);
        }
      }

      const activeDaysCount = agg.timeline.filter(d => d.costUsd > 0 || d.inferenceRequests > 0).length;
      const avgDaily = activeDaysCount > 0 ? (agg.totalCost / activeDaysCount) : 0;
      document.getElementById('kpi-daily-avg-cost').textContent = `Avg: ${fmtUsd(avgDaily)}/day`;
      const vCombinedUsd = (agg.vertexCost || 0) + (agg.otherAiCost || 0);
      document.getElementById('kpi-vertex-cost').textContent = `${fmtEur(vCombinedUsd)} (${fmtUsd(vCombinedUsd)})`;
      document.getElementById('kpi-gemini-cost').textContent = `${fmtEur(agg.geminiCost)} (${fmtUsd(agg.geminiCost)})`;
      document.getElementById('kpi-other-ai-cost').textContent = `${fmtEur(agg.infraCost || 0)} (${fmtUsd(agg.infraCost || 0)})`;

      document.getElementById('kpi-req-title').textContent = agg.excludeSys ? 'AI Calls (LLM)' : 'Total Calls';
      document.getElementById('kpi-total-requests').textContent = fmtNum(agg.displayedRequests);
      document.getElementById('kpi-inf-req').textContent = fmtNum(agg.infRequests);
      document.getElementById('kpi-sys-req').textContent = fmtNum(agg.sysRequests);
      const vReqEl = document.getElementById('kpi-vertex-req');
      if (vReqEl) vReqEl.textContent = fmtNum(agg.vertexRequests);
      const gReqEl = document.getElementById('kpi-gemini-req');
      if (gReqEl) gReqEl.textContent = fmtNum(agg.geminiApiRequests);

      const badge429 = document.getElementById('kpi-429-badge');
      badge429.textContent = `${fmtNum(agg.errors429)} err 429`;
      badge429.className = agg.errors429 > 0
        ? 'jt-chip jt-chip--red mono'
        : 'jt-chip jt-chip--gray mono';

      document.getElementById('kpi-total-tokens').textContent = fmtTok(agg.totalTokens);
      document.getElementById('kpi-in-tokens').textContent = fmtTok(agg.inputTokens);
      document.getElementById('kpi-out-tokens').textContent = fmtTok(agg.outputTokens);
      document.getElementById('kpi-cache-tokens').textContent = fmtTok(agg.cachedTokens);
      const thinkEl = document.getElementById('kpi-think-tokens');
      if (thinkEl) thinkEl.textContent = fmtTok(agg.thinkingTokens);
      const cacheHitEl = document.getElementById('kpi-cache-hit-pct');
      if (cacheHitEl) {
        const hitPct = agg.inputTokens > 0 ? Math.min(100, (agg.cachedTokens / agg.inputTokens) * 100) : 0;
        cacheHitEl.textContent = `${hitPct.toFixed(1)}%`;
      }

      setSafeHtml(document.getElementById('kpi-ma-badge'), `<svg class="jt-ico" aria-hidden="true"><use href="#ico-shield"/></svg> ${escapeHtml(agg.matchedModelArmorProjs)} Model Armor`);
      document.getElementById('kpi-deployed-res').textContent = fmtNum(agg.matchedDeployedRes);
      document.getElementById('kpi-features-sub').textContent = `${agg.matchedFeatures} active AI services`;

      document.getElementById('kpi-total-keys').textContent = fmtNum(agg.matchedApiKeys);
      document.getElementById('kpi-total-sa').textContent = fmtNum(agg.matchedSa);
      document.getElementById('kpi-total-projects').textContent = fmtNum(agg.matchedProjects);
      document.getElementById('kpi-active-projects').textContent = `${s.aiEnabledProjects || 0} AI / ${s.totalProjects || 0} tot`;
      document.getElementById('kpi-scan-time').textContent = `Updated in ${globalScanData.elapsedSeconds || 0}s`;

      // Update compact period summary strip for non-dashboard views (Task D1 — zero extra calculation)
      const stripSpendEl = document.getElementById('jt-strip-spend');
      if (stripSpendEl) stripSpendEl.textContent = fmtEur(agg.totalCost);
      const stripSpendUsdEl = document.getElementById('jt-strip-spend-usd');
      if (stripSpendUsdEl) stripSpendUsdEl.textContent = `(${fmtUsd(agg.totalCost)})`;
      const stripCallsEl = document.getElementById('jt-strip-calls');
      if (stripCallsEl) stripCallsEl.textContent = fmtNum(agg.displayedRequests);
      const stripTokensEl = document.getElementById('jt-strip-tokens');
      if (stripTokensEl) stripTokensEl.textContent = fmtTok(agg.totalTokens);
      const stripProjsEl = document.getElementById('jt-strip-projects');
      if (stripProjsEl) stripProjsEl.textContent = `${fmtNum(agg.matchedProjects)} projects`;
      const stripPeriodEl = document.getElementById('jt-strip-period');
      if (stripPeriodEl) {
        const hdrRangeEl = document.getElementById('jt-range-label');
        stripPeriodEl.textContent = (hdrRangeEl && hdrRangeEl.textContent.trim()) || `${agg.timeline.length}d`;
      }

      // Summary row above projects table
      setSafeHtml(document.getElementById('projects-visibility-text'), `
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-slate-500">
          <span>Account: <b class="text-slate-700">${escapeHtml((globalScanData.auth && globalScanData.auth.activeAccount) || '')}</b></span>
          <span>• <b class="text-emerald-700">${escapeHtml(s.fullAccessProjects || 0)}</b> projects with full permissions</span>
          ${(s.partialAccessProjects || 0) > 0 ? `<span>• <b class="text-amber-700">${escapeHtml(s.partialAccessProjects)}</b> with partial permissions</span>` : ''}
          ${(s.noMonitoringAccessProjects || 0) > 0 ? `<span>• <b class="text-rose-600">${escapeHtml(s.noMonitoringAccessProjects)}</b> with access denied (403)</span>` : ''}
          <span class="text-slate-400">(${s.billingAccountDirectAccess ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Billing Invoices OK' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Costs estimated from Cloud Monitoring'})</span>
        </div>
      `);

      const dailyBadge = document.getElementById('tab-count-daily');
      if (dailyBadge) {
        dailyBadge.textContent = agg.timeline.length + 'd';
        dailyBadge.title = `${agg.timeline.length} days in the analyzed period`;
      }

      renderCharts(agg);
      renderCurrentTab(agg);
      syncFilterbarForView(currentTab);
      updateFilterbarUi();
    }

    // =========================================================================
    // CHART.JS CHARTS (UNIFIED JT_COLORS PALETTE FROM CSS TOKENS)
    // =========================================================================
    function renderCharts(agg) {
      const labels = agg.timeline.map(d => d.date.slice(5));
      const costs = agg.timeline.map(d => Number((d.costUsd || 0).toFixed(3)));
      const reqs = agg.timeline.map(d => agg.excludeSys ? (d.inferenceRequests || 0) : (d.requests || 0));
      const tokensM = agg.timeline.map(d => Number(((d.tokens || 0) / 1_000_000).toFixed(3)));
      const maxCost = costs.length > 0 ? Math.max(...costs) : 0;
      const costBarColors = costs.map(c => (maxCost > 0 && c === maxCost) ? JT_COLORS.amber : JT_COLORS.navy);
      const monoFont = { family: "'JetBrains Mono', monospace", size: 10 };

      const ctxCost = document.getElementById('chartDailyCost').getContext('2d');
      if (chartCostInstance) chartCostInstance.destroy();
      chartCostInstance = new Chart(ctxCost, {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Cost ($ USD)',
            data: costs,
            backgroundColor: costBarColors,
            borderRadius: 3
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: ctx => ` $${Number(ctx.raw).toFixed(3)}` } }
          },
          scales: {
            x: { ticks: { color: JT_COLORS.text3, font: monoFont }, grid: { display: false }, border: { color: JT_COLORS.border } },
            y: { beginAtZero: true, ticks: { color: JT_COLORS.text3, font: monoFont, callback: v => '$' + v }, grid: { color: JT_COLORS.divider }, border: { display: false } }
          }
        }
      });

      const ctxUsage = document.getElementById('chartDailyUsage').getContext('2d');
      if (chartUsageInstance) chartUsageInstance.destroy();
      chartUsageInstance = new Chart(ctxUsage, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              type: 'bar',
              label: 'AI Calls',
              data: reqs,
              backgroundColor: JT_COLORS.info,
              borderRadius: 2,
              yAxisID: 'y'
            },
            {
              type: 'line',
              label: 'Tokens (M)',
              data: tokensM,
              borderColor: JT_COLORS.navy,
              backgroundColor: JT_COLORS.amber,
              borderWidth: 2,
              pointRadius: 2.5,
              tension: 0.25,
              yAxisID: 'y1'
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { labels: { color: JT_COLORS.text2, font: monoFont, boxWidth: 10 } } },
          scales: {
            x: { ticks: { color: JT_COLORS.text3, font: monoFont }, grid: { display: false }, border: { color: JT_COLORS.border } },
            y: { type: 'linear', position: 'left', beginAtZero: true, ticks: { color: JT_COLORS.text3, font: monoFont }, grid: { color: JT_COLORS.divider }, border: { display: false } },
            y1: { type: 'linear', position: 'right', beginAtZero: true, ticks: { color: JT_COLORS.navy, font: monoFont, callback: v => v + 'M' }, grid: { drawOnChartArea: false }, border: { display: false } }
          }
        }
      });

      const topCreds = agg.credBreakdown.slice(0, 6);
      const credLabels = topCreds.map(c => c.label.length > 26 ? c.label.slice(0, 24) + '…' : c.label);
      const credCosts = topCreds.map(c => Number((c.costUsd || 0).toFixed(3)));
      const maxCredCost = credCosts.length > 0 ? Math.max(...credCosts) : 0;
      const credBarColors = credCosts.map(c => (maxCredCost > 0 && c === maxCredCost) ? JT_COLORS.navy : JT_COLORS.info);

      const ctxCred = document.getElementById('chartCredBreakdown').getContext('2d');
      if (chartCredInstance) chartCredInstance.destroy();
      chartCredInstance = new Chart(ctxCred, {
        type: 'bar',
        data: {
          labels: credLabels,
          datasets: [{
            label: 'Cost ($)',
            data: credCosts,
            backgroundColor: credBarColors,
            borderRadius: 3
          }]
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const item = topCreds[ctx.dataIndex];
                  return ` $${Number(ctx.raw).toFixed(3)} • ${fmtNum(item ? item.requests : 0)} calls`;
                }
              }
            }
          },
          scales: {
            x: { beginAtZero: true, ticks: { color: JT_COLORS.text3, font: monoFont, callback: v => '$' + v }, grid: { color: JT_COLORS.divider }, border: { display: false } },
            y: { ticks: { color: JT_COLORS.navy, font: monoFont }, grid: { display: false }, border: { color: JT_COLORS.border } }
          }
        }
      });
    }

    // =========================================================================
    // NAVIGAZIONE MENU LATERALE, SOTTO-TAB & HELPER UTENTE / DEDUPLICAZIONE
    // =========================================================================
    const activeSubTabs = {
      'credentials': 'active-creds',
      'ai-tools': 'notebooks',
      'models': 'used-models',
      'pricing': 'pricing-rates',
      'features': 'gdpr-finops',
      'security': 'sec-findings'
    };

    function switchSubTab(viewId, subTabId) {
      activeSubTabs[viewId] = subTabId;
      applyActiveSubTab(viewId);
    }

    function applyActiveSubTab(viewId) {
      const viewEl = document.getElementById('view-' + viewId);
      if (!viewEl) return;
      const currentSub = activeSubTabs[viewId];
      if (!currentSub) return;

      const navBtns = viewEl.querySelectorAll('[data-subtab-btn]');
      navBtns.forEach(btn => {
        const bId = btn.getAttribute('data-subtab-btn');
        const isActive = bId === currentSub;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-selected', String(isActive));
      });

      const panels = viewEl.querySelectorAll('[data-subtab-panel]');
      panels.forEach(panel => {
        const pId = panel.getAttribute('data-subtab-panel');
        panel.classList.toggle('hidden', pId !== currentSub);
      });
    }

    function jumpToSecurityRemediation(projectId) {
      closeProjectModal();
      closeUserModal();
      activeSubTabs['security'] = 'sec-findings';
      if (projectId) {
        const searchEl = document.getElementById('search-input');
        if (searchEl) searchEl.value = projectId;
      }
      switchTab('security');
    }

    function renderUserEmailClickable(email, extraClass = '') {
      const clean = String(email || '').trim();
      if (!clean || clean === '—' || clean === 'unknown' || clean.includes('svc_notebooklm_enterprise')) {
        return `<span class="${escapeHtml(extraClass)}">${escapeHtml(clean || '—')}</span>`;
      }
      return `<button type="button" data-jt-click="event.stopPropagation(); openUserModal(${jsArg(clean)})" title="Click to open the 360° Inspection Sheet for ${escapeHtml(clean)}" class="user-email-chip text-left font-bold text-[#0F2A4A] hover:text-blue-700 mono ${escapeHtml(extraClass)}"><span><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> ${escapeHtml(clean)}</span><span class="text-[10px] text-blue-600 font-normal"><svg class="jt-ico" aria-hidden="true"><use href="#ico-search"/></svg></span></button>`;
    }

    function groupRepeatedAiResources(resources) {
      const groupsMap = new Map();
      const result = [];
      (resources || []).forEach(r => {
        const rType = String(r.resourceType || '');
        const userKey = r.runtimeUser || r.ownerEmail || r.user || '';
        const nameKey = String(r.displayName || '').trim();
        const isGroupable = (
          rType === 'COLAB_EXECUTION_JOB' ||
          rType === 'REASONING_ENGINE' ||
          rType === 'AGENT_REGISTRY_AGENT' ||
          rType === 'AGENTSPACE_DATASTORE'
        ) && nameKey;

        if (!isGroupable) {
          result.push({
            ...r,
            runCount: 1,
            _runCount: 1,
            succeededCount: 1,
            _succeededCount: 1,
            failedCount: 0,
            _failedCount: 0,
            runsHistory: [r],
            _groupedRuns: [r]
          });
          return;
        }

        const key = `${r.projectId || ''}::${rType}::${nameKey}::${userKey}::${r.location || ''}`;
        const tsMatch = String(r.details || '').match(/Executed:\s*([0-9T:\- ]{10,19})/i);
        const ts = r.updateTime || r.createTime || (tsMatch ? tsMatch[1].trim() : '');
        const stUp = String(r.state || r.status || '').toUpperCase();
        const isSucc = stUp.includes('SUCCEED') || stUp === 'ACTIVE' || stUp === 'READY';
        const isFail = stUp.includes('FAIL') || stUp.includes('ERROR') || stUp.includes('CANCEL');
        const runItem = { ...r, createTime: r.createTime || ts, updateTime: r.updateTime || ts };

        if (!groupsMap.has(key)) {
          const item = {
            ...r,
            runCount: 1,
            _runCount: 1,
            succeededCount: isSucc ? 1 : 0,
            _succeededCount: isSucc ? 1 : 0,
            failedCount: isFail ? 1 : 0,
            _failedCount: isFail ? 1 : 0,
            latestTime: ts,
            _latestTime: ts,
            firstTime: ts,
            _firstTime: ts,
            runsHistory: [runItem],
            _groupedRuns: [runItem]
          };
          groupsMap.set(key, item);
          result.push(item);
        } else {
          const g = groupsMap.get(key);
          g.runCount++;
          g._runCount = g.runCount;
          if (isSucc) {
            g.succeededCount++;
            g._succeededCount = g.succeededCount;
          }
          if (isFail) {
            g.failedCount++;
            g._failedCount = g.failedCount;
          }
          g.runsHistory.push(runItem);
          g._groupedRuns = g.runsHistory;
          if (ts && (!g.latestTime || ts > g.latestTime)) {
            g.latestTime = ts;
            g._latestTime = ts;
            g.updateTime = r.updateTime || ts || g.updateTime;
            g.state = r.state || g.state;
            g.resourceId = r.resourceId || g.resourceId;
          }
          if (ts && (!g.firstTime || ts < g.firstTime)) {
            g.firstTime = ts;
            g._firstTime = ts;
          }
        }
      });
      result.forEach(item => {
        if (item.runsHistory && item.runsHistory.length > 1) {
          item.runsHistory.sort((a, b) => String(b.updateTime || b.createTime || '').localeCompare(String(a.updateTime || a.createTime || '')));
          item._groupedRuns = item.runsHistory;
        }
      });
      return result;
    }

    function switchTab(tab, renderNow = true) {
      currentTab = tab;
      closeMobileSidebar();
      try {
        sessionStorage.setItem(SS_UI_TAB_KEY, tab);
      } catch (err) {
        ignoreStorageError(err);
      }
      const isDash = tab === 'dashboard';
      const kpiGridEl = document.getElementById('global-kpi-grid');
      if (kpiGridEl) kpiGridEl.classList.toggle('hidden', !isDash);
      const chartsWrapEl = document.getElementById('charts-section-wrap');
      const showChartsToggle = document.getElementById('toggle-show-charts');
      const wantCharts = !showChartsToggle || showChartsToggle.checked;
      if (chartsWrapEl) chartsWrapEl.classList.toggle('hidden', !isDash || !wantCharts);
      const summaryStripEl = document.getElementById('global-summary-strip');
      if (summaryStripEl) summaryStripEl.classList.toggle('hidden', isDash);

      ['dashboard', 'projects', 'sync', 'features', 'security', 'daily', 'credentials', 'users', 'ai-tools', 'models', 'pricing'].forEach(t => {
        const btn = document.getElementById('tab-' + t);
        const view = document.getElementById('view-' + t);
        if (btn) {
          btn.classList.toggle('active', t === tab);
          if (t === tab) {
            btn.setAttribute('aria-current', 'page');
          } else {
            btn.removeAttribute('aria-current');
          }
        }
        if (view) view.classList.toggle('hidden', t !== tab);
      });
      const titleEl = document.getElementById('current-view-title');
      if (titleEl && VIEW_TITLES[tab]) titleEl.textContent = VIEW_TITLES[tab];
      const subtitleEl = document.getElementById('current-view-subtitle');
      if (subtitleEl && VIEW_SUBTITLES[tab]) subtitleEl.textContent = VIEW_SUBTITLES[tab];
      syncFilterbarForView(tab);
      updateFilterbarUi();
      if (isDash) {
        requestAnimationFrame(() => {
          [chartCostInstance, chartUsageInstance, chartCredInstance].forEach(ch => {
            if (ch && typeof ch.resize === 'function') {
              ch.resize();
              ch.update('none');
            }
          });
        });
      }
      if (renderNow) {
        if (!globalScanData && tab === 'pricing' && typeof renderPricingAndRatesTab === 'function') {
          renderPricingAndRatesTab();
          applyActiveSubTab('pricing');
        } else {
          renderCurrentTab();
        }
      }
    }

    function dashboardFilterByKeyword(targetTab, searchKeyword) {
      const searchEl = document.getElementById('search-input');
      if (searchEl && searchKeyword !== undefined) {
        searchEl.value = searchKeyword;
      }
      switchTab(targetTab || 'projects');
    }

    function renderCurrentTab(aggOpt = null) {
      syncFilterbarForView(currentTab);
      updateFilterbarUi();
      if (!globalScanData) return;
      const agg = aggOpt || getFilteredAggregation();

      const selProj = agg.selProj;
      const selType = agg.selType;
      let credCount = 0, projCount = 0, modelCount = 0, featCount = 0, secCount = 0, userCount = 0, aiToolsCount = 0;

      (globalScanData.projects || []).forEach(p => {
        if (!isProjectVisibleByToggles(p)) return;
        if (selProj !== 'ALL' && p.projectId !== selProj) return;
        projCount++;
        featCount += (p.vertexFeatures || []).length + (p.deployedAiResources || []).length;
        secCount += ((p.aiSecurityPosture && p.aiSecurityPosture.findings) || []).length;
        (p.credentialsUsage || []).forEach(c => {
          if (selType !== 'ALL' && (c.resolvedType || 'OAUTH_CLIENT') !== selType) return;
          credCount++;
        });
        userCount += (p.usersUsage || []).length;
        modelCount += (p.models || []).length;
        const ats = p.aiToolsSummary || {};
        const asInfo = ats.aiStudio || {};
        const nbInfo = ats.notebooks || {};
        if (asInfo.isAiStudioProject || (asInfo.apiKeysCount || 0) > 0 || (asInfo.inferenceCalls || 0) > 0) aiToolsCount++;
        aiToolsCount += (nbInfo.colabRuntimesCount || 0) + (nbInfo.colabTemplatesCount || 0) + (nbInfo.workbenchInstancesCount || 0) + ((nbInfo.notebookLmEnterpriseCalls || 0) > 0 ? 1 : 0);
      });

      const projsBadge = document.getElementById('tab-count-projects');
      if (projsBadge) {
        projsBadge.textContent = projCount;
        projsBadge.title = `${projCount} GCP projects visible with active filters`;
      }
      const featBadge = document.getElementById('tab-count-features');
      if (featBadge) {
        featBadge.textContent = featCount;
        featBadge.title = `${featCount} Vertex AI services and deployed AI resources`;
      }
      const credBadge = document.getElementById('tab-count-credentials');
      if (credBadge) {
        credBadge.textContent = credCount;
        credBadge.title = `${credCount} credenziali API Key, Service Account e OAuth rilevate`;
      }
      const usersBadge = document.getElementById('tab-count-users');
      if (usersBadge) {
        usersBadge.textContent = userCount;
        usersBadge.title = `${userCount} users detected with AI usage or spend`;
      }
      const aiToolsBadge = document.getElementById('tab-count-ai-tools');
      if (aiToolsBadge) {
        aiToolsBadge.textContent = aiToolsCount;
        aiToolsBadge.title = `${aiToolsCount} active AI Studio, notebook and runtime projects`;
      }
      const modelsBadge = document.getElementById('tab-count-models');
      if (modelsBadge) {
        modelsBadge.textContent = modelCount;
        modelsBadge.title = `${modelCount} AI models detected in visible projects`;
      }
      const pricingBadge = document.getElementById('tab-count-pricing');
      if (pricingBadge) {
        const prModels = (window._jtModelsPricingState && window._jtModelsPricingState.config && window._jtModelsPricingState.config.models)
          || (globalScanData.modelsPricingConfig && globalScanData.modelsPricingConfig.models)
          || null;
        if (prModels) {
          const prCnt = Object.values(prModels).filter(m => !(m && String(m.status || 'active').toLowerCase() === 'deleted')).length;
          pricingBadge.textContent = prCnt;
          pricingBadge.title = `${prCnt} models priced in catalog`;
        }
      }
      const secBadge = document.getElementById('tab-count-security');
      if (secBadge) {
        secBadge.textContent = secCount;
        secBadge.title = `${secCount} AI posture findings and risks detected`;
        secBadge.className = secCount > 0
          ? 'nav-badge bg-rose-100 text-rose-700 font-extrabold'
          : 'nav-badge';
      }

      if (currentTab === 'dashboard') renderExecutiveDashboardTab(agg);
      else if (currentTab === 'projects') renderProjectsTable(agg);
      else if (currentTab === 'sync') renderSyncProjectsTab();
      else if (currentTab === 'features') renderFeaturesAndModelArmorTab(agg);
      else if (currentTab === 'security') renderSecurityPostureTab(agg);
      else if (currentTab === 'daily') renderDailyTable(agg);
      else if (currentTab === 'credentials') renderCredentialsTable(agg);
      else if (currentTab === 'users') renderUsersTable(agg);
      else if (currentTab === 'ai-tools') renderAiToolsTab(agg);
      else if (currentTab === 'models') renderModelsTable(agg);
      else if (currentTab === 'pricing' && typeof renderPricingAndRatesTab === 'function') renderPricingAndRatesTab(agg);

      applyActiveSubTab(currentTab);
      enhanceAllTablesWithFrontendSortAndFilter();
      syncFilterbarForView(currentTab);
      updateFilterbarUi();
    }

    // VISTA 0: EXECUTIVE AI DASHBOARD (METRICHE SIGNIFICATIVE & KEYWORD ZERO FRONZOLI)
