// File: scripts/neighborhood-map.js
class NeighborhoodMap extends HTMLElement {
  connectedCallback() {
    // 1. Read coordinates and zoom from HTML attributes, with Edmonds fallback
    this.lat = parseFloat(this.getAttribute('lat')) || 47.8107;
    this.lon = parseFloat(this.getAttribute('lon')) || -122.3774;
    this.zoom = parseInt(this.getAttribute('zoom')) || 13;
    
    // 2. Enforce physical dimensions so the map engine has a canvas to draw on
    if (!this.style.display) this.style.display = 'block';
    if (!this.style.height) this.style.height = '380px';
    this.style.width = '100%';

    this.initMap();
  }

  initMap() {
    // 3. Lazy-load Leaflet engines only if they haven't been loaded yet
    if (typeof window.L === 'undefined') {
      const css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(css);

      const script = document.createElement('script');
      script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
      script.onload = () => this.renderLeaflet();
      document.head.appendChild(script);
    } else {
      this.renderLeaflet();
    }
  }

  renderLeaflet() {
    // Prevent duplicate initializations if the framework re-renders
    if (this._mapInstance) return;
    
    // Initialize map locked to the component's boundaries
    this._mapInstance = window.L.map(this).setView([this.lat, this.lon], this.zoom);

    // Mount CARTO Positron Light (Muted grays, perfect for data overlays)
    window.L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 20
    }).addTo(this._mapInstance);

    // Drop primary center pin
    window.L.marker([this.lat, this.lon]).addTo(this._mapInstance);
  }
}

// Register the custom element globally
if (!customElements.get('neighborhood-map')) {
  customElements.define('neighborhood-map', NeighborhoodMap);
}