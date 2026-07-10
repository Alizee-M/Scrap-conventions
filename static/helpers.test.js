// Run with `node --test` (Node 18+ built-in test runner, no dependencies).
//
// helpers.js is a plain classic <script> (not a module): it reads
// currentSort/userLat/userLon/distanceMax/dateFrom/dateTo as free variables
// that, in the browser, come from templates/index.html's own inline script
// sharing the same top-level scope. To test it in isolation without
// duplicating that scope-sharing trick, we run the file's source in a `vm`
// context pre-seeded with those variables as plain global properties.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const SOURCE = fs.readFileSync(path.join(__dirname, 'helpers.js'), 'utf8');

function loadHelpers(state = {}) {
  const context = {
    currentSort: 'date',
    userLat: null,
    userLon: null,
    distanceMax: null,
    dateFrom: null,
    dateTo: null,
    console,
    ...state,
  };
  vm.createContext(context);
  vm.runInContext(SOURCE, context, { filename: 'helpers.js' });
  return context;
}

// ─── escapeHtml ──────────────────────────────────────────────────────────────

test('escapeHtml escapes all 5 XSS-relevant characters', () => {
  const h = loadHelpers();
  assert.equal(h.escapeHtml(`<script>alert("x")</script>&'`), '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;&#39;');
});

test('escapeHtml treats null/undefined as an empty string', () => {
  const h = loadHelpers();
  assert.equal(h.escapeHtml(null), '');
  assert.equal(h.escapeHtml(undefined), '');
});

// ─── safeUrl ─────────────────────────────────────────────────────────────────

test('safeUrl allows http(s) URLs and rejects everything else', () => {
  const h = loadHelpers();
  assert.equal(h.safeUrl('https://example.com/x'), 'https://example.com/x');
  assert.equal(h.safeUrl('http://example.com/x'), 'http://example.com/x');
  assert.equal(h.safeUrl('javascript:alert(1)'), '');
  assert.equal(h.safeUrl(''), '');
  assert.equal(h.safeUrl(undefined), '');
});

// ─── fmtDate ─────────────────────────────────────────────────────────────────

test('fmtDate returns "?" for a falsy date', () => {
  const h = loadHelpers();
  assert.equal(h.fmtDate(null), '?');
  assert.equal(h.fmtDate(''), '?');
});

test('fmtDate formats an ISO date in French, noon-anchored to dodge DST/timezone rollover', () => {
  const h = loadHelpers();
  assert.equal(h.fmtDate('2026-07-03'), new Date('2026-07-03T12:00:00').toLocaleDateString('fr-FR', {
    day: 'numeric', month: 'short', year: 'numeric',
  }));
});

// ─── fmtDist ─────────────────────────────────────────────────────────────────

test('fmtDist returns null for a missing distance', () => {
  const h = loadHelpers();
  assert.equal(h.fmtDist(null), null);
  assert.equal(h.fmtDist(undefined), null);
});

test('fmtDist shows "< 1 km" under 1km and rounds above it', () => {
  const h = loadHelpers();
  assert.equal(h.fmtDist(0.4), '< 1 km');
  assert.equal(h.fmtDist(42.6), '43 km');
});

// ─── mappyLink ───────────────────────────────────────────────────────────────

test('mappyLink returns null without a destination', () => {
  const h = loadHelpers();
  assert.equal(h.mappyLink(''), null);
  assert.equal(h.mappyLink(null), null);
});

test('mappyLink links straight to the destination when the user has no known position', () => {
  const h = loadHelpers({ userLat: null, userLon: null });
  assert.equal(h.mappyLink('Tours'), 'https://fr.mappy.com/itineraire#/vers/Tours/');
});

test('mappyLink includes an origin/destination route once the user position is known', () => {
  const h = loadHelpers({ userLat: 47.39, userLon: 0.68 });
  assert.equal(
    h.mappyLink('Tours'),
    `https://fr.mappy.com/itineraire#/recherche/${encodeURIComponent('47.39,0.68')}/Tours/`,
  );
});

// ─── sortedData ──────────────────────────────────────────────────────────────

function _conv(name, date, distance_km) {
  return { name, date, distance_km };
}

test('sortedData sorts by date by default, undated events last', () => {
  const h = loadHelpers({ currentSort: 'date' });
  const data = [_conv('Late', '2026-09-01'), _conv('Early', '2026-08-01'), _conv('Undated', null)];

  const result = Array.from(h.sortedData(data), c => c.name);

  assert.deepEqual(result, ['Early', 'Late', 'Undated']);
});

test('sortedData does not mutate the input array', () => {
  const h = loadHelpers({ currentSort: 'date' });
  const data = [_conv('B', '2026-09-01'), _conv('A', '2026-08-01')];

  h.sortedData(data);

  assert.deepEqual(data.map(c => c.name), ['B', 'A']);
});

test('sortedData sorts by distance when requested and a user position is known', () => {
  const h = loadHelpers({ currentSort: 'distance', userLat: 47.39, userLon: 0.68 });
  const data = [_conv('Far', '2026-08-01', 400), _conv('Near', '2026-08-01', 10), _conv('NoDist', '2026-08-01', null)];

  const result = Array.from(h.sortedData(data), c => c.name);

  assert.deepEqual(result, ['Near', 'Far', 'NoDist']);
});

test('sortedData falls back to date sort for "distance" when no user position is known', () => {
  const h = loadHelpers({ currentSort: 'distance', userLat: null });
  const data = [_conv('Late', '2026-09-01'), _conv('Early', '2026-08-01')];

  const result = Array.from(h.sortedData(data), c => c.name);

  assert.deepEqual(result, ['Early', 'Late']);
});

// ─── filterData ──────────────────────────────────────────────────────────────

test('filterData with no active filters keeps everything', () => {
  const h = loadHelpers();
  const data = [_conv('A', '2026-08-01', 10), _conv('B', null, null)];

  assert.equal(h.filterData(data).length, 2);
});

test('filterData drops events beyond distanceMax, including those with no distance at all', () => {
  const h = loadHelpers({ distanceMax: 50 });
  const data = [_conv('Near', '2026-08-01', 10), _conv('Far', '2026-08-01', 200), _conv('Unknown', '2026-08-01', null)];

  const result = h.filterData(data);

  assert.deepEqual(result.map(c => c.name), ['Near']);
});

test('filterData drops events outside the [dateFrom, dateTo] window, including undated ones', () => {
  const h = loadHelpers({ dateFrom: '2026-08-01', dateTo: '2026-08-31' });
  const data = [
    _conv('Before', '2026-07-15'),
    _conv('InWindow', '2026-08-15'),
    _conv('After', '2026-09-15'),
    _conv('Undated', null),
  ];

  const result = h.filterData(data);

  assert.deepEqual(result.map(c => c.name), ['InWindow']);
});
