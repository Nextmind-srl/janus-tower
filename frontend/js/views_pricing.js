    // =========================================================================
    // VIEW 4B: PRICING & RATES (CLOUD BILLING CATALOG SYNC, SETTINGS & DRAWER)
    // =========================================================================
    window._jtModelsPricingState = {
      loading: false,
      syncing: false,
      error: null,
      needsLogin: false,
      config: null,
      observedModels: [],
      syncInProgress: false,
      lastLoadedAt: 0
    };

    function _fmtRatePer1M(val) {
      const n = Number(val);
      if (Number.isNaN(n) || n < 0) return '—';
      if (n === 0) return '$0.00';
      if (n < 0.01) return '$' + n.toFixed(4);
      if (n < 1) return '$' + n.toFixed(3).replace(/0$/, '');
      return '$' + n.toFixed(2);
    }

    function _formatPricingRelativeAge(isoStr) {
      if (!isoStr) return { ageLabel: 'Never', formattedDate: 'Never synced' };
      const ms = Date.parse(isoStr);
      if (Number.isNaN(ms)) return { ageLabel: String(isoStr), formattedDate: String(isoStr) };
      const diffSec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
      let ageLabel = 'Just now';
      if (diffSec >= 86400) {
        const d = Math.floor(diffSec / 86400);
        ageLabel = `${d} d ago`;
      } else if (diffSec >= 3600) {
        const h = Math.floor(diffSec / 3600);
        ageLabel = `${h} h ago`;
      } else if (diffSec >= 60) {
        const m = Math.floor(diffSec / 60);
        ageLabel = `${m} m ago`;
      }
      const formattedDate = isoStr.replace('T', ' ').slice(0, 16) + ' UTC';
      return { ageLabel, formattedDate };
    }

    function _hasModelManualOverride(m) {
      if (!m) return false;
      const src = String(m.source || '').toUpperCase();
      if (src === 'MANUAL') return true;
      if (m.manualOverride && typeof m.manualOverride === 'object') {
        return Object.keys(m.manualOverride).length > 0;
      }
      return Boolean(m.manualOverride);
    }

    function _renderPricingSourceBadge(source, manualOverride = false, isEstimatedField = false) {
      const src = String(source || 'BUILTIN_DEFAULT').toUpperCase();
      if (manualOverride || src === 'MANUAL') {
        return toneBadge('purple', 'Manual', { title: 'Manual rate override (preserved across Cloud Billing syncs)' });
      }
      if (isEstimatedField) {
        return toneBadge('amber', 'Estimated', { title: 'Estimated rate (regional multiplier or fallback)' });
      }
      if (src.startsWith('GCP_BILLING')) {
        return toneBadge('green', 'Catalog', { title: 'Synced from Google Cloud Billing Catalog API' });
      }
      if (src.startsWith('VERTEX_PUBLISHER')) {
        return toneBadge('blue', 'Publisher', { title: 'Discovered from Vertex AI Publisher Models API' });
      }
      if (src === 'CLOUD_MONITORING_DISCOVERED' || src === 'ESTIMATED') {
        return toneBadge('amber', 'Estimated', { title: 'Observed in Cloud Monitoring with estimated fallback rate' });
      }
      return toneBadge('gray', 'Built-in', { title: 'Built-in default list price' });
    }

    function _isModelDeleted(m) {
      return Boolean(m) && String(m.status || 'active').toLowerCase() === 'deleted';
    }

    function _renderPricingStatusBadges(m) {
      const parts = [];
      if (_isModelDeleted(m)) {
        const when = m.deletedAt ? ` on ${String(m.deletedAt).slice(0, 10)}` : '';
        parts.push(toneBadge('red', 'Deleted', { title: `No longer returned by the Google API${when}. Kept in the list with its stored rates.` }));
      }
      if (String(m.pricingStatus || '').toUpperCase() === 'NO_CATALOG_PRICE') {
        parts.push(toneBadge('gray', 'No catalog price', { title: 'Google Cloud Billing catalog has no SKU for this model. No rate is estimated.' }));
      }
      return parts.join(' ');
    }

    function _renderCatalogRatesSection(m) {
      const cat = (m && m.catalog && typeof m.catalog === 'object') ? m.catalog : null;
      if (!cat) return '';
      const fieldLabels = [['input', 'Input'], ['output', 'Output'], ['cache_read_input', 'Cache read'], ['regional_input', 'Regional input'], ['regional_output', 'Regional output'], ['regional_cache_read_input', 'Regional cache read']];
      const rows = [];
      [['vertex', 'Vertex AI'], ['geminiApi', 'Gemini API']].forEach(([svcKey, svcLabel]) => {
        const byModality = (cat[svcKey] && typeof cat[svcKey] === 'object') ? cat[svcKey] : {};
        Object.keys(byModality).sort().forEach(modality => {
          const rates = byModality[modality] || {};
          const cells = fieldLabels.map(([k]) => (rates[k] === undefined || rates[k] === null)
            ? '<td class="py-2 px-3 text-right mono text-slate-400">—</td>'
            : `<td class="py-2 px-3 text-right mono font-bold">${escapeHtml(_fmtRatePer1M(Number(rates[k])))}</td>`).join('');
          rows.push(`<tr><td class="py-2 px-3 font-bold text-slate-800">${escapeHtml(svcLabel)}</td><td class="py-2 px-3 capitalize text-slate-700">${escapeHtml(modality)}</td>${cells}</tr>`);
        });
      });
      const perUnit = Array.isArray(cat.perUnit) ? cat.perUnit : [];
      const unitRows = perUnit.map(u => `<tr><td class="py-2 px-3 text-slate-800">${escapeHtml(u.sku || '')}</td><td class="py-2 px-3 text-right mono font-bold">${escapeHtml(String(u.usd))}</td><td class="py-2 px-3 text-slate-600">${escapeHtml(u.unit || '')}</td></tr>`).join('');
      const ambiguous = Array.isArray(cat.ambiguous) ? cat.ambiguous : [];
      if (!rows.length && !unitRows) return '';
      return `
        <div class="jt-table-panel bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div class="px-4 py-2.5 bg-slate-50 border-b border-slate-200">
            <h3 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]">Catalog rates by modality (USD per 1M tokens)</h3>
            <p class="text-xs text-slate-500 mt-0.5">Read from the Cloud Billing catalog${cat.syncedAt ? ` on ${escapeHtml(String(cat.syncedAt).slice(0, 10))}` : ''}. Only text tokens feed the cost calculation; other modalities are shown for reference.</p>
          </div>
          ${rows.length ? `<div class="overflow-x-auto"><table class="jt-table w-full text-left border-collapse"><thead><tr class="border-b border-slate-200 text-xs font-bold uppercase tracking-wider text-slate-500 bg-slate-50"><th scope="col" class="py-2 px-3">Service</th><th scope="col" class="py-2 px-3">Modality</th>${fieldLabels.map(([, l]) => `<th scope="col" class="py-2 px-3 text-right">${escapeHtml(l)}</th>`).join('')}</tr></thead><tbody class="divide-y divide-slate-100 text-xs">${rows.join('')}</tbody></table></div>` : ''}
          ${unitRows ? `<div class="overflow-x-auto border-t border-slate-200"><table class="jt-table w-full text-left border-collapse"><thead><tr class="border-b border-slate-200 text-xs font-bold uppercase tracking-wider text-slate-500 bg-slate-50"><th scope="col" class="py-2 px-3">Per-unit SKU</th><th scope="col" class="py-2 px-3 text-right">USD</th><th scope="col" class="py-2 px-3">Unit</th></tr></thead><tbody class="divide-y divide-slate-100 text-xs">${unitRows}</tbody></table></div>` : ''}
          ${ambiguous.length ? `<div class="px-4 py-2 border-t border-slate-200 text-xs text-amber-800 bg-amber-50">Several SKUs compete for: <span class="mono">${escapeHtml(ambiguous.join(', '))}</span>. The highest price is used.</div>` : ''}
        </div>`;
    }

    function _updatePricingSidebarBadge() {
      const st = window._jtModelsPricingState;
      const badgeEl = document.getElementById('tab-count-pricing');
      if (!badgeEl) return;
      const modelsObj = (st.config && st.config.models) || {};
      const count = Object.values(modelsObj).filter(m => !_isModelDeleted(m)).length;
      if (count > 0) {
        badgeEl.textContent = String(count);
        badgeEl.title = `${count} active AI models in pricing catalog`;
      } else if (globalScanData && globalScanData.modelsPricingConfig && globalScanData.modelsPricingConfig.models) {
        const fallbackCount = Object.values(globalScanData.modelsPricingConfig.models).filter(m => !_isModelDeleted(m)).length;
        badgeEl.textContent = String(fallbackCount);
      }
    }

    function _renderPricingLoadingSkeleton() {
      const kpiGrid = document.getElementById('pricing-kpi-grid');
      const statusBanner = document.getElementById('pricing-status-banner');
      const tbody = document.getElementById('pricing-rates-tbody');
      if (kpiGrid) {
        setSafeHtml(kpiGrid, [1, 2, 3, 4].map(() => `
          <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs animate-pulse space-y-2">
            <div class="h-3.5 w-28 bg-slate-200 rounded"></div>
            <div class="h-7 w-20 bg-slate-200 rounded"></div>
            <div class="h-3.5 w-40 bg-slate-100 rounded"></div>
          </div>
        `).join(''));
      }
      if (statusBanner) {
        setSafeHtml(statusBanner, `
          <div class="flex items-center justify-between gap-3 animate-pulse">
            <div class="h-4 w-64 bg-slate-200 rounded"></div>
            <div class="h-8 w-44 bg-slate-200 rounded-lg"></div>
          </div>
        `);
      }
      if (tbody) {
        setSafeHtml(tbody, `
          <tr>
            <td colspan="11" class="py-10 px-4 text-center text-xs text-slate-500">
              Loading model pricing catalog and Cloud Monitoring coverage…
            </td>
          </tr>
        `);
      }
    }

    async function loadModelsPricingData(forceRefresh = false) {
      const st = window._jtModelsPricingState;
      if (st.loading) return;
      if (!forceRefresh && st.config && (Date.now() - st.lastLoadedAt < 15000)) {
        _renderPricingViewContents();
        return;
      }

      st.loading = true;
      st.error = null;
      st.needsLogin = false;
      if (!st.config) {
        _renderPricingLoadingSkeleton();
      }

      try {
        const resp = await fetch('/api/models-pricing', {
          signal: AbortSignal.timeout(30000),
          method: 'GET',
          headers: getBrowserAuthHeaders()
        });
        if (resp.status === 401) {
          st.loading = false;
          st.needsLogin = true;
          openLoginScreen(false);
          _renderPricingViewContents();
          return;
        }
        const data = await resp.json();
        const isOk = resp.ok && (data.success === true || data.status === 'ok');
        if (!isOk) {
          throw new Error(data.error || data.message || `HTTP ${resp.status}`);
        }
        if (data.needsLogin || (data.auth && data.auth.needsLogin)) {
          st.loading = false;
          st.needsLogin = true;
          openLoginScreen(false);
          _renderPricingViewContents();
          return;
        }
        st.config = data.config || {};
        st.observedModels = Array.isArray(data.observed)
          ? data.observed
          : (Array.isArray(data.observedModels) ? data.observedModels : []);
        st.syncInProgress = Boolean(data.syncInProgress || (data.auth && data.auth.syncInProgress));
        st.lastLoadedAt = Date.now();
        st.loading = false;
        _updatePricingSidebarBadge();
        _renderPricingViewContents();
      } catch (err) {
        st.loading = false;
        st.error = err && err.message ? err.message : 'Failed to load models pricing catalog';
        _renderPricingViewContents();
      }
    }
    window.loadModelsPricingData = loadModelsPricingData;

    async function triggerModelsPricingCloudSync() {
      const st = window._jtModelsPricingState;
      if (st.syncing || st.syncInProgress) return;
      st.syncing = true;
      st.error = null;
      _renderPricingStatusBanner();

      try {
        const resp = await fetch('/api/models-pricing/sync', {
          signal: AbortSignal.timeout(180000),
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({})
        });
        if (resp.status === 401) {
          st.syncing = false;
          st.needsLogin = true;
          openLoginScreen(false);
          _renderPricingViewContents();
          return;
        }
        const data = await resp.json();
        const isOk = resp.ok && (data.success === true || data.status === 'ok' || data.status === 'partial');
        if (!isOk) {
          throw new Error(data.error || data.message || `Sync failed (HTTP ${resp.status})`);
        }
        st.config = data.config || st.config;
        if (Array.isArray(data.observed)) {
          st.observedModels = data.observed;
        } else if (Array.isArray(data.observedModels)) {
          st.observedModels = data.observedModels;
        }
        st.syncInProgress = false;
        st.syncing = false;
        st.lastLoadedAt = Date.now();
        _updatePricingSidebarBadge();
        _renderPricingViewContents();
      } catch (err) {
        st.syncing = false;
        st.syncInProgress = false;
        st.error = err && err.message ? err.message : 'Cloud Billing sync failed';
        _renderPricingViewContents();
      }
    }
    window.triggerModelsPricingCloudSync = triggerModelsPricingCloudSync;

    function openPricingBillingSettings() {
      switchSubTab('pricing', 'pricing-settings');
    }
    window.openPricingBillingSettings = openPricingBillingSettings;

    function onPricingRatesFilterChanged() {
      _renderPricingRatesTable();
      _applyAllPricingSorts();
    }
    window.onPricingRatesFilterChanged = onPricingRatesFilterChanged;

    function _buildObservedModelsMap() {
      const st = window._jtModelsPricingState;
      const obsMap = new Map();
      (st.observedModels || []).forEach(item => {
        if (!item) return;
        if (item.modelId) obsMap.set(String(item.modelId).toLowerCase(), item);
        const aliasKey = item.matchedModelId || item.baseModel;
        if (aliasKey && aliasKey !== 'default' && !obsMap.has(String(aliasKey).toLowerCase())) {
          obsMap.set(String(aliasKey).toLowerCase(), item);
        }
      });

      // Fallback from globalScanData if server cache had not populated observedModels yet
      if (obsMap.size === 0 && globalScanData && Array.isArray(globalScanData.projects)) {
        const modelsDict = (st.config && st.config.models) || {};
        globalScanData.projects.forEach(p => {
          (p.models || []).forEach(m => {
            const rawId = String(m.modelId || m.model || '').trim();
            if (!rawId) return;
            const key = rawId.toLowerCase();
            const catItem = modelsDict[rawId] || modelsDict[key] || null;
            const catSrc = catItem ? String(catItem.source || 'BUILTIN_DEFAULT') : 'ESTIMATED';
            const existing = obsMap.get(key) || {
              modelId: rawId,
              matchedModelId: catItem ? rawId : 'default',
              calls: 0,
              inputTokens: 0,
              outputTokens: 0,
              thinkingTokens: 0,
              cachedTokens: 0,
              totalTokens: 0,
              costUsd: 0,
              projects: [],
              locations: [],
              priceOrigin: _hasModelManualOverride(catItem) ? 'manual' : (catSrc.startsWith('GCP_BILLING') ? 'catalog' : 'fallback'),
              isFallback: !catItem || (!catSrc.startsWith('GCP_BILLING') && !_hasModelManualOverride(catItem)),
              source: catSrc
            };
            existing.calls += (m.invocations ?? m.requests ?? 0);
            existing.inputTokens += (m.inputTokens || 0);
            existing.outputTokens += (m.outputTokens || 0);
            existing.thinkingTokens += (m.thinkingTokens || 0);
            existing.cachedTokens += (m.cachedTokens || 0);
            existing.totalTokens += (m.totalTokens || 0);
            existing.costUsd += (m.costUsd ?? m.estimatedCostUsd ?? 0);
            if (p.projectId && !existing.projects.includes(p.projectId)) {
              existing.projects.push(p.projectId);
            }
            (m.locations || []).forEach(loc => {
              if (loc && !existing.locations.includes(loc)) existing.locations.push(loc);
            });
            obsMap.set(key, existing);
          });
        });
      }
      return obsMap;
    }

    function _computePricingKpiStats() {
      const st = window._jtModelsPricingState;
      const cfg = st.config || {};
      const modelsObj = cfg.models || {};
      const modelEntries = Object.entries(modelsObj);
      const lastSync = cfg.lastApiSync || {};
      const obsMap = _buildObservedModelsMap();

      let fromCatalogCount = 0;
      let builtinFallbackCount = 0;
      let manualCount = 0;

      const deletedCount = modelEntries.filter(([, m]) => _isModelDeleted(m)).length;
      modelEntries.forEach(([, m]) => {
        if (_isModelDeleted(m)) return;
        const src = String(m.source || 'BUILTIN_DEFAULT').toUpperCase();
        if (_hasModelManualOverride(m)) {
          manualCount++;
        } else if (src.startsWith('GCP_BILLING') || src.startsWith('VERTEX_PUBLISHER')) {
          fromCatalogCount++;
        } else {
          builtinFallbackCount++;
        }
      });

      const unpricedObserved = [];
      const seenObsKeys = new Set();
      obsMap.forEach((obs) => {
        const canonicalKey = String(obs.modelId || obs.matchedModelId || obs.baseModel || '').toLowerCase();
        if (!canonicalKey || seenObsKeys.has(canonicalKey)) return;
        seenObsKeys.add(canonicalKey);
        const matchedId = (obs.matchedModelId && obs.matchedModelId !== 'default') ? obs.matchedModelId : (obs.baseModel || obs.modelId);
        const catEntry = modelsObj[matchedId] || modelsObj[obs.modelId] || null;
        const catSrc = catEntry ? String(catEntry.source || '').toUpperCase() : '';
        const isUnpriced = Boolean(
          obs.isFallback ||
          obs.isFallbackPricing ||
          obs.priceOrigin === 'fallback' ||
          !catEntry ||
          catSrc === 'CLOUD_MONITORING_DISCOVERED' ||
          catSrc === 'ESTIMATED'
        );
        if (isUnpriced && (obs.calls || 0) > 0) {
          unpricedObserved.push({ obs, catEntry });
        }
      });

      return {
        totalModels: modelEntries.length - deletedCount,
        deletedCount,
        fromCatalogCount,
        builtinFallbackCount,
        manualCount,
        lastSync,
        unpricedObserved,
        obsMap
      };
    }

    function _renderPricingKpiGrid(stats) {
      const kpiGrid = document.getElementById('pricing-kpi-grid');
      if (!kpiGrid) return;

      const lastSync = stats.lastSync || {};
      const syncedAt = lastSync.syncedAt || null;
      const syncErrors = Array.isArray(lastSync.errors) ? lastSync.errors : [];
      const isPartial = Boolean(lastSync.partial || syncErrors.length > 0);
      const ageInfo = _formatPricingRelativeAge(syncedAt);

      let syncStatusBadge = toneBadge('gray', 'Never synced');
      if (syncedAt) {
        syncStatusBadge = isPartial
          ? toneBadge('amber', 'Partial')
          : toneBadge('green', 'OK');
      }

      const skusScanned = Number(lastSync.skusScanned || 0);
      const skusMatched = Number(lastSync.skusMatched || 0);
      const billingUpdatedCount = Array.isArray(lastSync.modelsUpdatedFromBilling)
        ? lastSync.modelsUpdatedFromBilling.length
        : Number(stats.fromCatalogCount || 0);
      const publisherCount = Number(lastSync.publisherModelsDiscovered || 0);

      const unpricedCount = stats.unpricedObserved.length;
      const unpricedBadge = unpricedCount > 0
        ? toneBadge('amber', 'Fallback active')
        : toneBadge('green', '100% covered');

      setSafeHtml(kpiGrid, `
        <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs text-slate-500 font-medium">
            <span>Models priced</span>
            ${toneBadge('navy', 'USD / 1M', { chip: true, mono: true })}
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span id="pricing-kpi-models-count" class="jt-kpi__value text-2xl font-extrabold text-[#0F2A4A] mono">${fmtNum(stats.totalModels)}</span>
            <span class="jt-kpi__unit text-xs text-slate-500">active models${stats.deletedCount > 0 ? ` · ${fmtNum(stats.deletedCount)} deleted` : ''}</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-1 text-xs text-slate-600">
            <span>Catalog: <b class="text-emerald-700 mono">${fmtNum(stats.fromCatalogCount)}</b></span>
            <span>Built-in: <b class="text-slate-700 mono">${fmtNum(stats.builtinFallbackCount)}</b></span>
            <span>Manual: <b class="text-purple-700 mono">${fmtNum(stats.manualCount)}</b></span>
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs text-slate-500 font-medium">
            <span>Last sync</span>
            ${syncStatusBadge}
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span id="pricing-kpi-last-sync-age" class="jt-kpi__value text-2xl font-extrabold text-[#0F2A4A] mono">${escapeHtml(ageInfo.ageLabel)}</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-600">
            <span class="mono">${escapeHtml(ageInfo.formattedDate)}</span>
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs text-slate-500 font-medium">
            <span>SKUs matched</span>
            ${toneBadge('blue', 'Cloud Billing', { chip: true })}
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span id="pricing-kpi-skus-matched" class="jt-kpi__value text-2xl font-extrabold text-[#0F2A4A] mono">${fmtNum(skusMatched)} / ${fmtNum(skusScanned)}</span>
            <span class="jt-kpi__unit text-xs text-slate-500">SKUs</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-600">
            <span>Catalog models: <b class="text-slate-800 mono">${fmtNum(billingUpdatedCount)}</b></span>
            <span>Publisher: <b class="text-slate-800 mono">${fmtNum(publisherCount)}</b></span>
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border ${unpricedCount > 0 ? 'border-amber-300 bg-amber-50/30' : 'border-slate-200'} p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs text-slate-500 font-medium">
            <span>Used but not priced</span>
            ${unpricedBadge}
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span id="pricing-kpi-unpriced-count" class="jt-kpi__value text-2xl font-extrabold ${unpricedCount > 0 ? 'text-amber-700' : 'text-emerald-700'} mono">${fmtNum(unpricedCount)}</span>
            <span class="jt-kpi__unit text-xs text-slate-500">models in last scan</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-600">
            <span>${unpricedCount > 0 ? 'Using fallback/estimated rate' : 'All active models have explicit rates'}</span>
            ${unpricedCount > 0 ? `<button type="button" data-jt-click="switchSubTab('pricing', 'pricing-coverage')" class="font-bold text-amber-800 hover:underline cursor-pointer">Review →</button>` : ''}
          </div>
        </div>
      `);
    }

    function _renderPricingStatusBanner() {
      const bannerEl = document.getElementById('pricing-status-banner');
      if (!bannerEl) return;

      const st = window._jtModelsPricingState;
      if (st.needsLogin) {
        setSafeHtml(bannerEl, `
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center gap-2.5 text-xs text-amber-900">
              ${toneBadge('amber', 'Session expired')}
              <span class="font-semibold">Your Google Cloud session has expired. Please sign in to load or sync model rates.</span>
            </div>
            <button type="button" data-jt-click="openLoginScreen(true)" class="jt-btn jt-btn--primary text-xs cursor-pointer">
              Sign in with Google
            </button>
          </div>
        `);
        return;
      }

      if (st.error && !st.config) {
        setSafeHtml(bannerEl, `
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center gap-2.5 text-xs text-rose-800">
              ${toneBadge('red', 'Error')}
              <span class="font-semibold">${escapeHtml(st.error)}</span>
            </div>
            <button type="button" data-jt-click="loadModelsPricingData(true)" class="jt-btn jt-btn--primary text-xs cursor-pointer">
              Retry
            </button>
          </div>
        `);
        return;
      }

      const cfg = st.config || {};
      const lastSync = cfg.lastApiSync || {};
      const syncedAt = lastSync.syncedAt || null;
      const errors = Array.isArray(lastSync.errors) ? lastSync.errors : [];
      const isSyncing = Boolean(st.syncing || st.syncInProgress);
      const has429 = errors.some(e => String(e).includes('429') || String(e).toLowerCase().includes('rate'));

      let bannerTone = 'amber';
      let headline = 'Indicative list prices — not synced yet';
      let detailText = 'Using built-in list rates. Run a live sync to pull SKU rates from the Google Cloud Billing Catalog API and Vertex AI Publisher Models.';

      if (has429) {
        bannerTone = 'amber';
        headline = 'Rate-limited, retry later';
        detailText = String(errors[0] || 'Google Cloud API returned HTTP 429 rate limit during catalog sync.');
      } else if (syncedAt && (lastSync.partial || errors.length > 0)) {
        bannerTone = 'amber';
        headline = `Sync partial: ${errors.length} ${errors.length === 1 ? 'error' : 'errors'}`;
        detailText = String(errors[0] || 'Some catalog endpoints could not be queried.');
      } else if (syncedAt) {
        bannerTone = 'green';
        headline = 'Synced with Google Cloud Billing Catalog';
        detailText = `Last synced ${ _formatPricingRelativeAge(syncedAt).ageLabel } · ${fmtNum(lastSync.skusMatched || 0)} AI SKUs matched across ${fmtNum(lastSync.skusScanned || 0)} scanned SKUs.`;
      }

      const inlineErrHtml = st.error
        ? `<div class="mt-2 text-xs text-rose-700 font-semibold">${escapeHtml(st.error)}</div>`
        : '';

      const bSettings = cfg.billingSettings || {};
      const vDisc = Number(bSettings.vertexBillingCreditDiscountPct ?? bSettings.vertexCreditDiscountPct ?? 0);
      const gDisc = Number(bSettings.geminiApiBillingCreditDiscountPct ?? bSettings.geminiApiCreditDiscountPct ?? 0);
      const iCache = Number(bSettings.vertexImplicitCacheHitRatioPct ?? bSettings.implicitCacheHitPct ?? 93);
      const rMult = Number(bSettings.regionalMultiplierDefault ?? 1.1);

      setSafeHtml(bannerEl, `
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="space-y-1">
            <div class="flex flex-wrap items-center gap-2 text-xs">
              ${toneBadge(bannerTone, headline)}
              <span class="text-slate-600">${escapeHtml(detailText)}</span>
            </div>
            <div class="text-xs text-slate-500 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>Active billing adjustments:</span>
              <span class="mono text-slate-700">Vertex discount: <b>${escapeHtml(vDisc)}%</b></span>
              <span>·</span>
              <span class="mono text-slate-700">Gemini API discount: <b>${escapeHtml(gDisc)}%</b></span>
              <span>·</span>
              <span class="mono text-slate-700">Implicit cache: <b>${escapeHtml(iCache)}%</b></span>
              <span>·</span>
              <span class="mono text-slate-700">Regional multiplier: <b>${escapeHtml(rMult.toFixed(2))}×</b></span>
            </div>
            ${inlineErrHtml}
          </div>
          <div class="flex flex-wrap items-center gap-2 shrink-0">
            <button
              type="button"
              id="btn-pricing-open-settings"
              data-jt-click="openPricingBillingSettings()"
              aria-label="Open billing settings"
              class="jt-btn-secondary px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-800 border border-slate-200 text-xs font-bold cursor-pointer transition"
            >
              Open billing settings
            </button>
            <button
              type="button"
              id="btn-pricing-sync-cloud"
              data-jt-click="triggerModelsPricingCloudSync()"
              ${isSyncing ? 'disabled' : ''}
              aria-label="Sync model rates from Google Cloud"
              class="jt-btn jt-btn--primary px-3.5 py-1.5 rounded-lg disabled:opacity-60 disabled:cursor-not-allowed text-xs font-extrabold cursor-pointer transition inline-flex items-center gap-1.5"
            >
              <svg class="jt-ico ${isSyncing ? 'animate-spin' : ''}" aria-hidden="true"><use href="#ico-refresh"/></svg>
              <span>${isSyncing ? 'Syncing from Google Cloud…' : 'Sync from Google Cloud'}</span>
            </button>
          </div>
        </div>
      `);
    }

    function _renderPricingRatesTable(statsOpt = null) {
      const tbody = document.getElementById('pricing-rates-tbody');
      if (!tbody) return;

      const st = window._jtModelsPricingState;
      const cfg = st.config || {};
      const modelsObj = cfg.models || {};
      const stats = statsOpt || _computePricingKpiStats();
      const obsMap = stats.obsMap;
      const regionalMult = Number((cfg.billingSettings && cfg.billingSettings.regionalMultiplierDefault) || 1.1);

      const searchEl = document.getElementById('pricing-filter-search');
      const pubEl = document.getElementById('pricing-filter-publisher');
      const srcEl = document.getElementById('pricing-filter-source');
      const onlyUsedEl = document.getElementById('pricing-filter-only-used');
      const statusEl = document.getElementById('pricing-filter-status');

      const q = (searchEl ? searchEl.value : '').toLowerCase().trim();
      const pubFilter = pubEl ? pubEl.value : 'ALL';
      const srcFilter = srcEl ? srcEl.value : 'ALL';
      const onlyUsed = Boolean(onlyUsedEl && onlyUsedEl.checked);
      const statusFilter = statusEl ? statusEl.value : 'ALL';

      const entries = Object.entries(modelsObj).map(([modelId, m]) => {
        const obs = obsMap.get(modelId.toLowerCase()) || null;
        const calls = obs ? Number(obs.calls || 0) : 0;
        const vendor = String(m.publisher || m.vendor || 'google').toLowerCase();
        const source = String(m.source || 'BUILTIN_DEFAULT').toUpperCase();
        const manualOverride = _hasModelManualOverride(m);
        const inRate = Number(m.input ?? m.inputPer1M ?? 0);
        const outRate = Number(m.output ?? m.outputPer1M ?? 0);
        const thinkRate = Number(m.thinking ?? m.thinkingPer1M ?? outRate);
        const cacheRate = Number(m.cache_read_input ?? m.cacheHitPer1M ?? (inRate * 0.1));
        const regInRate = Number(m.regional_input ?? m.regionalInputPer1M ?? (inRate * regionalMult));
        const regOutRate = Number(m.regional_output ?? m.regionalOutputPer1M ?? (outRate * regionalMult));
        const isRegionalEstimated = !m.lastSkuIdRegional && !manualOverride;

        return {
          modelId,
          label: m.displayName || m.label || modelId,
          vendor,
          category: m.launchStage || m.category || 'GA',
          inRate,
          outRate,
          thinkRate,
          cacheRate,
          regInRate,
          regOutRate,
          isRegionalEstimated,
          source,
          manualOverride,
          updatedAt: m.updatedAt || cfg.updatedAt || '',
          lastSkuIdGlobal: m.lastSkuIdGlobal || '',
          lastSkuIdRegional: m.lastSkuIdRegional || '',
          deleted: _isModelDeleted(m),
          deletedAt: m.deletedAt || '',
          statusBadges: _renderPricingStatusBadges(m),
          calls,
          obs
        };
      });

      const filtered = entries.filter(item => {
        if (onlyUsed && item.calls <= 0) return false;
        if (statusFilter === 'ACTIVE' && item.deleted) return false;
        if (statusFilter === 'DELETED' && !item.deleted) return false;
        if (pubFilter !== 'ALL' && item.vendor !== pubFilter.toLowerCase()) return false;
        if (srcFilter !== 'ALL') {
          if (srcFilter === 'MANUAL' && !item.manualOverride) return false;
          if (srcFilter === 'ESTIMATED' && item.source !== 'CLOUD_MONITORING_DISCOVERED' && item.source !== 'ESTIMATED') return false;
          if (srcFilter === 'GCP_BILLING_API' || srcFilter === 'GCP_BILLING_CATALOG') {
            if (item.manualOverride || !item.source.startsWith('GCP_BILLING')) return false;
          } else if (srcFilter === 'VERTEX_PUBLISHER_API' || srcFilter === 'VERTEX_PUBLISHER_CATALOG') {
            if (item.manualOverride || !item.source.startsWith('VERTEX_PUBLISHER')) return false;
          } else if (srcFilter !== 'MANUAL' && srcFilter !== 'ESTIMATED' && (item.manualOverride || item.source !== srcFilter)) {
            return false;
          }
        }
        if (q) {
          const hay = `${item.modelId} ${item.label} ${item.vendor} ${item.source} ${item.lastSkuIdGlobal} ${item.lastSkuIdRegional}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      }).sort((a, b) => (Number(a.deleted) - Number(b.deleted)) || (b.calls - a.calls) || a.modelId.localeCompare(b.modelId));

      const ratesBadge = document.getElementById('subtab-badge-pricing-rates');
      if (ratesBadge) ratesBadge.textContent = String(filtered.length);

      if (filtered.length === 0) {
        setSafeHtml(tbody, `
          <tr>
            <td colspan="11" class="py-10 px-4 text-center text-xs text-slate-500">
              No models match the active filters. Try clearing the search or filter criteria.
            </td>
          </tr>
        `);
        return;
      }

      setSafeHtml(tbody, filtered.map(item => {
        const updatedShort = item.updatedAt ? String(item.updatedAt).slice(0, 10) : '—';
        const usedHtml = item.calls > 0
          ? `<span class="font-extrabold text-emerald-700 mono">${fmtNum(item.calls)} calls</span>`
          : `<span class="text-slate-400 mono">0</span>`;
        const regBadgeHint = item.isRegionalEstimated
          ? `<span class="text-amber-700 ml-1" title="Calculated using regional multiplier (${regionalMult.toFixed(2)}×)">*</span>`
          : '';

        return `
          <tr
            data-jt-click="openPricingModelDrawer(${jsArg(item.modelId)})"
            class="hover:bg-slate-50 transition cursor-pointer${item.deleted ? ' opacity-60' : ''}"
            title="Click to inspect SKUs, cost example, and manual override for ${escapeHtml(item.modelId)}"
          >
            <td class="py-3 px-4" data-sort-val="${escapeHtml(item.modelId)}">
              <div class="font-bold text-[#0F2A4A] mono">${escapeHtml(item.modelId)}</div>
              <div class="text-xs text-slate-500">${escapeHtml(item.label)}</div>
              ${item.statusBadges ? `<div class="mt-1 flex flex-wrap gap-1">${item.statusBadges}</div>` : ''}
            </td>
            <td class="py-3 px-4 capitalize text-slate-700 font-semibold" data-sort-val="${escapeHtml(item.vendor)}">
              ${escapeHtml(item.vendor)}
            </td>
            <td class="py-3 px-4 text-right mono font-bold text-slate-800" data-sort-val="${escapeHtml(item.inRate)}">
              ${escapeHtml(_fmtRatePer1M(item.inRate))}
            </td>
            <td class="py-3 px-4 text-right mono font-bold text-slate-800" data-sort-val="${escapeHtml(item.outRate)}">
              ${escapeHtml(_fmtRatePer1M(item.outRate))}
            </td>
            <td class="py-3 px-4 text-right mono text-slate-700" data-sort-val="${escapeHtml(item.thinkRate)}">
              ${escapeHtml(_fmtRatePer1M(item.thinkRate))}
            </td>
            <td class="py-3 px-4 text-right mono text-emerald-700" data-sort-val="${escapeHtml(item.cacheRate)}">
              ${escapeHtml(_fmtRatePer1M(item.cacheRate))}
            </td>
            <td class="py-3 px-4 text-right mono text-slate-700" data-sort-val="${escapeHtml(item.regInRate)}">
              ${escapeHtml(_fmtRatePer1M(item.regInRate))}${regBadgeHint}
            </td>
            <td class="py-3 px-4 text-right mono text-slate-700" data-sort-val="${escapeHtml(item.regOutRate)}">
              ${escapeHtml(_fmtRatePer1M(item.regOutRate))}${regBadgeHint}
            </td>
            <td class="py-3 px-4 whitespace-nowrap" data-sort-val="${escapeHtml(item.manualOverride ? 'MANUAL' : item.source)}">
              ${_renderPricingSourceBadge(item.source, item.manualOverride)}
            </td>
            <td class="py-3 px-4 mono text-xs text-slate-500 whitespace-nowrap" data-sort-val="${escapeHtml(updatedShort)}">
              ${escapeHtml(updatedShort)}
            </td>
            <td class="py-3 px-4 text-right whitespace-nowrap" data-sort-val="${escapeHtml(item.calls)}">
              ${usedHtml}
            </td>
          </tr>
        `;
      }).join(''));
    }

    function _renderPricingBillingSettingsBox() {
      const box = document.getElementById('pricing-billing-settings-box');
      if (!box) return;

      const st = window._jtModelsPricingState;
      const cfg = st.config || {};
      const bs = cfg.billingSettings || {};
      const vDisc = Number(bs.vertexBillingCreditDiscountPct ?? bs.vertexCreditDiscountPct ?? 0);
      const gDisc = Number(bs.geminiApiBillingCreditDiscountPct ?? bs.geminiApiCreditDiscountPct ?? 0);
      const iCache = Number(bs.vertexImplicitCacheHitRatioPct ?? bs.implicitCacheHitPct ?? 93);
      const rMult = Number(bs.regionalMultiplierDefault ?? 1.1);
      const usdEur = Number(bs.usdToEurRate ?? 0.92);
      const usdEurAuto = bs.usdToEurRateAuto !== false;
      const fx = (cfg.fxRate && typeof cfg.fxRate === 'object') ? cfg.fxRate : null;
      const fxLine = fx && Number.isFinite(Number(fx.usdToEur))
        ? `Google Cloud rate: ${Number(fx.usdToEur).toFixed(4)} €/$ (effective ${String(fx.effectiveTime || '').replace('T', ' ').replace('Z', ' UTC')})`
        : 'Google Cloud rate not synced yet: run "Sync from Google Cloud".';
      const gCache = Number(bs.geminiApiImplicitCacheHitRatioPct ?? 0);
      const msSav = Number(bs.managedServiceSavingsPct ?? 0);

      setSafeHtml(box, `
        <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-3">
          <div>
            <h3 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Billing Settings &amp; Cost Calculation Parameters
            </h3>
            <p class="text-xs text-slate-600 mt-0.5">
              Defaults: <code class="mono">0%</code> discounts, <code class="mono">93%</code> Vertex AI implicit cache hit, <code class="mono">1.10×</code> regional multiplier. Calibrate them on your Cloud Billing export (see Cost calibration). Saving recalculates the cached costs instantly, without a new scan.
            </p>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              id="btn-pricing-reset-settings"
              data-jt-click="resetPricingBillingSettingsToDefaults()"
              aria-label="Reset billing settings to neutral defaults"
              class="jt-btn-secondary px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 text-xs font-bold cursor-pointer transition"
            >
              Reset to defaults
            </button>
            <button
              type="button"
              id="btn-pricing-save-settings"
              data-jt-click="savePricingBillingSettings()"
              aria-label="Save billing settings"
              class="jt-btn jt-btn--primary px-4 py-1.5 rounded-lg text-xs font-extrabold cursor-pointer transition"
            >
              Save settings
            </button>
          </div>
        </div>

        <div id="pricing-settings-feedback" class="hidden rounded-lg px-3.5 py-2 text-xs font-semibold"></div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col justify-between gap-2">
            <div class="flex items-start justify-between gap-4">
              <div>
                <label for="pricing-cfg-vertex-discount" class="block text-xs font-extrabold text-[#0F2A4A]">
                  Vertex AI credit discount (%)
                </label>
                <p class="text-xs text-slate-600 mt-0.5">
                  0% = gross cost without discounts. Reduces estimated Vertex AI token spend by the negotiated commitment or credit percentage (0%–95%).
                </p>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <input
                  type="number"
                  id="pricing-cfg-vertex-discount"
                  aria-label="Vertex AI credit discount percentage"
                  min="0"
                  max="95"
                  step="0.5"
                  value="${escapeHtml(vDisc)}"
                  class="w-24 bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-right text-xs font-bold mono text-slate-900"
                />
                <span class="text-xs font-bold text-slate-500 mono">%</span>
              </div>
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col justify-between gap-2">
            <div class="flex items-start justify-between gap-4">
              <div>
                <label for="pricing-cfg-gemini-discount" class="block text-xs font-extrabold text-[#0F2A4A]">
                  Gemini API credit discount (%)
                </label>
                <p class="text-xs text-slate-600 mt-0.5">
                  0% = gross cost without discounts. Applies to Google AI Studio / Generative Language API token usage (0%–95%).
                </p>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <input
                  type="number"
                  id="pricing-cfg-gemini-discount"
                  aria-label="Gemini API credit discount percentage"
                  min="0"
                  max="95"
                  step="0.5"
                  value="${escapeHtml(gDisc)}"
                  class="w-24 bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-right text-xs font-bold mono text-slate-900"
                />
                <span class="text-xs font-bold text-slate-500 mono">%</span>
              </div>
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col justify-between gap-2">
            <div class="flex items-start justify-between gap-4">
              <div>
                <label for="pricing-cfg-implicit-cache" class="block text-xs font-extrabold text-[#0F2A4A]">
                  Implicit cache hit (%)
                </label>
                <p class="text-xs text-slate-600 mt-0.5">
                  0% = only explicit cached tokens reported by Cloud Monitoring receive cached-read pricing. Set &gt; 0% (up to 98%) only to model synthetic implicit caching when uncached.
                </p>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <input
                  type="number"
                  id="pricing-cfg-implicit-cache"
                  aria-label="Implicit cache hit percentage"
                  min="0"
                  max="98"
                  step="0.5"
                  value="${escapeHtml(iCache)}"
                  class="w-24 bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-right text-xs font-bold mono text-slate-900"
                />
                <span class="text-xs font-bold text-slate-500 mono">%</span>
              </div>
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col justify-between gap-2">
            <div class="flex items-start justify-between gap-4">
              <div>
                <label for="pricing-cfg-regional-mult" class="block text-xs font-extrabold text-[#0F2A4A]">
                  Regional multiplier (×)
                </label>
                <p class="text-xs text-slate-600 mt-0.5">
                  1.10× = +10% regional premium applied to non-global endpoints (e.g. <code class="mono">europe-west8</code>, <code class="mono">europe-west1</code>) when no dedicated regional SKU is matched (1.00×–3.00×).
                </p>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <input
                  type="number"
                  id="pricing-cfg-regional-mult"
                  aria-label="Regional multiplier"
                  min="1.0"
                  max="3.0"
                  step="0.05"
                  value="${escapeHtml(rMult.toFixed(2))}"
                  class="w-24 bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-right text-xs font-bold mono text-slate-900"
                />
                <span class="text-xs font-bold text-slate-500 mono">×</span>
              </div>
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col justify-between gap-2">
            <div class="flex items-start justify-between gap-4">
              <div>
                <label for="pricing-cfg-usd-eur" class="block text-xs font-extrabold text-[#0F2A4A]">
                  USD → EUR rate (€ per $1)
                </label>
                <p class="text-xs text-slate-600 mt-0.5">
                  Used only to display euro amounts; USD figures are unaffected. With automatic mode the rate comes from the Google Cloud billing catalog on every sync, so euro totals follow the rate Google applies to your invoice. The manual value (0.50–1.50) is used when automatic mode is off or not synced yet. Past months are shown at the current rate.
                </p>
                <label class="mt-2 flex items-center gap-2 text-xs font-bold text-slate-700">
                  <input type="checkbox" id="pricing-cfg-usd-eur-auto" aria-label="Use the Google Cloud billing exchange rate automatically" ${usdEurAuto ? 'checked' : ''} />
                  Use the Google Cloud billing rate automatically
                </label>
                <p class="text-xs text-slate-500 mono mt-1">${escapeHtml(fxLine)}</p>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <input
                  type="number"
                  id="pricing-cfg-usd-eur"
                  aria-label="USD to EUR conversion rate"
                  min="0.5"
                  max="1.5"
                  step="0.001"
                  value="${escapeHtml(usdEur.toFixed(4))}"
                  class="w-24 bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-right text-xs font-bold mono text-slate-900"
                />
                <span class="text-xs font-bold text-slate-500 mono">€/$</span>
              </div>
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col justify-between gap-2">
            <div class="flex items-start justify-between gap-4">
              <div>
                <label for="pricing-cfg-gemini-cache" class="block text-xs font-extrabold text-[#0F2A4A]">
                  Gemini API default cache hit (%)
                </label>
                <p class="text-xs text-slate-600 mt-0.5">
                  Share of Gemini API (AI Studio) input tokens billed at the cached rate, for models without their own value in the model drawer. Google does not report cached tokens separately: calibrate it on your invoice (0%–98%).
                </p>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <input
                  type="number"
                  id="pricing-cfg-gemini-cache"
                  aria-label="Gemini API default cache hit percentage"
                  min="0"
                  max="98"
                  step="0.5"
                  value="${escapeHtml(gCache)}"
                  class="w-24 bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-right text-xs font-bold mono text-slate-900"
                />
                <span class="text-xs font-bold text-slate-500 mono">%</span>
              </div>
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col justify-between gap-2">
            <div class="flex items-start justify-between gap-4">
              <div>
                <label for="pricing-cfg-managed-savings" class="block text-xs font-extrabold text-[#0F2A4A]">
                  Managed services savings (%)
                </label>
                <p class="text-xs text-slate-600 mt-0.5">
                  Discount applied to the call-based estimates for Agentspace / Gemini Enterprise / Cloud AI Companion. 0% = list-price estimate; 100% = not charged on this billing account (e.g. a per-user licence billed elsewhere): usage stays visible but its cost is 0 (0%–100%).
                </p>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <input
                  type="number"
                  id="pricing-cfg-managed-savings"
                  aria-label="Managed services savings percentage"
                  min="0"
                  max="100"
                  step="0.5"
                  value="${escapeHtml(msSav)}"
                  class="w-24 bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-right text-xs font-bold mono text-slate-900"
                />
                <span class="text-xs font-bold text-slate-500 mono">%</span>
              </div>
            </div>
          </div>


        </div>
      `);
    }

    function _showPricingSettingsFeedback(tone, msg) {
      const fb = document.getElementById('pricing-settings-feedback');
      if (!fb) return;
      fb.classList.remove('hidden', 'bg-emerald-50', 'text-emerald-800', 'border-emerald-200', 'bg-rose-50', 'text-rose-800', 'border-rose-200');
      if (tone === 'ok') {
        fb.classList.add('bg-emerald-50', 'text-emerald-800', 'border', 'border-emerald-200');
      } else {
        fb.classList.add('bg-rose-50', 'text-rose-800', 'border', 'border-rose-200');
      }
      fb.textContent = msg;
    }

    async function _submitBillingSettingsPayload(billingSettings) {
      try {
        const resp = await fetch('/api/models-pricing/config', {
          signal: AbortSignal.timeout(30000),
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ billingSettings })
        });
        const data = await resp.json();
        const isOk = resp.ok && (data.success === true || data.status === 'ok');
        if (!isOk) {
          throw new Error(data.error || (data.errors && data.errors.join('; ')) || data.message || `HTTP ${resp.status}`);
        }
        const st = window._jtModelsPricingState;
        st.config = data.config || st.config;
        if (Array.isArray(data.observed)) {
          st.observedModels = data.observed;
        } else if (Array.isArray(data.observedModels)) {
          st.observedModels = data.observedModels;
        }
        st.lastLoadedAt = Date.now();
        _renderPricingViewContents();
        _showPricingSettingsFeedback('ok', 'Billing settings saved and applied to cost calculations.');
      } catch (err) {
        _showPricingSettingsFeedback('err', err && err.message ? err.message : 'Failed to save billing settings.');
      }
    }

    async function savePricingBillingSettings() {
      const vEl = document.getElementById('pricing-cfg-vertex-discount');
      const gEl = document.getElementById('pricing-cfg-gemini-discount');
      const cEl = document.getElementById('pricing-cfg-implicit-cache');
      const rEl = document.getElementById('pricing-cfg-regional-mult');
      const eEl = document.getElementById('pricing-cfg-usd-eur');
      const eAutoEl = document.getElementById('pricing-cfg-usd-eur-auto');
      const gcEl = document.getElementById('pricing-cfg-gemini-cache');
      const msEl = document.getElementById('pricing-cfg-managed-savings');

      const eVal = Number(eEl ? eEl.value : 0.92);
      const gcVal = Number(gcEl ? gcEl.value : 0);
      const msVal = Number(msEl ? msEl.value : 0);
      const vVal = Number(vEl ? vEl.value : 0);
      const gVal = Number(gEl ? gEl.value : 0);
      const cVal = Number(cEl ? cEl.value : 0);
      const rVal = Number(rEl ? rEl.value : 1.1);

      if (Number.isNaN(vVal) || vVal < 0 || vVal > 95) {
        _showPricingSettingsFeedback('err', 'Vertex AI credit discount must be between 0% and 95%.');
        return;
      }
      if (Number.isNaN(gVal) || gVal < 0 || gVal > 95) {
        _showPricingSettingsFeedback('err', 'Gemini API credit discount must be between 0% and 95%.');
        return;
      }
      if (Number.isNaN(cVal) || cVal < 0 || cVal > 98) {
        _showPricingSettingsFeedback('err', 'Implicit cache hit percentage must be between 0% and 98%.');
        return;
      }
      if (Number.isNaN(rVal) || rVal < 1.0 || rVal > 3.0) {
        _showPricingSettingsFeedback('err', 'Regional multiplier must be between 1.00× and 3.00×.');
        return;
      }

      if (Number.isNaN(eVal) || eVal < 0.5 || eVal > 1.5) {
        _showPricingSettingsFeedback('err', 'USD to EUR rate must be between 0.50 and 1.50.');
        return;
      }

      if (Number.isNaN(gcVal) || gcVal < 0 || gcVal > 98) {
        _showPricingSettingsFeedback('err', 'Gemini API default cache hit must be between 0% and 98%.');
        return;
      }
      if (Number.isNaN(msVal) || msVal < 0 || msVal > 100) {
        _showPricingSettingsFeedback('err', 'Managed services savings must be between 0% and 100%.');
        return;
      }

      await _submitBillingSettingsPayload({
        vertexBillingCreditDiscountPct: vVal,
        geminiApiBillingCreditDiscountPct: gVal,
        vertexImplicitCacheHitRatioPct: cVal,
        regionalMultiplierDefault: rVal,
        usdToEurRate: eVal,
        usdToEurRateAuto: eAutoEl ? !!eAutoEl.checked : true,
        geminiApiImplicitCacheHitRatioPct: gcVal,
        managedServiceSavingsPct: msVal
      });
    }
    window.savePricingBillingSettings = savePricingBillingSettings;

    async function resetPricingBillingSettingsToDefaults() {
      await _submitBillingSettingsPayload({
        vertexBillingCreditDiscountPct: 0.0,
        geminiApiBillingCreditDiscountPct: 0.0,
        vertexImplicitCacheHitRatioPct: 93.0,
        regionalMultiplierDefault: 1.10,
        usdToEurRate: 0.92,
        usdToEurRateAuto: true,
        geminiApiImplicitCacheHitRatioPct: 0.0,
        managedServiceSavingsPct: 0.0
      });
    }
    window.resetPricingBillingSettingsToDefaults = resetPricingBillingSettingsToDefaults;

    function _renderPricingCoverageTables(statsOpt = null) {
      const unpricedTbody = document.getElementById('pricing-unpriced-tbody');
      const unusedTbody = document.getElementById('pricing-unused-tbody');
      if (!unpricedTbody || !unusedTbody) return;

      const st = window._jtModelsPricingState;
      const cfg = st.config || {};
      const modelsObj = cfg.models || {};
      const stats = statsOpt || _computePricingKpiStats();
      const obsMap = stats.obsMap;

      const unpricedList = stats.unpricedObserved || [];
      const unusedList = [];
      Object.entries(modelsObj).forEach(([modelId, m]) => {
        if (_isModelDeleted(m)) return;
        const obs = obsMap.get(modelId.toLowerCase());
        const calls = obs ? Number(obs.calls || 0) : 0;
        if (calls <= 0) {
          unusedList.push({ modelId, m });
        }
      });

      const covBadge = document.getElementById('subtab-badge-pricing-coverage');
      if (covBadge) covBadge.textContent = String(unpricedList.length);
      const unpricedCountBadge = document.getElementById('pricing-unpriced-count-badge');
      if (unpricedCountBadge) unpricedCountBadge.textContent = String(unpricedList.length);
      const unusedCountBadge = document.getElementById('pricing-unused-count-badge');
      if (unusedCountBadge) unusedCountBadge.textContent = String(unusedList.length);

      if (unpricedList.length === 0) {
        setSafeHtml(unpricedTbody, `
          <tr>
            <td colspan="4" class="py-8 px-4 text-center text-xs text-emerald-700 font-semibold">
              All models observed in the last scan have explicit catalog or manual rates.
            </td>
          </tr>
        `);
      } else {
        setSafeHtml(unpricedTbody, unpricedList.map(({ obs, catEntry }) => {
          const mId = obs.modelId || obs.baseModel || 'unknown';
          const projs = (obs.projects || []).join(', ') || '—';
          const inFallbackVal = obs.inputRate ?? (catEntry ? (catEntry.input ?? catEntry.inputPer1M) : 0.50);
          const outFallbackVal = obs.outputRate ?? (catEntry ? (catEntry.output ?? catEntry.outputPer1M) : 2.50);
          const fallbackIn = _fmtRatePer1M(inFallbackVal);
          const fallbackOut = _fmtRatePer1M(outFallbackVal);
          return `
            <tr
              data-jt-click="openPricingModelDrawer(${jsArg(mId)})"
              class="hover:bg-amber-50/50 transition cursor-pointer"
              title="Click to configure an explicit rate for ${escapeHtml(mId)}"
            >
              <td class="py-3 px-4 font-bold text-[#0F2A4A] mono" data-sort-val="${escapeHtml(mId)}">${escapeHtml(mId)}</td>
              <td class="py-3 px-4 mono text-slate-600">${escapeHtml(projs)}</td>
              <td class="py-3 px-4 text-right mono font-bold text-slate-800" data-sort-val="${escapeHtml(obs.calls || 0)}">${fmtNum(obs.calls || 0)}</td>
              <td class="py-3 px-4 text-right mono text-amber-800 font-semibold">${escapeHtml(fallbackIn)} in / ${escapeHtml(fallbackOut)} out</td>
            </tr>
          `;
        }).join(''));
      }

      if (unusedList.length === 0) {
        setSafeHtml(unusedTbody, `
          <tr>
            <td colspan="4" class="py-8 px-4 text-center text-xs text-slate-500">
              Every model in the pricing catalog was observed in the last scan.
            </td>
          </tr>
        `);
      } else {
        setSafeHtml(unusedTbody, unusedList.map(({ modelId, m }) => {
          const vendor = String(m.publisher || m.vendor || 'google');
          const inStr = _fmtRatePer1M(m.input ?? m.inputPer1M ?? 0);
          const outStr = _fmtRatePer1M(m.output ?? m.outputPer1M ?? 0);
          return `
            <tr
              data-jt-click="openPricingModelDrawer(${jsArg(modelId)})"
              class="hover:bg-slate-50 transition cursor-pointer"
              title="Click to inspect ${escapeHtml(modelId)}"
            >
              <td class="py-3 px-4" data-sort-val="${escapeHtml(modelId)}">
                <div class="font-bold text-[#0F2A4A] mono">${escapeHtml(modelId)}</div>
                <div class="text-xs text-slate-500">${escapeHtml(m.displayName || m.label || modelId)}</div>
              </td>
              <td class="py-3 px-4 capitalize text-slate-700 font-semibold">${escapeHtml(vendor)}</td>
              <td class="py-3 px-4 text-right mono text-slate-800">${escapeHtml(inStr)} / ${escapeHtml(outStr)}</td>
              <td class="py-3 px-4 whitespace-nowrap">${_renderPricingSourceBadge(m.source, _hasModelManualOverride(m))}</td>
            </tr>
          `;
        }).join(''));
      }
    }

    function _effectiveUsdToEurFromConfig(cfg) {
      const bs = (cfg && cfg.billingSettings) || {};
      const fx = cfg && cfg.fxRate;
      if (bs.usdToEurRateAuto !== false && fx && Number.isFinite(Number(fx.usdToEur)) && Number(fx.usdToEur) >= 0.5 && Number(fx.usdToEur) <= 1.5) return Number(fx.usdToEur);
      return Number(bs.usdToEurRate);
    }

    function _syncUsdToEurRateFromConfig() {
      const st = window._jtModelsPricingState || {};
      const rate = _effectiveUsdToEurFromConfig(st.config);
      if (Number.isFinite(rate) && typeof setUsdToEurRate === 'function' && setUsdToEurRate(rate) && typeof refreshDashboardView === 'function' && typeof globalScanData !== 'undefined' && globalScanData) {
        refreshDashboardView();
      }
    }

    // Column sorting for the Pricing tables. Rows are reordered in the DOM using each cell's data-sort-val (or its text);
    // numbers compare as numbers. The default order (set by the renderers) is kept until a header is clicked.
    const JT_PRICING_SORT_TABLES = ['pricing-rates-table', 'pricing-unpriced-table', 'pricing-unused-table'];
    const _jtPricingSortState = {};

    function _pricingSortCompare(a, b) {
      const na = Number(a), nb = Number(b);
      if (a !== '' && b !== '' && Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
      return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
    }

    function _applyPricingSort(tableId) {
      const table = document.getElementById(tableId);
      const st = _jtPricingSortState[tableId];
      if (!table) return;
      table.querySelectorAll('thead th').forEach((th, i) => {
        const on = st && st.col === i;
        th.setAttribute('aria-sort', on ? (st.asc ? 'ascending' : 'descending') : 'none');
        const mark = th.querySelector('.jt-sort-mark');
        if (mark) mark.textContent = on ? (st.asc ? ' ▲' : ' ▼') : ' ⇅';
      });
      if (!st) return;
      const tbody = table.querySelector('tbody');
      if (!tbody) return;
      const rows = Array.from(tbody.querySelectorAll(':scope > tr')).filter(tr => tr.querySelectorAll(':scope > td').length > 1);
      const keyOf = (tr) => {
        const td = tr.querySelectorAll(':scope > td')[st.col];
        if (!td) return '';
        return td.dataset.sortVal !== undefined ? td.dataset.sortVal : (td.innerText || td.textContent || '').trim();
      };
      rows.sort((ra, rb) => (st.asc ? 1 : -1) * _pricingSortCompare(keyOf(ra), keyOf(rb)));
      rows.forEach(tr => tbody.appendChild(tr));
    }

    function sortPricingTable(tableId, col) {
      const cur = _jtPricingSortState[tableId];
      _jtPricingSortState[tableId] = { col, asc: cur && cur.col === col ? !cur.asc : true };
      _applyPricingSort(tableId);
    }
    window.sortPricingTable = sortPricingTable;

    function _initPricingSortHeaders() {
      JT_PRICING_SORT_TABLES.forEach(id => {
        const table = document.getElementById(id);
        if (!table) return;
        table.querySelectorAll('thead th').forEach((th, i) => {
          if (th.dataset.jtSortInit) return;
          th.dataset.jtSortInit = '1';
          th.classList.add('cursor-pointer', 'select-none');
          th.setAttribute('tabindex', '0');
          th.setAttribute('aria-sort', 'none');
          const mark = document.createElement('span');
          mark.className = 'jt-sort-mark text-slate-300';
          mark.textContent = ' ⇅';
          th.appendChild(mark);
          const go = () => sortPricingTable(id, i);
          th.addEventListener('click', go);
          th.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
        });
      });
    }

    function _applyAllPricingSorts() {
      _initPricingSortHeaders();
      JT_PRICING_SORT_TABLES.forEach(_applyPricingSort);
    }

    function _renderPricingViewContents() {
      _syncUsdToEurRateFromConfig();
      const stats = _computePricingKpiStats();
      _renderPricingKpiGrid(stats);
      _renderPricingStatusBanner();
      _renderPricingRatesTable(stats);
      _renderPricingBillingSettingsBox();
      _renderPricingCoverageTables(stats);
      _applyAllPricingSorts();
      applyActiveSubTab('pricing');
    }

    function renderPricingAndRatesTab() {
      const st = window._jtModelsPricingState;
      if (!st.config && !st.loading) {
        loadModelsPricingData(false);
        return;
      }
      _renderPricingViewContents();
    }
    window.renderPricingAndRatesTab = renderPricingAndRatesTab;

    // =========================================================================
    // MODEL DETAIL & MANUAL OVERRIDE DRAWER
    // =========================================================================
    function openPricingModelDrawer(modelId) {
      const modal = document.getElementById('pricing-model-modal');
      const titleEl = document.getElementById('modal-pricing-model-title');
      const subEl = document.getElementById('modal-pricing-model-subtitle');
      const bodyEl = document.getElementById('modal-pricing-model-body');
      if (!modal || !bodyEl) return;

      const st = window._jtModelsPricingState;
      const cfg = st.config || (globalScanData && globalScanData.modelsPricingConfig) || {};
      const modelsObj = cfg.models || {};
      const obsMap = _buildObservedModelsMap();
      const bSettings = cfg.billingSettings || {};
      const regionalMult = Number(bSettings.regionalMultiplierDefault || 1.1);
      const vertexDiscPct = Number(bSettings.vertexBillingCreditDiscountPct ?? bSettings.vertexCreditDiscountPct ?? 0);
      const gemCacheDefault = Number(bSettings.geminiApiImplicitCacheHitRatioPct ?? 0);

      const cleanId = String(modelId || '').trim();
      const isNewModel = !cleanId;
      const m = (!isNewModel && modelsObj[cleanId]) ? modelsObj[cleanId] : {
        displayName: cleanId || '',
        publisher: 'google',
        launchStage: 'GA',
        input: 1.25,
        output: 5.0,
        thinking: 5.0,
        cache_read_input: 0.125,
        regional_input: Number((1.25 * regionalMult).toFixed(4)),
        regional_output: Number((5.0 * regionalMult).toFixed(4)),
        regional_cache_read_input: Number((0.125 * regionalMult).toFixed(4)),
        source: isNewModel ? 'MANUAL' : 'ESTIMATED',
        manualOverride: isNewModel ? { input: 1.25, output: 5.0 } : null,
        lastSkuIdGlobal: '',
        lastSkuIdRegional: '',
        updatedAt: ''
      };

      const obs = cleanId ? (obsMap.get(cleanId.toLowerCase()) || null) : null;
      const source = String(m.source || 'BUILTIN_DEFAULT').toUpperCase();
      const isManual = _hasModelManualOverride(m);
      const isRegEstimated = !m.lastSkuIdRegional && !isManual;
      const displayLabel = m.displayName || m.label || cleanId;
      const vendor = String(m.publisher || m.vendor || 'google').toLowerCase();
      const gemCacheOwn = (typeof m.geminiApiCacheHitRatioPct === 'number' && Number.isFinite(m.geminiApiCacheHitRatioPct)) ? m.geminiApiCacheHitRatioPct : null;
      const gemRates = (m.geminiApiRates && typeof m.geminiApiRates === 'object') ? m.geminiApiRates : null;

      const inRate = Number(m.input ?? m.inputPer1M ?? 0);
      const outRate = Number(m.output ?? m.outputPer1M ?? 0);
      const thinkRate = Number(m.thinking ?? m.thinkingPer1M ?? outRate);
      const cacheRate = Number(m.cache_read_input ?? m.cacheHitPer1M ?? (inRate * 0.1));
      const regInRate = Number(m.regional_input ?? m.regionalInputPer1M ?? (inRate * regionalMult));
      const regOutRate = Number(m.regional_output ?? m.regionalOutputPer1M ?? (outRate * regionalMult));
      const regCacheRate = Number(m.regional_cache_read_input ?? m.regionalCacheHitPer1M ?? (cacheRate * regionalMult));

      // Deterministic cost example: 1M input + 1M output
      const exampleGlobalUsd = inRate + outRate;
      const exampleRegionalUsd = regInRate + regOutRate;
      const exampleNetVertexUsd = exampleGlobalUsd * Math.max(0, 1 - vertexDiscPct / 100);

      if (titleEl) {
        setSafeHtml(titleEl, `
          <span>${escapeHtml(isNewModel ? 'Add Custom Model Rate' : cleanId)}</span>
          ${_renderPricingSourceBadge(source, isManual)}
          ${_renderPricingStatusBadges(m)}
        `);
      }
      if (subEl) {
        subEl.textContent = isNewModel
          ? 'Define a manual USD per 1M tokens rate override'
          : `${displayLabel} · Publisher: ${vendor.toUpperCase()} · Updated: ${(m.updatedAt || cfg.updatedAt || '—').slice(0, 10)}`;
      }

      const projectsUsed = obs && Array.isArray(obs.projects) && obs.projects.length > 0 ? obs.projects : [];
      const regionsList = obs ? (Array.isArray(obs.locations) ? obs.locations : (Array.isArray(obs.regions) ? obs.regions : [])) : [];

      setSafeHtml(bodyEl, `
        <!-- Section 1: Deterministic Cost Example & SKU Provenance -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
            <div class="text-xs font-bold uppercase tracking-wider text-slate-500">Global Cost Example</div>
            <div class="text-lg font-extrabold text-[#0F2A4A] mono">1M input + 1M output = ${escapeHtml(fmtUsd(exampleGlobalUsd))}</div>
            <div class="text-xs text-slate-600 mono">
              Input: ${escapeHtml(_fmtRatePer1M(inRate))} · Output: ${escapeHtml(_fmtRatePer1M(outRate))}
              ${vertexDiscPct > 0 ? ` · Net (-${escapeHtml(vertexDiscPct)}%): <b>${escapeHtml(fmtUsd(exampleNetVertexUsd))}</b>` : ''}
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
            <div class="text-xs font-bold uppercase tracking-wider text-slate-500">EU / Regional Example</div>
            <div class="text-lg font-extrabold text-[#0F2A4A] mono">1M input + 1M output = ${escapeHtml(fmtUsd(exampleRegionalUsd))}</div>
            <div class="text-xs text-slate-600 mono">
              Reg. In: ${escapeHtml(_fmtRatePer1M(regInRate))} · Reg. Out: ${escapeHtml(_fmtRatePer1M(regOutRate))}
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
            <div class="text-xs font-bold uppercase tracking-wider text-slate-500">Cloud Billing SKU IDs</div>
            <div class="text-xs text-slate-700 mono">Global SKU: <b>${escapeHtml(m.lastSkuIdGlobal || '—')}</b></div>
            <div class="text-xs text-slate-700 mono">Regional SKU: <b>${escapeHtml(m.lastSkuIdRegional || '—')}</b></div>
            <div class="text-xs text-slate-500">Updated: <span class="mono">${escapeHtml((m.updatedAt || cfg.updatedAt || '—').slice(0, 19).replace('T', ' '))}</span></div>
          </div>
        </div>

        ${_renderCatalogRatesSection(m)}

        <!-- Section 2: Per-Field Rate Breakdown & Source -->
        <div class="jt-table-panel bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div class="px-4 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <h3 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]">Rate Breakdown by Token Type (USD per 1M tokens)</h3>
            <span class="text-xs text-slate-500 mono">Stage: ${escapeHtml(m.launchStage || m.category || 'GA')}</span>
          </div>
          <div class="overflow-x-auto">
            <table class="jt-table w-full text-left border-collapse">
              <thead>
                <tr class="border-b border-slate-200 text-xs font-bold uppercase tracking-wider text-slate-500 bg-slate-50">
                  <th scope="col" class="py-2.5 px-4">Rate Field</th>
                  <th scope="col" class="py-2.5 px-4 text-right">Global ($ / 1M)</th>
                  <th scope="col" class="py-2.5 px-4">Global Source</th>
                  <th scope="col" class="py-2.5 px-4 text-right">Regional ($ / 1M)</th>
                  <th scope="col" class="py-2.5 px-4">Regional Source</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 text-xs">
                <tr>
                  <td class="py-2.5 px-4 font-bold text-slate-800">Input tokens</td>
                  <td class="py-2.5 px-4 text-right mono font-bold">${escapeHtml(_fmtRatePer1M(inRate))}</td>
                  <td class="py-2.5 px-4">${_renderPricingSourceBadge(source, isManual)}</td>
                  <td class="py-2.5 px-4 text-right mono font-bold">${escapeHtml(_fmtRatePer1M(regInRate))}</td>
                  <td class="py-2.5 px-4">${_renderPricingSourceBadge(source, isManual, isRegEstimated)}</td>
                </tr>
                <tr>
                  <td class="py-2.5 px-4 font-bold text-slate-800">Output tokens</td>
                  <td class="py-2.5 px-4 text-right mono font-bold">${escapeHtml(_fmtRatePer1M(outRate))}</td>
                  <td class="py-2.5 px-4">${_renderPricingSourceBadge(source, isManual)}</td>
                  <td class="py-2.5 px-4 text-right mono font-bold">${escapeHtml(_fmtRatePer1M(regOutRate))}</td>
                  <td class="py-2.5 px-4">${_renderPricingSourceBadge(source, isManual, isRegEstimated)}</td>
                </tr>
                <tr>
                  <td class="py-2.5 px-4 font-bold text-slate-800">Thinking / reasoning tokens</td>
                  <td class="py-2.5 px-4 text-right mono font-bold">${escapeHtml(_fmtRatePer1M(thinkRate))}</td>
                  <td class="py-2.5 px-4">${_renderPricingSourceBadge(source, isManual)}</td>
                  <td class="py-2.5 px-4 text-right mono font-bold">${escapeHtml(_fmtRatePer1M(regOutRate))}</td>
                  <td class="py-2.5 px-4">${_renderPricingSourceBadge(source, isManual, isRegEstimated)}</td>
                </tr>
                <tr>
                  <td class="py-2.5 px-4 font-bold text-slate-800">Cache read tokens</td>
                  <td class="py-2.5 px-4 text-right mono font-bold text-emerald-700">${escapeHtml(_fmtRatePer1M(cacheRate))}</td>
                  <td class="py-2.5 px-4">${_renderPricingSourceBadge(source, isManual)}</td>
                  <td class="py-2.5 px-4 text-right mono font-bold text-emerald-700">${escapeHtml(_fmtRatePer1M(regCacheRate))}</td>
                  <td class="py-2.5 px-4">${_renderPricingSourceBadge(source, isManual, isRegEstimated)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Section 3: Observed Usage in Last Scan (Projects & Regions, zero personal data) -->
        <div class="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]">Observed Activity in Last Scan</h3>
            <span class="mono text-xs font-bold ${obs && obs.calls > 0 ? 'text-emerald-700' : 'text-slate-500'}">
              ${obs && obs.calls > 0 ? `${fmtNum(obs.calls)} calls · ${fmtTok(obs.totalTokens || 0)} tokens · ${fmtUsd(obs.costUsd || 0)}` : '0 calls observed in last scan'}
            </span>
          </div>
          <div class="text-xs text-slate-600 flex flex-wrap items-center gap-2">
            <span>Projects using this model:</span>
            ${projectsUsed.length > 0
              ? projectsUsed.map(pid => `<span class="jt-chip jt-chip--navy mono text-xs">${escapeHtml(pid)}</span>`).join(' ')
              : '<span class="text-slate-400">None in current scan window</span>'}
          </div>
          ${regionsList.length > 0 ? `
            <div class="text-xs text-slate-600 flex flex-wrap items-center gap-2">
              <span>Regions:</span>
              ${regionsList.map(r => `<span class="jt-chip jt-chip--gray mono text-xs">${escapeHtml(r)}</span>`).join(' ')}
            </div>
          ` : ''}
        </div>

        <!-- Section 4: Manual Override Form -->
        <div class="p-4 rounded-xl bg-white border border-slate-200 space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]">Manual Rate Override (USD per 1M tokens)</h3>
              <p class="text-xs text-slate-600 mt-0.5">Saving a manual override marks this model as <code class="mono">MANUAL</code> so future Cloud Billing syncs will not overwrite your custom rates.</p>
            </div>
            ${(!isNewModel && isManual) ? `
              <button
                type="button"
                data-jt-click="resetPricingModelManualOverride(${jsArg(cleanId)})"
                class="jt-btn-secondary px-3 py-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-800 border border-rose-200 text-xs font-bold cursor-pointer transition"
              >
                Remove manual override
              </button>
            ` : ''}
          </div>

          <div id="pricing-drawer-feedback" class="hidden rounded-lg px-3.5 py-2 text-xs font-semibold"></div>

          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label for="pricing-ov-model-id" class="block text-xs font-bold text-slate-700 mb-1">Model ID</label>
              <input
                type="text"
                id="pricing-ov-model-id"
                aria-label="Model ID"
                value="${escapeHtml(cleanId)}"
                ${isNewModel ? '' : 'readonly'}
                placeholder="e.g. gemini-2.5-pro"
                class="w-full bg-slate-50 border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs font-bold mono text-slate-900"
              />
            </div>
            <div>
              <label for="pricing-ov-label" class="block text-xs font-bold text-slate-700 mb-1">Display Label</label>
              <input
                type="text"
                id="pricing-ov-label"
                aria-label="Model display label"
                value="${escapeHtml(displayLabel)}"
                placeholder="e.g. Gemini 2.5 Pro"
                class="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs text-slate-900"
              />
            </div>
            <div>
              <label for="pricing-ov-vendor" class="block text-xs font-bold text-slate-700 mb-1">Publisher</label>
              <select
                id="pricing-ov-vendor"
                aria-label="Model publisher"
                class="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-900"
              >
                ${['google', 'anthropic', 'meta', 'mistral', 'deepseek', 'partner'].map(v => `
                  <option value="${escapeHtml(v)}" ${vendor === v ? 'selected' : ''}>${escapeHtml(v.toUpperCase())}</option>
                `).join('')}
              </select>
            </div>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <div>
              <label for="pricing-ov-input" class="block text-xs font-bold text-slate-700 mb-1">Input ($ / 1M)</label>
              <input type="number" id="pricing-ov-input" aria-label="Input USD per 1M tokens" min="0" max="1000" step="0.0001" value="${escapeHtml(inRate)}" class="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs font-bold mono text-slate-900" />
            </div>
            <div>
              <label for="pricing-ov-output" class="block text-xs font-bold text-slate-700 mb-1">Output ($ / 1M)</label>
              <input type="number" id="pricing-ov-output" aria-label="Output USD per 1M tokens" min="0" max="1000" step="0.0001" value="${escapeHtml(outRate)}" class="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs font-bold mono text-slate-900" />
            </div>
            <div>
              <label for="pricing-ov-thinking" class="block text-xs font-bold text-slate-700 mb-1">Thinking ($ / 1M)</label>
              <input type="number" id="pricing-ov-thinking" aria-label="Thinking USD per 1M tokens" min="0" max="1000" step="0.0001" value="${escapeHtml(thinkRate)}" class="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs font-bold mono text-slate-900" />
            </div>
            <div>
              <label for="pricing-ov-cache" class="block text-xs font-bold text-slate-700 mb-1">Cache read ($ / 1M)</label>
              <input type="number" id="pricing-ov-cache" aria-label="Cache read USD per 1M tokens" min="0" max="1000" step="0.0001" value="${escapeHtml(cacheRate)}" class="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs font-bold mono text-slate-900" />
            </div>
            <div>
              <label for="pricing-ov-reg-input" class="block text-xs font-bold text-slate-700 mb-1">Regional input ($ / 1M)</label>
              <input type="number" id="pricing-ov-reg-input" aria-label="Regional input USD per 1M tokens" min="0" max="1000" step="0.0001" value="${escapeHtml(regInRate)}" class="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs font-bold mono text-slate-900" />
            </div>
            <div>
              <label for="pricing-ov-reg-output" class="block text-xs font-bold text-slate-700 mb-1">Regional output ($ / 1M)</label>
              <input type="number" id="pricing-ov-reg-output" aria-label="Regional output USD per 1M tokens" min="0" max="1000" step="0.0001" value="${escapeHtml(regOutRate)}" class="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs font-bold mono text-slate-900" />
            </div>
          </div>

          <div class="pt-2 flex items-center justify-end gap-2">
            <button
              type="button"
              data-jt-click="savePricingModelManualOverride()"
              class="jt-btn jt-btn--primary px-4 py-1.5 rounded-lg text-xs font-extrabold cursor-pointer transition"
            >
              Save manual override
            </button>
          </div>

          ${isNewModel ? '' : `
          <div class="mt-2 pt-4 border-t border-slate-200 space-y-2">
            <h4 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]">Gemini API (AI Studio) cache hit</h4>
            <p class="text-xs text-slate-600">
              Share of this model's Gemini API input tokens billed at the cached rate. Google does not report cached tokens separately, so calibrate it on your invoice.
              Leave empty to use the default (<code class="mono">${escapeHtml(gemCacheDefault)}%</code>). It does not change the rates above.
            </p>
            ${gemRates ? `<p class="text-xs text-slate-500 mono">Gemini API catalog rates ($ / 1M): input ${escapeHtml(_fmtRatePer1M(gemRates.input))} · output ${escapeHtml(_fmtRatePer1M(gemRates.output))} · cache ${escapeHtml(_fmtRatePer1M(gemRates.cache_read_input))}</p>` : ''}
            <div class="flex items-center gap-2">
              <label for="pricing-ov-gem-cache" class="text-xs font-bold text-slate-700">Cache hit (%)</label>
              <input type="number" id="pricing-ov-gem-cache" aria-label="Gemini API cache hit percentage for this model" min="0" max="98" step="0.5" value="${gemCacheOwn === null ? '' : escapeHtml(gemCacheOwn)}" placeholder="default" class="w-24 bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 text-right text-xs font-bold mono text-slate-900" />
              <button type="button" data-jt-click="savePricingModelGeminiCache(${jsArg(cleanId)})" class="jt-btn-secondary px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 text-xs font-bold cursor-pointer transition">Save cache hit</button>
            </div>
          </div>`}
        </div>
      `);

      modal.classList.remove('hidden');
      if (typeof jtActivateDrawerFocus === 'function') {
        requestAnimationFrame(() => jtActivateDrawerFocus('pricing-model-modal'));
      } else if (titleEl && typeof titleEl.focus === 'function') {
        requestAnimationFrame(() => titleEl.focus());
      }
    }
    window.openPricingModelDrawer = openPricingModelDrawer;

    function closePricingModelDrawer() {
      const modal = document.getElementById('pricing-model-modal');
      if (modal) modal.classList.add('hidden');
      if (typeof jtDeactivateDrawerFocus === 'function') {
        jtDeactivateDrawerFocus('pricing-model-modal');
      }
    }
    window.closePricingModelDrawer = closePricingModelDrawer;

    function _showPricingDrawerFeedback(tone, msg) {
      const fb = document.getElementById('pricing-drawer-feedback');
      if (!fb) return;
      fb.classList.remove('hidden', 'bg-emerald-50', 'text-emerald-800', 'border-emerald-200', 'bg-rose-50', 'text-rose-800', 'border-rose-200');
      if (tone === 'ok') {
        fb.classList.add('bg-emerald-50', 'text-emerald-800', 'border', 'border-emerald-200');
      } else {
        fb.classList.add('bg-rose-50', 'text-rose-800', 'border', 'border-rose-200');
      }
      fb.textContent = msg;
    }

    async function savePricingModelManualOverride() {
      const idEl = document.getElementById('pricing-ov-model-id');
      const labelEl = document.getElementById('pricing-ov-label');
      const vendorEl = document.getElementById('pricing-ov-vendor');
      const inEl = document.getElementById('pricing-ov-input');
      const outEl = document.getElementById('pricing-ov-output');
      const thinkEl = document.getElementById('pricing-ov-thinking');
      const cacheEl = document.getElementById('pricing-ov-cache');
      const regInEl = document.getElementById('pricing-ov-reg-input');
      const regOutEl = document.getElementById('pricing-ov-reg-output');

      const modelId = String(idEl ? idEl.value : '').trim();
      if (!modelId) {
        _showPricingDrawerFeedback('err', 'Model ID is required.');
        return;
      }

      const inRate = Number(inEl ? inEl.value : 0);
      const outRate = Number(outEl ? outEl.value : 0);
      const thinkRate = Number(thinkEl ? thinkEl.value : outRate);
      const cacheRate = Number(cacheEl ? cacheEl.value : 0);
      const regInRate = Number(regInEl ? regInEl.value : inRate);
      const regOutRate = Number(regOutEl ? regOutEl.value : outRate);

      for (const [lbl, val] of [
        ['Input rate', inRate],
        ['Output rate', outRate],
        ['Thinking rate', thinkRate],
        ['Cache read rate', cacheRate],
        ['Regional input rate', regInRate],
        ['Regional output rate', regOutRate]
      ]) {
        if (Number.isNaN(val) || val < 0 || val > 1000) {
          _showPricingDrawerFeedback('err', `${lbl} must be between $0 and $1,000 per 1M tokens.`);
          return;
        }
      }

      const regMultFactor = (regInRate > 0 && inRate > 0) ? (regInRate / inRate) : 1.1;
      const regThinkFactor = (regOutRate > 0 && outRate > 0) ? (regOutRate / outRate) : regMultFactor;
      const regThinkRate = Number((thinkRate * regThinkFactor).toFixed(6));
      const regCacheRate = Number((cacheRate * regMultFactor).toFixed(6));

      try {
        const resp = await fetch('/api/models-pricing/config', {
          signal: AbortSignal.timeout(30000),
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            models: {
              [modelId]: {
                displayName: String(labelEl ? labelEl.value : modelId).trim() || modelId,
                publisher: String(vendorEl ? vendorEl.value : 'google').trim().toLowerCase(),
                input: inRate,
                output: outRate,
                thinking: thinkRate,
                cache_read_input: cacheRate,
                regional_input: regInRate,
                regional_output: regOutRate,
                regional_thinking: regThinkRate,
                regional_cache_read_input: regCacheRate
              }
            }
          })
        });
        const data = await resp.json();
        const isOk = resp.ok && (data.success === true || data.status === 'ok');
        if (!isOk) {
          throw new Error(data.error || (data.errors && data.errors.join('; ')) || data.message || `HTTP ${resp.status}`);
        }
        const st = window._jtModelsPricingState;
        st.config = data.config || st.config;
        if (Array.isArray(data.observed)) {
          st.observedModels = data.observed;
        } else if (Array.isArray(data.observedModels)) {
          st.observedModels = data.observedModels;
        }
        st.lastLoadedAt = Date.now();
        _updatePricingSidebarBadge();
        _renderPricingViewContents();
        openPricingModelDrawer(modelId);
        _showPricingDrawerFeedback('ok', `Manual rate override saved for ${modelId}.`);
      } catch (err) {
        _showPricingDrawerFeedback('err', err && err.message ? err.message : 'Failed to save manual override.');
      }
    }
    window.savePricingModelManualOverride = savePricingModelManualOverride;

    async function savePricingModelGeminiCache(modelId) {
      const cleanId = String(modelId || '').trim();
      const el = document.getElementById('pricing-ov-gem-cache');
      if (!cleanId || !el) return;
      const raw = String(el.value || '').trim();
      let value = null;
      if (raw !== '') {
        value = Number(raw);
        if (Number.isNaN(value) || value < 0 || value > 98) {
          _showPricingDrawerFeedback('err', 'Gemini API cache hit must be between 0% and 98% (or empty for the default).');
          return;
        }
      }
      try {
        const resp = await fetch('/api/models-pricing/config', {
          signal: AbortSignal.timeout(30000),
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ models: { [cleanId]: { geminiApiCacheHitRatioPct: value } } })
        });
        const data = await resp.json();
        const isOk = resp.ok && (data.success === true || data.status === 'ok');
        if (!isOk) {
          throw new Error(data.error || (data.errors && data.errors.join('; ')) || data.message || `HTTP ${resp.status}`);
        }
        const st = window._jtModelsPricingState;
        st.config = data.config || st.config;
        st.lastLoadedAt = Date.now();
        _renderPricingViewContents();
        openPricingModelDrawer(cleanId);
        _showPricingDrawerFeedback('ok', value === null ? `Gemini API cache hit reset to default for ${cleanId}. Run a scan to recalculate costs.` : `Gemini API cache hit saved for ${cleanId}. Run a scan to recalculate costs.`);
      } catch (err) {
        _showPricingDrawerFeedback('err', err && err.message ? err.message : 'Failed to save Gemini API cache hit.');
      }
    }
    window.savePricingModelGeminiCache = savePricingModelGeminiCache;

    async function resetPricingModelManualOverride(modelId) {
      const cleanId = String(modelId || '').trim();
      if (!cleanId) return;
      try {
        const resp = await fetch('/api/models-pricing/config', {
          signal: AbortSignal.timeout(30000),
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            models: {
              [cleanId]: {
                clearManualOverride: true
              }
            }
          })
        });
        const data = await resp.json();
        const isOk = resp.ok && (data.success === true || data.status === 'ok');
        if (!isOk) {
          throw new Error(data.error || (data.errors && data.errors.join('; ')) || data.message || `HTTP ${resp.status}`);
        }
        const st = window._jtModelsPricingState;
        st.config = data.config || st.config;
        if (Array.isArray(data.observed)) {
          st.observedModels = data.observed;
        } else if (Array.isArray(data.observedModels)) {
          st.observedModels = data.observedModels;
        }
        st.lastLoadedAt = Date.now();
        _updatePricingSidebarBadge();
        _renderPricingViewContents();
        if (st.config && st.config.models && st.config.models[cleanId]) {
          openPricingModelDrawer(cleanId);
          _showPricingDrawerFeedback('ok', `Manual override removed; restored catalog/built-in rate for ${cleanId}.`);
        } else {
          closePricingModelDrawer();
        }
      } catch (err) {
        _showPricingDrawerFeedback('err', err && err.message ? err.message : 'Failed to reset manual override.');
      }
    }
    window.resetPricingModelManualOverride = resetPricingModelManualOverride;
