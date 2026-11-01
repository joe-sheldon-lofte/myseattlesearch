export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 1. Health & Edge Diagnostic Gate
    if (url.pathname === "/api/health") {
      return new Response(
        JSON.stringify({
          status: "healthy",
          environment: env.ENVIRONMENT || "production",
          timestamp_utc: new Date().toISOString(),
          secrets: {
            wsdot: Boolean(env.WSDOT_ACCESS_CODE),
            onebusaway: Boolean(env.ONEBUSAWAY_API_KEY),
            tomtom: Boolean(env.TOMTOM_API_KEY),
            airlabs: Boolean(env.AIRLABS_API_KEY)
          }
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }
        }
      );
    }

    // 2. WSDOT Toll Rates (SR-520, I-405, SR-99 Tunnel) — 30s Edge Cache
    if (url.pathname.startsWith("/api/tolls")) {
      if (!env.WSDOT_ACCESS_CODE) {
        return new Response(JSON.stringify({ error: "Missing WSDOT_ACCESS_CODE" }), { status: 500 });
      }
      const upstream = `https://wsdot.wa.gov/Traffic/api/TollRates/TollRatesREST.svc/GetTollRatesAsJson?AccessCode=${env.WSDOT_ACCESS_CODE}`;
      return handleCachedUpstream(request, upstream, 30);
    }

    // 3. WSDOT Ferries (Terminals, Sailings, Vessel Telemetry) — 60s Edge Cache
    if (url.pathname.startsWith("/api/ferries")) {
      if (!env.WSDOT_ACCESS_CODE) {
        return new Response(JSON.stringify({ error: "Missing WSDOT_ACCESS_CODE" }), { status: 500 });
      }
      const endpoint = url.searchParams.get("endpoint") || "terminals";
      const upstream = `https://wsdot.wa.gov/ferries/api/${endpoint}/rest/v1/?AccessCode=${env.WSDOT_ACCESS_CODE}`;
      return handleCachedUpstream(request, upstream, 60);
    }

    // 4. OneBusAway Regional Transit (Bus, Light Rail, Sounder, Amtrak) — 30s Edge Cache
    if (url.pathname.startsWith("/api/transit")) {
      if (!env.ONEBUSAWAY_API_KEY) {
        return new Response(JSON.stringify({ error: "Missing ONEBUSAWAY_API_KEY" }), { status: 500 });
      }
      const stopId = url.searchParams.get("stopId") || "1_29261";
      const upstream = `https://api.pugetsound.onebusaway.org/api/where/arrivals-and-departures-for-stop/${stopId}.json?key=${env.ONEBUSAWAY_API_KEY}`;
      return handleCachedUpstream(request, upstream, 30);
    }

    // 5. TomTom Traffic Flow Raster Tile Proxy — 300s (5m) Edge Cache
    if (url.pathname.startsWith("/api/traffic-tile")) {
      if (!env.TOMTOM_API_KEY) {
        return new Response(JSON.stringify({ error: "Missing TOMTOM_API_KEY" }), { status: 500 });
      }
      const z = url.searchParams.get("z");
      const x = url.searchParams.get("x");
      const y = url.searchParams.get("y");

      if (!z || !x || !y) {
        return new Response(JSON.stringify({ error: "Missing tile coordinates z, x, y" }), { status: 400 });
      }

      const upstream = `https://api.tomtom.com/traffic/map/4/tile/flow/relative/${z}/${x}/${y}.png?key=${env.TOMTOM_API_KEY}`;
      return handleCachedImageTile(request, upstream, 300);
    }

    // 6. TomTom Driving Commute Routing Matrix — 300s (5m) Edge Cache
    if (url.pathname.startsWith("/api/commute-time")) {
      if (!env.TOMTOM_API_KEY) {
        return new Response(JSON.stringify({ error: "Missing TOMTOM_API_KEY" }), { status: 500 });
      }
      const origin = url.searchParams.get("origin");
      const destination = url.searchParams.get("dest");

      if (!origin || !destination) {
        return new Response(JSON.stringify({ error: "Requires origin and dest parameters" }), { status: 400 });
      }

      const upstream = `https://api.tomtom.com/routing/1/calculateRoute/${origin}:${destination}/json?key=${env.TOMTOM_API_KEY}&traffic=true&travelMode=car`;
      return handleCachedUpstream(request, upstream, 300);
    }

    // 7. Airport Operational Status & Delays (FAA NAS Status XML to Normalized JSON) — 60s Edge Cache
    if (url.pathname.startsWith("/api/airport-status")) {
      const code = (url.searchParams.get("code") || "SEA").toUpperCase();
      const upstream = "https://nasstatus.faa.gov/api/airport-status-information";
      return handleAirportStatus(request, upstream, code, 60);
    }

    // 8. Flight Schedules & Boards (AirLabs API) — 180s Edge Cache
    if (url.pathname.startsWith("/api/flights")) {
      if (!env.AIRLABS_API_KEY) {
        return new Response(JSON.stringify({ error: "Missing AIRLABS_API_KEY" }), { status: 500 });
      }
      const airport = (url.searchParams.get("airport") || "SEA").toUpperCase();
      const type = url.searchParams.get("type") || "departures";
      const paramName = type === "arrivals" ? "arr_iata" : "dep_iata";
      const upstream = `https://airlabs.co/api/v9/schedules?${paramName}=${airport}&api_key=${env.AIRLABS_API_KEY}`;
      return handleCachedUpstream(request, upstream, 180);
    }

    // 9. NOAA Active Emergency & Weather Alerts (Open API) — 60s Edge Cache
    if (url.pathname.startsWith("/api/weather-alerts")) {
      const upstream = "https://api.weather.gov/alerts/active?area=WA";
      return handleCachedUpstream(request, upstream, 60, {
        "User-Agent": "(myseattlesearch.com, api@myseattlesearch.com)"
      });
    }

    // 10. USGS Pacific Northwest Earthquakes (Open API) — 60s Edge Cache
    if (url.pathname.startsWith("/api/earthquakes")) {
      const upstream = "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=2.0&minlatitude=45.5&maxlatitude=49.0&minlongitude=-124.8&maxlongitude=-116.9";
      return handleCachedUpstream(request, upstream, 60);
    }

    // 11. Regional Power Outages (Corrected Seattle City Light ArcGIS Layer) — 180s Edge Cache
    if (url.pathname.startsWith("/api/power-outages")) {
      const upstream = "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/Current_Outages/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=json";
      return handleCachedUpstream(request, upstream, 180);
    }

    // 12. NIFC Pacific Northwest Wildfires (Open ArcGis GeoJSON) — 300s Edge Cache
    if (url.pathname.startsWith("/api/wildfires")) {
      const upstream = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/Current_WildlandFire_Perimeters/FeatureServer/0/query?where=IncidentTypeCategory%3D%27WF%27+AND+POOState%3D%27US-WA%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson";
      return handleCachedUpstream(request, upstream, 300);
    }

    // 13. RainViewer Weather Radar Frames & Metadata — 300s Edge Cache
    if (url.pathname.startsWith("/api/weather-radar")) {
      const upstream = "https://api.rainviewer.com/public/weather-maps.json";
      return handleCachedUpstream(request, upstream, 300);
    }

    // 14. Fallback: Eleventy Static Assets (_site)
    return env.ASSETS.fetch(request);
  }
};

