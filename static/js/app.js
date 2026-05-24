/* ──────────────────────────────────────────────────────────────────────────
   Primitive Camping Finder — Frontend Logic
   ────────────────────────────────────────────────────────────────────────── */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let map, markerCluster, userMarker, radiusCircle;
let allCampsites = [];
let activeCard = null;
let activeMarker = null;
const markerMap = new Map(); // campsite id → leaflet marker

// ─── Leaflet Map Init ─────────────────────────────────────────────────────────
function initMap() {
  map = L.map('map', {
    center: [39.5, -98.35],
    zoom: 4,
    zoomControl: true,
  });

  // Dark-friendly tile layer (CartoDB Dark Matter)
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
  }).addTo(map);

  markerCluster = L.markerClusterGroup({
    maxClusterRadius: 60,
    iconCreateFunction: clusterIcon,
  });
  map.addLayer(markerCluster);
}

function clusterIcon(cluster) {
  const count = cluster.getChildCount();
  return L.divIcon({
    html: `<div class="cluster-inner">${count}</div>`,
    className: 'cluster-icon',
    iconSize: [40, 40],
  });
}

// Inject cluster CSS dynamically (avoids extra stylesheet)
const clusterStyle = document.createElement('style');
clusterStyle.textContent = `
  .cluster-icon { background: transparent; }
  .cluster-inner {
    width: 40px; height: 40px;
    background: #2d4a1e;
    border: 2px solid #5cb85c;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    color: #8fd48f; font-weight: 700; font-size: 0.85rem;
  }
`;
document.head.appendChild(clusterStyle);

// ─── Campsite Marker Icon ─────────────────────────────────────────────────────
function campIcon(score, active = false) {
  const maxScore = 14;
  const pct = Math.min(score / maxScore, 1);
  const hue = Math.round(pct * 60 + 100); // 100 (yellow-green) → 160 (green)
  const border = active ? '#fff' : `hsl(${hue}, 60%, 55%)`;
  const bg = active ? '#3d8b3d' : `hsl(${hue}, 40%, 18%)`;
  return L.divIcon({
    html: `<div style="width:18px;height:18px;border-radius:50%;border:2.5px solid ${border};background:${bg};box-shadow:0 1px 6px rgba(0,0,0,0.6)"></div>`,
    className: '',
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -12],
  });
}

// ─── Toast ────────────────────────────────────────────────────────────────────
let toastTimer;
function showToast(msg, type = '') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast${type ? ' ' + type : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
}

// ─── Search Flow ──────────────────────────────────────────────────────────────
async function searchByText() {
  const q = document.getElementById('locationInput').value.trim();
  if (!q) { showToast('Enter a location to search', 'error'); return; }

  setLoading(true, 'Geocoding…');
  try {
    const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    if (!res.ok) { showToast(data.error || 'Location not found', 'error'); return; }
    await searchNear(data.lat, data.lon, data.display_name);
  } catch (e) {
    showToast('Network error — please try again', 'error');
  } finally {
    setLoading(false);
  }
}

function searchByGPS() {
  if (!navigator.geolocation) {
    showToast('Geolocation not supported by your browser', 'error');
    return;
  }
  setLoading(true, 'Getting your location…');
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      try {
        await searchNear(pos.coords.latitude, pos.coords.longitude, 'Your Location');
      } finally {
        setLoading(false);
      }
    },
    (err) => {
      setLoading(false);
      showToast('Could not get GPS location: ' + err.message, 'error');
    },
    { timeout: 10000 }
  );
}

async function searchNear(lat, lon, label) {
  const radius = document.getElementById('radiusSelect').value;

  // Place user marker
  if (userMarker) userMarker.remove();
  if (radiusCircle) radiusCircle.remove();

  userMarker = L.circleMarker([lat, lon], {
    radius: 8, color: '#fff', fillColor: '#5cb85c',
    fillOpacity: 1, weight: 2,
  }).addTo(map).bindPopup(`<strong>📍 ${label}</strong>`);

  radiusCircle = L.circle([lat, lon], {
    radius: radius * 1609.34,
    color: '#5cb85c', fillColor: '#5cb85c',
    fillOpacity: 0.05, weight: 1, dashArray: '6',
  }).addTo(map);

  map.fitBounds(radiusCircle.getBounds(), { padding: [20, 20] });

  setLoading(true, 'Finding primitive campsites…');
  try {
    const res = await fetch(`/api/campsites?lat=${lat}&lon=${lon}&radius=${radius}`);
    const data = await res.json();
    if (!res.ok) { showToast(data.error || 'Campsite search failed', 'error'); return; }
    allCampsites = data.campsites;
    renderResults(allCampsites, data.total_found);
    if (data.demo) {
      showToast('🧪 Demo mode — showing sample data. Deploy with live APIs for real results.');
    } else {
      showToast(`Found ${data.total_found} campsites, showing top ${data.campsites.length}`);
    }
  } catch (e) {
    showToast('Failed to fetch campsites', 'error');
  } finally {
    setLoading(false);
  }
}

