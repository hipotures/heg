(() => {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const TABS = [
    ['graph', 'Graph'],
    ['progress', 'Progress'],
    ['cycles', 'Cycle profile'],
    ['lanes', 'Lanes'],
    ['verification', 'Verification'],
    ['history', 'History'],
  ];
  const clamp = (value, minimum, maximum) =>
    Math.max(minimum, Math.min(maximum, value));
  const numeric = value =>
    typeof value === 'number' && Number.isFinite(value) ? value : null;
  const LIVE_FRONTIER_INTERVAL_SECONDS = [1, 2, 3, 4, 5];
  const DEFAULT_LIVE_FRONTIER_INTERVAL_SECONDS = 5;

  window.createScientificObservatory = options => {
    const {root, api, esc, fmt, label, shortId, badge} = options;
    const savedLiveInterval = Number(
      sessionStorage.getItem('sglab-observatory-live-interval')
    );
    const configuredLiveInterval = Number(
      Number.isFinite(savedLiveInterval) && savedLiveInterval > 0
        ? savedLiveInterval
        : options.liveFrontierIntervalSeconds
    );
    const liveFrontierIntervalSeconds =
      LIVE_FRONTIER_INTERVAL_SECONDS.includes(configuredLiveInterval)
        ? configuredLiveInterval
        : DEFAULT_LIVE_FRONTIER_INTERVAL_SECONDS;
    const state = {
      campaign: null,
      campaignId: null,
      campaignState: null,
      campaignFault: null,
      source: sessionStorage.getItem('sglab-observatory-source') || 'global_best',
      laneId: sessionStorage.getItem('sglab-observatory-lane') || '',
      candidateId: '',
      tab: sessionStorage.getItem('sglab-observatory-tab') || 'graph',
      graph: null,
      series: null,
      renderKey: '',
      positions: null,
      transform: {x: 0, y: 0, scale: 1},
      selectedVertex: null,
      layers: new Map(),
      refreshing: false,
      refreshQueued: false,
      destroyed: false,
      liveFrontierIntervalSeconds,
      lastLiveFrontierFetchAt: 0,
      forceGraphRefresh: false,
    };

    root.innerHTML = `
      <div class="observatory-shell">
        <div class="observatory-toolbar">
          <div class="observatory-selectors">
            <label>Graph source
              <select data-observatory-source>
                <option value="global_best">Best global candidate</option>
                <option value="live_frontier">Live search frontier</option>
                <option value="lane_best">Best from a lane</option>
                <option value="m4_active">Candidate currently in M4</option>
              </select>
            </label>
            <label data-observatory-live-interval-label hidden>Refresh
              <select data-live-frontier-interval>
                ${LIVE_FRONTIER_INTERVAL_SECONDS.map(seconds =>
                  `<option value="${seconds}" ${seconds === state.liveFrontierIntervalSeconds ? 'selected' : ''}>${seconds} s</option>`
                ).join('')}
              </select>
            </label>
            <label data-observatory-lane-label hidden>Search lane
              <select data-observatory-lane></select>
            </label>
          </div>
          <div class="observatory-status" data-observatory-status aria-live="polite">
            Waiting for campaign data…
          </div>
        </div>
        <div class="observatory-layout">
          <div class="graph-stage" data-graph-stage>
            <div class="graph-stage-controls">
              <button type="button" data-graph-zoom="in" aria-label="Zoom in">+</button>
              <button type="button" data-graph-zoom="out" aria-label="Zoom out">−</button>
              <output data-graph-zoom-level aria-live="off">100%</output>
              <button type="button" data-graph-zoom="reset">Reset</button>
            </div>
            <div class="graph-empty" data-graph-empty>
              Select a retained candidate to inspect its structure.
            </div>
            <svg data-graph-svg viewBox="0 0 1000 680"
                 role="img" aria-label="Selected campaign graph" hidden></svg>
          </div>
          <aside class="observatory-inspector" data-observatory-inspector>
            <div class="empty">No graph selected yet.</div>
          </aside>
        </div>
        <div class="observatory-tabs" role="tablist" aria-label="Scientific visualizations">
          ${TABS.map(([key, title]) => `<button type="button" role="tab"
            data-observatory-tab="${key}" aria-selected="${state.tab === key}">
            ${esc(title)}</button>`).join('')}
        </div>
        <div class="observatory-panel" data-observatory-panel></div>
      </div>`;

    const sourceSelect = root.querySelector('[data-observatory-source]');
    const laneSelect = root.querySelector('[data-observatory-lane]');
    const laneLabel = root.querySelector('[data-observatory-lane-label]');
    const liveIntervalLabel = root.querySelector(
      '[data-observatory-live-interval-label]'
    );
    const status = root.querySelector('[data-observatory-status]');
    const svg = root.querySelector('[data-graph-svg]');
    const graphEmpty = root.querySelector('[data-graph-empty]');
    const zoomLevel = root.querySelector('[data-graph-zoom-level]');
    const inspector = root.querySelector('[data-observatory-inspector]');
    const panel = root.querySelector('[data-observatory-panel]');
    const stage = root.querySelector('[data-graph-stage]');
    const liveIntervalSelect = root.querySelector(
      '[data-live-frontier-interval]'
    );
    if (!TABS.some(([key]) => key === state.tab)) state.tab = 'graph';
    if (!['global_best', 'live_frontier', 'lane_best', 'm4_active'].includes(state.source)) {
      state.source = 'global_best';
    }
    sourceSelect.value = state.source;

    const persistSelection = () => {
      sessionStorage.setItem('sglab-observatory-source', state.source);
      sessionStorage.setItem('sglab-observatory-lane', state.laneId);
      sessionStorage.setItem('sglab-observatory-tab', state.tab);
    };

    const graphQuery = () => {
      const params = new URLSearchParams({source: state.source});
      if (state.source === 'lane_best') params.set('lane_id', state.laneId);
      if (state.source === 'candidate') {
        params.set('candidate_id', state.candidateId);
      }
      return `/api/research-campaign/visualization/graph?${params}`;
    };

    const setStatus = value => {
      status.textContent = value;
    };

    let liveRefreshTimer = null;
    let liveRefreshTimerKey = '';
    const syncLiveRefreshTimer = () => {
      const enabled = state.source === 'live_frontier'
        && state.campaign?.campaign_id
        && state.campaignState === 'running'
        && !state.destroyed;
      const nextKey = enabled
        ? `${state.campaign.campaign_id}:${state.liveFrontierIntervalSeconds}`
        : '';
      if (nextKey === liveRefreshTimerKey) return;
      if (liveRefreshTimer !== null) clearInterval(liveRefreshTimer);
      liveRefreshTimer = null;
      liveRefreshTimerKey = nextKey;
      if (enabled) {
        liveRefreshTimer = setInterval(
          () => {
            state.forceGraphRefresh = true;
            refresh(state.campaign);
          },
          state.liveFrontierIntervalSeconds * 1000,
        );
      }
    };

    const updateSourceControls = data => {
      const lanes = data?.availability?.lanes || state.series?.lanes || [];
      const previousLane = state.laneId;
      laneSelect.innerHTML = lanes.map(lane =>
        `<option value="${esc(lane.lane_id)}">${esc(label(lane.algorithm))} · ${esc(shortId(lane.lane_id))}</option>`
      ).join('');
      if (lanes.some(lane => lane.lane_id === previousLane)) {
        laneSelect.value = previousLane;
      } else if (lanes.length) {
        state.laneId = lanes[0].lane_id;
        laneSelect.value = state.laneId;
      }
      laneLabel.hidden = state.source !== 'lane_best';
      liveIntervalLabel.hidden = state.source !== 'live_frontier';
      const m4 = sourceSelect.querySelector('option[value="m4_active"]');
      m4.disabled = !data?.availability?.m4_active;
      if (state.source === 'candidate') {
        let direct = sourceSelect.querySelector('option[value="candidate"]');
        if (!direct) {
          direct = document.createElement('option');
          direct.value = 'candidate';
          sourceSelect.append(direct);
        }
        direct.textContent = `Selected candidate · ${shortId(state.candidateId)}`;
      } else {
        sourceSelect.querySelector('option[value="candidate"]')?.remove();
      }
      sourceSelect.value = state.source;
      persistSelection();
    };

    const refresh = async campaign => {
      state.campaign = campaign;
      if (!campaign?.campaign_id) {
        state.campaignId = null;
        state.campaignState = null;
        state.campaignFault = null;
        state.graph = null;
        state.series = null;
        showEmpty('No research campaign is selected.');
        syncLiveRefreshTimer();
        return;
      }
      if (state.refreshing) {
        state.refreshQueued = true;
        return;
      }
      if (state.campaignId !== campaign.campaign_id) {
        state.campaignId = campaign.campaign_id;
        state.graph = null;
        state.series = null;
        state.renderKey = '';
        state.positions = null;
        state.transform = {x: 0, y: 0, scale: 1};
      }
      state.campaignState = campaign.state || null;
      state.campaignFault = campaign.fault_kind || null;
      if (state.source === 'lane_best' && !state.laneId) {
        state.source = 'global_best';
      }
      state.refreshing = true;
      if (!state.graph && !state.series) {
        setStatus('Loading retained scientific evidence…');
      }
      try {
        const now = performance.now();
        const liveDue = state.forceGraphRefresh
          || state.source !== 'live_frontier'
          || !state.graph
          || now - state.lastLiveFrontierFetchAt
            >= state.liveFrontierIntervalSeconds * 1000;
        const [graph, series] = await Promise.all([
          liveDue ? api(graphQuery()) : Promise.resolve(state.graph),
          api('/api/research-campaign/visualization/series'),
        ]);
        if (state.destroyed) return;
        state.series = series;
        updateSourceControls(graph);
        if (liveDue) {
          updateGraph(graph);
          state.forceGraphRefresh = false;
          if (state.source === 'live_frontier') {
            state.lastLiveFrontierFetchAt = performance.now();
          }
        }
        renderActivePanel();
        if (state.source === 'live_frontier') {
          const running = state.campaignState === 'running';
          setStatus(running
            ? `Live frontier · ${fmt(state.liveFrontierIntervalSeconds)} s sampling`
            : `Frontier paused · ${label(state.campaignState || 'not running')}${state.campaignFault ? ` · ${label(state.campaignFault)}` : ''}`);
        } else {
          setStatus(`Updated · ${new Date().toLocaleTimeString()}`);
        }
      } catch (error) {
        setStatus(error.message);
        if (!state.graph) showEmpty(error.message);
      } finally {
        state.refreshing = false;
        syncLiveRefreshTimer();
        if (state.refreshQueued) {
          state.refreshQueued = false;
          refresh(campaign);
        }
      }
    };

    const showEmpty = message => {
      svg.setAttribute('hidden', '');
      graphEmpty.hidden = false;
      graphEmpty.textContent = message;
      inspector.innerHTML = `<div class="empty">${esc(message)}</div>`;
      panel.innerHTML = `<div class="empty">${esc(message)}</div>`;
    };

    const updateGraph = data => {
      state.graph = data;
      const exactKey = JSON.stringify(data.exact_verification || null);
      const renderKey = `${data.selection.graph_sha256}:${exactKey}`;
      if (renderKey !== state.renderKey) {
        renderNetwork(data);
        state.renderKey = renderKey;
      }
      renderInspector(data);
      if (state.tab === 'graph') renderGraphSummary();
    };

    const cycleClass = length =>
      [4, 8, 16, 32].includes(Number(length))
        ? `cycle-${length}` : 'cycle-other';

    const layoutGraph = (graph, prior) => {
      const width = 1000;
      const height = 680;
      const margin = 42;
      const n = graph.vertices.length;
      const sameOrder = prior && prior.length === n;
      const points = Array.from({length: n}, (_, vertex) => {
        if (sameOrder) return {...prior[vertex]};
        const angle = 2 * Math.PI * vertex / Math.max(1, n) - Math.PI / 2;
        const jitter = ((vertex * 1103515245 + 12345) >>> 8) % 29 - 14;
        const radius = Math.min(width, height) * .38 + jitter;
        return {
          x: width / 2 + Math.cos(angle) * radius,
          y: height / 2 + Math.sin(angle) * radius,
        };
      });
      if (n > 180) return points;
      const edges = graph.edges;
      for (let iteration = 0; iteration < 90; iteration += 1) {
        const force = Array.from({length: n}, () => ({x: 0, y: 0}));
        for (let first = 0; first < n; first += 1) {
          for (let second = first + 1; second < n; second += 1) {
            let dx = points[first].x - points[second].x;
            let dy = points[first].y - points[second].y;
            const distance2 = Math.max(36, dx * dx + dy * dy);
            const magnitude = 12500 / distance2;
            const distance = Math.sqrt(distance2);
            dx /= distance;
            dy /= distance;
            force[first].x += dx * magnitude;
            force[first].y += dy * magnitude;
            force[second].x -= dx * magnitude;
            force[second].y -= dy * magnitude;
          }
        }
        for (const [u, v] of edges) {
          const dx = points[v].x - points[u].x;
          const dy = points[v].y - points[u].y;
          const distance = Math.max(1, Math.hypot(dx, dy));
          const magnitude = (distance - 86) * .018;
          force[u].x += dx / distance * magnitude;
          force[u].y += dy / distance * magnitude;
          force[v].x -= dx / distance * magnitude;
          force[v].y -= dy / distance * magnitude;
        }
        const cooling = 1 - iteration / 100;
        for (let vertex = 0; vertex < n; vertex += 1) {
          force[vertex].x += (width / 2 - points[vertex].x) * .003;
          force[vertex].y += (height / 2 - points[vertex].y) * .003;
          points[vertex].x = clamp(
            points[vertex].x + force[vertex].x * cooling,
            margin,
            width - margin,
          );
          points[vertex].y = clamp(
            points[vertex].y + force[vertex].y * cooling,
            margin,
            height - margin,
          );
        }
      }
      return points;
    };

    const cycleMarkup = (vertices, length, classes, authority) => {
      if (!Array.isArray(vertices) || !vertices.length) return '';
      return `<polyline class="cycle-overlay ${classes}"
        data-cycle-vertices="${esc(vertices.join(','))}"
        data-cycle-length="${esc(length)}"
        data-cycle-authority="${esc(authority)}"></polyline>`;
    };

    const applyPositions = positions => {
      for (const edge of svg.querySelectorAll('[data-edge-u]')) {
        const u = positions[Number(edge.dataset.edgeU)];
        const v = positions[Number(edge.dataset.edgeV)];
        edge.setAttribute('x1', u.x);
        edge.setAttribute('y1', u.y);
        edge.setAttribute('x2', v.x);
        edge.setAttribute('y2', v.y);
      }
      for (const vertex of svg.querySelectorAll('[data-vertex]')) {
        const point = positions[Number(vertex.dataset.vertex)];
        vertex.setAttribute('cx', point.x);
        vertex.setAttribute('cy', point.y);
      }
      for (const cycle of svg.querySelectorAll('[data-cycle-vertices]')) {
        const vertices = cycle.dataset.cycleVertices.split(',').map(Number);
        const path = [...vertices, vertices[0]].map(vertex => {
          const point = positions[vertex];
          return `${point.x},${point.y}`;
        }).join(' ');
        cycle.setAttribute('points', path);
      }
    };

    const updateViewport = () => {
      const viewport = svg.querySelector('[data-graph-viewport]');
      if (!viewport) return;
      const {scale} = state.transform;
      const maximumX = 360 + 500 * Math.max(0, scale - 1);
      const maximumY = 240 + 340 * Math.max(0, scale - 1);
      state.transform.x = clamp(state.transform.x, -maximumX, maximumX);
      state.transform.y = clamp(state.transform.y, -maximumY, maximumY);
      viewport.setAttribute(
        'transform',
        `translate(${state.transform.x} ${state.transform.y}) translate(500 340) scale(${scale}) translate(-500 -340)`,
      );
      zoomLevel.textContent = `${Math.round(scale * 100)}%`;
    };

    const renderNetwork = data => {
      const oldPositions = state.positions;
      const sameOrder = oldPositions?.length === data.graph.vertices.length;
      const positions = layoutGraph(data.graph, sameOrder ? oldPositions : null);
      state.positions = positions;
      const heuristic = data.cycle_examples.map(item =>
        cycleMarkup(
          item.vertices,
          item.length,
          cycleClass(item.length),
          item.authority,
        )
      ).join('');
      const exactWitness = data.exact_verification?.witnesses?.[0];
      const exact = exactWitness
        ? cycleMarkup(
            exactWitness.vertices,
            exactWitness.length,
            'cycle-exact',
            exactWitness.authority,
          ) + cycleMarkup(
            exactWitness.vertices,
            exactWitness.length,
            'cycle-exact-core',
            exactWitness.authority,
          )
        : '';
      svg.innerHTML = `
        <g data-graph-viewport>
          <g aria-label="Graph edges">
            ${data.graph.edges.map(([u, v]) =>
              `<line class="graph-edge" data-edge-u="${u}" data-edge-v="${v}"></line>`
            ).join('')}
          </g>
          <g aria-label="Cycle overlays">${heuristic}${exact}</g>
          <g aria-label="Graph vertices">
            ${data.graph.vertices.map(vertex =>
              `<circle class="graph-vertex" data-vertex="${vertex}" r="7"
                tabindex="0" role="button" aria-label="Vertex ${vertex}">
                <title>Vertex ${vertex}</title>
              </circle>`
            ).join('')}
          </g>
        </g>`;
      applyPositions(sameOrder ? oldPositions : positions);
      updateViewport();
      graphEmpty.hidden = true;
      svg.removeAttribute('hidden');
      svg.classList.toggle(
        'is-entering',
        !sameOrder && !matchMedia('(prefers-reduced-motion:reduce)').matches,
      );
      if (sameOrder && !matchMedia('(prefers-reduced-motion:reduce)').matches) {
        const started = performance.now();
        const animate = now => {
          const progress = clamp((now - started) / 460, 0, 1);
          const eased = 1 - Math.pow(1 - progress, 4);
          const frame = positions.map((point, index) => ({
            x: oldPositions[index].x + (point.x - oldPositions[index].x) * eased,
            y: oldPositions[index].y + (point.y - oldPositions[index].y) * eased,
          }));
          applyPositions(frame);
          if (progress < 1) requestAnimationFrame(animate);
        };
        requestAnimationFrame(animate);
      } else {
        applyPositions(positions);
      }
      applyLayerVisibility();
    };

    const renderInspector = data => {
      const selection = data.selection;
      const score = data.score || {};
      const exact = data.exact_verification;
      const lengths = [...new Set([
        ...data.cycle_examples.map(item => Number(item.length)),
        ...(exact?.witnesses || []).map(item => Number(item.length)),
      ])].sort((a, b) => a - b);
      for (const length of lengths) {
        if (!state.layers.has(String(length))) state.layers.set(String(length), true);
      }
      if (!state.layers.has('exact')) state.layers.set('exact', true);
      const layerRows = lengths.map(length => {
        const item = data.cycle_examples.find(value => Number(value.length) === length);
        const suffix = item?.vertices
          ? 'bounded example'
          : item?.search_complete
            ? 'no display example'
            : 'display budget exhausted';
        return `<label><input type="checkbox" data-cycle-toggle="${length}"
          ${state.layers.get(String(length)) ? 'checked' : ''}>
          <span class="cycle-key key-${[4, 8, 16, 32].includes(length) ? length : 'other'}"></span>
          Cycle ${length} · ${esc(suffix)}</label>`;
      }).join('');
      const exactRow = exact?.witnesses?.length
        ? `<label><input type="checkbox" data-cycle-toggle="exact"
             ${state.layers.get('exact') ? 'checked' : ''}>
             <span class="cycle-key key-exact"></span>
             Exact M4 witness · cycle ${exact.witnesses[0].length}</label>`
        : '<div class="meta">No exact M4 witness is available for this candidate.</div>';
      inspector.innerHTML = `
        <div>
          <div class="chips">${badge(selection.state)}
            ${selection.transient ? badge('transient heuristic') : ''}
            ${selection.verification_status ? badge(selection.verification_status) : ''}
          </div>
          <h3 title="${esc(selection.candidate_id)}">${esc(shortId(selection.candidate_id))}</h3>
          <p class="meta">From ${esc(shortId(selection.lane_id))} · ${esc(selection.published_at || selection.created_at)}</p>
        </div>
        <dl class="semantic">
          <div><dt>Order / edges</dt><dd>${fmt(data.graph.order)} / ${fmt(data.graph.size)}</dd></div>
          <div><dt>Weighted penalty</dt><dd>${fmt(score.weighted_penalty)}</dd></div>
          <div><dt>Score coverage</dt><dd>${score.complete === false ? 'Approximate / truncated' : score.complete === true ? 'Complete' : 'Unrecorded'}</dd></div>
          ${selection.transient ? `<div><dt>Lane evaluations</dt><dd>${fmt(selection.high_water)}</dd></div>` : ''}
          <div><dt>Graph SHA-256</dt><dd class="id" title="${esc(selection.graph_sha256)}">${esc(shortId(selection.graph_sha256))}</dd></div>
        </dl>
        ${selection.transient
          ? '<div class="observatory-warning">Live frontier is transient heuristic telemetry. It is not a retained scientific record or exact certification.</div>'
          : ''}
        ${score.complete === false
          ? '<div class="observatory-warning">Witness counts are capped or incomplete. They are heuristic measurements, not certification.</div>'
          : ''}
        <div class="layer-controls">
          <strong>Visible cycle layers</strong>
          ${layerRows}${exactRow}
        </div>`;
    };

    const applyLayerVisibility = () => {
      for (const cycle of svg.querySelectorAll('[data-cycle-length]')) {
        const exact = cycle.dataset.cycleAuthority === 'persisted_M4_manifest';
        const key = exact ? 'exact' : cycle.dataset.cycleLength;
        cycle.hidden = state.layers.get(String(key)) === false;
      }
    };

    const renderGraphSummary = () => {
      if (!state.graph) {
        panel.innerHTML = '<div class="empty">No graph selected yet.</div>';
        return;
      }
      const graph = state.graph.graph;
      const exact = state.graph.exact_verification;
      const vertex = Number.isInteger(state.selectedVertex)
        && state.selectedVertex >= 0
        && state.selectedVertex < graph.order
        ? state.selectedVertex
        : null;
      if (vertex === null) state.selectedVertex = null;
      const neighbours = vertex === null
        ? []
        : graph.edges.flatMap(edge => {
            if (edge[0] === vertex) return [edge[1]];
            if (edge[1] === vertex) return [edge[0]];
            return [];
          }).sort((a, b) => a - b);
      const displayMemberships = vertex === null
        ? []
        : state.graph.cycle_examples
          .filter(item => item.vertices?.includes(vertex))
          .map(item => Number(item.length))
          .sort((a, b) => a - b);
      const exactMemberships = vertex === null
        ? []
        : (exact?.witnesses || [])
          .filter(item => item.vertices?.includes(vertex))
          .map(item => Number(item.length))
          .sort((a, b) => a - b);
      panel.innerHTML = `
        <div class="observatory-legend">
          <span><span class="cycle-key"></span>Bounded display examples</span>
          <span><span class="cycle-key key-exact"></span>Persisted exact M4 witness</span>
        </div>
        <p class="meta">The layout is deterministic for the selected graph. Display scans never certify absence. ${exact
          ? `M4 artifact integrity: ${esc(label(exact.integrity_status))}.`
          : 'This candidate has no terminal M4 artifact.'}</p>
        ${vertex === null
          ? '<div class="observatory-guidance"><strong>Inspect a vertex</strong><span>Select any node in the graph to see its adjacency and cycle membership.</span></div>'
          : `<div class="vertex-inspector">
              <h3>Vertex ${fmt(vertex)}</h3>
              <dl class="semantic">
                <div><dt>Degree</dt><dd>${fmt(neighbours.length)}</dd></div>
                <div><dt>Adjacent vertices</dt><dd>${neighbours.length ? neighbours.map(fmt).join(', ') : 'None'}</dd></div>
                <div><dt>Bounded display cycles</dt><dd>${displayMemberships.length ? displayMemberships.map(length => `length ${fmt(length)}`).join(', ') : 'None shown'}</dd></div>
                <div><dt>Exact M4 witness</dt><dd>${exactMemberships.length ? exactMemberships.map(length => `length ${fmt(length)}`).join(', ') : 'Not on the persisted witness'}</dd></div>
              </dl>
            </div>`}`;
    };

    const lineChart = points => {
      if (!points.length) return '<div class="empty">No numeric record series yet.</div>';
      const width = 1000;
      const height = 288;
      const margin = {left: 72, right: 26, top: 24, bottom: 46};
      const values = points.map(point => point.value);
      let minimum = Math.min(...values);
      let maximum = Math.max(...values);
      if (minimum === maximum) {
        minimum -= 1;
        maximum += 1;
      }
      const x = index => margin.left + index / Math.max(1, points.length - 1)
        * (width - margin.left - margin.right);
      const y = value => margin.top + (maximum - value) / (maximum - minimum)
        * (height - margin.top - margin.bottom);
      const path = points.map((point, index) =>
        `${index ? 'L' : 'M'} ${x(index).toFixed(2)} ${y(point.value).toFixed(2)}`
      ).join(' ');
      return `<div class="chart-frame">
        <svg viewBox="0 0 ${width} ${height}" role="img"
             aria-label="Weighted penalty record progression">
          <line class="chart-axis" x1="${margin.left}" y1="${height - margin.bottom}"
                x2="${width - margin.right}" y2="${height - margin.bottom}"></line>
          <line class="chart-axis" x1="${margin.left}" y1="${margin.top}"
                x2="${margin.left}" y2="${height - margin.bottom}"></line>
          <text class="chart-label" x="8" y="${margin.top + 5}">${esc(String(maximum))}</text>
          <text class="chart-label" x="8" y="${height - margin.bottom + 5}">${esc(String(minimum))}</text>
          <text class="chart-label" x="${margin.left}" y="${height - 13}">oldest retained record</text>
          <text class="chart-label" text-anchor="end" x="${width - margin.right}" y="${height - 13}">latest retained record</text>
          <path class="chart-line" d="${path}"></path>
          ${points.map((point, index) =>
            `<circle class="chart-point" cx="${x(index)}" cy="${y(point.value)}" r="4">
              <title>${esc(shortId(point.candidate_id))}: ${esc(point.value)}</title>
            </circle>`
          ).join('')}
        </svg>
        <div class="meta">${fmt(points.length)} retained records with a numeric weighted penalty.</div>
      </div>`;
    };

    const renderProgress = () => {
      const points = (state.series?.candidate_history || [])
        .filter(item => numeric(item.weighted_penalty) !== null)
        .map(item => ({...item, value: item.weighted_penalty}));
      panel.innerHTML = lineChart(points);
    };

    const renderCycles = () => {
      const counts = state.graph?.score?.witness_counts || {};
      const entries = Object.entries(counts)
        .map(([length, count]) => [Number(length), Number(count)])
        .filter(([, count]) => Number.isFinite(count))
        .sort((a, b) => a[0] - b[0]);
      if (!entries.length) {
        panel.innerHTML = '<div class="empty">No cycle-count profile was retained.</div>';
        return;
      }
      const maximum = Math.max(1, ...entries.map(([, count]) => count));
      panel.innerHTML = `<div class="cycle-bars">${entries.map(([length, count]) =>
        `<div class="cycle-bar-row">
          <strong>Cycle ${length}</strong>
          <div class="cycle-bar-track" aria-label="${count} retained witnesses">
            <div class="cycle-bar-fill" style="width:${100 * count / maximum}%"></div>
          </div>
          <span>${fmt(count)}</span>
        </div>`
      ).join('')}</div>
      <p class="meta">${state.graph.score.complete === false
        ? 'Counts are approximate or truncated by the witness cap.'
        : 'The retained score marks this count profile complete.'}</p>`;
    };

    const renderLanes = () => {
      const latest = new Map();
      for (const window of state.series?.lane_windows || []) latest.set(window.lane_id, window);
      const lanes = state.series?.lanes || [];
      panel.innerHTML = lanes.length
        ? `<div class="lane-viz-list">${lanes.map(lane => {
            const metric = latest.get(lane.lane_id) || {};
            return `<div class="lane-viz-row">
              <div class="viz-value"><span>${badge(lane.state)}</span><strong>${esc(label(lane.algorithm))}</strong><span title="${esc(lane.lane_id)}">${esc(shortId(lane.lane_id))}</span></div>
              <div class="viz-value"><span>Evaluations</span><strong>${fmt(lane.telemetry_high_water)}</strong></div>
              <div class="viz-value"><span>Throughput</span><strong>${numeric(metric.candidates_per_second) === null ? 'Unavailable' : `${fmt(metric.candidates_per_second)}/s`}</strong></div>
              <div class="viz-value"><span>Operator yield</span><strong>${numeric(metric.operator_yield) === null ? 'Unavailable' : `${(100 * metric.operator_yield).toFixed(2)}%`}</strong></div>
              <button type="button" data-show-lane="${esc(lane.lane_id)}">Show lane best</button>
            </div>`;
          }).join('')}</div>`
        : '<div class="empty">No search lanes have been persisted.</div>';
    };

    const renderVerification = () => {
      const jobs = state.series?.verifications || [];
      panel.innerHTML = jobs.length
        ? `<div class="verification-viz-list">${jobs.map(job =>
            `<div class="verification-viz-row">
              <div class="viz-value"><span>${badge(job.state)}</span><strong title="${esc(job.verification_job_id)}">${esc(shortId(job.verification_job_id))}</strong></div>
              <div class="viz-value"><span>Candidate</span><strong title="${esc(job.candidate_id)}">${esc(shortId(job.candidate_id))}</strong></div>
              <div class="viz-value"><span>Result / input</span><strong>${esc(label(job.certification_status || 'pending'))}</strong><span>${job.immutable_snapshot ? 'Immutable snapshot' : 'Legacy candidate reference'}</span></div>
            </div>`
          ).join('')}</div>`
        : '<div class="empty">No M4 verification jobs have been persisted.</div>';
    };

    const renderHistory = () => {
      const history = [...(state.series?.candidate_history || [])].reverse().slice(0, 40);
      panel.innerHTML = history.length
        ? `<div class="history-viz-list">${history.map(item =>
            `<div class="history-viz-row">
              <div class="viz-value"><span>${badge(item.state)}</span><strong title="${esc(item.candidate_id)}">${esc(shortId(item.candidate_id))}</strong><span>${esc(item.created_at)}</span></div>
              <div class="viz-value"><span>Weighted penalty</span><strong>${fmt(item.weighted_penalty)}</strong></div>
              <div class="viz-value"><span>Lane</span><strong title="${esc(item.lane_id)}">${esc(shortId(item.lane_id))}</strong></div>
              <button type="button" data-show-candidate="${esc(item.candidate_id)}">Show graph</button>
            </div>`
          ).join('')}</div>`
        : '<div class="empty">No retained candidate history is available.</div>';
    };

    const renderActivePanel = () => {
      for (const button of root.querySelectorAll('[data-observatory-tab]')) {
        button.setAttribute('aria-selected', String(button.dataset.observatoryTab === state.tab));
      }
      ({
        graph: renderGraphSummary,
        progress: renderProgress,
        cycles: renderCycles,
        lanes: renderLanes,
        verification: renderVerification,
        history: renderHistory,
      })[state.tab]();
    };

    const selectSource = async (source, value = '') => {
      state.source = source;
      if (source === 'lane_best') state.laneId = value || state.laneId;
      if (source === 'candidate') state.candidateId = value;
      state.forceGraphRefresh = true;
      if (source === 'live_frontier') state.lastLiveFrontierFetchAt = 0;
      laneLabel.hidden = source !== 'lane_best';
      liveIntervalLabel.hidden = source !== 'live_frontier';
      persistSelection();
      syncLiveRefreshTimer();
      if (state.campaignId) {
        state.renderKey = '';
        await refresh(state.campaign);
      }
    };

    sourceSelect.addEventListener('change', () => {
      selectSource(sourceSelect.value);
    });
    laneSelect.addEventListener('change', () => {
      state.laneId = laneSelect.value;
      selectSource('lane_best', state.laneId);
    });
    root.addEventListener('change', event => {
      if (event.target === liveIntervalSelect) {
        state.liveFrontierIntervalSeconds = Number(liveIntervalSelect.value);
        sessionStorage.setItem(
          'sglab-observatory-live-interval',
          String(state.liveFrontierIntervalSeconds),
        );
        state.lastLiveFrontierFetchAt = 0;
        state.forceGraphRefresh = true;
        syncLiveRefreshTimer();
        if (state.source === 'live_frontier' && state.campaignId) {
          refresh(state.campaign);
        }
        return;
      }
      const toggle = event.target.closest('[data-cycle-toggle]');
      if (!toggle) return;
      state.layers.set(String(toggle.dataset.cycleToggle), toggle.checked);
      applyLayerVisibility();
    });
    root.addEventListener('click', event => {
      const tab = event.target.closest('[data-observatory-tab]');
      if (tab) {
        state.tab = tab.dataset.observatoryTab;
        persistSelection();
        renderActivePanel();
        return;
      }
      const candidate = event.target.closest('[data-show-candidate]');
      if (candidate) {
        selectSource('candidate', candidate.dataset.showCandidate);
        root.scrollIntoView({behavior: 'smooth', block: 'start'});
        return;
      }
      const lane = event.target.closest('[data-show-lane]');
      if (lane) {
        selectSource('lane_best', lane.dataset.showLane);
        root.scrollIntoView({behavior: 'smooth', block: 'start'});
        return;
      }
      const zoom = event.target.closest('[data-graph-zoom]');
      if (zoom) {
        if (zoom.dataset.graphZoom === 'reset') {
          state.transform = {x: 0, y: 0, scale: 1};
        } else {
          const factor = zoom.dataset.graphZoom === 'in' ? 1.2 : 1 / 1.2;
          state.transform.scale = clamp(state.transform.scale * factor, .55, 4);
        }
        updateViewport();
      }
    });
    svg.addEventListener('click', event => {
      const vertex = event.target.closest('[data-vertex]');
      if (!vertex) return;
      state.selectedVertex = Number(vertex.dataset.vertex);
      for (const item of svg.querySelectorAll('[data-vertex]')) {
        item.classList.toggle('selected', item === vertex);
      }
      if (state.tab === 'graph') renderGraphSummary();
    });

    let drag = null;
    svg.addEventListener('pointerdown', event => {
      if (event.target.closest('[data-vertex]')) return;
      drag = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        x: state.transform.x,
        y: state.transform.y,
      };
      svg.setPointerCapture(event.pointerId);
      svg.classList.add('is-dragging');
    });
    svg.addEventListener('pointermove', event => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const rect = svg.getBoundingClientRect();
      state.transform.x = drag.x + (event.clientX - drag.clientX) * 1000 / rect.width;
      state.transform.y = drag.y + (event.clientY - drag.clientY) * 680 / rect.height;
      updateViewport();
    });
    const endDrag = event => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      drag = null;
      svg.classList.remove('is-dragging');
    };
    svg.addEventListener('pointerup', endDrag);
    svg.addEventListener('pointercancel', endDrag);
    svg.addEventListener('wheel', event => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
      state.transform.scale = clamp(state.transform.scale * factor, .55, 4);
      updateViewport();
    }, {passive: false});

    return {
      refresh,
      showCandidate: candidateId => selectSource('candidate', candidateId),
      showLane: laneId => selectSource('lane_best', laneId),
      destroy: () => {
        state.destroyed = true;
        syncLiveRefreshTimer();
      },
    };
  };
})();
