// static/js/app.js

document.addEventListener('DOMContentLoaded', () => {
    // 1) Initialize map without default zoom controls
    const map = L.map('map', { zoomControl: false }).setView([39.9526, -75.1652], 13);
    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      {
        attribution:
          '&copy; <a href="https://carto.com/">CARTO</a> contributors, &copy; OpenStreetMap',
        subdomains: 'abcd',
        maxZoom: 19
      }
    ).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
  
    // 2) Marker cluster
    const markers = L.markerClusterGroup().addTo(map);
  
    // 3) Helpers
    function severityColor(s) {
      return s >= 4 ? '#e31a1c'
           : s >= 3 ? '#fd8d3c'
           : s >= 2 ? '#fecc5c'
           :          '#31a354';
    }
    function makeIcon(sev) {
      const color = severityColor(sev);
      return L.divIcon({
        html: `<div style="
          background:${color};
          width:16px; height:16px;
          border:2px solid white;
          border-radius:50%;
          box-shadow:0 0 2px rgba(0,0,0,0.5);
        "></div>`,
        className: '',
        iconSize: [20,20],
        iconAnchor: [10,10]
      });
    }
  
    // 4) Control variables
    let sevChecks, startEl, endEl, confEl, confValEl, exportCsvBtn, exportGeoBtn, errDiv, zoomInBtn, zoomOutBtn;
  
    // 5) Legend panel with embedded controls + custom zoom + home link
    const legend = L.control({ position: 'topleft' });
    legend.onAdd = () => {
      const w = L.DomUtil.create('div', 'leaflet-control legend tb-panel');
      w.innerHTML = `
        <div class="panel-header">
          <a href="/" class="home-link">Home</a>
          <h3>Filters & Export</h3>
        </div>
        <div class="tb-body">
          <div class="filter-group">
            <label>Severity</label>
            <div class="severity-options">
              <label><input type="checkbox" value="1"> 1 – Minor</label>
              <label><input type="checkbox" value="2"> 2 – Low</label>
              <label><input type="checkbox" value="3"> 3 – Medium</label>
              <label><input type="checkbox" value="4"> 4 – High</label>
              <label><input type="checkbox" value="5"> 5 – Critical</label>
            </div>
          </div>
          <div class="filter-group">
            <label>Start Date</label>
            <input type="date" id="start_date"/>
          </div>
          <div class="filter-group">
            <label>End Date</label>
            <input type="date" id="end_date"/>
          </div>
          <div class="filter-group">
            <label>Confidence ≥ <span id="conf_val">0.00</span></label>
            <input type="number" id="confidence" min="0" max="1" step="0.01" value="0.00"/>
          </div>
          <div id="conf-error" class="conf-error"></div>
          <div class="zoom-group">
            <label>Zoom</label>
            <button id="zoom-in">+</button>
            <button id="zoom-out">−</button>
          </div>
          <button class="export-btn" id="export-csv">Export CSV</button>
          <button class="export-btn" id="export-geojson">Export GeoJSON</button>
        </div>
      `;
      L.DomEvent.disableClickPropagation(w);
  
      // grab controls
      sevChecks     = w.querySelectorAll('.severity-options input');
      startEl       = w.querySelector('#start_date');
      endEl         = w.querySelector('#end_date');
      confEl        = w.querySelector('#confidence');
      confValEl     = w.querySelector('#conf_val');
      errDiv        = w.querySelector('#conf-error');
      zoomInBtn     = w.querySelector('#zoom-in');
      zoomOutBtn    = w.querySelector('#zoom-out');
      exportCsvBtn  = w.querySelector('#export-csv');
      exportGeoBtn  = w.querySelector('#export-geojson');
  
      // attach handlers
      sevChecks.forEach(chk => chk.addEventListener('change', fetchAndRender));
      startEl.addEventListener('change', fetchAndRender);
      endEl.addEventListener('change', fetchAndRender);
      confEl.addEventListener('change', () => {
        let v = parseFloat(confEl.value);
        if (isNaN(v) || v < 0 || v > 1) {
          errDiv.textContent = '⚠️ Confidence must be 0.00–1.00';
          errDiv.style.display = 'block';
          v = Math.min(Math.max(v||0,0),1);
          confEl.value = v.toFixed(2);
        } else {
          errDiv.style.display = 'none';
        }
        confValEl.textContent = parseFloat(confEl.value).toFixed(2);
        fetchAndRender();
      });
  
      zoomInBtn.addEventListener('click', () => map.zoomIn());
      zoomOutBtn.addEventListener('click', () => map.zoomOut());
  
      exportCsvBtn.addEventListener('click', () => {
        window.location = '/export?format=csv&' + buildParams();
      });
      exportGeoBtn.addEventListener('click', () => {
        window.location = '/export?format=geojson&' + buildParams();
      });
  
      return w;
    };
    legend.addTo(map);
  
    // 6) Build params
    function buildParams() {
      const params = new URLSearchParams();
      sevChecks.forEach(chk => { if (chk.checked) params.append('severity', chk.value); });
      if (startEl.value) params.set('start_date', startEl.value);
      if (endEl.value)   params.set('end_date', endEl.value);
      const c = parseFloat(confEl.value)||0;
      params.set('conf_min', c.toFixed(2));
      return params.toString();
    }
  
    // 7) Fetch & render
    async function fetchAndRender() {
      try {
        const res = await fetch('/api/potholes?' + buildParams());
        const data = await res.json();
        markers.clearLayers();
        data.forEach(p => {
          L.marker([p.lat, p.lng], { icon: makeIcon(p.severity) })
            .bindPopup(
              `<strong>ID:</strong> ${p.id}<br>` +
              `<strong>Date:</strong> ${p.date}<br>` +
              `<strong>Severity:</strong> ${p.severity}<br>` +
              `<strong>Confidence:</strong> ${p.confidence.toFixed(2)}`
            )
            .addTo(markers);
        });
      } catch (err) {
        console.error('Error:', err);
      }
    }
  
    // 8) Initial load
    fetchAndRender();
  });
  