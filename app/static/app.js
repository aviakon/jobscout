// Copy-to-clipboard buttons (e.g. cover letter).
document.addEventListener("click", async (e) => {
  const copyBtn = e.target.closest("button[data-copy-target]");
  if (!copyBtn) return;
  const el = document.getElementById(copyBtn.dataset.copyTarget);
  if (!el) return;
  try {
    await navigator.clipboard.writeText(el.innerText);
    const original = copyBtn.textContent;
    copyBtn.textContent = "✓ הועתק";
    setTimeout(() => (copyBtn.textContent = original), 1500);
  } catch {
    alert("לא ניתן להעתיק אוטומטית. סמן והעתק ידנית.");
  }
});

// Match status buttons: update via POST, reflect state without a full reload.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-match]");
  if (!btn) return;
  const matchId = btn.dataset.match;
  const status = btn.dataset.status;
  const candidateId = document.getElementById("skill-chips")?.dataset.candidate;
  const body = new URLSearchParams({ status });
  try {
    const res = await fetch(`/candidate/${candidateId}/match/${matchId}/status`, { method: "POST", body });
    if (!res.ok) throw new Error(await res.text());
    const article = btn.closest(".match");
    article.dataset.status = status;
    const label = article.querySelector(".status-label");
    if (label) label.textContent = status;
    if (status === "hidden") {
      article.style.transition = "opacity .3s";
      article.style.opacity = "0";
      setTimeout(() => { article.remove(); applyFilters(); }, 300);
    }
  } catch (err) {
    alert("Failed to update: " + err.message);
  }
});

// --- Filter + sort the matches list (client-side) ---------------------------
const toolbar = document.getElementById("matches-toolbar");
const list = document.getElementById("matches-list");

function readControls() {
  if (!toolbar) return {};
  const get = (name) => toolbar.querySelector(`[data-control="${name}"]`);
  return {
    sort: get("sort")?.value || "score",
    source: get("source")?.value || "",
    minscore: parseInt(get("minscore")?.value || "0", 10),
    newonly: get("newonly")?.checked || false,
  };
}

function applyFilters() {
  if (!list) return;
  const c = readControls();
  const cards = Array.from(list.querySelectorAll(".match"));

  // sort
  cards.sort((a, b) => {
    if (c.sort === "company") return a.dataset.company.localeCompare(b.dataset.company, "he");
    if (c.sort === "new") return (b.dataset.new | 0) - (a.dataset.new | 0)
      || (b.dataset.score | 0) - (a.dataset.score | 0);
    return (b.dataset.score | 0) - (a.dataset.score | 0); // score
  });
  cards.forEach((card) => list.appendChild(card));

  // filter
  let visible = 0;
  cards.forEach((card) => {
    const ok =
      (c.source === "" || card.dataset.source === c.source) &&
      (parseInt(card.dataset.score, 10) >= c.minscore) &&
      (!c.newonly || card.dataset.new === "1");
    card.style.display = ok ? "" : "none";
    if (ok) visible++;
  });

  const val = toolbar.querySelector(".minscore-val");
  if (val) val.textContent = c.minscore;
  const count = document.getElementById("visible-count");
  if (count) count.textContent = `מציג ${visible} מתוך ${cards.length}`;
}

if (toolbar) {
  toolbar.addEventListener("input", applyFilters);
  toolbar.addEventListener("change", applyFilters);
  applyFilters();
}

