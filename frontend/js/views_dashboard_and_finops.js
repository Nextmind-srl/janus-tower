    function _accumulateExecProjEntities(p, execCtx) {
      const { modelMap, regionMap, toolMap, userMap, credList, nonEuResRegions, weights } = execCtx;
      (p.models || []).forEach(m => {
        const mk = m.modelId || m.model || 'unknown';
        if (!modelMap[mk]) modelMap[mk] = { model: mk, calls: 0, tokens: 0, costUsd: 0, regions: new Set() };
        modelMap[mk].calls += (m.invocations ?? m.requests ?? 0);
        modelMap[mk].tokens += (m.totalTokens || 0);
        modelMap[mk].costUsd += (m.costUsd ?? m.estimatedCostUsd ?? 0);
        (m.locations || (m.location ? [m.location] : [])).forEach(loc => { if (loc) modelMap[mk].regions.add(loc); });
      });

      const dr = p.dataResidency || {};
      weights.nonEuResCount += (dr.nonEuResourcesCount || (dr.nonEuDeployedResources || []).length || 0);
      (dr.nonEuDeployedResources || []).forEach(nr => { if (nr.location) nonEuResRegions.add(nr.location); });
      (dr.regions || []).forEach(r => {
        const rk = r.location || 'global';
        if (!regionMap[rk]) regionMap[rk] = { location: rk, category: r.category || 'GLOBAL_ANYCAST', calls: 0, tokens: 0, costUsd: 0, res: 0 };
        regionMap[rk].calls += (r.calls || 0);
        regionMap[rk].tokens += (r.tokens || 0);
        regionMap[rk].costUsd += (r.costUsd || 0);
        regionMap[rk].res += (r.resourcesCount || 0);
        const w = (r.costUsd || 0) * 1000 + (r.tokens || 0) / 1000 + (r.calls || 0) + (r.resourcesCount || 0) * 50;
        if (r.category === 'ITALY_LOCAL') weights.italyWeight += Math.max(1, w);
        else if (r.category === 'EU_EEA') weights.euWeight += Math.max(1, w);
        else if (r.category === 'NON_EU_US_OTHER') weights.nonEuWeight += Math.max(1, w);
        else weights.globalWeight += Math.max(1, w);
      });

      const ats = p.aiToolsSummary || {};
      toolMap['VERTEX_API'].calls += (p.vertexRequests || 0);
      toolMap['VERTEX_API'].cost += (p.vertexCostUsd || 0);
      toolMap['AI_STUDIO'].calls += (p.geminiApiRequests || ats.geminiApiRequests || (ats.aiStudio && ats.aiStudio.inferenceCalls) || 0);
      toolMap['AI_STUDIO'].cost += (p.geminiCostUsd || ats.geminiApiCostUsd || (ats.aiStudio && ats.aiStudio.costUsd) || 0);
      toolMap['NOTEBOOKLM'].calls += (ats.notebookLmEnterpriseCalls || (ats.notebooks && ats.notebooks.notebookLmEnterpriseCalls) || 0);
      toolMap['COLAB_NB'].calls += (ats.colabEnterpriseCalls || 0) + (ats.colabResourcesCount || 0);

      let projAgentspaceCalls = 0;
      let projDialogflowCalls = 0;
      (p.vertexFeatures || []).forEach(vf => {
        if (vf.isControlPlaneOnly) return;
        const vReqs = vf.inferenceRequests || vf.requests || 0;
        const vCost = vf.costUsd || 0;
        if (vf.id === 'svc_agentspace_assistant' || (vf.service === 'discoveryengine.googleapis.com' && vf.id !== 'svc_notebooklm_enterprise')) {
          projAgentspaceCalls += vReqs;
          toolMap['AGENTSPACE'].cost += vCost;
        } else if (vf.service === 'dialogflow.googleapis.com') {
          projDialogflowCalls += vReqs;
          toolMap['DIALOGFLOW_CX'].cost += vCost;
        }
      });

      let userAgentspaceCalls = 0;
      (p.usersUsage || []).forEach(u => {
        const uAgentC = (u.assistTurns || 0) + (u.searchQueries || 0);
        userAgentspaceCalls += uAgentC;
        toolMap['CODE_ASSIST'].calls += (u.codeAssistCalls || 0);

        const ue = u.userEmail || 'unknown';
        if (!userMap[ue]) userMap[ue] = { email: ue, calls: 0, tokens: 0, costUsd: 0, tools: new Set(), projects: new Set() };
        const uCalls = (u.totalInteractions || 0) + (u.apiKeysCalls || 0);
        const uToks = ((u.loggedTotalTokens || 0) + (u.vertexOauthTokens || 0) + (u.apiKeysTotalTokens || 0)) || (u.attributedTokens || 0);
        const uCost = (u.estimatedCostUsd !== undefined && u.estimatedCostUsd !== null) ? u.estimatedCostUsd : ((u.oauthCostUsd || 0) + (u.apiKeysCostUsd || 0));
        userMap[ue].calls += uCalls;
        userMap[ue].tokens += uToks;
        userMap[ue].costUsd += uCost;
        userMap[ue].projects.add(p.projectId);
        (u.toolsUsed || []).forEach(t => userMap[ue].tools.add(t));
      });
      toolMap['AGENTSPACE'].calls += Math.max(projAgentspaceCalls, userAgentspaceCalls);
      toolMap['DIALOGFLOW_CX'].calls += projDialogflowCalls;

      (p.credentialsUsage || []).forEach(c => {
        const cCalls = c.ok200Inference ?? c.inferenceRequests ?? c.requests ?? c.calls ?? 0;
        const cFailed = c.failedInference ?? ((c.otherErrors || 0) + (c.errors429 || 0));
        const cCost = c.estimatedCostUsd || 0;
        if (cCost > 0 || cCalls > 0 || cFailed > 0) {
          credList.push({
            name: c.resolvedName || c.name || c.displayName || c.credentialId || 'cred',
            id: c.credentialId || '',
            type: c.resolvedType || c.type || 'OAUTH_CLIENT',
            projectId: p.projectId,
            calls: cCalls,
            tokens: c.totalTokens || 0,
            failed: cFailed,
            costUsd: cCost
          });
        }
      });
    }

    function _accumulateExecProjectForensicsAndSec(p, acc) {
      const lf = p.aiLogForensics || {};
      const hsb = p.httpStatusBreakdown || lf.httpStatusBreakdown || {};
      acc.http200 += (hsb.ok200 ?? hsb['200'] ?? hsb['2xx'] ?? 0);
      acc.http429 += (hsb.err429 ?? hsb['429'] ?? 0);
      acc.http401_403 += (hsb.err401_403 ?? hsb['401_403'] ?? hsb['403'] ?? 0);
      acc.http400 += (hsb.err400 ?? hsb['400'] ?? 0);
      acc.http5xx += (hsb.err5xx ?? hsb['5xx'] ?? hsb['500'] ?? 0);
      acc.infErrs += (hsb.inferenceErrors ?? ((p.inferenceErrors429 || 0) + (p.inferenceErrorsOther || 0)));
      acc.sysErrs += (hsb.systemControlPlaneErrors ?? Math.max(0, ((p.errors429 || 0) + (p.otherErrors || 0)) - ((p.inferenceErrors429 || 0) + (p.inferenceErrorsOther || 0))));
      const pLat = p.avgLatencyMs ?? lf.avgLatencyMs ?? 0;
      if (pLat > 0) {
        const wC = Math.max(1, (p.inferenceRequests || 1));
        acc.latencyWeightedSum += (pLat * wC);
        acc.latencyWeightCalls += wC;
      }
      acc.err429 += (lf.errors429Count ?? p.errors429 ?? 0);
      acc.errFailed += (lf.failedOrDeniedCallsCount || 0);
      acc.unrestrKeys += (lf.unrestrictedKeysCount || 0);
      acc.staleKeys += (lf.staleKeysOver90dCount || 0);
      acc.ghostKeys += (lf.ghostDeletedKeysWithTrafficCount || 0);
      acc.saKeys += (lf.exportedSaKeysCount || 0);
      (lf.externalUsers || []).forEach(u => acc.extUsers.add(u));
      if (lf.unattributedAuditBlindness) {
        acc.blindProjs++;
        acc.blindTokens += (lf.unattributedTokens || 0);
      }
      acc.pubEndpoints += (lf.publicEndpointsCount || 0);
      acc.nonCmek += (lf.nonCmekResourcesCount || 0);
      acc.weekendCalls += (lf.weekendCalls || 0);
      acc.weekendUsd += (lf.weekendCostUsd || 0);
      (lf.costSpikeDays || []).forEach(sd => acc.spikeDays.push({ ...sd, projectId: p.projectId }));
      (lf.securityKeywords || []).forEach(kw => {
        const parts = String(kw).split(':');
        const base = parts[0];
        const num = parts.length > 1 ? (parseInt(parts[1], 10) || 1) : 1;
        if (!acc.secTagCounts[base]) acc.secTagCounts[base] = { projs: 0, total: 0 };
        acc.secTagCounts[base].projs += 1;
        acc.secTagCounts[base].total += num;
      });
      (lf.adminMutations || []).forEach(m => { acc.mutationCounts[m] = (acc.mutationCounts[m] || 0) + 1; });

      const sp = p.aiSecurityPosture || {};
      if (sp.evaluated) {
        acc.secScores.push(sp.score ?? 100);
        acc.critCount += (sp.criticalCount || 0);
        acc.highCount += (sp.highCount || 0);
        acc.medCount += (sp.mediumCount || 0);
        (sp.findings || []).forEach(f => {
          acc.findingList.push({ ...f, projectId: p.projectId, score: sp.score ?? 100 });
        });
      }
    }

    function _applySummaryOverridesIfUnfiltered(isUnfilteredAll, s, sFe, sDr, sLf, state) {
      if (!isUnfilteredAll) return;
      if (s.excludedNonAiInfraCostUsd !== undefined) state.excludedNonAiInfraUsd = s.excludedNonAiInfraCostUsd;
      else if (sFe.excludedNonAiInfraCostUsd !== undefined) state.excludedNonAiInfraUsd = sFe.excludedNonAiInfraCostUsd;
      if (sFe.dailyBurnRateAiUsd !== undefined) state.dailyBurnAiUsd = sFe.dailyBurnRateAiUsd;
      if (sFe.dailyBurnRateTcoUsd !== undefined) state.dailyBurnTcoUsd = sFe.dailyBurnRateTcoUsd;
      if (sFe.forecast30dAiUsd !== undefined) state.forecast30dAiUsd = sFe.forecast30dAiUsd;
      if (sFe.forecast30dTcoUsd !== undefined) state.forecast30dTcoUsd = sFe.forecast30dTcoUsd;
      if (sFe.zombieReasoningEnginesCount !== undefined) state.zombieBuildsCount = sFe.zombieReasoningEnginesCount;
      if (sDr.nonEuResourcesCount !== undefined) state.nonEuResCount = sDr.nonEuResourcesCount;
      (sDr.nonEuDeployedResources || []).forEach(nr => { if (nr.location) state.nonEuResRegions.add(nr.location); });
      const sh = s.httpStatusBreakdown || sLf.httpStatusBreakdown;
      if (sh) {
        state.http200 = sh.ok200 ?? sh['200'] ?? sh['2xx'] ?? state.http200;
        state.http429 = sh.err429 ?? sh['429'] ?? state.http429;
        state.http401_403 = sh.err401_403 ?? sh['401_403'] ?? sh['403'] ?? state.http401_403;
        state.http400 = sh.err400 ?? sh['400'] ?? state.http400;
        state.http5xx = sh.err5xx ?? sh['5xx'] ?? sh['500'] ?? state.http5xx;
        state.infErrs = sh.inferenceErrors ?? state.infErrs;
        state.sysErrs = sh.systemControlPlaneErrors ?? state.sysErrs;
      }
    }

    function _computeSecGrade(avgSec) {
      if (avgSec >= 90) return 'A';
      if (avgSec >= 75) return 'B';
      if (avgSec >= 60) return 'C';
      if (avgSec >= 40) return 'D';
      return 'F';
    }

    function _aggregateExecutiveDashboardMetrics(agg, q, visibleProjs) {
      const s = globalScanData.summary || {};
      const sFe = s.finopsExtended || {};
      const sDr = s.dataResidency || {};
      const sLf = s.aiLogForensics || {};
      const isUnfilteredAll = (agg.selProj === 'ALL' && !q);

      let netAiUsd = 0, grossAiUsd = 0, cacheSavedUsd = 0, potentialCacheUsd = 0, infraUsd = 0, idleWasteMonthlyUsd = 0;
      let last7CostUsd = 0, prev7CostUsd = 0, last7Calls = 0, prev7Calls = 0;
      let aiCalls = 0, sysCalls = 0, totTokens = 0, inTokens = 0, outTokens = 0, cachedTokens = 0;

      const fAcc = {
        latencyWeightedSum: 0, latencyWeightCalls: 0,
        http200: 0, http429: 0, http401_403: 0, http400: 0, http5xx: 0, infErrs: 0, sysErrs: 0,
        err429: 0, errFailed: 0, unrestrKeys: 0, staleKeys: 0, ghostKeys: 0, saKeys: 0, extUsers: new Set(),
        blindProjs: 0, blindTokens: 0, pubEndpoints: 0, nonCmek: 0, weekendCalls: 0, weekendUsd: 0,
        spikeDays: [], secScores: [], critCount: 0, highCount: 0, medCount: 0,
        secTagCounts: {}, mutationCounts: {}, findingList: [],
        excludedNonAiInfraUsd: 0, dailyBurnAiUsd: 0, dailyBurnTcoUsd: 0, forecast30dAiUsd: 0, forecast30dTcoUsd: 0,
        zombieBuildsCount: 0, nonEuResCount: 0, nonEuResRegions: new Set()
      };

      const modelMap = {};
      const toolMap = {
        'VERTEX_API': { calls: 0, cost: 0, tab: 'models', kw: 'aiplatform' },
        'AGENTSPACE': { calls: 0, cost: 0, tab: 'features', kw: 'DiscoveryEngine' },
        'NOTEBOOKLM': { calls: 0, cost: 0, tab: 'ai-tools', kw: 'NotebookLM' },
        'AI_STUDIO': { calls: 0, cost: 0, tab: 'ai-tools', kw: 'generativelanguage' },
        'COLAB_NB': { calls: 0, cost: 0, tab: 'ai-tools', kw: 'colab' },
        'DIALOGFLOW_CX': { calls: 0, cost: 0, tab: 'features', kw: 'dialogflow' },
        'CODE_ASSIST': { calls: 0, cost: 0, tab: 'ai-tools', kw: 'cloudaicompanion' }
      };
      const regionMap = {};
      const userMap = {};
      const credList = [];
      const weights = { italyWeight: 0, euWeight: 0, globalWeight: 0, nonEuWeight: 0, nonEuResCount: 0 };
      const execCtx = { modelMap, regionMap, toolMap, userMap, credList, nonEuResRegions: fAcc.nonEuResRegions, weights };

      visibleProjs.forEach(p => {
        const cUsd = p.estimatedCostUsd || 0;
        const fe = p.finopsExtended || {};
        const pAiSav = (p.cacheSavingsUsd || 0) ||
          ((p.vertexCacheSavingsUsd || 0) + (p.geminiCacheSavingsUsd || 0) + (p.otherAiCacheSavingsUsd || 0)) ||
          (fe.cacheSavingsUsd || 0) ||
          (p.models || []).reduce((sum, m) => sum + (m.cacheSavingsUsd || 0), 0);
        const pAiGross = (p.grossCostUsd || 0) ||
          ((p.vertexGrossCostUsd || p.vertexCostUsd || 0) + (p.geminiGrossCostUsd || p.geminiCostUsd || 0) + (p.otherAiGrossCostUsd || p.otherAiCostUsd || 0)) ||
          (cUsd + pAiSav);
        netAiUsd += cUsd;
        grossAiUsd += Math.max(pAiGross, cUsd + pAiSav);
        cacheSavedUsd += pAiSav;
        infraUsd += (p.infraCostUsd || 0);
        aiCalls += (p.inferenceRequests ?? p.billableRequests ?? 0);
        sysCalls += (p.systemRequests ?? p.systemFreeRequests ?? 0);
        totTokens += (p.totalTokens || 0);
        inTokens += (p.inputTokens || 0);
        outTokens += (p.outputTokens || 0) + (p.thinkingTokens || 0);
        cachedTokens += (p.cachedTokens || 0);

        potentialCacheUsd += (fe.potentialExtraCacheSavingsUsd || 0);
        idleWasteMonthlyUsd += (fe.estimatedMonthlyIdleWasteUsd || 0);
        fAcc.excludedNonAiInfraUsd += (p.excludedNonAiInfraCostUsd ?? fe.excludedNonAiInfraCostUsd ?? 0);
        fAcc.dailyBurnAiUsd += (fe.dailyBurnRateAiUsd || 0);
        fAcc.dailyBurnTcoUsd += (fe.dailyBurnRateTcoUsd || 0);
        fAcc.forecast30dAiUsd += (fe.forecast30dAiUsd || 0);
        fAcc.forecast30dTcoUsd += (fe.forecast30dTcoUsd || 0);
        last7CostUsd += (fe.last7dCostUsd || 0);
        prev7CostUsd += (fe.prev7dCostUsd || 0);
        last7Calls += (fe.last7dRequests || 0);
        prev7Calls += (fe.prev7dRequests || 0);
        fAcc.zombieBuildsCount += (fe.zombieReasoningEnginesCount || (fe.zombieReasoningEngines || []).length || 0);

        _accumulateExecProjectForensicsAndSec(p, fAcc);
        _accumulateExecProjEntities(p, execCtx);
      });

      const { italyWeight, euWeight, globalWeight, nonEuWeight } = weights;
      fAcc.nonEuResCount = weights.nonEuResCount;

      const totalBillUsd = isUnfilteredAll && s.totalTcoUsd !== undefined ? s.totalTcoUsd : (netAiUsd + infraUsd);
      _applySummaryOverridesIfUnfiltered(isUnfilteredAll, s, sFe, sDr, sLf, fAcc);

      const costTrend7dPct = (isUnfilteredAll && sFe.costTrend7dPct !== undefined)
        ? sFe.costTrend7dPct
        : (prev7CostUsd > 0 ? Number((((last7CostUsd - prev7CostUsd) / prev7CostUsd) * 100).toFixed(1)) : 0);
      const requestsTrend7dPct = (isUnfilteredAll && sFe.requestsTrend7dPct !== undefined)
        ? sFe.requestsTrend7dPct
        : (prev7Calls > 0 ? Number((((last7Calls - prev7Calls) / prev7Calls) * 100).toFixed(1)) : 0);
      const sAvgLat = s.avgLatencyMs ?? sLf.avgLatencyMs;
      const avgLatencyMs = (isUnfilteredAll && sAvgLat !== undefined && sAvgLat > 0)
        ? sAvgLat
        : (fAcc.latencyWeightCalls > 0 ? Number((fAcc.latencyWeightedSum / fAcc.latencyWeightCalls).toFixed(1)) : 0);

      let costTrendArrow = '•';
      if (costTrend7dPct > 0) costTrendArrow = '▲';
      else if (costTrend7dPct < 0) costTrendArrow = '▼';

      let costTrendColor = 'text-slate-600 bg-slate-100';
      if (costTrend7dPct > 5) costTrendColor = 'text-rose-600 bg-rose-50';
      else if (costTrend7dPct < -5) costTrendColor = 'text-emerald-700 bg-emerald-50';

      let reqTrendArrow = '•';
      if (requestsTrend7dPct > 0) reqTrendArrow = '▲';
      else if (requestsTrend7dPct < 0) reqTrendArrow = '▼';

      let reqTrendColor = 'text-slate-600 bg-slate-100';
      if (requestsTrend7dPct > 0) reqTrendColor = 'text-blue-700 bg-blue-50';
      else if (requestsTrend7dPct < 0) reqTrendColor = 'text-amber-700 bg-amber-50';

      const nonEuRegionsList = Array.from(fAcc.nonEuResRegions).join(', ') || 'us-central1';

      const costPer1kCalls = aiCalls > 0 ? (netAiUsd / (aiCalls / 1000)) : 0;
      const costPer1mTokens = totTokens > 0 ? (netAiUsd / (totTokens / 1000000)) : 0;
      const promptTokensAll = Math.max(inTokens, cachedTokens);
      const cacheHitPct = promptTokensAll > 0 ? ((cachedTokens / promptTokensAll) * 100).toFixed(1) : '0.0';
      const totRegWeight = italyWeight + euWeight + globalWeight + nonEuWeight;
      const euPct = totRegWeight > 0 ? (((italyWeight + euWeight) / totRegWeight) * 100).toFixed(0) : '100';
      const itPct = totRegWeight > 0 ? ((italyWeight / totRegWeight) * 100).toFixed(0) : '0';
      const glPct = totRegWeight > 0 ? ((globalWeight / totRegWeight) * 100).toFixed(0) : '0';
      const avgSec = fAcc.secScores.length > 0 ? Math.round(fAcc.secScores.reduce((a, b) => a + b, 0) / fAcc.secScores.length) : 100;
      const secGrade = _computeSecGrade(avgSec);
      const totErrs = fAcc.err429 + fAcc.errFailed;
      const errPct = (aiCalls + sysCalls + totErrs) > 0 ? ((totErrs / (aiCalls + sysCalls + totErrs)) * 100).toFixed(2) : '0.00';

      return {
        netAiUsd, grossAiUsd, cacheSavedUsd, potentialCacheUsd, infraUsd, idleWasteMonthlyUsd,
        excludedNonAiInfraUsd: fAcc.excludedNonAiInfraUsd, dailyBurnAiUsd: fAcc.dailyBurnAiUsd,
        dailyBurnTcoUsd: fAcc.dailyBurnTcoUsd, forecast30dAiUsd: fAcc.forecast30dAiUsd,
        forecast30dTcoUsd: fAcc.forecast30dTcoUsd, zombieBuildsCount: fAcc.zombieBuildsCount,
        nonEuResCount: fAcc.nonEuResCount, nonEuRegionsList, avgLatencyMs,
        http200: fAcc.http200, http429: fAcc.http429, http401_403: fAcc.http401_403,
        http400: fAcc.http400, http5xx: fAcc.http5xx, infErrs: fAcc.infErrs, sysErrs: fAcc.sysErrs,
        aiCalls, sysCalls, totTokens, inTokens, outTokens, cachedTokens,
        err429: fAcc.err429, errFailed: fAcc.errFailed, unrestrKeys: fAcc.unrestrKeys,
        staleKeys: fAcc.staleKeys, ghostKeys: fAcc.ghostKeys, saKeys: fAcc.saKeys, extUsers: fAcc.extUsers,
        blindProjs: fAcc.blindProjs, blindTokens: fAcc.blindTokens, pubEndpoints: fAcc.pubEndpoints,
        nonCmek: fAcc.nonCmek, weekendCalls: fAcc.weekendCalls, weekendUsd: fAcc.weekendUsd,
        spikeDays: fAcc.spikeDays, critCount: fAcc.critCount, highCount: fAcc.highCount, medCount: fAcc.medCount,
        modelMap, toolMap, regionMap, secTagCounts: fAcc.secTagCounts, mutationCounts: fAcc.mutationCounts,
        userMap, credList, findingList: fAcc.findingList,
        nonEuWeight, totalBillUsd, costTrend7dPct, requestsTrend7dPct,
        costTrendArrow, costTrendColor, reqTrendArrow, reqTrendColor,
        costPer1kCalls, costPer1mTokens, cacheHitPct, euPct, itPct, glPct, avgSec, secGrade, totErrs, errPct
      };
    }

    function _renderExecutiveDashboardKpiCards(metricsEl, d, visibleProjsCount) {
      setSafeHtml(metricsEl, `
        <div data-jt-click="switchTab('daily')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-blue-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> NET AI COST</span>
            <span class="jt-chip px-1.5 py-0.5 rounded ${escapeHtml(d.costTrendColor)} mono">${escapeHtml(d.costTrendArrow)} ${d.costTrend7dPct > 0 ? '+' : ''}${escapeHtml(d.costTrend7dPct)}% 7d</span>
          </div>
          <div class="flex items-baseline justify-between mt-1">
            <div class="jt-kpi__value text-xl font-extrabold text-[#0F2A4A] mono">${fmtUsd(d.netAiUsd)}</div>
            <span class="jt-kpi__unit text-[10px] font-bold text-slate-500 mono">${fmtEur(d.netAiUsd)}</span>
          </div>
          <div class="jt-kpi__note mt-1 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>30d FCST: <b class="text-[#0F2A4A]">${fmtUsd(d.forecast30dAiUsd)}</b></span>
            <span>BURN: <b>$${d.dailyBurnAiUsd.toFixed(2)}/d</b></span>
          </div>
          <div class="mt-0.5 flex items-center justify-between text-[9px] text-slate-400 mono">
            <span>GROSS: <b>${fmtUsd(d.grossAiUsd)}</b></span>
            <span>PROJS: <b>${escapeHtml(visibleProjsCount)}</b></span>
          </div>
        </div>

        <div data-jt-click="switchTab('features')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-emerald-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> CACHE HIT &amp; SAVED</span>
            <span class="jt-chip jt-chip--green px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 mono">${escapeHtml(d.cacheHitPct)}% HIT</span>
          </div>
          <div class="jt-kpi__value text-xl font-extrabold text-emerald-700 mono mt-1">-${fmtUsd(d.cacheSavedUsd)}</div>
          <div class="jt-kpi__note mt-1.5 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>CACHED: <b>${fmtTok(d.cachedTokens)}</b></span>
            <span>POTENTIAL: <b class="text-amber-700">-${fmtUsd(d.potentialCacheUsd)}</b></span>
          </div>
        </div>

        <div data-jt-click="switchTab('projects')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-blue-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> TOTAL INVOICE (AI + INFRA)</span>
            <span class="jt-chip jt-chip--blue px-1.5 py-0.5 rounded bg-blue-50 text-[#0F2A4A] font-extrabold mono">${fmtEur(d.totalBillUsd)}</span>
          </div>
          <div class="flex items-baseline justify-between mt-1">
            <div class="jt-kpi__value text-xl font-extrabold text-slate-900 mono">${fmtUsd(d.totalBillUsd)}</div>
            <span class="text-[10px] text-slate-500 mono">AI: <b class="text-emerald-700">${fmtEur(d.netAiUsd)}</b> + Infra: <b>${fmtEur(d.infraUsd)}</b></span>
          </div>
          <div class="jt-kpi__note mt-1 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>AI INFRA (9 srv): <b>${fmtUsd(d.infraUsd)} (${fmtEur(d.infraUsd)})</b></span>
            <span>IDLE: <b class="${d.idleWasteMonthlyUsd > 0 ? 'text-rose-600' : 'text-slate-600'}">$${d.idleWasteMonthlyUsd.toFixed(0)}/m</b></span>
          </div>
          ${d.excludedNonAiInfraUsd > 0 ? `
          <div class="mt-1 px-1.5 py-0.5 rounded bg-emerald-50 border border-emerald-200 text-emerald-800 text-[9px] font-bold mono truncate" title="Cloud SQL on projects with 0 AI calls, excluded from AI TCO">
            Excluded Non-AI SQL: -${fmtUsd(d.excludedNonAiInfraUsd)}
          </div>` : ''}
        </div>

        <div data-jt-click="switchTab('models')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-blue-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> UNIT ECONOMICS</span>
            <span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 mono">UNIT</span>
          </div>
          <div class="jt-kpi__value text-xl font-extrabold text-slate-900 mono mt-1">$${d.costPer1mTokens.toFixed(2)}<span class="jt-kpi__unit text-[11px] font-normal text-slate-400">/1M tok</span></div>
          <div class="jt-kpi__note mt-1.5 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>1K CALLS: <b>$${d.costPer1kCalls.toFixed(3)}</b></span>
            <span>MODELS: <b>${Object.keys(d.modelMap).length}</b></span>
          </div>
        </div>

        <div data-jt-click="switchTab('daily')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-blue-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> VOLUME &amp; TOKENS</span>
            <span class="jt-chip px-1.5 py-0.5 rounded ${escapeHtml(d.reqTrendColor)} mono">${escapeHtml(d.reqTrendArrow)} ${d.requestsTrend7dPct > 0 ? '+' : ''}${escapeHtml(d.requestsTrend7dPct)}% 7d</span>
          </div>
          <div class="flex items-baseline justify-between mt-1">
            <div class="jt-kpi__value text-xl font-extrabold text-slate-900 mono">${fmtNum(d.aiCalls)} <span class="jt-kpi__unit text-[11px] font-normal text-slate-400">AI</span></div>
            <span class="text-[10px] font-bold text-blue-700 mono">${fmtTok(d.totTokens)} tok</span>
          </div>
          <div class="jt-kpi__note mt-1 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>IN/OUT: <b>${fmtTok(d.inTokens)}/${fmtTok(d.outTokens)}</b></span>
            <span>${d.avgLatencyMs > 0 ? `LAT: <b>${escapeHtml(d.avgLatencyMs)} ms</b>` : `SYS $0: <b>${fmtNum(d.sysCalls)}</b>`}</span>
          </div>
        </div>

        <div data-jt-click="switchTab('features')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-emerald-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span data-kpi-label="🇪🇺 GDPR RESIDENCY"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> GDPR RESIDENCY</span>
            <span class="jt-chip ${(d.nonEuWeight > 0 || d.nonEuResCount > 0) ? 'jt-chip--amber bg-amber-100 text-amber-800' : 'jt-chip--green bg-emerald-50 text-emerald-700'} px-1.5 py-0.5 rounded mono">${d.nonEuWeight > 0 ? 'US TRAFFIC' : (d.nonEuResCount > 0 ? 'NON-EU RES' : 'EU OK')}</span>
          </div>
          <div class="jt-kpi__value text-xl font-extrabold text-emerald-700 mono mt-1">${escapeHtml(d.euPct)}% <span class="jt-kpi__unit text-[11px] font-normal text-slate-400">EU</span></div>
          <div class="jt-kpi__note mt-1 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>IT: <b>${escapeHtml(d.itPct)}%</b></span>
            <span>GLOBAL: <b>${escapeHtml(d.glPct)}%</b></span>
            <span>REGIONS: <b>${Object.keys(d.regionMap).length}</b></span>
          </div>
          ${d.nonEuResCount > 0 ? `
          <div class="mt-1 px-1.5 py-0.5 rounded bg-amber-50 border border-amber-300 text-amber-900 text-[9px] font-extrabold mono truncate" title="AI resources deployed outside the EU">
            <svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> ${escapeHtml(d.nonEuResCount)} Non-EU Deployed (${escapeHtml(d.nonEuRegionsList)})
          </div>` : ''}
        </div>

        <div data-jt-click="switchTab('security')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-rose-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-shield"/></svg> SECURITY SCORE</span>
            <span class="jt-chip ${d.avgSec >= 80 ? 'jt-chip--green bg-emerald-50 text-emerald-700' : 'jt-chip--amber bg-amber-100 text-amber-800'} px-1.5 py-0.5 rounded mono">GRADE ${escapeHtml(d.secGrade)}</span>
          </div>
          <div class="jt-kpi__value text-xl font-extrabold ${d.avgSec >= 80 ? 'text-emerald-700' : 'text-amber-700'} mono mt-1">${escapeHtml(d.avgSec)}/100</div>
          <div class="jt-kpi__note mt-1 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>CRIT: <b class="${d.critCount > 0 ? 'text-rose-600' : ''}">${escapeHtml(d.critCount)}</b></span>
            <span>HIGH: <b class="${d.highCount > 0 ? 'text-amber-600' : ''}">${escapeHtml(d.highCount)}</b></span>
            <span>MED: <b>${escapeHtml(d.medCount)}</b></span>
          </div>
          ${d.zombieBuildsCount > 0 ? `
          <div data-jt-click="event.stopPropagation(); switchTab('features');" class="mt-1 px-1.5 py-0.5 rounded-full bg-purple-50 border border-purple-200 text-purple-800 text-[9px] font-extrabold mono truncate text-center hover:bg-purple-100" title="Duplicate/obsolete Reasoning Engine builds detected">
            <svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> ${escapeHtml(d.zombieBuildsCount)} Zombie Agent Builds
          </div>` : ''}
        </div>

        <div data-jt-click="switchTab('credentials')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-rose-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> HTTP 429 &amp; FAILS</span>
            <span class="jt-chip ${d.totErrs > 0 ? 'jt-chip--red bg-rose-50 text-rose-700' : 'jt-chip--gray bg-slate-100 text-slate-600'} px-1.5 py-0.5 rounded mono">${escapeHtml(d.errPct)}% ERR</span>
          </div>
          <div class="flex items-baseline justify-between mt-1">
            <div class="jt-kpi__value text-xl font-extrabold ${d.totErrs > 0 ? 'text-rose-700' : 'text-slate-800'} mono">${fmtNum(d.totErrs)}</div>
            <span class="text-[9px] text-slate-500 mono">${d.avgLatencyMs > 0 ? `LAT: <b>${escapeHtml(d.avgLatencyMs)}ms</b>` : `INF: <b class="text-rose-600">${escapeHtml(d.infErrs)}</b> · SYS: <b>${escapeHtml(d.sysErrs)}</b>`}</span>
          </div>
          <div class="jt-kpi__note mt-1 flex items-center justify-between text-[9px] text-slate-500 mono">
            <span>429: <b>${fmtNum(d.http429 || d.err429)}</b></span>
            <span>401/3: <b class="${d.http401_403 > 0 ? 'text-amber-700' : ''}">${fmtNum(d.http401_403)}</b></span>
            <span>400: <b>${fmtNum(d.http400)}</b></span>
            <span>5xx: <b class="${d.http5xx > 0 ? 'text-rose-600' : ''}">${fmtNum(d.http5xx)}</b></span>
          </div>
        </div>

        <div data-jt-click="switchTab('security')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-amber-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> KEY &amp; IAM HYGIENE</span>
            <span class="jt-chip ${(d.unrestrKeys + d.ghostKeys + d.saKeys) > 0 ? 'jt-chip--amber bg-amber-100 text-amber-800' : 'jt-chip--green bg-emerald-50 text-emerald-700'} px-1.5 py-0.5 rounded mono">KEYS</span>
          </div>
          <div class="jt-kpi__value text-xl font-extrabold text-slate-900 mono mt-1">${escapeHtml(d.unrestrKeys + d.ghostKeys + d.saKeys)} <span class="jt-kpi__unit text-[11px] font-normal text-slate-400">RISK</span></div>
          <div class="jt-kpi__note mt-1.5 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>UNRESTR: <b>${escapeHtml(d.unrestrKeys)}</b></span>
            <span>GHOST: <b class="${d.ghostKeys > 0 ? 'text-rose-600' : ''}">${escapeHtml(d.ghostKeys)}</b></span>
            <span>SA: <b>${escapeHtml(d.saKeys)}</b></span>
            <span>&gt;90d: <b>${escapeHtml(d.staleKeys)}</b></span>
          </div>
        </div>

        <div data-jt-click="switchTab('security')" class="jt-kpi bg-white rounded-xl border border-slate-200 p-3 shadow-2xs cursor-pointer hover:border-indigo-400 transition">
          <div class="flex items-center justify-between text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> LOG FORENSICS</span>
            <span class="jt-chip jt-chip--purple px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 mono">SPIKES: ${d.spikeDays.length}</span>
          </div>
          <div class="jt-kpi__value text-xl font-extrabold text-slate-900 mono mt-1">${fmtNum(d.weekendCalls)} <span class="jt-kpi__unit text-[11px] font-normal text-slate-400">WKND</span></div>
          <div class="jt-kpi__note mt-1.5 flex items-center justify-between text-[10px] text-slate-500 mono">
            <span>WKND $: <b>${fmtUsd(d.weekendUsd)}</b></span>
            <span>EXT: <b class="${d.extUsers.size > 0 ? 'text-amber-700' : ''}">${escapeHtml(d.extUsers.size)}</b></span>
            <span>BLIND: <b>${escapeHtml(d.blindProjs)}</b></span>
          </div>
        </div>
      `);
    }

    function _renderExecutiveDashboardKeywordsAndGrids(kwEl, gridsEl, d, visibleProjs) {
      const topModels = Object.values(d.modelMap).sort((a, b) => (b.costUsd - a.costUsd) || (b.tokens - a.tokens) || (b.calls - a.calls));
      const topRegions = Object.values(d.regionMap).sort((a, b) => (b.costUsd - a.costUsd) || (b.tokens - a.tokens) || (b.calls - a.calls));
      const secKeywords = Object.entries(d.secTagCounts).sort((a, b) => (b[1].projs - a[1].projs) || (b[1].total - a[1].total));
      const mutKeywords = Object.entries(d.mutationCounts).sort((a, b) => b[1] - a[1]);

      const modelPills = topModels.map(m => `
        <button type="button" data-jt-click="dashboardFilterByKeyword('models', ${jsArg(m.model)})" class="px-2 py-1 rounded-md bg-slate-50 hover:bg-blue-50 border border-slate-200 hover:border-blue-300 text-[11px] mono flex items-center gap-1.5 cursor-pointer transition">
          <span class="font-bold text-slate-800">${escapeHtml(m.model)}</span>
          <span class="text-slate-400">${fmtTok(m.tokens)}</span>
          <span class="font-extrabold text-[#0F2A4A]">${fmtUsd(m.costUsd)}</span>
        </button>
      `).join('') || '<span class="text-[11px] text-slate-400 mono">NONE</span>';

      const toolPills = Object.entries(d.toolMap).filter(([, v]) => v.calls > 0 || v.cost > 0).map(([k, v]) => `
        <button type="button" data-jt-click="dashboardFilterByKeyword(${jsArg(v.tab)}, '')" class="px-2 py-1 rounded-md bg-indigo-50/70 hover:bg-indigo-100 border border-indigo-200 text-[11px] mono flex items-center gap-1.5 cursor-pointer transition">
          <span class="font-extrabold text-indigo-900">#${escapeHtml(k)}</span>
          <span class="text-indigo-700 font-bold">${fmtNum(v.calls)} calls</span>
          ${v.cost > 0 ? `<span class="text-[#0F2A4A] font-extrabold">${fmtUsd(v.cost)}</span>` : ''}
        </button>
      `).join('');

      const regionPills = topRegions.map(r => {
        const badgeCls = r.category === 'ITALY_LOCAL' || r.category === 'EU_EEA'
          ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
          : (r.category === 'NON_EU_US_OTHER' ? 'bg-rose-50 border-rose-300 text-rose-900' : 'bg-amber-50 border-amber-200 text-amber-900');
        return `
          <button type="button" data-jt-click="dashboardFilterByKeyword('features', ${jsArg(r.location)})" class="px-2 py-1 rounded-md border ${escapeHtml(badgeCls)} text-[11px] mono flex items-center gap-1.5 cursor-pointer transition">
            <span class="font-extrabold">${escapeHtml(r.location)}</span>
            <span class="opacity-75">${fmtNum(r.calls)}c</span>
            ${r.res > 0 ? `<span class="opacity-75">${escapeHtml(r.res)}res</span>` : ''}
            <span class="font-bold">${fmtUsd(r.costUsd)}</span>
          </button>
        `;
      }).join('');

      const secPills = secKeywords.map(([kw, info]) => {
        const isCrit = kw.includes('GHOST') || kw.includes('STATIC_SA') || kw.includes('NON_EU') || kw.includes('PUBLIC_ENDPOINT') || kw.includes('FAIL');
        const cls = isCrit
          ? 'bg-rose-50 border-rose-200 text-rose-800 hover:bg-rose-100'
          : 'bg-amber-50 border-amber-200 text-amber-900 hover:bg-amber-100';
        return `
          <button type="button" data-jt-click="dashboardFilterByKeyword('security', '')" class="px-2 py-0.5 rounded border ${escapeHtml(cls)} text-[10px] mono font-extrabold flex items-center gap-1 cursor-pointer transition">
            <span>#${escapeHtml(kw)}:${fmtNum(info.total)}</span>
            <span class="px-1 rounded bg-white/80 text-slate-800">${escapeHtml(info.projs)}p</span>
          </button>
        `;
      }).join('');

      const mutPills = mutKeywords.slice(0, 12).map(([m, cnt]) => `
        <button type="button" data-jt-click="dashboardFilterByKeyword('credentials', ${jsArg(m)})" class="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 text-[10px] mono font-semibold flex items-center gap-1 cursor-pointer transition">
          <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> ${escapeHtml(m)}</span>
          <span class="text-slate-400">${escapeHtml(cnt)}p</span>
        </button>
      `).join('');

      setSafeHtml(kwEl, `
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-[10px] font-extrabold uppercase tracking-wider text-slate-400 w-24 shrink-0"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> MODELS</span>
          <div class="flex flex-wrap gap-1.5 flex-1">${modelPills}</div>
        </div>
        <div class="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-100">
          <span class="text-[10px] font-extrabold uppercase tracking-wider text-slate-400 w-24 shrink-0"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> AI TOOLS</span>
          <div class="flex flex-wrap gap-1.5 flex-1">${toolPills}</div>
        </div>
        <div class="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-100">
          <span class="text-[10px] font-extrabold uppercase tracking-wider text-slate-400 w-24 shrink-0"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> REGIONS</span>
          <div class="flex flex-wrap gap-1.5 flex-1">${regionPills}</div>
        </div>
        <div class="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-100">
          <span class="text-[10px] font-extrabold uppercase tracking-wider text-slate-400 w-24 shrink-0"><svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> SEC TAGS</span>
          <div class="flex flex-wrap gap-1.5 flex-1">${secPills}</div>
        </div>
        <div class="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-100">
          <span class="text-[10px] font-extrabold uppercase tracking-wider text-slate-400 w-24 shrink-0"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> AUDIT OPS</span>
          <div class="flex flex-wrap gap-1.5 flex-1">${mutPills}</div>
        </div>
      `);

      const topProjs = [...visibleProjs].sort((a, b) => ((b.estimatedCostUsd || 0) - (a.estimatedCostUsd || 0)) || ((b.totalTokens || 0) - (a.totalTokens || 0)) || ((b.inferenceRequests || 0) - (a.inferenceRequests || 0))).slice(0, 7);
      const topUsers = Object.values(d.userMap).sort((a, b) => (b.costUsd - a.costUsd) || (b.tokens - a.tokens) || (b.calls - a.calls)).slice(0, 7);
      const topCreds = [...d.credList].sort((a, b) => (b.costUsd - a.costUsd) || (b.tokens - a.tokens) || (b.calls - a.calls)).slice(0, 7);

      const maxProjCost = Math.max(0.01, ...topProjs.map(p => p.estimatedCostUsd || 0));
      const maxUserCost = Math.max(0.01, ...topUsers.map(u => u.costUsd || 0));
      const maxCredCost = Math.max(0.01, ...topCreds.map(c => c.costUsd || 0));

      setSafeHtml(gridsEl, `
        <!-- TOP PROGETTI -->
        <div class="jt-dash-card bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
          <div class="jt-dash-card__head px-3.5 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <span class="jt-dash-card__title text-[11px] font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> TOP PROJECTS ($)</span>
            <button type="button" data-jt-click="switchTab('projects')" class="text-[10px] font-bold text-blue-700 hover:underline cursor-pointer">ALL →</button>
          </div>
          <div class="divide-y divide-slate-100 text-xs">
            ${topProjs.map(p => {
              const pct = Math.min(100, Math.max(3, Math.round(((p.estimatedCostUsd || 0) / maxProjCost) * 100)));
              return `
              <div data-jt-click="openProjectModal(${jsArg(p.projectId)})" class="px-3.5 py-2 hover:bg-slate-50 cursor-pointer">
                <div class="flex items-center justify-between gap-2">
                  <div class="min-w-0">
                    <div class="font-bold text-slate-900 truncate mono text-[11px]">${escapeHtml(p.projectId)}</div>
                    <div class="text-[10px] text-slate-400 mono">${fmtNum(p.inferenceRequests ?? p.billableRequests ?? 0)} calls · ${fmtTok(p.totalTokens || 0)} tok</div>
                  </div>
                  <div class="text-right shrink-0 mono">
                    <div class="font-extrabold text-[#0F2A4A]">${fmtUsd(p.estimatedCostUsd || 0)}</div>
                    <div class="text-[10px] text-slate-400">Score ${escapeHtml((p.aiSecurityPosture && p.aiSecurityPosture.score) ?? 100)}</div>
                  </div>
                </div>
                <div class="jt-progress-track mt-1.5"><div class="jt-progress-fill" style="width:${pct}%"></div></div>
              </div>
            `;}).join('')}
          </div>
        </div>

        <!-- TOP UTENTI -->
        <div class="jt-dash-card bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
          <div class="jt-dash-card__head px-3.5 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <span class="jt-dash-card__title text-[11px] font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> TOP USERS ($)</span>
            <button type="button" data-jt-click="switchTab('users')" class="text-[10px] font-bold text-blue-700 hover:underline cursor-pointer">ALL →</button>
          </div>
          <div class="divide-y divide-slate-100 text-xs">
            ${topUsers.map(u => {
              const pct = Math.min(100, Math.max(3, Math.round(((u.costUsd || 0) / maxUserCost) * 100)));
              return `
              <div data-jt-click="openUserModal(${jsArg(u.email || '')})" class="px-3.5 py-2 hover:bg-blue-50/50 cursor-pointer transition" title="Click to open the user's 360° sheet">
                <div class="flex items-center justify-between gap-2">
                  <div class="min-w-0">
                    <div class="font-bold text-[#0F2A4A] hover:underline truncate mono text-[11px]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> ${escapeHtml(u.email)}</div>
                    <div class="text-[10px] text-slate-400 mono truncate">${fmtNum(u.calls)} calls · ${escapeHtml(Array.from(u.tools).slice(0, 2).join(', '))}</div>
                  </div>
                  <div class="text-right shrink-0 mono">
                    <div class="font-extrabold text-[#0F2A4A]">${fmtUsd(u.costUsd)}</div>
                    <div class="text-[10px] text-slate-400">${fmtTok(u.tokens)} tok</div>
                  </div>
                </div>
                <div class="jt-progress-track mt-1.5"><div class="jt-progress-fill" style="width:${pct}%"></div></div>
              </div>
            `;}).join('')}
          </div>
        </div>

        <!-- TOP CREDENZIALI & SPIKE LOGS -->
        <div class="jt-dash-card bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
          <div class="jt-dash-card__head px-3.5 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <span class="jt-dash-card__title text-[11px] font-extrabold uppercase tracking-wider text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> TOP KEYS &amp; OAUTH ($)</span>
            <button type="button" data-jt-click="switchTab('credentials')" class="text-[10px] font-bold text-blue-700 hover:underline cursor-pointer">ALL →</button>
          </div>
          <div class="divide-y divide-slate-100 text-xs">
            ${topCreds.map(c => {
              const pct = Math.min(100, Math.max(3, Math.round(((c.costUsd || 0) / maxCredCost) * 100)));
              return `
              <div data-jt-click="dashboardFilterByKeyword('credentials', ${jsArg(c.name)})" class="px-3.5 py-2 hover:bg-slate-50 cursor-pointer">
                <div class="flex items-center justify-between gap-2">
                  <div class="min-w-0">
                    <div class="font-bold text-slate-900 truncate mono text-[11px]" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</div>
                    <div class="text-[10px] text-slate-400 mono truncate">${escapeHtml(c.projectId)} · ${escapeHtml(c.type)} ${c.failed > 0 ? `· <b class="text-rose-600">${escapeHtml(c.failed)} err</b>` : ''}</div>
                  </div>
                  <div class="text-right shrink-0 mono">
                    <div class="font-extrabold text-[#0F2A4A]">${fmtUsd(c.costUsd)}</div>
                    <div class="text-[10px] text-slate-400">${fmtNum(c.calls)} calls · ${fmtTok(c.tokens)} tok</div>
                  </div>
                </div>
                <div class="jt-progress-track mt-1.5"><div class="jt-progress-fill" style="width:${pct}%"></div></div>
              </div>
            `;}).join('')}
          </div>
        </div>
      `);
    }

    function renderExecutiveDashboardTab(agg) {
      const metricsEl = document.getElementById('dashboard-metrics-strip');
      const kwEl = document.getElementById('dashboard-keywords-matrix');
      const gridsEl = document.getElementById('dashboard-top-grids');
      if (!metricsEl || !kwEl || !gridsEl) return;

      const q = (document.getElementById('search-input').value || '').toLowerCase().trim();
      const visibleProjs = (globalScanData.projects || []).filter(p => {
        if (!isProjectVisibleByToggles(p)) return false;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return false;
        if (q && !JSON.stringify({
          id: p.projectId,
          n: p.name,
          m: (p.models || []).map(x => x.modelId || x.model),
          u: (p.usersUsage || []).map(x => x.userEmail),
          c: (p.credentialsUsage || []).map(x => x.resolvedName || x.credentialId),
          k: (p.aiLogForensics && p.aiLogForensics.securityKeywords) || []
        }).toLowerCase().includes(q)) return false;
        return true;
      });

      const d = _aggregateExecutiveDashboardMetrics(agg, q, visibleProjs);
      _renderExecutiveDashboardKpiCards(metricsEl, d, visibleProjs.length);
      _renderExecutiveDashboardKeywordsAndGrids(kwEl, gridsEl, d, visibleProjs);
    }

    // Invisible, attribute-only marker used by the table dropdown filters. It is NOT in innerText, so free-text search
    // and the CSV export never see it (see _rowFilterTokens in views_security_and_modals.js).
    function jtRowToken(token) {
      return `<span class="hidden" data-jt-token="${escapeHtml(token)}" aria-hidden="true"></span>`;
    }

    // VISTA 1: TABELLA PROGETTI PULITA E LEGGIBILE
    function renderProjectsTable(agg) {
      const tbody = document.getElementById('projects-tbody');
      const onlyActive = document.getElementById('filter-only-active').checked;
      const q = (document.getElementById('search-input').value || '').toLowerCase().trim();

      const list = (globalScanData.projects || []).filter(p => {
        if (!isProjectVisibleByToggles(p)) return false;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return false;
        if (onlyActive && !(p.inferenceRequests > 0) && !p.totalTokens && !(p.estimatedCostUsd > 0)) return false;
        if (q) {
          const hay = `${p.projectId} ${p.name} ${(p.models || []).map(m => m.modelId).join(' ')} ${(p.vertexFeatures || []).map(f => f.name).join(' ')}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      if (list.length === 0) {
        setSafeHtml(tbody, `<tr><td colspan="8" class="py-10 text-center text-slate-400">No projects match the selected filters.</td></tr>`);
        return;
      }

      setSafeHtml(tbody, list.map(p => {
        const perms = p.permissions || {};
        const areas = perms.areas || {};
        const monArea = areas.monitoring || { granted: true };
        const suArea = areas.serviceUsage || { granted: true };
        const maArea = areas.modelArmor || { granted: true };
        const billInfoArea = areas.billingInfo || { granted: true };
        const isSelected = agg.selProj === p.projectId;
        const isAiStudioFree = (p.skippedNoBilling || !p.billingEnabled) && (p.isAiStudioProject || p.aiActive || (p.apiKeys || []).length > 0);

        // CASO 0: Google ha limitato le richieste (429) e non ci sono dati precedenti: non verificato, NON negato
        if (p.transientError && !p.staleFromPreviousScan) {
          return `
            <tr class="hover:bg-amber-50/40">
              <td class="py-3 px-4">
                <div class="font-bold text-slate-900">${escapeHtml(p.name)}</div>
                ${p.name === p.projectId ? '' : `<div class="text-[11px] text-slate-500 mono">${escapeHtml(p.projectId)}</div>`}
              </td>
              <td class="py-3 px-4">
                ${jtTipChip('jt-badge jt-badge--amber rounded-full bg-amber-50 text-amber-800 border border-amber-200', 'ico-refresh', 'Not verified', `Not verified (Google rate limit)${p.error ? ': ' + p.error : ''}`)}
              </td>
              <td colspan="5" class="py-3 px-4 text-amber-800 text-[11px]">
                Google rate-limited requests during the scan: the project stays in the list and will be verified on the next scan.
              </td>
              <td class="py-3 px-4 text-right">
                <button type="button" data-jt-click="openProjectModal(${jsArg(p.projectId)})" class="px-2.5 py-1 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600 font-semibold text-[11px] cursor-pointer">
                  Details
                </button>
              </td>
            </tr>
          `;
        }

        // CASO A: Senza Billing (e non progetto AI Studio attivo)
        if ((p.skippedNoBilling || !p.billingEnabled) && !isAiStudioFree) {
          const is403 = billInfoArea.granted === false;
          return `
            <tr class="hover:bg-slate-50 text-slate-400">
              <td class="py-3 px-4">
                <div class="font-bold text-slate-600">${escapeHtml(p.name)}</div>
                ${p.name === p.projectId ? '' : `<div class="text-[11px] mono">${escapeHtml(p.projectId)}</div>`}
              </td>
              <td class="py-3 px-4">
                <span class="jt-badge ${is403 ? 'jt-badge--red bg-rose-50 text-rose-700 border border-rose-200' : 'jt-badge--gray bg-slate-100 text-slate-500'} px-2 py-0.5 rounded-full text-[11px] font-semibold">
                  ${is403 ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> Billing 403' : 'No Billing'}
                </span>
              </td>
              <td colspan="5" class="py-3 px-4 text-slate-400">
                ${is403 ? 'Permission denied to verify Billing Account' : 'Project without active billing'}
              </td>
              <td class="py-3 px-4 text-right">
                <button type="button" data-jt-click="openProjectModal(${jsArg(p.projectId)})" class="px-2.5 py-1 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600 font-semibold text-[11px] cursor-pointer">
                  Details
                </button>
              </td>
            </tr>
          `;
        }

        // CASO B: Accesso 403 totale su Monitoring e ServiceUsage
        if (p.scanStatus === 'NO_PERMISSIONS_403' || (!monArea.granted && !suArea.granted)) {
          return `
            <tr class="bg-rose-50/40 hover:bg-rose-50/80 transition">
              <td class="py-3.5 px-4">
                <div class="font-bold text-slate-900">${escapeHtml(p.name)}</div>
                ${p.name === p.projectId ? '' : `<div class="text-[11px] text-slate-500 mono">${escapeHtml(p.projectId)}</div>`}
              </td>
              <td class="py-3.5 px-4">
                <button type="button" data-jt-click="openProjectModal(${jsArg(p.projectId)})" class="jt-badge jt-badge--red px-2.5 py-1 rounded-full bg-rose-100 text-rose-700 border border-rose-200 text-[11px] font-bold cursor-pointer" title="Click to see which IAM permissions are missing">
                  <svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> Access Denied (${escapeHtml(perms.iamGrantedCount || 1)}/${escapeHtml(perms.iamTotalCount || 12)})
                </button>
              </td>
              <td class="py-3.5 px-4 text-rose-700 font-medium"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> Unreadable (403)</td>
              <td class="py-3.5 px-4 text-rose-700"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403</td>
              <td class="py-3.5 px-4 text-right text-rose-700 mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403</td>
              <td class="py-3.5 px-4 text-right text-rose-700 mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403</td>
              <td class="py-3.5 px-4 text-right text-rose-700 font-bold mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403</td>
              <td class="py-3.5 px-4 text-right">
                <button type="button" data-jt-click="openProjectModal(${jsArg(p.projectId)})" class="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-semibold text-[11px] cursor-pointer">
                  View Permissions
                </button>
              </td>
            </tr>
          `;
        }

        // Badge Permessi Pulito
        let permBadge = '';
        if (p.staleFromPreviousScan) {
          permBadge = jtTipChip('jt-badge jt-badge--amber rounded-full bg-amber-50 text-amber-800 border border-amber-200 cursor-pointer', 'ico-refresh', 'Not verified', `Not verified (Google rate limit), data from the previous scan${p.error ? ': ' + p.error : ''}`, `data-jt-click="openProjectModal(${jsArg(p.projectId)})"`);
        } else if (perms.accessLevel === 'FULL') {
          permBadge = jtTipChip('jt-badge jt-badge--green rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 cursor-pointer', 'ico-check', `Full (${perms.iamGrantedCount || 12}/${perms.iamTotalCount || 12})`, 'Full IAM permissions: click for details', `data-jt-click="openProjectModal(${jsArg(p.projectId)})"`);
        } else {
          const missingText = (perms.missingSummary || []).join(', ');
          permBadge = jtTipChip('jt-badge jt-badge--amber rounded-full bg-amber-50 text-amber-800 border border-amber-200 cursor-pointer', 'ico-alert', `Partial (${perms.iamGrantedCount || 0}/${perms.iamTotalCount || 12})`, `403 on: ${missingText}`, `data-jt-click="openProjectModal(${jsArg(p.projectId)})"`);
        }

        // Badge Data Residency & AI Studio
        const dr = p.dataResidency || {};
        let extraBadges = '';
        if (p.isAiStudioProject) {
          extraBadges += jtTipChip('jt-badge jt-badge--amber bg-amber-50 text-amber-800 border border-amber-200', 'ico-terminal', 'AI Studio', `AI Studio ${isAiStudioFree ? '(Free-Tier)' : '(Pay-As-You-Go)'}`);
        }
        if (dr.status && dr.status !== 'NO_TRAFFIC') {
          const drStyle = dr.status === 'ITALY_LOCAL' || dr.status === 'EU_COMPLIANT'
            ? 'jt-badge--green bg-emerald-50 text-emerald-700 border-emerald-200'
            : (dr.status === 'NON_EU_ALERT' ? 'jt-badge--red bg-rose-50 text-rose-700 border-rose-200' : 'jt-badge--blue bg-blue-50 text-blue-700 border-blue-200');
          const drShortHtml = dr.status === 'ITALY_LOCAL' ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Milan' : (dr.status === 'EU_COMPLIANT' ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> EU' : (dr.status === 'NON_EU_ALERT' ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> Non-EU' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Global'));
          extraBadges += `<span class="jt-badge px-1.5 py-0.5 rounded border text-[9px] font-bold ${escapeHtml(drStyle)}" title="${escapeHtml(dr.label || '')}">${drShortHtml}</span>`;
        }

        // Servizi AI Attivi (Max 2 pillole pulite + contatore)
        const feats = p.vertexFeatures || [];
        const maxShow = 2;
        let servicesHtml = feats.slice(0, maxShow).map(f =>
          jtTipChip('jt-badge jt-badge--gray inline-block max-w-[11rem] truncate align-top rounded-md bg-slate-100 text-slate-700 mr-1 mb-1', '', f.name, f.name)
        ).join('');
        if (feats.length > maxShow) {
          servicesHtml += jtTipChip('jt-badge jt-badge--blue inline-block align-top rounded-md bg-blue-50 text-blue-700 mb-1', '', `+${feats.length - maxShow}`, feats.slice(maxShow).map(f => f.name).join('\n'));
        }
        if (!servicesHtml) {
          servicesHtml = p.aiActive ? `<span class="text-slate-400">AI API Enabled</span>` : `<span class="text-slate-400">No AI service</span>`;
        }

        // Stato Model Armor Pulito
        const ma = p.modelArmor || { enabled: false };
        let maHtml = `<span class="text-slate-400 text-[11px]">Inactive</span>`;
        if (ma.enabled) {
          if (ma.status === 'PERMISSION_DENIED' || !maArea.granted) {
            maHtml = `<span class="jt-badge jt-badge--red px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 text-[11px] font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403 Config</span>`;
          } else if (ma.status === 'CONFIGURED_ACTIVE') {
            maHtml = `<span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 text-[11px] font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-shield"/></svg> Active</span>`;
          } else {
            maHtml = `<span class="jt-badge jt-badge--blue px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 text-[11px] font-medium">Enabled (Default)</span>`;
          }
        }

        const callsHtml = monArea.granted
          ? `<span class="font-semibold ${p.inferenceRequests > 0 ? 'text-slate-900' : 'text-slate-400'}">${fmtNum(p.inferenceRequests || 0)}</span>`
          : `<span class="text-rose-600 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403</span>`;

        const tokensHtml = monArea.granted
          ? `<span class="${p.totalTokens > 0 ? 'text-slate-800 font-medium' : 'text-slate-400'}">${fmtTok(p.totalTokens)}</span>`
          : `<span class="text-rose-600 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403</span>`;

        const exclSqlUsd = p.excludedNonAiInfraCostUsd ?? (p.finopsExtended && p.finopsExtended.excludedNonAiInfraCostUsd) ?? 0;
        const costHtml = monArea.granted
          ? `<div><span class="text-sm font-extrabold ${p.estimatedCostUsd > 0 ? 'text-emerald-700' : 'text-slate-400'}">${fmtUsd(p.estimatedCostUsd)}</span> <span class="text-[11px] font-bold text-slate-600">(${fmtEur(p.estimatedCostUsd)})</span></div>
             ${isAiStudioFree ? `<div class="text-[10px] text-amber-700 font-semibold">Free-Tier AI Studio</div>` : ''}
             ${(p.infraCostUsd || 0) > 0 ? `<div class="text-[10px] text-[#0F2A4A] font-semibold">TCO AI: ${fmtEur(p.totalBillCostUsd || ((p.estimatedCostUsd || 0) + (p.infraCostUsd || 0)))} (Infra AI: ${fmtUsd(p.infraCostUsd)})</div>` : ''}
             ${exclSqlUsd > 0 ? `<div class="text-[10px] text-slate-500 font-semibold mono" title="Project with 0 AI calls: general Cloud SQL/Infra cost unrelated to AI, excluded from AI TCO">Infra AI: <b>$0.00</b> <span class="px-1 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">(Excluded non-AI SQL: $${exclSqlUsd.toFixed(2)})</span></div>` : ''}`
          : `<span class="text-rose-600 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-lock"/></svg> 403</span>`;

        return `
          <tr class="hover:bg-slate-50/90 transition ${isSelected ? 'bg-blue-50/50' : ''}">
            <td class="py-3.5 px-4">
              <div class="flex items-center gap-1.5 flex-wrap">
                <span class="font-bold text-slate-900 cursor-pointer hover:text-blue-700" data-jt-click="selectSingleProjectFilter(${jsArg(p.projectId)})" title="Click to filter the charts on this project">${escapeHtml(p.name)}</span>
                ${extraBadges}
              </div>
              ${p.name === p.projectId ? '' : `<div class="text-[11px] text-slate-400 mono">${escapeHtml(p.projectId)}</div>`}
              ${jtRowToken((p.inferenceRequests > 0 || p.totalTokens > 0 || p.estimatedCostUsd > 0) ? 'prj-active' : 'prj-idle')}
            </td>
            <td class="py-3.5 px-4">${permBadge}</td>
            <td class="py-3.5 px-4">${servicesHtml}</td>
            <td class="py-3.5 px-4">${maHtml}</td>
            <td class="py-3.5 px-4 text-right mono">${callsHtml}</td>
            <td class="py-3.5 px-4 text-right mono">${tokensHtml}</td>
            <td class="py-3.5 px-4 text-right mono">${costHtml}</td>
            <td class="py-3.5 px-4 text-right whitespace-nowrap">
              <button type="button" data-jt-click="selectSingleProjectFilter(${jsArg(p.projectId)})" class="px-2.5 py-1 rounded-lg ${isSelected ? 'bg-[#0F2A4A] text-white' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'} font-semibold text-[11px] mr-1 cursor-pointer transition">
                ${isSelected ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Filtered' : 'Filter'}
              </button>
              <button type="button" data-jt-click="openProjectModal(${jsArg(p.projectId)})" class="px-2.5 py-1 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-700 font-semibold text-[11px] cursor-pointer transition">
                Details
              </button>
            </td>
          </tr>
        `;
      }).join(''));
    }

    // VISTA 2: GIORNALIERO
    function renderDailyTable(agg) {
      const tbody = document.getElementById('daily-tbody');
      const onlyActive = document.getElementById('filter-only-active').checked;
      const q = (document.getElementById('search-input').value || '').toLowerCase().trim();

      let runningCost = 0;
      const withCumulative = agg.timeline.map(d => {
        runningCost += (d.costUsd || 0);
        return { ...d, cumulativeCostUsd: runningCost };
      });

      const rows = withCumulative.filter(d => {
        if (onlyActive && !(d.costUsd > 0) && !(d.inferenceRequests > 0)) return false;
        if (q && !d.date.toLowerCase().includes(q)) return false;
        return true;
      }).reverse();

      if (rows.length === 0) {
        setSafeHtml(tbody, `<tr><td colspan="10" class="py-10 text-center text-slate-400">No daily data found.</td></tr>`);
        return;
      }

      setSafeHtml(tbody, rows.map(d => `
        <tr class="hover:bg-slate-50 transition ${d.costUsd > 0 || d.inferenceRequests > 0 ? '' : 'text-slate-400'}">
          <td class="py-3 px-4 font-semibold text-slate-800 mono">${escapeHtml(d.date)}</td>
          <td class="py-3 px-4 text-right mono font-bold ${d.inferenceRequests > 0 ? 'text-blue-700' : 'text-slate-400'}">${fmtNum(d.inferenceRequests)}</td>
          <td class="py-3 px-4 text-right mono text-slate-400">${fmtNum(d.systemRequests)}</td>
          <td class="py-3 px-4 text-right mono ${d.errors429 > 0 ? 'text-rose-600 font-bold' : 'text-slate-400'}">${fmtNum(d.errors429)}</td>
          <td class="py-3 px-4 text-right mono">${fmtNum(d.inputTokens)}</td>
          <td class="py-3 px-4 text-right mono">${fmtNum(d.outputTokens)}</td>
          <td class="py-3 px-4 text-right mono text-emerald-700">${fmtNum(d.cachedTokens)}</td>
          <td class="py-3 px-4 text-right mono font-bold text-slate-800">${fmtTok(d.tokens)}</td>
          <td class="py-3 px-4 text-right mono font-extrabold ${d.costUsd > 0 ? 'text-emerald-700' : 'text-slate-400'}">${fmtUsd(d.costUsd)}</td>
          <td class="py-3 px-4 text-right mono text-slate-500">${fmtUsd(d.cumulativeCostUsd)}</td>
        </tr>
      `).join(''));
    }

    function _renderSingleCredentialRow(r, selCred) {
      const isSelected = selCred === `${r.projectId}||${r.credentialId}`;
      const badgeStyle = r.type === 'API_KEY'
        ? 'jt-badge--amber bg-amber-50 text-amber-800 border-amber-200'
        : (r.type === 'SERVICE_ACCOUNT' ? 'jt-badge--blue bg-blue-50 text-blue-700 border-blue-200' : 'jt-badge--purple bg-purple-50 text-purple-700 border-purple-200');

      let formulaLabel = '';
      if (r.costSource === 'GEMINI_API_PAYLOAD_BYTES') {
        formulaLabel = `<div class="text-[10px] text-amber-700 font-semibold">Payload: ${fmtBytes(r.requestBytes)} In / ${fmtBytes(r.responseBytes)} Out</div>`;
      } else if (r.costSource === 'GEMINI_API_ESTIMATE') {
        formulaLabel = `<div class="text-[10px] text-amber-700 font-semibold">$0.00259 × ${fmtNum(r.ok200Inference)} OK</div>`;
      } else if (r.costSource && r.costSource.includes('VERTEX_TOKEN_METRICS')) {
        formulaLabel = `<div class="text-[10px] text-blue-700 font-semibold">Actual Vertex Tokens</div>`;
      } else if (r.costSource && (r.costSource.includes('AGENTSPACE') || r.costSource.includes('CODE_ASSIST') || r.costSource.includes('DOCUMENT_AI'))) {
        formulaLabel = `<div class="text-[10px] text-purple-700 font-semibold">Tokens + AI Service</div>`;
      } else if (r.costUsd === 0) {
        formulaLabel = `<div class="text-[10px] text-slate-400">$0 (No usage)</div>`;
      }

      const totalFailed = r.failedInference || (r.errors429 + r.otherErrors);
      const isStreamingIde = (r.infMethods || '').includes('StreamGenerateContent') && r.type === 'API_KEY';

      return `
        <tr class="hover:bg-slate-50 transition ${isSelected ? 'bg-blue-50/50' : ''}">
          <td class="py-3 px-4" data-sort-val="${escapeHtml(r.name)}">
            <div class="flex items-center gap-1.5 flex-wrap">
              <span class="font-bold text-slate-900">${escapeHtml(r.name)}</span>
              ${r.isConsoleInternalKey ? jtTipChip('jt-badge jt-badge--gray bg-slate-100 text-slate-700 border border-slate-300', 'ico-terminal', 'Console UI', 'GCP Console / Colab UI') : ''}
              ${r.tokensEstimatedFromBytes ? jtTipChip('jt-badge jt-badge--amber bg-amber-50 text-amber-800 border border-amber-200', '', 'estimated from bytes', 'Some days: tokens are not from exact metrics but estimated from payload bytes') : ''}
              ${r.isAiStudioKey ? jtTipChip('jt-badge jt-badge--amber bg-amber-100 text-amber-900 border border-amber-300', 'ico-terminal', 'AI Studio', 'Google AI Studio key') : ''}
              ${isStreamingIde ? jtTipChip('jt-badge jt-badge--purple bg-indigo-50 text-indigo-700 border border-indigo-200', 'ico-bolt', 'Antigravity IDE', 'Antigravity / Streaming IDE (StreamGenerateContent)') : ''}
            </div>
            <div class="text-[11px] text-slate-400 mono">${escapeHtml(r.credentialId)}</div>
            ${jtRowToken(r.inferenceRequests > 0 ? 'cred-traffic' : 'cred-idle')}
            ${r.ownerEmail ? `<div class="text-[10px] text-emerald-700 font-semibold mt-0.5 flex items-center gap-1 flex-wrap"><span>Created by:</span> ${renderUserEmailClickable(r.ownerEmail)}</div>` : ''}
          </td>
          <td class="py-3 px-4">
            <span class="jt-badge px-2 py-0.5 rounded-full border text-[10px] font-bold mono ${escapeHtml(badgeStyle)}">${escapeHtml(r.type)}</span>
          </td>
          <td class="py-3 px-4 mono text-slate-600">${escapeHtml(r.projectId)}</td>
          <td class="py-3 px-4">
            <div class="text-slate-700 font-medium">${escapeHtml(r.service)}</div>
            <div class="text-[11px] text-slate-400 mono truncate max-w-xs">${escapeHtml(r.infMethods || 'System calls only ($0)')}</div>
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.ok200Inference)}">
            <div class="font-bold ${r.ok200Inference > 0 ? 'text-slate-900' : 'text-slate-400'}">${fmtNum(r.ok200Inference)}</div>
            ${r.inferenceRequests !== r.ok200Inference ? `<div class="text-[10px] text-slate-400">of ${fmtNum(r.inferenceRequests)} total</div>` : ''}
            ${(r.todayCalls > 0 || r.yesterdayCalls > 0) ? `<div class="text-[10px] text-indigo-700 font-semibold mt-0.5">Today: ${fmtNum(r.todayCalls)} · Yesterday: ${fmtNum(r.yesterdayCalls)}</div>` : ''}
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(totalFailed)}">
            <div class="${totalFailed > 0 ? 'text-rose-600 font-bold' : 'text-slate-400'}">${fmtNum(totalFailed)}</div>
            ${r.errors429 > 0 ? `<div class="text-[10px] text-rose-500">${fmtNum(r.errors429)} HTTP 429</div>` : (totalFailed > 0 ? `<div class="text-[10px] text-slate-400">404/503 ($0)</div>` : '')}
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.totalTokens)}">
            <div class="text-slate-800 font-bold">${fmtTok(r.totalTokens)}</div>
            <div class="text-[10px] text-slate-400">In: ${fmtTok(r.inputTokens)} · Out: ${fmtTok(r.outputTokens)}</div>
            ${(r.todayTokens > 0 || r.yesterdayTokens > 0) ? `<div class="text-[10px] text-indigo-700 font-semibold">Today: ${fmtTok(r.todayTokens)} · Yesterday: ${fmtTok(r.yesterdayTokens)}</div>` : ''}
            ${formulaLabel}
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.cacheSavingsUsd)}">
            ${r.grossCostUsd > 0 || r.cacheSavingsUsd > 0
              ? `<div class="text-slate-700 font-semibold">${fmtUsd(r.grossCostUsd)} <span class="text-[10px] text-slate-400">(${fmtEur(r.grossCostUsd)})</span></div>
                 ${r.cacheSavingsUsd > 0 ? `<div class="text-[10px] text-emerald-700 font-bold">Cache: -${fmtEur(r.cacheSavingsUsd)}</div>` : `<div class="text-[10px] text-slate-400">Cache: $0</div>`}`
              : `<span class="text-slate-300">—</span>`
            }
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.costUsd)}">
            <div class="font-extrabold text-sm ${r.costUsd > 0 ? 'text-emerald-700' : 'text-slate-400'}">${fmtUsd(r.costUsd)} <span class="text-xs font-bold text-slate-500">(${fmtEur(r.costUsd)})</span></div>
            ${(r.todayCostUsd > 0 || r.yesterdayCostUsd > 0)
              ? `<div class="text-[10px] text-amber-800 font-bold mt-0.5">Today: ${fmtUsd(r.todayCostUsd)} (${fmtEur(r.todayCostUsd)})<br>Yesterday: ${fmtUsd(r.yesterdayCostUsd)} (${fmtEur(r.yesterdayCostUsd)})</div>`
              : ''}
          </td>
          <td class="py-3 px-4 text-right">
            <button type="button" data-jt-click="selectSingleCredentialFilter(${jsArg(r.projectId)}, ${jsArg(r.credentialId)})" class="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-[11px] cursor-pointer">
              Filter
            </button>
          </td>
        </tr>
      `;
    }

    // VISTA 3: CREDENZIALI (API KEYS & SERVICE ACCOUNTS)
    function renderCredentialsTable(agg) {
      const tbody = document.getElementById('credentials-tbody');
      const onlyActive = document.getElementById('filter-only-active').checked;
      const q = (document.getElementById('search-input').value || '').toLowerCase().trim();

      const rows = [];
      (globalScanData.projects || []).forEach(p => {
        if (!isProjectVisibleByToggles(p)) return;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return;

        (p.credentialsUsage || []).forEach(c => {
          const cType = c.resolvedType || 'OAUTH_CLIENT';
          if (agg.selType !== 'ALL' && cType !== agg.selType) return;
          const compKey = `${p.projectId}||${c.credentialId}`;
          if (agg.selCred !== 'ALL' && compKey !== agg.selCred) return;

          const infReqs = c.inferenceRequests || 0;
          const ok200Inf = (c.ok200Inference !== undefined && c.ok200Inference !== null) ? c.ok200Inference : infReqs;
          const failedInf = Math.max(0, infReqs - ok200Inf);
          const dSer = c.dailySeries || {};
          const sortedDays = Object.keys(dSer).sort();
          const latestDay = c.todayDate || (sortedDays.length > 0 ? sortedDays[sortedDays.length - 1] : '');
          const prevDay = c.yesterdayDate || (sortedDays.length > 1 ? sortedDays[sortedDays.length - 2] : '');
          const tBucket = dSer[latestDay] || {};
          const yBucket = dSer[prevDay] || {};

          rows.push({
            projectId: p.projectId,
            credentialId: c.credentialId,
            name: c.resolvedName || c.credentialId,
            type: cType,
            ownerEmail: c.ownerEmail || '',
            isConsoleInternalKey: Boolean(c.isConsoleInternalKey),
            isAiStudioKey: Boolean(c.isAiStudioKey),
            service: c.service,
            infMethods: (c.inferenceMethods || []).join(', '),
            inferenceRequests: infReqs,
            ok200Inference: ok200Inf,
            failedInference: failedInf,
            requests: c.requests || 0,
            errors429: c.errors429 || 0,
            otherErrors: c.otherErrors || 0,
            requestBytes: c.requestBytes || 0,
            responseBytes: c.responseBytes || 0,
            inputTokens: c.inputTokens || 0,
            outputTokens: c.outputTokens || 0,
            cachedTokens: c.cachedTokens || 0,
            totalTokens: c.totalTokens || 0,
            costSource: c.costSource || '',
            tokensEstimatedFromBytes: Boolean(c.tokensEstimatedFromBytes),
            grossCostUsd: c.grossCostUsd || c.estimatedCostUsd || 0,
            cacheSavingsUsd: c.cacheSavingsUsd || 0,
            costUsd: c.estimatedCostUsd || 0,
            todayCalls: c.todayCalls !== undefined ? c.todayCalls : (tBucket.inferenceRequests || tBucket.requests || 0),
            todayTokens: c.todayTokens !== undefined ? c.todayTokens : (tBucket.tokens || 0),
            todayCostUsd: c.todayCostUsd !== undefined ? c.todayCostUsd : (tBucket.costUsd || 0),
            yesterdayCalls: c.yesterdayCalls !== undefined ? c.yesterdayCalls : (yBucket.inferenceRequests || yBucket.requests || 0),
            yesterdayTokens: c.yesterdayTokens !== undefined ? c.yesterdayTokens : (yBucket.tokens || 0),
            yesterdayCostUsd: c.yesterdayCostUsd !== undefined ? c.yesterdayCostUsd : (yBucket.costUsd || 0)
          });
        });
      });

      const filtered = rows.filter(r => {
        if (onlyActive && r.inferenceRequests === 0 && r.costUsd === 0) return false;
        if (q) {
          const hay = `${r.name} ${r.credentialId} ${r.ownerEmail} ${r.projectId} ${r.service} ${r.infMethods}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      }).sort((a, b) => (b.costUsd - a.costUsd) || (b.inferenceRequests - a.inferenceRequests));

      const credActiveBadge = document.getElementById('subtab-badge-cred-active');
      if (credActiveBadge) credActiveBadge.textContent = filtered.length;

      if (filtered.length === 0) {
        setSafeHtml(tbody, `<tr><td colspan="10" class="py-10 text-center text-slate-400">No API keys or service accounts found for the current filters.</td></tr>`);
      } else {
        setSafeHtml(tbody, filtered.map(r => _renderSingleCredentialRow(r, agg.selCred)).join(''));
      }

      // Renderizza sempre l'Inventario Completo Service Account IAM (53 SA) & Audit Chiavi Esportate
      renderServiceAccountsInventorySection(agg, q);
    }

    function renderServiceAccountsInventorySection(agg, q) {
      const saTbody = document.getElementById('service-accounts-tbody');
      const kpiBar = document.getElementById('sa-inventory-kpi-bar');
      if (!saTbody || !globalScanData) return;

      // Mappa di consumo AI per Service Account dai credentialsUsage dei progetti
      const saUsageMap = {};
      const visibleProjSet = new Set();
      (globalScanData.projects || []).forEach(p => {
        if (!isProjectVisibleByToggles(p)) return;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return;
        visibleProjSet.add(p.projectId);
        (p.credentialsUsage || []).forEach(c => {
          if (c.resolvedType === 'SERVICE_ACCOUNT' || (c.credentialId || '').includes('gserviceaccount.com')) {
            const key = `${p.projectId}||${(c.credentialId || '').toLowerCase()}`;
            saUsageMap[key] = {
              calls: c.inferenceRequests || c.requests || 0,
              ok200Calls: (c.ok200Inference !== undefined && c.ok200Inference !== null) ? c.ok200Inference : (c.inferenceRequests || 0),
              tokens: c.totalTokens || 0,
              costUsd: c.estimatedCostUsd || 0
            };
          }
        });
      });

      const rawSummaryInv = globalScanData.summary && globalScanData.summary.serviceAccountsInventory;
      const summaryInv = Array.isArray(rawSummaryInv)
        ? rawSummaryInv
        : (rawSummaryInv && Array.isArray(rawSummaryInv.items) ? rawSummaryInv.items : null);

      const rawList = [];
      if (summaryInv && summaryInv.length > 0) {
        summaryInv.forEach(sa => {
          if (agg.selProj !== 'ALL' && sa.projectId !== agg.selProj) return;
          if (agg.selProj === 'ALL' && visibleProjSet.size > 0 && !visibleProjSet.has(sa.projectId)) return;
          rawList.push(sa);
        });
      } else {
        (globalScanData.projects || []).forEach(p => {
          if (!visibleProjSet.has(p.projectId)) return;
          (p.serviceAccounts || []).forEach(sa => {
            rawList.push({
              ...sa,
              projectId: p.projectId,
              projectName: p.name || p.projectId
            });
          });
        });
      }

      const saRows = rawList.map(sa => {
        const email = sa.email || '';
        const pId = sa.projectId || '';
        const usage = saUsageMap[`${pId}||${email.toLowerCase()}`] || {};
        const exportedKeys = sa.exportedKeys || sa.userManagedKeys || [];
        const expCount = sa.userManagedKeysCount !== undefined ? sa.userManagedKeysCount : exportedKeys.length;
        const calls = sa.calls !== undefined ? sa.calls : (sa.inferenceRequests !== undefined ? sa.inferenceRequests : (usage.calls || 0));
        const ok200 = sa.ok200Calls !== undefined ? sa.ok200Calls : (usage.ok200Calls !== undefined ? usage.ok200Calls : calls);
        const tokens = sa.tokens !== undefined ? sa.tokens : (sa.totalTokens !== undefined ? sa.totalTokens : (usage.tokens || 0));
        const costUsd = sa.costUsd !== undefined ? sa.costUsd : (sa.estimatedCostUsd !== undefined ? sa.estimatedCostUsd : (usage.costUsd || 0));
        const emailLow = email.toLowerCase();
        const isDefault = sa.isDefaultGcpSa !== undefined
          ? Boolean(sa.isDefaultGcpSa)
          : (emailLow.includes('-compute@developer.gserviceaccount.com') || emailLow.includes('@appspot.gserviceaccount.com') || emailLow.includes('@cloudservices.gserviceaccount.com') || emailLow.includes('@cloudbuild.gserviceaccount.com'));

        return {
          email,
          displayName: sa.displayName || email.split('@')[0] || 'Service Account',
          projectId: pId,
          projectName: sa.projectName || pId,
          disabled: Boolean(sa.disabled),
          isDefault,
          userManagedKeysCount: expCount,
          exportedKeys,
          calls,
          ok200,
          tokens,
          costUsd
        };
      }).filter(r => {
        if (q) {
          const hay = `${r.displayName} ${r.email} ${r.projectId} ${r.projectName}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      }).sort((a, b) => (b.userManagedKeysCount - a.userManagedKeysCount) || (b.costUsd - a.costUsd) || (b.calls - a.calls) || a.email.localeCompare(b.email));

      const credSaBadge = document.getElementById('subtab-badge-cred-sa');
      if (credSaBadge) credSaBadge.textContent = saRows.length;

      if (kpiBar) {
        const totalSa = saRows.length;
        const withExportedKeys = saRows.filter(x => x.userManagedKeysCount > 0).length;
        const totalExpKeys = saRows.reduce((s, x) => s + x.userManagedKeysCount, 0);
        const withTraffic = saRows.filter(x => x.calls > 0 || x.costUsd > 0).length;
        const activeSa = saRows.filter(x => !x.disabled).length;
        setSafeHtml(kpiBar, `
          <span class="jt-chip jt-chip--neutral px-2.5 py-1 rounded-lg bg-slate-100 border border-slate-200 font-bold text-slate-800 mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Total SAs: ${escapeHtml(totalSa)} (${escapeHtml(activeSa)} active)</span>
          <span class="jt-chip ${withExportedKeys > 0 ? 'jt-chip--red bg-rose-50 border-rose-200 text-rose-800' : 'jt-chip--green bg-emerald-50 border-emerald-200 text-emerald-800'} px-2.5 py-1 rounded-lg border font-bold mono">
            ${withExportedKeys > 0 ? `<svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> Exported Keys: ${escapeHtml(withExportedKeys)} SA (${escapeHtml(totalExpKeys)} keys)` : `<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Zero Exported Keys (100% Zero-Trust)`}
          </span>
          <span class="jt-chip jt-chip--blue px-2.5 py-1 rounded-lg bg-blue-50 border border-blue-200 font-bold text-blue-800 mono"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> With AI Traffic: ${escapeHtml(withTraffic)} SA</span>
        `);
      }

      if (saRows.length === 0) {
        setSafeHtml(saTbody, `<tr><td colspan="7" class="py-8 text-center text-slate-400">No IAM service accounts found for the current filters.</td></tr>`);
        applyActiveSubTab('credentials');
        return;
      }

      setSafeHtml(saTbody, saRows.map(sa => {
        const statusBadge = sa.disabled
          ? `<span class="jt-badge jt-badge--red px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> Disabled</span>`
          : `<span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Active</span>`;
        const originBadge = sa.isDefault
          ? `<span class="jt-badge jt-badge--gray px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200 text-[10px] font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Default GCP</span>`
          : `<span class="jt-badge jt-badge--purple px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 text-[10px] font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Custom IAM</span>`;

        let keysBadge = '';
        if (sa.userManagedKeysCount > 0) {
          const keyDetails = (sa.exportedKeys || []).slice(0, 2).map(k => {
            const kId = (k.keyId || k.name || '').slice(0, 10);
            const kDate = (k.validAfterTime || '').slice(0, 10);
            return `${kId}${kDate ? ` (${kDate})` : ''}`;
          }).join(', ');
          keysBadge = `
            <div>
              ${jtTipChip('jt-badge jt-badge--red rounded-full bg-rose-100 text-rose-800 border border-rose-300', 'ico-alert', `${sa.userManagedKeysCount} Exported keys`, `${sa.userManagedKeysCount} Exported Static Keys (USER_MANAGED)`)}
              ${keyDetails ? `<div class="text-[10px] text-rose-700 mono mt-0.5">${escapeHtml(keyDetails)}</div>` : ''}
            </div>
          `;
        } else {
          keysBadge = jtTipChip('jt-badge jt-badge--green rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200', 'ico-check', '0 Keys', '0 Keys (Zero-Trust)');
        }

        const trafficTag = (sa.calls > 0 || sa.costUsd > 0)
          ? ' ' + jtTipChip('jt-badge jt-badge--blue ml-1.5 bg-blue-50 text-blue-700 border border-blue-200', 'ico-check', 'AI Traffic', 'With AI traffic in the period')
          : '';

        return `
          <tr class="hover:bg-slate-50 transition">
            <td class="py-3 px-4" data-sort-val="${escapeHtml(sa.displayName)}">
              <div class="font-bold text-slate-900 flex items-center flex-wrap">
                <span>${escapeHtml(sa.displayName)}</span>
                ${trafficTag}
              </div>
              <div class="text-[11px] text-slate-500 mono">${escapeHtml(sa.email)}</div>
              ${jtRowToken((sa.calls > 0 || sa.costUsd > 0) ? 'sa-traffic' : 'sa-dormant')}
            </td>
            <td class="py-3 px-4 mono text-slate-600 font-semibold" data-sort-val="${escapeHtml(sa.projectId)}">
              <div>${escapeHtml(sa.projectId)}</div>
              ${sa.projectName && sa.projectName !== sa.projectId ? `<div class="text-[10px] text-slate-400 font-sans">${escapeHtml(sa.projectName)}</div>` : ''}
            </td>
            <td class="py-3 px-4" data-sort-val="${sa.disabled ? 0 : 1}">
              <div class="flex flex-wrap items-center gap-1">${statusBadge} ${originBadge}</div>
            </td>
            <td class="py-3 px-4" data-sort-val="${escapeHtml(sa.userManagedKeysCount)}">
              ${keysBadge}
            </td>
            <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(sa.calls)}">
              <span class="font-bold ${sa.calls > 0 ? 'text-slate-900' : 'text-slate-400'}">${fmtNum(sa.ok200)}</span>
              ${sa.calls !== sa.ok200 ? `<span class="text-[10px] text-slate-400"> / ${fmtNum(sa.calls)}</span>` : ''}
            </td>
            <td class="py-3 px-4 text-right mono ${sa.tokens > 0 ? 'text-slate-800 font-bold' : 'text-slate-400'}" data-sort-val="${escapeHtml(sa.tokens)}">
              ${fmtTok(sa.tokens)}
            </td>
            <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(sa.costUsd)}">
              <span class="font-extrabold ${sa.costUsd > 0 ? 'text-emerald-700' : 'text-slate-400'}">${fmtUsd(sa.costUsd)}</span>
              <span class="text-[11px] text-slate-500">(${fmtEur(sa.costUsd)})</span>
            </td>
          </tr>
        `;
      }).join(''));
    }

    // VISTA 3B: COSTI E UTILIZZO PER SINGOLO UTENTE (OAUTH + API KEYS PERSONALI / ANTIGRAVITY / AI STUDIO / NOTEBOOK)
    function _collectUsersUsageRows(agg) {
      const rows = [];
      let totalOauthPoolCost = 0;
      let totalApiKeysCost = 0;

      (globalScanData.projects || []).forEach(p => {
        if (!isProjectVisibleByToggles(p)) return;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return;

        const credMap = {};
        (p.credentialsUsage || []).forEach(c => {
          credMap[c.credentialId] = c;
          const cType = c.resolvedType || 'OAUTH_CLIENT';
          if (cType === 'API_KEY') totalApiKeysCost += (c.estimatedCostUsd || 0);
          else if (cType !== 'SERVICE_ACCOUNT') totalOauthPoolCost += (c.estimatedCostUsd || 0);
        });

        const pDailyKeys = Object.keys(p.dailySeries || {}).sort();
        const latestProjDay = pDailyKeys.length > 0 ? pDailyKeys[pDailyKeys.length - 1] : '';
        const prevProjDay = pDailyKeys.length > 1 ? pDailyKeys[pDailyKeys.length - 2] : '';

        (p.usersUsage || []).forEach(u => {
          const uEmailLow = (u.userEmail || '').toLowerCase();
          let keysDetails = u.apiKeysDetails || [];
          if (keysDetails.length === 0 && (p.apiKeys || []).length > 0) {
            keysDetails = (p.apiKeys || [])
              .filter(k => (k.ownerEmail || '').toLowerCase() === uEmailLow)
              .map(k => {
                const cObj = credMap[`apikey:${k.uid}`] || {};
                const dSer = cObj.dailySeries || {};
                const tD = k.todayDate || latestProjDay;
                const yD = k.yesterdayDate || prevProjDay;
                const tB = dSer[tD] || {};
                const yB = dSer[yD] || {};
                return {
                  uid: k.uid,
                  displayName: k.displayName || k.uid,
                  status: k.status || 'ACTIVE',
                  calls: k.inferenceRequests || k.requests || 0,
                  ok200Calls: k.ok200Inference !== undefined ? k.ok200Inference : (k.inferenceRequests || 0),
                  inputTokens: k.inputTokens || 0,
                  outputTokens: k.outputTokens || 0,
                  totalTokens: k.totalTokens || 0,
                  requestBytes: k.requestBytes || 0,
                  responseBytes: k.responseBytes || 0,
                  grossCostUsd: k.grossCostUsd || k.estimatedCostUsd || 0,
                  cacheSavingsUsd: k.cacheSavingsUsd || 0,
                  costUsd: k.estimatedCostUsd || 0,
                  todayCalls: k.todayCalls !== undefined ? k.todayCalls : (tB.inferenceRequests || tB.requests || 0),
                  todayTokens: k.todayTokens !== undefined ? k.todayTokens : (tB.tokens || 0),
                  todayCostUsd: k.todayCostUsd !== undefined ? k.todayCostUsd : (tB.costUsd || 0),
                  yesterdayCalls: k.yesterdayCalls !== undefined ? k.yesterdayCalls : (yB.inferenceRequests || yB.requests || 0),
                  yesterdayTokens: k.yesterdayTokens !== undefined ? k.yesterdayTokens : (yB.tokens || 0),
                  yesterdayCostUsd: k.yesterdayCostUsd !== undefined ? k.yesterdayCostUsd : (yB.costUsd || 0),
                  methods: k.inferenceMethods || k.methods || []
                };
              })
              .sort((a, b) => (b.costUsd - a.costUsd) || (b.totalTokens - a.totalTokens));
          }

          const keysTodayCalls = u.apiKeysTodayCalls !== undefined ? u.apiKeysTodayCalls : keysDetails.reduce((s, x) => s + (x.todayCalls || 0), 0);
          const keysTodayTokens = u.apiKeysTodayTokens !== undefined ? u.apiKeysTodayTokens : keysDetails.reduce((s, x) => s + (x.todayTokens || 0), 0);
          const keysTodayCost = u.apiKeysTodayCostUsd !== undefined ? u.apiKeysTodayCostUsd : keysDetails.reduce((s, x) => s + (x.todayCostUsd || 0), 0);
          const keysYestCalls = u.apiKeysYesterdayCalls !== undefined ? u.apiKeysYesterdayCalls : keysDetails.reduce((s, x) => s + (x.yesterdayCalls || 0), 0);
          const keysYestTokens = u.apiKeysYesterdayTokens !== undefined ? u.apiKeysYesterdayTokens : keysDetails.reduce((s, x) => s + (x.yesterdayTokens || 0), 0);
          const keysYestCost = u.apiKeysYesterdayCostUsd !== undefined ? u.apiKeysYesterdayCostUsd : keysDetails.reduce((s, x) => s + (x.yesterdayCostUsd || 0), 0);

          const oauthDetails = Array.isArray(u.oauthClientsDetails) ? u.oauthClientsDetails : [];
          const vOauthCalls = u.vertexOauthCalls !== undefined ? u.vertexOauthCalls : oauthDetails.reduce((s, x) => s + (x.calls || 0), 0);
          const vOauthInTok = u.vertexOauthInputTokens !== undefined ? u.vertexOauthInputTokens : oauthDetails.reduce((s, x) => s + (x.inputTokens || 0), 0);
          const vOauthOutTok = u.vertexOauthOutputTokens !== undefined ? u.vertexOauthOutputTokens : oauthDetails.reduce((s, x) => s + (x.outputTokens || 0), 0);
          const vOauthCachedTok = u.vertexOauthCachedTokens !== undefined ? u.vertexOauthCachedTokens : oauthDetails.reduce((s, x) => s + (x.cachedTokens || 0), 0);
          const vOauthToks = u.vertexOauthTokens !== undefined ? u.vertexOauthTokens : oauthDetails.reduce((s, x) => s + (x.totalTokens || 0), 0);
          const vOauthGross = u.vertexOauthGrossCostUsd !== undefined ? u.vertexOauthGrossCostUsd : oauthDetails.reduce((s, x) => s + (x.grossCostUsd || 0), 0);
          const vOauthSav = u.vertexOauthCacheSavingsUsd !== undefined ? u.vertexOauthCacheSavingsUsd : oauthDetails.reduce((s, x) => s + (x.cacheSavingsUsd || 0), 0);
          const vOauthCost = u.vertexOauthCostUsd !== undefined ? u.vertexOauthCostUsd : oauthDetails.reduce((s, x) => s + (x.costUsd || 0), 0);
          const vOauthTodayCalls = u.vertexOauthTodayCalls !== undefined ? u.vertexOauthTodayCalls : oauthDetails.reduce((s, x) => s + (x.todayCalls || 0), 0);
          const vOauthTodayTokens = u.vertexOauthTodayTokens !== undefined ? u.vertexOauthTodayTokens : oauthDetails.reduce((s, x) => s + (x.todayTokens || 0), 0);
          const vOauthTodayCost = u.vertexOauthTodayCostUsd !== undefined ? u.vertexOauthTodayCostUsd : oauthDetails.reduce((s, x) => s + (x.todayCostUsd || 0), 0);
          const vOauthYestCalls = u.vertexOauthYesterdayCalls !== undefined ? u.vertexOauthYesterdayCalls : oauthDetails.reduce((s, x) => s + (x.yesterdayCalls || 0), 0);
          const vOauthYestTokens = u.vertexOauthYesterdayTokens !== undefined ? u.vertexOauthYesterdayTokens : oauthDetails.reduce((s, x) => s + (x.yesterdayTokens || 0), 0);
          const vOauthYestCost = u.vertexOauthYesterdayCostUsd !== undefined ? u.vertexOauthYesterdayCostUsd : oauthDetails.reduce((s, x) => s + (x.yesterdayCostUsd || 0), 0);

          const hasStreamKey = keysDetails.some(k => (k.methods || []).some(m => String(m).toLowerCase().includes('stream')));
          const isPureCaUser = (u.codeAssistCalls || 0) > 0 && (u.assistTurns || 0) === 0 && (u.searchQueries || 0) === 0;
          const fallbackOauthCost = (u.oauthCostUsd !== undefined && u.oauthCostUsd !== null) ? u.oauthCostUsd : (u.estimatedCostUsd || 0);
          const fallbackCaCost = isPureCaUser ? Math.max(0, fallbackOauthCost - vOauthCost) : 0;
          const caCost = u.codeAssistCostUsd !== undefined ? u.codeAssistCostUsd : fallbackCaCost;
          const fallbackCaToks = isPureCaUser ? ((u.loggedTotalTokens || 0) || Math.max(0, (u.attributedTokens || 0) - vOauthToks)) : 0;
          const caToks = u.codeAssistTokens !== undefined ? u.codeAssistTokens : fallbackCaToks;

          rows.push({
            projectId: p.projectId,
            projectName: p.name,
            userEmail: u.userEmail || 'unknown',
            userType: u.userType || 'INTERNAL_USER',
            totalInteractions: u.totalInteractions || 0,
            assistTurns: u.assistTurns || 0,
            searchQueries: u.searchQueries || 0,
            codeAssistCalls: u.codeAssistCalls || 0,
            codeAssistCostUsd: caCost,
            codeAssistTokens: caToks,
            vertexOauthCalls: vOauthCalls,
            vertexOauthInputTokens: vOauthInTok,
            vertexOauthOutputTokens: vOauthOutTok,
            vertexOauthCachedTokens: vOauthCachedTok,
            vertexOauthTokens: vOauthToks,
            vertexOauthGrossCostUsd: vOauthGross,
            vertexOauthCacheSavingsUsd: vOauthSav,
            vertexOauthCostUsd: vOauthCost,
            vertexOauthTodayCalls: vOauthTodayCalls,
            vertexOauthTodayTokens: vOauthTodayTokens,
            vertexOauthTodayCostUsd: vOauthTodayCost,
            vertexOauthYesterdayCalls: vOauthYestCalls,
            vertexOauthYesterdayTokens: vOauthYestTokens,
            vertexOauthYesterdayCostUsd: vOauthYestCost,
            oauthClientsDetails: oauthDetails,
            antigravityIdeCalls: u.antigravityIdeCalls !== undefined ? u.antigravityIdeCalls : ((u.codeAssistCalls || 0) + vOauthCalls + (u.apiKeysCalls || 0)),
            antigravityIdeTokens: u.antigravityIdeTokens !== undefined ? u.antigravityIdeTokens : (caToks + vOauthToks + (u.apiKeysTotalTokens || 0)),
            antigravityIdeCostUsd: u.antigravityIdeCostUsd !== undefined ? u.antigravityIdeCostUsd : (caCost + vOauthCost + (u.apiKeysCostUsd || 0)),
            hasStreamKey: hasStreamKey,
            codeAssistAcceptedLines: u.codeAssistAcceptedLines || 0,
            codeAssistAcceptedCount: u.codeAssistAcceptedCount || 0,
            codeAssistExposedCount: u.codeAssistExposedCount || 0,
            codeAssistAcceptanceRatePct: u.codeAssistAcceptanceRatePct || 0,
            codeAssistInputChars: u.codeAssistInputChars || 0,
            codeAssistOutputChars: u.codeAssistOutputChars || 0,
            codeAssistSeatMonthlyUsd: 0,
            ideClients: u.ideClients || [],
            ideVersions: u.ideVersions || [],
            codeAssistLanguages: u.codeAssistLanguages || [],
            codeAssistWorkspaces: u.codeAssistWorkspaces || [],
            notebookLmCalls: u.notebookLmCalls || 0,
            colabCalls: u.colabCalls || 0,
            aiStudioCalls: u.aiStudioCalls || 0,
            toolsUsed: u.toolsUsed || [],
            fileOps: u.fileOps || 0,
            loggedInferenceOps: u.loggedInferenceOps || 0,
            loggedInputTokens: u.loggedInputTokens || 0,
            loggedOutputTokens: u.loggedOutputTokens || 0,
            loggedCachedTokens: u.loggedCachedTokens || 0,
            loggedTotalTokens: u.loggedTotalTokens || 0,
            attributedTokens: u.attributedTokens || 0,
            apiKeysCount: u.apiKeysCount || keysDetails.length || 0,
            apiKeysNames: u.apiKeysNames || keysDetails.map(k => k.displayName),
            apiKeysDetails: keysDetails,
            apiKeysCalls: u.apiKeysCalls || 0,
            apiKeysInputTokens: u.apiKeysInputTokens || 0,
            apiKeysOutputTokens: u.apiKeysOutputTokens || 0,
            apiKeysCachedTokens: u.apiKeysCachedTokens || 0,
            apiKeysTotalTokens: u.apiKeysTotalTokens || 0,
            apiKeysRequestBytes: u.apiKeysRequestBytes || 0,
            apiKeysResponseBytes: u.apiKeysResponseBytes || 0,
            apiKeysGrossCostUsd: u.apiKeysGrossCostUsd || 0,
            apiKeysCacheSavingsUsd: u.apiKeysCacheSavingsUsd || 0,
            apiKeysCostUsd: u.apiKeysCostUsd || 0,
            apiKeysTodayCalls: keysTodayCalls,
            apiKeysTodayTokens: keysTodayTokens,
            apiKeysTodayCostUsd: keysTodayCost,
            apiKeysYesterdayCalls: keysYestCalls,
            apiKeysYesterdayTokens: keysYestTokens,
            apiKeysYesterdayCostUsd: keysYestCost,
            oauthCostUsd: (u.oauthCostUsd !== undefined && u.oauthCostUsd !== null) ? u.oauthCostUsd : (u.estimatedCostUsd || 0),
            oauthSharePct: u.oauthSharePct !== undefined ? u.oauthSharePct : ((u.oauthCostUsd > 0) ? (u.sharePct || 0) : 0),
            directCostUsd: u.directCostUsd || 0,
            estimatedCostUsd: u.estimatedCostUsd || 0,
            sharePct: u.sharePct || 0,
            methods: u.methods || [],
            engines: u.engines || [],
            dataStores: u.dataStores || [],
            services: u.services || [],
            activeDaysCount: u.activeDaysCount || 1,
            lastSeen: u.lastSeen || ''
          });
        });
      });

      return rows;
    }

    function _renderSingleUserRow(r) {
      const isExt = r.userType === 'EXTERNAL_USER';
      const isOauthWk = r.userType === 'OAUTH_WORKLOAD';
      const userBadge = isOauthWk
        ? `<span class="jt-badge jt-badge--purple px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-800 border border-indigo-200 text-[10px] font-bold">OAUTH WORKLOAD</span>`
        : (isExt
          ? `<span class="jt-badge jt-badge--amber px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200 text-[10px] font-bold">EXTERNAL</span>`
          : `<span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] font-bold">INTERNAL</span>`);

      const channels = [];
      if (r.vertexOauthCalls > 0 || r.vertexOauthCostUsd > 0) {
        channels.push(jtTipChip('jt-badge jt-badge--purple bg-indigo-50 text-indigo-800 border border-indigo-300', 'ico-bolt', 'Antigravity IDE', 'Antigravity IDE (Vertex AI OAuth)'));
      }
      if (r.apiKeysCount > 0 || r.aiStudioCalls > 0) {
        const hasIdeKeyName = (r.apiKeysNames || []).some(kn => /antigravity|ide|vscode|cursor|cline|windsurf/i.test(kn));
        channels.push(jtTipChip('jt-badge jt-badge--amber bg-amber-50 text-amber-800 border border-amber-300', 'ico-terminal', 'AI Studio', `${hasIdeKeyName ? 'AI Studio / Antigravity' : 'Google AI Studio API Key'} (${r.apiKeysCount} Key)`));
      }
      if (r.notebookLmCalls > 0 || r.toolsUsed.some(t => t.toLowerCase().includes('notebooklm'))) {
        channels.push(jtTipChip('jt-badge jt-badge--green bg-teal-50 text-teal-800 border border-teal-300', 'ico-doc', 'NotebookLM', 'NotebookLM Enterprise'));
      }
      if (r.colabCalls > 0 || r.toolsUsed.some(t => t.toLowerCase().includes('colab') || t.toLowerCase().includes('workbench'))) {
        channels.push(jtTipChip('jt-badge jt-badge--amber bg-orange-50 text-orange-800 border border-orange-300', 'ico-terminal', 'Colab', 'Colab / Workbench'));
      }
      if (r.engines.length > 0) channels.push(jtTipChip('jt-badge jt-badge--purple bg-purple-50 text-purple-700 border border-purple-200', 'ico-bot', 'Agentspace', `Agentspace: ${r.engines.join(', ')}`));
      if (r.ideClients.length > 0) channels.push(jtTipChip('jt-badge jt-badge--blue bg-blue-50 text-blue-700 border border-blue-200', 'ico-terminal', 'IDE', `IDE: ${r.ideClients.join(', ')}`));
      if ((r.codeAssistLanguages || []).length > 0) channels.push(jtTipChip('jt-badge jt-badge--purple bg-indigo-50 text-indigo-700 border border-indigo-200', 'ico-terminal', 'Code Assist', `Code Assist: ${r.codeAssistLanguages.join(', ').toUpperCase()}`));
      if (r.dataStores.length > 0) channels.push(jtTipChip('jt-badge jt-badge--gray bg-slate-100 text-slate-700', 'ico-doc', 'RAG', `RAG: ${r.dataStores.join(', ')}`));
      if (channels.length === 0) channels.push(`<span class="text-slate-400 text-[11px]">${escapeHtml(r.services.join(', '))}</span>`);

      const opsBreakdown = [];
      if (r.vertexOauthCalls > 0) opsBreakdown.push(`<span class="text-indigo-800 font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> ${fmtNum(r.vertexOauthCalls)} Vertex AI OAuth (${fmtTok(r.vertexOauthTokens)} tok)</span>`);
      if (r.assistTurns > 0) opsBreakdown.push(`<b>${escapeHtml(r.assistTurns)}</b> Chat/Assist`);
      if (r.searchQueries > 0) opsBreakdown.push(`<b>${escapeHtml(r.searchQueries)}</b> Search`);
      if (r.codeAssistCalls > 0) opsBreakdown.push(`<b>${escapeHtml(r.codeAssistCalls)}</b> Code Assist`);
      if (r.codeAssistAcceptedLines > 0) opsBreakdown.push(`<span class="text-blue-700 font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> ${fmtNum(r.codeAssistAcceptedLines)} accepted code lines (${escapeHtml(r.codeAssistAcceptanceRatePct)}% accept)</span>`);
      if (r.notebookLmCalls > 0) opsBreakdown.push(`<span class="text-teal-800 font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${escapeHtml(r.notebookLmCalls)} NotebookLM</span>`);
      if (r.colabCalls > 0) opsBreakdown.push(`<span class="text-orange-800 font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> ${escapeHtml(r.colabCalls)} Colab/Notebook</span>`);
      if (r.fileOps > 0) opsBreakdown.push(`<b>${escapeHtml(r.fileOps)}</b> File/Upload`);
      if (r.apiKeysCalls > 0) opsBreakdown.push(`<span class="text-amber-800 font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> ${fmtNum(r.apiKeysCalls)} API Key calls (${fmtBytes(r.apiKeysRequestBytes)} prompt)</span>`);

      const totTokUser = r.loggedTotalTokens + (r.vertexOauthTokens || 0) + r.apiKeysTotalTokens;
      const totInUser = r.loggedInputTokens + (r.vertexOauthInputTokens || 0) + r.apiKeysInputTokens;
      const totOutUser = r.loggedOutputTokens + (r.vertexOauthOutputTokens || 0) + r.apiKeysOutputTokens;

      const ideTelemetryHtml = (r.codeAssistCalls > 0 || r.codeAssistAcceptedLines > 0)
        ? `<div class="mt-1.5 p-2 rounded-lg bg-blue-50/70 border border-blue-200 space-y-1 text-[10px] text-slate-700">
             <div class="flex flex-wrap items-center justify-between gap-2">
               <span class="font-bold text-blue-900 uppercase tracking-wider"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Developer Telemetry IDE / Gemini Code Assist (Actual GCP Logs):</span>
               <span class="jt-badge jt-badge--blue px-1.5 py-0.5 rounded bg-blue-100 text-blue-900 font-extrabold mono">${escapeHtml((r.ideClients || []).length > 0 ? r.ideClients.join(', ') : 'cloudaicompanion.googleapis.com')}</span>
             </div>
             <div class="flex flex-wrap items-center gap-x-3 gap-y-1 pt-0.5 border-t border-blue-200/60">
               <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Accepted lines: <b class="text-blue-900 mono">${fmtNum(r.codeAssistAcceptedLines)}</b> (${escapeHtml(r.codeAssistAcceptedCount)}/${escapeHtml(r.codeAssistExposedCount)} suggestions · <b class="text-emerald-700">${escapeHtml(r.codeAssistAcceptanceRatePct)}% Acceptance Rate</b>)</span>
               ${(r.codeAssistLanguages || []).length > 0 ? `<span><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Languages: <b class="mono text-indigo-800">${escapeHtml(r.codeAssistLanguages.join(', '))}</b></span>` : ''}
               ${(r.codeAssistWorkspaces || []).length > 0 ? `<span><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Workspace: <b class="mono text-slate-800">${escapeHtml(r.codeAssistWorkspaces.slice(0, 4).join(', '))}</b></span>` : ''}
               ${(r.codeAssistInputChars > 0 || r.codeAssistOutputChars > 0) ? `<span class="text-slate-500 mono">Payload IDE: ${(r.codeAssistInputChars / 1024).toFixed(1)} KB in / ${(r.codeAssistOutputChars / 1024).toFixed(1)} KB out</span>` : ''}
             </div>
           </div>`
        : '';

      const perOauthClientBreakdownHtml = (r.oauthClientsDetails && r.oauthClientsDetails.length > 0)
        ? `<div class="mt-1.5 p-2 rounded-lg bg-indigo-50/70 border border-indigo-200 space-y-1">
             <div class="text-[10px] font-bold text-indigo-900 uppercase tracking-wider"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Spend Details: Vertex AI OAuth / Antigravity IDE (${escapeHtml(r.oauthClientsDetails.length)}):</div>
             ${r.oauthClientsDetails.map(od => {
               const modStr = (od.models || []).length > 0 ? ` · Models: ${escapeHtml((od.models || []).join(', '))}` : '';
               return `
                 <div class="text-[10px] text-slate-700 flex flex-wrap items-center justify-between gap-2 border-t border-indigo-200/60 pt-1">
                   <div>
                     <span class="font-bold text-indigo-950">${escapeHtml(od.displayName || od.credentialId)}</span>
                     <span class="jt-badge jt-badge--purple px-1 py-0.2 rounded bg-indigo-100 text-indigo-800 text-[9px] font-bold ml-1">Vertex AI OAuth</span>
                     <span class="text-slate-500 mono ml-1">(${fmtNum(od.calls)} calls · ${fmtTok(od.totalTokens)} tok${modStr})</span>
                   </div>
                   <div class="mono text-right">
                     <span class="font-extrabold text-emerald-700">${fmtUsd(od.costUsd)} (${fmtEur(od.costUsd)})</span>
                     ${(od.todayCostUsd > 0 || od.yesterdayCostUsd > 0 || od.todayCalls > 0 || od.yesterdayCalls > 0)
                       ? `<span class="text-indigo-900 font-semibold ml-1.5">[Today: <b>${fmtUsd(od.todayCostUsd)} (${fmtEur(od.todayCostUsd)})</b>, ${fmtTok(od.todayTokens)} · Yesterday: <b>${fmtUsd(od.yesterdayCostUsd)} (${fmtEur(od.yesterdayCostUsd)})</b>, ${fmtTok(od.yesterdayTokens)}]</span>`
                       : `<span class="text-slate-400 ml-1">[Today/Yesterday: $0]</span>`
                     }
                   </div>
                 </div>
               `;
             }).join('')}
           </div>`
        : '';

      const perKeyBreakdownHtml = (r.apiKeysDetails && r.apiKeysDetails.length > 0)
        ? `<div class="mt-1.5 p-2 rounded-lg bg-amber-50/70 border border-amber-200 space-y-1">
             <div class="text-[10px] font-bold text-amber-900 uppercase tracking-wider"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Spend Details per API Key (${r.apiKeysDetails.length}):</div>
             ${jtExpandList(r.apiKeysDetails.map(kd => {
               const isStream = (kd.methods || []).some(m => m.toLowerCase().includes('stream'));
               const isIdeKey = /antigravity|ide|vscode|cursor|cline|windsurf/i.test(kd.displayName || '');
               return `
                 <div class="text-[10px] text-slate-700 flex flex-wrap items-center justify-between gap-2 border-t border-amber-200/60 pt-1">
                   <div>
                     <span class="font-bold text-slate-900">${escapeHtml(kd.displayName)}</span>
                     ${isStream ? `<span class="jt-badge jt-badge--purple px-1 py-0.2 rounded bg-indigo-100 text-indigo-800 text-[9px] font-bold ml-1">${isIdeKey ? 'Antigravity / IDE Stream' : 'Gemini API Stream'}</span>` : ''}
                     <span class="text-slate-500 mono ml-1">(${fmtNum(kd.calls)} calls · ${fmtTok(kd.totalTokens)} tok)</span>
                   </div>
                   <div class="mono text-right">
                     <span class="font-extrabold text-emerald-700">${fmtUsd(kd.costUsd)} (${fmtEur(kd.costUsd)})</span>
                     ${(kd.todayCostUsd > 0 || kd.yesterdayCostUsd > 0 || kd.todayCalls > 0 || kd.yesterdayCalls > 0)
                       ? `<span class="text-amber-900 font-semibold ml-1.5">[Today: <b>${fmtUsd(kd.todayCostUsd)} (${fmtEur(kd.todayCostUsd)})</b>, ${fmtTok(kd.todayTokens)} · Yesterday: <b>${fmtUsd(kd.yesterdayCostUsd)} (${fmtEur(kd.yesterdayCostUsd)})</b>, ${fmtTok(kd.yesterdayTokens)}]</span>`
                       : `<span class="text-slate-400 ml-1">[Today/Yesterday: $0]</span>`
                     }
                   </div>
                 </div>
               `;
             }), { visible: 2, noun: 'keys', stack: true, key: `cbu-keys:${r.userEmail}:${r.projectId}` })}
           </div>`
        : (r.apiKeysNames.length > 0 ? `<div class="text-[10px] text-amber-800 font-semibold mt-0.5"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Keys: ${escapeHtml(r.apiKeysNames.join(', '))}</div>` : '');

      const combTodayCalls = (r.vertexOauthTodayCalls || 0) + (r.apiKeysTodayCalls || 0);
      const combYestCalls = (r.vertexOauthYesterdayCalls || 0) + (r.apiKeysYesterdayCalls || 0);
      const combTodayToks = (r.vertexOauthTodayTokens || 0) + (r.apiKeysTodayTokens || 0);
      const combYestToks = (r.vertexOauthYesterdayTokens || 0) + (r.apiKeysYesterdayTokens || 0);

      return `
        <tr class="hover:bg-slate-50 transition ${(r.apiKeysCostUsd > 0 || r.vertexOauthCostUsd > 0) ? 'bg-amber-50/20' : ''}">
          <td class="py-3 px-4" data-sort-val="${escapeHtml(r.userEmail)}">
            <div class="flex items-center gap-2 flex-wrap">
              ${renderUserEmailClickable(r.userEmail)}
              ${userBadge}
            </div>
            <div class="text-[10px] text-slate-400 mt-0.5">
              Active ${escapeHtml(r.activeDaysCount)}d · Last access: ${escapeHtml(r.lastSeen ? r.lastSeen.replace('T', ' ').slice(0, 16) + ' UTC' : '—')}
            </div>
            ${ideTelemetryHtml}
            ${perOauthClientBreakdownHtml}
            ${perKeyBreakdownHtml}
          </td>
          <td class="py-3 px-4 mono text-slate-600 font-semibold">${escapeHtml(r.projectId)}</td>
          <td class="py-3 px-4">
            <div class="flex flex-wrap gap-1">${channels.join(' ')}</div>
          </td>
          <td class="py-3 px-4">
            <div class="text-slate-700 text-[11px]">${opsBreakdown.join(' · ') || 'AI operations'}</div>
            <div class="text-[10px] text-slate-400 mono truncate max-w-xs">${escapeHtml(r.methods.join(', '))}</div>
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.totalInteractions + r.apiKeysCalls)}">
            <div class="font-bold text-slate-900">${fmtNum(r.totalInteractions + r.apiKeysCalls)}</div>
            ${r.apiKeysCalls > 0 ? `<div class="text-[10px] text-amber-700">${fmtNum(r.totalInteractions)} OAuth + ${fmtNum(r.apiKeysCalls)} Key</div>` : ''}
            ${(combTodayCalls > 0 || combYestCalls > 0) ? `<div class="text-[10px] text-indigo-700 font-semibold">Today: ${fmtNum(combTodayCalls)} · Yesterday: ${fmtNum(combYestCalls)}</div>` : ''}
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(totTokUser > 0 ? totTokUser : r.attributedTokens)}">
            ${totTokUser > 0
              ? `<div class="font-bold text-slate-800">${fmtTok(totTokUser)}</div>
                 <div class="text-[10px] text-slate-400">In: ${fmtTok(totInUser)} · Out: ${fmtTok(totOutUser)}</div>
                 ${(combTodayToks > 0 || combYestToks > 0) ? `<div class="text-[10px] text-indigo-700 font-semibold">Today: ${fmtTok(combTodayToks)} · Yesterday: ${fmtTok(combYestToks)}</div>` : ''}`
              : `<div class="text-slate-500 font-medium">${fmtTok(r.attributedTokens)} <span class="text-[10px] text-slate-400">(pool estimate)</span></div>`
            }
          </td>
          <td class="py-3 px-4 text-right mono bg-indigo-50/25" data-sort-val="${escapeHtml(r.antigravityIdeCostUsd || (r.antigravityIdeCalls * 0.0001))}">
            ${r.antigravityIdeCalls > 0
              ? `<div class="font-extrabold text-indigo-900">${fmtUsd(r.antigravityIdeCostUsd)} <span class="text-[10px] text-slate-500">(${fmtEur(r.antigravityIdeCostUsd)})</span></div>
                 <div class="text-[10px] font-bold text-indigo-700 mt-0.5"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> ${fmtNum(r.antigravityIdeCalls)} calls · ${fmtTok(r.antigravityIdeTokens)} tok</div>
                 <div class="text-[9px] text-slate-500 mt-0.5 leading-tight space-y-0.5">
                   ${r.vertexOauthCalls > 0 ? `<div><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Vertex AI OAuth (Antigravity): <b>${fmtNum(r.vertexOauthCalls)}</b> call (${fmtUsd(r.vertexOauthCostUsd)})</div>` : ''}
                   ${r.codeAssistCalls > 0 ? `<div><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> Plugin IDE (${escapeHtml((r.ideClients || []).join(', ') || 'Code Assist')}): <b>${fmtNum(r.codeAssistCalls)}</b> call (${fmtUsd(r.codeAssistCostUsd)})</div>` : ''}
                   ${r.apiKeysCalls > 0 ? `<div><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> ${r.hasStreamKey ? 'Antigravity / Stream API Key' : 'Gemini API Key'}: <b>${fmtNum(r.apiKeysCalls)}</b> call (${fmtUsd(r.apiKeysCostUsd)})</div>` : ''}
                 </div>`
              : `<div class="text-slate-400 font-semibold text-[11px]">$0.00 <span class="text-[9px] font-normal">(0 call GCP)</span></div>
                 <div class="text-[9px] text-slate-400 mt-0.5">Web App / Native Quota only</div>`
            }
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.oauthCostUsd)}">
            ${(r.oauthCostUsd === 0 && r.apiKeysCostUsd > 0)
              ? `<div class="text-slate-400 text-[11px] font-semibold">API Key only</div>
                 <div class="text-[10px] text-amber-700 font-semibold">See API Keys column →</div>`
              : `<div class="text-purple-700 font-bold">${fmtUsd(r.oauthCostUsd)} <span class="text-[10px] text-slate-500">(${fmtEur(r.oauthCostUsd)})</span></div>
                 ${r.vertexOauthCostUsd > 0
                   ? `<div class="text-[10px] text-indigo-800 font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bolt"/></svg> Vertex OAuth: ${fmtUsd(r.vertexOauthCostUsd)}</div>
                      ${(r.vertexOauthTodayCostUsd > 0 || r.vertexOauthYesterdayCostUsd > 0) ? `<div class="text-[9px] text-indigo-700 font-semibold">Today: ${fmtUsd(r.vertexOauthTodayCostUsd)} · Yesterday: ${fmtUsd(r.vertexOauthYesterdayCostUsd)}</div>` : ''}`
                   : `<div class="text-[10px] text-slate-400">${r.oauthSharePct.toFixed(1)}% OAuth pool</div>`}`
            }
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.apiKeysCostUsd)}">
            ${r.apiKeysCostUsd > 0
              ? `<div class="font-bold text-amber-800">${fmtUsd(r.apiKeysCostUsd)} <span class="text-[10px] text-slate-500">(${fmtEur(r.apiKeysCostUsd)})</span></div>
                 <div class="text-[10px] text-slate-500">Gross ${fmtEur(r.apiKeysGrossCostUsd)} · Cache -${fmtEur(r.apiKeysCacheSavingsUsd)}</div>
                 ${(r.apiKeysTodayCostUsd > 0 || r.apiKeysYesterdayCostUsd > 0)
                   ? `<div class="text-[10px] text-indigo-800 font-bold mt-0.5">Today: ${fmtUsd(r.apiKeysTodayCostUsd)} (${fmtEur(r.apiKeysTodayCostUsd)})<br>Yesterday: ${fmtUsd(r.apiKeysYesterdayCostUsd)} (${fmtEur(r.apiKeysYesterdayCostUsd)})</div>`
                   : ''}`
              : `<span class="text-slate-300">$0.00</span>`
            }
          </td>
          <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.estimatedCostUsd)}">
            <div class="font-extrabold text-emerald-700 text-sm">${fmtUsd(r.estimatedCostUsd)}</div>
            <div class="text-[11px] font-bold text-slate-500">${fmtEur(r.estimatedCostUsd)}</div>
            <div class="text-[10px] text-slate-400">${r.sharePct.toFixed(1)}% of project total</div>
          </td>
        </tr>
      `;
    }

    function renderUsersTable(agg) {
      const kpiGrid = document.getElementById('users-kpi-grid');
      const tbody = document.getElementById('users-tbody');
      const q = (document.getElementById('search-input').value || '').toLowerCase().trim();

      const rows = _collectUsersUsageRows(agg);

      const filtered = rows.filter(r => {
        if (q) {
          const hay = `${r.userEmail} ${r.projectId} ${r.apiKeysNames.join(' ')} ${r.toolsUsed.join(' ')} ${r.engines.join(' ')} ${r.ideClients.join(' ')} ${(r.codeAssistLanguages || []).join(' ')} ${(r.codeAssistWorkspaces || []).join(' ')} ${r.methods.join(' ')} ${r.dataStores.join(' ')}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      }).sort((a, b) => (b.estimatedCostUsd - a.estimatedCostUsd) || ((b.loggedTotalTokens + (b.vertexOauthTokens || 0) + b.apiKeysTotalTokens) - (a.loggedTotalTokens + (a.vertexOauthTokens || 0) + a.apiKeysTotalTokens)) || (b.totalInteractions - a.totalInteractions));

      const uniqueUsers = new Set(filtered.map(r => r.userEmail)).size;
      const externalUsers = new Set(filtered.filter(r => r.userType === 'EXTERNAL_USER').map(r => r.userEmail)).size;
      const totalUserOauthCost = filtered.reduce((acc, r) => acc + r.oauthCostUsd, 0);
      const totalUserApiKeysCost = filtered.reduce((acc, r) => acc + r.apiKeysCostUsd, 0);
      const totalUserCombinedCost = filtered.reduce((acc, r) => acc + r.estimatedCostUsd, 0);
      const totalCombinedTokens = filtered.reduce((acc, r) => acc + r.loggedTotalTokens + (r.vertexOauthTokens || 0) + r.apiKeysTotalTokens, 0);
      const totalQueries = filtered.reduce((acc, r) => acc + r.totalInteractions + r.apiKeysCalls, 0);
      const totalIdeAcceptedLines = filtered.reduce((acc, r) => acc + (r.codeAssistAcceptedLines || 0), 0);
      const totalIdeUsers = new Set(filtered.filter(r => (r.codeAssistCalls || 0) > 0 || (r.codeAssistAcceptedLines || 0) > 0).map(r => r.userEmail)).size;
      const totalAntigravityDevUsers = new Set(filtered.filter(r => (r.antigravityIdeCalls || 0) > 0).map(r => r.userEmail)).size;
      const totalAntigravityDevCalls = filtered.reduce((acc, r) => acc + (r.antigravityIdeCalls || 0), 0);
      const totalAntigravityDevCost = filtered.reduce((acc, r) => acc + (r.antigravityIdeCostUsd || 0), 0);
      const topUser = filtered[0];

      if (kpiGrid) {
        setSafeHtml(kpiGrid, `
          <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
            <div class="jt-kpi__label text-xs font-semibold text-slate-500"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> Active Human Users (OAuth + API Keys)</div>
            <div class="jt-kpi__value text-2xl font-extrabold text-slate-900 mt-1 mono">${fmtNum(uniqueUsers)}</div>
            <div class="jt-kpi__note text-[11px] text-slate-500 mt-1">
              <span class="font-semibold text-emerald-700">${fmtNum(uniqueUsers - externalUsers)} internal</span> ·
              <span class="font-semibold ${externalUsers > 0 ? 'text-amber-700' : 'text-slate-400'}">${fmtNum(externalUsers)} external (@external)</span>
              ${totalAntigravityDevUsers > 0 ? ` · <span class="font-semibold text-indigo-700"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> ${escapeHtml(totalAntigravityDevUsers)} dev IDE/API</span>` : ''}
            </div>
          </div>
          <div class="jt-kpi bg-white rounded-xl border border-indigo-200 p-4 shadow-2xs">
            <div class="jt-kpi__label text-xs font-semibold text-indigo-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Antigravity, IDE &amp; Code Assist (GCP)</div>
            <div class="jt-kpi__value text-2xl font-extrabold text-indigo-800 mt-1 mono">${fmtUsd(totalAntigravityDevCost)} <span class="jt-kpi__unit text-sm font-bold text-slate-500">(${fmtEur(totalAntigravityDevCost)})</span></div>
            <div class="jt-kpi__note text-[11px] text-slate-600 mt-1">
              <b>${fmtNum(totalAntigravityDevCalls)}</b> dev calls (${escapeHtml(totalAntigravityDevUsers)} users)${totalIdeUsers > 0 ? ` · Plugin IDE: <b>${escapeHtml(totalIdeUsers)}</b> (${fmtNum(totalIdeAcceptedLines)} lines)` : ''}
            </div>
          </div>
          <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
            <div class="jt-kpi__label text-xs font-semibold text-slate-500"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Total User Cost (OAuth + API Keys)</div>
            <div class="jt-kpi__value jt-kpi__value--green text-2xl font-extrabold text-emerald-700 mt-1 mono">${fmtUsd(totalUserCombinedCost)} <span class="jt-kpi__unit text-sm font-bold text-slate-500">(${fmtEur(totalUserCombinedCost)})</span></div>
            <div class="jt-kpi__note text-[11px] text-slate-500 mt-1">OAuth: <b>${fmtUsd(totalUserOauthCost)}</b> + API Keys: <b>${fmtUsd(totalUserApiKeysCost)}</b> · <b>${fmtTok(totalCombinedTokens)}</b> tok</div>
          </div>
          <div class="jt-kpi bg-white rounded-xl border border-slate-200 p-4 shadow-2xs">
            <div class="jt-kpi__label text-xs font-semibold text-slate-500"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Top User by Variable Cost</div>
            <div class="mt-1.5 truncate">${topUser ? renderUserEmailClickable(topUser.userEmail) : '—'}</div>
            <div class="jt-kpi__note text-[11px] text-slate-500 mt-1">${topUser ? `<b>${fmtUsd(topUser.estimatedCostUsd)} (${fmtEur(topUser.estimatedCostUsd)})</b> · IDE/API: <b>${fmtUsd(topUser.antigravityIdeCostUsd || 0)}</b>` : 'No users detected'}</div>
          </div>
        `);
      }

      if (filtered.length === 0) {
        setSafeHtml(tbody, `<tr><td colspan="10" class="py-10 text-center text-slate-400">No active users found in the logs for the current filters.</td></tr>`);
        return;
      }

      setSafeHtml(tbody, filtered.map(r => _renderSingleUserRow(r)).join(''));
    }

    // VISTA 3C: AI STUDIO, COLAB ENTERPRISE, VERTEX WORKBENCH & NOTEBOOKLM ENTERPRISE
    function _collectAiToolsInventory(agg) {
      const aiStudioProjects = [];
      const notebookResources = [];
      const notebookLmProjects = [];
      const toolUsersMap = new Map();

      let totalAiStudioCalls = 0, totalAiStudioTokens = 0, totalAiStudioCost = 0, totalAiStudioKeys = 0;
      let totalNotebookLmCalls = 0, totalColabRuntimes = 0, totalColabTemplates = 0, totalWorkbench = 0;

      (globalScanData.projects || []).forEach(p => {
        if (!isProjectVisibleByToggles(p)) return;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return;
        const ats = p.aiToolsSummary || {};
        const asInfo = ats.aiStudio || {};
        const nbInfo = ats.notebooks || {};

        const isAiStudioProj = Boolean(
          p.isAiStudioProject || asInfo.isAiStudioProject ||
          (asInfo.apiKeysCount || 0) > 0 || (asInfo.inferenceCalls || 0) > 0 ||
          (p.geminiApiRequests || 0) > 0
        );

        if (isAiStudioProj) {
          const asKeys = (p.apiKeys || []).filter(k =>
            k.isAiStudioKey ||
            (k.apiTargets || []).includes('generativelanguage.googleapis.com') ||
            (k.inferenceRequests || 0) > 0 ||
            p.isAiStudioProject
          );
          const calls = asInfo.inferenceCalls ?? (p.geminiApiRequests || asKeys.reduce((s, k) => s + (k.ok200Inference ?? k.inferenceRequests ?? 0), 0));
          const tokens = asInfo.totalTokens ?? asKeys.reduce((s, k) => s + (k.totalTokens || 0), 0);
          const cost = asInfo.costUsd ?? (p.geminiCostUsd || asKeys.reduce((s, k) => s + (k.estimatedCostUsd || 0), 0));
          const reqB = asInfo.requestBytes ?? asKeys.reduce((s, k) => s + (k.requestBytes || 0), 0);
          const respB = asInfo.responseBytes ?? asKeys.reduce((s, k) => s + (k.responseBytes || 0), 0);
          const owners = new Set(asInfo.owners || []);
          asKeys.forEach(k => { if (k.ownerEmail) owners.add(k.ownerEmail); });

          totalAiStudioCalls += calls;
          totalAiStudioTokens += tokens;
          totalAiStudioCost += cost;
          totalAiStudioKeys += asKeys.length;

          aiStudioProjects.push({
            projectId: p.projectId,
            projectName: p.name,
            tier: asInfo.tier || (p.billingEnabled ? 'PAID_PAY_AS_YOU_GO' : 'FREE_TIER_NO_BILLING'),
            billingEnabled: Boolean(p.billingEnabled),
            keysCount: asKeys.length,
            keys: asKeys,
            owners: Array.from(owners),
            calls,
            tokens,
            reqBytes: reqB,
            respBytes: respB,
            costUsd: cost
          });
        }

        const nlmCalls = nbInfo.notebookLmEnterpriseCalls || 0;
        if (nlmCalls > 0) {
          totalNotebookLmCalls += nlmCalls;
          notebookLmProjects.push({
            projectId: p.projectId,
            projectName: p.name,
            calls: nlmCalls,
            users: nbInfo.users || []
          });
        }

        totalColabRuntimes += (nbInfo.colabRuntimesCount || 0);
        totalColabTemplates += (nbInfo.colabTemplatesCount || 0);
        totalWorkbench += (nbInfo.workbenchInstancesCount || 0);

        (p.deployedAiResources || []).forEach(r => {
          if (['COLAB_RUNTIME', 'COLAB_ENTERPRISE_RUNTIME', 'COLAB_RUNTIME_TEMPLATE', 'COLAB_ENTERPRISE_TEMPLATE', 'COLAB_EXECUTION_JOB', 'WORKBENCH_INSTANCE', 'WORKBENCH_NOTEBOOK'].includes(r.resourceType)) {
            notebookResources.push({ ...r, projectId: p.projectId, projectName: p.name });
          }
        });

        (p.usersUsage || []).forEach(u => {
          const email = u.userEmail || 'unknown';
          const prev = toolUsersMap.get(email) || {
            userEmail: email,
            userType: u.userType || 'INTERNAL_USER',
            projects: new Set(),
            tools: new Set(),
            ideClients: new Set(),
            aiStudioCalls: 0,
            aiStudioKeys: new Set(),
            notebookLmCalls: 0,
            colabCalls: 0,
            agentspaceCalls: 0,
            codeAssistCalls: 0,
            antigravityIdeCalls: 0,
            antigravityIdeCostUsd: 0,
            totalTokens: 0,
            totalCostUsd: 0,
            lastSeen: ''
          };
          prev.projects.add(p.projectId);
          (u.toolsUsed || []).forEach(t => prev.tools.add(t));
          (u.ideClients || []).forEach(ic => prev.ideClients.add(ic));
          (u.apiKeysNames || []).forEach(kn => prev.aiStudioKeys.add(kn));
          if ((u.apiKeysCount || 0) > 0) prev.tools.add('AI Studio / API Key');
          if ((u.notebookLmCalls || 0) > 0) prev.tools.add('NotebookLM Enterprise');
          if ((u.colabCalls || 0) > 0) prev.tools.add('Colab / Workbench');
          if ((u.assistTurns || 0) > 0 || (u.searchQueries || 0) > 0) prev.tools.add('Gemini Enterprise (Agentspace)');
          if ((u.codeAssistCalls || 0) > 0) prev.tools.add('Gemini Code Assist');

          const uCaCalls = u.codeAssistCalls || 0;
          const uVOauthCalls = u.vertexOauthCalls || 0;
          const uVOauthCost = u.vertexOauthCostUsd || 0;
          const uAkCalls = u.aiStudioCalls || u.apiKeysCalls || 0;
          const uOauthCost = (u.oauthCostUsd !== undefined && u.oauthCostUsd !== null) ? u.oauthCostUsd : Math.max(0, (u.estimatedCostUsd || 0) - (u.apiKeysCostUsd || 0));
          const isOnlyCaOauth = (u.assistTurns || 0) === 0 && (u.searchQueries || 0) === 0;
          const estCaFromOauth = isOnlyCaOauth ? Math.max(0, uOauthCost - uVOauthCost) : Math.min(Math.max(0, uOauthCost - uVOauthCost), uCaCalls * 0.0014);
          const defaultCaCost = uCaCalls > 0 ? estCaFromOauth : 0;
          const uCaCost = (u.codeAssistCostUsd !== undefined) ? u.codeAssistCostUsd : defaultCaCost;
          const uIdeCost = (u.antigravityIdeCostUsd !== undefined) ? u.antigravityIdeCostUsd : (uCaCost + uVOauthCost + (u.apiKeysCostUsd || 0));

          if (uVOauthCalls > 0) prev.tools.add('Antigravity IDE (Vertex AI OAuth)');
          prev.aiStudioCalls += uAkCalls;
          prev.notebookLmCalls += (u.notebookLmCalls || 0);
          prev.colabCalls += (u.colabCalls || 0);
          prev.agentspaceCalls += (u.assistTurns || 0) + (u.searchQueries || 0);
          prev.codeAssistCalls += uCaCalls;
          prev.antigravityIdeCalls += (u.antigravityIdeCalls !== undefined) ? u.antigravityIdeCalls : (uCaCalls + uVOauthCalls + uAkCalls);
          prev.antigravityIdeCostUsd += uIdeCost;
          prev.totalTokens += (u.loggedTotalTokens || 0) + (u.vertexOauthTokens || 0) + (u.apiKeysTotalTokens || 0);
          prev.totalCostUsd += (u.estimatedCostUsd || 0);
          if (u.lastSeen && u.lastSeen > prev.lastSeen) prev.lastSeen = u.lastSeen;
          toolUsersMap.set(email, prev);
        });
      });

      const toolUsersList = Array.from(toolUsersMap.values())
        .sort((a, b) => (b.totalCostUsd - a.totalCostUsd) || ((b.aiStudioCalls + b.notebookLmCalls + b.colabCalls + b.agentspaceCalls) - (a.aiStudioCalls + a.notebookLmCalls + a.colabCalls + a.agentspaceCalls)));

      return {
        aiStudioProjects,
        notebookResources,
        notebookLmProjects,
        toolUsersList,
        totalAiStudioCalls,
        totalAiStudioTokens,
        totalAiStudioCost,
        totalAiStudioKeys,
        totalNotebookLmCalls,
        totalColabRuntimes,
        totalColabTemplates,
        totalWorkbench
      };
    }

    function _renderAiToolsKpiGrid(kpiGrid, inv) {
      setSafeHtml(kpiGrid, `
        <div class="jt-kpi bg-white rounded-xl border border-amber-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs font-semibold text-amber-900">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Google AI Studio Projects &amp; Keys</span>
            <span class="jt-badge jt-badge--amber px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-extrabold mono">${inv.aiStudioProjects.length} projects</span>
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span class="jt-kpi__value text-2xl font-extrabold text-slate-900 mono">${fmtNum(inv.totalAiStudioCalls)}</span>
            <span class="jt-kpi__unit text-xs text-slate-500">calls (${escapeHtml(inv.totalAiStudioKeys)} API Keys)</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-600">
            <span>Tokens: <b class="mono">${fmtTok(inv.totalAiStudioTokens)}</b></span>
            <span>Cost: <b class="text-emerald-700 mono">${fmtUsd(inv.totalAiStudioCost)} (${fmtEur(inv.totalAiStudioCost)})</b></span>
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border border-teal-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs font-semibold text-teal-900">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> NotebookLM Enterprise</span>
            <span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full bg-teal-100 text-teal-800 text-[10px] font-extrabold mono">${inv.notebookLmProjects.length} projects</span>
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span class="jt-kpi__value text-2xl font-extrabold text-teal-800 mono">${fmtNum(inv.totalNotebookLmCalls)}</span>
            <span class="jt-kpi__unit text-xs text-slate-500">logged operations</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 text-[11px] text-slate-500">
            Tracked via <code class="mono text-slate-700">svc_notebooklm_enterprise</code> &amp; Discovery Engine
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border border-orange-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs font-semibold text-orange-900">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Colab Enterprise &amp; Workbench</span>
            <span class="jt-badge jt-badge--amber px-2 py-0.5 rounded-full bg-orange-100 text-orange-800 text-[10px] font-extrabold mono">${inv.notebookResources.length} resources</span>
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span class="jt-kpi__value text-2xl font-extrabold text-slate-900 mono">${escapeHtml(inv.totalColabRuntimes)}</span>
            <span class="jt-kpi__unit text-xs text-slate-500">Runtimes · <b>${escapeHtml(inv.totalColabTemplates)}</b> Templates · <b>${escapeHtml(inv.totalWorkbench)}</b> Workbench</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 text-[11px] text-slate-500">
            Inventory of <code class="mono text-slate-700">notebookRuntimes</code>, <code class="mono text-slate-700">notebookExecutionJobs</code> and VMs
          </div>
        </div>

        <div class="jt-kpi bg-white rounded-xl border border-indigo-200 p-4 shadow-2xs">
          <div class="jt-kpi__label flex items-center justify-between text-xs font-semibold text-indigo-900">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> Users Cataloged by AI Tool</span>
            <span class="jt-badge jt-badge--purple px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-800 text-[10px] font-extrabold mono">Multi-Tool</span>
          </div>
          <div class="mt-1.5 flex items-baseline gap-2">
            <span class="jt-kpi__value text-2xl font-extrabold text-[#0F2A4A] mono">${fmtNum(inv.toolUsersList.length)}</span>
            <span class="jt-kpi__unit text-xs text-slate-500">active users mapped</span>
          </div>
          <div class="jt-kpi__note mt-2 pt-2 border-t border-slate-100 text-[11px] text-slate-500">
            AI Studio · NotebookLM · Colab · Agentspace · Code Assist
          </div>
        </div>
      `);
    }

    function renderAiToolsTab(agg) {
      const kpiGrid = document.getElementById('ai-tools-kpi-grid');
      const container = document.getElementById('ai-tools-content-container');
      if (!kpiGrid || !container || !globalScanData) return;
      const q = (document.getElementById('search-input').value || '').toLowerCase().trim();

      const inv = _collectAiToolsInventory(agg);
      _renderAiToolsKpiGrid(kpiGrid, inv);
      const { aiStudioProjects, notebookResources, notebookLmProjects, toolUsersList } = inv;

      const filteredAiStudio = aiStudioProjects.filter(ap => {
        if (!q) return true;
        const hay = `${ap.projectId} ${ap.projectName} ${ap.owners.join(' ')} ${ap.keys.map(k => k.displayName + ' ' + k.uid).join(' ')}`.toLowerCase();
        return hay.includes(q);
      });

      const aiStudioRowsHtml = filteredAiStudio.length > 0
        ? filteredAiStudio.map(ap => {
            const tierBadge = ap.billingEnabled
              ? jtTipChip('jt-badge jt-badge--green rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200', 'ico-chart', 'Pay-As-You-Go', 'Pay-As-You-Go (Billing Active)')
              : jtTipChip('jt-badge jt-badge--amber rounded-full bg-amber-50 text-amber-800 border border-amber-300', 'ico-bolt', 'Free-Tier', 'Free-Tier (No Billing)', 'data-badge-label="🆓 Free-Tier (No Billing)"');

            const ownersHtml = ap.owners.length > 0
              ? jtExpandList(ap.owners.map(o => renderUserEmailClickable(o)), { visible: 2, noun: 'users', key: `ais-owners:${ap.projectId}` })
              : `<span class="text-slate-400 text-[11px]">Creator not in logs (last 30d)</span>`;

            const keysSummaryHtml = ap.keys.length > 2
              ? `<div class="text-[11px] font-bold text-slate-700 mb-0.5">${ap.keys.length} keys · ${fmtTok(ap.keys.reduce((a, k) => a + (k.totalTokens || 0), 0))} tok · ${fmtUsd(ap.keys.reduce((a, k) => a + (k.estimatedCostUsd || 0), 0))}</div>`
              : '';
            const keyBlocks = ap.keys.map(k => {
                  const isConsole = Boolean(k.isConsoleInternalKey);
                  return `<div class="text-[11px] flex flex-wrap items-center justify-between gap-2 py-0.5 border-b border-slate-100 last:border-0">
                    <div class="flex items-center flex-wrap gap-1">
                      <span class="font-bold text-slate-800">${escapeHtml(k.displayName)}</span>
                      ${isConsole ? `<span class="jt-badge jt-badge--gray px-1 py-0.2 rounded bg-slate-100 text-slate-600 text-[9px] font-bold ml-1">Console/Colab UI</span>` : ''}
                      <span class="text-[10px] text-slate-400 mono">(apikey:${escapeHtml(k.uid)})</span>
                      ${k.ownerEmail ? `<span class="text-[10px] text-emerald-700 font-semibold">→</span> ${renderUserEmailClickable(k.ownerEmail)}` : ''}
                    </div>
                    <div class="mono text-[10px] text-slate-600">
                      <b>${fmtNum(k.ok200Inference ?? k.inferenceRequests ?? 0)}</b> call · <b>${fmtTok(k.totalTokens || 0)}</b> tok · <b class="text-emerald-700">${fmtUsd(k.estimatedCostUsd || 0)}</b>
                    </div>
                  </div>`;
            });
            const keysDetailHtml = ap.keys.length > 0
              ? keysSummaryHtml + jtExpandList(keyBlocks, { visible: 2, noun: 'keys', stack: true, key: `ais-keys:${ap.projectId}` })
              : `<span class="text-slate-400 text-[11px]">0 active keys</span>`;

            return `
              <tr class="hover:bg-slate-50 align-top">
                <td class="py-3 px-4" data-sort-val="${escapeHtml(ap.projectName)}">
                  <div class="font-bold text-slate-900 cursor-pointer hover:text-blue-700" data-jt-click="openProjectModal(${jsArg(ap.projectId)})">${escapeHtml(ap.projectName)}</div>
                  <div class="text-[11px] text-slate-500 mono">${escapeHtml(ap.projectId)}</div>
                </td>
                <td class="py-3 px-4">${tierBadge}</td>
                <td class="py-3 px-4">${ownersHtml}</td>
                <td class="py-3 px-4 min-w-[280px]">${keysDetailHtml}</td>
                <td class="py-3 px-4 text-right mono font-bold text-slate-900" data-sort-val="${escapeHtml(ap.calls)}">${fmtNum(ap.calls)}</td>
                <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(ap.tokens)}">
                  <div class="font-bold text-slate-800">${fmtTok(ap.tokens)}</div>
                  <div class="text-[10px] text-amber-700">${fmtBytes(ap.reqBytes)} In / ${fmtBytes(ap.respBytes)} Out</div>
                </td>
                <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(ap.costUsd)}">
                  <div class="font-extrabold text-emerald-700">${fmtUsd(ap.costUsd)}</div>
                  <div class="text-[10px] text-slate-500 font-bold">${fmtEur(ap.costUsd)}</div>
                </td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="7" class="py-8 text-center text-slate-400">No Google AI Studio projects found for the selected filters.</td></tr>`;

      const notebookCombinedRows = [];
      notebookLmProjects.forEach(np => {
        notebookCombinedRows.push({
          typeLabel: 'NotebookLM Enterprise (SaaS Service)',
          name: `NotebookLM Enterprise (${np.projectName})`,
          projectId: np.projectId,
          location: 'eu / global',
          userOrSa: np.users.length > 0 ? np.users.join(', ') : 'svc_notebooklm_enterprise (API Service)',
          machineOrDetails: `${fmtNum(np.calls)} Discovery Engine / NotebookLM API calls`,
          state: 'ACTIVE',
          calls: np.calls,
          runCount: 1,
          succeededCount: 1,
          failedCount: 0,
          latestTime: '',
          firstTime: '',
          consoleUrl: `https://console.cloud.google.com/gen-app-builder/engines?project=${np.projectId}`
        });
      });

      const groupedNotebookResources = groupRepeatedAiResources(notebookResources);
      groupedNotebookResources.forEach(nr => {
        notebookCombinedRows.push({
          typeLabel: nr.typeLabel || nr.resourceType,
          name: nr.displayName,
          projectId: nr.projectId,
          location: nr.location || '—',
          userOrSa: nr.runtimeUser || nr.ownerEmail || '—',
          machineOrDetails: nr.details || nr.machineType || '—',
          state: nr.state || 'CONFIGURED',
          calls: 0,
          runCount: nr._runCount || 1,
          succeededCount: nr._succeededCount || 0,
          failedCount: nr._failedCount || 0,
          latestTime: nr._latestTime || nr.updateTime || nr.createTime || '',
          firstTime: nr._firstTime || '',
          consoleUrl: nr.consoleUrl || `https://console.cloud.google.com/vertex-ai/colab/runtimes?project=${nr.projectId}`
        });
      });

      const filteredNotebooks = notebookCombinedRows.filter(nr => {
        if (!q) return true;
        return `${nr.typeLabel} ${nr.name} ${nr.projectId} ${nr.userOrSa} ${nr.machineOrDetails}`.toLowerCase().includes(q);
      });

      const notebooksRowsHtml = filteredNotebooks.length > 0
        ? filteredNotebooks.map(nr => {
            const isRunning = ['ACTIVE', 'RUNNING', 'READY', 'SUCCEEDED'].includes(String(nr.state).toUpperCase());
            const stateBadge = isRunning
              ? `<span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-extrabold whitespace-nowrap"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> ${escapeHtml(nr.state)}</span>`
              : `<span class="jt-badge jt-badge--gray px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px] font-semibold whitespace-nowrap">${escapeHtml(nr.state)}</span>`;

            const runCounterBadge = nr.runCount > 1
              ? `<div class="mt-1 flex flex-wrap items-center gap-1.5">
                   ${jtTipChip('jt-badge jt-badge--purple rounded-md bg-indigo-50 text-indigo-800 border border-indigo-200 mono', 'ico-refresh', `${nr.runCount} runs`, `${nr.runCount} scheduled runs (${nr.succeededCount} SUCCEEDED${nr.failedCount > 0 ? ` · ${nr.failedCount} FAILED` : ''})`)}
                   ${nr.latestTime ? `<span class="text-[10px] text-slate-400 mono">Last: ${escapeHtml(nr.latestTime.replace('T', ' ').slice(0, 16))} UTC${escapeHtml(nr.firstTime && nr.firstTime !== nr.latestTime ? ` · First: ${nr.firstTime.slice(0, 10)}` : '')}</span>` : ''}
                 </div>`
              : (nr.latestTime ? `<div class="text-[10px] text-slate-400 mono mt-0.5">Run: ${escapeHtml(nr.latestTime.replace('T', ' ').slice(0, 16))} UTC</div>` : '');

            const userParts = String(nr.userOrSa || '').split(',').map(x => x.trim()).filter(Boolean);
            const userCellHtml = (nr.userOrSa && nr.userOrSa.includes('@') && !nr.userOrSa.includes(','))
              ? renderUserEmailClickable(nr.userOrSa)
              : (userParts.length > 1
                ? jtExpandList(userParts.map(x => (x.includes('@') ? renderUserEmailClickable(x) : `<span class="mono text-emerald-800 font-semibold">${escapeHtml(x)}</span>`)), { visible: 2, noun: 'users', key: `nb-users:${nr.projectId}:${nr.name}` })
                : `<span class="mono text-emerald-800 font-semibold">${escapeHtml(nr.userOrSa)}</span>`);

            return `
              <tr class="hover:bg-slate-50">
                <td class="py-3 px-4 font-bold text-[#0F2A4A]"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> ${escapeHtml(nr.typeLabel)}</td>
                <td class="py-3 px-4">
                  <div class="font-bold text-slate-900 mono">${escapeHtml(nr.name)}</div>
                  ${runCounterBadge}
                </td>
                <td class="py-3 px-4 mono text-slate-700 font-semibold whitespace-nowrap">${escapeHtml(nr.projectId)} <span class="text-slate-400">(${escapeHtml(nr.location)})</span></td>
                <td class="py-3 px-4">${userCellHtml}</td>
                <td class="py-3 px-4 text-slate-600">${escapeHtml(nr.machineOrDetails)}</td>
                <td class="py-3 px-4 whitespace-nowrap">${stateBadge}</td>
                <td class="py-3 px-4 text-right whitespace-nowrap">
                  <a href="${escapeHtml(nr.consoleUrl)}" target="_blank" rel="noopener" class="btn-nowrap inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[10px] transition whitespace-nowrap shrink-0">
                    Open in GCP ↗
                  </a>
                </td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="7" class="py-8 text-center text-slate-400">No Colab Enterprise runtime, Vertex AI Workbench instance or NotebookLM service detected in the selected projects.</td></tr>`;

      const filteredToolUsers = toolUsersList.filter(u => {
        if (!q) return true;
        return `${u.userEmail} ${Array.from(u.projects).join(' ')} ${Array.from(u.tools).join(' ')} ${Array.from(u.aiStudioKeys).join(' ')}`.toLowerCase().includes(q);
      });

      const toolUsersRowsHtml = filteredToolUsers.length > 0
        ? filteredToolUsers.map(u => {
            const toolsBadges = Array.from(u.tools).map(t => {
              const shortT = String(t).split(' (')[0];
              if (t.includes('Antigravity')) return jtTipChip('jt-badge jt-badge--purple bg-indigo-50 text-indigo-800 border border-indigo-300', 'ico-terminal', shortT, t);
              if (t.includes('AI Studio')) return jtTipChip('jt-badge jt-badge--amber bg-amber-50 text-amber-800 border border-amber-300', 'ico-terminal', shortT, t);
              if (t.includes('NotebookLM')) return jtTipChip('jt-badge jt-badge--green bg-teal-50 text-teal-800 border border-teal-300', 'ico-doc', shortT, t);
              if (t.includes('Colab') || t.includes('Workbench')) return jtTipChip('jt-badge jt-badge--amber bg-orange-50 text-orange-800 border border-orange-300', 'ico-terminal', shortT, t);
              if (t.includes('Code Assist')) return jtTipChip('jt-badge jt-badge--blue bg-blue-50 text-blue-700 border border-blue-200', 'ico-terminal', shortT, t);
              return jtTipChip('jt-badge jt-badge--purple bg-purple-50 text-purple-700 border border-purple-200', 'ico-bot', shortT, t);
            }).join(' ');

            return `
              <tr class="hover:bg-slate-50">
                <td class="py-3 px-4 font-bold text-slate-900 mono" data-sort-val="${escapeHtml(u.userEmail)}">
                  ${renderUserEmailClickable(u.userEmail)}
                  ${u.aiStudioKeys.size > 0 ? `<div class="text-[10px] text-amber-800 font-semibold mt-0.5"><svg class="jt-ico" aria-hidden="true"><use href="#ico-key"/></svg> Key: ${jtExpandList(Array.from(u.aiStudioKeys).map(kn => `<span>${escapeHtml(kn)}</span>`), { visible: 2, noun: 'keys', key: `mx-keys:${u.userEmail}` })}</div>` : ''}
                </td>
                <td class="py-3 px-4 mono text-slate-600 text-[11px]">${jtExpandList(Array.from(u.projects).map(pj => `<span>${escapeHtml(pj)}</span>`), { visible: 2, noun: 'projects', key: `mx-proj:${u.userEmail}` })}</td>
                <td class="py-3 px-4"><div class="flex flex-wrap gap-1">${toolsBadges}</div></td>
                <td class="py-3 px-4 text-right mono ${u.aiStudioCalls > 0 ? 'font-bold text-amber-800' : 'text-slate-400'}" data-sort-val="${escapeHtml(u.aiStudioCalls)}">${fmtNum(u.aiStudioCalls)}</td>
                <td class="py-3 px-4 text-right mono bg-indigo-50/30" data-sort-val="${escapeHtml(u.antigravityIdeCostUsd || (u.antigravityIdeCalls * 0.0001))}">
                  ${u.antigravityIdeCalls > 0
                    ? `<div class="font-extrabold text-indigo-900">${fmtUsd(u.antigravityIdeCostUsd)} <span class="text-[10px] text-slate-500">(${fmtEur(u.antigravityIdeCostUsd)})</span></div>
                       <div class="text-[10px] font-bold text-indigo-700">${fmtNum(u.antigravityIdeCalls)} calls (${escapeHtml(u.codeAssistCalls > 0 ? `${u.codeAssistCalls} IDE` : '')}${u.codeAssistCalls > 0 && u.aiStudioCalls > 0 ? ' + ' : ''}${escapeHtml(u.aiStudioCalls > 0 ? `${fmtNum(u.aiStudioCalls)} API Key` : '')})</div>`
                    : `<div class="text-slate-400 font-semibold text-[11px]">$0.00 <span class="text-[9px] font-normal">(0 call GCP)</span></div>`
                  }
                </td>
                <td class="py-3 px-4 text-right mono ${(u.notebookLmCalls + u.colabCalls) > 0 ? 'font-bold text-teal-800' : 'text-slate-400'}" data-sort-val="${escapeHtml(u.notebookLmCalls + u.colabCalls)}">${fmtNum(u.notebookLmCalls + u.colabCalls)}</td>
                <td class="py-3 px-4 text-right mono ${u.agentspaceCalls > 0 ? 'font-bold text-purple-800' : 'text-slate-400'}" data-sort-val="${escapeHtml(u.agentspaceCalls)}">${fmtNum(u.agentspaceCalls)}</td>
                <td class="py-3 px-4 text-right mono font-semibold text-slate-800" data-sort-val="${escapeHtml(u.totalTokens)}">${fmtTok(u.totalTokens)}</td>
                <td class="py-3 px-4 text-right mono font-extrabold text-emerald-700" data-sort-val="${escapeHtml(u.totalCostUsd)}">${fmtUsd(u.totalCostUsd)} <span class="text-[10px] text-slate-500">(${fmtEur(u.totalCostUsd)})</span></td>
              </tr>
            `;
          }).join('')
        : `<tr><td colspan="9" class="py-8 text-center text-slate-400">No users found for the current filters.</td></tr>`;

      setSafeHtml(container, `
        <!-- Sub-Tab Bar Orizzontale (AI Studio & Notebook) -->
        <div class="subtab-bar jt-tabs">
          <button type="button" data-subtab-btn="notebooks" data-jt-click="switchSubTab('ai-tools', 'notebooks')" class="subtab-btn active" title="Gemini Notebooks, Colab Enterprise, Vertex AI Workbench &amp; NotebookLM — Gemini Notebooks &amp; Scheduled Colab">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Notebooks &amp; Colab</span>
            <span class="subtab-badge">${filteredNotebooks.length}</span>
          </button>
          <button type="button" data-subtab-btn="ai-studio" data-jt-click="switchSubTab('ai-tools', 'ai-studio')" class="subtab-btn" title="Google AI Studio Projects, API Keys &amp; Users — Google AI Studio Projects &amp; Keys">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> AI Studio</span>
            <span class="subtab-badge">${filteredAiStudio.length}</span>
          </button>
          <button type="button" data-subtab-btn="users-matrix" data-jt-click="switchSubTab('ai-tools', 'users-matrix')" class="subtab-btn" title="Cross-reference Matrix of Users × AI Tools Used — Users × AI Tools Matrix">
            <span><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> User × Tool Matrix</span>
            <span class="subtab-badge">${filteredToolUsers.length}</span>
          </button>
        </div>

        <!-- Tabella 1: Progetti & Chiavi Google AI Studio -->
        <div data-subtab-panel="ai-studio" class="jt-table-panel hidden bg-white rounded-xl border border-amber-200 shadow-2xs overflow-hidden">
          <div class="px-4 py-3 bg-amber-50/70 border-b border-amber-200 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="text-xs font-extrabold uppercase tracking-wider text-amber-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Google AI Studio — Created Projects (<code class="mono">gen-lang-client-*</code>), API Keys &amp; Users (${filteredAiStudio.length})</h3>
              <p class="text-[11px] text-amber-800 mt-0.5">Automatic inventory of all projects created by <b>Google AI Studio</b> (both <b>Pay-As-You-Go</b> with Billing and <b>Free-Tier</b> without Billing) and of all keys that call <code class="mono">generativelanguage.googleapis.com</code>.</p>
            </div>
            <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener" class="btn-nowrap px-3 py-1.5 rounded-lg bg-amber-700 hover:bg-amber-800 text-white font-bold text-xs transition whitespace-nowrap shrink-0">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Open Google AI Studio ↗
            </a>
          </div>
          <div class="overflow-x-auto">
            <table class="jt-table jt-sticky-first w-full text-left border-collapse">
              <thead>
                <tr class="border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-50">
                  <th class="py-2.5 px-4">AI Studio / GCP Project</th>
                  <th class="py-2.5 px-4">Plan / Billing</th>
                  <th class="py-2.5 px-4">Who Uses AI Studio (Key Creator)</th>
                  <th class="py-2.5 px-4">API Keys &amp; Usage per Key</th>
                  <th class="py-2.5 px-4 text-right">200 OK Calls</th>
                  <th class="py-2.5 px-4 text-right">Tokens &amp; HTTP Payload</th>
                  <th class="py-2.5 px-4 text-right">Net Cost ($ / €)</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 text-xs">${aiStudioRowsHtml}</tbody>
            </table>
          </div>
        </div>

        <!-- Tabella 2: Gemini Notebooks (Colab Enterprise, Vertex Workbench & NotebookLM Enterprise) -->
        <div data-subtab-panel="notebooks" class="jt-table-panel bg-white rounded-xl border border-teal-200 shadow-2xs overflow-hidden">
          <div class="px-4 py-3 bg-teal-50/70 border-b border-teal-200 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="text-xs font-extrabold uppercase tracking-wider text-teal-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Gemini Notebooks — Colab Enterprise, Vertex AI Workbench &amp; NotebookLM Enterprise (${filteredNotebooks.length} Resources Grouped from ${notebookResources.length + notebookLmProjects.length} total)</h3>
              <p class="text-[11px] text-teal-800 mt-0.5">Monitoring of <b>NotebookLM Enterprise</b> (<code class="mono">svc_notebooklm_enterprise</code>), <b>Colab Enterprise</b> (Runtimes, Runtime Templates, scheduled Execution Jobs grouped by notebook) and <b>Vertex AI Workbench</b>. Click the user for the history of all runs.</p>
            </div>
            <a href="https://console.cloud.google.com/vertex-ai/colab/notebooks" target="_blank" rel="noopener" class="btn-nowrap px-3 py-1.5 rounded-lg bg-teal-700 hover:bg-teal-800 text-white font-bold text-xs transition whitespace-nowrap shrink-0">
              <svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Open Colab Enterprise in GCP ↗
            </a>
          </div>
          <div class="overflow-x-auto">
            <table class="jt-table jt-sticky-first w-full text-left border-collapse">
              <thead>
                <tr class="border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-50">
                  <th class="py-2.5 px-4">Tool / Notebook Type</th>
                  <th class="py-2.5 px-4">Resource / Runtime Name</th>
                  <th class="py-2.5 px-4">Project &amp; Region</th>
                  <th class="py-2.5 px-4">Assigned User / Service Account</th>
                  <th class="py-2.5 px-4">Machine Details / Activity</th>
                  <th class="py-2.5 px-4">Status</th>
                  <th class="py-2.5 px-4 text-right">Console GCP</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 text-xs">${notebooksRowsHtml}</tbody>
            </table>
          </div>
        </div>

        <!-- Tabella 3: Matrice Utenti x Tool AI -->
        <div data-subtab-panel="users-matrix" class="jt-table-panel hidden bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
          <div class="px-4 py-3 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="text-xs font-extrabold uppercase tracking-wider text-slate-800"><svg class="jt-ico" aria-hidden="true"><use href="#ico-user"/></svg> Users × AI Tools Used Matrix (${filteredToolUsers.length} Users)</h3>
              <p class="text-[11px] text-slate-500 mt-0.5">Cross-summary of who uses <b>AI Studio / Antigravity</b>, <b>NotebookLM Enterprise</b>, <b>Colab / Workbench</b>, <b>Gemini Enterprise (Agentspace)</b> and <b>Gemini Code Assist</b>.</p>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table class="jt-table jt-sticky-first w-full text-left border-collapse">
              <thead>
                <tr class="border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-50">
                  <th class="py-2.5 px-4">User &amp; Keys</th>
                  <th class="py-2.5 px-4">Projects</th>
                  <th class="py-2.5 px-4">AI Tools Used</th>
                  <th class="py-2.5 px-4 text-right">Call AI Studio / Key</th>
                  <th class="py-2.5 px-4 text-right bg-indigo-50/60 text-indigo-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Antigravity / IDE &amp; Code Assist</th>
                  <th class="py-2.5 px-4 text-right">Call Notebook / Colab</th>
                  <th class="py-2.5 px-4 text-right">Call Agentspace / Search</th>
                  <th class="py-2.5 px-4 text-right">Total Tokens</th>
                  <th class="py-2.5 px-4 text-right">Total Cost ($ / €)</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 text-xs">${toolUsersRowsHtml}</tbody>
            </table>
          </div>
        </div>
      `);
      applyActiveSubTab('ai-tools');
    }

    // VISTA 4: MODELLI AI (INSTALLATI DA MODEL GARDEN vs CONFIGURATI NELLE APP vs UTILIZZATI)
    function renderModelsTable(agg) {
      const mgSection = document.getElementById('model-garden-and-apps-section');
      const tbody = document.getElementById('models-tbody');
      const q = (document.getElementById('search-input').value || '').toLowerCase().trim();

      const rows = [];
      const mgResources = [];
      const geminiApps = [];
      const usedModelsSet = new Set();

      (globalScanData.projects || []).forEach(p => {
        if (!isProjectVisibleByToggles(p)) return;
        if (agg.selProj !== 'ALL' && p.projectId !== agg.selProj) return;

        (p.models || []).forEach(m => {
          usedModelsSet.add((m.modelId || '').toLowerCase());
          if (agg.selModel !== 'ALL' && m.modelId !== agg.selModel) return;
          rows.push({
            projectId: p.projectId,
            modelId: m.modelId,
            locations: (m.locations || []).join(', '),
            invocations: m.invocations || 0,
            inputTokens: m.inputTokens || 0,
            outputTokens: (m.outputTokens || 0) + (m.thinkingTokens || 0),
            rawOutputTokens: m.outputTokens || 0,
            thinkingTokens: m.thinkingTokens || 0,
            cachedTokens: m.cachedTokens || 0,
            totalTokens: m.totalTokens || 0,
            grossCostUsd: m.grossCostUsd || m.costUsd || 0,
            cacheSavingsUsd: m.cacheSavingsUsd || 0,
            costUsd: m.costUsd || 0,
            tokensEstimatedFromBytes: Boolean(m.tokensEstimatedFromBytes)
          });
        });

        (p.deployedAiResources || []).forEach(r => {
          if (r.resourceType === 'VERTEX_MODEL_GARDEN' || r.resourceType === 'VERTEX_MODEL' || r.resourceType === 'VERTEX_ENDPOINT') {
            mgResources.push({ ...r, projectId: p.projectId, projectName: p.name });
          } else if (r.resourceType === 'AGENTSPACE_APP' && (r.isGeminiEnterprise || (r.enabledModels && r.enabledModels.length > 0) || r.cid)) {
            geminiApps.push({ ...r, projectId: p.projectId, projectName: p.name });
          }
        });
      });

      // Collect all models enabled in Gemini Enterprise apps to cross-check usage
      const appEnabledModelsMap = {};
      geminiApps.forEach(app => {
        (app.enabledModels || []).forEach(mName => {
          if (!appEnabledModelsMap[mName]) appEnabledModelsMap[mName] = [];
          appEnabledModelsMap[mName].push(app.displayName);
        });
      });

      if (mgSection) {
        const mgRowsHtml = mgResources.length > 0
          ? mgResources.map(r => {
              const isEndpoint = r.resourceType === 'VERTEX_ENDPOINT';
              const activeNodes = r.deployedModelsCount || 0;
              const nameLow = (r.displayName || '').toLowerCase();
              const pubLow = (r.publicModelName || r.modelGardenModel || '').toLowerCase();
              const isUsedInMetrics = Array.from(usedModelsSet).some(um => um.includes(nameLow) || (pubLow && um.includes(pubLow.split('/').pop())));

              const badgeType = isEndpoint
                ? `<span class="jt-badge jt-badge--amber px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200 text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> Endpoint Online (One-Click Deploy)</span>`
                : `<span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Installed Model (Model Garden)</span>`;

              const statusBadge = activeNodes > 0
                ? `<span class="jt-badge jt-badge--green px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-extrabold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> ${escapeHtml(activeNodes)} Active GPU Nodes</span>`
                : `<span class="jt-badge jt-badge--gray px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px] font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg> Idle / 0 Active Nodes ($0 GPU)</span>`;

              const usageBadge = isUsedInMetrics
                ? `<span class="jt-badge jt-badge--blue px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 text-[10px] font-bold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-chart"/></svg> Traffic Detected</span>`
                : `<span class="jt-badge jt-badge--gray px-2 py-0.5 rounded-full bg-slate-50 text-slate-500 border border-slate-200 text-[10px] font-medium">0 calls in the last 30d</span>`;

              const consoleHref = r.consoleUrl || (isEndpoint
                ? `https://console.cloud.google.com/vertex-ai/online-prediction/endpoints?project=${r.projectId}`
                : `https://console.cloud.google.com/vertex-ai/models?project=${r.projectId}`);
              const mgHref = r.modelGardenUrl || `https://console.cloud.google.com/vertex-ai/model-garden?project=${r.projectId}`;

              return `
                <tr class="hover:bg-slate-50">
                  <td class="py-3 px-4">
                    <div class="font-bold text-slate-900 mono">${escapeHtml(r.displayName)}</div>
                    <div class="text-[10px] text-slate-400 mono">ID: ${escapeHtml(r.resourceId)}</div>
                  </td>
                  <td class="py-3 px-4">${badgeType}</td>
                  <td class="py-3 px-4 mono text-slate-700 font-semibold">${escapeHtml(r.projectId)} <span class="text-slate-400">(${escapeHtml(r.location)})</span></td>
                  <td class="py-3 px-4">
                    <div class="text-slate-700 text-[11px]">${escapeHtml(r.details || '—')}</div>
                  </td>
                  <td class="py-3 px-4">
                    <div class="flex flex-col gap-1 items-start">
                      ${statusBadge}
                      ${usageBadge}
                    </div>
                  </td>
                  <td class="py-3 px-4 text-right whitespace-nowrap">
                    <div class="inline-flex items-center gap-1.5">
                      <a href="${escapeHtml(consoleHref)}" target="_blank" rel="noopener" class="px-2.5 py-1 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[10px] transition">
                        ${isEndpoint ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-puzzle"/></svg> Open Endpoint' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-doc"/></svg> Model Registry'} ↗
                      </a>
                      <a href="${escapeHtml(mgHref)}" target="_blank" rel="noopener" class="px-2.5 py-1 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-800 border border-emerald-200 font-bold text-[10px] transition">
                        <svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Model Garden ↗
                      </a>
                    </div>
                  </td>
                </tr>
              `;
            }).join('')
          : `<tr><td colspan="6" class="py-6 text-center text-slate-400">No custom model installed from Model Garden or dedicated endpoint found in the selected projects.</td></tr>`;

        const appsModelsHtml = geminiApps.length > 0
          ? geminiApps.map(app => {
              const selOn = app.modelSelector === 'ON';
              const enModels = app.enabledModels || [];
              const disModels = app.disabledModels || [];
              const cfgUrl = app.configUrl || `https://console.cloud.google.com/gen-app-builder/locations/${app.location}/engines/${app.resourceId}/configurations?project=${app.projectId}`;
              const webUrl = app.webAppUrl || (app.cid ? `https://vertexaisearch.cloud.google.com/${app.location}/home/cid/${app.cid}` : '');

              const enBadges = enModels.length > 0
                ? enModels.map(m => {
                    const isUsed = Array.from(usedModelsSet).some(um => um.includes(m.toLowerCase()));
                    return `<span class="jt-badge jt-badge--green inline-flex items-center gap-1 px-2 py-0.5 rounded-md ${isUsed ? 'bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold' : 'bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium'} text-[10px] mono" title="${isUsed ? 'Model enabled, with actual token usage detected' : 'Model enabled in the app'}">
                      ${isUsed ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg>' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-close"/></svg>'} ${escapeHtml(m)} ${isUsed ? '(Used)' : ''}
                    </span>`;
                  }).join(' ')
                : `<span class="text-slate-400 text-[11px]">Google default model</span>`;

              const disBadges = disModels.length > 0
                ? disModels.map(m => `<span class="jt-badge jt-badge--gray inline-block px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 border border-slate-200 text-[10px] mono line-through" title="Disabled in the app configuration">${escapeHtml(m)}</span>`).join(' ')
                : `<span class="text-slate-400 text-[10px]">None</span>`;

              return `
                <tr class="hover:bg-slate-50 align-top">
                  <td class="py-3 px-4">
                    <div class="font-bold text-slate-900">${escapeHtml(app.displayName)}</div>
                    <div class="text-[10px] text-slate-400 mono">Engine: ${escapeHtml(app.resourceId)}</div>
                    ${app.cid ? `<div class="text-[10px] text-indigo-700 font-semibold mono mt-0.5">cid: ${escapeHtml(app.cid)}</div>` : ''}
                  </td>
                  <td class="py-3 px-4 mono text-slate-700 font-semibold whitespace-nowrap">${escapeHtml(app.projectId)} <span class="text-slate-400">(${escapeHtml(app.location)})</span></td>
                  <td class="py-3 px-4 whitespace-nowrap">
                    <span class="jt-badge px-2 py-0.5 rounded-full text-[10px] font-extrabold border ${selOn ? 'jt-badge--green bg-emerald-50 text-emerald-700 border-emerald-200' : 'jt-badge--amber bg-amber-50 text-amber-800 border-amber-300'}">
                      ${selOn ? '<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Selector ON' : '<svg class="jt-ico" aria-hidden="true"><use href="#ico-alert"/></svg> Selector OFF'}
                    </span>
                  </td>
                  <td class="py-3 px-4">
                    <div class="flex flex-wrap gap-1">${enBadges}</div>
                  </td>
                  <td class="py-3 px-4">
                    <div class="flex flex-wrap gap-1">${disBadges}</div>
                  </td>
                  <td class="py-3 px-4 text-right whitespace-nowrap">
                    <div class="inline-flex items-center gap-1.5">
                      <a href="${escapeHtml(cfgUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1 rounded-lg bg-[#0F2A4A] hover:bg-blue-900 text-white font-bold text-[10px] transition">
                        <svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Enable Models ↗
                      </a>
                      ${webUrl ? `<a href="${escapeHtml(webUrl)}" target="_blank" rel="noopener" class="px-2.5 py-1 rounded-lg bg-blue-50 hover:bg-blue-100 text-blue-800 border border-blue-200 font-bold text-[10px] transition"><svg class="jt-ico" aria-hidden="true"><use href="#ico-globe"/></svg> Web App ↗</a>` : ''}
                    </div>
                  </td>
                </tr>
              `;
            }).join('')
          : '';

        const mgBadgeEl = document.getElementById('subtab-badge-models-mg');
        if (mgBadgeEl) mgBadgeEl.textContent = mgResources.length;
        const appsModBadgeEl = document.getElementById('subtab-badge-models-apps');
        if (appsModBadgeEl) appsModBadgeEl.textContent = geminiApps.length;

        setSafeHtml(mgSection, `
          <!-- Tabella 1: Modelli Installati dal Model Garden & Endpoint Dedicati -->
          <div data-subtab-panel="model-garden" class="jt-table-panel bg-white rounded-xl border border-emerald-200 shadow-2xs overflow-hidden">
            <div class="px-4 py-3 bg-emerald-50/70 border-b border-emerald-200 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 class="text-xs font-extrabold uppercase tracking-wider text-emerald-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Models Installed from Vertex AI Model Garden &amp; Dedicated Endpoints (${mgResources.length})</h3>
                <p class="text-[11px] text-emerald-800 mt-0.5">Models downloaded/registered from <b>Model Garden</b> (<code class="mono">aiplatform.googleapis.com/v1/models</code>) and <b>One-Click Deploy Online Endpoints</b> (<code class="mono">endpoints</code>), with GPU node status and actual traffic.</p>
              </div>
              <a href="https://console.cloud.google.com/vertex-ai/model-garden" target="_blank" rel="noopener" class="px-3 py-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs transition whitespace-nowrap shrink-0">
                <svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Open Vertex AI Model Garden Catalog ↗
              </a>
            </div>
            <div class="overflow-x-auto">
              <table class="jt-table w-full text-left border-collapse">
                <thead>
                  <tr class="border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-50">
                    <th class="py-2.5 px-4">Model / Endpoint</th>
                    <th class="py-2.5 px-4">Resource Type</th>
                    <th class="py-2.5 px-4">Project &amp; Region</th>
                    <th class="py-2.5 px-4">Details &amp; Container</th>
                    <th class="py-2.5 px-4">Node Status &amp; Usage</th>
                    <th class="py-2.5 px-4 text-right">GCP Console Link</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 text-xs">${mgRowsHtml}</tbody>
              </table>
            </div>
          </div>

          <div data-subtab-panel="apps-models" class="jt-table-panel bg-white rounded-xl border border-indigo-200 shadow-2xs overflow-hidden">
            <div class="px-4 py-3 bg-indigo-50/70 border-b border-indigo-200 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 class="text-xs font-extrabold uppercase tracking-wider text-indigo-950"><svg class="jt-ico" aria-hidden="true"><use href="#ico-terminal"/></svg> Enabled vs Disabled Models in Gemini Enterprise / Agentspace Apps (${geminiApps.length} Apps)</h3>
                <p class="text-[11px] text-indigo-800 mt-0.5">Shows which models are enabled in each App, which have generated actual traffic (<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> Used) and the direct link to <b>enable the Model Selector</b> or add models.</p>
              </div>
            </div>
            <div class="overflow-x-auto">
              <table class="jt-table w-full text-left border-collapse">
                <thead>
                  <tr class="border-b border-slate-200 text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-50">
                    <th class="py-2.5 px-4">Gemini Enterprise App &amp; CID</th>
                    <th class="py-2.5 px-4">Project &amp; Region</th>
                    <th class="py-2.5 px-4">Model Selector</th>
                    <th class="py-2.5 px-4">Enabled Models (<svg class="jt-ico" aria-hidden="true"><use href="#ico-check"/></svg> = With Token Usage)</th>
                    <th class="py-2.5 px-4">Disabled Models (Can Be Enabled from Console)</th>
                    <th class="py-2.5 px-4 text-right">Configure in GCP</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 text-xs">${appsModelsHtml || `<tr><td colspan="6" class="py-8 text-center text-slate-400">No Gemini Enterprise apps detected for the current filters.</td></tr>`}</tbody>
              </table>
            </div>
          </div>
        `);
      }

      const filtered = rows.filter(r => {
        if (q && !`${r.modelId} ${r.projectId} ${r.locations}`.toLowerCase().includes(q)) return false;
        return true;
      }).sort((a, b) => b.costUsd - a.costUsd || b.totalTokens - a.totalTokens);

      const usedModBadgeEl = document.getElementById('subtab-badge-models-used');
      if (usedModBadgeEl) usedModBadgeEl.textContent = filtered.length;

      if (filtered.length === 0) {
        setSafeHtml(tbody, `<tr><td colspan="11" class="py-10 text-center text-slate-400">No AI model usage recorded in the period.</td></tr>`);
        applyActiveSubTab('models');
        return;
      }

      setSafeHtml(tbody, filtered.map(r => {
        const mLow = (r.modelId || '').toLowerCase();
        const isAiStudio = mLow.includes('ai studio') || (r.locations || '').toLowerCase().includes('ai studio');
        const matchingApps = Object.keys(appEnabledModelsMap).filter(k => mLow.includes(k.toLowerCase()));
        let originBadge = '';
        if (isAiStudio) {
          originBadge = jtTipChip('jt-badge jt-badge--amber rounded-full bg-amber-50 text-amber-800 border border-amber-200', 'ico-key', 'AI Studio', 'API Keys (AI Studio / Antigravity)');
        } else if (matchingApps.length > 0) {
          originBadge = jtTipChip('jt-badge jt-badge--purple rounded-full bg-indigo-50 text-indigo-800 border border-indigo-200', 'ico-globe', 'Gemini Enterprise', `Vertex Serverless + Gemini Enterprise App: ${matchingApps.join(', ')}`);
        } else {
          originBadge = jtTipChip('jt-badge jt-badge--blue rounded-full bg-blue-50 text-blue-700 border border-blue-200', 'ico-globe', 'Vertex MaaS', 'Vertex AI MaaS (Serverless API)');
        }

        return `
          <tr class="hover:bg-slate-50 transition">
            <td class="py-3 px-4 font-bold text-[#0F2A4A] mono" data-sort-val="${escapeHtml(r.modelId)}">${escapeHtml(r.modelId)}${r.tokensEstimatedFromBytes ? ' ' + jtTipChip('jt-badge jt-badge--amber bg-amber-50 text-amber-800 border border-amber-200', '', 'estimated from bytes', 'Some days: tokens are not from exact metrics but estimated from payload bytes') : ''}</td>
            <td class="py-3 px-4">${originBadge}</td>
            <td class="py-3 px-4 mono text-slate-600 font-semibold">${escapeHtml(r.projectId)}</td>
            <td class="py-3 px-4 mono text-slate-500">${escapeHtml(r.locations)}</td>
            <td class="py-3 px-4 text-right mono font-bold text-slate-800" data-sort-val="${escapeHtml(r.invocations)}">${fmtNum(r.invocations)}</td>
            <td class="py-3 px-4 text-right mono text-slate-700" data-sort-val="${escapeHtml(r.inputTokens)}">${fmtNum(r.inputTokens)}</td>
            <td class="py-3 px-4 text-right mono text-slate-700" data-sort-val="${escapeHtml(r.outputTokens)}">
              <div>${fmtNum(r.outputTokens)}</div>
              ${r.thinkingTokens > 0 ? `<div class="text-[10px] text-purple-700 font-semibold"><svg class="jt-ico" aria-hidden="true"><use href="#ico-bot"/></svg> Think: ${fmtTok(r.thinkingTokens)}</div>` : ''}
            </td>
            <td class="py-3 px-4 text-right mono text-emerald-700" data-sort-val="${escapeHtml(r.cachedTokens)}">${fmtNum(r.cachedTokens)}</td>
            <td class="py-3 px-4 text-right mono font-bold text-slate-900" data-sort-val="${escapeHtml(r.totalTokens)}">${fmtNum(r.totalTokens)}</td>
            <td class="py-3 px-4 text-right mono" data-sort-val="${escapeHtml(r.costUsd)}">
              <div><span class="font-extrabold text-emerald-700">${fmtUsd(r.costUsd)}</span> <span class="text-[11px] font-bold text-slate-500">(${fmtEur(r.costUsd)})</span></div>
              ${r.cacheSavingsUsd > 0 ? `<div class="text-[10px] text-slate-400">Gross ${fmtEur(r.grossCostUsd)} · Cache -${fmtEur(r.cacheSavingsUsd)}</div>` : ''}
            </td>
            <td class="py-3 px-4 text-right">
              <button type="button" data-jt-click="selectSingleModelFilter(${jsArg(r.projectId)}, ${jsArg(r.modelId)})" class="px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold text-[11px] cursor-pointer whitespace-nowrap shrink-0">
                Filter
              </button>
            </td>
          </tr>
        `;
      }).join(''));

      applyActiveSubTab('models');
    }

