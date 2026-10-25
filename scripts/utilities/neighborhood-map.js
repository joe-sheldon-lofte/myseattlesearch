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
    // 1. Scoped CSS for subdued architectural tile layer and retina markers
    if (!document.getElementById('neighborhood-map-style')) {
      const style = document.createElement('style');
      style.id = 'neighborhood-map-style';
      style.textContent = `
        neighborhood-map .leaflet-tile-pane {
          filter: grayscale(75%) contrast(98%) brightness(102%);
          -webkit-filter: grayscale(75%) contrast(98%) brightness(102%);
        }
      `;
      document.head.appendChild(style);
    }

    // 2. Inject Leaflet CSS if not already present
    if (!document.querySelector('link[href*="leaflet.css"]')) {
      const cssLink = document.createElement('link');
      cssLink.rel = 'stylesheet';
      cssLink.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(cssLink);
    }

    // 3. Inject Leaflet JS if window.L is not available yet
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

    // Initialize Leaflet instance bound to container
    this._mapInstance = window.L.map(this._canvas, {
      scrollWheelZoom: false,
      zoomControl: true
    }).setView([this.lat, this.lon], this.zoom);

    // Full-granularity OpenStreetMap basemap (filtered via CSS in tile-pane)
    window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
      maxZoom: 19
    }).addTo(this._mapInstance);

    // Teardrop map pin utilizing system design tokens
    const pinIcon = window.L.divIcon({
      className: 'neighborhood-map-pin',
      html: `
        <div style="width: 24px; height: 24px; background: var(--color-secondary-default, #1E4D6B); border: 2.5px solid var(--white, #FFFFFF); border-radius: 50% 50% 50% 0; transform: rotate(-45deg); box-shadow: 0 4px 10px rgba(0,0,0,0.3); box-sizing: border-box;">
          <div style="width: 6px; height: 6px; background: var(--white, #FFFFFF); border-radius: 50%; margin: 6.5px auto;"></div>
        </div>
      `,
      iconSize: [24, 24],
      iconAnchor: [12, 24]
    });

    window.L.marker([this.lat, this.lon], { icon: pinIcon }).addTo(this._mapInstance);

    // Invalidate size on load and observe fluid resizing dynamically
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