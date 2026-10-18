(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const input = $('#wordle-guess');
  let game = null, csrf = '', busy = false;
  const status = message => { $('#wordle-status').textContent = message; };
  async function api(path, body) {
    const response = await fetch('/api/tools/wordle/' + path, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type':'application/json', 'X-CSRF-Token':csrf}, body:JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to save your game.');
    return data;
  }
  function controls() {
    const active = game?.status === 'active';
    input.disabled = !active || busy; $('#wordle-submit').disabled = !active || busy;
    $('#wordle-new').disabled = busy || !csrf; $('#wordle-refresh').disabled = busy;
    $('#wordle-hard').disabled = busy;
    $('#wordle-keyboard').querySelectorAll('button').forEach(button => { button.disabled = !active || busy; });
  }
  function render(data) {
    game = data.game; if (data.csrf_token) csrf = data.csrf_token;
    $('#wordle-hard').checked = Boolean(game?.hard_mode);
    const grid = $('#wordle-grid'); grid.replaceChildren();
    const priority = {absent:1,present:2,correct:3}, keys = {};
    for (let row = 0; row < 6; row++) {
      const line = document.createElement('div'); line.className = 'wordle-row';
      const entry = game?.guesses[row];
      for (let column = 0; column < 5; column++) {
        const tile = document.createElement('span'); const letter = entry?.word[column], mark = entry?.marks[column];
        tile.className = 'wordle-tile' + (mark ? ' '+mark : ''); tile.textContent = letter?.toUpperCase() || '';
        tile.setAttribute('aria-label',letter ? `${letter.toUpperCase()}: ${mark}` : 'Empty'); line.append(tile);
        if (letter && (priority[mark] > (priority[keys[letter]] || 0))) keys[letter] = mark;
      }
      grid.append(line);
    }
    $('#wordle-keyboard').querySelectorAll('[data-letter]').forEach(button => { button.className = keys[button.dataset.letter] || ''; });
    const stats = $('#wordle-stats'); stats.replaceChildren();
    for (const [label,key] of [['Played','played'],['Wins','wins'],['Win %','win_percent'],['Current streak','current_streak'],['Best streak','max_streak']]) {
      const pair = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = data.stats[key]; pair.append(dt,dd); stats.append(pair);
    }
    const distribution = $('#wordle-distribution'); distribution.replaceChildren();
    Object.entries(data.stats.distribution).forEach(([attempt,count]) => { const li = document.createElement('li');li.textContent = `${attempt} ${attempt === '1' ? 'guess' : 'guesses'}: ${count}`;distribution.append(li); });
    status(!game ? 'Start a new game.' : game.status === 'won' ? `You won in ${game.guesses.length}! The word was ${game.answer.toUpperCase()}.`
      : game.status === 'lost' ? `The word was ${game.answer.toUpperCase()}. Try another game.` : `${game.guesses.length} of 6 guesses used${game.hard_mode ? ' · Hard mode' : ''}.`);
    controls();
  }
  for (const letters of ['qwertyuiop','asdfghjkl','zxcvbnm']) {
    const row = document.createElement('div'); row.className = 'wordle-key-row';
    for (const letter of letters) {
      const button = document.createElement('button');button.type = 'button';button.dataset.letter = letter;button.textContent = letter.toUpperCase();
      button.addEventListener('click',() => { if (input.value.length < 5) input.value += letter.toUpperCase(); input.focus(); });row.append(button);
    }
    $('#wordle-keyboard').append(row);
  }
  const actions = document.createElement('div'); actions.className = 'wordle-key-row';
  for (const label of ['Enter','Backspace']) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click',() => { if (label === 'Enter') $('#wordle-guess-form').requestSubmit(); else { input.value = input.value.slice(0,-1); input.focus(); } });actions.append(button);
  }
  $('#wordle-keyboard').append(actions);
  async function load() {
    busy = true;controls();
    try { render(await api('game')); } catch(error) { status(error.message); }
    finally { busy = false; controls(); }
  }
  $('#wordle-refresh').addEventListener('click',load);
  $('#wordle-new').addEventListener('click',async () => {
    if (busy) return;
    const reset = game?.status === 'active';
    if (reset && game.guesses.length && !window.confirm('Starting another game counts this game as a loss. Continue?')) return;
    busy = true;controls();
    try { render(await api('games',{hard_mode:$('#wordle-hard').checked,reset,revision:game?.revision})); input.value = ''; }
    catch(error) { status(error.message); }
    finally { busy = false;controls();if (!input.disabled) input.focus(); }
  });
  $('#wordle-guess-form').addEventListener('submit',async event => {
    event.preventDefault();if (busy || game?.status !== 'active') return;
    busy = true;controls();
    try { render(await api(`games/${game.id}/guesses`,{word:input.value,revision:game.revision}));input.value = ''; }
    catch(error) { status(error.message); }
    finally { busy = false;controls();if (!input.disabled) input.focus(); }
  });
  controls();load();
})();
