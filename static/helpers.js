// Pure(ish) rendering/formatting helpers, split out of the inline script in
// templates/index.html so they can be unit-tested with `node --test`
// (see helpers.test.js). Loaded as a plain classic <script> — not a module —
// so `currentSort`/`userLat`/etc. below resolve to the `let` declarations in
// index.html's own inline script: both share the page's top-level scope.

// Event name/location/image/url all come from 3rd-party scraped sites, not
// from this app — never trust them raw in innerHTML (stored XSS otherwise).
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function safeUrl(u) {
  return /^https?:\/\//i.test(u || '') ? u : '';
}

function fmtDate(iso) {
  if (!iso) return '?';
  return new Date(iso + 'T12:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
}

function fmtDist(km) {
  if (km === null || km === undefined) return null;
  return km < 1 ? '< 1 km' : `${Math.round(km)} km`;
}

// Deep link into Mappy's itinerary planner (km voiture réels, temps de trajet,
// coût carburant/péages) — Mappy n'a pas d'API self-service gratuite, donc on
// laisse Mappy calculer ça lui-même plutôt que de le refaire nous-mêmes.
// Format documenté par le support Mappy : fr.mappy.com/itineraire#/recherche/DEPART/DESTINATION/
function mappyLink(destination) {
  if (!destination) return null;
  const dest = encodeURIComponent(destination);
  if (userLat === null) return `https://fr.mappy.com/itineraire#/vers/${dest}/`;
  const origin = encodeURIComponent(`${userLat},${userLon}`);
  return `https://fr.mappy.com/itineraire#/recherche/${origin}/${dest}/`;
}

function sortedData(data) {
  const copy = [...data];
  if (currentSort === 'distance' && userLat !== null) {
    copy.sort((a, b) => (a.distance_km ?? 99999) - (b.distance_km ?? 99999));
  } else {
    copy.sort((a, b) => (a.date || '9999').localeCompare(b.date || '9999'));
  }
  return copy;
}

function filterData(data) {
  return data.filter(c => {
    if (distanceMax !== null) {
      if (c.distance_km === null || c.distance_km === undefined || c.distance_km > distanceMax) return false;
    }
    if (dateFrom && (!c.date || c.date < dateFrom)) return false;
    if (dateTo && (!c.date || c.date > dateTo)) return false;
    return true;
  });
}
