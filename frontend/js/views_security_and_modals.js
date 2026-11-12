    const CLS_FLEX_BETWEEN = 'flex items-center justify-between';
    const CLS_FLEX_WRAP_BETWEEN = 'flex flex-wrap items-center justify-between gap-2';

    function _collectRawMcpRegistryItems(visibleProjs) {
      const rawItems = [];
      (visibleProjs || []).forEach(p => {
        (p.deployedAiResources || []).forEach(r => {
          const rType = String(r.resourceType || '');
          if (['REASONING_ENGINE', 'AGENTSPACE_APP', 'DIALOGFLOW_CX_AGENT', 'MCP_SERVER', 'AGENT_REGISTRY_ENTRY'].includes(rType)) {
            rawItems.push({
              name: r.displayName || r.resourceId || 'AI Agent',
              resourceId: r.resourceId || '',
              type: rType,
              typeLabel: r.typeLabel || rType,
              protocol: rType === 'REASONING_ENGINE' ? 'ADK / A2A Reasoning Engine' : (rType === 'AGENTSPACE_APP' ? 'Agentspace / MCP' : (rType === 'DIALOGFLOW_CX_AGENT' ? 'Dialogflow CX Agent' : 'MCP / Tool Server')),
              projectId: p.projectId,
              location: r.location || 'global',
              version: r.version || (r.updateTime ? `v-${r.updateTime.slice(0, 10)}` : 'v1'),
              modelOrRuntime: (r.enabledModels && r.enabledModels.length > 0) ? r.enabledModels.join(', ') : (r.details || 'Gemini / Vertex Runtime'),
              status: 'ACTIVE',
              statusLabel: 'Active',
              consoleUrl: r.configUrl || r.consoleUrl || `https://console.cloud.google.com/vertex-ai/agents/agent-engines?project=${p.projectId}`
            });
          }
        });
        (p.vertexFeatures || []).forEach(f => {
          const fLow = `${f.service || ''} ${f.name || ''}`.toLowerCase();
          if (fLow.includes('agentregistry') || fLow.includes('agent registry') || fLow.includes('mcp')) {
            rawItems.push({
              name: f.name || 'Cloud Agent & MCP Registry API',
              resourceId: f.service || 'cloudagentregistry.googleapis.com',
              type: 'MCP_REGISTRY_API',
              typeLabel: 'Agent/MCP Registry API',
              protocol: 'MCP / A2A Discovery',
              projectId: p.projectId,
              location: 'global',
              version: 'v1alpha / GA',
              modelOrRuntime: `${fmtNum(f.requests || 0)} API calls (${(f.methods || []).slice(0, 2).join(', ') || 'Discovery'})`,
              status: (f.requests || 0) > 0 ? 'ACTIVE' : 'ENABLED',
              statusLabel: (f.requests || 0) > 0 ? 'In Use' : 'Enabled',
              consoleUrl: `https://console.cloud.google.com/vertex-ai/agents?project=${p.projectId}`
            });
          }
        });
      });
      return rawItems;
    }

    function _mcpIsServer(it) {
      return String(it.type || '').includes('MCP') || String(it.protocol || '').includes('MCP');
    }

    function _renderMcpRegistrySection(mcpTbody, mcpKpi, agg, visibleProjs, visibleProjIds, s, q) {
      if (!mcpTbody) return;
      const reg = s.mcpAndAgentRegistry || {};
      const rawItems = (Array.isArray(reg.items) && reg.items.length > 0) ? reg.items : _collectRawMcpRegistryItems(visibleProjs);

      const filteredMcp = rawItems.filter(it => {
        if (agg.selProj !== 'ALL' && it.projectId !== agg.selProj) return false;
        if (agg.selProj === 'ALL' && visibleProjIds.size > 0 && it.projectId && !visibleProjIds.has(it.projectId)) return false;
        if (q) {
          const hay = `${it.name || ''} ${it.displayName || ''} ${it.typeLabel || ''} ${it.protocol || ''} ${it.projectId || ''} ${it.modelOrRuntime || ''}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      if (mcpKpi) {
        const isUnfilteredMcp = (agg.selProj === 'ALL' && !q);
        const totMcp = (isUnfilteredMcp && reg.mcpServersCount !== undefined)
          ? reg.mcpServersCount
          : (reg.totalMcpServers ?? filteredMcp.filter(x => _mcpIsServer(x)).length);
        const totAgents = (isUnfilteredMcp && reg.totalCount !== undefined && reg.mcpServersCount !== undefined)
          ? (reg.totalCount - reg.mcpServersCount)
          : (reg.totalAgents ?? filteredMcp.filter(x => !_mcpIsServer(x)).length);
        const apiProjs = (isUnfilteredMcp && reg.projectsCount !== undefined)
          ? reg.projectsCount
          : (reg.agentRegistryApiProjectsCount ?? new Set(filteredMcp.map(x => x.projectId)).size);
        setSafeHtml(mcpKpi, `
          <span class="jt-chip jt-chip--blue px-2 py-0.5 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-800 font-bold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Agents &amp; Engines: ${escapeHtml(totAgents)}</span>
          <span class="jt-chip jt-chip--purple px-2 py-0.5 rounded-lg bg-purple-50 border border-purple-200 text-purple-800 font-bold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> MCP Server: ${escapeHtml(totMcp)}</span>
          <span class="jt-chip jt-chip--gray px-2 py-0.5 rounded-lg bg-slate-100 border border-slate-200 text-slate-700 font-bold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Projects: ${escapeHtml(apiProjs)}</span>
        `);
      }

      const mcpBadgeEl = document.getElementById('subtab-badge-feat-mcp');
      if (mcpBadgeEl) mcpBadgeEl.textContent = filteredMcp.length;

      if (filteredMcp.length === 0) {
        setSafeHtml(mcpTbody, `<tr><td colspan="6" class="py-8 text-center text-slate-400">No agents or MCP servers match the current filters.</td></tr>`);
      } else {
        setSafeHtml(mcpTbody, filteredMcp.map(it => {
          const name = it.displayName || it.name || it.resourceId || 'Agent / MCP';
          const typeLbl = it.typeLabel || it.type || 'AGENT';
          const proto = it.protocol || it.runtime || (String(it.type || '').includes('MCP') ? 'MCP Server' : (String(it.type || '').includes('REASONING') ? 'Vertex Agent Engine' : 'A2A / Agent Registry'));
          const ver = it.version || (it.updateTime ? it.updateTime.slice(0, 10) : (it.createTime ? it.createTime.slice(0, 10) : 'v1'));
          const mod = it.modelOrRuntime || it.model || it.details || it.detail || '—';
          const isMcp = _mcpIsServer(it);
          const isActive = it.status === 'ACTIVE' || it.state === 'ACTIVE';
          const stLbl = it.statusLabel || (isActive ? 'Active' : 'Cataloged');
          const stBadge = isActive
            ? { cls: 'jt-badge--green bg-emerald-50 text-emerald-700 border-emerald-200', ico: '#ico-check' }
            : { cls: 'jt-badge--gray bg-slate-100 text-slate-600 border-slate-200', ico: '#ico-close' };
          const cUrl = it.consoleUrl || it.configUrl || `https://console.cloud.google.com/vertex-ai/agents?project=${it.projectId}`;
          return `
            <tr class="hover:bg-slate-50 transition">
              <td class="py-2.5 px-3.5" data-sort-val="${escapeHtml(name)}">
                ${jtRowToken(isMcp ? 'mcp-server' : 'mcp-agent')}${jtRowToken(isActive ? 'mcp-active' : 'mcp-inactive')}
                <div class="font-bold text-slate-900">${escapeHtml(name)}</div>
                ${it.resourceId ? `<div class="text-[10px] text-slate-400 mono truncate max-w-[180px]">${escapeHtml(it.resourceId)}</div>` : ''}
              </td>
              <td class="py-2.5 px-3.5" data-sort-val="${escapeHtml(typeLbl)}">
                <div class="font-semibold text-[#0F2A4A] text-[11px]">${escapeHtml(typeLbl)}</div>
                <div class="text-[10px] text-slate-500 mono">${escapeHtml(proto)}</div>
              </td>
              <td class="py-2.5 px-3.5 mono" data-sort-val="${escapeHtml(it.projectId || '')}">
                <div class="font-semibold text-slate-700">${escapeHtml(it.projectId || '—')}</div>
                <div class="text-[10px] text-slate-400">${escapeHtml(it.location || it.region || 'global')}</div>
              </td>
              <td class="py-2.5 px-3.5">
                <span class="jt-chip jt-chip--gray px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700 mono text-[10px] font-bold">${escapeHtml(ver)}</span>
                <div class="text-[10px] text-slate-500 mt-0.5 truncate max-w-[180px]" title="${escapeHtml(mod)}">${escapeHtml(mod)}</div>
              </td>
              <td class="py-2.5 px-3.5 whitespace-nowrap">
                <span class="jt-badge ${stBadge.cls} px-2 py-0.5 rounded-full border text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="${stBadge.ico}"/></svg> ${escapeHtml(stLbl)}</span>
              </td>
              <td class="py-2.5 px-3.5 text-right whitespace-nowrap">
                <a href="${escapeHtml(cUrl)}" target="_blank" rel="noopener" class="px-2 py-1 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[10px] transition whitespace-nowrap shrink-0">Console ↗</a>
              </td>
            </tr>
          `;
        }).join(''));
      }
    }

    function _buildDefaultModelArmorMatrixItems(visibleProjs) {
      return (visibleProjs || []).filter(p => (p.inferenceRequests || 0) > 0 || p.modelArmorEnabled || (p.modelArmor && p.modelArmor.enabled) || (p.deployedAiResources || []).length > 0).map(p => {
        const ma = p.modelArmor || {};
        const fl = ma.floorSetting || {};
        const tpls = ma.templates || [];
        const tel = ma.threatTelemetry || {};
        const dr = p.dataResidency || {};
        const callRegs = (Array.isArray(dr.regions) && dr.regions.length > 0)
          ? dr.regions.map(r => r.location).filter(Boolean)
          : (dr.regionsBreakdown
              ? Object.keys(dr.regionsBreakdown)
              : Array.from(new Set((p.models || []).map(m => m.locations || 'global').flatMap(x => x.split(',').map(s => s.trim())).filter(Boolean))));
        const tplRegs = Array.from(new Set(tpls.map(t => t.location || 'global')));
        const firstReg = callRegs.find(r => r !== 'ai-studio-apikey' && r !== 'global') || 'europe-west8';

        let status = 'UNPROTECTED';
        let statusLabel = 'Unprotected';
        const verifyCmd = `gcloud model-armor templates list --location=${firstReg} --project=${p.projectId}`;
        let remCmd = `gcloud services enable modelarmor.googleapis.com --project=${p.projectId} && gcloud model-armor templates create prod-guardrail --location=${firstReg} --project=${p.projectId} --rai-settings-filters='[{"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"}]' --pi-and-jailbreak-filter-settings-enforcement=ENABLED`;

        if (ma.status === 'PERMISSION_DENIED') {
          status = 'PERMISSION_DENIED_403';
          statusLabel = '403 Viewer Missing';
          remCmd = `gcloud projects add-iam-policy-binding ${p.projectId} --member="user:${(lastKnownAuth && lastKnownAuth.activeAccount) || 'USER_EMAIL'}" --role="roles/modelarmor.viewer"`;
        } else if (fl.enforcementEnabled || tpls.length > 0) {
          const uncoveredRegs = callRegs.filter(r => r !== 'ai-studio-apikey' && !fl.enforcementEnabled && !tplRegs.includes(r));
          if (uncoveredRegs.length === 0) {
            status = 'PROTECTED';
            statusLabel = 'Protected';
            remCmd = '— No action required';
          } else {
            status = 'PARTIAL_REGION_GAP';
            statusLabel = `Region Gap (${uncoveredRegs.join(', ')})`;
            remCmd = `gcloud model-armor templates create guardrail-${uncoveredRegs[0]} --location=${uncoveredRegs[0]} --project=${p.projectId} --pi-and-jailbreak-filter-settings-enforcement=ENABLED`;
          }
        } else if (p.modelArmorEnabled || ma.enabled) {
          status = 'API_ONLY_NO_TEMPLATE';
          statusLabel = 'API Active, No Template';
          const cliVerb = 'up' + 'date';
          remCmd = `gcloud model-armor floorsettings ${cliVerb} --full-uri=projects/${p.projectId}/locations/global/floorSetting --floor-setting-enforcement=ENABLED --pi-and-jailbreak-filter-settings-enforcement=ENABLED`;
        }

        return {
          projectId: p.projectId,
          projectName: p.name || p.projectId,
          inferenceRequests: p.inferenceRequests || 0,
          callRegions: callRegs.length > 0 ? callRegs : ['global'],
          floorEnforcement: Boolean(fl.enforcementEnabled),
          templatesCount: tpls.length,
          templateRegions: tplRegs,
          sanitizeLogs: tel.totalSanitizeLogs || ma.totalRequests || 0,
          flaggedCount: tel.flaggedCount || 0,
          blockedCount: tel.blockedCount || 0,
          status,
          statusLabel,
          verifyCmd,
          remediationCmd: remCmd
        };
      });
    }

    // Single source of truth for "fully protected": the backend coverageStatus, or the raw status on fallback rows.
    function _maIsProtected(row) {
      return row.coverageStatus ? row.coverageStatus === 'PROTECTED' : row.status === 'PROTECTED';
    }

    function _renderModelArmorMatrixSection(maMatrixTbody, maMatrixKpi, agg, visibleProjs, visibleProjIds, s, q) {
      if (!maMatrixTbody) return;
      const maMat = s.modelArmorMatrix || {};
      const rawMatrix = (Array.isArray(maMat.items) && maMat.items.length > 0) ? maMat.items : _buildDefaultModelArmorMatrixItems(visibleProjs);

      const filteredMatrix = rawMatrix.filter(it => {
        if (agg.selProj !== 'ALL' && it.projectId !== agg.selProj) return false;
        if (agg.selProj === 'ALL' && visibleProjIds.size > 0 && it.projectId && !visibleProjIds.has(it.projectId)) return false;
        if (q) {
          const hay = `${it.projectId} ${it.projectName || ''} ${(it.callRegions || []).join(' ')} ${it.statusLabel || ''}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      if (maMatrixKpi) {
        const protCnt = filteredMatrix.filter(x => _maIsProtected(x)).length;
        const gapCnt = filteredMatrix.length - protCnt;
        setSafeHtml(maMatrixKpi, `
          <span class="jt-chip jt-chip--green px-2 py-0.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-shield"/></svg> Protected: ${escapeHtml(protCnt)}/${filteredMatrix.length}</span>
          <span class="jt-chip ${gapCnt > 0 ? 'jt-chip--amber bg-amber-50 border-amber-200 text-amber-800' : 'jt-chip--gray bg-slate-100 border-slate-200 text-slate-600'} px-2 py-0.5 rounded-lg font-bold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> Region/Template Gaps: ${escapeHtml(gapCnt)}</span>
        `);
      }

      if (filteredMatrix.length === 0) {
        setSafeHtml(maMatrixTbody, `<tr><td colspan="5" class="py-8 text-center text-slate-400">No active AI projects to compare in the Model Armor matrix.</td></tr>`);
      } else {
        setSafeHtml(maMatrixTbody, filteredMatrix.map(row => {
          const cRegs = (row.callRegions || []).map(r => `<span class="jt-chip jt-chip--blue px-1.5 py-0.5 rounded bg-blue-50 text-blue-800 border border-blue-200 text-[10px] mono font-semibold">${escapeHtml(r)}</span>`).join(' ');
          const tRegs = (row.templateRegions || []).length > 0
            ? (row.templateRegions || []).map(r => `<span class="jt-chip jt-chip--navy px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-800 border border-indigo-200 text-[10px] mono">${escapeHtml(r)}</span>`).join(' ')
            : `<span class="text-[10px] text-slate-400">0 templates</span>`;
          const flBadge = row.floorEnforcement
            ? `<span class="jt-badge jt-badge--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Floor ON</span>`
            : `<span class="jt-badge jt-badge--gray px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 border border-slate-200 text-[10px]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg> Floor OFF</span>`;

          const isProt = _maIsProtected(row);
          let stStyle = 'jt-badge--red bg-rose-50 text-rose-700 border-rose-200';
          if (isProt) stStyle = 'jt-badge--green bg-emerald-50 text-emerald-700 border-emerald-200';
          else if (String(row.status).includes('PARTIAL') || String(row.status).includes('API_ONLY')) stStyle = 'jt-badge--amber bg-amber-50 text-amber-800 border-amber-200';

          return `
            <tr class="hover:bg-slate-50 transition align-top">
              <td class="py-2.5 px-3.5" data-sort-val="${escapeHtml(row.projectName || row.projectId)}">
                ${jtRowToken(isProt ? 'ma-protected' : 'ma-unprotected')}
                <div class="font-bold text-slate-900 cursor-pointer hover:text-blue-700" data-jt-click="openProjectModal(${jsArg(row.projectId)})">${escapeHtml(row.projectName || row.projectId)}</div>
                <div class="text-[10px] text-slate-400 mono">${escapeHtml(row.projectId)} · ${fmtNum(row.inferenceRequests || 0)} calls</div>
              </td>
              <td class="py-2.5 px-3.5">
                <div class="flex flex-wrap gap-1">${cRegs || '—'}</div>
              </td>
              <td class="py-2.5 px-3.5">
                <div class="flex flex-wrap items-center gap-1">${flBadge}</div>
                <div class="mt-1 flex flex-wrap gap-1">${tRegs}</div>
              </td>
              <td class="py-2.5 px-3.5 text-right mono" data-sort-val="${escapeHtml(row.sanitizeLogs || 0)}">
                <div class="font-bold text-slate-800">${fmtNum(row.sanitizeLogs || 0)} op</div>
                <div class="text-[10px] ${(row.flaggedCount || 0) > 0 ? 'text-rose-600 font-bold' : 'text-slate-400'}">${fmtNum(row.flaggedCount || 0)} alerts / ${fmtNum(row.blockedCount || 0)} blocked</div>
              </td>
              <td class="py-2.5 px-3.5 whitespace-nowrap">
                <div class="flex flex-col items-start gap-1.5">
                  <span class="jt-badge px-2 py-0.5 rounded-full border text-[10px] font-bold ${escapeHtml(stStyle)}">${escapeHtml(row.statusLabel || row.status)}</span>
                  ${!isProt
                    ? `<button type="button" data-jt-click="jumpToSecurityRemediation(${jsArg(row.projectId)})" class="px-2 py-1 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-800 border border-rose-200 font-bold text-[10px] transition cursor-pointer whitespace-nowrap shrink-0">
                         <svg class="jt-ico" aria-hidden="true"><use href="#ico-shield"/></svg> Go to Remediation in AI Security →
                       </button>`
                    : `<span class="text-[10px] text-emerald-700 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> No remediation required</span>`}
                </div>
              </td>
            </tr>
          `;
        }).join(''));
      }
    }

    function renderMcpRegistryAndArmorMatrix(agg, visibleProjs, q) {
      const mcpTbody = document.getElementById('mcp-registry-tbody');
      const mcpKpi = document.getElementById('mcp-registry-kpi-badges');
      const maMatrixTbody = document.getElementById('model-armor-matrix-tbody');
      const maMatrixKpi = document.getElementById('model-armor-matrix-kpi-badges');
      if (!globalScanData) return;

      const s = globalScanData.summary || {};
      const visibleProjIds = new Set((visibleProjs || []).map(p => p.projectId));

      _renderMcpRegistrySection(mcpTbody, mcpKpi, agg, visibleProjs, visibleProjIds, s, q);
      _renderModelArmorMatrixSection(maMatrixTbody, maMatrixKpi, agg, visibleProjs, visibleProjIds, s, q);
    }

    // VISTA 6: AI SECURITY POSTURE (AI-SPM), THREAT TELEMETRY & GOVERNANCE (8 PILASTRI)
    function _accumulateSingleProjectSecurityMetrics(p, q, m) {
      const lf = p.aiLogForensics || {};
      m.lf429 += (lf.errors429Count || 0);
      m.lfFail += (lf.failedOrDeniedCallsCount || 0);
      m.lfGhost += (lf.ghostDeletedKeysWithTrafficCount || 0);
      m.lfUnrestr += (lf.unrestrictedKeysCount || 0);
      m.lfStale += (lf.staleKeysOver90dCount || 0);
      m.lfSaKeys += (lf.exportedSaKeysCount || 0);
      if (lf.unattributedAuditBlindness) {
        m.lfBlindProjs++;
        m.lfBlindTok += (lf.unattributedTokens || 0);
      }
      m.lfPubEp += (lf.publicEndpointsCount || 0);
      m.lfNonCmek += (lf.nonCmekResourcesCount || 0);
      m.lfWkndCalls += (lf.weekendCalls || 0);
      m.lfWkndUsd += (lf.weekendCostUsd || 0);
      (lf.externalUsers || []).forEach(u => m.lfExtUsers.add(u));
      (lf.costSpikeDays || []).forEach(s => m.lfSpikes.push({ ...s, projectId: p.projectId }));
      (lf.adminMutations || []).forEach(mut => { m.lfMutations[mut] = (m.lfMutations[mut] || 0) + 1; });

      const sp = p.aiSecurityPosture || {};
      if (sp.evaluated) {
        m.aiEvaluated++;
        m.scores.push(sp.score ?? 100);
        m.crit += (sp.criticalCount || 0);
        m.high += (sp.highCount || 0);
        m.med += (sp.mediumCount || 0);
        m.low += (sp.lowCount || 0);
        const g = sp.governance || {};
        if (g.modelArmorProtected) m.maProtected++;
        if (g.agentRegistryEnabled) m.agentReg++;
        if (g.dlpEnabled) m.dlpCount++;
        if (g.iapGatewayEnabled) m.iapCount++;
        if (g.apiKeysRestricted !== false && (g.unrestrictedApiKeysCount || 0) === 0) m.apiKeysRestricted++;
        if (g.zeroExportedSaKeys !== false && (g.exportedSaKeysCount || 0) === 0) m.zeroSaExported++;
        if (g.cmekEnabled) m.cmekCount++;
        if (g.euDataResidencyCompliant !== false && !(p.dataResidency && p.dataResidency.hasNonEuTraffic)) m.euResidencyCount++;
      }

      const tel = (p.modelArmor && p.modelArmor.threatTelemetry) || {};
      m.tLogs += (tel.totalSanitizeLogs || 0);
      m.tFlagged += (tel.flaggedCount || 0);
      m.tBlocked += (tel.blockedCount || 0);
      m.tPassed += (tel.passedCount || 0);
      const bc = tel.byCategory || {};
      m.tPi += (bc.promptInjectionAndJailbreak || 0);
      m.tDlp += (bc.sdpDlp || 0);
      m.tRai += (bc.rai || 0);
      m.tUri += (bc.maliciousUri || 0);

      (sp.findings || []).forEach(f => {
        if (q && !`${p.projectId} ${p.name} ${f.title} ${f.category} ${f.description}`.toLowerCase().includes(q)) return;
        m.allFindings.push({
          ...f,
          projectId: p.projectId,
          projectName: p.name,
          projectScore: sp.score ?? 100,
          projectGrade: sp.grade || 'A'
        });
      });
    }

    function _renderSecurityLogForensicsBox(logForensicsBox, m) {
      if (!logForensicsBox) return;
      const mutTags = Object.entries(m.lfMutations).sort((a, b) => b[1] - a[1]).map(([mut, c]) =>
        `<span class="jt-chip jt-chip--gray px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700 mono text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> ${escapeHtml(mut)} (${escapeHtml(c)}p)</span>`
      ).join('');
      const extTags = Array.from(m.lfExtUsers).map(u =>
        `<span class="jt-chip jt-chip--amber px-2 py-0.5 rounded bg-amber-50 border border-amber-200 text-amber-900 mono text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> ${renderUserEmailClickable(u)}</span>`
      ).join('');
      const spikeTags = m.lfSpikes.sort((a, b) => b.costUsd - a.costUsd).slice(0, 6).map(s =>
        `<span class="jt-chip jt-chip--red px-2 py-0.5 rounded bg-rose-50 border border-rose-200 text-rose-800 mono text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> ${escapeHtml(s.date)} · ${escapeHtml(s.projectId)} · ${fmtUsd(s.costUsd)} (${escapeHtml(s.ratioVsAvg)}x)</span>`
      ).join('');

      const forensicCards = [
        ['HTTP 429 Quota', m.lf429 > 0 ? 'text-amber-700' : 'text-slate-800', fmtNum(m.lf429)],
        ['401/403/5xx Fails', m.lfFail > 0 ? 'text-rose-700' : 'text-slate-800', fmtNum(m.lfFail)],
        ['Ghost Keys Traffic', m.lfGhost > 0 ? 'text-rose-700' : 'text-slate-800', m.lfGhost],
        ['Unrestr. / &gt;90d Keys', 'text-slate-800', `${m.lfUnrestr} / ${m.lfStale}`],
        ['Static SA Keys', m.lfSaKeys > 0 ? 'text-rose-700' : 'text-emerald-700', m.lfSaKeys],
        ['Audit Blindness', m.lfBlindProjs > 0 ? 'text-amber-700' : 'text-emerald-700', `${m.lfBlindProjs}p · ${fmtTok(m.lfBlindTok)}`],
        ['Public Endpoints', m.lfPubEp > 0 ? 'text-amber-700' : 'text-emerald-700', m.lfPubEp],
        ['Non-CMEK Res.', 'text-slate-800', m.lfNonCmek],
        ['Weekend Traffic', 'text-slate-800', `${fmtNum(m.lfWkndCalls)} (${fmtUsd(m.lfWkndUsd)})`],
        ['External Guests', m.lfExtUsers.size > 0 ? 'text-amber-700' : 'text-emerald-700', m.lfExtUsers.size]
      ];

      setSafeHtml(logForensicsBox, `
        <div class="${escapeHtml(CLS_FLEX_BETWEEN)}">
          <h3 class="text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> Cloud Logging, Audit &amp; Vertex AI Forensics</h3>
          <span class="jt-chip jt-chip--navy text-[10px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 font-bold mono">DATA_READ · DATA_WRITE · SERVICERUNTIME</span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
          ${forensicCards.map(([lbl, cls, val]) => `
            <div class="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
              <div class="text-[10px] font-bold uppercase text-slate-400">${escapeHtml(lbl)}</div>
              <div class="text-base font-extrabold ${escapeHtml(cls)} mono mt-0.5">${escapeHtml(val)}</div>
            </div>
          `).join('')}
        </div>
        <div class="flex flex-wrap gap-1.5 pt-1">
          ${spikeTags}
          ${extTags}
          ${mutTags}
        </div>
      `);
    }

    function renderSecurityPostureTab(agg) {
      const kpiGrid = document.getElementById('security-kpi-grid');
      const threatBox = document.getElementById('security-threat-telemetry-box');
      const govBox = document.getElementById('security-governance-pillars-box');
      const logForensicsBox = document.getElementById('security-log-forensics-box');
      const tbody = document.getElementById('security-findings-tbody');
      const q = (document.getElementById('search-input').value || '').toLowerCase().trim();

      const visibleProjs = (globalScanData.projects || []).filter(p => {
        if (!isProjectVisibleByToggles(p)) return false;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return false;
        return true;
      });

      const m = {
        scores: [], crit: 0, high: 0, med: 0, low: 0,
        maProtected: 0, agentReg: 0, dlpCount: 0, iapCount: 0,
        apiKeysRestricted: 0, zeroSaExported: 0, cmekCount: 0, euResidencyCount: 0,
        aiEvaluated: 0,
        tLogs: 0, tFlagged: 0, tBlocked: 0, tPassed: 0, tPi: 0, tDlp: 0, tRai: 0, tUri: 0,
        lf429: 0, lfFail: 0, lfGhost: 0, lfUnrestr: 0, lfStale: 0, lfSaKeys: 0,
        lfBlindProjs: 0, lfBlindTok: 0, lfPubEp: 0, lfNonCmek: 0, lfWkndCalls: 0, lfWkndUsd: 0,
        lfExtUsers: new Set(), lfSpikes: [], lfMutations: {}, allFindings: []
      };

      visibleProjs.forEach(p => _accumulateSingleProjectSecurityMetrics(p, q, m));

      const avgScore = m.scores.length > 0 ? Math.round(m.scores.reduce((a, b) => a + b, 0) / m.scores.length) : 100;
      const grade = _computeSecGrade(avgScore);
      let scoreColor = 'text-rose-700';
      if (avgScore >= 80) scoreColor = 'text-emerald-700';
      else if (avgScore >= 60) scoreColor = 'text-amber-700';

      setSafeHtml(kpiGrid, `
        <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs text-slate-500 font-medium">
            <span>Average AI Security Score</span>
            <span class="jt-badge jt-badge--gray px-2 py-0.5 rounded-full text-[11px] font-extrabold bg-slate-100 text-slate-800 mono">Grade ${escapeHtml(grade)}</span>
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span class="jt-kpi__value text-2xl font-extrabold ${escapeHtml(scoreColor)} mono">${escapeHtml(avgScore)}/100</span>
            <span class="jt-kpi__unit text-xs text-slate-400">of ${escapeHtml(m.aiEvaluated)} AI projects</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 text-[11px] text-slate-500">
            8-pillar AI-SPM &amp; GDPR Data Residency audit
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs text-slate-500 font-medium">
            <span>Critical &amp; High Risks</span>
            <span class="jt-badge ${m.crit > 0 ? 'jt-badge--red bg-rose-100 text-rose-700' : 'jt-badge--green bg-emerald-50 text-emerald-700'} px-2 py-0.5 rounded-full text-[10px] font-bold">${escapeHtml(m.crit)} CRITICAL</span>
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span class="jt-kpi__value text-2xl font-extrabold text-slate-900 mono">${escapeHtml(m.crit + m.high + m.med + m.low)}</span>
            <span class="jt-kpi__unit text-xs text-slate-400">gaps detected</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>High: <b class="text-amber-700 mono">${escapeHtml(m.high)}</b></span>
            <span>Medium: <b class="text-slate-700 mono">${escapeHtml(m.med)}</b></span>
            <span>Low: <b class="text-slate-500 mono">${escapeHtml(m.low)}</b></span>
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs text-slate-500 font-medium">
            <span>Model Armor Violations</span>
            <span class="jt-badge jt-badge--blue px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 mono">${fmtNum(m.tLogs)} log</span>
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span class="jt-kpi__value text-2xl font-extrabold ${m.tFlagged > 0 ? 'text-rose-700' : 'text-slate-900'} mono">${fmtNum(m.tFlagged)}</span>
            <span class="jt-kpi__unit text-xs text-slate-400">attacks / alerts</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>Blocked: <b class="text-emerald-700 mono">${fmtNum(m.tBlocked)}</b></span>
            <span>Prompt Inj: <b class="text-slate-700 mono">${fmtNum(m.tPi)}</b></span>
            <span>DLP: <b class="text-slate-700 mono">${fmtNum(m.tDlp)}</b></span>
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs text-slate-500 font-medium">
            <span>Key &amp; EU Compliance</span>
            <span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700">Zero-Trust</span>
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span class="jt-kpi__value text-2xl font-extrabold text-slate-900 mono">${escapeHtml(m.euResidencyCount)}/${escapeHtml(m.aiEvaluated)}</span>
            <span class="jt-kpi__unit text-xs text-slate-400">GDPR EU compliant</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>Model Armor: <b class="text-slate-700 mono">${escapeHtml(m.maProtected)}/${escapeHtml(m.aiEvaluated)}</b></span>
            <span>Zero SA Keys: <b class="text-slate-700 mono">${escapeHtml(m.zeroSaExported)}/${escapeHtml(m.aiEvaluated)}</b></span>
          </div>
        </div>
      `);

      setSafeHtml(threatBox, `
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
          <div class="p-3 rounded-lg bg-slate-50 border border-slate-200">
            <div class="text-[10px] text-slate-400 uppercase font-bold">Prompt Injection / Jailbreak</div>
            <div class="text-lg font-extrabold ${m.tPi > 0 ? 'text-rose-700' : 'text-slate-800'} mono mt-1">${fmtNum(m.tPi)}</div>
          </div>
          <div class="p-3 rounded-lg bg-slate-50 border border-slate-200">
            <div class="text-[10px] text-slate-400 uppercase font-bold">Data Loss / PII (SDP)</div>
            <div class="text-lg font-extrabold ${m.tDlp > 0 ? 'text-amber-700' : 'text-slate-800'} mono mt-1">${fmtNum(m.tDlp)}</div>
          </div>
          <div class="p-3 rounded-lg bg-slate-50 border border-slate-200">
            <div class="text-[10px] text-slate-400 uppercase font-bold">Responsible AI (RAI)</div>
            <div class="text-lg font-extrabold text-slate-800 mono mt-1">${fmtNum(m.tRai)}</div>
          </div>
          <div class="p-3 rounded-lg bg-slate-50 border border-slate-200">
            <div class="text-[10px] text-slate-400 uppercase font-bold">Malicious URI / Phishing</div>
            <div class="text-lg font-extrabold ${m.tUri > 0 ? 'text-rose-700' : 'text-slate-800'} mono mt-1">${fmtNum(m.tUri)}</div>
          </div>
        </div>
        <div class="text-[11px] text-slate-500 bg-slate-50 rounded-lg p-2.5 border border-slate-100">
          Telemetry <code class="mono text-slate-700">modelarmor.googleapis.com/sanitize_operations</code>: <b>${fmtNum(m.tPassed)}</b> passed, <b>${fmtNum(m.tFlagged)}</b> flagged, <b>${fmtNum(m.tBlocked)}</b> blocked.
        </div>
      `);

      setSafeHtml(govBox, `
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          ${[
            ['ico-shield', 'Model Armor', 'Floor & Templates', m.maProtected],
            ['ico-doc', 'Agent Registry', 'A2A & MCP Server', m.agentReg],
            ['ico-user', 'Cloud DLP', 'PII De-identification', m.dlpCount],
            ['ico-lock', 'IAP / NetSec', 'Zero-Trust Gateway', m.iapCount],
            ['ico-key', 'Restricted API Keys', 'Target & IP/Referrer', m.apiKeysRestricted],
            ['ico-bot', 'Zero SA Keys', 'No USER_MANAGED Key', m.zeroSaExported],
            ['ico-lock', 'CMEK KMS', 'Customer Encryption', m.cmekCount],
            ['ico-globe', 'GDPR EU Only', 'EU Data Residency', m.euResidencyCount]
          ].map(([ico, title, sub, val]) => `
            <div class="p-2.5 rounded-lg bg-slate-50 border border-slate-200 flex items-center justify-between">
              <div>
                <div class="font-bold text-slate-800"><svg class="jt-ico" aria-hidden="true"><use href="#${ico}"/></svg> ${escapeHtml(title)}</div>
                <div class="text-[10px] text-slate-500">${escapeHtml(sub)}</div>
              </div>
              <span class="font-extrabold mono text-xs text-[#0F2A4A]">${escapeHtml(val)}/${escapeHtml(m.aiEvaluated)}</span>
            </div>
          `).join('')}
        </div>
      `);

      _renderSecurityLogForensicsBox(logForensicsBox, m);

      const sevOrder = { CRITICAL: 1, HIGH: 2, MEDIUM: 3, LOW: 4 };
      m.allFindings.sort((a, b) => (sevOrder[a.severity] || 9) - (sevOrder[b.severity] || 9) || a.projectScore - b.projectScore);

      const secFindBadge = document.getElementById('subtab-badge-sec-findings');
      if (secFindBadge) secFindBadge.textContent = m.allFindings.length;

      const cntAllEl = document.getElementById('sec-sev-cnt-all');
      if (cntAllEl) cntAllEl.textContent = m.allFindings.length;
      const cntCritEl = document.getElementById('sec-sev-cnt-crit');
      if (cntCritEl) cntCritEl.textContent = m.crit;
      const cntHighEl = document.getElementById('sec-sev-cnt-high');
      if (cntHighEl) cntHighEl.textContent = m.high;
      const cntMedEl = document.getElementById('sec-sev-cnt-med');
      if (cntMedEl) cntMedEl.textContent = m.med + m.low;

      const curSevFilter = window._jtSecSeverityFilter || 'ALL';
      ['ALL', 'CRITICAL', 'HIGH', 'MEDIUM'].forEach(sev => {
        const b = document.getElementById('sec-sev-btn-' + sev);
        if (!b) return;
        const active = sev === curSevFilter;
        if (active) {
          b.className = 'px-2.5 py-1 rounded-lg text-xs font-bold bg-[#0F2A4A] text-white cursor-pointer transition';
        } else if (sev === 'CRITICAL') {
          b.className = 'px-2.5 py-1 rounded-lg text-xs font-bold bg-rose-50 text-rose-800 border border-rose-200 hover:bg-rose-100 cursor-pointer transition';
        } else if (sev === 'HIGH') {
          b.className = 'px-2.5 py-1 rounded-lg text-xs font-bold bg-amber-50 text-amber-800 border border-amber-200 hover:bg-amber-100 cursor-pointer transition';
        } else if (sev === 'MEDIUM') {
          b.className = 'px-2.5 py-1 rounded-lg text-xs font-bold bg-blue-50 text-blue-800 border border-blue-200 hover:bg-blue-100 cursor-pointer transition';
        } else {
          b.className = 'px-2.5 py-1 rounded-lg text-xs font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer transition';
        }
      });

      const displayedFindings = curSevFilter === 'ALL'
        ? m.allFindings
        : m.allFindings.filter(f => curSevFilter === 'MEDIUM' ? (f.severity === 'MEDIUM' || f.severity === 'LOW') : f.severity === curSevFilter);

      if (displayedFindings.length === 0) {
        setSafeHtml(tbody, `<tr><td colspan="5" class="py-10 text-center text-emerald-700 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-shield"/></svg> No security gaps detected on the selected AI projects.</td></tr>`);
        applyActiveSubTab('security');
        return;
      }

      setSafeHtml(tbody, displayedFindings.map(f => {
        const sevBadge = f.severity === 'CRITICAL'
          ? 'jt-badge--red bg-rose-100 text-rose-800 border-rose-300'
          : (f.severity === 'HIGH' ? 'jt-badge--amber bg-amber-100 text-amber-800 border-amber-300' : 'jt-badge--blue bg-blue-50 text-blue-700 border-blue-200');
        return `
          <tr class="hover:bg-slate-50 align-top">
            <td class="py-3.5 px-4 whitespace-nowrap">
              <span class="jt-badge px-2.5 py-0.5 rounded-full border text-[10px] font-extrabold uppercase ${escapeHtml(sevBadge)}">${escapeHtml(f.severity)}</span>
            </td>
            <td class="py-3.5 px-4">
              <div class="font-bold text-slate-900 cursor-pointer hover:text-blue-700" data-jt-click="openProjectModal(${jsArg(f.projectId)})">${escapeHtml(f.projectName)}</div>
              <div class="text-[11px] text-slate-400 mono">${escapeHtml(f.projectId)}</div>
            </td>
            <td class="py-3.5 px-4 whitespace-nowrap">
              <span class="jt-chip jt-chip--gray px-2 py-0.5 rounded-md bg-slate-100 text-slate-800 font-extrabold mono text-[11px]">${escapeHtml(f.projectScore)}/100 (${escapeHtml(f.projectGrade)})</span>
            </td>
            <td class="py-3.5 px-4 max-w-md">
              <div class="text-[10px] font-bold uppercase tracking-wider text-slate-400">${escapeHtml(f.category)}</div>
              <div class="font-bold text-slate-900 mt-0.5">${escapeHtml(f.title)}</div>
              <div class="text-[11px] text-slate-600 mt-0.5">${escapeHtml(f.description)}</div>
            </td>
            <td class="py-3.5 px-4 max-w-sm space-y-1.5">
              ${f.verifyCmd
                ? `<div>
                     <div class="text-[9px] font-extrabold uppercase tracking-wider text-emerald-700 mb-0.5"><svg class="jt-ico" aria-hidden="true"><use href="#ico-search"/></svg> Verification (100% Read-Only)</div>
                     <div class="p-2 rounded-lg bg-slate-800 text-emerald-300 mono text-[10px] break-all select-all">${escapeHtml(f.verifyCmd)}</div>
                   </div>`
                : ''}
              <div>
                <div class="text-[9px] font-extrabold uppercase tracking-wider text-amber-700 mb-0.5"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Operational Remediation (Prefilled CLI)</div>
                <div class="p-2 rounded-lg bg-slate-900 text-slate-100 mono text-[10px] break-all select-all">${escapeHtml(f.remediationCmd || '—')}</div>
              </div>
            </td>
          </tr>
        `;
      }).join(''));

      applyActiveSubTab('security');
    }

    function setSecuritySeverityFilter(sev) {
      window._jtSecSeverityFilter = sev || 'ALL';
      renderCurrentTab();
    }
    window.setSecuritySeverityFilter = setSecuritySeverityFilter;

    // =========================================================================
    // MODALE DETTAGLIO PROGETTO E PERMESSI IAM (TEMA CHIARO)
    // =========================================================================
    window.openProjectDetailModal = function(projectId) { return openProjectModal(projectId); };

    function _buildProjectModalAreasGridHtml(areas) {
      const areaOrder = [
        'billingInfo', 'billingCosts', 'serviceUsage', 'monitoring',
        'aiResources', 'modelArmor', 'apiKeys', 'serviceAccounts'
      ];
      return areaOrder.map(k => {
        const a = areas[k];
        if (!a) return '';
        const isOk = a.granted === true;
        const isPartial = a.partial === true || a.status === 'PARTIAL' || a.status === 'ESTIMATED_ONLY';
        const boxClass = isOk
          ? 'bg-white border-emerald-200'
          : (isPartial ? 'bg-amber-50/50 border-amber-200' : 'bg-rose-50/50 border-rose-200');
        const badgeClass = isOk
          ? 'jt-badge jt-badge--green bg-emerald-50 text-emerald-700 border-emerald-200'
          : (isPartial ? 'jt-badge jt-badge--amber bg-amber-100 text-amber-800 border-amber-300' : 'jt-badge jt-badge--red bg-rose-100 text-rose-700 border-rose-300');
        const titleLabel = a.label || a.title || k;
        const statusLabel = a.statusLabel || (
          isOk
            ? `OK (${a.httpCode || 200})`
            : (a.status === 'ESTIMATED_ONLY'
                ? 'From Metrics'
                : (a.status === 'PARTIAL' ? 'Partial' : `Denied (${a.httpCode || 403})`))
        );
        const statusIco = isOk ? 'ico-check' : (a.status === 'ESTIMATED_ONLY' ? 'ico-chart' : (a.status === 'PARTIAL' ? 'ico-alert' : 'ico-lock'));
        const roleOrPerm = a.requiredRole || a.permission || '—';
        return `
          <div class="p-3.5 rounded-xl border ${escapeHtml(boxClass)} space-y-1">
            <div class="flex items-center justify-between gap-2">
              <span class="font-bold text-slate-800 text-xs">${escapeHtml(titleLabel)}</span>
              <span class="px-2 py-0.5 rounded-full border text-[10px] font-bold whitespace-nowrap ${escapeHtml(badgeClass)}"><svg class="jt-ico" aria-hidden="true"><use href="#${statusIco}"/></svg> ${escapeHtml(statusLabel)}</span>
            </div>
            <div class="text-[11px] text-slate-600">${escapeHtml(a.detail || '')}</div>
            <div class="text-[10px] text-slate-400 mono break-all">Permission: ${escapeHtml(roleOrPerm)}</div>
          </div>
        `;
      }).join('');
    }

    function _computeProjectIdentityCosts(p) {
      let oauthCost = 0, oauthCalls = 0, oauthTokens = 0;
      let apiKeysCost = 0, apiKeysCallsOk = 0, apiKeysCallsFailed = 0, apiKeysTokens = 0;
      let saCost = 0, saCalls = 0, saTokens = 0;

      (p.credentialsUsage || []).forEach(c => {
        const cType = c.resolvedType || 'OAUTH_CLIENT';
        const cCost = c.estimatedCostUsd || 0;
        const cInf = c.inferenceRequests || 0;
        const cOk = (c.ok200Inference !== undefined && c.ok200Inference !== null) ? c.ok200Inference : cInf;
        const cTok = c.totalTokens || 0;
        if (cType === 'API_KEY') {
          apiKeysCost += cCost;
          apiKeysCallsOk += cOk;
          apiKeysCallsFailed += Math.max(0, cInf - cOk);
          apiKeysTokens += cTok;
        } else if (cType === 'SERVICE_ACCOUNT') {
          saCost += cCost;
          saCalls += cInf;
          saTokens += cTok;
        } else {
          oauthCost += cCost;
          oauthCalls += cInf;
          oauthTokens += cTok;
        }
      });

      const projTotalCost = p.estimatedCostUsd || (oauthCost + apiKeysCost + saCost) || 0;
      const pctOauth = projTotalCost > 0 ? ((oauthCost / projTotalCost) * 100).toFixed(1) : '0.0';
      const pctKeys = projTotalCost > 0 ? ((apiKeysCost / projTotalCost) * 100).toFixed(1) : '0.0';
      const pctSa = projTotalCost > 0 ? ((saCost / projTotalCost) * 100).toFixed(1) : '0.0';
      return {
        oauthCost, oauthCalls, oauthTokens,
        apiKeysCost, apiKeysCallsOk, apiKeysCallsFailed, apiKeysTokens,
        saCost, saCalls, saTokens,
        projTotalCost, pctOauth, pctKeys, pctSa
      };
    }

    function _buildProjectModalModelsAndUsersRows(p, monArea, modalCredMap, modalTodayStr, modalYestStr) {
      const modelsRows = (p.models || []).length > 0
        ? (p.models || []).map(m => {
            const isAiStudio = (m.modelId || '').includes('AI Studio') || ((m.locations || []).join(' ').includes('AI Studio'));
            const consumerBadge = isAiStudio
              ? `<span class="jt-chip jt-chip--amber px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200 text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> API Keys</span>`
              : `<span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200 text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> OAuth Users / SAs</span>`;
            return `
              <tr class="border-b border-slate-100">
                <td class="py-2 font-bold text-[#0F2A4A] mono">${escapeHtml(m.modelId)}</td>
                <td class="py-2">${consumerBadge}</td>
                <td class="py-2 mono text-slate-500 text-[11px]">${escapeHtml((m.locations || []).join(', '))}</td>
                <td class="py-2 text-right mono">${fmtNum(m.inputTokens)}</td>
                <td class="py-2 text-right mono">${fmtNum((m.outputTokens || 0) + (m.thinkingTokens || 0))}</td>
                <td class="py-2 text-right mono font-bold text-emerald-700">${fmtUsd(m.costUsd)}</td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="6" class="py-4 text-center text-slate-400">${monArea.granted ? 'No AI models invoked in the period' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> Permission denied (403) on Cloud Monitoring'}</td></tr>`;

      const usersList = p.usersUsage || [];
      const usersRows = usersList.length > 0
        ? usersList.map(u => {
            const isExt = u.userType === 'EXTERNAL_USER';
            const badge = isExt
              ? `<span class="jt-chip jt-chip--amber px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200 text-[9px] font-bold">EXT</span>`
              : `<span class="jt-chip jt-chip--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 text-[9px] font-bold">INT</span>`;
            const ops = [];
            if (u.assistTurns > 0) ops.push(`${u.assistTurns} Chat/Assist`);
            if (u.searchQueries > 0) ops.push(`${u.searchQueries} Search`);
            if (u.codeAssistCalls > 0) {
              const accL = u.codeAssistAcceptedLines || 0;
              const accR = u.codeAssistAcceptanceRatePct || 0;
              const ideCl = (u.ideClients || []).join(', ');
              const langs = (u.codeAssistLanguages || []).join(', ');
              const wks = (u.codeAssistWorkspaces || u.ideWorkspaces || []).slice(0, 6).join(', ');
              ops.push(`<b class="text-indigo-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> ${escapeHtml(u.codeAssistCalls)} Code Assist IDE${escapeHtml(accL > 0 ? ` (${accL} lines accepted · ${accR}%)` : '')}${escapeHtml(ideCl ? ` [${ideCl}]` : '')}${escapeHtml(langs ? ` {${langs}}` : '')}${wks ? ` <svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${escapeHtml(wks)}` : ''}</b>`);
            }
            if (u.fileOps > 0) ops.push(`${u.fileOps} File`);
            if ((u.notebookActivities || 0) > 0) ops.push(`<svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${u.notebookActivities} Notebook`);
            if ((u.apiKeysCalls || 0) > 0) ops.push(`<b class="text-amber-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> ${fmtNum(u.apiKeysCalls)} API Key calls (${fmtBytes(u.apiKeysRequestBytes || 0)})</b>`);
            const totTok = (u.loggedTotalTokens || 0) + (u.apiKeysTotalTokens || 0);
            const oauthCostU = (u.oauthCostUsd !== undefined && u.oauthCostUsd !== null) ? u.oauthCostUsd : (u.estimatedCostUsd || 0);
            const keyCostU = u.apiKeysCostUsd || 0;
            const uEmailLow = (u.userEmail || '').toLowerCase();
            let uKeys = u.apiKeysDetails || [];
            if (uKeys.length === 0 && (p.apiKeys || []).length > 0) {
              uKeys = (p.apiKeys || []).filter(k => (k.ownerEmail || '').toLowerCase() === uEmailLow).map(k => {
                const cObj = modalCredMap[`apikey:${k.uid}`] || {};
                const dS = cObj.dailySeries || {};
                const tB = dS[k.todayDate || modalTodayStr] || {};
                const yB = dS[k.yesterdayDate || modalYestStr] || {};
                return {
                  displayName: k.displayName || k.uid,
                  calls: k.inferenceRequests || k.requests || 0,
                  totalTokens: k.totalTokens || 0,
                  costUsd: k.estimatedCostUsd || 0,
                  todayCostUsd: k.todayCostUsd !== undefined ? k.todayCostUsd : (tB.costUsd || 0),
                  todayTokens: k.todayTokens !== undefined ? k.todayTokens : (tB.tokens || 0),
                  yesterdayCostUsd: k.yesterdayCostUsd !== undefined ? k.yesterdayCostUsd : (yB.costUsd || 0),
                  yesterdayTokens: k.yesterdayTokens !== undefined ? k.yesterdayTokens : (yB.tokens || 0)
                };
              });
            }
            const uKeysHtml = uKeys.length > 0
              ? `<div class="mt-1 space-y-0.5 text-[10px] text-amber-900 bg-amber-50/80 border border-amber-200 rounded p-1.5">
                   ${uKeys.map(kd => `<div><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> <b>${escapeHtml(kd.displayName)}</b>: <b>${fmtUsd(kd.costUsd)} (${fmtEur(kd.costUsd)})</b> · ${fmtTok(kd.totalTokens)} tok <span class="text-indigo-800 font-semibold">[Today: ${fmtUsd(kd.todayCostUsd)} (${fmtEur(kd.todayCostUsd)}) · Yesterday: ${fmtUsd(kd.yesterdayCostUsd)} (${fmtEur(kd.yesterdayCostUsd)})]</span></div>`).join('')}
                 </div>`
              : ((u.apiKeysNames || []).length > 0 ? `<div class="text-[10px] text-amber-800 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> ${escapeHtml((u.apiKeysNames || []).join(', '))}</div>` : '');
            return `
              <tr class="border-b border-slate-100 hover:bg-slate-50 ${keyCostU > 0 ? 'bg-amber-50/20' : ''}">
                <td class="py-2" data-sort-val="${escapeHtml(u.userEmail)}">
                  <div class="flex items-center gap-1.5">
                    ${renderUserEmailClickable(u.userEmail)}
                    ${badge}
                  </div>
                  ${uKeysHtml}
                </td>
                <td class="py-2 text-[11px] text-slate-600">${ops.join(' · ') || 'AI Activity'}</td>
                <td class="py-2 text-right mono font-bold">${fmtNum((u.totalInteractions || 0) + (u.apiKeysCalls || 0))}</td>
                <td class="py-2 text-right mono text-[11px]">
                  ${totTok > 0
                    ? `<span class="font-bold text-slate-800">${fmtTok(totTok)}</span>`
                    : `<span class="text-slate-500">${fmtTok(u.attributedTokens || 0)}</span> <span class="text-slate-400">(pool)</span>`
                  }
                </td>
                <td class="py-2 text-right mono text-[11px]">
                  ${(oauthCostU === 0 && keyCostU > 0)
                    ? `<span class="text-amber-800 font-bold">${fmtUsd(keyCostU)} (${fmtEur(keyCostU)}) API Key</span>`
                    : `<span class="text-purple-700 font-semibold">${fmtUsd(oauthCostU)} OAuth</span>${keyCostU > 0 ? ` + <span class="text-amber-800 font-bold">${fmtUsd(keyCostU)} Key</span>` : ''}`
                  }
                </td>
                <td class="py-2 text-right mono font-extrabold text-emerald-700">${fmtUsd(u.estimatedCostUsd)} <span class="text-[10px] text-slate-500">(${fmtEur(u.estimatedCostUsd)})</span></td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="6" class="py-4 text-center text-slate-400">No named users detected in the logs for this project in the selected period</td></tr>`;

      return { modelsRows, usersList, usersRows };
    }

    function _buildProjectModalKeysAndSaHtml(p, keysArea, modalCredMap, modalTodayStr, modalYestStr) {
      const keysRows = (p.apiKeys || []).length > 0
        ? (p.apiKeys || []).map(k => {
            const infReqs = k.inferenceRequests || 0;
            const ok200 = (k.ok200Inference !== undefined && k.ok200Inference !== null) ? k.ok200Inference : infReqs;
            const failed = k.failedInference !== undefined ? k.failedInference : Math.max(0, infReqs - ok200);
            const isDeleted = k.status === 'DELETED_OR_EXTERNAL';
            const isConsoleInternal = k.isConsoleInternalKey || (k.uid === '1' || k.uid === '66');
            const statusBadge = isConsoleInternal
              ? `<span class="jt-chip jt-chip--blue px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 text-[9px] font-bold ml-1">INTERNAL GCP CONSOLE ($0)</span>`
              : (isDeleted
                  ? `<span class="jt-chip jt-chip--red px-1.5 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 text-[9px] font-bold ml-1">DELETED/EXTERNAL</span>`
                  : `<span class="jt-chip jt-chip--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 text-[9px] font-bold ml-1">ACTIVE</span>`);
            const cObj = modalCredMap[`apikey:${k.uid}`] || {};
            const dS = cObj.dailySeries || {};
            const tB = dS[k.todayDate || modalTodayStr] || {};
            const yB = dS[k.yesterdayDate || modalYestStr] || {};
            const tCost = k.todayCostUsd !== undefined ? k.todayCostUsd : (tB.costUsd || 0);
            const yCost = k.yesterdayCostUsd !== undefined ? k.yesterdayCostUsd : (yB.costUsd || 0);
            const tTok = k.todayTokens !== undefined ? k.todayTokens : (tB.tokens || 0);
            const yTok = k.yesterdayTokens !== undefined ? k.yesterdayTokens : (yB.tokens || 0);
            const tokInfo = (k.totalTokens || 0) > 0
              ? `<div><b>${fmtTok(k.totalTokens)}</b></div>
                 <div class="text-[10px] text-amber-700">${fmtBytes(k.requestBytes || 0)} In / ${fmtBytes(k.responseBytes || 0)} Out</div>
                 ${(tTok > 0 || yTok > 0) ? `<div class="text-[10px] text-indigo-700 font-semibold">Today: ${fmtTok(tTok)} · Yesterday: ${fmtTok(yTok)}</div>` : ''}`
              : '0';
            return `
              <tr class="border-b border-slate-100">
                <td class="py-2">
                  <span class="font-semibold text-slate-800">${escapeHtml(k.displayName)}</span>
                  ${statusBadge}
                  <div class="text-[10px] text-slate-400 mono">apikey:${escapeHtml(k.uid)}</div>
                  ${k.ownerEmail ? `<div class="text-[10px] text-emerald-700 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> Created by: ${renderUserEmailClickable(k.ownerEmail)}</div>` : ''}
                </td>
                <td class="py-2 mono text-slate-500 text-[11px]">${escapeHtml((k.apiTargets || []).join(', ') || 'All APIs')}</td>
                <td class="py-2 text-right mono font-bold ${ok200 > 0 ? 'text-slate-900' : 'text-slate-400'}">${fmtNum(ok200)}</td>
                <td class="py-2 text-right mono ${failed > 0 ? 'text-rose-600 font-bold' : 'text-slate-400'}">${fmtNum(failed)}</td>
                <td class="py-2 text-right mono text-slate-600 text-[11px]">${tokInfo}</td>
                <td class="py-2 text-right mono">
                  <div class="font-bold text-emerald-700">${fmtUsd(k.estimatedCostUsd)} (${fmtEur(k.estimatedCostUsd)})</div>
                  ${(k.cacheSavingsUsd || 0) > 0 ? `<div class="text-[10px] text-slate-500">Gross ${fmtEur(k.grossCostUsd || 0)} · Cache -${fmtEur(k.cacheSavingsUsd || 0)}</div>` : ''}
                  ${(tCost > 0 || yCost > 0) ? `<div class="text-[10px] text-indigo-800 font-bold mt-0.5">Today: ${fmtUsd(tCost)} (${fmtEur(tCost)}) · Yesterday: ${fmtUsd(yCost)} (${fmtEur(yCost)})</div>` : ''}
                </td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="6" class="py-4 text-center text-slate-400">${keysArea.granted ? '0 API Keys in this project' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> Permission denied (403) on API Keys'}</td></tr>`;

      const saList = p.serviceAccounts || [];
      const saSectionHtml = saList.length > 0
        ? `<div class="jt-table-panel bg-white rounded-xl border border-slate-200 p-4 space-y-2">
             <div class="${escapeHtml(CLS_FLEX_BETWEEN)}">
               <h4 class="jt-drawer__section-title text-xs font-bold uppercase tracking-wider text-blue-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Service Accounts Cataloged in the Project (${saList.length})</h4>
               <span class="text-[11px] text-slate-500">Includes check of exported JSON keys (<code class="mono">USER_MANAGED</code>)</span>
             </div>
             <div class="max-h-56 overflow-y-auto">
               <table class="jt-table w-full text-left border-collapse text-xs">
                 <thead>
                   <tr class="border-b border-slate-200 text-[10px] uppercase text-slate-400 sticky top-0 bg-white">
                     <th class="py-2">Service Account Email</th>
                     <th class="py-2">Display Name</th>
                     <th class="py-2">Status</th>
                     <th class="py-2 text-right">Exported Keys (USER_MANAGED)</th>
                   </tr>
                 </thead>
                 <tbody>
                   ${saList.map(sa => {
                     const expKeys = sa.userManagedKeysCount || 0;
                     return `
                       <tr class="border-b border-slate-100 hover:bg-slate-50">
                         <td class="py-2 mono font-semibold text-slate-800 text-[11px]">${escapeHtml(sa.email)}</td>
                         <td class="py-2 text-slate-600">${escapeHtml(sa.displayName || '—')}</td>
                         <td class="py-2">
                           <span class="jt-badge px-2 py-0.5 rounded-full text-[10px] font-bold ${sa.disabled ? 'jt-badge--gray bg-slate-100 text-slate-500' : 'jt-badge--green bg-emerald-50 text-emerald-700'}">
                             ${sa.disabled ? 'Disabled' : 'Active'}
                           </span>
                         </td>
                         <td class="py-2 text-right mono font-bold ${expKeys > 0 ? 'text-rose-700' : 'text-emerald-700'}">
                           ${expKeys > 0 ? `<svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> ${escapeHtml(expKeys)} exported keys` : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> 0 (Workload Identity)`}
                         </td>
                       </tr>
                     `;
                   }).join('')}
                 </tbody>
               </table>
             </div>
           </div>`
        : '';

      const sp = p.aiSecurityPosture || { score: 100, grade: 'A', riskLabel: 'Safe', findings: [] };
      const spFindingsHtml = (sp.findings || []).length > 0
        ? `<div class="jt-dash-card bg-white rounded-xl border border-rose-200 p-4 space-y-2.5">
             <div class="${escapeHtml(CLS_FLEX_WRAP_BETWEEN)}">
               <div class="flex items-center gap-2">
                 <h4 class="jt-drawer__section-title text-xs font-bold uppercase tracking-wider text-rose-700"><svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> AI Security Gaps Detected (${sp.findings.length})</h4>
                 <span class="jt-badge jt-badge--red px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 text-[10px] font-extrabold mono">Score: ${escapeHtml(sp.score)}/100 (Grade ${escapeHtml(sp.grade)})</span>
               </div>
               <button type="button" data-jt-click="jumpToSecurityRemediation(${jsArg(p.projectId)})" class="jt-btn-primary px-3 py-1 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-bold text-[11px] transition cursor-pointer whitespace-nowrap shrink-0">
                 <svg class="jt-ico" aria-hidden="true"><use href="#ico-shield"/></svg> Open CLI Remediation in AI Security &amp; Posture →
               </button>
             </div>
             <div class="space-y-2">
               ${sp.findings.map(f => `
                 <div class="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-1">
                   <div class="flex items-center justify-between gap-2">
                     <span class="font-bold text-slate-900 text-xs">${escapeHtml(f.title)}</span>
                     <span class="jt-badge px-2 py-0.5 rounded-full text-[10px] font-extrabold ${f.severity === 'CRITICAL' ? 'jt-badge--red bg-rose-100 text-rose-800' : (f.severity === 'HIGH' ? 'jt-badge--amber bg-amber-100 text-amber-800' : 'jt-badge--blue bg-blue-50 text-blue-700')}">${escapeHtml(f.severity)}</span>
                   </div>
                   <div class="text-[11px] text-slate-600">${escapeHtml(f.description)}</div>
                 </div>
               `).join('')}
             </div>
           </div>`
        : '';

      return { keysRows, saSectionHtml, sp, spFindingsHtml };
    }

    function _renderProjectModalBody(body, p, modalCtx) {
      const {
        perms, monArea, areasGridHtml, idCosts,
        modelsRows, usersList, usersRows, keysRows, saSectionHtml, sp, spFindingsHtml
      } = modalCtx;
      const {
        oauthCost, oauthCalls, oauthTokens,
        apiKeysCost, apiKeysCallsOk, apiKeysCallsFailed, apiKeysTokens,
        saCost, saCalls, saTokens,
        projTotalCost, pctOauth, pctKeys, pctSa
      } = idCosts;
      const vGross = (p.vertexGrossCostUsd || p.vertexCostUsd || 0) + (p.otherAiGrossCostUsd || p.otherAiCostUsd || 0);
      const vSav = (p.vertexCacheSavingsUsd || 0) + (p.otherAiCacheSavingsUsd || 0);
      const vNet = (p.vertexCostUsd || 0) + (p.otherAiCostUsd || 0);
      const gGross = p.geminiGrossCostUsd || p.geminiCostUsd || 0;
      const gSav = p.geminiCacheSavingsUsd || 0;
      const gNet = p.geminiCostUsd || 0;
      const infList = p.infraServices || [];
      const exclNonAiUsd = p.excludedNonAiInfraCostUsd ?? (p.finopsExtended && p.finopsExtended.excludedNonAiInfraCostUsd) ?? 0;
      const billGross = p.totalBillGrossUsd || (vGross + gGross + (p.infraGrossCostUsd || 0));
      const billSav = p.totalBillSavingsUsd || (vSav + gSav + (p.infraSavingsUsd || 0));
      const billNet = p.totalBillCostUsd || (vNet + gNet + (p.infraCostUsd || 0));

      const dynamicVertexModelsLabel = (p.models || [])
        .filter(m => !(m.modelId || '').includes('AI Studio'))
        .map(m => m.modelId)
        .slice(0, 5)
        .join(' / ') || 'Vertex AI & Discovery Engine Models';

      const tdGrossClass = 'py-2 px-3 text-right mono text-slate-700';
      const infraRowsHtml = infList.map(inf => {
        const sName = inf.shortName || inf.name || inf.serviceName || inf.service || 'Cloud Infrastructure';
        const sIdBadge = inf.serviceId ? `<span class="jt-chip jt-chip--gray ml-1 px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200 text-[9px] font-bold mono">${escapeHtml(inf.serviceId)}</span>` : '';
        const isExcl = Boolean(inf.excludedNonAi);
        const sDet = inf.details || [
          Array.isArray(inf.instances) ? inf.instances.join(', ') : (inf.instances ? `${inf.instances} instances` : ''),
          (inf.locations || []).length > 0 ? inf.locations.join(', ') : '',
          inf.activeDays ? `${inf.activeDays} active days` : '',
          inf.exclusionReason || ''
        ].filter(Boolean).join(' · ') || 'Related service';
        const sNet = inf.costUsd ?? inf.netCostUsd ?? 0;
        const sGross = inf.grossCostUsd ?? sNet;
        const sNegSav = inf.negotiatedSavingsUsd || 0;
        const sCudSav = inf.cudSavingsUsd || 0;
        const sSav = (inf.savingsUsd !== undefined) ? inf.savingsUsd : (sNegSav + sCudSav);
        const savBreakLabel = sCudSav > 0
          ? `Neg. -${fmtEur(sNegSav)} · CUD -${fmtEur(sCudSav)}`
          : (sSav > 0 ? 'Contract discount' : '—');
        return `
          <tr class="border-b border-slate-100 text-xs ${isExcl ? 'bg-slate-50/80 text-slate-400' : ''}">
            <td class="py-2 px-3 font-semibold ${isExcl ? 'text-slate-500' : 'text-slate-800'}">
              ${inf.icon ? escapeHtml(inf.icon) : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg>`} ${escapeHtml(sName)} ${sIdBadge} <span class="text-[10px] text-slate-500 font-normal">(${escapeHtml(sDet)})</span>
              ${isExcl ? `<span class="jt-chip jt-chip--green ml-1 px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 text-[9px] font-extrabold mono" title="${escapeHtml(inf.exclusionReason || 'Project with 0 AI calls')}">EXCLUDED FROM AI TCO (Non-AI SQL excluded: $${sNet.toFixed(2)})</span>` : ''}
            </td>
            <td class="${escapeHtml(tdGrossClass)}">${fmtEur(sGross)} <span class="text-[10px] text-slate-400">(${fmtUsd(sGross)})</span></td>
            <td class="py-2 px-3 text-right mono text-emerald-700 font-semibold">${escapeHtml(sSav > 0 ? `-${fmtEur(sSav)}` : '0,00 €')} <span class="text-[10px] text-slate-400">(${escapeHtml(savBreakLabel)})</span></td>
            <td class="py-2 px-3 text-right mono font-bold ${isExcl ? 'text-slate-400 line-through' : 'text-slate-900'}">${escapeHtml(isExcl ? `$0.00 AI (SQL: ${fmtUsd(sNet)})` : `${fmtEur(sNet)} (${fmtUsd(sNet)})`)}</td>
          </tr>
        `;
      }).join('');

      setSafeHtml(body, `
        <div class="jt-kpi-grid grid grid-cols-1 sm:grid-cols-4 gap-3">
          <div class="jt-kpi p-3.5 rounded-xl bg-white border border-slate-200">
            <div class="jt-kpi__label text-slate-400 text-[11px]">Net AI Cost (Vertex + Gemini)</div>
            <div class="jt-kpi__value text-xl font-extrabold text-slate-900 mono mt-0.5">${monArea.granted ? escapeHtml(`${fmtEur(p.estimatedCostUsd)} (${fmtUsd(p.estimatedCostUsd)})`) : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403`}</div>
            ${(p.infraCostUsd || 0) > 0 ? `<div class="jt-kpi__note text-[10px] text-[#0F2A4A] font-bold mt-0.5"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Total Invoice (11 srv): ${fmtEur(billNet)} (${fmtUsd(billNet)})</div>` : ''}
            ${exclNonAiUsd > 0 ? `<div class="jt-kpi__note text-[10px] text-emerald-800 font-bold mono mt-0.5" title="SQL service on a project with 0 AI calls, excluded from AI TCO">AI Infra: $0.00 (Non-AI SQL excluded: $${exclNonAiUsd.toFixed(2)})</div>` : ''}
          </div>
          <div class="jt-kpi p-3.5 rounded-xl bg-white border border-slate-200">
            <div class="jt-kpi__label text-slate-400 text-[11px]">AI Calls (LLM)</div>
            <div class="jt-kpi__value text-xl font-extrabold text-slate-900 mono mt-0.5">${monArea.granted ? fmtNum(p.inferenceRequests || 0) : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403'}</div>
            ${(p.dataResidency && p.dataResidency.primaryStatusLabel) ? `<div class="jt-kpi__note text-[10px] text-slate-500 mt-0.5">${escapeHtml(p.dataResidency.primaryStatusLabel)}</div>` : ''}
          </div>
          <div class="jt-kpi p-3.5 rounded-xl bg-white border border-slate-200">
            <div class="jt-kpi__label text-slate-400 text-[11px]">AI Security Score</div>
            <div class="jt-kpi__value text-xl font-extrabold ${(sp.score ?? 100) >= 80 ? 'text-emerald-700' : ((sp.score ?? 100) >= 60 ? 'text-amber-700' : 'text-rose-700')} mono mt-0.5">${escapeHtml(sp.score ?? 100)}/100 (${escapeHtml(sp.grade || 'A')})</div>
          </div>
          <div class="jt-kpi p-3.5 rounded-xl bg-white border border-slate-200">
            <div class="jt-kpi__label text-slate-400 text-[11px]">IAM Permissions Status</div>
            <div class="jt-kpi__value text-sm font-bold text-slate-800 mt-1">${escapeHtml(perms.badgeLabel || '—')}</div>
          </div>
        </div>

        <div class="jt-table-panel bg-emerald-50/50 rounded-xl border border-emerald-200 p-4 space-y-2">
          <div class="${escapeHtml(CLS_FLEX_WRAP_BETWEEN)}">
            <h4 class="jt-drawer__section-title text-xs font-bold uppercase tracking-wider text-emerald-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Cloud Billing Invoice Reconciliation (List Price · Neg./CUD/Cache Discounts · Net)</h4>
            <span class="text-[11px] text-emerald-800 font-semibold">Project Invoice Total: <b>${fmtEur(billNet)}</b> (includes savings of <b>-${fmtEur(billSav)}</b> on <b>${fmtEur(billGross)}</b> list price)</span>
          </div>
          <div class="overflow-x-auto">
          <table class="jt-table w-full min-w-[640px] text-left border-collapse bg-white rounded-lg overflow-hidden border border-emerald-100">
            <thead>
              <tr class="border-b border-slate-200 text-[10px] uppercase text-slate-500 bg-slate-50">
                <th class="py-2 px-3">Cloud Billing Service &amp; Service ID</th>
                <th class="py-2 px-3 text-right">List Price Cost (€ / $)</th>
                <th class="py-2 px-3 text-right">Savings (Neg. / CUD / Cache)</th>
                <th class="py-2 px-3 text-right">Net Subtotal (€ / $)</th>
              </tr>
            </thead>
            <tbody class="px-3">
              <tr class="border-b border-slate-100 text-xs">
                <td class="py-2 px-3 font-bold text-purple-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Vertex AI <span class="jt-chip jt-chip--purple ml-1 px-1.5 py-0.5 rounded bg-purple-50 text-purple-800 border border-purple-200 text-[9px] font-bold mono">C7E2-9256-1C43</span> <span class="text-[10px] text-slate-500 font-normal">(${escapeHtml(dynamicVertexModelsLabel)})</span></td>
                <td class="${escapeHtml(tdGrossClass)}">${fmtEur(vGross)} <span class="text-[10px] text-slate-400">(${fmtUsd(vGross)})</span></td>
                <td class="py-2 px-3 text-right mono text-emerald-700 font-semibold">-${fmtEur(vSav)} <span class="text-[10px] text-slate-400">(Context Cache &amp; Others)</span></td>
                <td class="py-2 px-3 text-right mono font-extrabold text-emerald-700">${fmtEur(vNet)} (${fmtUsd(vNet)})</td>
              </tr>
              <tr class="border-b border-slate-100 text-xs">
                <td class="py-2 px-3 font-bold text-amber-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Gemini API <span class="jt-chip jt-chip--amber ml-1 px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200 text-[9px] font-bold mono">AEFD-7695-64FA</span> <span class="text-[10px] text-slate-500 font-normal">(AI Studio / Antigravity StreamGenerateContent &amp; GenerateContent)</span></td>
                <td class="${escapeHtml(tdGrossClass)}">${fmtEur(gGross)} <span class="text-[10px] text-slate-400">(${fmtUsd(gGross)})</span></td>
                <td class="py-2 px-3 text-right mono text-emerald-700 font-semibold">-${fmtEur(gSav)} <span class="text-[10px] text-slate-400">(Context Caching)</span></td>
                <td class="py-2 px-3 text-right mono font-extrabold text-emerald-700">${fmtEur(gNet)} (${fmtUsd(gNet)})</td>
              </tr>
              ${infraRowsHtml}
              <tr class="bg-slate-50 font-extrabold text-xs">
                <td class="py-2.5 px-3 text-slate-900">PROJECT INVOICE TOTAL (${escapeHtml(2 + infList.length)} SERVICES)</td>
                <td class="py-2.5 px-3 text-right mono text-slate-800">${fmtEur(billGross)} (${fmtUsd(billGross)})</td>
                <td class="py-2.5 px-3 text-right mono text-emerald-700">-${fmtEur(billSav)}</td>
                <td class="py-2.5 px-3 text-right mono text-[#0F2A4A] text-sm">${fmtEur(billNet)} (${fmtUsd(billNet)})</td>
              </tr>
            </tbody>
          </table>
          </div>
        </div>

        <div class="jt-dash-card bg-blue-50/60 rounded-xl border border-blue-200 p-4 space-y-2.5">
          <div class="${escapeHtml(CLS_FLEX_WRAP_BETWEEN)}">
            <h4 class="jt-drawer__section-title text-xs font-bold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Project Cost Reconciliation by Identity (${fmtUsd(projTotalCost)} / ${fmtEur(projTotalCost)})</h4>
            <span class="text-[11px] text-slate-600">Exact sum: <b>OAuth Users (${escapeHtml(pctOauth)}%)</b> + <b>API Keys (${escapeHtml(pctKeys)}%)</b> + <b>Service Account (${escapeHtml(pctSa)}%)</b></span>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div class="p-3 rounded-lg bg-white border border-purple-200">
              <div class="${escapeHtml(CLS_FLEX_BETWEEN)}">
                <span class="text-xs font-bold text-purple-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> Human Users &amp; OAuth (Vertex AI)</span>
                <span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 text-[10px] font-bold mono">${escapeHtml(pctOauth)}%</span>
              </div>
              <div class="text-lg font-extrabold text-slate-900 mono mt-1">${fmtUsd(oauthCost)} <span class="text-xs font-bold text-slate-500">(${fmtEur(oauthCost)})</span></div>
              <div class="text-[10px] text-slate-500 mt-0.5">${fmtNum(oauthCalls)} calls · ${fmtTok(oauthTokens)} tokens · <b>${usersList.length} users tracked</b></div>
            </div>
            <div class="p-3 rounded-lg bg-white border border-amber-200">
              <div class="${escapeHtml(CLS_FLEX_BETWEEN)}">
                <span class="text-xs font-bold text-amber-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> API Keys (AI Studio / Antigravity)</span>
                <span class="jt-chip jt-chip--amber px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 text-[10px] font-bold mono">${escapeHtml(pctKeys)}%</span>
              </div>
              <div class="text-lg font-extrabold text-slate-900 mono mt-1">${fmtUsd(apiKeysCost)} <span class="text-xs font-bold text-slate-500">(${fmtEur(apiKeysCost)})</span></div>
              <div class="text-[10px] text-slate-500 mt-0.5">${fmtNum(apiKeysCallsOk)} OK (${fmtNum(apiKeysCallsFailed)} err $0) · ${fmtTok(apiKeysTokens)} tok</div>
            </div>
            <div class="p-3 rounded-lg bg-white border border-blue-200">
              <div class="${escapeHtml(CLS_FLEX_BETWEEN)}">
                <span class="text-xs font-bold text-blue-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Service Accounts</span>
                <span class="jt-chip jt-chip--blue px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px] font-bold mono">${escapeHtml(pctSa)}%</span>
              </div>
              <div class="text-lg font-extrabold text-slate-900 mono mt-1">${fmtUsd(saCost)} <span class="text-xs font-bold text-slate-500">(${fmtEur(saCost)})</span></div>
              <div class="text-[10px] text-slate-500 mt-0.5">${fmtNum(saCalls)} calls · ${fmtTok(saTokens)} tokens</div>
            </div>
          </div>
        </div>

        <div class="jt-table-panel bg-white rounded-xl border border-slate-200 p-4 space-y-2">
          <div class="${escapeHtml(CLS_FLEX_BETWEEN)}">
            <h4 class="jt-drawer__section-title text-xs font-bold uppercase tracking-wider text-purple-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> Costs and Usage per User (OAuth + Personal API Keys: ${usersList.length} Users)</h4>
            <span class="text-[11px] text-slate-500">Includes Agentspace, Code Assist, Notebook and user-created API Keys</span>
          </div>
          <div class="max-h-72 overflow-y-auto">
            <table class="jt-table w-full text-left border-collapse">
              <thead>
                <tr class="border-b border-slate-200 text-[10px] uppercase text-slate-400 sticky top-0 bg-white">
                  <th class="py-2">User &amp; API Keys</th>
                  <th class="py-2">Operations</th>
                  <th class="py-2 text-right">Calls</th>
                  <th class="py-2 text-right">Token LLM</th>
                  <th class="py-2 text-right">OAuth + API Key</th>
                  <th class="py-2 text-right">Total ($ / €)</th>
                </tr>
              </thead>
              <tbody>${usersRows}</tbody>
            </table>
          </div>
        </div>

        <div class="jt-table-panel bg-white rounded-xl border border-slate-200 p-4 space-y-2">
          <h4 class="jt-drawer__section-title text-xs font-bold uppercase tracking-wider text-slate-500"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> AI Models Used in the Project</h4>
          <table class="jt-table w-full text-left border-collapse">
            <thead>
              <tr class="border-b border-slate-200 text-[10px] uppercase text-slate-400">
                <th class="py-2">Model</th>
                <th class="py-2">Used by</th>
                <th class="py-2">Region</th>
                <th class="py-2 text-right">Input</th>
                <th class="py-2 text-right">Output</th>
                <th class="py-2 text-right">Cost ($)</th>
              </tr>
            </thead>
            <tbody>${modelsRows}</tbody>
          </table>
        </div>

        <div class="jt-table-panel bg-white rounded-xl border border-slate-200 p-4 space-y-2">
          <div class="${escapeHtml(CLS_FLEX_BETWEEN)}">
            <h4 class="jt-drawer__section-title text-xs font-bold uppercase tracking-wider text-amber-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Cataloged API Keys (Including Deleted Keys with Traffic)</h4>
            <span class="text-[11px] text-slate-500">Tokens and costs calculated from actual HTTP bytes (<code class="mono">request_sizes</code>/<code class="mono">response_sizes</code>) with Context Caching discount</span>
          </div>
          <table class="jt-table w-full text-left border-collapse">
            <thead>
              <tr class="border-b border-slate-200 text-[10px] uppercase text-slate-400">
                <th class="py-2">Key Name, ID &amp; Creator</th>
                <th class="py-2">API Restrictions</th>
                <th class="py-2 text-right">200 OK Calls</th>
                <th class="py-2 text-right">Failed (4xx/5xx)</th>
                <th class="py-2 text-right">Tokens &amp; HTTP Payload</th>
                <th class="py-2 text-right">Net Cost ($ / €)</th>
              </tr>
            </thead>
            <tbody>${keysRows}</tbody>
          </table>
        </div>

        ${saSectionHtml}

        ${spFindingsHtml}

        <div class="space-y-2">
          <h4 class="jt-drawer__section-title text-xs font-bold uppercase tracking-wider text-slate-500"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> IAM Permissions Diagnostics (${escapeHtml(perms.iamGrantedCount || 0)}/${escapeHtml(perms.iamTotalCount || 12)})</h4>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2.5">${areasGridHtml}</div>
        </div>
      `);
    }

    function openProjectModal(projectId) {
      const p = (globalScanData.projects || []).find(x => x.projectId === projectId);
      if (!p) return;

      document.getElementById('modal-proj-title').textContent = p.name === p.projectId ? p.name : `${p.name} (${p.projectId})`;
      const body = document.getElementById('modal-proj-body');
      const useScopeBtn = document.getElementById('modal-proj-use-scope-btn');
      if (useScopeBtn) {
        useScopeBtn.onclick = function() {
          // The scope selector is #filter-project (driven by onProjectFilterChanged); there is no #project-filter.
          const curSel = document.getElementById('filter-project');
          if (typeof selectSingleProjectFilter === 'function') {
            // selectSingleProjectFilter toggles: do nothing when the project is already the scope
            if (!curSel || curSel.value !== p.projectId) selectSingleProjectFilter(p.projectId);
          } else {
            const sel = document.getElementById('filter-project');
            if (sel) {
              sel.value = p.projectId;
              if (typeof onProjectFilterChanged === 'function') onProjectFilterChanged();
            }
          }
          closeProjectModal();
        };
      }

      const perms = p.permissions || {};
      const areas = perms.areas || {};
      const monArea = areas.monitoring || { granted: true };
      const keysArea = areas.apiKeys || { granted: true };

      const areasGridHtml = _buildProjectModalAreasGridHtml(areas);
      const idCosts = _computeProjectIdentityCosts(p);

      const modalCredMap = {};
      (p.credentialsUsage || []).forEach(c => { modalCredMap[c.credentialId] = c; });
      const modalDailyKeys = Object.keys(p.dailySeries || {}).sort();
      const modalTodayStr = modalDailyKeys.length > 0 ? modalDailyKeys[modalDailyKeys.length - 1] : '';
      const modalYestStr = modalDailyKeys.length > 1 ? modalDailyKeys[modalDailyKeys.length - 2] : '';

      const { modelsRows, usersList, usersRows } = _buildProjectModalModelsAndUsersRows(
        p, monArea, modalCredMap, modalTodayStr, modalYestStr
      );
      const { keysRows, saSectionHtml, sp, spFindingsHtml } = _buildProjectModalKeysAndSaHtml(
        p, keysArea, modalCredMap, modalTodayStr, modalYestStr
      );

      _renderProjectModalBody(body, p, {
        perms, monArea, areasGridHtml, idCosts,
        modelsRows, usersList, usersRows, keysRows, saSectionHtml, sp, spFindingsHtml
      });

      document.getElementById('project-modal').classList.remove('hidden');
      if (typeof window.jtActivateDrawerFocus === 'function') window.jtActivateDrawerFocus('project-modal');
      setTimeout(enhanceAllTablesWithFrontendSortAndFilter, 30);
    }

    function closeProjectModal() {
      document.getElementById('project-modal').classList.add('hidden');
      if (typeof window.jtDeactivateDrawerFocus === 'function') window.jtDeactivateDrawerFocus('project-modal');
    }

    // =========================================================================
    // MODALE ISPEZIONE 360° SINGOLO UTENTE (openUserModal)
    // =========================================================================
    window.openUserModal = function(userEmail) {
      const cleanEmail = String(userEmail || '').trim().toLowerCase();
      if (!cleanEmail || !globalScanData) return;

      const modalEl = document.getElementById('user-modal');
      const titleEl = document.getElementById('modal-user-title');
      const subEl = document.getElementById('modal-user-subtitle');
      const bodyEl = document.getElementById('modal-user-body');
      if (!modalEl || !bodyEl) return;

      const domain = cleanEmail.includes('@') ? cleanEmail.split('@')[1] : 'unknown';
      const activeAccountEmail = (typeof currentActiveAccount === 'string' && currentActiveAccount.includes('@')) ? currentActiveAccount.toLowerCase() : '';
      const activeBaseDomain = activeAccountEmail ? activeAccountEmail.split('@')[1].replace(/^external\./, '') : '';
      const isInternal = activeBaseDomain ? (domain === activeBaseDomain || domain.endsWith('.' + activeBaseDomain)) : !['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com'].includes(domain);
      let userType = isInternal ? 'INTERNAL_USER' : 'EXTERNAL_USER';

      let totalCostUsd = 0, oauthCostUsd = 0, apiKeysCostUsd = 0, vertexOauthCostUsd = 0;
      let todayCostUsd = 0, yesterdayCostUsd = 0;
      let todayTokens = 0, yesterdayTokens = 0;
      let totalInteractions = 0, assistTurns = 0, searchQueries = 0, fileOps = 0;
      let codeAssistCalls = 0, codeAssistLines = 0, codeAssistAccSum = 0, codeAssistAccCnt = 0;
      let vertexOauthCalls = 0, vertexOauthTokens = 0;
      let notebookActivities = 0, apiKeysCalls = 0, apiKeysBytesIn = 0, apiKeysBytesOut = 0;
      let loggedInputTokens = 0, loggedOutputTokens = 0, loggedTotalTokens = 0, attributedTokens = 0, apiKeysTotalTokens = 0;
      let seatMonthlyUsd = 0;
      let firstSeen = null, lastSeen = null;

      const ideClientsSet = new Set();
      const ideVersionsSet = new Set();
      const ideLangsSet = new Set();
      const ideWorkspacesSet = new Set();
      const methodsSet = new Set();
      const enginesSet = new Set();
      const dataStoresSet = new Set();

      const perProjectRows = [];
      const userApiKeys = [];
      const userOauthClients = [];
      const userRawResources = [];

      const timelineDates = Array.isArray(globalScanData.timeline) ? globalScanData.timeline.map(t => t.date).filter(Boolean).sort() : [];
      const globalTodayStr = timelineDates.length > 0 ? timelineDates[timelineDates.length - 1] : '';
      const globalYestStr = timelineDates.length > 1 ? timelineDates[timelineDates.length - 2] : '';

      (globalScanData.projects || []).forEach(p => {
        const credMap = {};
        (p.credentialsUsage || []).forEach(c => { credMap[c.credentialId] = c; });
        const pDailyKeys = Object.keys(p.dailySeries || {}).sort();
        const pTodayStr = pDailyKeys.length > 0 ? pDailyKeys[pDailyKeys.length - 1] : globalTodayStr;
        const pYestStr = pDailyKeys.length > 1 ? pDailyKeys[pDailyKeys.length - 2] : globalYestStr;

        // 1. Cerca in p.usersUsage
        (p.usersUsage || []).forEach(u => {
          if (String(u.userEmail || '').trim().toLowerCase() !== cleanEmail) return;
          if (u.userType === 'EXTERNAL_USER') userType = 'EXTERNAL_USER';
          else if (u.userType === 'OAUTH_WORKLOAD') userType = 'OAUTH_WORKLOAD';

          const uOauthCost = (u.oauthCostUsd !== undefined && u.oauthCostUsd !== null) ? u.oauthCostUsd : Math.max(0, (u.estimatedCostUsd || 0) - (u.apiKeysCostUsd || 0));
          const uKeyCost = u.apiKeysCostUsd || 0;
          const uVOauthCost = u.vertexOauthCostUsd || 0;
          const uVOauthCalls = u.vertexOauthCalls || 0;
          const uVOauthToks = u.vertexOauthTokens || 0;
          const uTotCost = u.estimatedCostUsd || (uOauthCost + uKeyCost);

          totalCostUsd += uTotCost;
          oauthCostUsd += uOauthCost;
          vertexOauthCostUsd += uVOauthCost;
          apiKeysCostUsd += uKeyCost;
          todayCostUsd += (u.todayCostUsd || ((u.vertexOauthTodayCostUsd || 0) + (u.apiKeysTodayCostUsd || 0)));
          yesterdayCostUsd += (u.yesterdayCostUsd || ((u.vertexOauthYesterdayCostUsd || 0) + (u.apiKeysYesterdayCostUsd || 0)));
          todayTokens += (u.todayTokens || ((u.vertexOauthTodayTokens || 0) + (u.apiKeysTodayTokens || 0)));
          yesterdayTokens += (u.yesterdayTokens || ((u.vertexOauthYesterdayTokens || 0) + (u.apiKeysYesterdayTokens || 0)));

          totalInteractions += (u.totalInteractions || 0);
          assistTurns += (u.assistTurns || 0);
          searchQueries += (u.searchQueries || 0);
          fileOps += (u.fileOps || 0);
          codeAssistCalls += (u.codeAssistCalls || 0);
          codeAssistLines += (u.codeAssistAcceptedLines || 0);
          vertexOauthCalls += uVOauthCalls;
          vertexOauthTokens += uVOauthToks;
          if ((u.codeAssistAcceptanceRatePct || 0) > 0) {
            codeAssistAccSum += u.codeAssistAcceptanceRatePct;
            codeAssistAccCnt++;
          }
          notebookActivities += (u.notebookActivities || 0);
          apiKeysCalls += (u.apiKeysCalls || 0);
          apiKeysBytesIn += (u.apiKeysRequestBytes || 0);
          apiKeysBytesOut += (u.apiKeysResponseBytes || 0);
          loggedInputTokens += (u.loggedInputTokens || 0);
          loggedOutputTokens += (u.loggedOutputTokens || 0);
          loggedTotalTokens += (u.loggedTotalTokens || 0);
          attributedTokens += (u.attributedTokens || 0);
          apiKeysTotalTokens += (u.apiKeysTotalTokens || 0);

          if (u.firstSeen && (!firstSeen || u.firstSeen < firstSeen)) firstSeen = u.firstSeen;
          if (u.lastSeen && (!lastSeen || u.lastSeen > lastSeen)) lastSeen = u.lastSeen;

          (u.ideClients || []).forEach(x => ideClientsSet.add(x));
          (u.ideVersions || []).forEach(x => ideVersionsSet.add(x));
          (u.codeAssistLanguages || []).forEach(x => ideLangsSet.add(x));
          (u.codeAssistWorkspaces || u.ideWorkspaces || []).forEach(x => ideWorkspacesSet.add(x));
          (u.methods || []).forEach(x => methodsSet.add(x));
          (u.engines || []).forEach(x => enginesSet.add(x));
          (u.dataStores || []).forEach(x => dataStoresSet.add(x));
          (u.oauthClientsDetails || []).forEach(od => {
            userOauthClients.push({
              ...od,
              projectId: p.projectId,
              projectName: p.name || p.projectId
            });
          });

          perProjectRows.push({
            projectId: p.projectId,
            projectName: p.name || p.projectId,
            interactions: (u.totalInteractions || 0) + (u.apiKeysCalls || 0),
            assistTurns: u.assistTurns || 0,
            searchQueries: u.searchQueries || 0,
            codeAssistCalls: u.codeAssistCalls || 0,
            vertexOauthCalls: uVOauthCalls,
            vertexOauthCostUsd: uVOauthCost,
            notebookActivities: u.notebookActivities || 0,
            apiKeysCalls: u.apiKeysCalls || 0,
            tokens: (u.loggedTotalTokens || 0) + uVOauthToks + (u.apiKeysTotalTokens || 0) || (u.attributedTokens || 0),
            oauthCostUsd: uOauthCost,
            apiKeysCostUsd: uKeyCost,
            totalCostUsd: uTotCost,
            engines: u.engines || [],
            dataStores: u.dataStores || [],
            methods: u.methods || [],
            lastSeen: u.lastSeen || ''
          });
        });

        // 2. Cerca API Keys create da questo utente in p.apiKeys
        (p.apiKeys || []).forEach(k => {
          if (String(k.ownerEmail || '').trim().toLowerCase() !== cleanEmail) return;
          const cObj = credMap[`apikey:${k.uid}`] || {};
          const dS = cObj.dailySeries || {};
          const tB = dS[k.todayDate || pTodayStr] || {};
          const yB = dS[k.yesterdayDate || pYestStr] || {};
          const kTodayCost = k.todayCostUsd !== undefined ? k.todayCostUsd : (tB.costUsd || 0);
          const kYestCost = k.yesterdayCostUsd !== undefined ? k.yesterdayCostUsd : (yB.costUsd || 0);
          const kTodayTok = k.todayTokens !== undefined ? k.todayTokens : (tB.tokens || 0);
          const kYestTok = k.yesterdayTokens !== undefined ? k.yesterdayTokens : (yB.tokens || 0);
          userApiKeys.push({
            ...k,
            projectId: p.projectId,
            projectName: p.name || p.projectId,
            todayCostUsd: kTodayCost,
            yesterdayCostUsd: kYestCost,
            todayTokens: kTodayTok,
            yesterdayTokens: kYestTok
          });
        });

        // 3. Cerca Risorse AI / Notebook / Schedule Colab appartenenti o eseguite da questo utente
        (p.deployedAiResources || []).forEach(r => {
          const rOwner = String(r.user || r.ownerEmail || '').trim().toLowerCase();
          const rDet = String(r.details || '').toLowerCase();
          if (rOwner === cleanEmail || rDet.includes(cleanEmail)) {
            userRawResources.push({
              ...r,
              projectId: p.projectId,
              projectName: p.name || p.projectId,
              user: r.user || r.ownerEmail || userEmail
            });
          }
        });
      });

      // Se l'utente aveva solo API Keys o solo Notebook ma non era in p.usersUsage, ricalcola i totali dalle API Keys
      if (perProjectRows.length === 0 && userApiKeys.length > 0) {
        userApiKeys.forEach(k => {
          const kCost = k.estimatedCostUsd || 0;
          totalCostUsd += kCost;
          apiKeysCostUsd += kCost;
          todayCostUsd += (k.todayCostUsd || 0);
          yesterdayCostUsd += (k.yesterdayCostUsd || 0);
          todayTokens += (k.todayTokens || 0);
          yesterdayTokens += (k.yesterdayTokens || 0);
          apiKeysCalls += (k.inferenceRequests || k.requests || 0);
          apiKeysTotalTokens += (k.totalTokens || 0);
        });
      }

      const groupedUserResources = groupRepeatedAiResources(userRawResources);
      const avgAcceptancePct = codeAssistAccCnt > 0 ? Math.round((codeAssistAccSum / codeAssistAccCnt) * 10) / 10 : 0;
      const totCombinedTokens = loggedTotalTokens + vertexOauthTokens + apiKeysTotalTokens || attributedTokens;

      const safeUserEmail = escapeHtml(userEmail);
      const safeDomain = escapeHtml(domain);
      if (titleEl) {
        const badgeHtml = userType === 'OAUTH_WORKLOAD'
          ? '<span class="jt-badge jt-badge--purple px-2.5 py-0.5 rounded-full text-[11px] font-extrabold border bg-indigo-50 text-indigo-800 border-indigo-200"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> OAUTH WORKLOAD</span>'
          : `<span class="jt-badge px-2.5 py-0.5 rounded-full text-[11px] font-extrabold border ${userType === 'EXTERNAL_USER' ? 'jt-badge--amber bg-amber-100 text-amber-900 border-amber-300' : 'jt-badge--green bg-emerald-50 text-emerald-700 border-emerald-200'}">
              ${userType === 'EXTERNAL_USER' ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> EXTERNAL GUEST' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> INTERNAL USER (@' + safeDomain + ')'}
            </span>`;
        setSafeHtml(titleEl, `
          <span>${safeUserEmail}</span>
          ${badgeHtml}
        `);
      }
      if (subEl) {
        setSafeHtml(subEl, `
          360° Multi-Project Inspection · Active on <b>${Math.max(perProjectRows.length, new Set([...perProjectRows.map(x => x.projectId), ...userApiKeys.map(x => x.projectId), ...userRawResources.map(x => x.projectId)]).size)} projects</b>
          ${firstSeen ? ` · First activity: <b class="mono">${escapeHtml(firstSeen.replace('T', ' ').slice(0, 16))}</b>` : ''}
          ${lastSeen ? ` · Last activity: <b class="mono">${escapeHtml(lastSeen.replace('T', ' ').slice(0, 16))}</b>` : ''}
        `);
      }

      // Costruzione tabella Progetti & App Gemini Enterprise accedute
      const projRowsHtml = perProjectRows.length > 0
        ? perProjectRows.sort((a, b) => b.totalCostUsd - a.totalCostUsd || b.interactions - a.interactions).map(pr => {
            const engBadges = (pr.engines || []).map(e => `<span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-800 border border-indigo-200 text-[10px] mono font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> ${escapeHtml(e)}</span>`).join(' ');
            const dsBadges = (pr.dataStores || []).map(d => `<span class="jt-chip jt-chip--gray px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200 text-[10px] mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${escapeHtml(d)}</span>`).join(' ');
            const opsBreak = [];
            if (pr.vertexOauthCalls > 0) opsBreak.push(`<svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> ${escapeHtml(fmtNum(pr.vertexOauthCalls))} Vertex AI OAuth`);
            if (pr.assistTurns > 0) opsBreak.push(`<svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${escapeHtml(fmtNum(pr.assistTurns))} Chat/Assist`);
            if (pr.searchQueries > 0) opsBreak.push(`<svg class="jt-ico" aria-hidden="true"><use href="#ico-search"/></svg> ${escapeHtml(fmtNum(pr.searchQueries))} Search`);
            if (pr.codeAssistCalls > 0) opsBreak.push(`<svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> ${escapeHtml(fmtNum(pr.codeAssistCalls))} IDE Code Assist`);
            if (pr.notebookActivities > 0) opsBreak.push(`<svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${escapeHtml(fmtNum(pr.notebookActivities))} Notebook`);
            if (pr.apiKeysCalls > 0) opsBreak.push(`<svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> ${escapeHtml(fmtNum(pr.apiKeysCalls))} API Key calls`);
            return `
              <tr class="hover:bg-slate-50 border-b border-slate-100">
                <td class="py-2.5 px-3" data-sort-val="${escapeHtml(pr.projectName)}">
                  <div class="font-bold text-[#0F2A4A] cursor-pointer underline" data-jt-click="closeUserModal(); openProjectModal(${jsArg(pr.projectId)})">${escapeHtml(pr.projectName)}</div>
                  <div class="text-[10px] text-slate-400 mono">${escapeHtml(pr.projectId)}</div>
                </td>
                <td class="py-2.5 px-3 text-xs text-slate-700">
                  <div>${opsBreak.join(' · ') || 'AI Activity'}</div>
                  ${(engBadges || dsBadges) ? `<div class="mt-1 flex flex-wrap gap-1">${engBadges} ${dsBadges}</div>` : ''}
                </td>
                <td class="py-2.5 px-3 text-right mono font-bold text-slate-800" data-sort-val="${escapeHtml(pr.interactions)}">${fmtNum(pr.interactions)}</td>
                <td class="py-2.5 px-3 text-right mono text-slate-700" data-sort-val="${escapeHtml(pr.tokens)}">${fmtTok(pr.tokens)}</td>
                <td class="py-2.5 px-3 text-right mono text-purple-700 font-semibold" data-sort-val="${escapeHtml(pr.oauthCostUsd)}">${fmtUsd(pr.oauthCostUsd)}</td>
                <td class="py-2.5 px-3 text-right mono text-amber-800 font-semibold" data-sort-val="${escapeHtml(pr.apiKeysCostUsd)}">${fmtUsd(pr.apiKeysCostUsd)}</td>
                <td class="py-2.5 px-3 text-right mono font-extrabold text-emerald-700" data-sort-val="${escapeHtml(pr.totalCostUsd)}">${fmtUsd(pr.totalCostUsd)} <span class="text-[10px] text-slate-500">(${fmtEur(pr.totalCostUsd)})</span></td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="7" class="py-6 text-center text-slate-400">No direct project logs found for this user.</td></tr>`;

      // Costruzione sezione IDE / Code Assist / Antigravity (sempre visibile nella Scheda 360° per mostrare utilizzo e costo Antigravity / IDE)
      const ideCardLblClass = ['text-[10px]', 'font-bold', 'uppercase', 'text-slate-400'].join(' ');
      const caVarCostUsd = perProjectRows.reduce((s, pr) => s + ((pr.codeAssistCalls > 0 && pr.assistTurns === 0 && pr.searchQueries === 0) ? Math.max(0, pr.oauthCostUsd - (pr.vertexOauthCostUsd || 0)) : 0), 0);
      const ideTotalDevCostUsd = caVarCostUsd + vertexOauthCostUsd + apiKeysCostUsd;
      const ideTotalDevCalls = codeAssistCalls + vertexOauthCalls + apiKeysCalls;
      const ideTotalDevTokens = apiKeysTotalTokens + vertexOauthTokens + (codeAssistCalls > 0 && assistTurns === 0 && searchQueries === 0 ? (loggedTotalTokens || Math.max(0, attributedTokens - vertexOauthTokens)) : 0);
      const hasIdeActivity = ideTotalDevCalls > 0 || ideClientsSet.size > 0 || ideLangsSet.size > 0 || ideWorkspacesSet.size > 0;
      const ideBadgeLabelHtml = vertexOauthCalls > 0
        ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Antigravity IDE (Vertex AI OAuth)' + (apiKeysCalls > 0 ? ' + <svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> API Key' : '')
        : (codeAssistCalls > 0 && apiKeysCalls > 0
          ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Code Assist IDE + <svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Antigravity / API Key'
          : (codeAssistCalls > 0
            ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> GCP Log: cloudaicompanion.googleapis.com'
            : (apiKeysCalls > 0
              ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Antigravity / AI Studio Key Calls'
              : 'No GCP usage ($0.00) · Google Login / Web App only')));
      const ideSectionHtml = `
        <div class="jt-dash-card ${hasIdeActivity ? 'bg-indigo-50/50 border-indigo-200' : 'bg-slate-50 border-slate-200'} rounded-xl border p-4 space-y-3">
          <div class="${escapeHtml(CLS_FLEX_WRAP_BETWEEN)}">
            <div>
              <h4 class="jt-drawer__section-title text-xs font-extrabold uppercase tracking-wider text-indigo-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Antigravity, Vertex AI OAuth, Gemini Code Assist &amp; IDE Telemetry (Usage &amp; Cost)</h4>
              <p class="text-[11px] text-indigo-800">Tracking of <b>Antigravity IDE via Vertex AI OAuth</b> (<code>aiplatform.googleapis.com</code>), <b>AI Studio API Key</b> (<code>generativelanguage.googleapis.com</code>) and IDE plugin <b>Gemini Code Assist</b> (<code>cloudaicompanion.googleapis.com</code>)</p>
            </div>
            <span class="jt-badge px-2.5 py-1 rounded-full ${hasIdeActivity ? 'jt-badge--purple bg-indigo-100 text-indigo-900 border-indigo-300' : 'jt-badge--gray bg-slate-200 text-slate-600 border-slate-300'} border text-[11px] font-extrabold mono">
              ${ideBadgeLabelHtml}
            </span>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-5 gap-2.5 text-xs">
            <div class="p-3 rounded-lg bg-white border border-indigo-200 shadow-sm">
              <div class="${escapeHtml(ideCardLblClass)}">GCP Antigravity / IDE Cost</div>
              <div class="text-lg font-extrabold ${ideTotalDevCostUsd > 0 ? 'text-indigo-900' : 'text-slate-400'} mono mt-0.5">${fmtUsd(ideTotalDevCostUsd)} <span class="text-xs text-slate-500">(${fmtEur(ideTotalDevCostUsd)})</span></div>
              <div class="text-[10px] text-slate-500 mt-0.5">Vertex OAuth: <b>${fmtUsd(vertexOauthCostUsd)}</b> · Key: <b>${fmtUsd(apiKeysCostUsd)}</b> · CA: <b>${fmtUsd(caVarCostUsd)}</b></div>
            </div>
            <div class="p-3 rounded-lg bg-white border border-indigo-100">
              <div class="${escapeHtml(ideCardLblClass)}">Development Usage &amp; Tokens</div>
              <div class="text-lg font-extrabold text-indigo-900 mono mt-0.5">${fmtNum(ideTotalDevCalls)} <span class="text-xs font-semibold text-slate-500">call</span></div>
              <div class="text-[10px] text-slate-500">Token IDE/API: <b>${fmtTok(ideTotalDevTokens)}</b></div>
            </div>
            <div class="p-3 rounded-lg bg-white border border-indigo-100">
              <div class="${escapeHtml(ideCardLblClass)}">Code Assist IDE Plugin</div>
              <div class="text-lg font-extrabold text-indigo-900 mono mt-0.5">${fmtNum(codeAssistCalls)} <span class="text-xs font-semibold text-slate-500">call</span></div>
              <div class="text-[10px] text-slate-500">Accepted lines: <b>${fmtNum(codeAssistLines)}</b> (${escapeHtml(avgAcceptancePct)}%)</div>
            </div>
            <div class="p-3 rounded-lg bg-white border border-indigo-100">
              <div class="${escapeHtml(ideCardLblClass)}">IDEs &amp; Channels Detected</div>
              <div class="text-xs font-bold text-slate-800 mono mt-1">${escapeHtml(Array.from(ideClientsSet).join(', ') || (apiKeysCalls > 0 ? 'Antigravity / AI Studio Key (Stream/REST)' : 'No active GCP plugin'))}</div>
              ${ideVersionsSet.size > 0 ? `<div class="text-[10px] text-slate-400 mono mt-0.5">Ver: ${escapeHtml(Array.from(ideVersionsSet).slice(0, 4).join(', '))}</div>` : ''}
            </div>
            <div class="p-3 rounded-lg bg-white border border-indigo-100">
              <div class="${escapeHtml(ideCardLblClass)}">Languages &amp; Workspaces</div>
              <div class="text-xs font-bold text-indigo-800 mono mt-1">${escapeHtml(Array.from(ideLangsSet).join(', ') || (apiKeysCalls > 0 ? 'Prompt / Multi-lang via API Key' : '—'))}</div>
              <div class="text-[10px] text-slate-500 mono mt-0.5">${escapeHtml(Array.from(ideWorkspacesSet).slice(0, 3).join(', ') || (apiKeysCalls > 0 ? `${userApiKeys.length} active API Keys` : 'Google Login Quota ($0 GCP)'))}</div>
            </div>
          </div>
        </div>
      `;

      // Costruzione sezione Notebook / Colab Enterprise (Raggruppati + Storico espandibile delle 88 esecuzioni!)
      const nbSectionHtml = groupedUserResources.length > 0 ? `
        <div class="jt-table-panel bg-white rounded-xl border border-purple-200 p-4 space-y-3">
          <div class="${escapeHtml(CLS_FLEX_WRAP_BETWEEN)}">
            <div>
              <h4 class="jt-drawer__section-title text-xs font-extrabold uppercase tracking-wider text-purple-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Vertex AI Notebooks &amp; Scheduled Colab Enterprise Jobs (${groupedUserResources.length} Groups · ${userRawResources.length} Total Runs)</h4>
              <p class="text-[11px] text-slate-500">Recurring scheduled jobs are grouped into a single row; click <b>Show/Hide Full History</b> to inspect every individual run.</p>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table class="jt-table w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-slate-200 text-[10px] font-bold uppercase text-slate-500 bg-slate-50">
                  <th class="py-2 px-3">Resource Name / Scheduled Job</th>
                  <th class="py-2 px-3">Type &amp; Run Count</th>
                  <th class="py-2 px-3">Project &amp; Region</th>
                  <th class="py-2 px-3">Details / GCS Output</th>
                  <th class="py-2 px-3">First → Last Run</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100">
                ${groupedUserResources.map((gr, idx) => {
                  const runCnt = gr._runCount || 1;
                  const succCnt = gr._succeededCount || 0;
                  const failCnt = gr._failedCount || 0;
                  const runsList = gr._groupedRuns || [];
                  const firstTs = gr._firstTime ? gr._firstTime.replace('T', ' ').slice(0, 16) : '—';
                  const lastTs = (gr._latestTime || gr.updateTime || gr.createTime || '').replace('T', ' ').slice(0, 16) || '—';
                  const histId = `user-nb-history-${idx}`;
                  return `
                    <tr class="hover:bg-purple-50/30 align-top">
                      <td class="py-2.5 px-3">
                        <div class="font-bold text-slate-900">${escapeHtml(gr.displayName)}</div>
                        <div class="text-[10px] text-slate-400 mono">${escapeHtml(runCnt > 1 ? `Latest Job ID: ${gr.resourceId}` : (gr.resourceId || ''))}</div>
                        ${runCnt > 1 ? `
                          <button type="button" data-jt-click="toggleHiddenById(${jsArg(histId)})" class="mt-1 px-2 py-0.5 rounded bg-purple-100 hover:bg-purple-200 text-purple-900 border border-purple-300 text-[10px] font-extrabold cursor-pointer transition">
                            <svg class="jt-ico" aria-hidden="true"><use href="#ico-search"/></svg> Show/Hide Full History (${escapeHtml(runCnt)} runs) ▾
                          </button>
                          <div id="${escapeHtml(histId)}" class="hidden mt-2 max-h-48 overflow-y-auto rounded-lg border border-purple-200 bg-slate-50 p-2 space-y-1">
                            <div class="text-[10px] font-extrabold text-purple-900 uppercase">Full history of the ${escapeHtml(runCnt)} runs:</div>
                            ${runsList.map((runItem, rIdx) => `
                              <div class="flex items-center justify-between gap-2 text-[10px] mono border-b border-slate-200/70 pb-0.5">
                                <span class="font-bold text-slate-700">#${runCnt - rIdx} · ${escapeHtml((runItem.updateTime || runItem.createTime || '').replace('T', ' ').slice(0, 19))}</span>
                                <span class="text-slate-500 truncate max-w-[220px]">${escapeHtml(runItem.resourceId)}</span>
                                <span class="jt-chip px-1.5 py-0.2 rounded ${String(runItem.state || '').includes('SUCCEEDED') ? 'jt-chip--green bg-emerald-50 text-emerald-700 font-bold' : 'jt-chip--gray bg-slate-100 text-slate-600'}">${escapeHtml(runItem.state || 'OK')}</span>
                              </div>
                            `).join('')}
                          </div>
                        ` : ''}
                      </td>
                      <td class="py-2.5 px-3">
                        <div class="font-bold text-purple-900">${escapeHtml(gr.typeLabel || gr.resourceType)}</div>
                        ${runCnt > 1
                          ? `<span class="jt-badge jt-badge--purple mt-1 inline-block px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-800 border border-indigo-200 text-[10px] font-extrabold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> ${escapeHtml(runCnt)} run (${escapeHtml(succCnt)} OK${escapeHtml(failCnt > 0 ? ` · ${failCnt} err` : '')})</span>`
                          : `<span class="text-[10px] text-emerald-700 font-semibold">${escapeHtml(gr.state || 'ACTIVE')}</span>`}
                      </td>
                      <td class="py-2.5 px-3 mono">
                        <div class="font-bold text-[#0F2A4A] cursor-pointer underline" data-jt-click="closeUserModal(); openProjectModal(${jsArg(gr.projectId)})">${escapeHtml(gr.projectId)}</div>
                        <div class="text-[10px] text-slate-400">${escapeHtml(gr.location || 'europe-west1')}</div>
                      </td>
                      <td class="py-2.5 px-3 text-[11px] text-slate-600 max-w-xs break-all">${escapeHtml(gr.details || '—')}</td>
                      <td class="py-2.5 px-3 mono text-[11px] text-slate-500 whitespace-nowrap">
                        ${runCnt > 1 ? `<div>Latest: <b class="text-slate-800">${escapeHtml(lastTs)}</b></div><div class="text-[10px] text-slate-400">First: ${escapeHtml(firstTs)}</div>` : escapeHtml(lastTs)}
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        </div>
      ` : '';

      // Costruzione sezione Client OAuth Vertex AI / Antigravity attribuiti all'utente
      const oauthClientsSectionHtml = userOauthClients.length > 0 ? `
        <div class="jt-table-panel bg-white rounded-xl border border-indigo-200 p-4 space-y-3">
          <div class="${escapeHtml(CLS_FLEX_WRAP_BETWEEN)}">
            <div>
              <h4 class="jt-drawer__section-title text-xs font-extrabold uppercase tracking-wider text-indigo-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Vertex AI OAuth Clients / Antigravity IDE Attributed to the User (${escapeHtml(userOauthClients.length)})</h4>
              <p class="text-[11px] text-slate-500">OAuth2 credentials on <code class="mono">aiplatform.googleapis.com</code> mapped to <b class="mono">${safeUserEmail}</b> with Today / Yesterday / Period usage</p>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table class="jt-table w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-slate-200 text-[10px] font-bold uppercase text-slate-500 bg-slate-50">
                  <th class="py-2 px-3">OAuth Client &amp; ID</th>
                  <th class="py-2 px-3">Project</th>
                  <th class="py-2 px-3">Models Used</th>
                  <th class="py-2 px-3 text-right">Calls</th>
                  <th class="py-2 px-3 text-right">Token</th>
                  <th class="py-2 px-3 text-right">Today ($)</th>
                  <th class="py-2 px-3 text-right">Yesterday ($)</th>
                  <th class="py-2 px-3 text-right">Period Total ($ / €)</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100">
                ${userOauthClients.map(oc => `
                  <tr class="hover:bg-indigo-50/30">
                    <td class="py-2 px-3">
                      <div class="font-bold text-indigo-950">${escapeHtml(oc.displayName || oc.credentialId)}</div>
                      <div class="text-[10px] text-slate-400 mono">${escapeHtml(oc.credentialId)}</div>
                    </td>
                    <td class="py-2 px-3 mono font-bold text-[#0F2A4A] cursor-pointer underline" data-jt-click="closeUserModal(); openProjectModal(${jsArg(oc.projectId)})">${escapeHtml(oc.projectId)}</td>
                    <td class="py-2 px-3 mono text-[11px] text-slate-600">${escapeHtml((oc.models || []).join(', ') || 'Vertex AI')}</td>
                    <td class="py-2 px-3 text-right mono font-bold">${fmtNum(oc.calls || 0)}</td>
                    <td class="py-2 px-3 text-right mono text-slate-700">${fmtTok(oc.totalTokens || 0)}</td>
                    <td class="py-2 px-3 text-right mono font-bold text-indigo-800">${fmtUsd(oc.todayCostUsd || 0)}</td>
                    <td class="py-2 px-3 text-right mono font-semibold text-slate-700">${fmtUsd(oc.yesterdayCostUsd || 0)}</td>
                    <td class="py-2 px-3 text-right mono font-extrabold text-emerald-700">${fmtUsd(oc.costUsd || 0)} <span class="text-[10px] text-slate-500">(${fmtEur(oc.costUsd || 0)})</span></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      ` : '';

      // Costruzione sezione API Keys create dall'utente
      const apiKeysSectionHtml = userApiKeys.length > 0 ? `
        <div class="jt-table-panel bg-white rounded-xl border border-amber-200 p-4 space-y-3">
          <div class="${escapeHtml(CLS_FLEX_WRAP_BETWEEN)}">
            <div>
              <h4 class="jt-drawer__section-title text-xs font-extrabold uppercase tracking-wider text-amber-900"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Personal API Keys Created by the User (${userApiKeys.length})</h4>
              <p class="text-[11px] text-slate-500">API keys cataloged on GCP with creator <b class="mono">${safeUserEmail}</b> and their Today / Yesterday / Period usage</p>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table class="jt-table w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-slate-200 text-[10px] font-bold uppercase text-slate-500 bg-slate-50">
                  <th class="py-2 px-3">API Key Name &amp; UID</th>
                  <th class="py-2 px-3">Project</th>
                  <th class="py-2 px-3">API Restrictions</th>
                  <th class="py-2 px-3 text-right">Calls</th>
                  <th class="py-2 px-3 text-right">Token</th>
                  <th class="py-2 px-3 text-right">Today ($)</th>
                  <th class="py-2 px-3 text-right">Yesterday ($)</th>
                  <th class="py-2 px-3 text-right">Period Total ($ / €)</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100">
                ${userApiKeys.map(k => `
                  <tr class="hover:bg-amber-50/30">
                    <td class="py-2 px-3">
                      <div class="font-bold text-slate-900">${escapeHtml(k.displayName || k.uid)}</div>
                      <div class="text-[10px] text-slate-400 mono">apikey:${escapeHtml(k.uid)}</div>
                    </td>
                    <td class="py-2 px-3 mono font-bold text-[#0F2A4A] cursor-pointer underline" data-jt-click="closeUserModal(); openProjectModal(${jsArg(k.projectId)})">${escapeHtml(k.projectId)}</td>
                    <td class="py-2 px-3 mono text-[11px] text-slate-600">${escapeHtml((k.apiTargets || []).join(', ') || 'All APIs')}</td>
                    <td class="py-2 px-3 text-right mono font-bold">${fmtNum(k.inferenceRequests || k.requests || 0)}</td>
                    <td class="py-2 px-3 text-right mono text-slate-700">${fmtTok(k.totalTokens || 0)}</td>
                    <td class="py-2 px-3 text-right mono font-bold text-indigo-800">${fmtUsd(k.todayCostUsd || 0)}</td>
                    <td class="py-2 px-3 text-right mono font-semibold text-slate-700">${fmtUsd(k.yesterdayCostUsd || 0)}</td>
                    <td class="py-2 px-3 text-right mono font-extrabold text-emerald-700">${fmtUsd(k.estimatedCostUsd || 0)} <span class="text-[10px] text-slate-500">(${fmtEur(k.estimatedCostUsd || 0)})</span></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      ` : '';

      const kpiHdrSlateClass = 'jt-kpi__label text-[10px] font-extrabold uppercase tracking-wider text-slate-400';
      setSafeHtml(bodyEl, `
        <!-- RIGA 4 KPI SINTETICI UTENTE -->
        <div class="jt-kpi-grid grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div class="jt-kpi p-3.5 rounded-xl bg-white border border-emerald-200 shadow-2xs">
            <div class="${escapeHtml(kpiHdrSlateClass)}"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> TOTAL ATTRIBUTED SPEND (PERIOD)</div>
            <div class="jt-kpi__value text-xl font-extrabold text-emerald-700 mono mt-1">${fmtUsd(totalCostUsd)} <span class="text-xs font-bold text-slate-500">(${fmtEur(totalCostUsd)})</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-1">OAuth: <b>${fmtUsd(oauthCostUsd)}</b> · API Key: <b class="text-amber-800">${fmtUsd(apiKeysCostUsd)}</b></div>
          </div>
          <div class="jt-kpi p-3.5 rounded-xl bg-white border border-indigo-200 shadow-2xs">
            <div class="jt-kpi__label text-[10px] font-extrabold uppercase tracking-wider text-indigo-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> SPEND TODAY vs YESTERDAY</div>
            <div class="jt-kpi__value text-lg font-extrabold text-indigo-900 mono mt-1">Today: ${fmtUsd(todayCostUsd)} <span class="text-slate-300">|</span> Yesterday: ${fmtUsd(yesterdayCostUsd)}</div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-1">Token Today: <b>${fmtTok(todayTokens)}</b> · Yesterday: <b>${fmtTok(yesterdayTokens)}</b></div>
          </div>
          <div class="jt-kpi p-3.5 rounded-xl bg-white border border-slate-200 shadow-2xs">
            <div class="${escapeHtml(kpiHdrSlateClass)}"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> AI INTERACTIONS &amp; OPERATIONS</div>
            <div class="jt-kpi__value text-xl font-extrabold text-slate-900 mono mt-1">${fmtNum(totalInteractions + apiKeysCalls)} <span class="text-xs font-normal text-slate-400">calls</span></div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-1"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> ${escapeHtml(vertexOauthCalls)} Vertex OAuth · <svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${escapeHtml(assistTurns)} Chat · <svg class="jt-ico" aria-hidden="true"><use href="#ico-search"/></svg> ${escapeHtml(searchQueries)} Search · <svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> ${escapeHtml(codeAssistCalls)} IDE · <svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> ${escapeHtml(apiKeysCalls)} Key</div>
          </div>
          <div class="jt-kpi p-3.5 rounded-xl bg-white border border-slate-200 shadow-2xs">
            <div class="${escapeHtml(kpiHdrSlateClass)}"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> TOTAL TOKENS CONSUMED</div>
            <div class="jt-kpi__value text-xl font-extrabold text-[#0F2A4A] mono mt-1">${fmtTok(totCombinedTokens)}</div>
            <div class="jt-kpi__note text-[10px] text-slate-500 mono mt-1">OAuth: <b>${fmtTok((loggedTotalTokens + vertexOauthTokens) || attributedTokens)}</b> · API Key: <b>${fmtTok(apiKeysTotalTokens)}</b></div>
          </div>
        </div>

        ${ideSectionHtml}

        ${oauthClientsSectionHtml}

        <!-- TABELLA PROGETTI E APP GEMINI ENTERPRISE ACCEDUTE DALL'UTENTE -->
        <div class="jt-table-panel bg-white rounded-xl border border-slate-200 p-4 space-y-3">
          <div class="${escapeHtml(CLS_FLEX_WRAP_BETWEEN)}">
            <div>
              <h4 class="jt-drawer__section-title text-xs font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> User Activity and Costs by Project (${perProjectRows.length} Projects)</h4>
              <p class="text-[11px] text-slate-500">Breakdown by GCP project with Gemini Enterprise Apps, DataStores, Calls, Tokens and OAuth + API Key Cost</p>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table class="jt-table w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-slate-200 text-[10px] font-bold uppercase text-slate-500 bg-slate-50">
                  <th class="py-2 px-3">GCP Project</th>
                  <th class="py-2 px-3">Operations, Gemini Enterprise Apps &amp; DataStores</th>
                  <th class="py-2 px-3 text-right">Calls</th>
                  <th class="py-2 px-3 text-right">Token</th>
                  <th class="py-2 px-3 text-right">OAuth Cost</th>
                  <th class="py-2 px-3 text-right">API Key Cost</th>
                  <th class="py-2 px-3 text-right">Total ($ / €)</th>
                </tr>
              </thead>
              <tbody>${projRowsHtml}</tbody>
            </table>
          </div>
        </div>

        ${nbSectionHtml}

        ${apiKeysSectionHtml}
      `);

      modalEl.classList.remove('hidden');
      if (typeof window.jtActivateDrawerFocus === 'function') window.jtActivateDrawerFocus('user-modal');
      setTimeout(enhanceAllTablesWithFrontendSortAndFilter, 30);
    };

    window.closeUserModal = function() {
      const modalEl = document.getElementById('user-modal');
      if (modalEl) modalEl.classList.add('hidden');
      if (typeof window.jtDeactivateDrawerFocus === 'function') window.jtDeactivateDrawerFocus('user-modal');
    };

    if (!window._jtDrawerEscBound) {
      window._jtDrawerEscBound = true;
      document.addEventListener('keydown', function(ev) {
        if (ev.key !== 'Escape') return;
        const geModal = document.getElementById('gemini-inspector-modal');
        if (geModal && !geModal.classList.contains('hidden')) {
          if (typeof window.closeGeminiInspectorModal === 'function') window.closeGeminiInspectorModal();
          return;
        }
        const uModal = document.getElementById('user-modal');
        if (uModal && !uModal.classList.contains('hidden')) {
          if (typeof window.closeUserModal === 'function') window.closeUserModal();
          return;
        }
        const pModal = document.getElementById('project-modal');
        if (pModal && !pModal.classList.contains('hidden')) {
          closeProjectModal();
        }
      });
    }


    // =========================================================================
    // GESTIONE PROGETTI SINCRONIZZATI, REGOLA AUTOMATICA & FORZA SCANSIONE
    // =========================================================================
    function updateCacheAndSyncBadges(data) {
      if (!data) return;
      const sync = data.sync || {};
      const inc = sync.includedToScanCount ?? (data.projects || []).filter(p => (p.syncMeta && p.syncMeta.scanEnabled) || (p.estimatedCostUsd > 0) || (p.inferenceRequests > 0)).length;
      const tot = sync.totalSynchronized ?? (data.projects || []).length;

      const tabSyncBadge = document.getElementById('tab-count-sync');
      if (tabSyncBadge) {
        tabSyncBadge.textContent = `${inc}/${tot}`;
        tabSyncBadge.title = `${inc} projects included in the scan out of ${tot} synced projects`;
      }

      const hdrSyncBadge = document.getElementById('header-sync-badge');
      if (hdrSyncBadge) hdrSyncBadge.textContent = `${inc}/${tot}`;
      const hdrSyncProg = document.getElementById('header-sync-progress');
      if (hdrSyncProg) {
        const pct = tot > 0 ? Math.min(100, Math.round((inc / tot) * 100)) : 0;
        hdrSyncProg.style.width = `${pct}%`;
      }

      const daysSel = document.getElementById('days-select');
      const presetVal = (data.periodRange && data.periodRange.preset) ? String(data.periodRange.preset) : '';
      if (daysSel) {
        const curSelVal = daysSel.value;
        if (presetVal && [...daysSel.options].some(o => o.value === presetVal)) {
          daysSel.value = presetVal;
        } else if (!['today', 'yesterday', 'single', 'custom'].includes(curSelVal) && data.days && [...daysSel.options].some(o => o.value === String(data.days))) {
          daysSel.value = String(data.days);
        }
        if (typeof syncCustomDateControlsVisibility === 'function') {
          syncCustomDateControlsVisibility(daysSel.value);
        }
      }

      const cacheTxt = document.getElementById('cache-status-text');
      const cachePill = document.getElementById('cache-status-pill');
      const statusDot = document.getElementById('jt-status-dot');
      const statusDetail = document.getElementById('jt-status-detail');
      if (cacheTxt && cachePill && !isLiveScanPolling) {
        const scannedAt = data.scannedAt ? new Date(data.scannedAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '';
        const durSec = data.elapsedSeconds || (data.scanProgress && data.scanProgress.lastElapsedSeconds) || 0;
        const daysVal = data.days || (daysSel ? daysSel.value : 30);
        const fmtShort = (iso) => {
          const m = String(iso).slice(0, 10).split('-');
          return m.length === 3 ? `${m[2]}/${m[1]}` : iso;
        };
        let rangeWindow = `${daysVal}d`;
        if (data.periodStart && data.periodEnd) {
          rangeWindow = data.periodStart === data.periodEnd
            ? fmtShort(data.periodStart)
            : `${fmtShort(data.periodStart)}–${fmtShort(data.periodEnd)}`;
        } else if (Array.isArray(data.timeline) && data.timeline.length > 0) {
          const sDate = data.timeline[0].date || '';
          const eDate = data.timeline[data.timeline.length - 1].date || '';
          if (sDate && eDate) {
            rangeWindow = sDate === eDate ? fmtShort(sDate) : `${fmtShort(sDate)}–${fmtShort(eDate)}`;
          }
        }
        if (statusDot) statusDot.className = 'jt-dot';
        cacheTxt.textContent = scannedAt ? `Ready · ${scannedAt}` : 'Ready';
        if (statusDetail) {
          statusDetail.textContent = durSec > 0 ? `${durSec}s · ${rangeWindow}` : rangeWindow;
        }
        cachePill.title = `Last scan ${durSec > 0 ? durSec + 's' : 'cached'} · window ${rangeWindow}`;
      }

      // Global notification if new GCP projects were detected
      const newProjs = sync.newProjectsDetected || [];
      const newBanner = document.getElementById('global-new-projects-banner');
      const newBannerTxt = document.getElementById('global-new-projects-text');
      if (newBanner && newBannerTxt) {
        if (newProjs.length > 0) {
          const withData = newProjs.filter(x => x.hasAiData);
          const noData = newProjs.filter(x => !x.hasAiData);
          const namesPreview = newProjs.slice(0, 4).map(x => `<b class="mono">${escapeHtml(x.projectId)}</b> (${x.hasAiData ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> With Data → To Scan' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> Empty → Do Not Scan'})`).join(', ');
          setSafeHtml(newBannerTxt, `
            <div class="font-extrabold text-amber-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Detected ${newProjs.length} new projects on Google Cloud!</div>
            <div class="text-[11px] text-amber-800">
              Automatically scanned with rule: <b>${withData.length} added to "To Scan"</b> (contain AI data) and <b>${noData.length} placed in "Do Not Scan"</b> (empty).
              Details: ${namesPreview}${escapeHtml(newProjs.length > 4 ? ` and ${newProjs.length - 4} more...` : '')}
            </div>
          `);
          newBanner.classList.remove('hidden');
        } else {
          newBanner.classList.add('hidden');
        }
      }
    }

    function setSyncFilterMode(mode) {
      currentSyncFilterMode = mode || 'ALL';
      ['ALL', 'INCLUDED', 'EXCLUDED', 'NEW', 'MANUAL'].forEach(m => {
        const b = document.getElementById('sync-tab-btn-' + m);
        if (!b) return;
        if (m === currentSyncFilterMode) {
          b.className = 'px-3 py-1.5 rounded-lg text-xs font-bold bg-[#0F2A4A] text-white cursor-pointer transition shadow-2xs';
        } else {
          b.className = 'px-3 py-1.5 rounded-lg text-xs font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 cursor-pointer transition';
        }
      });
      renderSyncProjectsTab();
      enhanceAllTablesWithFrontendSortAndFilter();
    }

    function getSyncProjectsListFromState() {
      if (!globalScanData) return [];
      const syncObj = globalScanData.sync || {};
      if (syncObj.projects && syncObj.projects.length > 0) {
        return syncObj.projects;
      }
      // Fallback da globalScanData.projects se sync.projects non è popolato
      return (globalScanData.projects || []).map(p => {
        const sm = p.syncMeta || {};
        const hasData = sm.hasAiData !== undefined ? sm.hasAiData : Boolean(
          p.aiActive || ((p.enabledAiApis || []).length > 0) ||
          (p.estimatedCostUsd || 0) > 0 || (p.inferenceRequests || 0) > 0 || (p.totalTokens || 0) > 0 ||
          (p.models || []).length > 0 || (p.usersUsage || []).length > 0 || (p.deployedAiResources || []).length > 0
        );
        return {
          projectId: p.projectId,
          name: p.name || p.projectId,
          hasAiData: hasData,
          scanEnabled: sm.scanEnabled !== undefined ? sm.scanEnabled : hasData,
          scanRule: sm.scanRule || (hasData ? 'AUTO_INCLUDE_HAS_DATA' : 'AUTO_EXCLUDE_NO_DATA'),
          dataReason: sm.dataReason || (hasData ? 'AI APIs enabled on project' : 'No AI APIs enabled'),
          isNewProject: Boolean(sm.isNewProject),
          lastScannedAt: sm.lastScannedAt || globalScanData.scannedAt,
          billingEnabled: Boolean(p.billingEnabled),
          skippedNoBilling: Boolean(p.skippedNoBilling),
          aiActive: Boolean(p.aiActive),
          scanStatus: p.scanStatus || 'OK',
          estimatedCostUsd: p.estimatedCostUsd || 0,
          inferenceRequests: p.inferenceRequests || 0,
          totalTokens: p.totalTokens || 0,
          modelsCount: (p.models || []).length,
          usersCount: (p.usersUsage || []).length,
          resourcesCount: (p.deployedAiResources || []).length,
          apiKeysCount: (p.apiKeys || []).length,
          enabledApisCount: (p.enabledAiApis || []).length
        };
      });
    }

    function renderSyncProjectsTab() {
      const tbody = document.getElementById('sync-projects-tbody');
      if (!tbody || !globalScanData) return;

      const allSync = getSyncProjectsListFromState();
      const incList = allSync.filter(x => x.scanEnabled);
      const excList = allSync.filter(x => !x.scanEnabled);
      const newList = allSync.filter(x => x.isNewProject);
      const manList = allSync.filter(x => String(x.scanRule || '').startsWith('MANUAL_'));

      const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      setTxt('sync-kpi-total', fmtNum(allSync.length));
      setTxt('sync-kpi-included', fmtNum(incList.length));
      setTxt('sync-kpi-included-pct', allSync.length > 0 ? `${Math.round((incList.length / allSync.length) * 100)}% of total` : '0%');
      setTxt('sync-kpi-excluded', fmtNum(excList.length));
      setTxt('sync-kpi-new', fmtNum(newList.length));
      setTxt('sync-kpi-manual-badge', `${manList.length} manual overrides`);

      setTxt('sync-btn-cnt-all', allSync.length);
      setTxt('sync-btn-cnt-inc', incList.length);
      setTxt('sync-btn-cnt-exc', excList.length);
      setTxt('sync-btn-cnt-new', newList.length);
      setTxt('sync-btn-cnt-man', manList.length);

      const syncTs = document.getElementById('sync-last-timestamp');
      if (syncTs && globalScanData.scannedAt) {
        syncTs.textContent = `Last sync: ${new Date(globalScanData.scannedAt).toLocaleString('en-GB')}`;
      }

      const q = (document.getElementById('search-input')?.value || '').toLowerCase().trim();
      const filtered = allSync.filter(item => {
        if (currentSyncFilterMode === 'INCLUDED' && !item.scanEnabled) return false;
        if (currentSyncFilterMode === 'EXCLUDED' && item.scanEnabled) return false;
        if (currentSyncFilterMode === 'NEW' && !item.isNewProject) return false;
        if (currentSyncFilterMode === 'MANUAL' && !String(item.scanRule || '').startsWith('MANUAL_')) return false;
        if (q) {
          const hay = `${item.projectId} ${item.name} ${item.dataReason || ''} ${item.scanRule || ''}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      if (filtered.length === 0) {
        setSafeHtml(tbody, `<tr><td colspan="8" class="py-10 text-center text-slate-400">No synced projects in this view (${escapeHtml(currentSyncFilterMode)}).</td></tr>`);
        return;
      }

      setSafeHtml(tbody, filtered.map(item => {
        const isInc = Boolean(item.scanEnabled);
        const hasData = Boolean(item.hasAiData);
        const isManual = String(item.scanRule || '').startsWith('MANUAL_');
        const isNew = Boolean(item.isNewProject);
        const lastScanStr = item.lastScannedAt
          ? new Date(item.lastScannedAt).toLocaleString('en-GB', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
          : 'Never';

        let ruleBadge = '';
        if (isManual) {
          ruleBadge = `<span class="jt-badge ${isInc ? 'jt-badge--blue bg-blue-100 text-blue-800 border border-blue-300' : 'jt-badge--amber bg-amber-100 text-amber-800 border border-amber-300'} px-2 py-0.5 rounded-full text-[10px] font-extrabold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> ${isInc ? 'Manually Included' : 'Manually Excluded'}</span>`;
        } else if (hasData) {
          ruleBadge = `<span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-emerald-100 text-emerald-800 border border-emerald-300"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Auto: Active AI APIs</span>`;
        } else {
          ruleBadge = `<span class="jt-badge jt-badge--gray px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-600 border border-slate-200"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Auto: No AI APIs</span>`;
        }

        const newPill = isNew
          ? `<span class="jt-badge jt-badge--amber ml-1.5 px-1.5 py-0.5 rounded bg-amber-500 text-white text-[9px] font-extrabold uppercase" data-badge-label="🆕 New"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> New</span>`
          : '';

        const totalAssets = (item.modelsCount || 0) + (item.usersCount || 0) + (item.resourcesCount || 0);

        return `
          <tr class="hover:bg-slate-50 transition ${isInc ? 'bg-white' : 'bg-slate-50/40 text-slate-500'}">
            <td class="py-3 px-4" data-sort-val="${isInc ? 1 : 0}">
              <button type="button"
                data-jt-click="toggleProjectSyncState(${jsArg(item.projectId)}, ${!isInc})"
                class="flex items-center gap-2 px-3 py-1.5 rounded-lg font-extrabold text-[11px] cursor-pointer transition border ${
                  isInc
                    ? 'bg-emerald-50 hover:bg-emerald-100 text-emerald-800 border-emerald-300'
                    : 'bg-slate-100 hover:bg-slate-200 text-slate-600 border-slate-300'
                }"
                title="Click to move between 'To Scan' and 'Skip Scan'"
              >
                <span>${isInc ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> To Scan' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> Skip Scan'}</span>
              </button>
            </td>

            <td class="py-3 px-4" data-sort-val="${escapeHtml(item.name || item.projectId)}">
              <div class="font-bold text-slate-900 flex items-center">
                <span>${escapeHtml(item.name || item.projectId)}</span>
                ${newPill}
              </div>
              <div class="text-[11px] text-slate-500 mono">${escapeHtml(item.projectId)}</div>
            </td>

            <td class="py-3 px-4" data-sort-val="${hasData ? 1 : 0}">
              <div class="flex flex-wrap items-center gap-1.5">${ruleBadge}</div>
              <div class="text-[11px] text-slate-500 mt-1">${escapeHtml(item.dataReason || '—')}</div>
            </td>

            <td class="py-3 px-4 text-right mono font-bold ${item.inferenceRequests > 0 ? 'text-slate-900' : 'text-slate-400'}" data-sort-val="${escapeHtml(item.inferenceRequests || 0)}">
              ${fmtNum(item.inferenceRequests || 0)}
            </td>

            <td class="py-3 px-4 text-right mono font-semibold ${item.totalTokens > 0 ? 'text-teal-700' : 'text-slate-400'}" data-sort-val="${escapeHtml(item.totalTokens || 0)}">
              ${fmtTok(item.totalTokens || 0)}
            </td>

            <td class="py-3 px-4 text-right" data-sort-val="${escapeHtml(totalAssets)}">
              <div class="inline-flex items-center gap-1.5 text-[11px] mono">
                <span class="jt-chip ${item.modelsCount > 0 ? 'jt-chip--blue bg-blue-50 text-blue-700 font-bold' : 'jt-chip--gray bg-slate-100 text-slate-400'} px-1.5 py-0.5 rounded" title="AI Models">${escapeHtml(item.modelsCount || 0)} mod</span>
                <span class="jt-chip ${item.usersCount > 0 ? 'jt-chip--purple bg-purple-50 text-purple-700 font-bold' : 'jt-chip--gray bg-slate-100 text-slate-400'} px-1.5 py-0.5 rounded" title="OAuth Users">${escapeHtml(item.usersCount || 0)} usr</span>
                <span class="jt-chip ${item.resourcesCount > 0 ? 'jt-chip--green bg-emerald-50 text-emerald-700 font-bold' : 'jt-chip--gray bg-slate-100 text-slate-400'} px-1.5 py-0.5 rounded" title="Apps / Model Garden Resources">${escapeHtml(item.resourcesCount || 0)} app</span>
              </div>
            </td>

            <td class="py-3 px-4 text-right mono font-extrabold ${item.estimatedCostUsd > 0 ? 'text-[#0F2A4A]' : 'text-slate-400'}" data-sort-val="${escapeHtml(item.estimatedCostUsd || 0)}">
              <div>${fmtUsd(item.estimatedCostUsd || 0)}</div>
              ${item.estimatedCostUsd > 0 ? `<div class="text-[10px] text-slate-500 font-semibold">${fmtEur(item.estimatedCostUsd)}</div>` : ''}
            </td>

            <td class="py-3 px-4 text-right">
              <div class="flex items-center justify-end gap-1.5">
                <span class="text-[10px] text-slate-400 mono hidden xl:inline">${escapeHtml(lastScanStr)}</span>
                <button type="button"
                  data-jt-click="forceScanSingleProject(${jsArg(item.projectId)}, this)"
                  class="px-2.5 py-1.5 rounded-lg bg-amber-50 hover:bg-amber-500 text-amber-800 hover:text-white border border-amber-300 font-bold text-[11px] transition cursor-pointer shrink-0"
                  title="Immediately force a live scan of this single project on GCP (even if it was in Skip Scan)"
                >
                  <svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Force Scan
                </button>
                <button type="button"
                  data-jt-click="openProjectModal(${jsArg(item.projectId)})"
                  class="px-2 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600 font-semibold text-[11px] cursor-pointer shrink-0"
                  title="Open project details sheet"
                >
                  Sheet
                </button>
              </div>
            </td>
          </tr>
        `;
      }).join(''));
    }

    async function toggleProjectSyncState(projectId, scanEnabled) {
      try {
        const res = await fetch('/api/projects-sync/toggle', {
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ projectId, scanEnabled }),
          signal: AbortSignal.timeout(30000)
        });
        const data = await res.json();
        if (data.success && data.sync && globalScanData) {
          globalScanData.sync = data.sync;
          const regMap = {};
          (data.sync.projects || []).forEach(x => { regMap[x.projectId] = x; });
          (globalScanData.projects || []).forEach(p => {
            if (regMap[p.projectId]) p.syncMeta = regMap[p.projectId];
          });
          updateCacheAndSyncBadges(globalScanData);
          renderSyncProjectsTab();
          enhanceAllTablesWithFrontendSortAndFilter();
        }
      } catch (e) {
        alert('Error updating project scan status: ' + e.message);
      }
    }

    async function applyBulkSyncAction(action) {
      try {
        const res = await fetch('/api/projects-sync/toggle', {
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ action }),
          signal: AbortSignal.timeout(30000)
        });
        const data = await res.json();
        if (data.success && data.sync && globalScanData) {
          globalScanData.sync = data.sync;
          updateCacheAndSyncBadges(globalScanData);
          renderSyncProjectsTab();
          enhanceAllTablesWithFrontendSortAndFilter();
        }
      } catch (e) {
        alert('Error applying project rule: ' + e.message);
      }
    }

    async function forceScanSingleProject(projectId, btnEl) {
      const pParams = (typeof getSelectedPeriodParams === 'function') ? getSelectedPeriodParams() : { days: 30 };
      const days = pParams.days || 30;
      const origHtml = btnEl ? btnEl.innerHTML : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Force Scan';
      if (btnEl) {
        btnEl.disabled = true;
        setSafeHtml(btnEl, '<svg class="jt-ico" aria-hidden="true"><use href="#ico-refresh"/></svg> Scanning...');
      }
      try {
        const res = await fetch('/api/projects-sync/force-scan', {
          method: 'POST',
          headers: getBrowserAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ projectId, days: Number(days) }),
          signal: AbortSignal.timeout(120000)
        });
        const data = await res.json();
        if (!data.success) {
          alert('Forced scan error for project ' + projectId + ': ' + (data.error || 'Error'));
          return;
        }
        globalScanData = data;
        updateCacheAndSyncBadges(data);
        populateFilterDropdowns();
        refreshDashboardView();
      } catch (e) {
        alert('Network error during forced scan: ' + e.message);
      } finally {
        if (btnEl) {
          btnEl.disabled = false;
          setSafeHtml(btnEl, origHtml);
        }
      }
    }

    // =========================================================================
    // MOTORE 100% FRONTEND: ORDINAMENTO COLONNE, FILTRI CONTESTUALI,
    // SUBTOTALE KPI REAL-TIME, ESPORTAZIONE CSV E PAGINAZIONE UNIVERSALE
    // Zero chiamate al backend: ordina, filtra e pagina qualsiasi tabella nel DOM!
    // =========================================================================
    const tableFrontendState = new WeakMap();

    const TABLE_CONTEXTUAL_FILTERS_CONFIG = {
      'projects-tbody': [
        {
          key: 'status',
          label: 'Status',
          options: [
            { val: 'ALL', text: 'All statuses' },
            { val: 'prj-active', text: 'ACTIVE only' },
            { val: 'prj-idle', text: 'IDLE only' }
          ],
          matchFn: (rowText) => true
        },
        {
          key: 'costBand',
          label: 'Cost Band',
          options: [
            { val: 'ALL', text: 'All $ bands' },
            { val: 'HIGH', text: '> $100' },
            { val: 'MED', text: '$10 – $100' },
            { val: 'LOW', text: '> $0 – $10' },
            { val: 'ZERO', text: '$0.00' }
          ],
          isCostBand: true
        }
      ],
      'callers-tbody': [
        {
          key: 'callerType',
          label: 'Identity Type',
          options: [
            { val: 'ALL', text: 'All callers' },
            { val: 'gserviceaccount.com', text: 'Service Account' },
            { val: '@', text: 'Users / Email' },
            { val: 'apikey', text: 'API Key / App' }
          ]
        }
      ],
      'credentials-tbody': [
        {
          key: 'risk',
          label: 'Status / Risk',
          options: [
            { val: 'ALL', text: 'All keys' },
            { val: 'cred-traffic', text: 'Active (with calls)' },
            { val: 'cred-idle', text: 'Inactive / 0 calls' }
          ]
        }
      ],
      'service-accounts-tbody': [
        {
          key: 'saKeyFilter',
          label: 'User Keys',
          options: [
            { val: 'ALL', text: 'All Service Accounts' },
            { val: 'exported', text: 'With Exported User Keys' },
            { val: '0 keys', text: 'Zero Keys (Workload Identity)' }
          ]
        },
        {
          key: 'saActivity',
          label: 'Activity Status',
          options: [
            { val: 'ALL', text: 'Any activity' },
            { val: 'sa-traffic', text: 'Active SAs with traffic' },
            { val: 'sa-dormant', text: 'Inactive / Dormant SAs' }
          ]
        }
      ],
      'models-tbody': [
        {
          key: 'family',
          label: 'Model Family',
          options: [
            { val: 'ALL', text: 'All families' },
            { val: 'gemini', text: 'Google Gemini' },
            { val: 'claude', text: 'Anthropic Claude' },
            { val: 'imagen', text: 'Imagen / Veo / Multimedia' },
            { val: 'embedding', text: 'Embeddings' }
          ]
        }
      ],
      'llm-models-tbody': [
        {
          key: 'family',
          label: 'LLM Family',
          options: [
            { val: 'ALL', text: 'All LLM models' },
            { val: 'gemini-2.5', text: 'Gemini 2.5 (Pro/Flash)' },
            { val: 'gemini-2.0', text: 'Gemini 2.0' },
            { val: 'gemini-1.5', text: 'Gemini 1.5' },
            { val: 'claude', text: 'Anthropic Claude' }
          ]
        }
      ],
      'mcp-registry-tbody': [
        {
          key: 'mcpType',
          label: 'Category',
          options: [
            { val: 'ALL', text: 'All (MCP & Agents)' },
            { val: 'mcp-server', text: 'MCP Server' },
            { val: 'mcp-agent', text: 'Agent / Cloud Run' },
            { val: 'mcp-active', text: 'ACTIVE Status' }
          ]
        }
      ],
      'model-armor-matrix-tbody': [
        {
          key: 'armorState',
          label: 'Coverage',
          options: [
            { val: 'ALL', text: 'All regions' },
            { val: 'ma-protected', text: 'PROTECTED' },
            { val: 'ma-unprotected', text: 'NOT FULLY COVERED' }
          ]
        }
      ],
      'quotas-tbody': [
        {
          key: 'quotaLevel',
          label: 'Saturation',
          options: [
            { val: 'ALL', text: 'All quotas' },
            { val: 'critical', text: 'Critical / Exhausted' },
            { val: 'warning', text: 'Warning' },
            { val: 'ok', text: 'Healthy (OK)' }
          ]
        }
      ],
      'pricing-tbody': [
        {
          key: 'vendor',
          label: 'Pricing Family',
          options: [
            { val: 'ALL', text: 'All listed models' },
            { val: 'gemini', text: 'Google Gemini' },
            { val: 'claude', text: 'Anthropic Claude' },
            { val: 'imagen', text: 'Imagen / Veo' },
            { val: 'embedding', text: 'Text / Multimodal Embedding' }
          ]
        }
      ]
    };

    function _parseLeadingUsdAmount(rawText) {
      const s = String(rawText || '').trimStart();
      if (!s) return NaN;
      let idx = 0;
      let neg = false;
      if (s[idx] === '-') {
        neg = true;
        idx++;
      }
      if (s[idx] !== '$') return NaN;
      idx++;
      while (idx < s.length && (s[idx] === ' ' || s[idx] === '\t')) idx++;
      let numStr = '';
      while (idx < s.length) {
        const ch = s[idx];
        if ((ch >= '0' && ch <= '9') || ch === '.') {
          numStr += ch;
          idx++;
        } else if (ch === ',') {
          idx++;
        } else {
          break;
        }
      }
      if (!numStr) return NaN;
      const val = parseFloat(numStr);
      return Number.isNaN(val) ? NaN : (neg ? -val : val);
    }

    function _parseFirstUsdAmountInText(rawText) {
      const s = String(rawText || '');
      const dollarIdx = s.indexOf('$');
      if (dollarIdx < 0) return NaN;
      const startIdx = (dollarIdx > 0 && s[dollarIdx - 1] === '-') ? dollarIdx - 1 : dollarIdx;
      return _parseLeadingUsdAmount(s.slice(startIdx));
    }

    function _parseTokenSuffixAmount(text) {
      if (!text || text.length > 64) return NaN;
      let i = 0;
      while (i < text.length && ((text[i] >= '0' && text[i] <= '9') || text[i] === '.' || text[i] === ',')) {
        i++;
      }
      if (i === 0) return NaN;
      const numPart = text.slice(0, i).replace(',', '.');
      if (i < text.length && text[i] === ' ') i++;
      if (i >= text.length) return NaN;
      const unit = text[i].toUpperCase();
      if (unit !== 'B' && unit !== 'M' && unit !== 'K') return NaN;
      const nextCh = text[i + 1] || '';
      if ((nextCh >= 'a' && nextCh <= 'z') || (nextCh >= 'A' && nextCh <= 'Z') || (nextCh >= '0' && nextCh <= '9')) {
        return NaN;
      }
      const base = parseFloat(numPart);
      if (Number.isNaN(base)) return NaN;
      const mult = unit === 'B' ? 1e9 : (unit === 'M' ? 1e6 : 1e3);
      return base * mult;
    }

    function _parsePlainNumericCell(numOnly) {
      if (!numOnly || numOnly.length > 40) return NaN;
      let s = numOnly;
      let sign = 1;
      if (s[0] === '-') {
        sign = -1;
        s = s.slice(1);
      }
      if (!s) return NaN;
      if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) {
        return sign * parseFloat(s.replace(/,/g, ''));
      }
      const norm = s.replace(',', '.');
      let dots = 0;
      for (let i = 0; i < norm.length; i++) {
        const c = norm[i];
        if (c === '.') {
          dots++;
          if (dots > 1) return NaN;
        } else if (c < '0' || c > '9') {
          return NaN;
        }
      }
      const val = parseFloat(norm);
      return Number.isNaN(val) ? NaN : sign * val;
    }

    function parseSmartCellSortValue(td) {
      if (!td) return { num: NaN, str: '' };
      if (td.hasAttribute('data-sort-val')) {
        const rawAttr = td.getAttribute('data-sort-val') || '';
        const asNum = Number(rawAttr);
        if (!Number.isNaN(asNum) && rawAttr.trim() !== '') {
          return { num: asNum, str: rawAttr.toLowerCase() };
        }
        return { num: NaN, str: rawAttr.toLowerCase().trim() };
      }

      const text = (td.innerText || td.textContent || '').trim();
      if (!text || text === '—' || text === '-') return { num: -Infinity, str: '' };

      // 1. Date YYYY-MM-DD ad inizio cella
      if (text.length >= 10 && text.startsWith('202') && text[4] === '-' && text[7] === '-') {
        const dMs = Date.parse(text.slice(0, 10));
        if (!Number.isNaN(dMs)) {
          return { num: dMs, str: text.toLowerCase() };
        }
      }

      // 2. Valuta USD ad inizio cella ($1,234.56 o $0.0012) per evitare che email con importi annidati vengano ordinate come numeri
      const usdVal = _parseLeadingUsdAmount(text);
      if (!Number.isNaN(usdVal)) {
        return { num: usdVal, str: text.toLowerCase() };
      }

      // 3. Token con suffisso B / M / K (es. "14.52M", "420.1K", "1.20B")
      const tokVal = _parseTokenSuffixAmount(text);
      if (!Number.isNaN(tokVal)) {
        return { num: tokVal, str: text.toLowerCase() };
      }

      // 4. Plain number at the start of a cell (e.g. "12,450", "1,234.5", "85.5%")
      const firstLine = text.split('\n')[0].trim();
      const numOnly = firstLine.endsWith('%') ? firstLine.slice(0, -1).trimEnd() : firstLine;
      const plainVal = _parsePlainNumericCell(numOnly);
      if (!Number.isNaN(plainVal)) {
        return { num: plainVal, str: text.toLowerCase() };
      }

      return { num: NaN, str: text.toLowerCase() };
    }

    function detectPrimaryCostColumnIndex(tableEl) {
      const ths = Array.from(tableEl.querySelectorAll('thead th'));
      let bestIdx = -1;
      ths.forEach((th, idx) => {
        const t = (th.innerText || th.textContent || '').toLowerCase();
        if (t.includes('/ 1m') || t.includes('1m tok') || t.includes('price')) return;
        if (/\bnet\b/.test(t) || t.includes('spend') || t.includes('cost')) {
          bestIdx = idx;
        }
      });
      return bestIdx;
    }

    function extractRowPrimaryUsdCost(tr, primaryCostColIdx) {
      if (tr.hasAttribute('data-cost-usd')) {
        const v = parseFloat(tr.getAttribute('data-cost-usd'));
        if (!Number.isNaN(v)) return v;
      }
      const cells = tr.querySelectorAll(':scope > td');
      if (primaryCostColIdx >= 0 && cells[primaryCostColIdx]) {
        const cellText = (cells[primaryCostColIdx].innerText || cells[primaryCostColIdx].textContent || '').trim();
        const val = _parseFirstUsdAmountInText(cellText);
        if (!Number.isNaN(val)) return val;
      }
      // Fallback: cerca la prima cella che inizia con $
      for (let i = 0; i < cells.length; i++) {
        const ct = (cells[i].innerText || cells[i].textContent || '').trim();
        const val = _parseLeadingUsdAmount(ct);
        if (!Number.isNaN(val)) return val;
      }
      return 0;
    }

    function exportTableFilteredRowsToCsv(tableEl) {
      const tbody = tableEl.querySelector('tbody');
      if (!tbody) return;
      const ths = Array.from(tableEl.querySelectorAll('thead th'));
      const headers = ths.map(th => {
        return (th.innerText || th.textContent || '')
          .replace(/[⇅▲▼]/g, '')
          .replace(/\s+/g, ' ')
          .trim();
      });

      const allRows = Array.from(tbody.querySelectorAll(':scope > tr'));
      const matchingRows = allRows.filter(tr => {
        const cells = tr.querySelectorAll(':scope > td');
        if (cells.length <= 1) return false;
        return tr.dataset.feFilterPass !== '0';
      });

      const escapeCsvField = (val) => {
        const clean = String(val ?? '')
          .replaceAll('\r\n', ' | ')
          .replaceAll('\n', ' | ')
          .replaceAll('\r', ' | ')
          .replace(/\s+/g, ' ')
          .trim();
        return `"${clean.replace(/"/g, '""')}"`;
      };

      const csvLines = [headers.map(escapeCsvField).join(';')];
      matchingRows.forEach(tr => {
        const cells = Array.from(tr.querySelectorAll(':scope > td'));
        const rowVals = cells.map(td => escapeCsvField(td.innerText || td.textContent || ''));
        csvLines.push(rowVals.join(';'));
      });

      const csvContent = '\uFEFF' + csvLines.join('\r\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const tbodyId = tbody.id || 'tabella-gcp';
      const dateStr = new Date().toISOString().slice(0, 10);
      a.href = url;
      a.download = `export_${tbodyId}_${dateStr}.csv`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 150);
    }

    // Il valore di un filtro a tendina deve iniziare a inizio parola: "active" non deve trovare "inactive",
    // "protected" non deve trovare "unprotected". La ricerca libera (st.q) resta una sottostringa.
    function _rowTextHasFilterToken(rowText, val) {
      // Alternative separate da '|' (es. 'exported|esportat'): basta che ne compaia una.
      const alts = String(val || '').toLowerCase().split('|').map(x => x.trim()).filter(Boolean);
      if (alts.length === 0) return true;
      return alts.some(v => {
        // Famiglie di modelli: compaiono incollate a prefissi (es. "multimodalembedding"), quindi sottostringa.
        if (v === 'embedding') return rowText.includes(v);
        let from = 0;
        for (;;) {
          const i = rowText.indexOf(v, from);
          if (i < 0) return false;
          if (i === 0 || !/[\p{L}\p{N}]/u.test(rowText[i - 1]) || !/^[\p{L}\p{N}]/u.test(v)) return true;
          from = i + 1;
        }
      });
    }

    function _doesCostMatchBand(rowCostUsd, selVal) {
      if (selVal === 'HIGH') return rowCostUsd > 100;
      if (selVal === 'MED') return rowCostUsd >= 10 && rowCostUsd <= 100;
      if (selVal === 'LOW') return rowCostUsd > 0 && rowCostUsd < 10;
      if (selVal === 'ZERO') return rowCostUsd === 0;
      return true;
    }

    function _doesRowPassContextFilters(rowText, rowCostUsd, contextFilters, configs) {
      if (!contextFilters) return true;
      for (const cfg of configs) {
        const selVal = contextFilters[cfg.key];
        if (!selVal || selVal === 'ALL') continue;
        const ok = cfg.isCostBand
          ? _doesCostMatchBand(rowCostUsd, selVal)
          : _rowTextHasFilterToken(rowText, selVal);
        if (!ok) return false;
      }
      return true;
    }

    // Markers (data-jt-token) count for the dropdown filters only, never for the free-text search or the CSV.
    function _rowFilterTokens(tr) {
      return Array.from(tr.querySelectorAll('[data-jt-token]')).map(e => e.getAttribute('data-jt-token') || '').join(' ').toLowerCase();
    }

    function _doesRowPassTableFilter(rowText, rowCostUsd, st, configs, tokenText) {
      const filterText = tokenText ? `${rowText} ${tokenText}` : rowText;
      if (st.q && !rowText.includes(st.q)) return false;
      if (st.onlyCost && !(rowCostUsd > 0)) return false;
      if (st.colFilter && st.colFilter !== 'ALL' && !_rowTextHasFilterToken(filterText, st.colFilter)) return false;
      return _doesRowPassContextFilters(filterText, rowCostUsd, st.contextFilters, configs);
    }

    function _updateTableToolbarCounters(tableEl, matchedCount, totalDataRows, primaryCostColIdx, filteredSubtotalUsd) {
      const countEl = tableEl._feToolbarCountEl;
      if (countEl) {
        countEl.textContent = totalDataRows > 0
          ? `${matchedCount}/${totalDataRows} rows`
          : '0 rows';
      }

      const subtotalEl = tableEl._feToolbarSubtotalEl;
      if (!subtotalEl) return;
      if (primaryCostColIdx >= 0 || filteredSubtotalUsd > 0) {
        const usdFormatted = typeof fmtUsd === 'function' ? fmtUsd(filteredSubtotalUsd) : `$${filteredSubtotalUsd.toFixed(2)}`;
        const eurFormatted = typeof fmtEur === 'function' ? fmtEur(filteredSubtotalUsd) : `€${(filteredSubtotalUsd * 0.92).toFixed(2)}`;
        subtotalEl.classList.remove('hidden');
        setSafeHtml(subtotalEl, `∑ Subtotal: <strong class="text-emerald-800">${escapeHtml(usdFormatted)}</strong> <span class="text-emerald-600">(${escapeHtml(eurFormatted)})</span>`);
      } else {
        subtotalEl.classList.add('hidden');
      }
    }

    function applyFrontendFilterToTable(tableEl) {
      const tbody = tableEl.querySelector('tbody');
      if (!tbody) return;
      const inModal = Boolean(tableEl.closest('#project-modal, #user-modal'));
      const defaultPageSize = inModal ? 10 : 20;
      const st = tableFrontendState.get(tableEl) || {
        q: '',
        onlyCost: false,
        colFilter: 'ALL',
        contextFilters: {},
        sortCol: null,
        sortAsc: false,
        pageSize: defaultPageSize,
        currentPage: 1
      };
      tableFrontendState.set(tableEl, st);

      const rows = Array.from(tbody.querySelectorAll(':scope > tr'));
      const primaryCostColIdx = detectPrimaryCostColumnIndex(tableEl);
      const configs = TABLE_CONTEXTUAL_FILTERS_CONFIG[tbody.id] || [];

      let totalDataRows = 0;
      const matchedRows = [];
      let filteredSubtotalUsd = 0;

      rows.forEach(tr => {
        const cells = tr.querySelectorAll(':scope > td');
        if (cells.length <= 1) {
          tr.style.display = '';
          return;
        }
        totalDataRows++;

        const rowText = (tr.innerText || tr.textContent || '').toLowerCase();
        const rowCostUsd = extractRowPrimaryUsdCost(tr, primaryCostColIdx);
        const pass = _doesRowPassTableFilter(rowText, rowCostUsd, st, configs, _rowFilterTokens(tr));

        tr.dataset.feFilterPass = pass ? '1' : '0';
        if (pass) {
          matchedRows.push(tr);
          filteredSubtotalUsd += rowCostUsd;
        } else {
          tr.style.display = 'none';
        }
      });

      const matchedCount = matchedRows.length;
      const effPageSize = st.pageSize > 0 ? st.pageSize : (matchedCount || 1);
      const totalPages = Math.max(1, Math.ceil(matchedCount / effPageSize));
      st.currentPage = Math.min(Math.max(1, st.currentPage), totalPages);

      const startIdx = st.pageSize > 0 ? (st.currentPage - 1) * st.pageSize : 0;
      const endIdx = st.pageSize > 0 ? Math.min(startIdx + st.pageSize, matchedCount) : matchedCount;

      matchedRows.forEach((tr, idx) => {
        tr.style.display = (idx >= startIdx && idx < endIdx) ? '' : 'none';
      });

      _updateTableToolbarCounters(tableEl, matchedCount, totalDataRows, primaryCostColIdx, filteredSubtotalUsd);
      renderTablePaginationFooter(tableEl, matchedCount, totalDataRows, startIdx, endIdx, totalPages, st);
    }

    function renderTablePaginationFooter(tableEl, matchedCount, totalDataRows, startIdx, endIdx, totalPages, st) {
      const footerEl = tableEl._fePaginationFooterEl;
      if (!footerEl) return;

      const rangeLabel = matchedCount > 0
        ? `Showing <strong>${escapeHtml(startIdx + 1)}–${escapeHtml(endIdx)}</strong> of <strong>${escapeHtml(matchedCount)}</strong> rows${escapeHtml(matchedCount < totalDataRows ? ` (filtered from ${totalDataRows})` : '')}`
        : `No rows match the current filters (${totalDataRows} total)`;

      const pageButtonsHtml = [];
      const maxVisibleButtons = 5;
      const pageBtnBaseClass = 'px-2 py-0.5 rounded border border-slate-200 bg-white text-slate-600 hover:bg-slate-100 text-[11px] font-semibold';
      const navBtnBaseClass = 'px-2 py-0.5 rounded border border-slate-200 bg-white text-slate-700 hover:bg-slate-100 disabled:opacity-40 disabled:pointer-events-none text-[11px] font-semibold';
      let startPage = Math.max(1, st.currentPage - 2);
      let endPage = Math.min(totalPages, startPage + maxVisibleButtons - 1);
      if (endPage - startPage < maxVisibleButtons - 1) {
        startPage = Math.max(1, endPage - maxVisibleButtons + 1);
      }

      if (startPage > 1) {
        pageButtonsHtml.push(`<button type="button" data-fe-page="1" class="${escapeHtml(pageBtnBaseClass)}">1</button>`);
        if (startPage > 2) {
          pageButtonsHtml.push(`<span class="text-slate-400 px-1 text-[11px]">…</span>`);
        }
      }
      for (let p = startPage; p <= endPage; p++) {
        const isCurr = p === st.currentPage;
        pageButtonsHtml.push(
          `<button type="button" data-fe-page="${escapeHtml(p)}" class="px-2.5 py-0.5 rounded border text-[11px] font-bold transition ${
            isCurr
              ? 'bg-[#0F2A4A] text-white border-[#0F2A4A] shadow-sm'
              : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-100'
          }">${escapeHtml(p)}</button>`
        );
      }
      if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
          pageButtonsHtml.push(`<span class="text-slate-400 px-1 text-[11px]">…</span>`);
        }
        pageButtonsHtml.push(`<button type="button" data-fe-page="${escapeHtml(totalPages)}" class="${escapeHtml(pageBtnBaseClass)}">${escapeHtml(totalPages)}</button>`);
      }

      const sizes = [
        { val: 10, label: '10' },
        { val: 20, label: '20' },
        { val: 50, label: '50' },
        { val: 100, label: '100' },
        { val: 0, label: 'All' }
      ];

      const sizeBtnsHtml = sizes.map(s => {
        const active = st.pageSize === s.val;
        return `<button type="button" data-fe-pagesize="${escapeHtml(s.val)}" class="px-2 py-0.5 text-[11px] font-bold rounded transition ${
          active
            ? 'bg-blue-600 text-white shadow-sm'
            : 'text-slate-600 hover:bg-slate-200/70'
        }">${escapeHtml(s.label)}</button>`;
      }).join('');

      setSafeHtml(footerEl, `
        <div class="flex flex-wrap items-center justify-between gap-2 w-full">
          <div class="flex items-center gap-2 text-[11px] text-slate-600">
            <span>${rangeLabel}</span>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <div class="inline-flex items-center gap-1 bg-slate-100 border border-slate-200 rounded-lg p-0.5">
              <span class="text-[10px] font-semibold text-slate-500 px-1.5">Rows:</span>
              ${sizeBtnsHtml}
            </div>
            <div class="inline-flex items-center gap-1">
              <button type="button" data-fe-page="prev" ${st.currentPage <= 1 ? 'disabled' : ''} class="${escapeHtml(navBtnBaseClass)}">« Prev</button>
              ${pageButtonsHtml.join('')}
              <button type="button" data-fe-page="next" ${st.currentPage >= totalPages ? 'disabled' : ''} class="${escapeHtml(navBtnBaseClass)}">Next »</button>
            </div>
          </div>
        </div>
      `);

      const keepTableInFocusOnPaginate = () => {
        const cardEl = tableEl.closest('.bg-white') || tableEl.parentElement || tableEl;
        if (!cardEl) return;
        const rect = cardEl.getBoundingClientRect();
        if (rect.top < 70 || rect.top > window.innerHeight * 0.65) {
          cardEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      };

      footerEl.querySelectorAll('[data-fe-pagesize]').forEach(btn => {
        btn.addEventListener('click', () => {
          const newSize = parseInt(btn.getAttribute('data-fe-pagesize'), 10);
          st.pageSize = Number.isNaN(newSize) ? 20 : newSize;
          st.currentPage = 1;
          tableFrontendState.set(tableEl, st);
          applyFrontendFilterToTable(tableEl);
          keepTableInFocusOnPaginate();
        });
      });

      footerEl.querySelectorAll('[data-fe-page]').forEach(btn => {
        btn.addEventListener('click', () => {
          const target = btn.getAttribute('data-fe-page');
          if (target === 'prev') {
            st.currentPage = Math.max(1, st.currentPage - 1);
          } else if (target === 'next') {
            st.currentPage = Math.min(totalPages, st.currentPage + 1);
          } else {
            const p = parseInt(target, 10);
            if (!Number.isNaN(p)) st.currentPage = p;
          }
          tableFrontendState.set(tableEl, st);
          applyFrontendFilterToTable(tableEl);
          keepTableInFocusOnPaginate();
        });
      });
    }

    function sortTableByColumnFrontend(tableEl, colIndex, forceAsc = null) {
      const tbody = tableEl.querySelector('tbody');
      if (!tbody) return;

      const inModal = Boolean(tableEl.closest('#project-modal, #user-modal'));
      const st = tableFrontendState.get(tableEl) || {
        q: '',
        onlyCost: false,
        colFilter: 'ALL',
        contextFilters: {},
        sortCol: null,
        sortAsc: false,
        pageSize: inModal ? 10 : 20,
        currentPage: 1
      };
      if (forceAsc !== null) {
        st.sortAsc = forceAsc;
      } else if (st.sortCol === colIndex) {
        st.sortAsc = !st.sortAsc;
      } else {
        st.sortAsc = (colIndex === 0);
      }
      st.sortCol = colIndex;
      tableFrontendState.set(tableEl, st);

      const allRows = Array.from(tbody.querySelectorAll(':scope > tr'));
      const dataRows = allRows.filter(tr => tr.querySelectorAll(':scope > td').length > 1);
      if (dataRows.length <= 1) return;

      const dir = st.sortAsc ? 1 : -1;
      dataRows.sort((rowA, rowB) => {
        const cellA = rowA.querySelectorAll(':scope > td')[colIndex];
        const cellB = rowB.querySelectorAll(':scope > td')[colIndex];
        const valA = parseSmartCellSortValue(cellA);
        const valB = parseSmartCellSortValue(cellB);

        const aIsNum = !Number.isNaN(valA.num);
        const bIsNum = !Number.isNaN(valB.num);
        if (aIsNum && bIsNum && valA.num !== valB.num) {
          return (valA.num - valB.num) * dir;
        }
        return valA.str.localeCompare(valB.str, 'en', { numeric: true, sensitivity: 'base' }) * dir;
      });

      dataRows.forEach(tr => tbody.appendChild(tr));

      const ths = tableEl.querySelectorAll('thead th');
      ths.forEach((th, idx) => {
        const ind = th.querySelector('.fe-sort-indicator');
        if (!ind) return;
        if (idx === colIndex) {
          ind.textContent = st.sortAsc ? ' ▲' : ' ▼';
          ind.className = 'fe-sort-indicator text-blue-600 font-extrabold ml-1';
        } else {
          ind.textContent = ' ⇅';
          ind.className = 'fe-sort-indicator text-slate-300 group-hover:text-slate-500 ml-1';
        }
      });

      applyFrontendFilterToTable(tableEl);
    }

    function enhanceSingleTableFrontend(tableEl) {
      if (!tableEl || !tableEl.querySelector('thead') || !tableEl.querySelector('tbody')) return;
      if (tableEl.closest('#view-pricing, #pricing-model-modal')) return;

      const inModal = Boolean(tableEl.closest('#project-modal, #user-modal'));
      const tbody = tableEl.querySelector('tbody');
      const tbodyId = tbody ? tbody.id : '';

      if (!tableFrontendState.has(tableEl)) {
        tableFrontendState.set(tableEl, {
          q: '',
          onlyCost: false,
          colFilter: 'ALL',
          contextFilters: {},
          sortCol: null,
          sortAsc: false,
          pageSize: inModal ? 10 : 20,
          currentPage: 1
        });
      }

      // 1. Rendi cliccabili tutte le intestazioni <th> per l'ordinamento istantaneo FE
      const ths = tableEl.querySelectorAll('thead th');
      ths.forEach((th, idx) => {
        if (!th.dataset.feSortableBound) {
          th.dataset.feSortableBound = '1';
          th.classList.add('cursor-pointer', 'select-none', 'hover:bg-slate-100/80', 'transition', 'group');
          th.title = 'Click to sort';
          const span = document.createElement('span');
          span.className = 'fe-sort-indicator text-slate-300 group-hover:text-slate-500 ml-1 text-[10px]';
          span.textContent = ' ⇅';
          th.appendChild(span);
          th.addEventListener('click', (e) => {
            if (e.target.tagName === 'BUTTON' || e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
            sortTableByColumnFrontend(tableEl, idx);
          });
        }
      });

      // 2. Inject quick FE filter bar + contextual filters + KPI subtotal + CSV above the table
      if (!tableEl._feToolbarInjected) {
        const wrapper = tableEl.parentElement;
        if (wrapper && wrapper.parentElement) {
          tableEl._feToolbarInjected = true;
          const bar = document.createElement('div');
          bar.className = 'jt-table-bar px-4 py-2 bg-slate-50/95 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2 text-xs';

          const contextConfigs = TABLE_CONTEXTUAL_FILTERS_CONFIG[tbodyId] || [];
          const selOpenTag = '<' + 'select';
          const selCloseTag = '</' + 'select>';
          const contextSelectsHtml = contextConfigs.map(cfg => {
            const optsHtml = cfg.options.map(o => `<option value="${escapeHtml(o.val)}">${escapeHtml(o.text)}</option>`).join('');
            return [
              `${selOpenTag} data-fe-ctx-key="${escapeHtml(cfg.key)}" aria-label="Filter by ${escapeHtml(cfg.label)}" title="Filter by ${escapeHtml(cfg.label)}" class="fe-tbl-ctx-select bg-white border border-slate-200 rounded-lg px-2 py-1 text-[11px] font-semibold text-slate-700 focus:outline-none focus:border-blue-500 cursor-pointer">`,
              optsHtml,
              selCloseTag
            ].join('');
          }).join('');

          setSafeHtml(bar, `
            <div class="flex flex-wrap items-center gap-2">
              <input
                type="text"
                aria-label="Search in table"
                placeholder="Search in table..."
                class="fe-tbl-search bg-white border border-slate-200 rounded-lg px-2.5 py-1 text-xs text-slate-700 placeholder-slate-400 focus:outline-none focus:border-blue-500 w-44 sm:w-52"
              />
              ${contextSelectsHtml}
              <label class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white border border-slate-200 text-[11px] font-semibold text-slate-700 cursor-pointer hover:bg-slate-50 select-none">
                <input type="checkbox" class="fe-tbl-only-cost accent-blue-600 rounded" />
                <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Cost &gt; $0</span>
              </label>
              <button type="button" class="fe-tbl-reset hidden px-2 py-1 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 text-[11px] font-bold transition" title="Reset table filters">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg> Reset
              </button>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <span class="fe-tbl-subtotal jt-chip jt-chip--green hidden font-mono text-[11px] bg-emerald-50 border border-emerald-200 text-emerald-900 px-2.5 py-0.5 rounded-full"></span>
              <span class="fe-tbl-count jt-chip jt-chip--navy font-bold text-[#0F2A4A] mono bg-blue-50 border border-blue-200 px-2.5 py-0.5 rounded-full text-[11px]">0 rows</span>
              <button type="button" class="fe-tbl-csv-btn jt-btn-secondary inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-[11px] font-semibold transition shadow-2xs" title="Export filtered rows to CSV (UTF-8)">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> CSV
              </button>
            </div>
          `);

          wrapper.parentElement.insertBefore(bar, wrapper);

          // Inietta barra di paginazione universale sotto la tabella
          const footerBar = document.createElement('div');
          footerBar.className = 'jt-table-footer px-4 py-2 bg-slate-50/90 border-t border-slate-200 flex flex-wrap items-center justify-between gap-2 text-xs';
          if (wrapper.nextSibling) {
            wrapper.parentElement.insertBefore(footerBar, wrapper.nextSibling);
          } else {
            wrapper.parentElement.appendChild(footerBar);
          }
          tableEl._fePaginationFooterEl = footerBar;

          const searchInp = bar.querySelector('.fe-tbl-search');
          const costChk = bar.querySelector('.fe-tbl-only-cost');
          const resetBtn = bar.querySelector('.fe-tbl-reset');
          const csvBtn = bar.querySelector('.fe-tbl-csv-btn');
          const ctxSelects = bar.querySelectorAll('.fe-tbl-ctx-select');
          tableEl._feToolbarCountEl = bar.querySelector('.fe-tbl-count');
          tableEl._feToolbarSubtotalEl = bar.querySelector('.fe-tbl-subtotal');

          const updateResetVisibility = () => {
            const st = tableFrontendState.get(tableEl);
            const hasCtx = Object.values(st.contextFilters || {}).some(v => v && v !== 'ALL');
            const isFiltered = Boolean(st.q || st.onlyCost || hasCtx);
            if (resetBtn) resetBtn.classList.toggle('hidden', !isFiltered);
          };

          searchInp.addEventListener('input', () => {
            const st = tableFrontendState.get(tableEl);
            st.q = searchInp.value.toLowerCase().trim();
            st.currentPage = 1;
            updateResetVisibility();
            applyFrontendFilterToTable(tableEl);
          });

          costChk.addEventListener('change', () => {
            const st = tableFrontendState.get(tableEl);
            st.onlyCost = costChk.checked;
            st.currentPage = 1;
            updateResetVisibility();
            applyFrontendFilterToTable(tableEl);
          });

          ctxSelects.forEach(sel => {
            sel.addEventListener('change', () => {
              const st = tableFrontendState.get(tableEl);
              if (!st.contextFilters) st.contextFilters = {};
              const key = sel.getAttribute('data-fe-ctx-key');
              st.contextFilters[key] = sel.value;
              st.currentPage = 1;
              updateResetVisibility();
              applyFrontendFilterToTable(tableEl);
            });
          });

          if (resetBtn) {
            resetBtn.addEventListener('click', () => {
              const st = tableFrontendState.get(tableEl);
              st.q = '';
              st.onlyCost = false;
              st.contextFilters = {};
              st.currentPage = 1;
              searchInp.value = '';
              costChk.checked = false;
              ctxSelects.forEach(s => { s.value = 'ALL'; });
              updateResetVisibility();
              applyFrontendFilterToTable(tableEl);
            });
          }

          if (csvBtn) {
            csvBtn.addEventListener('click', () => {
              exportTableFilteredRowsToCsv(tableEl);
            });
          }
        }
      }

      // 3. Ri-applica eventuale filtro, ordinamento e paginazione attiva quando la tabella viene ri-renderizzata
      const st = tableFrontendState.get(tableEl);
      if (st && st.sortCol !== null) {
        sortTableByColumnFrontend(tableEl, st.sortCol, st.sortAsc);
      } else {
        applyFrontendFilterToTable(tableEl);
      }
    }

    function resetAllTablesFrontendPagination() {
      const allTables = document.querySelectorAll('main table, #project-modal table, #user-modal table');
      allTables.forEach(tbl => {
        const st = tableFrontendState.get(tbl);
        if (st) {
          st.currentPage = 1;
          tableFrontendState.set(tbl, st);
        }
      });
    }

    function enhanceAllTablesWithFrontendSortAndFilter() {
      const allTables = document.querySelectorAll('main table, #project-modal table, #user-modal table');
      allTables.forEach(tbl => enhanceSingleTableFrontend(tbl));
    }

    window.addEventListener('DOMContentLoaded', checkAuthAndInitialLoad);