// ─── Render Results ───────────────────────────────────────────────────────────
function renderResults(sites, total) {
  const list = document.getElementById('campList');
  const countBadge = document.getElementById('resultCount');
  const filterBar = document.getElementById('filterBar');

  countBadge.textContent = sites.length;
  filterBar.classList.toggle('hidden', sites.length === 0);

  markerCluster.clearLayers();
  markerMap.clear();

  if (sites.length === 0) {
    list.innerHTML = `<div class="empty-state">
      <p>😔 No primitive campsites found in this area.</p>
      <p class="hint">Try increasing the search radius or a different location.</p>
    </div>`;
    return;
  }

  list.innerHTML = sites.map((s, i) => campCard(s, i)).join('');

  // Add click handlers
  list.querySelectorAll('.camp-card').forEach((card) => {
    const id = card.dataset.id;
    card.addEventListener('click', (e) => {
      if (e.target.closest('a, .btn-reddit')) return; // let links propagate
      focusCampsite(id);
    });
    card.querySelector('.btn-reddit')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const site = allCampsites.find(s => String(s.id) === id);
      if (site) openReddit(site);
    });
  });

  // Add map markers
  sites.forEach((s) => {
    const marker = L.marker([s.lat, s.lon], { icon: campIcon(s.score) });
    marker.bindPopup(popupHtml(s));
    marker.on('click', () => focusCampsite(String(s.id)));
    markerMap.set(String(s.id), marker);
    markerCluster.addLayer(marker);
  });
}

// ─── Camp Card HTML ───────────────────────────────────────────────────────────
const MAX_SCORE = 14;

function flagTag(f) {
  const classMap = {
    backcountry: 'flag-backcountry',
    free: 'flag-free',
    informal: 'flag-informal',
    'no reservation': 'flag-no-reservation',
    'wilderness hut': 'flag-wilderness-hut',
    'public land': 'flag-public-land',
  };
  const cls = classMap[f] || 'flag-free';
  return `<span class="flag-tag ${cls}">${f}</span>`;
}

function campCard(s, i) {
  const pct = Math.round(Math.min(s.score / MAX_SCORE, 1) * 100);
  const flags = s.flags.map(flagTag).join('');
  const desc = s.description
    ? `<div class="camp-desc">${escHtml(s.description)}</div>`
    : '';
  const websiteBtn = s.website
    ? `<a class="btn-sm btn-link" href="${escAttr(s.website)}" target="_blank" rel="noopener">🌐 Web</a>`
    : '';

  return `
    <div class="camp-card" data-id="${s.id}" data-index="${i}">
      <div class="camp-card-header">
        <div class="camp-name">${escHtml(s.name)}</div>
        <div class="camp-distance">${s.distance_mi} mi</div>
      </div>
      ${flags ? `<div class="camp-flags">${flags}</div>` : ''}
      <div class="prim-score">
        <span class="prim-label">Primitiveness</span>
        <div class="prim-bar"><div class="prim-fill" style="width:${pct}%"></div></div>
        <span class="prim-label">${pct}%</span>
      </div>
      ${desc}
      <div class="camp-actions">
        <button class="btn-sm btn-reddit">🔴 Reddit Reviews</button>
        <button class="btn-sm btn-map" onclick="zoomToSite('${s.id}')">🗺️ Zoom</button>
        ${websiteBtn}
      </div>
    </div>`;
}

function popupHtml(s) {
  const flags = s.flags.join(', ') || 'standard';
  return `
    <strong>${escHtml(s.name)}</strong><br/>
    <span style="color:#7a9e7a;font-size:0.8rem">${s.distance_mi} mi away · ${flags}</span><br/>
    <span style="color:#5cb85c;font-size:0.8rem">Primitiveness: ${Math.round(Math.min(s.score/MAX_SCORE,1)*100)}%</span>`;
}