// --- Per-skill experience gauge ---------------------------------------------
(function () {
  const chips = document.getElementById("skill-chips");
  const modal = document.getElementById("gauge-modal");
  if (!chips || !modal) return;

  const candidateId = chips.dataset.candidate;
  const arc = document.getElementById("gauge-arc");
  const range = document.getElementById("gauge-range");
  const num = document.getElementById("gauge-num");
  const unit = document.getElementById("gauge-unit");
  const title = document.getElementById("gauge-skill");
  const saved = document.getElementById("gauge-saved");
  const MAX = parseInt(range.max, 10);
  const R = 52;
  const CIRC = 2 * Math.PI * R;
  arc.style.strokeDasharray = CIRC;

  let currentChip = null;
  let saveTimer = null;

  function render(years) {
    const frac = Math.min(years, MAX) / MAX;
    arc.style.strokeDashoffset = CIRC * (1 - frac);
    num.textContent = years >= MAX ? MAX + "+" : years;
    unit.textContent = years === 1 ? "שנה" : "שנים";
  }

  function openFor(chip) {
    currentChip = chip;
    const years = parseInt(chip.dataset.years || "0", 10);
    title.textContent = chip.dataset.skill;
    range.value = years;
    saved.textContent = "";
    render(years);
    modal.hidden = false;
  }

  function close() {
    modal.hidden = true;
    currentChip = null;
  }

  async function save(years) {
    if (!currentChip) return;
    const body = new URLSearchParams({ skill: currentChip.dataset.skill, years });
    try {
      const res = await fetch(`/candidate/${candidateId}/skill-experience`, { method: "POST", body });
      if (!res.ok) throw new Error(await res.text());
      currentChip.dataset.years = years;
      currentChip.classList.toggle("has-exp", years > 0);
      const badge = currentChip.querySelector(".chip-years");
      if (badge) badge.textContent = years > 0 ? years + "y" : "+";
      saved.textContent = "✓ נשמר";
      setTimeout(() => (saved.textContent = ""), 1500);
    } catch (err) {
      saved.textContent = "שגיאה בשמירה";
    }
  }

  function onChange(years) {
    render(years);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save(years), 350);
  }

  chips.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip) openFor(chip);
  });
  range.addEventListener("input", () => onChange(parseInt(range.value, 10)));
  modal.querySelectorAll(".gauge-step").forEach((b) =>
    b.addEventListener("click", () => {
      let v = parseInt(range.value, 10) + parseInt(b.dataset.step, 10);
      v = Math.max(0, Math.min(MAX, v));
      range.value = v;
      onChange(v);
    })
  );
  modal.querySelector(".gauge-close").addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) close(); });

  const removeBtn = document.getElementById("gauge-remove");
  if (removeBtn) {
    removeBtn.addEventListener("click", async () => {
      if (!currentChip) return;
      const body = new URLSearchParams({ skill: currentChip.dataset.skill });
      try {
        const res = await fetch(`/candidate/${candidateId}/skills/remove`, { method: "POST", body });
        if (!res.ok) throw new Error();
        currentChip.remove();
        close();
      } catch {
        saved.textContent = "שגיאה בהסרה";
      }
    });
  }
})();

// --- Add a skill via search (autocomplete over the skill vocabulary) ---------
(function () {
  const chips = document.getElementById("skill-chips");
  const wrap = document.getElementById("add-skill");
  const input = document.getElementById("skill-search");
  const list = document.getElementById("skill-suggest");
  if (!chips || !wrap || !input) return;

  const candidateId = chips.dataset.candidate;
  let ALL = [];
  try {
    ALL = JSON.parse(document.getElementById("all-skills-data").textContent);
  } catch {}

  const present = () =>
    new Set(Array.from(chips.querySelectorAll(".chip")).map((c) => c.dataset.skill.toLowerCase()));

  function render(q) {
    q = q.trim();
    list.innerHTML = "";
    if (!q) { list.hidden = true; return; }
    const have = present();
    const ql = q.toLowerCase();
    const matches = ALL.filter((s) => s.toLowerCase().includes(ql) && !have.has(s.toLowerCase())).slice(0, 8);
    const items = matches.map((s) => ({ label: s, value: s }));
    const exact = ALL.some((s) => s.toLowerCase() === ql) || have.has(ql);
    if (!exact && q.length >= 2) items.push({ label: `הוסף "${q}"`, value: q, custom: true });
    if (!items.length) { list.hidden = true; return; }
    for (const it of items) {
      const li = document.createElement("li");
      li.textContent = it.label;
      li.dataset.value = it.value;
      if (it.custom) li.className = "custom";
      list.appendChild(li);
    }
    list.hidden = false;
  }

  function createChip(skill) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip chip-added";
    btn.dataset.skill = skill;
    btn.dataset.years = "0";
    const name = document.createElement("span");
    name.className = "chip-name";
    name.textContent = skill;
    const yrs = document.createElement("span");
    yrs.className = "chip-years";
    yrs.textContent = "+";
    btn.append(name, yrs);
    chips.insertBefore(btn, wrap);
    btn.classList.add("pop");
  }

  async function addSkill(skill) {
    skill = (skill || "").trim();
    if (!skill) return;
    try {
      const res = await fetch(`/candidate/${candidateId}/skills/add`, {
        method: "POST",
        body: new URLSearchParams({ skill }),
      });
      const j = await res.json();
      if (j.added) createChip(j.skill);
    } catch {}
    input.value = "";
    render("");
    input.focus();
  }

  input.addEventListener("input", () => render(input.value));
  input.addEventListener("focus", () => render(input.value));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const first = list.querySelector("li");
      if (first) addSkill(first.dataset.value);
      else if (input.value.trim()) addSkill(input.value);
    } else if (e.key === "Escape") {
      list.hidden = true;
    }
  });
  list.addEventListener("click", (e) => {
    const li = e.target.closest("li");
    if (li) addSkill(li.dataset.value);
  });
  document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) list.hidden = true; });
})();

