// kiWe frontend — talks to the FastAPI app in kebplayground/api.py.
// No build step, no framework: hash routing + template strings, because the
// whole point is to show real data moving from the Python matcher to the
// screen, not to build a production SPA.

const RUN = { count: 60, seed: 1 };
let vocab = null;
let me = null;

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
  return res.json();
}
async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
  return res.json();
}
async function apiPatch(path, body) {
  const res = await fetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
  return res.json();
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function duck(size, bg, eye) {
  const s = size;
  return `<div class="duck-icon" style="width:${s}px;height:${s}px;background:${bg}">
    <div style="position:absolute;left:${s * .22}px;top:${s * .24}px;width:${s * .64}px;height:${s * .64}px;border-radius:50%;background:${eye}"></div>
    <div style="position:absolute;left:${s * .03}px;top:${s * .48}px;width:${s * .38}px;height:${s * .2}px;border-radius:${s * .12}px;background:#E0AC5F;transform:rotate(-20deg)"></div>
  </div>`;
}

// ------------------------------------------------------------------- router

const routes = {};
function on(pattern, handler) { routes[pattern] = handler; }

function parseHash() {
  const hash = (location.hash || '#/feed').slice(1);
  const parts = hash.split('/').filter(Boolean);
  return parts;
}

async function router() {
  const parts = parseHash();
  const top = parts[0] || 'feed';

  if (!me) {
    try { me = await apiGet('/api/me'); } catch (e) { renderError(e); return; }
  }
  if (!vocab) {
    try { vocab = await apiGet('/api/vocabulary'); } catch (e) { renderError(e); return; }
  }

  if (!me.signed_up && top !== 'signup') {
    location.hash = '#/signup';
    return;
  }

  try {
    if (top === 'signup') await screenSignup();
    else if (top === 'preferences') await screenPreferences();
    else if (top === 'feed') await screenFeed();
    else if (top === 'reveal') await screenReveal(parts[1]);
    else if (top === 'profile') await screenProfile(parts[1]);
    else if (top === 'matches') await screenMatches();
    else if (top === 'you') await screenYou();
    else { location.hash = '#/feed'; }
  } catch (e) {
    renderError(e);
  }
}
window.addEventListener('hashchange', router);

function renderError(e) {
  mount(`
    <div class="statusbar"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
    <div class="empty">
      <div class="baloo">Something went wrong.</div>
      ${esc(e.message || String(e))}
    </div>
  `);
}

function mount(innerHtml, { nav = null } = {}) {
  const phone = document.getElementById('phone');
  phone.innerHTML = `<div class="screen">${innerHtml}</div>${nav ? navbar(nav) : ''}`;
  wireNav();
}

function navbar(active) {
  const items = [
    ['feed', 'Feed', false],
    ['matches', 'Matches', true],
    ['you', 'You', false],
  ];
  return `<div class="navbar">
    ${items.map(([key, label, round]) => `
      <div class="item ${active === key ? 'active' : ''}" data-nav="${key}">
        <span class="dot ${round ? 'round' : ''}" style="${key === 'you' ? 'transform:rotate(45deg)' : ''}"></span>
        <span>${label}</span>
      </div>`).join('')}
  </div>`;
}

function wireNav() {
  document.querySelectorAll('[data-nav]').forEach((elm) => {
    elm.addEventListener('click', () => { location.hash = `#/${elm.dataset.nav}`; });
  });
}

// ------------------------------------------------------------------- signup

async function screenSignup() {
  const p = me.profile;
  const state = {
    faculty: p.faculty || Object.keys(vocab.majors_by_faculty)[0],
    major: p.major || '',
    year: p.year || 3,
    age: p.age || 20,
    mbti: p.mbti || 'INFP',
    gender: p.gender || vocab.genders[0],
    area: p.area || vocab.areas[0],
    mode: p.mode || 'friendship',
    languages: new Set(p.languages || []),
    interests: new Set(p.interests || []),
  };

  function render() {
    const majors = vocab.majors_by_faculty[state.faculty] || [];
    if (!majors.includes(state.major)) state.major = majors[0] || '';

    mount(`
      <div class="statusbar"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
      <div class="scroll">
        <div class="baloo" style="font-size:30px;font-weight:800;margin:18px 0 4px">Tell kiWe about you</div>
        <div style="font-size:14px;color:#7A6E95">Every field here feeds the real scorer — nothing is decorative.</div>

        <div class="label">FACULTY</div>
        <div class="chip-row">
          ${Object.keys(vocab.majors_by_faculty).map((f) => `<span class="chip ${f === state.faculty ? 'on' : ''}" data-faculty="${esc(f)}">${esc(f)}</span>`).join('')}
        </div>

        <div class="label">MAJOR</div>
        <div class="chip-row">
          ${majors.map((m) => `<span class="chip ${m === state.major ? 'on' : ''}" data-major="${esc(m)}">${esc(m)}</span>`).join('')}
        </div>

        <div style="display:flex;gap:12px;margin-top:20px">
          <div style="flex:1">
            <div class="label" style="margin-top:0">YEAR</div>
            <select class="field" id="s-year">${vocab.years.map((y) => `<option ${y === state.year ? 'selected' : ''}>${y}</option>`).join('')}</select>
          </div>
          <div style="flex:1">
            <div class="label" style="margin-top:0">AGE</div>
            <input class="field" id="s-age" type="number" min="16" max="60" value="${state.age}">
          </div>
        </div>

        <div style="display:flex;gap:12px;margin-top:16px">
          <div style="flex:1">
            <div class="label" style="margin-top:0">MBTI</div>
            <select class="field" id="s-mbti">${vocab.mbtis.map((m) => `<option ${m === state.mbti ? 'selected' : ''}>${m}</option>`).join('')}</select>
          </div>
          <div style="flex:1">
            <div class="label" style="margin-top:0">GENDER</div>
            <select class="field" id="s-gender">${vocab.genders.map((g) => `<option ${g === state.gender ? 'selected' : ''}>${g}</option>`).join('')}</select>
          </div>
        </div>

        <div class="label">AUCKLAND AREA</div>
        <div class="chip-row">
          ${vocab.areas.map((a) => `<span class="chip ${a === state.area ? 'on' : ''}" data-area="${esc(a)}">${esc(a)}</span>`).join('')}
        </div>

        <div class="label">LOOKING FOR</div>
        <div class="chip-row">
          ${vocab.modes.map((m) => `<span class="chip ${m === state.mode ? 'on' : ''}" data-mode="${esc(m)}">${esc(m[0].toUpperCase() + m.slice(1))}</span>`).join('')}
        </div>

        <div class="label">LANGUAGES <span style="font-weight:500;color:#B4A9CC">besides English</span></div>
        <div class="chip-row">
          ${vocab.languages.map((l) => `<span class="chip ${state.languages.has(l) ? 'on' : ''}" data-lang="${esc(l)}">${esc(l)}</span>`).join('')}
        </div>

        <div class="label">INTERESTS <span style="font-weight:500;color:#B4A9CC">${state.interests.size} picked</span></div>
        <div class="chip-row">
          ${vocab.interests.map((i) => `<span class="chip ${state.interests.has(i) ? 'on' : ''}" data-interest="${esc(i)}">${esc(i)}</span>`).join('')}
        </div>

        <div class="error" id="s-error"></div>
        <div style="height:70px"></div>
      </div>
      <div class="footer">
        <button class="btn-primary" id="s-submit">Next — preferences</button>
      </div>
    `);

    // Chip clicks re-render the whole screen, so plain <input>/<select>
    // fields have to push their live value into state first or a chip
    // click would snap them back to whatever they last rendered with.
    const syncFields = () => {
      state.year = Number(document.getElementById('s-year').value);
      state.age = Number(document.getElementById('s-age').value);
      state.mbti = document.getElementById('s-mbti').value;
      state.gender = document.getElementById('s-gender').value;
    };
    ['s-year', 's-age', 's-mbti', 's-gender'].forEach((id) => {
      document.getElementById(id).addEventListener('input', syncFields);
    });

    document.querySelectorAll('[data-faculty]').forEach((c) => c.addEventListener('click', () => { syncFields(); state.faculty = c.dataset.faculty; render(); }));
    document.querySelectorAll('[data-major]').forEach((c) => c.addEventListener('click', () => { syncFields(); state.major = c.dataset.major; render(); }));
    document.querySelectorAll('[data-area]').forEach((c) => c.addEventListener('click', () => { syncFields(); state.area = c.dataset.area; render(); }));
    document.querySelectorAll('[data-mode]').forEach((c) => c.addEventListener('click', () => { syncFields(); state.mode = c.dataset.mode; render(); }));
    document.querySelectorAll('[data-lang]').forEach((c) => c.addEventListener('click', () => {
      syncFields();
      const l = c.dataset.lang;
      state.languages.has(l) ? state.languages.delete(l) : state.languages.add(l);
      render();
    }));
    document.querySelectorAll('[data-interest]').forEach((c) => c.addEventListener('click', () => {
      syncFields();
      const i = c.dataset.interest;
      state.interests.has(i) ? state.interests.delete(i) : state.interests.add(i);
      render();
    }));

    document.getElementById('s-submit').addEventListener('click', async () => {
      syncFields();
      const errEl = document.getElementById('s-error');
      if (state.interests.size === 0) { errEl.textContent = 'Pick at least one interest.'; return; }
      try {
        const result = await apiPost('/api/signup', {
          major: state.major, faculty: state.faculty, year: state.year, age: state.age,
          mbti: state.mbti, languages: [...state.languages], gender: state.gender,
          area: state.area, interests: [...state.interests], mode: state.mode,
        });
        me = { profile: result.profile, signed_up: true, settings: me.settings };
        location.hash = '#/preferences';
      } catch (e) {
        errEl.textContent = e.message;
      }
    });
  }

  render();
}

// -------------------------------------------------------------- preferences

async function screenPreferences() {
  const p = me.profile;
  const prefs = p.preferences || {};
  const state = {
    genders: new Set(prefs.genders || []),
    ageMin: prefs.age ? prefs.age[0] : 18,
    ageMax: prefs.age ? prefs.age[1] : 30,
    noAgePref: !prefs.age,
    interests: new Set(prefs.interests || []),
    sameArea: !!prefs.same_area_only,
  };

  function render() {
    mount(`
      <div style="background:#B7A4EC;padding:14px 26px 22px;color:#241E33">
        <div style="display:flex;justify-content:space-between;font-size:13px;font-weight:700"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
        <div class="baloo" style="font-weight:800;font-size:28px;margin-top:18px">Who are you after?</div>
        <div style="font-size:13px;line-height:1.5;margin-top:6px;color:#3C3358">Gender and age are hard rules. Interests and area just nudge your score.</div>
      </div>
      <div class="scroll">
        <div class="card-box" style="border:2px solid #332A47;box-shadow:0 5px 0 #E0D6F7">
          <div style="font-weight:700;font-size:15px;margin-bottom:10px" class="baloo">Hard rules</div>
          <div class="label" style="margin-top:0">GENDER (leave empty to skip)</div>
          <div class="chip-row">
            ${vocab.genders.map((g) => `<span class="chip ${state.genders.has(g) ? 'on' : ''}" data-g="${esc(g)}">${esc(g)}</span>`).join('')}
          </div>
          <div class="label">AGE RANGE</div>
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:10px">
            <input type="checkbox" id="p-noage" ${state.noAgePref ? 'checked' : ''}> I don't mind — skip this rule
          </label>
          <div style="display:flex;gap:10px;${state.noAgePref ? 'opacity:.4;pointer-events:none' : ''}" id="p-age-inputs">
            <input class="field" type="number" id="p-age-min" value="${state.ageMin}" style="width:80px">
            <span style="align-self:center">to</span>
            <input class="field" type="number" id="p-age-max" value="${state.ageMax}" style="width:80px">
          </div>
        </div>

        <div style="display:flex;align-items:center;gap:8px;margin:16px 0 10px">
          <span class="baloo" style="font-weight:700;font-size:17px">Nice to haves</span>
          <span style="font-size:12px;color:#9A8FB5;margin-left:auto">lifts the score</span>
        </div>
        <div class="card-box">
          <div style="font-size:14px;font-weight:700;margin-bottom:9px">Interests you'd like shared</div>
          <div class="chip-row">
            ${vocab.interests.map((i) => `<span class="chip ${state.interests.has(i) ? 'on' : ''}" data-i="${esc(i)}">${esc(i)}</span>`).join('')}
          </div>
        </div>
        <div class="card-box" style="margin-top:10px;display:flex;align-items:center;justify-content:space-between">
          <div>
            <div style="font-size:14px;font-weight:700">Same area only</div>
            <div style="font-size:12px;color:#9A8FB5;margin-top:2px">You're in ${esc(p.area)}</div>
          </div>
          <div class="toggle ${state.sameArea ? 'on' : ''}" id="p-same-area"><div class="knob"></div></div>
        </div>
        <div class="error" id="p-error"></div>
        <div style="height:70px"></div>
      </div>
      <div class="footer">
        <button class="btn-primary" id="p-submit">Save preferences</button>
      </div>
    `);

    // Same reason as the signup screen: sync the number inputs into state
    // before any chip click re-renders the form around them.
    const syncAge = () => {
      state.ageMin = Number(document.getElementById('p-age-min').value);
      state.ageMax = Number(document.getElementById('p-age-max').value);
    };
    document.getElementById('p-age-min').addEventListener('input', syncAge);
    document.getElementById('p-age-max').addEventListener('input', syncAge);

    document.querySelectorAll('[data-g]').forEach((c) => c.addEventListener('click', () => {
      syncAge();
      const g = c.dataset.g;
      state.genders.has(g) ? state.genders.delete(g) : state.genders.add(g);
      render();
    }));
    document.querySelectorAll('[data-i]').forEach((c) => c.addEventListener('click', () => {
      syncAge();
      const i = c.dataset.i;
      state.interests.has(i) ? state.interests.delete(i) : state.interests.add(i);
      render();
    }));
    document.getElementById('p-noage').addEventListener('change', (e) => { syncAge(); state.noAgePref = e.target.checked; render(); });
    document.getElementById('p-same-area').addEventListener('click', () => { syncAge(); state.sameArea = !state.sameArea; render(); });

    document.getElementById('p-submit').addEventListener('click', async () => {
      syncAge();
      try {
        const result = await apiPost('/api/preferences', {
          genders: [...state.genders],
          age_min: state.noAgePref ? null : state.ageMin,
          age_max: state.noAgePref ? null : state.ageMax,
          interests: [...state.interests],
          same_area_only: state.sameArea,
        });
        me = { ...me, profile: result.profile };
        location.hash = '#/feed';
      } catch (e) {
        document.getElementById('p-error').textContent = e.message;
      }
    });
  }

  render();
}

// -------------------------------------------------------------------- feed

async function screenFeed() {
  const feed = await apiGet(`/api/feed?count=${RUN.count}&seed=${RUN.seed}`);

  if (feed.paused) {
    mount(`
      <div class="statusbar"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
      <div class="empty">
        <div class="baloo">You're sitting this one out.</div>
        Turn "in the next run" back on from the You tab to be matched again.
      </div>
    `, { nav: 'feed' });
    return;
  }

  if (feed.cards.length === 0) {
    const w = await apiGet(`/api/waiting?count=${RUN.count}&seed=${RUN.seed}`);
    mount(`
      <div class="statusbar"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
      <div class="scroll" style="text-align:center">
        <div style="display:inline-flex;align-items:center;gap:7px;background:#F0EAFF;border-radius:14px;padding:8px 14px;margin-top:10px">
          <span style="width:9px;height:9px;border-radius:50%;background:#E0AC5F"></span>
          <span style="font-size:12.5px;font-weight:700;color:#5A4F76">Run seed ${RUN.seed} finished</span>
        </div>
        <div style="margin:22px auto 0;width:128px" >${duck(128, '#B7A4EC', '#FAE9A8')}</div>
        <div class="baloo" style="font-size:29px;line-height:1.15;margin-top:18px">Nothing good<br>enough yet.</div>
        <div style="font-size:14px;line-height:1.55;color:#6B5F86;margin-top:10px;text-align:left">
          Everyone kiWe could offer you scored under ${w.floor}. You stay on the list for the next run. ${w.waiting.length} people are waiting with you.
        </div>

        <div class="card-box" style="border:2px solid #332A47;box-shadow:0 5px 0 #E0D6F7;margin-top:16px;text-align:left">
          <div style="display:flex;justify-content:space-between;align-items:baseline">
            <span class="baloo" style="font-weight:700;font-size:17px">Your best so far</span>
            <span style="font-size:13px;font-weight:700;color:#7B63C9">${w.best_score}</span>
          </div>
          <div style="height:12px;border-radius:8px;background:#F0EAFF;margin-top:12px;position:relative;overflow:hidden">
            <div style="position:absolute;left:0;top:0;bottom:0;width:${Math.round(w.best_score * 100)}%;background:#B7A4EC;border-radius:8px"></div>
            <div style="position:absolute;left:${Math.round(w.floor * 100)}%;top:-4px;bottom:-4px;width:3px;background:#332A47"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:11.5px;color:#9A8FB5;margin-top:7px">
            <span>0.0</span><span>floor ${w.floor}</span><span>1.0</span>
          </div>
        </div>

        <div class="label">RAISE YOUR ODDS</div>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${w.tips.map((t) => `<div style="background:#F7F1FF;border-radius:18px;padding:11px;font-size:13.5px;line-height:1.4;color:#4E4468;text-align:left">${esc(t)}</div>`).join('')}
        </div>
        <div style="height:20px"></div>
      </div>
    `, { nav: 'feed' });
    return;
  }

  const card = feed.cards[0];
  mount(`
    <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 22px 6px">
      <div style="display:flex;align-items:center;gap:9px">
        ${duck(32, '#B7A4EC', '#FAE9A8')}
        <span class="baloo" style="font-weight:800;font-size:22px">kiWe</span>
      </div>
      <div style="display:flex;align-items:center;gap:7px;background:#FAE9A8;border:2px solid #332A47;border-radius:14px;padding:6px 11px">
        <span style="width:9px;height:9px;border-radius:50%;background:#7B63C9"></span>
        <span style="font-size:12.5px;font-weight:700">${esc(feed.mode[0].toUpperCase() + feed.mode.slice(1))}</span>
      </div>
    </div>
    <div class="remaining">${feed.cards.length} match cleared your floor this run</div>
    <div class="stage">
      <div class="under2"></div><div class="under1"></div>
      <div class="match-card" id="feed-card">
        ${cardInner(card, me.settings.show_scores)}
      </div>
    </div>
    <div class="actions">
      <div class="round-btn pass-btn" id="btn-pass">&#10005;</div>
      <div class="round-btn like-btn" id="btn-like">&#9829;</div>
      <div class="round-btn pass-btn" id="btn-profile" style="color:#7B63C9">&#8635;</div>
    </div>
  `, { nav: 'feed' });

  document.getElementById('btn-profile').addEventListener('click', () => { location.hash = `#/profile/${card.id}`; });
  document.getElementById('btn-pass').addEventListener('click', async () => {
    await apiPost(`/api/feed/${card.id}/pass?count=${RUN.count}&seed=${RUN.seed}`);
    router();
  });
  document.getElementById('btn-like').addEventListener('click', async () => {
    await apiPost(`/api/feed/${card.id}/like?count=${RUN.count}&seed=${RUN.seed}`);
    location.hash = `#/reveal/${card.id}`;
  });
}

function cardInner(card, showScores) {
  return `
    <div class="match-card-scroll">
      <div class="row">
        ${duck(76, '#B7A4EC', '#FAE9A8')}
        <div style="flex:1;min-width:0">
          <div class="name baloo">${esc(card.name)}</div>
          <div class="study">${esc(card.study)}</div>
          <div class="tags">
            <span class="tag-dark">${esc(card.mbti)}</span>
            <span class="tag-light">${esc(card.area)}</span>
          </div>
        </div>
        ${showScores ? `
        <div class="ring" style="background:conic-gradient(#7B63C9 0 ${card.ringPct}, #EFE7FF ${card.ringPct} 100%)">
          <div class="ring-inner baloo">${card.score}</div>
        </div>` : ''}
      </div>
      <div class="divider"></div>
      <div style="font-size:11.5px;font-weight:700;letter-spacing:.08em;color:#9A8FB5">YOU BOTH</div>
      <div class="chips-sm">${(card.shared.slice(0, 4).map((t) => `<span class="chip-yellow">${esc(t)}</span>`).join('')) || '<span class="chip-purple">nothing yet</span>'}</div>
      <div style="font-size:11.5px;font-weight:700;letter-spacing:.08em;color:#9A8FB5;margin-top:14px">ALSO INTO</div>
      <div class="chips-sm">${card.other.slice(0, 3).map((t) => `<span class="chip-purple">${esc(t)}</span>`).join('') || '<span class="chip-purple">nothing listed</span>'}</div>
    </div>
    <div class="note-box">
      <span style="width:26px;height:26px;border-radius:9px;background:#B7A4EC;flex:none"></span>
      <span style="font-size:12.5px;line-height:1.4;color:#5A4F76">${esc(card.note)}</span>
    </div>
  `;
}

// ------------------------------------------------------------------ reveal

async function screenReveal(id) {
  const card = await apiGet(`/api/profile/${id}?count=${RUN.count}&seed=${RUN.seed}`);
  mount(`
    <div style="background:#7B63C9;min-height:100%;position:relative;color:#fff">
      <div style="display:flex;justify-content:space-between;padding:14px 26px 0;font-size:13px;font-weight:700;color:#F0EAFF"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
      <div style="position:relative;text-align:center;padding:40px 28px 0">
        <div style="font-size:13px;font-weight:700;letter-spacing:.14em;color:#E0D3FF">SEED ${RUN.seed} &middot; ${card.mode.toUpperCase()}</div>
        <div class="baloo" style="font-weight:800;font-size:44px;line-height:1.05;margin-top:12px">You two<br>lined up.</div>
        <div style="position:relative;height:180px;margin-top:26px;display:flex;align-items:center;justify-content:center">
          <div style="position:absolute;width:200px;height:200px;border-radius:50%;border:3px solid rgba(250,233,168,.5);animation:ring 2.4s ease-out infinite"></div>
          <div style="display:flex;align-items:center">
            <div style="transform:rotate(-7deg)">${duck(104, '#B7A4EC', '#FAE9A8')}</div>
            <div style="transform:rotate(7deg);margin-left:-16px">${duck(104, '#FAE9A8', '#B7A4EC')}</div>
          </div>
        </div>
        <div class="baloo" style="font-weight:800;font-size:30px;margin-top:6px">${esc(card.name)} &middot; ${card.score}</div>
        <div style="font-size:13.5px;color:#E0D3FF;margin-top:4px">Scored from both sides. The lower one stands.</div>
      </div>
      <div style="background:#FFFBF2;border-radius:34px 34px 0 0;padding:24px 24px 26px;margin-top:24px;color:#332A47">
        <div style="display:flex;gap:10px">
          <div style="flex:1;background:#F7F1FF;border-radius:18px;padding:13px 14px">
            <div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:#9A8FB5">STUDY</div>
            <div class="baloo" style="font-weight:700;font-size:15px;margin-top:4px;line-height:1.2">${esc(card.study)}</div>
          </div>
          <div style="flex:1;background:#FDF3D3;border-radius:18px;padding:13px 14px">
            <div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:#A88E50">SHARED</div>
            <div class="baloo" style="font-weight:700;font-size:15px;margin-top:4px;line-height:1.2">${card.shared.slice(0, 3).join(' &middot; ') || 'nothing yet'}</div>
          </div>
        </div>
        <div style="display:flex;gap:10px;margin-top:14px">
          <div class="btn-secondary" id="rv-back">&#10005;</div>
          <button class="btn-primary" id="rv-profile">See ${esc(card.name)}'s profile</button>
        </div>
      </div>
    </div>
  `);
  document.getElementById('rv-back').addEventListener('click', () => { location.hash = '#/feed'; });
  document.getElementById('rv-profile').addEventListener('click', () => { location.hash = `#/profile/${id}`; });
}

// ----------------------------------------------------------------- profile

async function screenProfile(id) {
  const card = await apiGet(`/api/profile/${id}?count=${RUN.count}&seed=${RUN.seed}`);
  mount(`
    <div style="background:#FAE9A8;padding:14px 24px 26px">
      <div style="display:flex;justify-content:space-between;font-size:13px;font-weight:700"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px">
        <div class="btn-secondary" style="width:38px;height:38px;border-radius:13px" id="pr-back">&#8249;</div>
      </div>
      <div style="display:flex;align-items:flex-end;gap:14px;margin-top:16px">
        ${duck(96, '#B7A4EC', '#FAE9A8')}
        <div style="padding-bottom:4px">
          <div class="baloo" style="font-weight:800;font-size:32px;line-height:1.1">${esc(card.name)}</div>
          <div style="font-size:14px;font-weight:500;color:#6B5A2E">${card.age} &middot; ${esc(card.area)} Auckland</div>
        </div>
      </div>
    </div>
    <div class="scroll">
      <div style="display:flex;gap:9px">
        <div style="flex:1;background:#fff;border:2px solid #E6DDFA;border-radius:18px;padding:10px 12px">
          <div style="font-size:11px;font-weight:700;color:#9A8FB5;letter-spacing:.06em">MATCH</div>
          <div class="baloo" style="font-weight:800;font-size:21px">${card.score}</div>
        </div>
        <div style="flex:1;background:#fff;border:2px solid #E6DDFA;border-radius:18px;padding:10px 12px">
          <div style="font-size:11px;font-weight:700;color:#9A8FB5;letter-spacing:.06em">MBTI</div>
          <div class="baloo" style="font-weight:800;font-size:21px">${esc(card.mbti)}</div>
        </div>
        <div style="flex:1;background:#fff;border:2px solid #E6DDFA;border-radius:18px;padding:10px 12px">
          <div style="font-size:11px;font-weight:700;color:#9A8FB5;letter-spacing:.06em">YEAR</div>
          <div class="baloo" style="font-weight:800;font-size:21px">${card.year}</div>
        </div>
      </div>

      <div class="card-box" style="border:2px solid #332A47;box-shadow:0 5px 0 #E0D6F7;margin-top:12px">
        <div style="font-size:11.5px;font-weight:700;letter-spacing:.08em;color:#9A8FB5">STUDY</div>
        <div class="baloo" style="font-weight:700;font-size:19px;margin-top:5px">${esc(card.study)}</div>
        <div style="font-size:13.5px;color:#6B5F86;margin-top:2px">${esc(card.faculty)}</div>
        ${card.department ? `<div style="display:inline-flex;align-items:center;gap:7px;margin-top:10px;background:#F7F1FF;border-radius:12px;padding:7px 12px">
          <span style="width:14px;height:14px;border-radius:4px;background:#7B63C9"></span>
          <span style="font-size:12.5px;font-weight:700;color:#5A4F76">${card.same_department ? 'Same department as you' : esc(card.department)}</span>
        </div>` : ''}
      </div>

      <div style="margin-top:12px;background:#F7F1FF;border-radius:20px;padding:13px">
        <div style="font-size:12px;font-weight:700;color:#7B63C9;letter-spacing:.06em">WHY KIWE PICKED THEM</div>
        <div style="font-size:13.5px;line-height:1.5;color:#4E4468;margin-top:5px">${esc(card.note)}</div>
      </div>

      <div class="label">LANGUAGES</div>
      <div class="chips-sm">
        ${card.languages.map((l) => `<span class="${card.sharedLanguages.includes(l) ? 'chip-yellow' : 'chip-purple'}">${esc(l)}${card.sharedLanguages.includes(l) ? ' &#10003;' : ''}</span>`).join('') || '<span class="chip-purple">none listed</span>'}
      </div>

      <div class="label">INTERESTS &middot; ${card.shared.length} SHARED</div>
      <div class="chips-sm">
        ${card.shared.map((t) => `<span class="chip-yellow">${esc(t)} &#10003;</span>`).join('')}
        ${card.other.map((t) => `<span class="chip-purple">${esc(t)}</span>`).join('')}
      </div>
      <div style="height:80px"></div>
    </div>
    <div class="footer">
      <div class="btn-secondary" id="pr-pass">&#10005;</div>
      <button class="btn-primary" style="background:#FAE9A8;border:3px solid #332A47;color:#332A47" id="pr-like">Like ${esc(card.name)} &#9829;</button>
    </div>
  `);
  document.getElementById('pr-back').addEventListener('click', () => { history.back(); });
  document.getElementById('pr-pass').addEventListener('click', async () => {
    await apiPost(`/api/feed/${id}/pass?count=${RUN.count}&seed=${RUN.seed}`);
    location.hash = '#/feed';
  });
  document.getElementById('pr-like').addEventListener('click', async () => {
    await apiPost(`/api/feed/${id}/like?count=${RUN.count}&seed=${RUN.seed}`);
    location.hash = `#/reveal/${id}`;
  });
}

