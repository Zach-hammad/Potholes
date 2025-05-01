// static/js/app.js
document.addEventListener('DOMContentLoaded', () => {
    // 1) Initialize map with CartoDB Positron basemap
    const map = L.map('map').setView([39.9526, -75.1652], 13);
    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      {
        attribution:
          '&copy; <a href="https://carto.com/">CARTO</a> contributors, &copy; OpenStreetMap',
        subdomains: 'abcd',
        maxZoom: 19
      }
    ).addTo(map);
  
    // 2) Add scale control (metric only)
    L.control.scale({ imperial: false }).addTo(map);
  
    // 3) MarkerCluster group
    const markers = L.markerClusterGroup();
    map.addLayer(markers);
  
    // 4) DOM elements
    const severityEl   = document.getElementById('severity');
    const startEl      = document.getElementById('start_date');
    const endEl        = document.getElementById('end_date');
    const confEl       = document.getElementById('confidence');
    const confValEl    = document.getElementById('conf_val');
    const exportCsvBtn = document.getElementById('export-csv');
    const exportGeoBtn = document.getElementById('export-geojson');
  
    // 5) Build query params from filters
    function buildParams() {
      const params = new URLSearchParams();
      Array.from(severityEl.selectedOptions)
        .map(o => o.value)
        .forEach(v => params.append('severity', v));
  
      if (startEl.value) params.set('start_date', startEl.value);
      if (endEl.value)   params.set('end_date', endEl.value);
  
      params.set('conf_min', confEl.value);
      confValEl.textContent = parseFloat(confEl.value).toFixed(2);
      return params.toString();
    }
  
    // 6) Severity → color helper
    function severityColor(s) {
      return s >= 4 ? '#e31a1c'
           : s >= 3 ? '#fd8d3c'
           : s >= 2 ? '#fecc5c'
           :          '#31a354';
    }
  
    // 7) Create custom divIcon based on severity
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
  
    // 8) Fetch data and render markers
    async function fetchAndRender() {
      const qs = buildParams();
      try {
        const res = await fetch('/api/potholes?' + qs);
        const data = await res.json();
        console.log('Potholes:', data);
  
        markers.clearLayers();
        data.forEach(p => {
          const m = L.marker([p.lat, p.lng], { icon: makeIcon(p.severity) })
            .bindPopup(`
              <strong>ID:</strong> ${p.id}<br>
              <strong>Date:</strong> ${p.date}<br>
              <strong>Severity:</strong> ${p.severity}<br>
              <strong>Confidence:</strong> ${p.confidence.toFixed(2)}
            `);
          markers.addLayer(m);
        });
  
        if (!data.length) console.warn('No potholes returned.');
      } catch (err) {
        console.error('Error fetching potholes:', err);
      }
    }
  
    // 9) Legend control
    const legend = L.control({ position: 'bottomright' });
    legend.onAdd = () => {
      const div = L.DomUtil.create('div', 'legend');
      const grades = [1,2,3,4,5];
      div.innerHTML = '<strong>Severity</strong><br>';
      grades.forEach(g => {
        div.innerHTML +=
          `<i style="
            background:${severityColor(g)};
            width:12px; height:12px;
            display:inline-block;
            margin-right:4px;
            border:1px solid #fff;
          "></i> ${g}<br>`;
      });
      return div;
    };
    legend.addTo(map);
  
    // 10) Wire up filters & exports
    [severityEl, startEl, endEl, confEl]
      .forEach(el => el.addEventListener('change', fetchAndRender));
  
    exportCsvBtn.addEventListener('click', () => {
      window.location = '/export?format=csv&' + buildParams();
    });
    exportGeoBtn.addEventListener('click', () => {
      window.location = '/export?format=geojson&' + buildParams();
    });
  
    // initial load
    fetchAndRender();
  });
  