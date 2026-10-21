/* Ledger dashboard: sort, filter and live search over the rows the server
 * already rendered (recency order), plus a quiet refresh every minute.
 * With JavaScript off the toolbar stays hidden and the list still works.
 * Sort and filter choices are remembered in localStorage.
 */
(function () {
  "use strict";
  var list = document.getElementById("project-list");
  var toolbar = document.getElementById("board-toolbar");
  if (!list || !toolbar) return;
  toolbar.hidden = false;

  var q = document.getElementById("q");
  var empty = document.getElementById("board-empty");
  var stamp = document.getElementById("gen-stamp");
  var LS = "ledger.board.";
  function load(k, f) { try { var v = localStorage.getItem(LS + k); return v === null ? f : v; } catch (e) { return f; } }
  function save(k, v) { try { localStorage.setItem(LS + k, v); } catch (e) { /* private window */ } }

  var SORTS = ["recent", "now", "quiet", "name"], FILTERS = ["all", "active", "quiet"];
  var state = { sort: load("sort", "recent"), filter: load("filter", "all") };
  if (SORTS.indexOf(state.sort) < 0) state.sort = "recent";      // values saved by the old page
  if (FILTERS.indexOf(state.filter) < 0) state.filter = "all";

  function age(r) { return r.dataset.age === "" ? 1e9 : Number(r.dataset.age); }
  function byName(a, b) { return a.dataset.name.localeCompare(b.dataset.name); }
  var sorters = {
    recent: function (a, b) { return age(a) - age(b) || byName(a, b); },
    now: function (a, b) { return Number(b.dataset.now) - Number(a.dataset.now) || age(a) - age(b); },
    quiet: function (a, b) { return age(b) - age(a) || byName(a, b); },
    name: byName,
  };
  function keep(r, text) {
    var a = age(r);
    if (state.filter === "active" && a > 30) return false;
    if (state.filter === "quiet" && a <= 30) return false;
    return !text || r.dataset.search.indexOf(text) !== -1;
  }
  function apply() {
    var rows = Array.prototype.slice.call(list.querySelectorAll(".row"));
    rows.sort(sorters[state.sort]).forEach(function (r) { list.appendChild(r); });
    var text = q ? q.value.trim().toLowerCase() : "";
    var shown = 0;
    rows.forEach(function (r) { var ok = keep(r, text); r.hidden = !ok; if (ok) shown++; });
    empty.hidden = shown > 0;
    ["sort", "filter"].forEach(function (g) {
      toolbar.querySelectorAll("#" + g + " button").forEach(function (b) {
        b.setAttribute("aria-pressed", String(b.dataset.v === state[g]));
      });
    });
  }
  ["sort", "filter"].forEach(function (g) {
    document.getElementById(g).addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      state[g] = b.dataset.v;
      save(g, state[g]);
      apply();
    });
  });
  if (q) q.addEventListener("input", apply);

  function refresh() {
    if (document.visibilityState !== "visible") return;
    fetch("/", { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.getElementById("project-list");
        var sum = doc.querySelector(".summary");
        var st = doc.getElementById("gen-stamp");
        if (fresh) list.innerHTML = fresh.innerHTML;
        if (sum) document.querySelector(".summary").innerHTML = sum.innerHTML;
        if (st && stamp) stamp.textContent = st.textContent;
        apply();
      })
      .catch(function () { /* server restarting; try again next minute */ });
  }
  setInterval(refresh, 60000);
  apply();
})();