async function handleAirportStatus(request, targetUrl, airportCode, cacheSeconds) {
  const cacheKey = new Request(request.url, request);
  const cache = caches.default;
  let response = await cache.match(cacheKey);

  if (!response) {
    try {
      const upstreamRes = await fetch(targetUrl);
      if (!upstreamRes.ok) {
        return new Response(JSON.stringify({ error: `Upstream error: ${upstreamRes.statusText}` }), {
          status: upstreamRes.status,
          headers: { "Content-Type": "application/json" }
        });
      }

      const xmlText = await upstreamRes.text();
      const isAffected = xmlText.includes(`<ARPT>${airportCode}</ARPT>`);
      let delayType = "Normal Operations";
      let reason = "On Schedule";

      if (isAffected) {
        if (xmlText.includes("Ground Stop") && xmlText.includes(airportCode)) {
          delayType = "Ground Stop";
        } else if (xmlText.includes("Ground Delay") && xmlText.includes(airportCode)) {
          delayType = "Ground Delay";
        } else if (xmlText.includes("Airport Closures") && xmlText.includes(airportCode)) {
          delayType = "Closure";
        } else {
          delayType = "Active Delay";
        }

        const match = xmlText.match(new RegExp(`<ARPT>${airportCode}</ARPT>[\\s\\S]*?<Reason>([^<]+)</Reason>`, "i"));
        if (match && match[1]) {
          reason = match[1].trim();
        }
      }

      const result = {
        airport: airportCode,
        status: isAffected ? "delayed" : "optimal",
        display_status: isAffected ? delayType.toUpperCase() : "NORMAL OPERATIONS",
        reason: reason,
        updated_utc: new Date().toISOString()
      };

      response = new Response(JSON.stringify(result), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": `public, max-age=${cacheSeconds}`,
          "Access-Control-Allow-Origin": "*"
        }
      });
      await cache.put(cacheKey, response.clone());
    } catch (err) {
      return new Response(JSON.stringify({ error: "Gateway connection failed", details: err.message }), {
        status: 502,
        headers: { "Content-Type": "application/json" }
      });
    }
  }

  return response;
}

