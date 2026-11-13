    // ---------------------------------------------------------------------------
    // Azioni delegate dell'interfaccia (al posto dei gestori inline onclick/onchange/...).
    //
    // I template scrivono data-jt-click / data-jt-change / data-jt-input / data-jt-keydown con una
    // o più chiamate separate da ";" a funzioni dell'elenco JT_ALLOWED_ACTIONS, con argomenti soltanto
    // letterali (stringhe, numeri, true/false/null) oppure this, this.value, this.checked.
    // Nessun eval e nessun new Function: un valore fuori grammatica o con una funzione non in elenco
    // non fa nulla (e lascia un errore in console). Il sanitizzatore toglie ogni attributo on*.
    // ---------------------------------------------------------------------------
    const JT_ALLOWED_ACTIONS = new Set([
      'applyBulkSyncAction', 'applyCustomDateFilter', 'calibratePricingFromBigQuery', 'clearFilterbarChip',
      'closeGeminiInspectorModal', 'closeJtMenus', 'closeLoginScreen', 'enterDemo', 'closeMobileSidebar',
      'closePricingModelDrawer', 'closeProjectModal', 'closeUserModal', 'dashboardFilterByKeyword',
      'enterWithSavedAccount', 'filterAgentspaceDataStores', 'filterGeCustomAgents', 'filterGeminiConnectorHubs',
      'forceScanSingleProject', 'jumpToBillingCalibrationSettings', 'jumpToSecurityRemediation',
      'loadModelsPricingData', 'logoutThisBrowser', 'onBillingCsvFileSelected', 'onCredTypeFilterChanged',
      'onFiltersChanged', 'onModelFilterChanged', 'onPeriodDaysChanged', 'onPricingRatesFilterChanged',
      'onProjectFilterChanged', 'onSpecificCredChanged', 'onVisibilityTogglesChanged', 'openGeminiInspectorModal',
      'openLoginScreen', 'openPricingBillingSettings', 'openPricingModelDrawer', 'openProjectModal', 'openUserModal',
      'purgeLocalData', 'renderCurrentTab', 'resetAllFilters', 'resetPricingBillingSettingsToDefaults',
      'resetPricingModelManualOverride', 'runScan', 'savePricingBillingSettings', 'savePricingModelGeminiCache',
      'savePricingModelManualOverride', 'selectHeaderPeriodFilter', 'selectHeaderProjectFilter',
      'selectSingleCredentialFilter', 'selectSingleModelFilter', 'selectSingleProjectFilter',
      'setSecuritySeverityFilter', 'setSyncFilterMode', 'switchGeminiEnterpriseSubView', 'switchGoogleAccount',
      'switchSubTab', 'switchTab', 'toggleChartsSection', 'toggleMobileSidebar', 'toggleProjectSyncState',
      'toggleSidebarCollapse', 'triggerBillingCsvUpload', 'triggerGoogleLogin', 'triggerModelsPricingCloudSync',
      // Azioni di supporto definite qui sotto (sostituiscono i gestori inline composti)
      'hideElementById', 'toggleHiddenById', 'switchTabOnKey', 'onBackdrop'
    ]);
    const JT_EVENT_CALLS = new Set(['event.stopPropagation', 'event.preventDefault']);
    const JT_ACTION_EVENTS = ['click', 'change', 'input', 'keydown'];

    // Contesto dell'azione in corso (elemento che porta l'attributo + evento), per le azioni di supporto.
    let _jtActionCtx = { el: null, event: null };

    function _jtParseString(src, i) {
      const quote = src[i];
      let out = '';
      let j = i + 1;
      while (j < src.length) {
        const c = src[j];
        if (c === quote) return { value: out, end: j + 1 };
        if (c === '\\') {
          const n = src[j + 1];
          if (n === undefined) return null;
          if (n === 'n') out += '\n';
          else if (n === 't') out += '\t';
          else if (n === 'r') out += '\r';
          else if (n === 'b') out += '\b';
          else if (n === 'f') out += '\f';
          else if (n === 'u') {
            const hex = src.slice(j + 2, j + 6);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) return null;
            out += String.fromCharCode(parseInt(hex, 16));
            j += 4;
          } else if (n === '\\' || n === '/' || n === '"' || n === "'") out += n;
          else return null;
          j += 2;
          continue;
        }
        out += c;
        j += 1;
      }
      return null;
    }

    // Restituisce [{ callee, args: [{kind, value}] }] oppure null se il testo esce dalla grammatica.
    function jtParseActions(src) {
      if (typeof src !== 'string' || !src.trim()) return null;
      const stmts = [];
      let i = 0;
      const skipWs = () => { while (i < src.length && /\s/.test(src[i])) i++; };
      while (true) {
        skipWs();
        const m = /^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?/.exec(src.slice(i));
        if (!m) return null;
        const callee = m[0];
        i += callee.length;
        skipWs();
        if (src[i] !== '(') return null;
        i++;
        const args = [];
        skipWs();
        if (src[i] === ')') {
          i++;
        } else {
          while (true) {
            skipWs();
            let arg = null;
            if (src[i] === "'" || src[i] === '"') {
              const s = _jtParseString(src, i);
              if (!s) return null;
              arg = { kind: 'lit', value: s.value };
              i = s.end;
            } else {
              const t = /^(?:-?\d+(?:\.\d+)?|true|false|null|this\.value|this\.checked|this)(?![\w$.])/.exec(src.slice(i));
              if (!t) return null;
              const tok = t[0];
              if (tok === 'true') arg = { kind: 'lit', value: true };
              else if (tok === 'false') arg = { kind: 'lit', value: false };
              else if (tok === 'null') arg = { kind: 'lit', value: null };
              else if (tok === 'this') arg = { kind: 'this' };
              else if (tok === 'this.value') arg = { kind: 'this.value' };
              else if (tok === 'this.checked') arg = { kind: 'this.checked' };
              else arg = { kind: 'lit', value: Number(tok) };
              i += tok.length;
            }
            args.push(arg);
            skipWs();
            if (src[i] === ',') { i++; continue; }
            if (src[i] === ')') { i++; break; }
            return null;
          }
        }
        if (callee.includes('.')) {
          if (!JT_EVENT_CALLS.has(callee) || args.length) return null;
        } else if (!JT_ALLOWED_ACTIONS.has(callee)) {
          return null;
        }
        stmts.push({ callee, args });
        skipWs();
        if (src[i] === ';') {
          i++;
          skipWs();
          if (i >= src.length) break;
          continue;
        }
        if (i >= src.length) break;
        return null;
      }
      return stmts;
    }

    const _jtActionCache = new Map();

    function jtRunActions(src, el, ev) {
      let stmts = _jtActionCache.get(src);
      if (stmts === undefined) {
        stmts = jtParseActions(src);
        _jtActionCache.set(src, stmts);
      }
      if (!stmts) {
        console.error('[JanusTower] invalid or disallowed action:', src);
        return;
      }
      for (const st of stmts) {
        _jtActionCtx = { el, event: ev };
        try {
          if (st.callee === 'event.stopPropagation') { ev.stopPropagation(); continue; }
          if (st.callee === 'event.preventDefault') { ev.preventDefault(); continue; }
          const fn = window[st.callee];
          if (typeof fn !== 'function') {
            console.error('[JanusTower] undefined function:', st.callee);
            return;
          }
          const args = st.args.map(a => {
            if (a.kind === 'this') return el;
            if (a.kind === 'this.value') return el.value;
            if (a.kind === 'this.checked') return el.checked;
            return a.value;
          });
          fn.apply(window, args);
        } catch (err) {
          console.error('[JanusTower] action error', src, err);
          return;
        }
      }
    }

    function jtDispatchAction(type, ev) {
      const attr = 'data-jt-' + type;
      // Catena degli antenati fissata in partenza (come il bubbling nativo): un'azione che ridisegna il DOM
      // e stacca il nodo non interrompe gli antenati.
      const chain = [];
      let node = ev.target && ev.target.nodeType === 1 ? ev.target : (ev.target && ev.target.parentElement);
      while (node && node !== document) {
        chain.push(node);
        node = node.parentElement;
      }
      for (const n of chain) {
        if (n.hasAttribute && n.hasAttribute(attr)) {
          jtRunActions(n.getAttribute(attr), n, ev);
          if (ev.cancelBubble) break; // stopPropagation() chiamato da un'azione: come con il gestore inline
        }
      }
    }

    JT_ACTION_EVENTS.forEach(type => document.addEventListener(type, ev => jtDispatchAction(type, ev)));

    // --- Azioni di supporto (al posto di frammenti di codice nei vecchi attributi) ---
    function hideElementById(id) {
      const el = document.getElementById(id);
      if (el) el.classList.add('hidden');
    }
    function toggleHiddenById(id) {
      const el = document.getElementById(id);
      if (el) el.classList.toggle('hidden');
    }
    // Come role="button": Invio o Spazio attivano la scheda
    function switchTabOnKey(name) {
      const ev = _jtActionCtx.event;
      if (ev && (ev.key === 'Enter' || ev.key === ' ')) {
        ev.preventDefault();
        switchTab(name);
      }
    }
    // Chiude un pannello solo se il clic è sullo sfondo (non sul contenuto)
    function onBackdrop(closeFnName) {
      const ctx = _jtActionCtx;
      if (!ctx.event || ctx.event.target !== ctx.el) return;
      if (!JT_ALLOWED_ACTIONS.has(closeFnName) || typeof window[closeFnName] !== 'function') return;
      window[closeFnName]();
    }
    window.hideElementById = hideElementById;
    window.toggleHiddenById = toggleHiddenById;
    window.switchTabOnKey = switchTabOnKey;
    window.onBackdrop = onBackdrop;
    window.jtParseActions = jtParseActions;

    if (typeof module !== 'undefined' && module.exports) {
      module.exports = { jtParseActions, JT_ALLOWED_ACTIONS };
    }
