(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const input = $('#wordle-guess');
  const play = $('#wordle-play');
  const lengthSelect = $('#wordle-length');
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
    // These settings apply to the next game, so keep them editable during a game.
    lengthSelect.disabled = busy;
    $('#wordle-keyboard').querySelectorAll('button').forEach(button => { button.disabled = !active || busy; });
  }
  function draft() {
    const row = $('#wordle-grid .wordle-row.current');
    row?.querySelectorAll('.wordle-tile').forEach((tile, index) => {
      const letter = input.value[index] || '';
      tile.textContent = letter; tile.classList.toggle('filled', Boolean(letter));
      tile.setAttribute('aria-label', letter ? `${letter}: not submitted` : 'Empty');
    });
    $('#wordle-draft').textContent = input.value ? `Current guess: ${input.value.split('').join(' ')}` : 'Current guess is empty.';
  }
  function enterKey(key) {
    if (busy || game?.status !== 'active') return;
    if (key === 'Enter') $('#wordle-guess-form').requestSubmit();
    else {
      if (key === 'Backspace') input.value = input.value.slice(0,-1);
      else if (/^[a-z]$/i.test(key) && input.value.length < Number(input.maxLength)) input.value += key.toUpperCase();
      draft();
    }
  }
  play.addEventListener('keydown', event => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing || event.target.closest('input,select,textarea,[contenteditable="true"]')) return;
    if (/^[a-z]$/i.test(event.key) || event.key === 'Enter' || event.key === 'Backspace') {
      event.preventDefault(); enterKey(event.key);
    }
  });
  input.addEventListener('input', draft);
  function render(data) {
    game = data.game; if (data.csrf_token) csrf = data.csrf_token;
    // Initialize the next-game settings from a saved game when it is loaded. Keep
    // later user changes while guesses update the current game.
    if (game && !render.settingsInitialized) {
      $('#wordle-hard').checked = Boolean(game.hard_mode);
      lengthSelect.value = String(game.word_length || 5);
      render.settingsInitialized = true;
    }
    const wordLength = game?.word_length || Number(lengthSelect.value);
    input.maxLength = wordLength; input.minLength = wordLength; input.pattern = `[A-Za-z]{${wordLength}}`;
    const grid = $('#wordle-grid'); grid.replaceChildren();
    const priority = {absent:1,present:2,correct:3}, keys = {};
    for (let row = 0; row < 6; row++) {
      const line = document.createElement('div'); line.className = 'wordle-row';
      const entry = game?.guesses[row];
      if (!entry && game?.status === 'active' && row === game.guesses.length) line.classList.add('current');
      for (let column = 0; column < wordLength; column++) {
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
    grid.style.setProperty('--word-length', wordLength);
    status(!game ? 'Start a new game.' : game.status === 'won' ? `You won in ${game.guesses.length}! The word was ${game.answer.toUpperCase()}.`
      : game.status === 'lost' ? `The word was ${game.answer.toUpperCase()}. Try another game.` : `${game.guesses.length} of 6 guesses used${game.hard_mode ? ' · Hard mode' : ''}.`);
    draft(); controls();
  }
  function keyButton(key, label=key.toUpperCase()) {
    const button = document.createElement('button');button.type = 'button';button.textContent = label;
    if (/^[a-z]$/i.test(key)) button.dataset.letter = key;
    else { button.dataset.action = key;button.setAttribute('aria-label',key); }
    button.addEventListener('click',() => { enterKey(key);play.focus({preventScroll:true}); });
    return button;
  }
  for (const letters of ['qwertyuiop','asdfghjkl','zxcvbnm']) {
    const row = document.createElement('div');row.className = 'wordle-key-row';
    if (letters === 'zxcvbnm') row.append(keyButton('Enter','Enter'));
    for (const letter of letters) row.append(keyButton(letter));
    if (letters === 'zxcvbnm') row.append(keyButton('Backspace','⌫'));
    $('#wordle-keyboard').append(row);
  }
  async function load() {
    busy = true;controls();
    try { const data = await api('game'); input.value = ''; render(data); if(document.activeElement === document.body) play.focus({preventScroll:true}); } catch(error) { status(error.message); }
    finally { busy = false; controls(); }
  }
  $('#wordle-refresh').addEventListener('click',load);
  $('#wordle-new').addEventListener('click',async () => {
    if (busy) return;
    const reset = game?.status === 'active';
    if (reset && game.guesses.length && !window.confirm('Starting another game counts this game as a loss. Continue?')) return;
    busy = true;controls();
    try { const data = await api('games',{hard_mode:$('#wordle-hard').checked,word_length:Number(lengthSelect.value),reset,revision:game?.revision}); input.value = ''; render(data); }
    catch(error) { status(error.message); }
    finally { busy = false;controls();if (!input.disabled) play.focus({preventScroll:true}); }
  });
  $('#wordle-guess-form').addEventListener('submit',async event => {
    event.preventDefault();if (busy || game?.status !== 'active') return;
    if(input.value.length !== Number(input.maxLength)){status(`Enter ${input.maxLength} letters.`);return;}
    busy = true;controls();
    try { const data = await api(`games/${game.id}/guesses`,{word:input.value,revision:game.revision});input.value = '';render(data); }
    catch(error) { status(error.message); }
    finally { busy = false;controls();if (!input.disabled) play.focus({preventScroll:true}); }
  });
  controls();load();
})();
