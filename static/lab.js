(() => {
  const byId = id => document.getElementById(id);
  const set = (id, value) => { byId(id).textContent = value; };
  const element = (tag, cls, value) => {
    const node = document.createElement(tag);
    node.className = cls;
    node.textContent = value;
    return node;
  };
  function draw(state) {
    const status = byId('labStatus');
    status.textContent = state.error ? 'ERROR' : state.running ? 'LIVE' : state.result ? 'COMPLETE' : 'READY';
    status.className = 'lab-status' + (state.error ? ' error' : state.running ? ' running' : '');
    byId('runLab').disabled = state.running;
    set('labStage', state.error || state.stage);
    set('labCommitted', `${state.committed} / 50`);
    set('labWaiting', Object.keys(state.waiting).length);
    set('labHeld', Object.keys(state.holders).length);
    set('labWaitCount', state.wait_count);
    byId('labProgress').style.width = `${Math.min(100, state.committed * 2)}%`;

    const locks = byId('lockRows');
    locks.replaceChildren();
    [1, 2, 3].forEach(account => {
      const row = element('div', 'lock-row', '');
      row.append(element('div', 'lock-name', `Account ${account}`));
      const track = element('div', 'lock-track', '');
      const holder = state.holders[account];
      if (holder) track.append(element('span', 'lock-holder', `● ${holder} holds`));
      Object.entries(state.waiting).filter(([, id]) => Number(id) === account).forEach(([name]) => track.append(element('span', 'lock-waiter', `◷ ${name} waits`)));
      if (!track.children.length) track.append(element('span', 'lock-free', 'Available'));
      row.append(track); locks.append(row);
    });
    const graph = byId('waitGraph'); graph.replaceChildren();
    const displayEdges = state.edges.length ? state.edges : !state.running ? state.last_edges : [];
    set('graphMode', state.edges.length ? 'live dependency edges' : displayEdges.length ? 'last observed wait' : 'live dependency edges');
    if (!displayEdges.length) graph.append(element('span', 'empty-graph', 'No thread is waiting right now.'));
    displayEdges.slice(0, 6).forEach(edge => {
      const row = element('div', 'wait-edge', '');
      row.append(element('span', '', edge.waiter), element('b', '', '→'), element('span', '', edge.holder), element('small', '', `on account ${edge.account}`));
      graph.append(row);
    });
    const feed = byId('labEvents'); feed.replaceChildren();
    if (!state.events.length) feed.append(element('div', 'empty-graph', 'Events appear here during the run.'));
    state.events.slice(0, 35).forEach(event => {
      const row = element('div', 'event-item', '');
      row.append(element('time', '', event.time), element('span', `event-kind ${event.kind}`, event.kind.replace('_', ' ')), element('span', '', event.message));
      feed.append(row);
    });
    if (!state.result) return;
    const {race, deadlock, sample, rollback} = state.result;
    set('raceExpected', race.expected); set('raceUnsafe', race.without_lock); set('raceSafe', race.with_lock);
    set('deadlockResult', deadlock.workers_finished && deadlock.circular_wait_observed ? '✓ Both workers finished after timeout' : 'Check the forced example');
    const lines = byId('deadlockEvents'); lines.replaceChildren();
    deadlock.events.forEach(event => lines.append(element('div', '', event)));
    set('sampleCount', `${sample.successful}/${sample.requested_operations}`);
    set('sampleTime', `${sample.elapsed_seconds}s`);
    set('sampleLedger', sample.accounting_correct && sample.all_operations_accounted_for ? 'PASS' : 'FAIL');
    set('rollbackBalance', rollback.balances_unchanged ? 'UNCHANGED' : 'CHANGED');
    set('rollbackCommitted', rollback.committed_records);
    set('rollbackResult', rollback.passed ? 'PASS' : 'FAIL');
  }
  async function refresh() {
    try {
      const response = await fetch('/lab/api/state', {cache: 'no-store'});
      if (!response.ok) throw new Error(`Status ${response.status}`);
      draw(await response.json());
    } catch (error) {
      set('labStage', `Monitor unavailable: ${error.message}`);
    }
  }
  refresh();
  setInterval(refresh, 250);
})();