async function handleCachedUpstream(request, targetUrl, cacheSeconds, extraHeaders = {}) {
  const cacheKey = new Request(request.url, request);
  const cache = caches.default;
  let response = await cache.match(cacheKey);

  if (!response) {
    try {
      const upstreamRes = await fetch(targetUrl, {
        headers: {
          "Accept": "application/json",
          ...extraHeaders
        }
      });

      if (!upstreamRes.ok) {
        const errorBody = await upstreamRes.text();
        return new Response(JSON.stringify({ error: `Upstream error: ${upstreamRes.statusText}`, details: errorBody }), {
          status: upstreamRes.status,
          headers: { "Content-Type": "application/json" }
        });
      }

      const data = await upstreamRes.json();
      response = new Response(JSON.stringify(data), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": `public, max-age=${cacheSeconds}`,
          "Access-Control-Allow-Origin": "*"
        }
      });
      await cache.put(cacheKey, response.clone());
    } catch (err) {
      return new Response(JSON.stringify({ error: "Gateway connection failed", details: err.message }), {
        status: 502,
        headers: { "Content-Type": "application/json" }
      });
    }
  }

  return response;
}

async function handleCachedImageTile(request, targetUrl, cacheSeconds) {
  const cacheKey = new Request(request.url, request);
  const cache = caches.default;
  let response = await cache.match(cacheKey);

  if (!response) {
    try {
      const upstreamRes = await fetch(targetUrl);
      if (!upstreamRes.ok) {
        const errorText = await upstreamRes.text();
        return new Response(JSON.stringify({ error: "Upstream tile error", status: upstreamRes.status, details: errorText }), {
          status: upstreamRes.status,
          headers: { "Content-Type": "application/json" }
        });
      }

      const tileBlob = await upstreamRes.arrayBuffer();
      response = new Response(tileBlob, {
        status: 200,
        headers: {
          "Content-Type": "image/png",
          "Cache-Control": `public, max-age=${cacheSeconds}`,
          "Access-Control-Allow-Origin": "*"
        }
      });
      await cache.put(cacheKey, response.clone());
    } catch (err) {
      return new Response(JSON.stringify({ error: "Tile gateway connection failed", details: err.message }), {
        status: 502,
        headers: { "Content-Type": "application/json" }
      });
    }
  }

  return response;
}