// ─── Focus / Zoom ─────────────────────────────────────────────────────────────
function focusCampsite(id) {
  const site = allCampsites.find(s => String(s.id) === id);
  if (!site) return;

  // Highlight card
  if (activeCard) activeCard.classList.remove('active');
  activeCard = document.querySelector(`.camp-card[data-id="${id}"]`);
  if (activeCard) {
    activeCard.classList.add('active');
    activeCard.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  // Highlight & open marker
  if (activeMarker) activeMarker.setIcon(campIcon(activeMarker._campScore || 0));
  const marker = markerMap.get(id);
  if (marker) {
    marker._campScore = site.score;
    marker.setIcon(campIcon(site.score, true));
    markerCluster.zoomToShowLayer(marker, () => {
      marker.openPopup();
    });
    activeMarker = marker;
  }
}

function zoomToSite(id) {
  const site = allCampsites.find(s => String(s.id) === id);
  if (!site) return;
  map.setView([site.lat, site.lon], 13);
  const marker = markerMap.get(id);
  if (marker) marker.openPopup();
}

// Make zoomToSite globally accessible (called from onclick in card HTML)
window.zoomToSite = zoomToSite;

// ─── Reddit Panel ─────────────────────────────────────────────────────────────
async function openReddit(site) {
  const panel = document.getElementById('redditPanel');
  const content = document.getElementById('redditContent');
  const title = document.getElementById('redditTitle');
  const queryEl = document.getElementById('redditQuery');

  panel.classList.remove('hidden');
  title.textContent = `Reddit: ${site.name}`;
  content.innerHTML = `<div class="loading-dots"><span></span><span></span><span></span></div>`;
  queryEl.textContent = '';

  // Derive state hint from tags
  const state = site.tags?.['addr:state'] || site.tags?.['addr:country'] || '';

  try {
    const params = new URLSearchParams({ name: site.name, state });
    const res = await fetch(`/api/reviews?${params}`);
    const data = await res.json();

    queryEl.innerHTML = `Searched: <strong>${escHtml(data.query)}</strong>`;

    if (!res.ok) {
      content.innerHTML = `<div class="no-reviews">⚠️ ${escHtml(data.error || 'Error fetching reviews')}</div>`;
      return;
    }

    const posts = data.posts || [];
    if (posts.length === 0) {
      content.innerHTML = `<div class="no-reviews">
        😞 No Reddit reviews found for <strong>${escHtml(site.name)}</strong>.<br/><br/>
        Try searching manually on Reddit for this location.
        <br/><br/>
        <a href="https://www.reddit.com/search/?q=${encodeURIComponent(site.name + ' primitive camping')}&sort=top"
           target="_blank" rel="noopener" style="color:#5cb85c">Open Reddit Search ↗</a>
      </div>`;
      return;
    }

    content.innerHTML = posts.map(redditPostHtml).join('');
  } catch (e) {
    content.innerHTML = `<div class="no-reviews">⚠️ Network error fetching Reddit reviews.</div>`;
  }
}

function redditPostHtml(p) {
  const date = p.created_utc
    ? new Date(p.created_utc * 1000).toLocaleDateString()
    : '';
  const snippet = p.snippet
    ? `<div class="post-snippet">${escHtml(p.snippet)}</div>`
    : '';
  return `
    <div class="reddit-post">
      <div class="post-sub">r/${escHtml(p.subreddit)}</div>
      <div class="post-title"><a href="${escAttr(p.url)}" target="_blank" rel="noopener">${escHtml(p.title)}</a></div>
      ${snippet}
      <div class="post-meta">
        <span class="post-score">▲ ${p.score.toLocaleString()}</span>
        <span class="post-comments">💬 ${p.num_comments}</span>
        ${date ? `<span>${date}</span>` : ''}
      </div>
    </div>`;
}

document.getElementById('closeReddit').addEventListener('click', () => {
  document.getElementById('redditPanel').classList.add('hidden');
});

// ─── Filters ──────────────────────────────────────────────────────────────────
function applyFilters() {
  const free = document.getElementById('filterFree').checked;
  const backcountry = document.getElementById('filterBackcountry').checked;
  const noRes = document.getElementById('filterNoReservation').checked;

  const filtered = allCampsites.filter(s => {
    if (free && !s.flags.includes('free')) return false;
    if (backcountry && !s.flags.includes('backcountry')) return false;
    if (noRes && !s.flags.includes('no reservation')) return false;
    return true;
  });

  renderResults(filtered, filtered.length);
}

['filterFree', 'filterBackcountry', 'filterNoReservation'].forEach(id => {
  document.getElementById(id)?.addEventListener('change', applyFilters);
});

// ─── Loading State ────────────────────────────────────────────────────────────
function setLoading(on, msg = '') {
  const list = document.getElementById('campList');
  const searchBtn = document.getElementById('searchBtn');
  const gpsBtn = document.getElementById('gpsBtn');
  searchBtn.disabled = on;
  gpsBtn.disabled = on;
  if (on) {
    list.innerHTML = `<div class="loading-spinner">
      <div class="spinner"></div>
      <span>${msg}</span>
    </div>`;
  }
}

// ─── Escape helpers ───────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(str) {
  return String(str ?? '').replace(/"/g,'&quot;');
}

// ─── Event Wiring ─────────────────────────────────────────────────────────────
document.getElementById('searchBtn').addEventListener('click', searchByText);
document.getElementById('gpsBtn').addEventListener('click', searchByGPS);
document.getElementById('locationInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') searchByText();
});

// ─── Bootstrap ────────────────────────────────────────────────────────────────
initMap();