// ----------------------------------------------------------------- matches

async function screenMatches() {
  const { history: rows } = await apiGet('/api/history');
  const styles = {
    Liked: { bg: '#FAE9A8', fg: '#332A47' },
    Passed: { bg: '#F4F0FC', fg: '#9A8FB5' },
  };
  mount(`
    <div class="statusbar"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
    <div style="padding:18px 24px 0">
      <div class="baloo" style="font-weight:800;font-size:32px">Matches</div>
      <div style="font-size:13px;color:#9A8FB5;margin-top:6px">Everyone you've acted on this session &mdash; ${rows.length} so far.</div>
    </div>
    <div class="scroll">
      ${rows.length === 0 ? `<div class="empty"><div class="baloo">Nothing yet.</div>Like or pass on a match from the feed and it'll show up here.</div>` : rows.map((r) => {
        const s = styles[r.status] || { bg: '#F4F0FC', fg: '#9A8FB5' };
        return `
        <div class="history-row">
          ${duck(56, '#B7A4EC', '#FAE9A8')}
          <div style="flex:1;min-width:0">
            <div style="display:flex;align-items:center;gap:7px">
              <span class="baloo" style="font-weight:700;font-size:18px">${esc(r.name)}</span>
              <span style="font-size:11.5px;font-weight:700;color:#9A8FB5">${r.score}</span>
            </div>
            <div style="font-size:12.5px;color:#6B5F86;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.study)}</div>
            <div style="font-size:11.5px;color:#B4A9CC;margin-top:3px">seed ${r.run_seed}</div>
          </div>
          <span class="status-pill" style="background:${s.bg};color:${s.fg}">${esc(r.status)}</span>
        </div>`;
      }).join('')}
      <div style="height:20px"></div>
    </div>
  `, { nav: 'matches' });
}

// ---------------------------------------------------------------------- you

async function screenYou() {
  me = await apiGet('/api/me');
  const p = me.profile;
  mount(`
    <div style="background:#B7A4EC;padding:14px 24px 24px">
      <div style="display:flex;justify-content:space-between;font-size:13px;font-weight:700"><span>9:41</span><span>&#9646;&#9646; &#9096;</span></div>
      <div style="display:flex;align-items:center;gap:14px;margin-top:22px">
        ${duck(88, '#FAE9A8', '#B7A4EC')}
        <div>
          <div class="baloo" style="font-weight:800;font-size:28px;line-height:1.1">You</div>
          <div style="font-size:13.5px;color:#3C3358;margin-top:2px">${esc(p.major)} &middot; Year ${p.year}</div>
          <div style="display:inline-flex;align-items:center;gap:6px;margin-top:8px;background:#332A47;color:#FAE9A8;border-radius:12px;padding:6px 11px">
            <span style="width:8px;height:8px;border-radius:50%;background:#FAE9A8"></span>
            <span style="font-size:12px;font-weight:700">Looking for ${esc(p.mode)}</span>
          </div>
        </div>
      </div>
    </div>
    <div class="scroll">
      <div class="card-box" style="border:2px solid #E0AC5F;background:#FDF3D3;display:flex;align-items:center;gap:12px">
        <span style="width:32px;height:32px;border-radius:11px;background:#E0AC5F;flex:none"></span>
        <div style="flex:1">
          <div style="font-size:13.5px;font-weight:700">Mode is set for good</div>
          <div style="font-size:12px;color:#7A6440;line-height:1.4;margin-top:2px">Friendship and dating are scored differently, so switching means signing up again.</div>
        </div>
      </div>

      <div class="label">YOUR PROFILE</div>
      <div class="list-plain">
        <div class="settings-row"><span style="font-size:14px;font-weight:600">Study</span><span style="font-size:13px;color:#9A8FB5">${esc(p.major)} &middot; Y${p.year}</span></div>
        <div class="settings-row"><span style="font-size:14px;font-weight:600">Interests</span><span style="font-size:13px;color:#9A8FB5">${p.interests.length} picked</span></div>
        <div class="settings-row"><span style="font-size:14px;font-weight:600">Languages</span><span style="font-size:13px;color:#9A8FB5">${p.languages.join(', ') || 'English only'}</span></div>
        <div class="settings-row"><span style="font-size:14px;font-weight:600">MBTI</span><span style="font-size:13px;color:#9A8FB5">${esc(p.mbti)}</span></div>
        <div class="settings-row"><span style="font-size:14px;font-weight:600">Area</span><span style="font-size:13px;color:#9A8FB5">${esc(p.area)}</span></div>
      </div>

      <div class="label">SETTINGS</div>
      <div class="list-plain">
        <div class="settings-row">
          <div><div style="font-size:14px;font-weight:600">In the next run</div><div style="font-size:12px;color:#9A8FB5;margin-top:2px">Pause to sit one out</div></div>
          <div class="toggle ${!me.settings.paused ? 'on' : ''}" id="y-inrun"><div class="knob"></div></div>
        </div>
        <div class="settings-row">
          <div><div style="font-size:14px;font-weight:600">Show match scores</div><div style="font-size:12px;color:#9A8FB5;margin-top:2px">The number on each card</div></div>
          <div class="toggle ${me.settings.show_scores ? 'on' : ''}" id="y-scores"><div class="knob"></div></div>
        </div>
        <div class="settings-row" id="y-prefs" style="cursor:pointer"><span style="font-size:14px;font-weight:600">Preferences</span><span style="font-size:13px;color:#9A8FB5">Edit &rsaquo;</span></div>
        <div class="settings-row" id="y-edit" style="cursor:pointer"><span style="font-size:14px;font-weight:600">Edit profile</span><span style="font-size:13px;color:#9A8FB5">Edit &rsaquo;</span></div>
      </div>
      <div style="height:20px"></div>
    </div>
  `, { nav: 'you' });

  document.getElementById('y-inrun').addEventListener('click', async () => {
    await apiPatch('/api/settings', { paused: !me.settings.paused });
    router();
  });
  document.getElementById('y-scores').addEventListener('click', async () => {
    await apiPatch('/api/settings', { show_scores: !me.settings.show_scores });
    router();
  });
  document.getElementById('y-prefs').addEventListener('click', () => { location.hash = '#/preferences'; });
  document.getElementById('y-edit').addEventListener('click', () => { location.hash = '#/signup'; });
}

router();
