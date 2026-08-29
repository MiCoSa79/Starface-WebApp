function testConn(instId, name, adminRoute) {
        const btn = event.target;
        btn.textContent = "⏳ Prüfe..."; btn.disabled = true;
        fetch((adminRoute ? "/admin/installations/" : "/installation/") + instId + (adminRoute ? "/test-conn" : "/test"))
            .then(r => r.json())
            .then(d => {
                let icon;
                if (d.ok) { icon = "✅"; }
                else if (d.state === 'unreachable') { icon = "❌"; }
                else if (d.state === 'config') { icon = "⚠️"; }
                else { icon = "🟠"; }   // not-installed / no-active-instance
                alert(icon + " " + name + "\n" + (d.message || d.error || "Fehler"));
            })
            .catch(err => {
                alert("❌ " + name + "\nNetzwerkfehler: " + err);
            })
            .finally(() => {
                btn.textContent = "⚡ Test"; btn.disabled = false;
            });
    }

    /* ── Combobox: Dropdown mit Suchfeld (ab 3 Zeichen) ───────── */
    function initComboboxes() {
        document.querySelectorAll('.cb').forEach(cb => {
            const sel = document.getElementById(cb.dataset.cb);
            if (!sel) return;
            const trigger = cb.querySelector('.cb-trigger');
            const valueEl = cb.querySelector('.cb-value');
            const pop = cb.querySelector('.cb-pop');
            const search = cb.querySelector('.cb-search');
            const list = cb.querySelector('.cb-list');
            const opts = Array.from(sel.options);
            const placeholderOpt = opts.find(o => o.value === '');
            // Filter-Combos zeigen ihren „Alle …“-Eintrag als wählbare Option, Formular-Combos nicht
            const items = opts.filter(o => o.value !== '' || !!sel.dataset.filter);
            function render(q) {
                list.innerHTML = '';
                const query = (q || '').trim().toLowerCase();
                const active = query.length >= 3 ? items.filter(o => o.textContent.trim().toLowerCase().includes(query)) : items;
                if (!active.length) {
                    const li = document.createElement('li');
                    li.className = 'empty';
                    li.textContent = 'Keine Treffer';
                    list.appendChild(li);
                    return;
                }
                active.forEach(o => {
                    const li = document.createElement('li');
                    li.textContent = o.textContent;
                    li.dataset.val = o.value;
                    li.addEventListener('click', () => {
                        sel.value = o.value;
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        valueEl.textContent = o.textContent;
                        valueEl.classList.toggle('placeholder', o.value === '');
                        close();
                    });
                    list.appendChild(li);
                });
            }
            function open() {
                pop.hidden = false;
                cb.classList.add('open');
                trigger.setAttribute('aria-expanded', 'true');
                render('');
                search.focus();
            }
            function close() {
                pop.hidden = true;
                cb.classList.remove('open');
                trigger.setAttribute('aria-expanded', 'false');
            }
            trigger.addEventListener('click', e => { e.stopPropagation(); pop.hidden ? open() : close(); });
            document.addEventListener('click', e => { if (!cb.contains(e.target)) close(); });
            search.addEventListener('input', () => render(search.value));
            search.addEventListener('keydown', e => {
                if (e.key === 'Enter') { const first = list.querySelector('li[data-val]'); if (first) first.click(); }
                else if (e.key === 'Escape') close();
            });
            // Initial: Platzhalter (kein Vorauswahlwert) oder aktuellen Wert anzeigen
            const cur = sel.options[sel.selectedIndex];
            if (cur && cur.value !== '') { valueEl.textContent = cur.textContent; }
            else if (placeholderOpt) { valueEl.textContent = placeholderOpt.textContent; valueEl.classList.add('placeholder'); }
        });
    }

    /* ── Tabellen: Filter (ab 3 Zeichen, Dropdowns aus Spaltenwerten) + Einklappen ── */
    function initTableFilters() {
        document.querySelectorAll('.tbl-wrap').forEach(wrap => {
            const first = wrap.querySelector('.tbl-filters input, .tbl-filters select');
            if (!first) return;
            const table = document.getElementById(first.dataset.filter);
            if (!table) return;
            const rows = Array.from(table.rows).slice(1);
            const countEl = document.querySelector('[data-count="' + wrap.dataset.wrap + '"]');
            const controls = Array.from(wrap.querySelectorAll('.tbl-filters input, .tbl-filters select'));
            controls.forEach(ctl => {
                if (ctl.tagName !== 'SELECT') return;
                const col = parseInt(ctl.dataset.col, 10);
                const vals = new Set();
                rows.forEach(r => {
                    if (r.cells[col]) { const v = r.cells[col].textContent.trim(); if (v) vals.add(v); }
                });
                [...vals].sort((a, b) => a.localeCompare(b, 'de', { numeric: true })).forEach(v => {
                    const o = document.createElement('option');
                    o.value = v; o.textContent = v; ctl.appendChild(o);
                });
            });
            if (!rows.length) {
                wrap.querySelector('.tbl-filters').style.display = 'none';
                if (countEl) countEl.textContent = '0 von 0';
                return;
            }
            function matches(r) {
                return controls.every(ctl => {
                    const col = parseInt(ctl.dataset.col, 10);
                    if (isNaN(col) || !r.cells[col]) return true;
                    const q = ctl.value.trim().toLowerCase();
                    if (!q) return true;
                    if (ctl.dataset.minlen && q.length < parseInt(ctl.dataset.minlen, 10)) return true;
                    const cell = r.cells[col].textContent.trim().toLowerCase();
                    return ctl.tagName === 'SELECT' ? cell === q : cell.includes(q);
                });
            }
            function apply() {
                let vis = 0;
                rows.forEach(r => {
                    const show = matches(r);
                    r.style.display = show ? '' : 'none';
                    if (show) vis++;
                });
                if (countEl) countEl.textContent = vis + ' von ' + rows.length;
            }
            controls.forEach(ctl => {
                if (ctl.tagName === 'SELECT') { ctl.addEventListener('change', apply); return; }
                let t;
                ctl.addEventListener('input', () => { clearTimeout(t); t = setTimeout(apply, 200); });
            });
            apply();
        });
    }
    function initCollapse() {
        document.querySelectorAll('.collapse-btn').forEach(btn => {
            const wrap = document.querySelector('.tbl-wrap[data-wrap="' + btn.dataset.collapse + '"]');
            if (!wrap) return;
            const key = 'sf.admin.collapse.' + btn.dataset.collapse;
            // F66/v1.0.59: Standard = AUFGEKLAPPT (war früher eingeklappt, als alles
            // auf einer Seite war). Nur explizites Zuklappen (='0') hält den Zustand.
            let collapsed = false;
            try { collapsed = localStorage.getItem(key) === '0'; } catch (e) {}
            if (collapsed) wrap.classList.add('collapsed');
            btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            btn.addEventListener('click', () => {
                wrap.classList.toggle('collapsed');
                const open = !wrap.classList.contains('collapsed');
                btn.setAttribute('aria-expanded', open ? 'true' : 'false');
                try { localStorage.setItem(key, open ? '1' : '0'); } catch (e) {}
            });
        });
    }
    // F86 (v1.0.83): Navigations-Dropdowns (Administration / Benutzerkonto /
    // Modul-Updates) schließen bei Klick außerhalb — native <details> togglen
    // sonst nur über das Summary selbst.
    function initNavDrops() {
        document.addEventListener('click', function (e) {
            document.querySelectorAll('details.drop[open], details.user-drop[open], details.sub[open]')
                .forEach(function (d) {
                    if (!d.contains(e.target)) { d.open = false; }
                });
        });
    }
    initCollapse();
    initTableFilters();
    initComboboxes();
    initNavDrops();
