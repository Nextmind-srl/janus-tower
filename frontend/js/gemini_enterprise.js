    if (typeof window.escapeHtml !== 'function') {
      window.escapeHtml = function(val) {
        if (val === null || val === undefined) return '';
        return String(val)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      };
    }

    window.filterAgentspaceDataStores = function(mode) {
      const rows = document.querySelectorAll('#agentspace-datastores-audit-tbody .ds-audit-row');
      rows.forEach(tr => {
        const st = tr.getAttribute('data-ds-status');
        tr.style.display = (mode === 'ALL' || st === mode) ? '' : 'none';
      });
      ['ALL', 'ACTIVE', 'UNUSED'].forEach(m => {
        const btn = document.getElementById(`ds-filter-btn-${m}`);
        if (!btn) return;
        if (m === mode) {
          btn.className = 'px-2 py-0.5 rounded bg-[#0F2A4A] text-white cursor-pointer transition';
        } else if (m === 'ACTIVE') {
          btn.className = 'px-2 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100 cursor-pointer transition';
        } else if (m === 'UNUSED') {
          btn.className = 'px-2 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200 hover:bg-amber-100 cursor-pointer transition';
        } else {
          btn.className = 'px-2 py-0.5 rounded bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer transition';
        }
      });
    };

    window.switchGeminiEnterpriseSubView = function(subView) {
      const mode = subView || 'ALL';
      window._activeGeSubView = mode;
      ['APPS', 'CONNECTORS', 'AGENTS', 'SECURITY'].forEach(key => {
        const el = document.getElementById(`ge-subview-${key}`);
        if (!el) return;
        if (mode === 'ALL' || mode === key) {
          el.classList.remove('hidden');
        } else {
          el.classList.add('hidden');
        }
      });
      ['ALL', 'APPS', 'CONNECTORS', 'AGENTS', 'SECURITY'].forEach(k => {
        const btn = document.querySelector(`[data-ge-subbtn="${k}"]`);
        if (!btn) return;
        if (k === mode) {
          btn.className = 'jt-ge-filter-chip active px-2.5 py-1 rounded-full text-[11px] font-bold transition cursor-pointer bg-[#0F2A4A] text-white';
        } else {
          btn.className = 'jt-ge-filter-chip px-2.5 py-1 rounded-full text-[11px] font-semibold transition cursor-pointer bg-white text-slate-600 border border-slate-200 hover:bg-slate-100';
        }
      });
    };

    window.filterGeminiConnectorHubs = function(mode) {
      const targetMode = mode || 'ALL';
      const cards = document.querySelectorAll('#ge-connector-hubs-grid .ge-hub-card, .ge-hub-card');
      cards.forEach(c => {
        const grp = c.getAttribute('data-hub-group') || '';
        const show = (targetMode === 'ALL' || grp === targetMode);
        c.style.display = show ? '' : 'none';
      });
      const btnStyles = {
        ALL: 'px-2.5 py-1 rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer transition',
        SAAS: 'px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-800 border border-indigo-200 hover:bg-indigo-100 cursor-pointer transition',
        WORKSPACE: 'px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100 cursor-pointer transition',
        GCP: 'px-2.5 py-1 rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer transition'
      };
      ['ALL', 'SAAS', 'WORKSPACE', 'GCP'].forEach(m => {
        const btn = document.getElementById(`hub-filter-btn-${m}`);
        if (!btn) return;
        if (m === targetMode) {
          btn.className = 'px-2.5 py-1 rounded-lg bg-[#0F2A4A] text-white cursor-pointer transition';
        } else {
          btn.className = btnStyles[m];
        }
      });
    };

    window.filterGeCustomAgents = function(engineFilter) {
      const target = engineFilter || 'ALL';
      const rows = document.querySelectorAll('#ge-custom-agents-tbody tr[data-agent-engine]');
      rows.forEach(r => {
        const eng = r.getAttribute('data-agent-engine') || '';
        r.style.display = (target === 'ALL' || eng === target) ? '' : 'none';
      });
      const btns = document.querySelectorAll('[data-ge-agent-filter-btn]');
      btns.forEach(b => {
        const val = b.getAttribute('data-ge-agent-filter-btn');
        if (val === target) {
          b.className = 'px-2.5 py-1 rounded-lg bg-[#0F2A4A] text-white text-[10px] font-bold cursor-pointer transition';
        } else {
          b.className = 'px-2.5 py-1 rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 text-[10px] font-bold cursor-pointer transition';
        }
      });
    };

    window.closeGeminiInspectorModal = function() {
      const modal = document.getElementById('gemini-inspector-modal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
      }
      if (typeof window.jtDeactivateDrawerFocus === 'function') window.jtDeactivateDrawerFocus('gemini-inspector-modal');
    };

    function _buildInspectorEngineHtml(targetObj, resourceId, resolvedLoc) {
      const feats = targetObj.featuresDetailed || [];
      const onFeats = feats.filter(f => f.state === 'ON' || f.isOn);
      const offFeats = feats.filter(f => f.state !== 'ON' && !f.isOn);
      const engId = targetObj.engineId || targetObj.resourceId || resourceId;
      const queriesCnt = targetObj.queriesCount ?? targetObj.queries ?? 0;
      const usersCnt = targetObj.activeUsersCount ?? targetObj.uniqueUsersCount ?? 0;
      const totPrincipals = targetObj.totalDetectedPrincipalsCount || usersCnt || 0;
      const agCnt = targetObj.agentsCount ?? (targetObj.agents ? targetObj.agents.length : 0);
      const agOwnersCnt = targetObj.agentOwnersCount ?? (targetObj.agentOwners ? targetObj.agentOwners.length : 0);
      const sessCnt = targetObj.sessionsCount ?? 0;
      const obsEnabled = Boolean(targetObj.observabilityEnabled);
      const licPool = targetObj.licensePool || {};
      const licCfg = (licPool.configs && licPool.configs[0]) || {};
      const dsCnt = targetObj.linkedDataStoresCount || (targetObj.dataStoreIds ? targetObj.dataStoreIds.length : 0);
      const appAgents = targetObj.agents || [];

      return `
        <div class="jt-kpi-grid grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.navy}">
            <div class="jt-kpi__label">Engine ID &amp; Web CID</div>
            <div class="jt-kpi__value font-mono !text-xs break-all">${escapeHtml(engId)}</div>
            <div class="jt-kpi__note">CID: <span class="font-mono font-bold">${escapeHtml(targetObj.cid || 'N/A')}</span> · Loc: <span class="font-mono">${escapeHtml(resolvedLoc)}</span>${targetObj.companyName ? ` · <b>${escapeHtml(targetObj.companyName)}</b>` : ''}</div>
          </div>
          <div class="jt-kpi" style="--kpi-accent: ${licPool.state === 'EXPIRED' ? JT_COLORS.danger : JT_COLORS.success}">
            <div class="jt-kpi__label">Licenses Region (${escapeHtml(resolvedLoc.toUpperCase())}) &amp; Log</div>
            <div class="jt-kpi__value !text-xs ${licPool.state === 'EXPIRED' ? 'text-rose-700' : 'text-emerald-800'}">
              ${licPool.state === 'EXPIRED'
                ? `EXPIRED (${escapeHtml(licCfg.endDate || '2025-11-30')})`
                : `${escapeHtml(licPool.state || 'ACTIVE')} (${licPool.assignedCount || 0}/${licPool.totalSeats || 0} seats)`}
            </div>
            <div class="jt-kpi__note ${obsEnabled ? 'text-emerald-700' : 'text-amber-700'} font-semibold">
              observabilityEnabled: <b>${obsEnabled ? 'true (Log Query ON)' : 'false (Log Query OFF)'}</b>
            </div>
          </div>
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.success}">
            <div class="jt-kpi__label">Feature Flags &amp; Model Selector</div>
            <div class="jt-kpi__value !text-sm text-emerald-700">${onFeats.length} ON / ${offFeats.length} OFF</div>
            <div class="jt-kpi__note">Model Selector: <span class="jt-chip jt-chip--mono">${escapeHtml(targetObj.modelSelector || 'DEFAULT')}</span></div>
          </div>
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.info}">
            <div class="jt-kpi__label">Usage, Agents &amp; DataStore</div>
            <div class="jt-kpi__value !text-sm">${fmtNum(queriesCnt)} queries · ${fmtNum(agCnt)} agents</div>
            <div class="jt-kpi__note">${fmtNum(totPrincipals)} users/owners · ${escapeHtml(sessCnt)} sessions · ${escapeHtml(dsCnt)} DS</div>
          </div>
        </div>

        ${appAgents.length > 0 ? `
          <div class="jt-drawer__section-title">Agents Configured in the Engine (${appAgents.length} Agents · ${escapeHtml(agOwnersCnt)} IAM Owners)</div>
          <div class="jt-table-panel p-3 mb-4">
            ${(targetObj.agentGroups || []).length > 0 ? `<div class="text-[10px] font-mono text-slate-600 mb-2">IAM Groups: ${targetObj.agentGroups.map(g => `<span class="jt-chip jt-chip--mono mr-1">${escapeHtml(g)}</span>`).join('')}</div>` : ''}
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-56 overflow-y-auto pr-1">
              ${appAgents.slice(0, 40).map(ag => `
                <div class="bg-slate-50/70 border border-slate-200 rounded p-2.5 flex items-start justify-between gap-2">
                  <div>
                    <div class="text-[11px] font-bold text-slate-900">${escapeHtml(ag.displayName || ag.agentId)} ${ag.llmModel ? `<span class="jt-chip jt-chip--mono ml-1">${escapeHtml(ag.llmModel)}</span>` : ''}</div>
                    <div class="text-[10px] font-mono text-slate-500 mt-0.5">Owner IAM: <b class="text-slate-800">${escapeHtml(ag.creatorEmail || (ag.owners || [])[0] || 'Admin / System')}</b></div>
                    ${ag.description || ag.instructionPreview ? `<div class="text-[10px] text-slate-600 mt-0.5 line-clamp-2">${escapeHtml(ag.description || ag.instructionPreview)}</div>` : ''}
                  </div>
                  <span class="jt-badge ${ag.state === 'ENABLED' ? 'jt-badge--success' : 'jt-badge--neutral'} shrink-0">${escapeHtml(ag.state || 'ENABLED')}</span>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}

        <div class="jt-drawer__section-title">Feature Flags Discovery Engine</div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
          <div class="jt-table-panel p-3">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-bold text-slate-800">Active Features</span>
              <span class="jt-badge jt-badge--success">${onFeats.length} ON</span>
            </div>
            <div class="space-y-1.5 max-h-64 overflow-y-auto pr-1">
              ${onFeats.map(f => `
                <div class="bg-slate-50/60 border border-slate-200 rounded p-2 flex items-start justify-between gap-2">
                  <div>
                    <div class="text-[11px] font-bold text-slate-800">${escapeHtml(f.label || f.key)} <span class="jt-chip jt-chip--mono ml-1">${escapeHtml(f.category || 'Feature')}</span></div>
                    <div class="text-[10px] font-mono text-slate-500">${escapeHtml(f.key)}</div>
                    <div class="text-[10px] text-slate-600 mt-0.5">${escapeHtml(f.description || '')}</div>
                  </div>
                  <span class="jt-badge jt-badge--success shrink-0">ON</span>
                </div>
              `).join('') || '<div class="text-xs text-slate-400 italic">No features ON</div>'}
            </div>
          </div>
          <div class="jt-table-panel p-3">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-bold text-slate-700">Disabled Features</span>
              <span class="jt-badge jt-badge--neutral">${offFeats.length} OFF</span>
            </div>
            <div class="space-y-1.5 max-h-64 overflow-y-auto pr-1">
              ${offFeats.map(f => `
                <div class="bg-slate-50/40 border border-slate-200 rounded p-2 flex items-start justify-between gap-2">
                  <div>
                    <div class="text-[11px] font-bold text-slate-700">${escapeHtml(f.label || f.key)} <span class="jt-chip jt-chip--mono ml-1">${escapeHtml(f.category || 'Feature')}</span></div>
                    <div class="text-[10px] font-mono text-slate-400">${escapeHtml(f.key)}</div>
                    <div class="text-[10px] text-slate-500 mt-0.5">${escapeHtml(f.description || '')}</div>
                  </div>
                  <span class="jt-badge jt-badge--neutral shrink-0">OFF</span>
                </div>
              `).join('') || '<div class="text-xs text-slate-400 italic">No features OFF</div>'}
            </div>
          </div>
        </div>
      `;
    }

    function _buildInspectorConnectorHtml(targetObj, resolvedLoc) {
      const rec = targetObj.recoveredParams || {};
      const ents = targetObj.entities || [];
      const linkedNames = (targetObj.linkedApps || []).map(la => la.displayName || la.engineId);
      return `
        <div class="jt-kpi-grid grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.navy}">
            <div class="jt-kpi__label">Connector Hub ID &amp; Creation</div>
            <div class="jt-kpi__value font-mono !text-xs break-all">${escapeHtml(targetObj.hubId)}</div>
            <div class="jt-kpi__note">Created: <b>${escapeHtml(targetObj.createTime || 'N/A')}</b> · Loc: <span class="font-mono">${escapeHtml(resolvedLoc)}</span></div>
          </div>
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.amber}">
            <div class="jt-kpi__label">Authentication &amp; Sync</div>
            <div class="jt-kpi__value !text-xs">${escapeHtml(targetObj.authModel || '-')}</div>
            <div class="jt-kpi__note">Sync: ${escapeHtml(targetObj.syncMode || '-')}</div>
          </div>
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.info}">
            <div class="jt-kpi__label">Entities &amp; RAG Usage</div>
            <div class="jt-kpi__value !text-sm">${ents.length} DataStore Entities · ${fmtNum(targetObj.totalQueries || 0)} query</div>
            <div class="jt-kpi__note">Linked apps: ${escapeHtml(linkedNames.join(', ') || 'None')}</div>
          </div>
        </div>
        <div class="jt-drawer__section-title">Configuration Parameters and Recovered Metadata</div>
        <div class="jt-table-panel p-3 mb-4">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
            ${Object.entries(rec).map(([k, v]) => `
              <div class="bg-slate-50/70 border border-slate-200 rounded p-2">
                <span class="font-bold text-slate-500 uppercase text-[9px] block">${escapeHtml(k)}</span>
                <span class="font-mono text-slate-800 break-all">${escapeHtml(typeof v === 'object' ? JSON.stringify(v) : String(v))}</span>
              </div>
            `).join('')}
          </div>
        </div>
        <div class="jt-drawer__section-title">DataStore Entities (${ents.length})</div>
        <div class="jt-table-panel overflow-hidden mb-4">
          <table class="jt-table w-full text-left border-collapse text-[11px]">
            <thead>
              <tr>
                <th class="py-2 px-3">Entity</th>
                <th class="py-2 px-3">Full DataStore ID</th>
                <th class="py-2 px-3">Content Config</th>
                <th class="py-2 px-3 text-right">Query RAG</th>
                <th class="py-2 px-3 text-right">Users</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              ${ents.map(e => `
                <tr>
                  <td class="py-1.5 px-3 font-bold text-[#0F2A4A]">${escapeHtml(e.entityLabel || e.entityName || '-')}</td>
                  <td class="py-1.5 px-3 font-mono text-slate-700">${escapeHtml(e.dataStoreId || '')}</td>
                  <td class="py-1.5 px-3"><span class="jt-chip jt-chip--mono">${escapeHtml(e.contentConfig || 'CONTENT_REQUIRED')}</span></td>
                  <td class="py-1.5 px-3 text-right font-mono font-bold">${fmtNum(e.queriesCount ?? e.queries ?? 0)}</td>
                  <td class="py-1.5 px-3 text-right font-mono">${escapeHtml(e.usersCount ?? e.uniqueUsersCount ?? 0)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    function _buildInspectorDatastoreHtml(targetObj, resourceId, resolvedLoc) {
      return `
        <div class="jt-kpi-grid grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.navy}">
            <div class="jt-kpi__label">DataStore ID &amp; Creation</div>
            <div class="jt-kpi__value font-mono !text-xs break-all">${escapeHtml(targetObj.dataStoreId || resourceId)}</div>
            <div class="jt-kpi__note">Created: <b>${escapeHtml(targetObj.createTime || 'N/A')}</b> · Loc: <span class="font-mono">${escapeHtml(resolvedLoc)}</span></div>
          </div>
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.info}">
            <div class="jt-kpi__label">Connector Hub &amp; Entity</div>
            <div class="jt-kpi__value !text-xs">${escapeHtml(targetObj.hubDisplayName || '-')} (${escapeHtml(targetObj.vendor || '-')})</div>
            <div class="jt-kpi__note">Entity: <b>${escapeHtml(targetObj.entityLabel || targetObj.entityName || '-')}</b> · Config: <span class="jt-chip jt-chip--mono">${escapeHtml(targetObj.contentConfig || '-')}</span></div>
          </div>
          <div class="jt-kpi" style="--kpi-accent: ${JT_COLORS.success}">
            <div class="jt-kpi__label">Usage &amp; Linked Apps</div>
            <div class="jt-kpi__value !text-sm">${fmtNum(targetObj.queriesCount || 0)} query · ${fmtNum(targetObj.activeUsersCount || 0)} users</div>
            <div class="jt-kpi__note">${escapeHtml(targetObj.linkedAppsCount || 0)} linked apps</div>
          </div>
        </div>
      `;
    }

    window.openGeminiInspectorModal = function(kind, projectId, resourceId, location) {
      const modal = document.getElementById('gemini-inspector-modal');
      const titleEl = document.getElementById('gemini-inspector-modal-title');
      const subEl = document.getElementById('gemini-inspector-modal-subtitle');
      const bodyEl = document.getElementById('gemini-inspector-modal-body');
      const probeBtn = document.getElementById('gemini-inspector-live-probe-btn');
      if (!modal || !bodyEl) return;

      const state = window._lastGeInventoryState || {};
      const fallbackInv = ((globalScanData && globalScanData.summary) ? globalScanData.summary.geminiEnterpriseInventory : null) || {};
      const appsList = state.apps || fallbackInv.apps || [];
      const hubsList = state.hubs || fallbackInv.connectorHubs || [];
      const dsList = state.dataStores || fallbackInv.dataStores || [];

      const normKind = (kind || 'ENGINE').toUpperCase();
      let targetObj = null;
      let resolvedLoc = location || 'eu';

      if (normKind === 'ENGINE' || normKind === 'APP') {
        targetObj = appsList.find(a => a.projectId === projectId && (a.engineId === resourceId || a.resourceId === resourceId))
                 || appsList.find(a => a.engineId === resourceId || a.resourceId === resourceId);
        if (targetObj && targetObj.location) resolvedLoc = targetObj.location;
        if (titleEl) titleEl.textContent = `App / Engine Gemini Enterprise: ${targetObj ? (targetObj.displayName || targetObj.engineId) : resourceId}`;
        if (subEl) subEl.textContent = `Project: ${projectId} • Engine ID: ${resourceId} • Location: ${resolvedLoc} • Type: ${targetObj ? (targetObj.appType || 'INTRANET') : '-'}`;
      } else if (normKind === 'CONNECTOR' || normKind === 'HUB') {
        targetObj = hubsList.find(h => h.projectId === projectId && h.hubId === resourceId)
                 || hubsList.find(h => h.hubId === resourceId);
        if (targetObj && targetObj.location) resolvedLoc = targetObj.location;
        if (titleEl) titleEl.textContent = `Connector Hub: ${targetObj ? (targetObj.hubDisplayName || targetObj.hubId) : resourceId}`;
        if (subEl) subEl.textContent = `Project: ${projectId} • Hub ID: ${resourceId} • Location: ${resolvedLoc} • Vendor: ${targetObj ? (targetObj.vendor || '-') : '-'}`;
      } else if (normKind === 'DATASTORE') {
        targetObj = dsList.find(d => d.projectId === projectId && (d.dataStoreId === resourceId || d.resourceId === resourceId))
                 || dsList.find(d => d.dataStoreId === resourceId || d.resourceId === resourceId);
        if (targetObj && targetObj.location) resolvedLoc = targetObj.location;
        if (titleEl) titleEl.textContent = `DataStore Discovery Engine: ${targetObj ? (targetObj.displayName || targetObj.dataStoreId) : resourceId}`;
        if (subEl) subEl.textContent = `Project: ${projectId} • DataStore ID: ${resourceId} • Location: ${resolvedLoc} • Hub: ${targetObj ? (targetObj.hubDisplayName || '-') : '-'}`;
      } else {
        targetObj = state;
        if (titleEl) titleEl.textContent = `Gemini Enterprise 360° Inventory (${projectId})`;
        if (subEl) subEl.textContent = `Full snapshot of Discovery Engine v1alpha/v1beta configurations + Cloud Audit Logs`;
      }

      if (probeBtn) {
        probeBtn.onclick = function() {
          window.runLiveGeminiInspect(projectId, resourceId, normKind, resolvedLoc);
        };
      }

      let customHtml = '';
      if ((normKind === 'ENGINE' || normKind === 'APP') && targetObj) {
        customHtml = _buildInspectorEngineHtml(targetObj, resourceId, resolvedLoc);
      } else if ((normKind === 'CONNECTOR' || normKind === 'HUB') && targetObj) {
        customHtml = _buildInspectorConnectorHtml(targetObj, resolvedLoc);
      } else if (normKind === 'DATASTORE' && targetObj) {
        customHtml = _buildInspectorDatastoreHtml(targetObj, resourceId, resolvedLoc);
      }

      setSafeHtml(bodyEl, `
        ${customHtml}
        <div id="gemini-live-probe-output" class="hidden mb-4"></div>
        <div>
          <div class="jt-drawer__section-title flex items-center justify-between">
            <span>Full Technical Payload (Inspected JSON)</span>
            <span class="text-[10px] font-mono text-slate-400 normal-case tracking-normal">Press "<svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Run Live v1alpha API Probe" at the top to query the GCP REST endpoints</span>
          </div>
          <pre class="bg-slate-900 text-emerald-300 font-mono text-[11px] p-4 rounded-xl overflow-x-auto max-h-96">${escapeHtml(JSON.stringify(targetObj || {}, null, 2))}</pre>
        </div>
      `);

      modal.classList.remove('hidden');
      modal.classList.add('flex');
      if (typeof window.jtActivateDrawerFocus === 'function') window.jtActivateDrawerFocus('gemini-inspector-modal');
    };

    window.runLiveGeminiInspect = async function(projectId, resourceId, kind, location) {
      const outEl = document.getElementById('gemini-live-probe-output');
      const probeBtn = document.getElementById('gemini-inspector-live-probe-btn');
      if (!outEl) return;
      const loc = location || 'eu';
      const rtype = (kind || 'ENGINE').toUpperCase();
      outEl.classList.remove('hidden');
      setSafeHtml(outEl, `<div class="p-3 rounded-xl bg-indigo-50 border border-indigo-200 text-xs text-indigo-900 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> Live query in progress on <code>${escapeHtml(loc === 'global' ? '' : loc + '-')}discoveryengine.googleapis.com</code> (v1alpha / v1beta) for <b>${escapeHtml(resourceId)}</b> (${escapeHtml(projectId || 'default-project')})...</div>`);
      if (probeBtn) probeBtn.disabled = true;
      try {
        const pid = encodeURIComponent(projectId || 'default-project');
        const rid = encodeURIComponent(resourceId || '');
        const locParam = encodeURIComponent(loc);
        const typeParam = encodeURIComponent(rtype);
        const headers = (typeof getBrowserAuthHeaders === 'function') ? getBrowserAuthHeaders() : {};
        const resp = await fetch(`/api/gemini-enterprise/inspect?projectId=${pid}&location=${locParam}&resourceType=${typeParam}&resourceId=${rid}`, { headers, signal: AbortSignal.timeout(30000) });
        const data = await resp.json();
        if (!resp.ok || data.success === false) {
          setSafeHtml(outEl, `<div class="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg> Live probe error (${escapeHtml(resp.status)}): ${escapeHtml(data.error || 'Unable to complete the request')}</div>`);
          return;
        }
        setSafeHtml(outEl, `
          <div class="border border-emerald-300 bg-emerald-50/40 rounded-xl p-3">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-bold text-emerald-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Live Discovery Engine REST API Response (${escapeHtml(data.inspectedAt || '')})</span>
              <span class="px-2 py-0.5 rounded bg-emerald-600 text-white text-[10px] font-bold">LIVE REST v1alpha/v1beta</span>
            </div>
            <pre class="bg-slate-950 text-cyan-300 font-mono text-[11px] p-3 rounded-lg overflow-x-auto max-h-80">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
          </div>
        `);
      } catch (err) {
        setSafeHtml(outEl, `<div class="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg> Error during live probe: ${escapeHtml(String(err))}</div>`);
      } finally {
        if (probeBtn) probeBtn.disabled = false;
      }
    };

    // VISTA 5: APP GEMINI ENTERPRISE, VERTEX AI, MODEL GARDEN, DATA RESIDENCY & MODEL ARMOR
    function _aggregateResidencyAndFinopsMetrics(visibleProjs, agg, q) {
      const s = globalScanData.summary || {};
      const sFe = s.finopsExtended || {};
      const sDr = s.dataResidency || {};
      const isUnfilteredAll = (agg.selProj === 'ALL' && !q);

      const m = {
        itCalls: 0, itTok: 0, itCost: 0,
        euCalls: 0, euTok: 0, euCost: 0,
        glCalls: 0, glTok: 0, glCost: 0,
        usCalls: 0, usTok: 0, usCost: 0,
        totInputTok: 0, totCachedTok: 0, totCacheSavings: 0, totExtraPotentialSavings: 0,
        dailyBurnAi: 0, dailyBurnTco: 0, forecast30dAi: 0, forecast30dTco: 0,
        last7Cost: 0, prev7Cost: 0, last7Req: 0, prev7Req: 0,
        excludedNonAiInfra: 0, realAiInfra: 0,
        allIdleResources: [], allZombieBuilds: [], allNonEuResources: [], allBudgets: [], nonEuProjects: []
      };

      visibleProjs.forEach(p => {
        const dr = p.dataResidency || {};
        const bd = dr.breakdown || {};
        if (bd.ITALY_LOCAL) {
          m.itCalls += (bd.ITALY_LOCAL.calls || 0);
          m.itTok += (bd.ITALY_LOCAL.tokens || 0);
          m.itCost += (bd.ITALY_LOCAL.costUsd || 0);
        }
        if (bd.EU_EEA) {
          m.euCalls += (bd.EU_EEA.calls || 0);
          m.euTok += (bd.EU_EEA.tokens || 0);
          m.euCost += (bd.EU_EEA.costUsd || 0);
        }
        if (bd.GLOBAL_ANYCAST) {
          m.glCalls += (bd.GLOBAL_ANYCAST.calls || 0);
          m.glTok += (bd.GLOBAL_ANYCAST.tokens || 0);
          m.glCost += (bd.GLOBAL_ANYCAST.costUsd || 0);
        }
        if (bd.NON_EU_US_OTHER) {
          m.usCalls += (bd.NON_EU_US_OTHER.calls || 0);
          m.usTok += (bd.NON_EU_US_OTHER.tokens || 0);
          m.usCost += (bd.NON_EU_US_OTHER.costUsd || 0);
        }
        if (dr.hasNonEuTraffic) {
          m.nonEuProjects.push({ projectId: p.projectId, nonEuPct: dr.nonEuPct || 0, regions: dr.regionsUsed || [] });
        }
        (dr.nonEuDeployedResources || []).forEach(nr => m.allNonEuResources.push({ ...nr, projectId: nr.projectId || p.projectId }));

        const fo = p.finopsExtended || {};
        m.totInputTok += (fo.inputTokens || p.inputTokens || 0);
        m.totCachedTok += (fo.cachedTokens || p.cachedTokens || 0);
        m.totCacheSavings += (fo.cacheSavingsUsd ?? p.cacheSavingsUsd ?? 0);
        m.totExtraPotentialSavings += (fo.potentialExtraCacheSavingsUsd || 0);
        m.dailyBurnAi += (fo.dailyBurnRateAiUsd || 0);
        m.dailyBurnTco += (fo.dailyBurnRateTcoUsd || 0);
        m.forecast30dAi += (fo.forecast30dAiUsd || 0);
        m.forecast30dTco += (fo.forecast30dTcoUsd || 0);
        m.last7Cost += (fo.last7dCostUsd || 0);
        m.prev7Cost += (fo.prev7dCostUsd || 0);
        m.last7Req += (fo.last7dRequests || 0);
        m.prev7Req += (fo.prev7dRequests || 0);
        m.excludedNonAiInfra += (p.excludedNonAiInfraCostUsd ?? fo.excludedNonAiInfraCostUsd ?? 0);
        m.realAiInfra += (p.infraCostUsd || 0);

        (fo.idleResources || []).forEach(ir => m.allIdleResources.push({ ...ir, projectId: ir.projectId || p.projectId }));
        (fo.zombieReasoningEngines || []).forEach(zb => m.allZombieBuilds.push({ ...zb, projectId: zb.projectId || p.projectId }));
        (fo.projectBudgets || []).forEach(bg => m.allBudgets.push({ ...bg, projectId: bg.projectId || p.projectId }));
      });

      if (isUnfilteredAll) {
        if (sFe.dailyBurnRateAiUsd !== undefined) m.dailyBurnAi = sFe.dailyBurnRateAiUsd;
        if (sFe.dailyBurnRateTcoUsd !== undefined) m.dailyBurnTco = sFe.dailyBurnRateTcoUsd;
        if (sFe.forecast30dAiUsd !== undefined) m.forecast30dAi = sFe.forecast30dAiUsd;
        if (sFe.forecast30dTcoUsd !== undefined) m.forecast30dTco = sFe.forecast30dTcoUsd;
        if (sFe.last7dCostUsd !== undefined) m.last7Cost = sFe.last7dCostUsd;
        if (sFe.prev7dCostUsd !== undefined) m.prev7Cost = sFe.prev7dCostUsd;
        if (s.excludedNonAiInfraCostUsd !== undefined) m.excludedNonAiInfra = s.excludedNonAiInfraCostUsd;
        else if (sFe.excludedNonAiInfraCostUsd !== undefined) m.excludedNonAiInfra = sFe.excludedNonAiInfraCostUsd;
        if (s.totalInfraCostUsd !== undefined) m.realAiInfra = s.totalInfraCostUsd;
        if (m.allZombieBuilds.length === 0 && (sFe.zombieReasoningEngines || []).length > 0) {
          sFe.zombieReasoningEngines.forEach(zb => m.allZombieBuilds.push(zb));
        }
        if (m.allNonEuResources.length === 0 && (sDr.nonEuDeployedResources || []).length > 0) {
          sDr.nonEuDeployedResources.forEach(nr => m.allNonEuResources.push(nr));
        }
        if (m.allBudgets.length === 0 && (sFe.projectBudgets || []).length > 0) {
          sFe.projectBudgets.forEach(bg => m.allBudgets.push(bg));
        }
      }

      m.costTrend7dPct = (isUnfilteredAll && sFe.costTrend7dPct !== undefined)
        ? sFe.costTrend7dPct
        : (m.prev7Cost > 0 ? Number((((m.last7Cost - m.prev7Cost) / m.prev7Cost) * 100).toFixed(1)) : 0);
      m.requestsTrend7dPct = (isUnfilteredAll && sFe.requestsTrend7dPct !== undefined)
        ? sFe.requestsTrend7dPct
        : (m.prev7Req > 0 ? Number((((m.last7Req - m.prev7Req) / m.prev7Req) * 100).toFixed(1)) : 0);
      return m;
    }

    function _renderResidencyAndFinopsSection(resFinContainer, visibleProjs, agg, q) {
      if (!resFinContainer) return;
      const m = _aggregateResidencyAndFinopsMetrics(visibleProjs, agg, q);
      const {
        itCalls, itTok, itCost, euCalls, euTok, euCost, glCalls, glTok, glCost, usCalls, usTok, usCost,
        totInputTok, totCachedTok, totCacheSavings, totExtraPotentialSavings,
        dailyBurnAi, dailyBurnTco, forecast30dAi, forecast30dTco, last7Cost, prev7Cost,
        excludedNonAiInfra, realAiInfra, allIdleResources, allZombieBuilds, allNonEuResources, allBudgets, nonEuProjects,
        costTrend7dPct, requestsTrend7dPct
      } = m;

      const totRegTok = itTok + euTok + glTok + usTok;
      const totRegCalls = itCalls + euCalls + glCalls + usCalls;
      const denom = totRegTok > 0 ? totRegTok : (totRegCalls || 1);
      const itPct = Math.round(((totRegTok > 0 ? itTok : itCalls) / denom) * 1000) / 10;
      const euPct = Math.round(((totRegTok > 0 ? euTok : euCalls) / denom) * 1000) / 10;
      const glPct = Math.round(((totRegTok > 0 ? glTok : glCalls) / denom) * 1000) / 10;
      const usPct = Math.round(((totRegTok > 0 ? usTok : usCalls) / denom) * 1000) / 10;
      const gdprCompliantPct = Math.min(100, Math.round((itPct + euPct) * 10) / 10);
      const cacheHitPct = totInputTok > 0 ? Math.round((totCachedTok / totInputTok) * 1000) / 10 : 0;

      setSafeHtml(resFinContainer, `
        <!-- NUOVA RIGA KPI FINOPS PREDITTIVA (4 MINI-CARD COMPATTE) -->
        <div class="jt-kpi-grid grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> DAILY BURN RATE</span>
              <span class="jt-chip jt-chip--blue px-1.5 py-0.5 rounded bg-blue-50 text-[#0F2A4A] mono">DAILY</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-[#0F2A4A] mono mt-1">$${dailyBurnAi.toFixed(2)}/d AI <span class="text-slate-300">|</span> <span class="text-slate-800">$${dailyBurnTco.toFixed(2)}/d TCO</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5">Net AI vs TCO (incl. AI Infra)</div>
          </div>

          <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> 30-DAY FORECAST</span>
              <span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 mono">30D PROJ</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-indigo-900 mono mt-1">${fmtUsd(forecast30dAi)} AI <span class="text-slate-300">|</span> <span class="text-slate-900">${fmtUsd(forecast30dTco)} TCO</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5">Monthly estimate (${fmtEur(forecast30dTco)} TCO)</div>
          </div>

          <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> TREND 7D VS PREV 7D</span>
              <span class="jt-chip px-1.5 py-0.5 rounded ${costTrend7dPct > 5 ? 'jt-chip--red bg-rose-50 text-rose-700' : (costTrend7dPct < -5 ? 'jt-chip--green bg-emerald-50 text-emerald-700' : 'jt-chip--gray bg-slate-100 text-slate-600')} mono">${costTrend7dPct > 0 ? '+' : ''}${escapeHtml(costTrend7dPct)}%</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-slate-900 mono mt-1">${costTrend7dPct > 0 ? '+' : ''}${escapeHtml(costTrend7dPct)}% Spend <span class="text-slate-300">|</span> <span class="text-blue-700">${requestsTrend7dPct > 0 ? '+' : ''}${escapeHtml(requestsTrend7dPct)}% Calls</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5">${fmtUsd(last7Cost)} (last 7d) vs ${fmtUsd(prev7Cost)} (prev. 7d)</div>
          </div>

          <div class="jt-kpi bg-white rounded-xl border border-emerald-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-emerald-800">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-shield"/></svg> FALSE INFRA COST FILTER</span>
              <span class="jt-chip jt-chip--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 mono">SQL FILTER</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-emerald-700 mono mt-1">-${fmtUsd(excludedNonAiInfra)} <span class="text-xs font-bold text-slate-500">excluded</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5">On projects with 0 AI inferences (<b>${fmtUsd(realAiInfra)}</b> actual AI Infra)</div>
          </div>
        </div>

        <div class="jt-dash-grid grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div class="jt-dash-card bg-white rounded-xl border border-slate-200 p-4 shadow-2xs space-y-3">
            <div class="flex items-center justify-between border-b border-slate-100 pb-2.5">
              <div>
                <h4 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> GDPR Data Residency &amp; AI Data Sovereignty</h4>
                <p class="text-[11px] text-slate-500">Non-EU Runtime Calls (<b class="mono">${fmtNum(usCalls)}</b>) vs Non-EU Deployed Resources (<b class="mono ${allNonEuResources.length > 0 ? 'text-rose-600' : ''}">${allNonEuResources.length}</b>)</p>
              </div>
              <span class="jt-badge px-2.5 py-1 rounded-full text-[11px] font-extrabold ${usCalls === 0 && allNonEuResources.length === 0 ? 'jt-badge--green bg-emerald-50 text-emerald-700 border border-emerald-200' : 'jt-badge--amber bg-amber-50 text-amber-800 border border-amber-200'}">
                ${escapeHtml(gdprCompliantPct)}% EU Traffic · ${allNonEuResources.length > 0 ? `<svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> ${escapeHtml(allNonEuResources.length)} Non-EU Res` : '0 Non-EU Res'}
              </span>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              <div class="p-2.5 rounded-lg bg-emerald-50/70 border border-emerald-200">
                <div class="text-[10px] font-bold text-emerald-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Italy (europe-west8)</div>
                <div class="text-base font-extrabold text-emerald-900 mono mt-0.5">${escapeHtml(itPct)}%</div>
                <div class="text-[10px] text-emerald-700 mono">${fmtNum(itCalls)} calls · ${fmtUsd(itCost)}</div>
              </div>
              <div class="p-2.5 rounded-lg bg-blue-50/70 border border-blue-200">
                <div class="text-[10px] font-bold text-blue-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> European Union (EEA)</div>
                <div class="text-base font-extrabold text-blue-900 mono mt-0.5">${escapeHtml(euPct)}%</div>
                <div class="text-[10px] text-blue-700 mono">${fmtNum(euCalls)} calls · ${fmtUsd(euCost)}</div>
              </div>
              <div class="p-2.5 rounded-lg bg-amber-50/70 border border-amber-200">
                <div class="text-[10px] font-bold text-amber-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Global / Multi-Region</div>
                <div class="text-base font-extrabold text-amber-900 mono mt-0.5">${escapeHtml(glPct)}%</div>
                <div class="text-[10px] text-amber-700 mono">${fmtNum(glCalls)} calls · ${fmtUsd(glCost)}</div>
              </div>
              <div class="p-2.5 rounded-lg ${(usCalls > 0 || allNonEuResources.length > 0) ? 'bg-rose-50/80 border-rose-200' : 'bg-slate-50 border-slate-200'} border">
                <div class="text-[10px] font-bold ${(usCalls > 0 || allNonEuResources.length > 0) ? 'text-rose-800' : 'text-slate-500'}"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Non-EU (US / Other)</div>
                <div class="text-base font-extrabold ${(usCalls > 0 || allNonEuResources.length > 0) ? 'text-rose-700' : 'text-slate-700'} mono mt-0.5">${escapeHtml(usPct)}% <span class="text-[10px] font-bold">(${allNonEuResources.length} res)</span></div>
                <div class="text-[10px] ${(usCalls > 0 || allNonEuResources.length > 0) ? 'text-rose-700' : 'text-slate-400'} mono">${fmtNum(usCalls)} calls · ${fmtUsd(usCost)}</div>
              </div>
            </div>
            ${allNonEuResources.length > 0 ? `
              <div class="text-[11px] text-rose-900 bg-rose-50/80 border border-rose-200 rounded-lg px-3 py-2 space-y-1">
                <div class="font-extrabold flex items-center justify-between">
                  <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> Non-EU Deployed Resources (${allNonEuResources.length}) — Non-EU Runtime Calls: ${fmtNum(usCalls)}</span>
                  <span class="jt-badge jt-badge--red px-1.5 py-0.5 rounded bg-rose-100 text-rose-800 text-[10px] mono">GDPR AUDIT</span>
                </div>
                <div class="divide-y divide-rose-200/60">
                  ${allNonEuResources.map(nr => `
                    <div class="py-1 flex flex-wrap items-center justify-between gap-2 mono text-[10px]">
                      <span><b class="text-rose-950">${escapeHtml(nr.name || nr.displayName || nr.resourceId)}</b> <span class="text-rose-700">(${escapeHtml(nr.type || nr.resourceType || 'REASONING_ENGINE')})</span></span>
                      <span><b class="underline cursor-pointer" data-jt-click="openProjectModal(${jsArg(nr.projectId)})">${escapeHtml(nr.projectId)}</b> · <span class="jt-badge jt-badge--red px-1.5 py-0.5 rounded bg-rose-600 text-white font-bold">NON-EU ${escapeHtml(nr.location)}</span></span>
                    </div>
                  `).join('')}
                </div>
              </div>
            ` : ''}
            ${nonEuProjects.length > 0 ? `
              <div class="text-[11px] text-amber-900 bg-amber-50/70 border border-amber-200 rounded-lg px-3 py-1.5">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> <b>Projects with Global / Non-EU traffic:</b> ${nonEuProjects.map(x => `<b class="mono cursor-pointer underline" data-jt-click="openProjectModal(${jsArg(x.projectId)})">${escapeHtml(x.projectId)}</b> (${escapeHtml(x.nonEuPct)}%)`).join(', ')}
              </div>
            ` : ''}
          </div>

          <div class="jt-dash-card bg-white rounded-xl border border-slate-200 p-4 shadow-2xs space-y-3">
            <div class="flex items-center justify-between border-b border-slate-100 pb-2.5">
              <div>
                <h4 class="text-xs font-extrabold uppercase tracking-wider text-emerald-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> FinOps Extended &amp; Context Caching</h4>
                <p class="text-[11px] text-slate-500">Input token cache efficiency, current savings, budgets and idle resources</p>
              </div>
              <span class="jt-badge jt-badge--green px-2.5 py-1 rounded-full text-[11px] font-extrabold bg-emerald-50 text-emerald-700 border border-emerald-200 mono">
                Hit Rate: ${escapeHtml(cacheHitPct)}%
              </span>
            </div>
            <div class="grid grid-cols-3 gap-2 text-xs">
              <div class="p-2.5 rounded-lg bg-emerald-50/60 border border-emerald-200">
                <div class="text-[10px] font-bold text-emerald-800">Current Cache Savings</div>
                <div class="text-base font-extrabold text-emerald-700 mono mt-0.5">-${fmtUsd(totCacheSavings)}</div>
                <div class="text-[10px] text-emerald-800 font-semibold">-${fmtEur(totCacheSavings)} (${fmtTok(totCachedTok)} tok)</div>
              </div>
              <div class="p-2.5 rounded-lg bg-indigo-50/60 border border-indigo-200">
                <div class="text-[10px] font-bold text-indigo-800">Additional Estimated Savings</div>
                <div class="text-base font-extrabold text-indigo-700 mono mt-0.5">${fmtUsd(totExtraPotentialSavings)}</div>
                <div class="text-[10px] text-indigo-700">Raising Cache Hit to 65%</div>
              </div>
              <div class="p-2.5 rounded-lg ${(allIdleResources.length > 0 || allZombieBuilds.length > 0) ? 'bg-amber-50 border-amber-200' : 'bg-slate-50 border-slate-200'} border">
                <div class="text-[10px] font-bold text-slate-600">Idle &amp; Zombie Builds</div>
                <div class="text-base font-extrabold ${(allIdleResources.length > 0 || allZombieBuilds.length > 0) ? 'text-amber-800' : 'text-slate-700'} mono mt-0.5">${allIdleResources.length} Idle · ${allZombieBuilds.length} <svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg></div>
                <div class="text-[10px] text-slate-500">Endpoint / Agent Builds</div>
              </div>
            </div>
            ${allIdleResources.length > 0 ? `
              <div class="text-[11px] text-amber-900 bg-amber-50/70 border border-amber-200 rounded-lg px-3 py-1.5">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> <b>Always-on or no-traffic resources:</b> ${allIdleResources.slice(0, 3).map(ir => `<span class="mono font-bold">${escapeHtml(ir.projectId)}/${escapeHtml(ir.displayName)}</span> (${escapeHtml(ir.reason)})`).join(' · ')}
              </div>
            ` : `
              <div class="text-[11px] text-emerald-800 bg-emerald-50/50 border border-emerald-100 rounded-lg px-3 py-1.5">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> No idle Dedicated Endpoints or Notebook Runtimes detected.
              </div>
            `}
            ${allBudgets.length > 0 ? `
              <div class="text-[10px] text-slate-700 bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5 flex flex-wrap items-center gap-2 mono">
                <b class="text-slate-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Project Budgets:</b>
                ${allBudgets.slice(0, 4).map(b => `<span class="jt-chip px-1.5 py-0.5 rounded ${b.status === 'OVER_BUDGET' ? 'jt-chip--red bg-rose-100 text-rose-800 font-bold' : (b.status === 'WARNING' ? 'jt-chip--amber bg-amber-100 text-amber-800 font-bold' : 'jt-chip--gray bg-white border border-slate-200')}">${escapeHtml(b.projectId)}: ${fmtUsd(b.currentSpendUsd)}/${fmtUsd(b.monthlyBudgetUsd)} (${escapeHtml(b.utilizationPct)}%)</span>`).join('')}
              </div>
            ` : ''}
          </div>
        </div>

        ${allZombieBuilds.length > 0 ? `
        <!-- TABELLA ZOMBIE REASONING ENGINES & OLD CI/CD BUILDS -->
        <div class="jt-table-panel bg-white rounded-xl border border-purple-200 shadow-2xs overflow-hidden">
          <div class="px-4 py-2.5 bg-purple-50/80 border-b border-purple-200 flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <span class="text-xs font-extrabold uppercase tracking-wider text-purple-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Zombie Reasoning Engines &amp; Old CI/CD Builds (${allZombieBuilds.length})</span>
              <span class="jt-badge jt-badge--purple px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 border border-purple-300 text-[10px] font-extrabold mono">CLEANUP CANDIDATES</span>
            </div>
            <span class="text-[11px] text-purple-800 mono">Duplicate/obsolete builds superseded by newer releases</span>
          </div>
          <div class="overflow-y-auto" style="max-height: 260px;">
            <table class="jt-table w-full text-left border-collapse text-xs">
              <thead class="sticky top-0 bg-slate-50 border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                <tr>
                  <th class="py-2 px-3">Project</th>
                  <th class="py-2 px-3">Base Agent</th>
                  <th class="py-2 px-3">Obsolete Build</th>
                  <th class="py-2 px-3">Region</th>
                  <th class="py-2 px-3">Creation Date</th>
                  <th class="py-2 px-3">Replaced by (Latest)</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 mono text-[11px]">
                ${allZombieBuilds.map(zb => {
                  const loc = zb.location || 'europe-west1';
                  const isExtraEu = zb.isEu === false || (!loc.startsWith('europe-') && !loc.startsWith('eu'));
                  return `
                    <tr class="hover:bg-purple-50/30">
                      <td class="py-2 px-3 font-bold text-[#0F2A4A] cursor-pointer underline" data-jt-click="openProjectModal(${jsArg(zb.projectId)})">${escapeHtml(zb.projectId)}</td>
                      <td class="py-2 px-3 font-bold text-slate-800">${escapeHtml(zb.baseName || 'Agent')}</td>
                      <td class="py-2 px-3 text-rose-700 font-semibold">${escapeHtml(zb.name || zb.resourceId)}</td>
                      <td class="py-2 px-3">
                        ${isExtraEu
                          ? `<span class="jt-badge jt-badge--red px-1.5 py-0.5 rounded bg-rose-600 text-white text-[10px] font-extrabold">NON-EU ${escapeHtml(loc)}</span>`
                          : `<span class="jt-badge jt-badge--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] font-bold">${escapeHtml(loc)}</span>`}
                      </td>
                      <td class="py-2 px-3 text-slate-500">${escapeHtml((zb.createTime || '').replace('T', ' ').slice(0, 16) || '—')}</td>
                      <td class="py-2 px-3 text-emerald-800 font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> ${escapeHtml(zb.keptLatestName || 'Latest build')}</td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        </div>
        ` : ''}
      `);
    }

    function _collectGeInventoryFromProjects(visibleProjs, agg, q) {
      const inv = {
        allApps: [], teleApps: [], teleDataStores: [], geAppsEnriched: [],
        geConnectorHubs: [], geDataStoresEnriched: [], geAgentsList: [],
        geAgentCreators: [], geDialogflowAgents: [], geReasoningEngines: [],
        geOauthEvents: [], geRootRuntimeUsers: 0
      };
      const matchesQ = (txt) => !q || txt.toLowerCase().includes(q);

      visibleProjs.forEach(p => {
        (p.deployedAiResources || []).forEach(r => {
          if (r.resourceType === 'AGENTSPACE_APP' && matchesQ(`${r.displayName} ${r.resourceId} ${r.cid || ''} ${p.projectId} ${(r.enabledModels || []).join(' ')}`)) {
            inv.allApps.push({ ...r, projectId: p.projectId, projectName: p.name });
          }
        });
        const at = p.agentspaceTelemetry || {};
        (at.apps || []).forEach(a => {
          if (matchesQ(`${a.displayName} ${a.engineId} ${p.projectId} ${a.defaultModel || ''}`)) inv.teleApps.push({ ...a, projectId: a.projectId || p.projectId });
        });
        (at.dataStores || []).forEach(ds => {
          if (matchesQ(`${ds.displayName} ${ds.dataStoreId} ${ds.connectorType || ''} ${p.projectId}`)) inv.teleDataStores.push({ ...ds, projectId: ds.projectId || p.projectId });
        });

        const gInv = p.geminiEnterpriseInventory || {};
        inv.geRootRuntimeUsers += Number((gInv.summary && gInv.summary.rootAgentRuntimeUsersCount) || 0);
        (gInv.apps || []).forEach(a => {
          if (matchesQ(`${a.displayName} ${a.engineId} ${a.cid || ''} ${p.projectId} ${(a.enabledModels || []).join(' ')} ${(a.enabledFeatures || []).join(' ')}`)) {
            inv.geAppsEnriched.push({ ...a, projectId: a.projectId || p.projectId });
          }
        });
        (gInv.connectorHubs || []).forEach(h => {
          if (matchesQ(`${h.hubDisplayName} ${h.hubId} ${h.vendor || ''} ${h.familyLabel || ''} ${p.projectId} ${(h.dataStoreIds || []).join(' ')}`)) {
            inv.geConnectorHubs.push({ ...h, projectId: h.projectId || p.projectId });
          }
        });
        (gInv.dataStores || []).forEach(d => {
          if (matchesQ(`${d.displayName} ${d.dataStoreId} ${d.vendor || ''} ${d.hubId || ''} ${p.projectId}`)) {
            inv.geDataStoresEnriched.push({ ...d, projectId: d.projectId || p.projectId });
          }
        });
        const agSec = gInv.agentsAndAssistants || {};
        (agSec.geminiEnterpriseAgents || []).forEach(ag => {
          if (matchesQ(`${ag.displayName} ${ag.agentId} ${ag.creatorEmail || ''} ${ag.engineName || ''} ${p.projectId}`)) inv.geAgentsList.push({ ...ag, projectId: ag.projectId || p.projectId });
        });
        (agSec.agentCreatorsAudit || []).forEach(cr => {
          if (matchesQ(`${cr.userEmail} ${cr.primaryEngineName || ''} ${(cr.actionBadges || []).join(' ')} ${p.projectId}`)) inv.geAgentCreators.push({ ...cr, projectId: cr.projectId || p.projectId });
        });
        (agSec.dialogflowAgents || []).forEach(df => {
          if (matchesQ(`${df.displayName} ${df.agentId} ${df.llmModel || ''} ${p.projectId}`)) inv.geDialogflowAgents.push({ ...df, projectId: df.projectId || p.projectId });
        });
        (agSec.reasoningEngines || []).forEach(re => {
          if (matchesQ(`${re.displayName} ${re.resourceId} ${re.baseName || ''} ${p.projectId}`)) inv.geReasoningEngines.push({ ...re, projectId: re.projectId || p.projectId });
        });
        const secGov = gInv.securityAndGovernance || {};
        (secGov.connectorOAuthEvents || []).forEach(oe => {
          if (matchesQ(`${oe.principalEmail} ${oe.credentialId || ''} ${p.projectId}`)) inv.geOauthEvents.push({ ...oe, projectId: oe.projectId || p.projectId });
        });
      });

      const sAt = (globalScanData.summary && globalScanData.summary.agentspaceTelemetry) || {};
      const sGe = (globalScanData.summary && globalScanData.summary.geminiEnterpriseInventory) || {};
      if (agg.selProj === 'ALL' && !q) {
        const fillIfEmpty = (target, src) => { if (target.length === 0 && (src || []).length > 0) src.forEach(x => target.push(x)); };
        fillIfEmpty(inv.teleApps, sAt.apps);
        fillIfEmpty(inv.teleDataStores, sAt.dataStores);
        fillIfEmpty(inv.geAppsEnriched, sGe.apps);
        fillIfEmpty(inv.geConnectorHubs, sGe.connectorHubs);
        fillIfEmpty(inv.geDataStoresEnriched, sGe.dataStores);
        const sAg = sGe.agentsAndAssistants || {};
        fillIfEmpty(inv.geAgentsList, sAg.geminiEnterpriseAgents);
        fillIfEmpty(inv.geAgentCreators, sAg.agentCreatorsAudit);
        fillIfEmpty(inv.geDialogflowAgents, sAg.dialogflowAgents);
        fillIfEmpty(inv.geReasoningEngines, sAg.reasoningEngines);
        fillIfEmpty(inv.geOauthEvents, sGe.securityAndGovernance && sGe.securityAndGovernance.connectorOAuthEvents);
        if (!inv.geRootRuntimeUsers && sGe.summary) inv.geRootRuntimeUsers = Number(sGe.summary.rootAgentRuntimeUsersCount || 0);
      }

      window._lastGeInventoryState = {
        apps: inv.geAppsEnriched,
        hubs: inv.geConnectorHubs,
        dataStores: inv.geDataStoresEnriched,
        agents: inv.geAgentsList,
        creators: inv.geAgentCreators,
        dialogflow: inv.geDialogflowAgents,
        reasoningEngines: inv.geReasoningEngines,
        oauthEvents: inv.geOauthEvents
      };
      return inv;
    }

    function _buildGeKpiStripAndNavHtml(ctx) {
      const {
        enterpriseApps, searchApps, selOnCount, selOffCount, totActiveFeatures,
        geDataStoresEnriched, teleDataStores, geConnectorHubs, thirdPartyHubs,
        geAgentsList, geAgentCreators, geDialogflowAgents, activeReList,
        geRootRuntimeUsers, geOauthEvents, activeSubView
      } = ctx;
      return `
        <div class="jt-kpi-grid grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-2.5">
          <div class="jt-kpi bg-white rounded-xl border border-indigo-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-indigo-900">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> ENTERPRISE APPS</span>
              <span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-800 mono">AGENTSPACE</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-[#0F2A4A] mono mt-1">${enterpriseApps.length} Enterprise <span class="text-slate-300">|</span> <span class="text-slate-600 text-xs">${searchApps.length} Search</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> ${escapeHtml(selOnCount)} Selector ON · <svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> ${escapeHtml(selOffCount)} Selector OFF</div>
          </div>

          <div class="jt-kpi bg-white rounded-xl border border-emerald-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-emerald-900">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> FEATURE FLAGS</span>
              <span class="jt-chip jt-chip--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 mono">CONFIG</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-emerald-800 mono mt-1">${escapeHtml(totActiveFeatures)} Flag ON</div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5">No-Code Agent, Deep Research, NotebookLM</div>
          </div>

          <div class="jt-kpi bg-white rounded-xl border border-blue-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-blue-900">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> CONNECTOR HUBS</span>
              <span class="jt-chip jt-chip--blue px-1.5 py-0.5 rounded bg-blue-50 text-blue-800 mono">${geDataStoresEnriched.length || teleDataStores.length} DS</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-blue-900 mono mt-1">${geConnectorHubs.length} Hub <span class="text-xs font-bold text-indigo-700">(${thirdPartyHubs.length} External SaaS)</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5">Confluence Wiki (6), DocuSign (3), GCP (13)</div>
          </div>

          <div class="jt-kpi bg-white rounded-xl border border-purple-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-purple-900">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> AGENTS &amp; OWNERS</span>
              <span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-purple-50 text-purple-800 mono">LIFECYCLE</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-purple-900 mono mt-1">${geAgentsList.length} Agents <span class="text-slate-300">|</span> <span class="text-xs">${geAgentCreators.length} Owner/Builder</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5">${geDialogflowAgents.length} Dialogflow · ${activeReList.length} ADK · ${escapeHtml(geRootRuntimeUsers)} runtime users</div>
          </div>

          <div class="jt-kpi bg-white rounded-xl border border-amber-200 p-3 shadow-2xs">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-amber-900">
              <span class="jt-kpi__label"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> OAUTH &amp; KEYS</span>
              <span class="jt-chip jt-chip--amber px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 mono">TOKENS</span>
            </div>
            <div class="jt-kpi__value text-base font-extrabold text-amber-900 mono mt-1">${geOauthEvents.length} Principal OAuth</div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-0.5">AcquireAndStoreRefreshToken &amp; AccessToken</div>
          </div>

          <div class="bg-gradient-to-br from-[#0F2A4A] to-indigo-950 text-white rounded-xl p-3 shadow-2xs flex flex-col justify-between">
            <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-blue-200">
              <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> LIVE PROBE v1alpha</span>
              <span class="px-1.5 py-0.5 rounded bg-white/15 text-white mono">READ-ONLY</span>
            </div>
            <div class="text-[11px] font-bold text-blue-100 mt-1">Real-time REST inspection of Engine, DataConnector &amp; Agents</div>
            <button type="button" data-jt-click="openGeminiInspectorModal('ENGINE', ${jsArg(enterpriseApps[0] ? enterpriseApps[0].projectId : 'default-project')}, ${jsArg(enterpriseApps[0] ? (enterpriseApps[0].engineId || enterpriseApps[0].resourceId) : 'gemini-enterprise-engine')}, ${jsArg(enterpriseApps[0] ? (enterpriseApps[0].location || 'eu') : 'eu')})" class="mt-1.5 w-full py-1 px-2 rounded bg-white text-[#0F2A4A] hover:bg-blue-50 font-extrabold text-[10px] transition cursor-pointer">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Open Live 360° Inspector
            </button>
          </div>
        </div>

        <!-- BARRA DI FILTRO SEZIONI INTERNA GEMINI ENTERPRISE (chip filtro inline D4) -->
        <div class="jt-ge-filter-bar">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500 mr-1">Section filter:</span>
            <button type="button" data-jt-click="switchGeminiEnterpriseSubView('ALL')" data-ge-subbtn="ALL" title="Full 360° View (All Gemini Enterprise sections)" class="jt-ge-filter-chip ${activeSubView === 'ALL' ? 'active px-2.5 py-1 rounded-full text-[11px] font-bold transition cursor-pointer bg-[#0F2A4A] text-white' : 'px-2.5 py-1 rounded-full text-[11px] font-semibold transition cursor-pointer bg-white text-slate-600 border border-slate-200 hover:bg-slate-100'}">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> All 360°
            </button>
            <button type="button" data-jt-click="switchGeminiEnterpriseSubView('APPS')" data-ge-subbtn="APPS" title="1. Apps, Models &amp; Feature Flags (${enterpriseApps.length} Enterprise + ${searchApps.length} Search)" class="jt-ge-filter-chip ${activeSubView === 'APPS' ? 'active px-2.5 py-1 rounded-full text-[11px] font-bold transition cursor-pointer bg-[#0F2A4A] text-white' : 'px-2.5 py-1 rounded-full text-[11px] font-semibold transition cursor-pointer bg-white text-slate-600 border border-slate-200 hover:bg-slate-100'}">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Apps &amp; Flags (${enterpriseApps.length + searchApps.length})
            </button>
            <button type="button" data-jt-click="switchGeminiEnterpriseSubView('CONNECTORS')" data-ge-subbtn="CONNECTORS" title="2. Connectors (Confluence, DocuSign, Workspace, GCP) &amp; DataStores (${geConnectorHubs.length} Hub / ${geDataStoresEnriched.length || teleDataStores.length} DS)" class="jt-ge-filter-chip ${activeSubView === 'CONNECTORS' ? 'active px-2.5 py-1 rounded-full text-[11px] font-bold transition cursor-pointer bg-[#0F2A4A] text-white' : 'px-2.5 py-1 rounded-full text-[11px] font-semibold transition cursor-pointer bg-white text-slate-600 border border-slate-200 hover:bg-slate-100'}">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> Connectors &amp; DS (${geConnectorHubs.length} / ${geDataStoresEnriched.length || teleDataStores.length})
            </button>
            <button type="button" data-jt-click="switchGeminiEnterpriseSubView('AGENTS')" data-ge-subbtn="AGENTS" title="3. Agents Created (${geAgentsList.length}), IAM Owners (${geAgentCreators.length}), Dialogflow &amp; ADK" class="jt-ge-filter-chip ${activeSubView === 'AGENTS' ? 'active px-2.5 py-1 rounded-full text-[11px] font-bold transition cursor-pointer bg-[#0F2A4A] text-white' : 'px-2.5 py-1 rounded-full text-[11px] font-semibold transition cursor-pointer bg-white text-slate-600 border border-slate-200 hover:bg-slate-100'}">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Agents &amp; Owners (${geAgentsList.length})
            </button>
            <button type="button" data-jt-click="switchGeminiEnterpriseSubView('SECURITY')" data-ge-subbtn="SECURITY" title="4. Keys, Connector OAuth &amp; CLI Commands (${geOauthEvents.length})" class="jt-ge-filter-chip ${activeSubView === 'SECURITY' ? 'active px-2.5 py-1 rounded-full text-[11px] font-bold transition cursor-pointer bg-[#0F2A4A] text-white' : 'px-2.5 py-1 rounded-full text-[11px] font-semibold transition cursor-pointer bg-white text-slate-600 border border-slate-200 hover:bg-slate-100'}">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> OAuth &amp; CLI (${geOauthEvents.length})
            </button>
          </div>
          <span class="text-[10px] text-slate-400 mono pr-1">100% Read-Only Discovery (v1alpha + Cloud Audit Logs)</span>
        </div>
      `;
    }

    function _renderSingleEnterpriseAppCard(app, geAgentsList) {
      const engId = app.engineId || app.resourceId || '';
      const selOn = app.modelSelector === 'ON';
      const enModels = app.enabledModels || [];
      const disModels = app.disabledModels || [];
      const enFeats = app.enabledFeatures || [];
      const disFeats = app.disabledFeatures || [];
      const featsDetailed = app.featuresDetailed || [];
      const linkedHubs = app.linkedConnectorHubs || [];
      const cfgUrl = app.configUrl || `https://console.cloud.google.com/gen-app-builder/locations/${app.location}/engines/${engId}/configurations?project=${app.projectId}`;
      const ovUrl = app.overviewUrl || `https://console.cloud.google.com/gen-app-builder/locations/${app.location}/engines/${engId}/overview?project=${app.projectId}`;
      const webUrl = app.webAppUrl || (app.cid ? `https://vertexaisearch.cloud.google.com/${app.location === 'eu' || app.location === 'us' ? app.location : 'global'}/home/cid/${app.cid}` : '');
      const queriesCnt = app.queriesCount ?? app.queries ?? 0;
      const usersCnt = app.activeUsersCount ?? 0;
      const dsCnt = app.linkedDataStoresCount || app.dataStoresCount || (app.dataStoreIds ? app.dataStoreIds.length : 0);
      const obsEnabled = Boolean(app.observabilityEnabled);
      const licPool = app.licensePool || {};
      const licState = app.licenseState || licPool.state || (app.location === 'global' ? 'EXPIRED' : 'ACTIVE');
      const licCfgs = licPool.configs || [];
      const rawEnd = licCfgs[0] && licCfgs[0].endDate;
      const licEnd = typeof rawEnd === 'string' ? rawEnd : (rawEnd && rawEnd.year ? `${rawEnd.year}-${String(rawEnd.month).padStart(2, '0')}-${String(rawEnd.day).padStart(2, '0')}` : '');
      const licTier = licCfgs[0] && licCfgs[0].subscriptionTier ? licCfgs[0].subscriptionTier.replace('SUBSCRIPTION_TIER_', '') : '';
      const blockedUsers = licPool.unassignedBlockedUsers || [];
      const appAgents = (app.agents && app.agents.length > 0) ? app.agents : geAgentsList.filter(ag => ag.engineId === engId);
      const appAgentsCnt = app.agentsCount ?? appAgents.length;
      const appOwners = app.agentOwners || [];
      const appOwnersCnt = app.agentOwnersCount ?? appOwners.length;
      const appGroups = app.agentGroups || [];
      const appSessionsCnt = app.sessionsCount ?? 0;
      const appAuditUsers = app.auditUsers || [];
      const ownerEmailsSet = new Set(appOwners.map(o => (typeof o === 'string' ? o : (o.email || o.userEmail || '')).toLowerCase()).filter(Boolean));
      const totPrincipals = app.totalDetectedPrincipalsCount ?? Math.max(usersCnt, appOwnersCnt + appAuditUsers.length);

      return `
        <div class="bg-white rounded-xl border-2 ${licState === 'EXPIRED' ? 'border-rose-300' : (selOn ? 'border-indigo-200' : 'border-amber-300')} p-4 shadow-2xs space-y-3">
          <div class="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 pb-2.5">
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-extrabold text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> ${escapeHtml(app.displayName)}</span>
                <span class="px-2 py-0.5 rounded-full text-[10px] font-extrabold ${app.location === 'eu' || (app.location || '').startsWith('eu') ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-rose-50 text-rose-800 border border-rose-200'} mono">${escapeHtml(app.projectId)} (${escapeHtml(app.location)})</span>
                <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-700 mono">${escapeHtml(app.appType || 'INTRANET')} · ${escapeHtml(app.solutionType || 'GENERATIVE_CHAT')}</span>
                ${app.companyName ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-800 border border-indigo-200"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> ${escapeHtml(app.companyName)}</span>` : ''}
              </div>
              <div class="text-[11px] text-slate-500 mono mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span>Engine ID: <b class="text-slate-800 select-all">${escapeHtml(engId)}</b></span>
                ${app.cid ? `<span>· Web CID: <b class="text-indigo-700 select-all">${escapeHtml(app.cid)}</b></span>` : ''}
                <span>· <b>${escapeHtml(dsCnt)} DataStores (${linkedHubs.length} Hub)</b></span>
                <span>· <b class="text-purple-800">${fmtNum(appAgentsCnt)} Agents</b> (${fmtNum(appOwnersCnt)} IAM Owners${escapeHtml(appSessionsCnt > 0 ? ` · ${appSessionsCnt} sessions` : '')})</span>
                <span>· <b class="${queriesCnt > 0 ? 'text-emerald-700' : 'text-slate-500'}">${fmtNum(queriesCnt)} query log</b> (${fmtNum(usersCnt)} query users · ${fmtNum(totPrincipals)} total users detected)</span>
              </div>
            </div>
            <div class="flex items-center gap-1.5 flex-wrap">
              <span class="px-2.5 py-1 rounded-full text-[10px] font-extrabold border ${selOn ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-800 border-amber-300'}">
                ${selOn ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> model-selector: ON' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> model-selector: OFF'}
              </span>
              <button type="button" data-jt-click="openGeminiInspectorModal('ENGINE', ${jsArg(app.projectId)}, ${jsArg(engId)}, ${jsArg(app.location || 'eu')})" class="px-2.5 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-extrabold text-[10px] transition cursor-pointer shadow-2xs">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Inspect 360°
              </button>
            </div>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
            <div class="p-2 rounded-lg border ${licState === 'EXPIRED' ? 'bg-rose-50 border-rose-300 text-rose-950' : 'bg-emerald-50/70 border-emerald-200 text-emerald-950'}">
              <div class="font-extrabold flex items-center justify-between">
                <span>${licState === 'EXPIRED' ? `<svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> ${escapeHtml(`License Pool (${(app.location || '').toUpperCase()}): EXPIRED`)}` : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> ${escapeHtml(`License Pool (${(app.location || '').toUpperCase()}): ACTIVE`)}`}</span>
                <span class="mono text-[10px] px-1.5 py-0.5 rounded bg-white/80 border ${licState === 'EXPIRED' ? 'border-rose-200 text-rose-800' : 'border-emerald-200 text-emerald-800'}">${escapeHtml(licPool.assignedCount || 0)}/${escapeHtml(licPool.totalSeats || 0)} seats</span>
              </div>
              <div class="text-[10px] mt-0.5">
                ${licState === 'EXPIRED'
                  ? `Free Trial expired on <b>${escapeHtml(licEnd || '2025-11-30')}</b> (${escapeHtml(licTier || 'TRIAL')}). ${blockedUsers.length > 0 ? `<b class="text-rose-800">${blockedUsers.length} logins blocked without a license</b> (${blockedUsers.map(u => escapeHtml(typeof u === 'string' ? u : (u.email || u.userEmail || ''))).filter(Boolean).join(', ')})` : ''}`
                  : `Contract <b>${escapeHtml(licTier || 'ENTERPRISE')}</b> valid until <b>${escapeHtml(licEnd || '2026-12-22')}</b> · <b>${escapeHtml(licPool.activeLogins30dCount || 0)}</b> active users in the last 30d.`}
              </div>
            </div>
            <div class="p-2 rounded-lg border ${obsEnabled ? 'bg-blue-50/70 border-blue-200 text-blue-950' : 'bg-amber-50/80 border-amber-200 text-amber-950'}">
              <div class="font-extrabold flex items-center justify-between">
                <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> Query Telemetry (<code class="mono text-[10px]">observabilityEnabled</code>):</span>
                <span class="mono text-[10px] px-1.5 py-0.5 rounded font-extrabold ${obsEnabled ? 'bg-emerald-600 text-white' : 'bg-amber-500 text-white'}">${obsEnabled ? 'ON' : 'OFF'}</span>
              </div>
              <div class="text-[10px] mt-0.5">
                ${obsEnabled
                  ? `User activity logging is active in Cloud Logging (<b>${fmtNum(queriesCnt)}</b> queries and <b>${fmtNum(usersCnt)}</b> users tracked).`
                  : `User activity logging is <b>DISABLED</b> on this Engine (so Cloud Logging shows 0 queries even though there are <b>${escapeHtml(appAgentsCnt)} agents</b> and <b>${escapeHtml(appOwnersCnt)} IAM owners</b>).`}
              </div>
            </div>
          </div>

          ${!selOn ? `
            <div class="p-2.5 rounded-lg bg-amber-50/80 border border-amber-200 text-[11px] text-amber-900">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> <b>Model Configuration Note:</b> In this App the model selector (<code class="mono">model-selector</code>) is <b>OFF</b> and only <b>${escapeHtml(enModels.join(', ') || 'gemini-2.5-pro')}</b> responds (${disModels.length} models disabled).
            </div>
          ` : ''}

          <div class="p-2.5 rounded-lg bg-purple-50/60 border border-purple-200 space-y-1.5 text-xs">
            <div class="flex flex-wrap items-center justify-between gap-1">
              <span class="text-[10px] font-extrabold uppercase tracking-wider text-purple-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Agents Configured in the App (${escapeHtml(appAgentsCnt)}) &amp; IAM Owners (${escapeHtml(appOwnersCnt)} Users${escapeHtml(appGroups.length > 0 ? ` · ${appGroups.length} Groups` : '')}):</span>
              ${appSessionsCnt > 0 ? `<span class="px-1.5 py-0.5 rounded bg-purple-100 text-purple-900 font-extrabold text-[9px] mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${escapeHtml(appSessionsCnt)} Conversational Sessions</span>` : ''}
            </div>
            ${appAgents.length > 0 ? `
              <div class="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                ${appAgents.slice(0, 16).map(ag => `
                  <span class="px-2 py-0.5 rounded bg-white border border-purple-200 text-purple-950 text-[10px] font-bold inline-flex items-center gap-1" title="${escapeHtml(ag.description || ag.instructionPreview || '')}${escapeHtml(ag.creatorEmail ? ' · Owner: ' + ag.creatorEmail : '')}">
                    <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> ${escapeHtml(ag.displayName)}</span>
                    ${ag.llmModel ? `<span class="text-[9px] mono text-indigo-700">(${escapeHtml(ag.llmModel)})</span>` : ''}
                  </span>
                `).join('')}
                ${appAgents.length > 16 ? `<button type="button" data-jt-click="openGeminiInspectorModal('ENGINE', ${jsArg(app.projectId)}, ${jsArg(engId)}, ${jsArg(app.location || 'eu')})" class="px-2 py-0.5 rounded bg-purple-700 text-white text-[10px] font-extrabold cursor-pointer">+ ${appAgents.length - 16} more agents (View all)</button>` : ''}
              </div>
            ` : `<div class="text-[11px] text-slate-400">No custom agents registered in the Assistant.</div>`}
            ${(appOwners.length > 0 || appGroups.length > 0 || appAuditUsers.length > 0) ? `
              <div class="pt-1 border-t border-purple-200/60 flex flex-wrap items-center gap-1 text-[10px]">
                <span class="font-extrabold text-purple-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> Detected Owners / Users:</span>
                ${appOwners.slice(0, 8).map(o => {
                  const emStr = typeof o === 'string' ? o : (o.email || o.userEmail || '');
                  const cnt = (typeof o === 'object' && o && o.agentsCount) ? ` <span class="text-[9px] text-purple-700 font-mono">(${escapeHtml(o.agentsCount)})</span>` : '';
                  return `<span class="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-800 font-semibold">${renderUserEmailClickable(emStr)}${cnt}</span>`;
                }).join('')}
                ${appOwners.length > 8 ? `<span class="px-1.5 py-0.5 rounded bg-purple-100 text-purple-900 font-bold mono">+${appOwners.length - 8} owners</span>` : ''}
                ${appGroups.map(g => `<span class="px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-900 border border-indigo-200 font-bold mono" title="IAM group authorized on the agent"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> ${escapeHtml(g)}</span>`).join('')}
                ${appAuditUsers.filter(u => {
                  const uEm = (typeof u === 'string' ? u : (u.email || u.userEmail || '')).toLowerCase();
                  return uEm && !ownerEmailsSet.has(uEm);
                }).map(u => {
                  const uEm = typeof u === 'string' ? u : (u.email || u.userEmail || '');
                  return `<span class="px-1.5 py-0.5 rounded bg-amber-50 text-amber-900 border border-amber-200 font-semibold" title="Detected in Cloud Audit Logs on this Engine"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> ${renderUserEmailClickable(uEm)}</span>`;
                }).join('')}
              </div>
            ` : ''}
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs bg-slate-50/80 p-2.5 rounded-lg border border-slate-200/80">
            <div>
              <span class="text-[10px] font-extrabold uppercase tracking-wider text-emerald-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Enabled LLM Models (${enModels.length}):</span>
              <div class="flex flex-wrap gap-1 mt-1">
                ${enModels.length > 0
                  ? enModels.map(m => `<span class="px-2 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 text-[10px] font-bold mono">${escapeHtml(m)}</span>`).join('')
                  : `<span class="text-slate-400 text-[11px]">gemini-2.5-pro (Default)</span>`}
              </div>
            </div>
            <div>
              <span class="text-[10px] font-extrabold uppercase tracking-wider text-slate-500"><svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg> Disabled Models (${disModels.length}):</span>
              <div class="flex flex-wrap gap-1 mt-1">
                ${disModels.length > 0
                  ? disModels.map(m => `<span class="px-1.5 py-0.5 rounded bg-white text-slate-500 border border-slate-200 text-[10px] mono">${escapeHtml(m)}</span>`).join('')
                  : `<span class="text-emerald-700 text-[10px] font-semibold">All available models are active</span>`}
              </div>
            </div>
          </div>

          ${linkedHubs.length > 0 ? `
            <div class="space-y-1">
              <div class="text-[10px] font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> Connector Hubs &amp; Data Sources Mounted on the App (${linkedHubs.length} Hubs / ${escapeHtml(dsCnt)} Entities):</div>
              <div class="flex flex-wrap gap-1.5">
                ${linkedHubs.map(lh => `
                  <button type="button" data-jt-click="openGeminiInspectorModal('CONNECTOR', ${jsArg(app.projectId)}, ${jsArg(lh.hubId)}, ${jsArg(app.location || 'eu')})" class="px-2 py-1 rounded-lg bg-blue-50/80 hover:bg-blue-100 text-blue-950 border border-blue-200 text-[10px] font-bold transition cursor-pointer flex items-center gap-1" title="Click to inspect connector ${escapeHtml(lh.hubDisplayName)} (${escapeHtml(lh.entities.join(', '))})">
                    <span>${lh.icon ? escapeHtml(lh.icon) : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg>`}</span>
                    <span>${escapeHtml(lh.hubDisplayName)}</span>
                    <span class="px-1 py-0.2 rounded bg-white text-blue-800 mono text-[9px] border border-blue-200">${lh.entities.length} entities</span>
                    ${lh.queriesCount > 0 ? `<span class="px-1 py-0.2 rounded bg-emerald-100 text-emerald-800 mono text-[9px]" title="Queries logged on the shared DataStore in region ${escapeHtml(app.location)}">${fmtNum(lh.queriesCount)} q${queriesCnt === 0 ? ' (shared DS)' : ''}</span>` : ''}
                  </button>
                `).join('')}
              </div>
            </div>
          ` : ''}

          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-extrabold uppercase tracking-wider text-slate-700"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Engine Feature Flags Configuration (${enFeats.length} ON · ${disFeats.length} OFF):</span>
              <span class="text-[9px] text-slate-400 mono">v1alpha engine.features</span>
            </div>
            <div class="flex flex-wrap gap-1 max-h-32 overflow-y-auto p-1.5 rounded-lg bg-slate-50 border border-slate-200/70">
              ${featsDetailed.length > 0
                ? featsDetailed.map(f => {
                    const isOn = f.state === 'ON';
                    return `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold mono border ${isOn ? 'bg-emerald-50 text-emerald-900 border-emerald-200' : 'bg-slate-100 text-slate-400 border-slate-200 line-through'}" title="${escapeHtml(f.category)}: ${escapeHtml(f.label)} — ${escapeHtml(f.description)}">${isOn ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg>' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg>'} ${escapeHtml(f.key)}</span>`;
                  }).join('')
                : enFeats.map(fk => `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold mono bg-emerald-50 text-emerald-900 border border-emerald-200"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> ${escapeHtml(fk)}</span>`).join('')}
            </div>
          </div>

          <div class="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-1.5">
              <a href="${escapeHtml(cfgUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1.5 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[11px] transition inline-flex items-center gap-1">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Configure in GCP ↗
              </a>
              <a href="${escapeHtml(ovUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-[11px] transition">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Overview ↗
              </a>
              ${webUrl ? `
                <a href="${escapeHtml(webUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1.5 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-800 border border-indigo-200 font-bold text-[11px] transition">
                  <svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Open Web App (CID) ↗
                </a>
              ` : ''}
            </div>
            <button type="button" data-jt-click="openGeminiInspectorModal('ENGINE', ${jsArg(app.projectId)}, ${jsArg(engId)}, ${jsArg(app.location || 'eu')})" class="px-2.5 py-1.5 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-800 border border-emerald-300 font-extrabold text-[11px] transition cursor-pointer">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> REST v1alpha Probe &amp; Details
            </button>
          </div>
        </div>
      `;
    }

    function _renderGeEnterpriseAppsCards(enterpriseApps, geAgentsList) {
      if (!enterpriseApps || enterpriseApps.length === 0) return '';
      return `<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        ${enterpriseApps.map(app => _renderSingleEnterpriseAppCard(app, geAgentsList)).join('')}
      </div>`;
    }

    function _renderGeSearchAppsTable(searchApps) {
      if (!searchApps || searchApps.length === 0) return '';
      return `<div class="jt-table-panel bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
        <div class="px-4 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <span class="text-[11px] font-bold uppercase tracking-wider text-slate-600"><svg class="jt-ico" aria-hidden="true"><use href="#ico-search"/></svg> Other Vertex AI Search &amp; Conversation Apps (${searchApps.length})</span>
          <span class="text-[10px] text-slate-400 mono">RAG / BigQuery / Document search engines</span>
        </div>
        <div class="overflow-x-auto">
          <table class="jt-table w-full text-left border-collapse text-xs">
            <thead>
              <tr class="border-b border-slate-200 text-[10px] font-bold uppercase text-slate-400 bg-slate-50/50">
                <th class="py-2 px-4">App Name</th>
                <th class="py-2 px-4">Engine ID</th>
                <th class="py-2 px-4">Project &amp; Region</th>
                <th class="py-2 px-4">Linked DataStores</th>
                <th class="py-2 px-4 text-right">Actions &amp; GCP Console</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              ${searchApps.map(app => {
                const engId = app.engineId || app.resourceId || '';
                const cfgUrl = app.configUrl || `https://console.cloud.google.com/gen-app-builder/locations/${app.location}/engines/${engId}/configurations?project=${app.projectId}`;
                const ovUrl = app.overviewUrl || `https://console.cloud.google.com/gen-app-builder/locations/${app.location}/engines/${engId}/overview?project=${app.projectId}`;
                const dsCnt = app.linkedDataStoresCount || app.dataStoresCount || (app.dataStoreIds ? app.dataStoreIds.length : 0);
                return `
                  <tr class="hover:bg-slate-50">
                    <td class="py-2.5 px-4 font-bold text-slate-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-search"/></svg> ${escapeHtml(app.displayName)}</td>
                    <td class="py-2.5 px-4 mono text-slate-500 text-[11px]">${escapeHtml(engId)}</td>
                    <td class="py-2.5 px-4 mono text-slate-700 font-semibold">${escapeHtml(app.projectId)} <span class="text-slate-400">(${escapeHtml(app.location)})</span></td>
                    <td class="py-2.5 px-4 mono text-slate-600">${escapeHtml(dsCnt)} DataStore</td>
                    <td class="py-2.5 px-4 text-right whitespace-nowrap">
                      <button type="button" data-jt-click="openGeminiInspectorModal('ENGINE', ${jsArg(app.projectId)}, ${jsArg(engId)}, ${jsArg(app.location || 'global')})" class="px-2.5 py-1 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-800 border border-indigo-200 font-bold text-[10px] transition cursor-pointer mr-1"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Inspect</button>
                      <a href="${escapeHtml(cfgUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[10px] transition"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Configure ↗</a>
                      <a href="${escapeHtml(ovUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-[10px] transition ml-1"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Overview ↗</a>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>`;
    }

    function _renderGeConnectorsSectionHtml(geConnectorHubs, thirdPartyHubs, workspaceAndNlmHubs, gcpAndOtherHubs, geDataStoresEnriched) {
      if (!geConnectorHubs || geConnectorHubs.length === 0) return '';
      return `
        <div class="jt-dash-card bg-white rounded-xl border border-blue-200 shadow-2xs p-4 space-y-4">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <h4 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> Enterprise Connectors (Confluence, DocuSign, Google Workspace, GCP Asset Inventory) &amp; Recovered Configurations</h4>
                <span class="jt-badge jt-badge--blue px-2 py-0.5 rounded-full bg-blue-50 text-blue-800 border border-blue-200 text-[10px] font-extrabold mono">${geConnectorHubs.length} Connector Hubs · ${geDataStoresEnriched.length} DataStores</span>
              </div>
              <p class="text-[11px] text-slate-500 mt-0.5">Smart grouping of Collections and multi-entity DataStores with decoded creation timestamps, OAuth/API Token protocol, ACLs and <code class="mono">dataConnector</code>.</p>
            </div>
            <div class="inline-flex flex-wrap items-center gap-1 text-[10px] font-bold">
              <button type="button" id="hub-filter-btn-ALL" data-jt-click="filterGeminiConnectorHubs('ALL')" class="px-2.5 py-1 rounded-lg bg-[#0F2A4A] text-white cursor-pointer transition">All (${geConnectorHubs.length})</button>
              <button type="button" id="hub-filter-btn-SAAS" data-jt-click="filterGeminiConnectorHubs('SAAS')" class="px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-800 border border-indigo-200 hover:bg-indigo-100 cursor-pointer transition"><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> External SaaS: Confluence &amp; DocuSign (${thirdPartyHubs.length})</button>
              <button type="button" id="hub-filter-btn-WORKSPACE" data-jt-click="filterGeminiConnectorHubs('WORKSPACE')" class="px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100 cursor-pointer transition"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Google Workspace &amp; NotebookLM (${workspaceAndNlmHubs.length})</button>
              <button type="button" id="hub-filter-btn-GCP" data-jt-click="filterGeminiConnectorHubs('GCP')" class="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer transition"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> GCP Asset &amp; DataStores (${gcpAndOtherHubs.length})</button>
            </div>
          </div>

          <div id="ge-connector-hubs-grid" class="grid grid-cols-1 lg:grid-cols-2 gap-3.5">
            ${geConnectorHubs.map(h => {
              const catGroup = h.isThirdPartySaaS ? 'SAAS' : ((h.family === 'GOOGLE_WORKSPACE' || h.family === 'NOTEBOOK_LM') ? 'WORKSPACE' : 'GCP');
              const paramsObj = h.recoveredParams || {};
              const paramEntries = Object.entries(paramsObj);
              const createdStr = h.createTime ? h.createTime.replace('T', ' ').slice(0, 16) + ' UTC' : 'N/A';
              const linkedAppsNames = (h.linkedApps || []).map(la => la.displayName || la.engineId);

              return `
                <div class="ge-hub-card rounded-xl border ${h.isThirdPartySaaS ? 'border-2 border-indigo-300 bg-indigo-50/15' : 'border-slate-200 bg-white'} p-3.5 shadow-2xs space-y-2.5 flex flex-col justify-between" data-hub-group="${escapeHtml(catGroup)}">
                  <div class="space-y-2.5">
                    <div class="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 pb-2">
                      <div>
                        <div class="flex items-center gap-1.5 flex-wrap">
                          <span class="text-base">${h.icon ? escapeHtml(h.icon) : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg>`}</span>
                          <span class="text-xs font-extrabold text-[#0F2A4A]">${escapeHtml(h.hubDisplayName)}</span>
                          <span class="jt-badge px-2 py-0.5 rounded-full text-[9px] font-extrabold ${h.isThirdPartySaaS ? 'jt-badge--purple bg-indigo-600 text-white' : 'jt-badge--gray bg-slate-100 text-slate-700'} mono">${escapeHtml(h.vendor)}</span>
                          <span class="jt-chip jt-chip--blue px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-50 text-blue-800 border border-blue-200 mono">${escapeHtml(h.projectId)} (${escapeHtml(h.location)})</span>
                        </div>
                        <div class="text-[10px] text-slate-500 mono mt-1">
                          Collection / Hub ID: <b class="text-slate-800 select-all">${escapeHtml(h.hubId)}</b> · Created: <b>${escapeHtml(createdStr)}</b>
                        </div>
                      </div>
                      <div class="flex items-center gap-1.5">
                        <span class="jt-badge px-2 py-0.5 rounded-full text-[9px] font-extrabold ${h.totalQueries > 0 ? 'jt-badge--green bg-emerald-50 text-emerald-700 border border-emerald-200' : (h.linkedAppsCount > 0 ? 'jt-badge--blue bg-blue-50 text-blue-800 border border-blue-200' : 'jt-badge--amber bg-amber-50 text-amber-800 border border-amber-200')} mono">
                          ${h.totalQueries > 0 ? `<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> ${escapeHtml(fmtNum(h.totalQueries))} QUERY` : (h.linkedAppsCount > 0 ? `<svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> MOUNTED ON APP` : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg> CONFIGURED (0 Q)`)}
                        </span>
                        <button type="button" data-jt-click="openGeminiInspectorModal('CONNECTOR', ${jsArg(h.projectId)}, ${jsArg(h.hubId)}, ${jsArg(h.location || 'eu')})" class="px-2 py-1 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[10px] transition cursor-pointer">
                          <svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Inspect Hub
                        </button>
                      </div>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px] bg-slate-50 p-2.5 rounded-lg border border-slate-200/80">
                      <div>
                        <div class="font-extrabold uppercase tracking-wider text-slate-400 text-[9px]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> Authentication &amp; Credentials</div>
                        <div class="font-bold text-slate-800 mt-0.5">${escapeHtml(h.authModel || 'Google Cloud IAM')}</div>
                      </div>
                      <div>
                        <div class="font-extrabold uppercase tracking-wider text-slate-400 text-[9px]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> Sync &amp; Refresh Protocol</div>
                        <div class="font-semibold text-slate-700 mt-0.5">${escapeHtml(h.syncProtocol || 'DiscoveryEngine Sync')} (${escapeHtml(h.refreshInterval || 'Continuous')})</div>
                      </div>
                    </div>

                    <div class="space-y-1">
                      <div class="text-[9px] font-extrabold uppercase tracking-wider text-slate-500"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Recovered Connector Parameters &amp; Endpoints:</div>
                      <div class="bg-slate-900 text-slate-100 rounded-lg p-2 font-mono text-[10px] space-y-0.5 overflow-x-auto">
                        ${paramEntries.map(([pk, pv]) => `<div><span class="text-sky-300">${escapeHtml(pk)}:</span> <span class="text-emerald-300 select-all">${escapeHtml(typeof pv === 'object' ? JSON.stringify(pv) : pv)}</span></div>`).join('')}
                      </div>
                    </div>

                    <div class="space-y-1">
                      <div class="flex items-center justify-between text-[10px]">
                        <span class="font-extrabold uppercase tracking-wider text-slate-600"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Connector Entities / DataStores (${escapeHtml(h.entitiesCount)}):</span>
                        ${linkedAppsNames.length > 0 ? `<span class="text-[9px] text-indigo-700 font-bold">Mounted on: ${escapeHtml(linkedAppsNames.join(', '))}</span>` : `<span class="text-[9px] text-slate-400">Not linked to an active Engine</span>`}
                      </div>
                      <div class="flex flex-wrap gap-1 max-h-28 overflow-y-auto">
                        ${(h.entities || []).map(ent => `
                          <span class="px-2 py-0.5 rounded bg-white border ${ent.queriesCount > 0 ? 'border-emerald-300 text-emerald-900 font-bold' : 'border-slate-200 text-slate-700'} text-[10px] mono inline-flex items-center gap-1" title="DataStore ID: ${escapeHtml(ent.dataStoreId)} · Content: ${escapeHtml(ent.contentConfig)}">
                            <b>${escapeHtml(ent.entityName)}</b>
                            ${ent.queriesCount > 0 ? `<span class="text-emerald-700">(${fmtNum(ent.queriesCount)} q)</span>` : ''}
                          </span>
                        `).join('')}
                      </div>
                    </div>
                  </div>

                  <div class="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2 text-[10px]">
                    <a href="${escapeHtml(h.consoleUrl)}" target="_blank" rel="noopener" class="font-bold text-[#0F2A4A] hover:underline"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Open DataStores in GCP Console ↗</a>
                    <button type="button" data-jt-click="openGeminiInspectorModal('CONNECTOR', ${jsArg(h.projectId)}, ${jsArg(h.hubId)}, ${jsArg(h.location || 'eu')})" class="text-indigo-700 hover:underline font-extrabold cursor-pointer"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> dataConnector v1alpha Probe →</button>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    function _renderAgentspaceAuditPanelHtml(teleApps, teleDataStores, geAppsEnriched, geAgentsList, activeTeleAppsCount, activeDsCount, unusedDsCount) {
      if ((!teleApps || teleApps.length === 0) && (!teleDataStores || teleDataStores.length === 0)) return '';
      return `
        <div class="jt-dash-card bg-white rounded-xl border border-indigo-200 shadow-2xs p-4 space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2.5">
            <div class="flex items-center gap-2">
              <h4 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> App Traffic Telemetry &amp; Full DataStores Matrix (${teleDataStores.length})</h4>
              <span class="jt-badge jt-badge--purple px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-800 border border-indigo-200 text-[10px] font-extrabold mono">${escapeHtml(activeTeleAppsCount)}/${teleApps.length} Apps Active · ${escapeHtml(activeDsCount)}/${teleDataStores.length} DataStores Active</span>
            </div>
            <div class="text-[11px] text-slate-500 mono">
              Unused DataStores (0 Queries): <b class="${unusedDsCount > 0 ? 'text-amber-700' : 'text-emerald-700'}">${escapeHtml(unusedDsCount)}</b>
            </div>
          </div>

          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div class="jt-table-panel border border-slate-200 rounded-xl overflow-hidden flex flex-col">
              <div class="px-3 py-2 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
                <span class="text-[11px] font-extrabold uppercase tracking-wider text-slate-700"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Agentspace Apps (${escapeHtml(activeTeleAppsCount)}/${teleApps.length} Active)</span>
                <span class="text-[10px] font-bold text-emerald-700 mono">Total Queries: ${fmtNum(teleApps.reduce((acc, x) => acc + (x.queries || x.queriesCount || 0), 0))}</span>
              </div>
              <div class="overflow-x-auto overflow-y-auto" style="max-height: 280px;">
                <table class="jt-table w-full text-left border-collapse text-xs">
                  <thead class="sticky top-0 bg-slate-50/95 border-b border-slate-200 text-[10px] font-bold uppercase text-slate-500">
                    <tr>
                      <th class="py-2 px-2.5">App Name / Engine ID</th>
                      <th class="py-2 px-2">Region</th>
                      <th class="py-2 px-2">Model</th>
                      <th class="py-2 px-2 text-right">DS</th>
                      <th class="py-2 px-2 text-right">Agents</th>
                      <th class="py-2 px-2 text-right">Users/Owners</th>
                      <th class="py-2 px-2 text-right">Query Log</th>
                      <th class="py-2 px-2.5 text-right">Status</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-slate-100 mono text-[11px]">
                    ${teleApps.map(a => {
                      const qCnt = a.queries ?? a.queriesCount ?? 0;
                      const enrApp = geAppsEnriched.find(ga => ga.engineId === a.engineId || ga.resourceId === a.engineId) || {};
                      const agCnt = a.agentsCount ?? enrApp.agentsCount ?? geAgentsList.filter(ag => ag.engineId === a.engineId).length;
                      const ownCnt = a.agentOwnersCount ?? enrApp.agentOwnersCount ?? 0;
                      const usrCnt = a.activeUsersCount || enrApp.totalDetectedPrincipalsCount || ownCnt || 0;
                      const licState = a.licenseState || enrApp.licenseState || (a.location === 'global' ? 'EXPIRED' : 'ACTIVE');
                      const obsOn = Boolean(a.observabilityEnabled ?? enrApp.observabilityEnabled ?? (qCnt > 0));
                      const isAct = qCnt > 0 || agCnt > 2 || ownCnt > 0;
                      let stBadgeHtml = `<span class="jt-badge jt-badge--amber px-1.5 py-0.5 rounded text-[9px] font-extrabold bg-amber-50 text-amber-800 border border-amber-200">ZERO TRAFFIC</span>`;
                      if (licState === 'EXPIRED') {
                        stBadgeHtml = `<span class="jt-badge jt-badge--red px-1.5 py-0.5 rounded text-[9px] font-extrabold bg-rose-50 text-rose-800 border border-rose-200" title="Free Trial license expired in region ${escapeHtml(a.location)}">TRIAL EXPIRED</span>`;
                      } else if (qCnt > 0) {
                        stBadgeHtml = `<span class="jt-badge jt-badge--green px-1.5 py-0.5 rounded text-[9px] font-extrabold bg-emerald-50 text-emerald-700 border border-emerald-200">ACTIVE (LOG ON)</span>`;
                      } else if (isAct) {
                        stBadgeHtml = `<span class="jt-badge jt-badge--blue px-1.5 py-0.5 rounded text-[9px] font-extrabold bg-blue-50 text-blue-800 border border-blue-200" title="App with ${escapeHtml(agCnt)} agents and ${escapeHtml(ownCnt)} IAM owners, but observabilityEnabled=false">ACTIVE (LOG OFF)</span>`;
                      }
                      return `
                        <tr class="hover:bg-slate-50 cursor-pointer" data-jt-click="openGeminiInspectorModal('ENGINE', ${jsArg(a.projectId || 'default-project')}, ${jsArg(a.engineId)}, ${jsArg(a.location || 'eu')})">
                          <td class="py-2 px-2.5">
                            <div class="font-bold text-[#0F2A4A] font-sans hover:underline">${escapeHtml(a.displayName || a.engineId)}</div>
                            <div class="text-[9px] text-slate-400">${escapeHtml(a.engineId)}${escapeHtml(a.cid ? ` · CID:${a.cid}` : '')}</div>
                          </td>
                          <td class="py-2 px-2 text-slate-600">${escapeHtml(a.location || 'eu')}</td>
                          <td class="py-2 px-2 text-indigo-700 font-bold">${escapeHtml(a.defaultModel || 'gemini-2.5-pro')}</td>
                          <td class="py-2 px-2 text-right font-bold text-slate-700">${escapeHtml(a.linkedDataStoresCount ?? 0)}</td>
                          <td class="py-2 px-2 text-right font-extrabold text-purple-800">${fmtNum(agCnt)}</td>
                          <td class="py-2 px-2 text-right text-slate-700" title="${escapeHtml(a.activeUsersCount || 0)} query users · ${escapeHtml(ownCnt)} IAM owners">${fmtNum(usrCnt)}</td>
                          <td class="py-2 px-2 text-right font-extrabold text-slate-900">${obsOn ? fmtNum(qCnt) : `<span class="text-slate-400" title="observabilityEnabled: false">0 (OFF)</span>`}</td>
                          <td class="py-2 px-2.5 text-right">
                            ${stBadgeHtml}
                          </td>
                        </tr>
                      `;
                    }).join('')}
                  </tbody>
                </table>
              </div>
            </div>

            <div class="jt-table-panel border border-slate-200 rounded-xl overflow-hidden flex flex-col">
              <div class="px-3 py-2 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-1.5">
                <span class="text-[11px] font-extrabold uppercase tracking-wider text-slate-700"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Individual DataStores (${escapeHtml(activeDsCount)} Active / ${escapeHtml(unusedDsCount)} Unused)</span>
                <div class="inline-flex items-center gap-1 text-[10px] font-bold">
                  <button type="button" id="ds-filter-btn-ALL" data-jt-click="filterAgentspaceDataStores('ALL')" class="px-2 py-0.5 rounded bg-[#0F2A4A] text-white cursor-pointer transition">All (${teleDataStores.length})</button>
                  <button type="button" id="ds-filter-btn-ACTIVE" data-jt-click="filterAgentspaceDataStores('ACTIVE')" class="px-2 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 hover:bg-emerald-100 cursor-pointer transition">Active (${escapeHtml(activeDsCount)})</button>
                  <button type="button" id="ds-filter-btn-UNUSED" data-jt-click="filterAgentspaceDataStores('UNUSED')" class="px-2 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200 hover:bg-amber-100 cursor-pointer transition">Unused 0 Queries (${escapeHtml(unusedDsCount)})</button>
                </div>
              </div>
              <div class="overflow-x-auto overflow-y-auto" style="max-height: 280px;">
                <table class="jt-table w-full text-left border-collapse text-xs">
                  <thead class="sticky top-0 bg-slate-50/95 border-b border-slate-200 text-[10px] font-bold uppercase text-slate-500">
                    <tr>
                      <th class="py-2 px-2.5">DataStore Name / ID</th>
                      <th class="py-2 px-2">Connector</th>
                      <th class="py-2 px-2 text-right">Users</th>
                      <th class="py-2 px-2 text-right">Query</th>
                      <th class="py-2 px-2.5 text-right">Status</th>
                    </tr>
                  </thead>
                  <tbody id="agentspace-datastores-audit-tbody" class="divide-y divide-slate-100 mono text-[11px]">
                    ${teleDataStores.map(ds => {
                      const qCnt = ds.queries ?? ds.queriesCount ?? 0;
                      const isAct = ds.status === 'ACTIVE' || qCnt > 0;
                      return `
                        <tr class="hover:bg-slate-50 ds-audit-row cursor-pointer" data-ds-status="${isAct ? 'ACTIVE' : 'UNUSED'}" data-jt-click="openGeminiInspectorModal('DATASTORE', ${jsArg(ds.projectId || 'default-project')}, ${jsArg(ds.dataStoreId)}, ${jsArg(ds.location || 'eu')})">
                          <td class="py-1.5 px-2.5">
                            <div class="font-bold text-slate-800 font-sans truncate max-w-[210px] hover:underline" title="${escapeHtml(ds.displayName || ds.dataStoreId)}">${escapeHtml(ds.displayName || ds.dataStoreId)}</div>
                            <div class="text-[9px] text-slate-400 truncate max-w-[210px]" title="${escapeHtml(ds.dataStoreId)}">${escapeHtml(ds.dataStoreId)}</div>
                          </td>
                          <td class="py-1.5 px-2">
                            <span class="jt-chip jt-chip--gray px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 text-[9px] font-bold">${escapeHtml(ds.connectorType || 'FIRST_PARTY')}</span>
                          </td>
                          <td class="py-1.5 px-2 text-right text-slate-700">${fmtNum(ds.activeUsersCount || 0)}</td>
                          <td class="py-1.5 px-2 text-right font-extrabold ${isAct ? 'text-emerald-700' : 'text-slate-400'}">${fmtNum(qCnt)}</td>
                          <td class="py-1.5 px-2.5 text-right">
                            <span class="jt-badge px-1.5 py-0.5 rounded text-[9px] font-extrabold ${isAct ? 'jt-badge--green bg-emerald-50 text-emerald-700 border border-emerald-200' : 'jt-badge--amber bg-amber-50 text-amber-800 border border-amber-200'}">
                              ${isAct ? 'ACTIVE' : '0 QUERIES'}
                            </span>
                          </td>
                        </tr>
                      `;
                    }).join('')}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function _renderGeAgentsSectionHtml(geAgentsList, geAgentCreators, geDialogflowAgents, geReasoningEngines, activeReList, enterpriseApps, geRootRuntimeUsers) {
      return `
        <div class="jt-dash-card bg-white rounded-xl border border-purple-200 shadow-2xs p-4 space-y-4">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <h4 class="text-xs font-extrabold uppercase tracking-wider text-purple-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Configured Agents Catalog (${geAgentsList.length}), IAM Owners (${geAgentCreators.length}), Dialogflow CX &amp; Reasoning Engines (ADK)</h4>
                <span class="jt-badge jt-badge--purple px-2 py-0.5 rounded-full bg-purple-50 text-purple-800 border border-purple-200 text-[10px] font-extrabold mono">${geAgentsList.length} Gemini Enterprise Agents · ${geAgentCreators.length} Owner/Builder · ${geDialogflowAgents.length} Dialogflow CX · ${activeReList.length} Active ADK</span>
              </div>
              <p class="text-[11px] text-slate-500 mt-0.5">Full discovery from API <code class="mono">assistants/default_assistant/agents</code> + <code class="mono">:getIamPolicy</code> (<code class="mono">roles/discoveryengine.agentOwner</code>) + Cloud Audit Logs (<code class="mono">CreateAgent</code>, <code class="mono">DeployLowCodeAgent</code>, <code class="mono">RequestAgentReview</code>).</p>
            </div>
            <span class="jt-chip jt-chip--gray px-2.5 py-1 rounded-full bg-slate-100 text-slate-700 text-[10px] font-bold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> ${escapeHtml(geRootRuntimeUsers)} Active Users on Root Agent Orchestrator</span>
          </div>

          ${geAgentsList.length > 0 ? `
            <div class="space-y-2">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="text-[11px] font-extrabold uppercase tracking-wider text-purple-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> 3A. Full Catalog of Configured Agents per Gemini Enterprise App (${geAgentsList.length})</div>
                <div class="flex flex-wrap items-center gap-1">
                  <button type="button" data-ge-agent-filter-btn="ALL" data-jt-click="filterGeCustomAgents('ALL')" class="px-2.5 py-1 rounded-lg bg-[#0F2A4A] text-white text-[10px] font-bold cursor-pointer transition">All Apps (${geAgentsList.length})</button>
                  ${enterpriseApps.map(ea => {
                    const eId = ea.engineId || ea.resourceId || '';
                    const cnt = geAgentsList.filter(ag => ag.engineId === eId).length;
                    return `<button type="button" data-ge-agent-filter-btn="${escapeHtml(eId)}" data-jt-click="filterGeCustomAgents(${jsArg(eId)})" class="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200 text-[10px] font-bold cursor-pointer transition">${escapeHtml(ea.displayName)} (${cnt})</button>`;
                  }).join('')}
                </div>
              </div>
              <div class="jt-table-panel overflow-x-auto overflow-y-auto border border-slate-200 rounded-xl" style="max-height: 340px;">
                <table class="jt-table w-full text-left border-collapse text-xs">
                  <thead class="sticky top-0 bg-slate-50 border-b border-slate-200 text-[10px] font-bold uppercase text-slate-500">
                    <tr>
                      <th class="py-2 px-3">Agent Name &amp; Description / Instructions</th>
                      <th class="py-2 px-3">App / Engine</th>
                      <th class="py-2 px-3">IAM Owner / Groups</th>
                      <th class="py-2 px-3">LLM Model &amp; Tools</th>
                      <th class="py-2 px-3 text-right">Status &amp; Update</th>
                    </tr>
                  </thead>
                  <tbody id="ge-custom-agents-tbody" class="divide-y divide-slate-100 text-[11px]">
                    ${geAgentsList.map(ag => {
                      const ownEmail = ag.creatorEmail || ((ag.owners || [])[0]) || '';
                      const grpList = ag.iamGroups || [];
                      return `
                        <tr class="hover:bg-slate-50" data-agent-engine="${escapeHtml(ag.engineId || '')}">
                          <td class="py-2 px-3 max-w-md">
                            <div class="font-extrabold text-purple-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> ${escapeHtml(ag.displayName || ag.agentId)} <span class="text-[9px] font-normal text-slate-400 mono">#${escapeHtml(ag.agentId)}</span></div>
                            ${ag.description ? `<div class="text-[10px] text-slate-600 truncate max-w-md" title="${escapeHtml(ag.description)}">${escapeHtml(ag.description)}</div>` : ''}
                            ${ag.instructionPreview ? `<div class="text-[9px] text-slate-400 italic truncate max-w-md" title="${escapeHtml(ag.instructionPreview)}">Prompt: ${escapeHtml(ag.instructionPreview)}</div>` : ''}
                          </td>
                          <td class="py-2 px-3">
                            <button type="button" data-jt-click="openGeminiInspectorModal('ENGINE', ${jsArg(ag.projectId || 'default-project')}, ${jsArg(ag.engineId)}, ${jsArg(ag.location || 'eu')})" class="font-bold text-[#0F2A4A] hover:underline text-left cursor-pointer">
                              <svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> ${escapeHtml(ag.engineName || ag.engineId)}
                            </button>
                            <div class="text-[9px] text-slate-400 mono">${escapeHtml(ag.location || 'eu')}</div>
                          </td>
                          <td class="py-2 px-3">
                            ${ownEmail ? `<div class="font-bold text-slate-900">${renderUserEmailClickable(ownEmail)}</div>` : `<span class="text-[10px] text-slate-400">Built-in Google / System</span>`}
                            ${grpList.length > 0 ? `<div class="flex flex-wrap gap-1 mt-0.5">${grpList.map(g => `<span class="jt-chip jt-chip--purple px-1 py-0.2 rounded bg-indigo-50 text-indigo-800 border border-indigo-200 text-[9px] mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> ${escapeHtml(g)}</span>`).join('')}</div>` : ''}
                          </td>
                          <td class="py-2 px-3">
                            <span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-800 border border-indigo-200 text-[10px] font-bold mono">${escapeHtml(ag.llmModel || 'Default Engine')}</span>
                            ${(ag.tools || []).length > 0 ? `<div class="text-[9px] text-slate-500 mono mt-0.5"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> ${escapeHtml((ag.tools || []).slice(0, 3).join(', '))}</div>` : ''}
                          </td>
                          <td class="py-2 px-3 text-right whitespace-nowrap mono">
                            <span class="jt-badge jt-badge--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 text-[9px] font-extrabold">${escapeHtml(ag.state || 'ENABLED')}</span>
                            <div class="text-[9px] text-slate-400 mt-0.5">${escapeHtml((ag.updateTime || ag.createTime || '').slice(0, 10) || '—')}</div>
                          </td>
                        </tr>
                      `;
                    }).join('')}
                  </tbody>
                </table>
              </div>
            </div>
          ` : ''}

          <div class="space-y-2">
            <div class="text-[11px] font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> 3A-bis. Agent IAM Owners (<code class="mono">agentOwner</code>) &amp; Lifecycle Audit Operations (${geAgentCreators.length})</div>
            <div class="jt-table-panel overflow-x-auto overflow-y-auto border border-slate-200 rounded-xl" style="max-height: 320px;">
              <table class="jt-table w-full text-left border-collapse text-xs">
                <thead class="sticky top-0 bg-slate-50 border-b border-slate-200 text-[10px] font-bold uppercase text-slate-500">
                  <tr>
                    <th class="py-2.5 px-3">IAM Owner / Creator</th>
                    <th class="py-2.5 px-3">Owned Agents &amp; Status</th>
                    <th class="py-2.5 px-3">IAM Roles &amp; Audit Operations</th>
                    <th class="py-2.5 px-3">Target App / Engine</th>
                    <th class="py-2.5 px-3">Models Used</th>
                    <th class="py-2.5 px-3 text-right">Calls / Queries</th>
                    <th class="py-2.5 px-3 text-right">Last Activity</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 text-[11px]">
                  ${geAgentCreators.length > 0 ? geAgentCreators.map(cr => {
                    const badgeColors = {
                      OWNER: 'bg-purple-100 text-purple-900 border-purple-300',
                      CREATE: 'bg-emerald-100 text-emerald-900 border-emerald-300',
                      DEPLOY: 'bg-indigo-100 text-indigo-900 border-indigo-300',
                      UPDATE: 'bg-blue-100 text-blue-900 border-blue-300',
                      REVIEW: 'bg-amber-100 text-amber-900 border-amber-300',
                      IAM_AUDIT: 'bg-purple-100 text-purple-900 border-purple-300',
                      DELETE: 'bg-rose-100 text-rose-900 border-rose-300',
                      RUNTIME: 'bg-slate-100 text-slate-700 border-slate-300'
                    };
                    const isEmail = (cr.userEmail || '').includes('@');
                    const ownedList = cr.ownedAgents || [];
                    return `
                      <tr class="hover:bg-slate-50">
                        <td class="py-2 px-3 font-bold text-slate-900">
                          ${isEmail ? renderUserEmailClickable(cr.userEmail) : `<span class="mono text-indigo-950">${escapeHtml(cr.userEmail)}</span>`}
                          <div class="text-[9px] text-slate-400 mono">${escapeHtml(cr.projectId)}${escapeHtml(cr.credentialId ? ` · ${cr.credentialId}` : '')}</div>
                        </td>
                        <td class="py-2 px-3 max-w-xs">
                          <div class="font-bold text-purple-950">${escapeHtml(cr.categoryLabel || 'Custom Agent')}</div>
                          ${ownedList.length > 0 ? `
                            <div class="flex flex-wrap gap-1 mt-0.5">
                              ${ownedList.slice(0, 4).map(oa => `<span class="jt-chip jt-chip--purple px-1.5 py-0.2 rounded bg-purple-50 text-purple-900 border border-purple-200 text-[9px] font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> ${escapeHtml(oa.displayName)}</span>`).join('')}
                              ${ownedList.length > 4 ? `<span class="px-1 py-0.2 rounded bg-slate-100 text-slate-600 text-[9px] mono">+${ownedList.length - 4}</span>` : ''}
                            </div>
                          ` : `<span class="jt-badge jt-badge--purple px-1.5 py-0.5 rounded text-[9px] font-extrabold bg-purple-50 text-purple-800 border border-purple-200 mono">${escapeHtml(cr.status)}</span>`}
                        </td>
                        <td class="py-2 px-3">
                          <div class="flex flex-wrap gap-1">
                            ${(cr.actions || []).map(act => `
                              <span class="jt-chip px-1.5 py-0.5 rounded border text-[9px] font-extrabold mono ${escapeHtml(badgeColors[act.badge] || 'bg-slate-100 text-slate-700 border-slate-200')}" title="${escapeHtml(act.label)}">
                                ${escapeHtml(act.badge)}: ${escapeHtml(act.method)}
                              </span>
                            `).join('')}
                          </div>
                        </td>
                        <td class="py-2 px-3">
                          <button type="button" data-jt-click="openGeminiInspectorModal('ENGINE', ${jsArg(cr.projectId)}, ${jsArg(cr.primaryEngineId)}, 'eu')" class="font-bold text-[#0F2A4A] hover:underline text-left cursor-pointer">
                            <svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> ${escapeHtml(cr.primaryEngineName || cr.primaryEngineId)}
                          </button>
                          <div class="text-[9px] text-slate-400 mono">${escapeHtml(cr.primaryEngineId)}</div>
                        </td>
                        <td class="py-2 px-3 mono text-[10px] text-indigo-800 font-semibold">${escapeHtml((cr.modelsUsed || []).slice(0, 3).join(', ') || 'gemini-2.5-pro (Engine)')}</td>
                        <td class="py-2 px-3 text-right mono font-bold text-slate-800">${fmtNum(cr.requests || 0)} <span class="text-[9px] text-slate-400 font-normal">(${fmtNum(cr.queriesCount || 0)} q)</span></td>
                        <td class="py-2 px-3 text-right mono text-slate-500">${escapeHtml((cr.lastSeen || '').slice(0, 10) || '—')}</td>
                      </tr>
                    `;
                  }).join('') : `<tr><td colspan="7" class="py-6 text-center text-slate-400">No agent creation events detected.</td></tr>`}
                </tbody>
              </table>
            </div>
          </div>

          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 pt-1">
            <div class="border border-slate-200 rounded-xl overflow-hidden">
              <div class="px-3.5 py-2 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
                <span class="text-[11px] font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> 3B. Dialogflow CX Conversational Agents (${geDialogflowAgents.length})</span>
                <span class="text-[9px] font-bold text-slate-500 mono">dialogflow.googleapis.com</span>
              </div>
              <div class="divide-y divide-slate-100 text-xs">
                ${geDialogflowAgents.length > 0 ? geDialogflowAgents.map(df => `
                  <div class="p-3 hover:bg-slate-50 flex items-center justify-between gap-2">
                    <div>
                      <div class="font-extrabold text-slate-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> ${escapeHtml(df.displayName)} <span class="jt-chip jt-chip--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 text-[9px] mono ml-1">${escapeHtml(df.llmModel || 'gemini-2.5-flash')}</span></div>
                      <div class="text-[10px] text-slate-500 mono mt-0.5">Agent ID: <b class="select-all">${escapeHtml(df.agentId)}</b> · Project: <b>${escapeHtml(df.projectId)}</b> (${escapeHtml(df.location)})</div>
                      <div class="text-[10px] text-slate-500 mt-0.5">${escapeHtml(df.details || '')}</div>
                    </div>
                    <a href="${escapeHtml(df.consoleUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1.5 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[10px] whitespace-nowrap shrink-0"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Open Agent Builder ↗</a>
                  </div>
                `).join('') : `<div class="p-4 text-center text-slate-400 text-xs">No Dialogflow CX agents found.</div>`}
              </div>
            </div>

            <div class="border border-slate-200 rounded-xl overflow-hidden">
              <div class="px-3.5 py-2 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
                <span class="text-[11px] font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> 3C. Vertex AI Reasoning Engines / ADK (${activeReList.length} Active · ${geReasoningEngines.length - activeReList.length} Zombie)</span>
                <span class="text-[9px] font-bold text-slate-500 mono">aiplatform.googleapis.com</span>
              </div>
              <div class="divide-y divide-slate-100 text-xs max-h-56 overflow-y-auto">
                ${geReasoningEngines.length > 0 ? geReasoningEngines.slice(0, 10).map(re => `
                  <div class="p-2.5 hover:bg-slate-50 flex items-center justify-between gap-2">
                    <div>
                      <div class="font-bold text-slate-900 flex items-center gap-1.5">
                        <span>${re.isZombieVersion ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg>' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg>'} ${escapeHtml(re.displayName)}</span>
                        <span class="jt-badge px-1.5 py-0.5 rounded text-[9px] font-extrabold mono ${re.isZombieVersion ? 'jt-badge--purple bg-purple-50 text-purple-800 border border-purple-200' : 'jt-badge--green bg-emerald-50 text-emerald-800 border border-emerald-200'}">${re.isZombieVersion ? 'ZOMBIE BUILD' : 'ACTIVE LATEST'}</span>
                      </div>
                      <div class="text-[10px] text-slate-500 mono">ID: ${escapeHtml(re.resourceId)} · ${escapeHtml(re.projectId)} (${escapeHtml(re.location)}) · Created: ${escapeHtml((re.createTime || '').slice(0, 10))}</div>
                    </div>
                    <a href="${escapeHtml(re.consoleUrl)}" target="_blank" rel="noopener" class="px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold text-[10px] whitespace-nowrap shrink-0">Console ↗</a>
                  </div>
                `).join('') : `<div class="p-4 text-center text-slate-400 text-xs">No ADK Reasoning Engines found.</div>`}
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function _renderGeSecuritySectionHtml(geOauthEvents) {
      return `
        <div class="jt-dash-card bg-white rounded-xl border border-amber-200 shadow-2xs p-4 space-y-4">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2.5">
            <div>
              <h4 class="text-xs font-extrabold uppercase tracking-wider text-amber-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> Keys, Connector OAuth Refresh/Access Tokens &amp; Direct Inspection CLI Commands</h4>
              <p class="text-[11px] text-slate-500 mt-0.5">Tracking of credentials that authenticate third-party connectors (<code class="mono">AcquireAndStoreRefreshToken</code>, <code class="mono">AcquireAccessToken</code>, <code class="mono">CheckRefreshToken</code>) and ready-to-use <code class="mono">curl</code> commands.</p>
            </div>
            <span class="jt-badge jt-badge--amber px-2.5 py-1 rounded-full bg-amber-50 text-amber-900 border border-amber-200 text-[10px] font-extrabold mono">${geOauthEvents.length} OAuth / API Key Connector Principals</span>
          </div>

          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div class="space-y-2">
              <div class="text-[10px] font-extrabold uppercase tracking-wider text-slate-600"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Credentials &amp; Principals with Connector Token Operations:</div>
              <div class="divide-y divide-slate-100 border border-slate-200 rounded-xl overflow-hidden">
                ${geOauthEvents.length > 0 ? geOauthEvents.map(oe => `
                  <div class="p-3 bg-white hover:bg-slate-50 space-y-1.5">
                    <div class="flex items-center justify-between gap-2">
                      <span class="font-extrabold text-slate-900 mono text-xs">${escapeHtml(oe.principalEmail)}</span>
                      <span class="jt-badge jt-badge--amber px-2 py-0.5 rounded bg-amber-50 text-amber-900 border border-amber-200 text-[10px] font-extrabold mono">${escapeHtml(oe.principalType)} · ${fmtNum(oe.requests || 0)} calls</span>
                    </div>
                    ${oe.credentialId ? `<div class="text-[10px] text-slate-500 mono">Credential ID: <b class="select-all">${escapeHtml(oe.credentialId)}</b> · Project: <b>${escapeHtml(oe.projectId)}</b></div>` : `<div class="text-[10px] text-slate-500 mono">Project: <b>${escapeHtml(oe.projectId)}</b> · Last activity: ${escapeHtml(oe.lastSeen || '—')}</div>`}
                    <div class="flex flex-wrap gap-1 pt-0.5">
                      ${(oe.methods || []).map(m => `<span class="jt-chip jt-chip--gray px-1.5 py-0.5 rounded bg-slate-100 text-slate-800 border border-slate-200 text-[9px] font-bold mono" title="${escapeHtml(m.description)}"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> ${escapeHtml(m.method)}</span>`).join('')}
                    </div>
                  </div>
                `).join('') : `<div class="p-4 text-center text-slate-400 text-xs">No Connector OAuth events detected in the period.</div>`}
              </div>
            </div>

            <div class="space-y-2">
              <div class="text-[10px] font-extrabold uppercase tracking-wider text-slate-600"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Read-Only CLI Commands to Inspect Connectors (Confluence / DocuSign) &amp; Agents:</div>
              <div class="bg-slate-900 text-slate-100 rounded-xl p-3 font-mono text-[10px] space-y-2 overflow-x-auto">
                <div>
                  <div class="text-amber-300 font-bold"># 1. Inspect Confluence Connector (DataConnector, URL, Auth &amp; Entities)</div>
                  <div class="text-emerald-300 select-all">curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" "https://eu-discoveryengine.googleapis.com/v1alpha/projects/YOUR_PROJECT_ID/locations/eu/collections/confluence-wiki-v2_001/dataConnector"</div>
                </div>
                <div>
                  <div class="text-amber-300 font-bold"># 2. Inspect DocuSign Connector (DataConnector &amp; OAuth Parameters)</div>
                  <div class="text-emerald-300 select-all">curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" "https://eu-discoveryengine.googleapis.com/v1alpha/projects/YOUR_PROJECT_ID/locations/eu/collections/docusign_001/dataConnector"</div>
                </div>
                <div>
                  <div class="text-amber-300 font-bold"># 3. List the Agents registered in the Gemini Enterprise Assistant</div>
                  <div class="text-emerald-300 select-all">curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" "https://eu-discoveryengine.googleapis.com/v1alpha/projects/YOUR_PROJECT_ID/locations/eu/collections/default_collection/engines/gemini-enterprise-engine_001/assistants/default_assistant/agents"</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function _renderModelArmorAndDeployedResources(maContainer, resTbody, featTbody, visibleProjs, allAppsLen, teleAppsLen, q) {
      const maProjects = visibleProjs.filter(p => p.modelArmorEnabled || (p.modelArmor && p.modelArmor.enabled));
      if (maProjects.length === 0) {
        setSafeHtml(maContainer, `<div class="col-span-2 bg-white rounded-xl border border-slate-200 p-6 text-center text-slate-400">No project in the current selection has Model Armor enabled.</div>`);
      } else {
        setSafeHtml(maContainer, maProjects.map(p => {
          const ma = p.modelArmor || {};
          const fl = ma.floorSetting || {};
          const flFilters = fl.filters || {};
          const templates = ma.templates || [];
          const isDenied = ma.status === 'PERMISSION_DENIED';
          const isConfigured = ma.status === 'CONFIGURED_ACTIVE';

          if (isDenied) {
            return `
              <div class="jt-dash-card bg-white rounded-xl p-5 border border-rose-200 space-y-2 shadow-2xs">
                <div class="flex items-center justify-between">
                  <h4 class="text-sm font-bold text-slate-900">${escapeHtml(p.name)} (<span class="mono text-slate-500">${escapeHtml(p.projectId)}</span>)</h4>
                  <span class="jt-badge jt-badge--red px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-rose-50 text-rose-700 border border-rose-200"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> Permission Denied (403)</span>
                </div>
                <p class="text-xs text-rose-700">The Model Armor API is active (${fmtNum(ma.totalRequests || 0)} calls), but the role <code class="mono">roles/modelarmor.viewer</code> is missing to read Floor Settings and Templates.</p>
              </div>
            `;
          }

          const tel = ma.threatTelemetry || {};
          const tplNames = templates.map(t => `<span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-800 border border-indigo-200 text-[10px] mono font-semibold">${escapeHtml(t.templateId || t.name || 'template')} (${escapeHtml(t.location || 'global')})</span>`).join(' ');
          return `
            <div class="jt-dash-card bg-white rounded-xl p-5 border border-slate-200 space-y-3 shadow-2xs">
              <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                <div>
                  <h4 class="text-sm font-bold text-slate-900">${escapeHtml(p.name)}</h4>
                  <div class="text-[11px] text-slate-400 mono">${escapeHtml(p.projectId)}</div>
                </div>
                <span class="jt-badge px-2.5 py-1 rounded-full text-[11px] font-bold ${isConfigured ? 'jt-badge--green bg-emerald-50 text-emerald-700 border border-emerald-200' : 'jt-badge--blue bg-blue-50 text-blue-700 border border-blue-200'}">
                  ${escapeHtml(ma.statusLabel || 'API Enabled')}
                </span>
              </div>
              <div class="grid grid-cols-4 gap-2 text-xs">
                <div class="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
                  <div class="text-[10px] text-slate-400">Enforcement</div>
                  <div class="font-bold text-slate-800 mt-0.5">${fl.enforcementEnabled ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Active' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg> Disabled'}</div>
                </div>
                <div class="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
                  <div class="text-[10px] text-slate-400">Prompt Injection</div>
                  <div class="font-bold text-slate-800 mono mt-0.5">${escapeHtml(flFilters.promptInjectionAndJailbreak || 'OFF')}</div>
                </div>
                <div class="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
                  <div class="text-[10px] text-slate-400">Cataloged Templates</div>
                  <div class="font-bold text-slate-800 mono mt-0.5">${templates.length}</div>
                </div>
                <div class="p-2.5 rounded-lg ${(tel.flaggedCount || 0) > 0 ? 'bg-rose-50 border-rose-200' : 'bg-slate-50 border-slate-100'} border">
                  <div class="text-[10px] text-slate-400">Threats Detected</div>
                  <div class="font-bold ${(tel.flaggedCount || 0) > 0 ? 'text-rose-700' : 'text-slate-800'} mono mt-0.5">${fmtNum(tel.flaggedCount || 0)} (${fmtNum(tel.blockedCount || 0)} blocked)</div>
                </div>
              </div>
              ${tplNames ? `<div class="pt-1 flex flex-wrap items-center gap-1 text-[10px] text-slate-500"><b>Templates:</b> ${tplNames}</div>` : ''}
            </div>
          `;
        }).join(''));
      }

      const rawResources = [];
      visibleProjs.forEach(p => {
        (p.deployedAiResources || []).forEach(r => {
          if (q && !`${r.displayName} ${r.typeLabel} ${p.projectId} ${r.details || ''} ${r.user || r.ownerEmail || ''}`.toLowerCase().includes(q)) return;
          rawResources.push({ ...r, projectId: p.projectId });
        });
      });
      const allResources = groupRepeatedAiResources(rawResources);

      const resHtml = allResources.length > 0
        ? allResources.map(r => {
            let defaultUrl = `https://console.cloud.google.com/vertex-ai?project=${r.projectId}`;
            if (r.resourceType === 'AGENTSPACE_APP') defaultUrl = `https://console.cloud.google.com/gen-app-builder/locations/${r.location}/engines/${r.resourceId}/configurations?project=${r.projectId}`;
            else if (r.resourceType === 'AGENTSPACE_DATASTORE') defaultUrl = `https://console.cloud.google.com/gen-app-builder/data-stores?project=${r.projectId}`;
            else if (r.resourceType === 'REASONING_ENGINE') defaultUrl = `https://console.cloud.google.com/vertex-ai/agents/agent-engines?project=${r.projectId}`;
            else if (r.resourceType === 'VERTEX_ENDPOINT') defaultUrl = `https://console.cloud.google.com/vertex-ai/online-prediction/endpoints?project=${r.projectId}`;
            else if (r.resourceType === 'VERTEX_MODEL_GARDEN' || r.resourceType === 'VERTEX_MODEL') defaultUrl = `https://console.cloud.google.com/vertex-ai/models?project=${r.projectId}`;
            else if (r.resourceType === 'DIALOGFLOW_CX_AGENT') defaultUrl = `https://conversational-agents.cloud.google.com/projects/${r.projectId}/locations/${r.location}/agents/${r.resourceId}`;

            const cUrl = r.configUrl || r.consoleUrl || defaultUrl;
            const wUrl = r.webAppUrl || '';
            const mgUrl = r.modelGardenUrl || '';
            const runCount = r._runCount || 1;
            const succCount = r._succeededCount || 0;
            const rUser = r.user || r.ownerEmail || '';

            return `
              <tr class="hover:bg-slate-50">
                <td class="py-3 px-4 font-semibold text-[#0F2A4A]">
                  <div>${escapeHtml(r.typeLabel)}</div>
                  ${runCount > 1 ? `<div class="mt-1"><span class="jt-badge jt-badge--purple px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-800 border border-indigo-200 text-[10px] font-extrabold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> ${escapeHtml(runCount)} runs (${escapeHtml(succCount)} OK)</span></div>` : ''}
                </td>
                <td class="py-3 px-4">
                  <div class="font-bold text-slate-900">${escapeHtml(r.displayName)}</div>
                  <div class="text-[10px] text-slate-400 mono">${escapeHtml(runCount > 1 ? `Last ID: ${r.resourceId || ''}` : (r.resourceId || ''))}</div>
                  ${rUser ? `<div class="mt-0.5 text-[10px] text-slate-500"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> ${renderUserEmailClickable(rUser)}</div>` : ''}
                </td>
                <td class="py-3 px-4 mono text-slate-600 font-semibold">${escapeHtml(r.projectId)}</td>
                <td class="py-3 px-4 mono text-slate-500">${escapeHtml(r.location)}</td>
                <td class="py-3 px-4 text-slate-600 max-w-md">${escapeHtml(r.details || '—')}</td>
                <td class="py-3 px-4 mono text-slate-400 whitespace-nowrap">${escapeHtml(r.updateTime ? r.updateTime.slice(0, 10) : '—')}</td>
                <td class="py-3 px-4 text-right whitespace-nowrap">
                  <div class="inline-flex items-center gap-1">
                    <a href="${escapeHtml(cUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[10px] transition whitespace-nowrap shrink-0">
                      <svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Console GCP ↗
                    </a>
                    ${wUrl ? `<a href="${escapeHtml(wUrl)}" target="_blank" rel="noopener" class="px-2 py-1 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-800 border border-indigo-200 font-bold text-[10px] transition whitespace-nowrap shrink-0"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Web App ↗</a>` : ''}
                    ${mgUrl ? `<a href="${escapeHtml(mgUrl)}" target="_blank" rel="noopener" class="px-2 py-1 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-800 border border-emerald-200 font-bold text-[10px] transition whitespace-nowrap shrink-0"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Model Garden ↗</a>` : ''}
                  </div>
                </td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="7" class="py-8 text-center text-slate-400">No custom deployed resources found.</td></tr>`;
      setSafeHtml(resTbody, resHtml);

      const allFeats = [];
      visibleProjs.forEach(p => {
        (p.vertexFeatures || []).forEach(f => {
          if (q && !`${f.name} ${f.service} ${p.projectId}`.toLowerCase().includes(q)) return;
          allFeats.push({ ...f, projectId: p.projectId });
        });
      });
      allFeats.sort((a, b) => (b.inferenceRequests - a.inferenceRequests) || (b.requests - a.requests));

      const featHtml = allFeats.length > 0
        ? allFeats.map(f => {
            const isCtrlOnly = f.isControlPlaneOnly || ((f.requests || 0) > 0 && (f.inferenceRequests || 0) === 0);
            const stBadge = (f.inferenceRequests || 0) > 0
              ? `<span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> In Use (Inference)</span>`
              : (isCtrlOnly
                  ? `<span class="jt-badge jt-badge--blue px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200" title="Discovery/configuration-only calls at $0 cost"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Control Plane Only ($0)</span>`
                  : `<span class="jt-badge jt-badge--gray px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-600">Enabled</span>`);
            return `
              <tr class="hover:bg-slate-50">
                <td class="py-3 px-4 font-bold text-slate-800">${f.icon ? escapeHtml(f.icon) : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg>`} ${escapeHtml(f.name)}</td>
                <td class="py-3 px-4 mono text-slate-600">${escapeHtml(f.projectId)}</td>
                <td class="py-3 px-4 text-slate-600">${escapeHtml(f.category)}</td>
                <td class="py-3 px-4">${stBadge}</td>
                <td class="py-3 px-4 mono text-[11px] text-slate-500">${escapeHtml((f.methods || []).slice(0, 3).join(', ') || '—')}</td>
                <td class="py-3 px-4 text-right mono font-bold ${(f.inferenceRequests || 0) > 0 ? 'text-slate-800' : 'text-slate-400'}">${fmtNum(f.inferenceRequests || 0)}</td>
                <td class="py-3 px-4 text-right mono text-slate-500">${fmtNum(f.requests || 0)}</td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="7" class="py-8 text-center text-slate-400">No services found.</td></tr>`;
      setSafeHtml(featTbody, featHtml);

      const setFeatBadge = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      setFeatBadge('subtab-badge-feat-apps', Math.max(allAppsLen, teleAppsLen));
      setFeatBadge('subtab-badge-feat-armor', maProjects.length);
      setFeatBadge('subtab-badge-feat-res', allResources.length);
      setFeatBadge('subtab-badge-feat-apis', allFeats.length);
    }

    function renderFeaturesAndModelArmorTab(agg) {
      const maContainer = document.getElementById('model-armor-cards');
      const resTbody = document.getElementById('deployed-resources-tbody');
      const featTbody = document.getElementById('vertex-features-tbody');
      const appsContainer = document.getElementById('gemini-enterprise-apps-container');
      const resFinContainer = document.getElementById('residency-and-finops-container');
      if (!maContainer || !resTbody || !featTbody) return;

      const searchEl = document.getElementById('search-input');
      const q = ((searchEl && searchEl.value) || '').toLowerCase().trim();
      const visibleProjs = (globalScanData.projects || []).filter(p => {
        if (!isProjectVisibleByToggles(p)) return false;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return false;
        return Boolean(p.aiActive || p.scanStatus === 'NO_PERMISSIONS_403' || p.isAiStudioProject);
      });

      _renderResidencyAndFinopsSection(resFinContainer, visibleProjs, agg, q);
      const inv = _collectGeInventoryFromProjects(visibleProjs, agg, q);
      const {
        allApps, teleApps, teleDataStores, geAppsEnriched, geConnectorHubs,
        geDataStoresEnriched, geAgentsList, geAgentCreators, geDialogflowAgents,
        geReasoningEngines, geOauthEvents, geRootRuntimeUsers
      } = inv;

      if (appsContainer) {
        const activeTeleAppsCount = teleApps.filter(a => a.status === 'ACTIVE' || (a.queries || a.queriesCount || 0) > 0).length;
        const activeDsCount = teleDataStores.filter(d => d.status === 'ACTIVE' || (d.queries || d.queriesCount || 0) > 0).length;
        const unusedDsCount = teleDataStores.length - activeDsCount;

        const appsSource = geAppsEnriched.length > 0 ? geAppsEnriched : allApps;
        const enterpriseApps = appsSource.filter(a => a.isGeminiEnterprise || a.cid || (a.enabledFeatures && a.enabledFeatures.length > 0) || a.modelSelector === 'ON' || a.modelSelector === 'OFF');
        const searchApps = appsSource.filter(a => !enterpriseApps.includes(a));

        const thirdPartyHubs = geConnectorHubs.filter(h => h.isThirdPartySaaS);
        const workspaceAndNlmHubs = geConnectorHubs.filter(h => !h.isThirdPartySaaS && (h.family === 'GOOGLE_WORKSPACE' || h.family === 'NOTEBOOK_LM'));
        const gcpAndOtherHubs = geConnectorHubs.filter(h => !h.isThirdPartySaaS && h.family !== 'GOOGLE_WORKSPACE' && h.family !== 'NOTEBOOK_LM');

        const activeReList = geReasoningEngines.filter(r => !r.isZombieVersion);
        const totActiveFeatures = enterpriseApps.reduce((acc, a) => acc + (a.enabledFeaturesCount || (a.enabledFeatures || []).length), 0);
        const selOnCount = enterpriseApps.filter(a => a.modelSelector === 'ON').length;
        const selOffCount = enterpriseApps.filter(a => a.modelSelector === 'OFF').length;
        const activeSubView = window._activeGeSubView || 'ALL';

        const geKpiStripHtml = _buildGeKpiStripAndNavHtml({
          enterpriseApps, searchApps, selOnCount, selOffCount, totActiveFeatures,
          geDataStoresEnriched, teleDataStores, geConnectorHubs, thirdPartyHubs,
          geAgentsList, geAgentCreators, geDialogflowAgents, activeReList,
          geRootRuntimeUsers, geOauthEvents, activeSubView
        });
        const entCardsHtml = _renderGeEnterpriseAppsCards(enterpriseApps, geAgentsList);
        const searchAppsTableHtml = _renderGeSearchAppsTable(searchApps);
        const connectorsSectionHtml = _renderGeConnectorsSectionHtml(geConnectorHubs, thirdPartyHubs, workspaceAndNlmHubs, gcpAndOtherHubs, geDataStoresEnriched);
        const agentspaceAuditPanelHtml = _renderAgentspaceAuditPanelHtml(teleApps, teleDataStores, geAppsEnriched, geAgentsList, activeTeleAppsCount, activeDsCount, unusedDsCount);
        const agentsSectionHtml = _renderGeAgentsSectionHtml(geAgentsList, geAgentCreators, geDialogflowAgents, geReasoningEngines, activeReList, enterpriseApps, geRootRuntimeUsers);
        const securitySectionHtml = _renderGeSecuritySectionHtml(geOauthEvents);

        const appsHtml = (enterpriseApps.length > 0 || searchApps.length > 0 || geConnectorHubs.length > 0 || teleApps.length > 0)
          ? `
            ${geKpiStripHtml}
            <div id="ge-subview-APPS" class="${(activeSubView === 'ALL' || activeSubView === 'APPS') ? 'space-y-4' : 'hidden space-y-4'}">
              ${entCardsHtml}
              ${searchAppsTableHtml}
            </div>
            <div id="ge-subview-CONNECTORS" class="${(activeSubView === 'ALL' || activeSubView === 'CONNECTORS') ? 'space-y-4' : 'hidden space-y-4'}">
              ${connectorsSectionHtml}
              ${agentspaceAuditPanelHtml}
            </div>
            <div id="ge-subview-AGENTS" class="${(activeSubView === 'ALL' || activeSubView === 'AGENTS') ? 'space-y-4' : 'hidden space-y-4'}">
              ${agentsSectionHtml}
            </div>
            <div id="ge-subview-SECURITY" class="${(activeSubView === 'ALL' || activeSubView === 'SECURITY') ? 'space-y-4' : 'hidden space-y-4'}">
              ${securitySectionHtml}
            </div>
          `
          : `<div class="bg-white rounded-xl border border-slate-200 p-6 text-center text-slate-400 text-xs">No Gemini Enterprise or Vertex AI Search apps found in the selected projects.</div>`;
        setSafeHtml(appsContainer, appsHtml);
      }

      _renderModelArmorAndDeployedResources(maContainer, resTbody, featTbody, visibleProjs, Math.max(allApps.length, geAppsEnriched.length), teleApps.length, q);
      renderMcpRegistryAndArmorMatrix(agg, visibleProjs, q);
      applyActiveSubTab('features');
    }

