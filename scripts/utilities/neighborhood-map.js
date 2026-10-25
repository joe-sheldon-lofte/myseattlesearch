// File: scripts/utilities/neighborhood-map.js
let cachedCityData = null;

class NeighborhoodMap extends HTMLElement {
  connectedCallback() {
    this.lat = parseFloat(this.getAttribute('lat')) || 47.7560;
    this.lon = parseFloat(this.getAttribute('lon')) || -122.3415;
    this.zoom = parseInt(this.getAttribute('zoom')) || 12;
    this.activeCity = (this.getAttribute('active-city') || 'Shoreline').trim();

    this.style.display = 'block';
    this.style.width = '100%';
    this.style.height = '100%';

    this.initLeaflet();
  }

  initLeaflet() {
    // 1. Scoped CSS for markers, labels, and text halos
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
          cursor: pointer;
        }
        .active-city-pill {
          background: var(--color-background-universal, #FFFFFF);
          color: var(--color-primary-default, #1C1C1E);
          border: 1px solid var(--color-border-light, rgba(0, 0, 0, 0.14));
          border-radius: 999px;
          padding: 3px 9px;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          white-space: nowrap;
          box-shadow: 0 4px 14px rgba(0, 0, 0, 0.16);
          margin-bottom: 4px;
          display: inline-flex;
          align-items: center;
          gap: 5px;
          line-height: 1.2;
        }
        .active-city-pill-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--color-secondary-default, #1E4D6B);
          flex-shrink: 0;
        }
        .active-city-pin {
          width: 22px;
          height: 22px;
          background: var(--color-secondary-default, #1E4D6B);
          border: 2.5px solid #FFFFFF;
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
          background: #FFFFFF;
          border-radius: 50%;
          margin: 6px auto;
        }
        .regional-city-marker {
          display: flex;
          align-items: center;
          gap: 4px;
          pointer-events: none;
          white-space: nowrap;
        }
        .regional-city-dot {
          width: 5px;
          height: 5px;
          border-radius: 50%;
          background: #64748B;
          border: 1px solid #FFFFFF;
          box-shadow: 0 0 2px rgba(0, 0, 0, 0.25);
          flex-shrink: 0;
        }
        .regional-city-name {
          font-size: 10px;
          font-weight: 700;
          color: #334155;
          text-shadow: 0 1px 2px #FFFFFF, 0 -1px 2px #FFFFFF, 1px 0 2px #FFFFFF, -1px 0 2px #FFFFFF, 0 0 4px #FFFFFF;
          letter-spacing: 0.01em;
          line-height: 1;
        }
      `;
      document.head.appendChild(style);
    }

    // 2. Inject Leaflet CSS
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

  async fetchCities() {
    if (cachedCityData) return cachedCityData;
    try {
      const res = await fetch('/data/city_data.json');
      if (res.ok) {
        cachedCityData = await res.json();
        return cachedCityData;
      }
    } catch (e) {
      console.warn('Could not load /data/city_data.json for map markers:', e);
    }
    return [];
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

    // Initialize Leaflet instance
    this._mapInstance = window.L.map(this._canvas, {
      scrollWheelZoom: false,
      zoomControl: true
    }).setView([this.lat, this.lon], this.zoom);

    // Esri World Light Gray Base Layer (Subdued, clean geography)
    window.L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
      maxZoom: 16
    }).addTo(this._mapInstance);

    // Esri World Light Gray Reference Layer (Subdued county/water lines)
    window.L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 16
    }).addTo(this._mapInstance);

    // Fetch and plot all 59 cities
    const cities = await this.fetchCities();
    const activeClean = this.activeCity.toLowerCase().replace(/[^a-z0-9]/g, '');

    cities.forEach(c => {
      const cLat = parseFloat(c.Latitude);
      const cLon = parseFloat(c.Longitude);
      if (isNaN(cLat) || isNaN(cLon)) return;

      const cName = c.City || '';
      const cClean = cName.toLowerCase().replace(/[^a-z0-9]/g, '');
      const isActive = cClean === activeClean;

      if (isActive) {
        // Active City: Prominent Pill Badge + Alpine Blue Pin
        const activeIcon = window.L.divIcon({
          className: 'active-city-custom-icon',
          html: `
            <div class="active-city-marker-wrap">
              <div class="active-city-pill">
                <span class="active-city-pill-dot"></span>
                <span>${cName}</span>
              </div>
              <div class="active-city-pin"></div>
            </div>
          `,
          iconSize: [160, 52],
          iconAnchor: [80, 52]
        });

        window.L.marker([cLat, cLon], { icon: activeIcon, zIndexOffset: 1000 }).addTo(this._mapInstance);
      } else {
        // Surrounding 58 Cities: Subtle Dot + Typographic Halo Label
        const regionalIcon = window.L.divIcon({
          className: 'regional-city-custom-icon',
          html: `
            <div class="regional-city-marker">
              <div class="regional-city-dot"></div>
              <div class="regional-city-name">${cName}</div>
            </div>
          `,
          iconSize: [120, 16],
          iconAnchor: [3, 8]
        });

        window.L.marker([cLat, cLon], { icon: regionalIcon, zIndexOffset: 10 }).addTo(this._mapInstance);
      }
    });

    // Invalidate size on initial mount and observe fluid resizing
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