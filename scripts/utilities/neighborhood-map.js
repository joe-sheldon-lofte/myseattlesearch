// File: scripts/utilities/neighborhood-map.js
class NeighborhoodMap extends HTMLElement {
  connectedCallback() {
    this.lat = parseFloat(this.getAttribute('lat')) || 47.7560;
    this.lon = parseFloat(this.getAttribute('lon')) || -122.3415;
    this.zoom = parseInt(this.getAttribute('zoom')) || 13;

    this.style.display = 'block';
    this.style.width = '100%';
    this.style.height = '100%';

    this.initLeaflet();
  }

  initLeaflet() {
    // 1. Inject Leaflet CSS if not already present in the head
    if (!document.querySelector('link[href*="leaflet.css"]')) {
      const cssLink = document.createElement('link');
      cssLink.rel = 'stylesheet';
      cssLink.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(cssLink);
    }

    // 2. Inject Leaflet JS if window.L is not available yet
    if (typeof window.L === 'undefined') {
      const existingScript = document.querySelector('script[src*="leaflet.js"]');
      if (existingScript) {
        existingScript.addEventListener('load', () => this.renderMap());
      } else {
        const script = document.createElement('script');
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        script.onload = () => this.renderMap();
        document.head.appendChild(script);
      }
    } else {
      this.renderMap();
    }
  }

  renderMap() {
    if (this._mapInstance) return;

    // Create a dedicated inner canvas container
    this._canvas = document.createElement('div');
    this._canvas.style.width = '100%';
    this._canvas.style.height = '100%';
    this._canvas.style.position = 'relative';
    this.innerHTML = '';
    this.appendChild(this._canvas);

    // Initialize Leaflet locked to inner container
    this._mapInstance = window.L.map(this._canvas, {
      scrollWheelZoom: false,
      zoomControl: true
    }).setView([this.lat, this.lon], this.zoom);

    // CARTO Positron Light Tiles (Muted palette engineered for data overlays)
    window.L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20
    }).addTo(this._mapInstance);

    // High-contrast SVG teardrop pin styled to design tokens
    const pinIcon = window.L.divIcon({
      className: 'neighborhood-map-pin',
      html: `<div style="width: 24px; height: 24px; background: #1E4D6B; border: 2.5px solid #FFFFFF; border-radius: 50% 50% 50% 0; transform: rotate(-45deg); box-shadow: 0 4px 10px rgba(0,0,0,0.3); box-sizing: border-box;"><div style="width: 6px; height: 6px; background: #FFFFFF; border-radius: 50%; margin: 6.5px auto;"></div></div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 24]
    });

    window.L.marker([this.lat, this.lon], { icon: pinIcon }).addTo(this._mapInstance);

    // Invalidate size on load and bind ResizeObserver to handle fluid adjustments dynamically
    setTimeout(() => {
      if (this._mapInstance) this._mapInstance.invalidateSize();
    }, 250);

    if (window.ResizeObserver) {
      this._resizeObserver = new ResizeObserver(() => {
        if (this._mapInstance) this._mapInstance.invalidateSize();
      });
      this._resizeObserver.observe(this);
    }
  }

  disconnectedCallback() {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
    }
    if (this._mapInstance) {
      this._mapInstance.remove();
      this._mapInstance = null;
    }
  }
}

if (!customElements.get('neighborhood-map')) {
  customElements.define('neighborhood-map', NeighborhoodMap);
}