// --- Rotating hero headline (landing) ---------------------------------------
(function () {
  const rotator = document.getElementById("rotator");
  if (!rotator) return;
  const lines = Array.from(rotator.querySelectorAll(".hero-line"));
  if (lines.length < 2) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let i = 0;
  setInterval(() => {
    lines[i].classList.remove("on");
    i = (i + 1) % lines.length;
    lines[i].classList.add("on");
  }, 3200);
})();

// --- Onboarding wizard ------------------------------------------------------
(function () {
  const form = document.getElementById("onboard-form");
  if (!form) return;

  // resume method tabs
  const methodInput = document.getElementById("resume_method");
  const tabs = form.querySelectorAll(".method-tab");
  const panels = form.querySelectorAll(".method-panel");
  tabs.forEach((tab) =>
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.toggle("active", t === tab));
      const m = tab.dataset.method;
      panels.forEach((p) => p.classList.toggle("active", p.dataset.panel === m));
      if (methodInput) methodInput.value = m;
    })
  );

  // dropzone helpers
  function wireDrop(zoneId, inputId, labelId) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    const label = document.getElementById(labelId);
    if (!zone || !input) return;
    const show = () => {
      if (input.files && input.files.length) {
        label.textContent = "✓ " + input.files[0].name;
        label.hidden = false;
      }
    };
    zone.addEventListener("click", () => input.click());
    input.addEventListener("change", show);
    ["dragover", "dragenter"].forEach((ev) =>
      zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("drag"); })
    );
    ["dragleave", "drop"].forEach((ev) =>
      zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("drag"); })
    );
    zone.addEventListener("drop", (e) => {
      if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); }
    });
  }
  wireDrop("dropzone", "file-input", "dz-file");
  wireDrop("photo-drop", "photo-input", "photo-file");

  // wizard steps
  const steps = form.querySelectorAll(".wizard-step");
  const dots = document.querySelectorAll(".step-dot");
  function goStep(n) {
    steps.forEach((s) => s.classList.toggle("active", s.dataset.step === String(n)));
    dots.forEach((d) => {
      const dn = Number(d.dataset.dot);
      d.classList.toggle("active", dn === n);
      d.classList.toggle("done", dn < n);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  // "continue without a resume" — search on the stated roles alone
  const noResumeNote = document.getElementById("noresume-note");
  function setNoResume(on) {
    if (methodInput) methodInput.value = on ? "none" : activeMethod();
    if (noResumeNote) noResumeNote.hidden = !on;
  }
  function activeMethod() {
    const tab = form.querySelector(".method-tab.active");
    return tab ? tab.dataset.method : "file";
  }

  const to2 = document.getElementById("to-step2");
  const to1 = document.getElementById("to-step1");
  const skip = document.getElementById("skip-resume");
  if (to2) to2.addEventListener("click", () => {
    setNoResume(false);
    if (validateResume()) goStep(2);
  });
  if (to1) to1.addEventListener("click", () => { setNoResume(false); goStep(1); });
  if (skip) skip.addEventListener("click", () => {
    document.getElementById("step1-err").textContent = "";
    setNoResume(true);
    goStep(2);
    const ri = document.getElementById("role-input");
    if (ri) setTimeout(() => ri.focus(), 350);
  });

  function validateResume() {
    const err = document.getElementById("step1-err");
    const m = methodInput ? methodInput.value : "file";
    let ok = false;
    if (m === "text") ok = document.getElementById("resume_text").value.trim().length > 20;
    else if (m === "link") ok = document.getElementById("resume_url").value.trim().length > 4;
    else if (m === "photo") ok = document.getElementById("photo-input").files.length > 0;
    else ok = document.getElementById("file-input").files.length > 0;
    if (err) err.textContent = ok ? "" : "בחרו קובץ, הדביקו טקסט, תמונה או קישור כדי להמשיך.";
    return ok;
  }

  // segmented + region chip groups -> hidden input
  form.querySelectorAll("[data-hidden]").forEach((group) => {
    const hidden = group.parentElement.querySelector(`input[name="${group.dataset.hidden}"]`);
    group.querySelectorAll("button").forEach((btn) =>
      btn.addEventListener("click", () => {
        group.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
        if (hidden) hidden.value = btn.dataset.val;
      })
    );
  });

  // work regions — multi-select ("כל הארץ" is exclusive)
  const regionGroup = document.getElementById("region-group");
  const regionsHidden = document.getElementById("regions-hidden");
  if (regionGroup && regionsHidden) {
    const btns = Array.from(regionGroup.querySelectorAll("button"));
    const syncRegions = () => {
      const on = btns.filter((b) => b.classList.contains("on") && b.dataset.val !== "all");
      regionsHidden.value = on.map((b) => b.dataset.val).join(",");
    };
    btns.forEach((btn) =>
      btn.addEventListener("click", () => {
        const val = btn.dataset.val;
        if (val === "all") {
          btns.forEach((b) => b.classList.toggle("on", b === btn));
        } else {
          btn.classList.toggle("on");
          const allBtn = btns.find((b) => b.dataset.val === "all");
          if (allBtn) allBtn.classList.remove("on");
          if (!btns.some((b) => b.classList.contains("on") && b.dataset.val !== "all") && allBtn)
            allBtn.classList.add("on"); // nothing left selected -> back to "all"
        }
        syncRegions();
      })
    );
    syncRegions();
  }

  // roles chips
  const rolesBox = document.getElementById("roles-box");
  const roleInput = document.getElementById("role-input");
  const rolesHidden = document.getElementById("roles-hidden");
  let roles = (rolesHidden && rolesHidden.value ? rolesHidden.value.split(",") : []).filter(Boolean);
  function renderRoles() {
    rolesBox.querySelectorAll(".role-chip").forEach((c) => c.remove());
    roles.forEach((r) => {
      const chip = document.createElement("span");
      chip.className = "role-chip";
      const t = document.createElement("span");
      t.textContent = r;
      const x = document.createElement("button");
      x.type = "button";
      x.textContent = "✕";
      x.addEventListener("click", () => { roles = roles.filter((v) => v !== r); sync(); });
      chip.append(t, x);
      rolesBox.insertBefore(chip, roleInput);
    });
  }
  function sync() { if (rolesHidden) rolesHidden.value = roles.join(","); renderRoles(); }
  function commitPendingRole() {
    if (!roleInput) return;
    const v = roleInput.value.trim();
    if (v && !roles.includes(v) && roles.length < 6) roles.push(v);
    roleInput.value = "";
    sync();
  }
  if (roleInput) {
    roleInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        commitPendingRole();
      }
    });
    // a role typed but never confirmed with Enter would otherwise be dropped
    roleInput.addEventListener("blur", commitPendingRole);
    sync();
  }

  form.addEventListener("submit", (e) => {
    commitPendingRole();
    if (methodInput && methodInput.value === "none" && roles.length === 0) {
      e.preventDefault();
      e.stopPropagation();  // keep the loading overlay from showing
      const err = document.getElementById("roles-err");
      if (err) err.textContent = "בלי קורות חיים צריך לפחות תפקיד אחד כדי לדעת מה לחפש.";
      if (roleInput) roleInput.focus();
    }
  });
})();

// --- Loading overlay for long-running form submits --------------------------
document.addEventListener("submit", (e) => {
  const form = e.target.closest("form[data-loading]");
  if (!form) return;
  const overlay = document.createElement("div");
  overlay.className = "loading-overlay";
  overlay.innerHTML = `<div class="loading-box">
      <div class="spinner"></div>
      <p>${form.dataset.loading}</p>
      <p class="loading-sub">זה יכול לקחת עד דקה. לא לסגור את החלון.</p>
    </div>`;
  document.body.appendChild(overlay);
});

// --- Sponsored ad clicks ----------------------------------------------------
// Fire-and-forget beacon so the advertiser's link is never delayed by us, and a
// blocked or failed beacon still lets the click through.
document.addEventListener("click", (e) => {
  const link = e.target.closest("a[data-ad]");
  if (!link) return;
  const url = `/ad/${encodeURIComponent(link.dataset.ad)}/click`;
  try {
    if (navigator.sendBeacon) navigator.sendBeacon(url);
    else fetch(url, { method: "POST", keepalive: true });
  } catch (_) { /* never block the click */ }
});
