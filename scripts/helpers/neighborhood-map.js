// File: scripts/utilities/neighborhood-map.js
let cachedBoundaryData = null;

class NeighborhoodMap extends HTMLElement {
  connectedCallback() {
    this.lat = parseFloat(this.getAttribute('lat')) || 47.7560;
    this.lon = parseFloat(this.getAttribute('lon')) || -122.3415;
    this.zoom = parseInt(this.getAttribute('zoom')) || 12;
    this.activeCity = (this.getAttribute('active-city') || 'Shoreline').trim();
    this.accentColor = this.resolveAccentColor();

    this.style.display = 'block';
    this.style.width = '100%';
    this.style.height = '100%';

    this.initLeaflet();
  }

  resolveAccentColor() {
    const attr = (this.getAttribute('accent-color') || '').trim();
    if (attr && !attr.startsWith('var(')) {
      return attr;
    }
    const varName = attr ? attr.replace(/^var\(\s*/, '').replace(/[\s,\)].*$/, '').trim() : '--color-secondary-default';
    const computed = window.getComputedStyle(this).getPropertyValue(varName).trim();
    return computed || 'var(--color-secondary-default, #1E4D6B)';
  }

  initLeaflet() {
    // 1. Scoped CSS for active focal marker and floating badge
    if (!document.getElementById('neighborhood-map-style')) {
      const style = document.createElement('style');
      style.id = 'neighborhood-map-style';
      style.textContent = `
        .active-city-marker-wrap {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: flex-end;
          pointer-events: auto;
          cursor: default;
        }
        .active-city-pill {
          background: var(--color-background-universal, #FFFFFF);
          color: var(--color-primary-default, #1C1C1E);
          border: 1px solid var(--color-border-light, rgba(0, 0, 0, 0.14));
          border-radius: 999px;
          padding: 3px 10px;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          white-space: nowrap;
          box-shadow: 0 4px 14px rgba(0, 0, 0, 0.16);
          margin-bottom: 4px;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          line-height: 1.2;
        }
        .active-city-pill-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .active-city-pin {
          width: 22px;
          height: 22px;
          border: 2.5px solid var(--white, #FFFFFF);
          border-radius: 50% 50% 50% 0;
          transform: rotate(-45deg);
          box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3);
          box-sizing: border-box;
        }
        .active-city-pin::after {
          content: '';
          display: block;
          width: 5px;
          height: 5px;
          background: var(--white, #FFFFFF);
          border-radius: 50%;
          margin: 6px auto;
        }
      `;
      document.head.appendChild(style);
    }

    // 2. Inject Leaflet CSS if not already loaded
    if (!document.querySelector('link[href*="leaflet.css"]')) {
      const cssLink = document.createElement('link');
      cssLink.rel = 'stylesheet';
      cssLink.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(cssLink);
    }

    // 3. Inject Leaflet JS and initialize
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

  async fetchBoundaries() {
    if (cachedBoundaryData) return cachedBoundaryData;
    try {
      const res = await fetch('/data/city_boundaries.json');
      if (res.ok) {
        cachedBoundaryData = await res.json();
        return cachedBoundaryData;
      }
    } catch (e) {
      console.warn('Could not load /data/city_boundaries.json:', e);
    }
    return null;
  }

  async renderMap() {
    if (this._mapInstance) return;

    // Dedicated inner canvas container
    this._canvas = document.createElement('div');
    this._canvas.style.width = '100%';
    this._canvas.style.height = '100%';
    this._canvas.style.position = 'relative';
    this.innerHTML = '';
    this.appendChild(this._canvas);

    // Initialize Leaflet instance locked to inner container
    this._mapInstance = window.L.map(this._canvas, {
      scrollWheelZoom: false,
      zoomControl: true
    }).setView([this.lat, this.lon], this.zoom);

    // Esri World Light Gray Base Layer (Subdued topography and water bodies)
    window.L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
      maxZoom: 16
    }).addTo(this._mapInstance);

    // Esri World Light Gray Reference Layer (Subdued street labels and road numbers)
    window.L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 16
    }).addTo(this._mapInstance);

    // Load and render active city boundary vector from /data/city_boundaries.json
    const boundaries = await this.fetchBoundaries();
    if (boundaries && boundaries.features) {
      const activeClean = this.activeCity.toLowerCase().replace(/[^a-z0-9]/g, '');
      const boundaryFeature = boundaries.features.find(f => {
        const p = f.properties || {};
        const cName = (p.CityName || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        const slug = (p.slug || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        const name = (p.name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        return cName === activeClean || slug === activeClean || name === activeClean;
      });

      if (boundaryFeature) {
        this._boundaryLayer = window.L.geoJSON(boundaryFeature, {
          style: {
            color: this.accentColor,
            weight: 2.25,
            opacity: 0.88,
            lineCap: 'round',
            lineJoin: 'round',
            fill: false
          }
        }).addTo(this._mapInstance);
      }
    }

    // Active City Focal Pin with Dynamic Color Accent
    const activeIcon = window.L.divIcon({
      className: 'active-city-custom-icon',
      html: `
        <div class="active-city-marker-wrap">
          <div class="active-city-pill">
            <span class="active-city-pill-dot" style="background: ${this.accentColor};"></span>
            <span>${this.activeCity}</span>
          </div>
          <div class="active-city-pin" style="background: ${this.accentColor};"></div>
        </div>
      `,
      iconSize: [160, 52],
      iconAnchor: [80, 52]
    });

    window.L.marker([this.lat, this.lon], { icon: activeIcon, zIndexOffset: 1000 }).addTo(this._mapInstance);

    // Invalidate size on initial mount and observe dynamic container resizing
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