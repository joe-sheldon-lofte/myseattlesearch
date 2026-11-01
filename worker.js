export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 1. Health Verification & Secret Check
    if (url.pathname === "/api/health") {
      return new Response(
        JSON.stringify({
          status: "healthy",
          environment: env.ENVIRONMENT || "production",
          timestamp: new Date().toISOString(),
          keys_loaded: {
            wsdot: Boolean(env.WSDOT_ACCESS_CODE),
            onebusaway: Boolean(env.ONEBUSAWAY_API_KEY)
          }
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }
        }
      );
    }

    // 2. WSDOT Toll Rates (SR-520, I-405, SR-99) — 30s Edge Cache
    if (url.pathname.startsWith("/api/tolls")) {
      if (!env.WSDOT_ACCESS_CODE) {
        return new Response(JSON.stringify({ error: "Missing WSDOT_ACCESS_CODE" }), { status: 500 });
      }
      const upstream = `https://wsdot.wa.gov/Traffic/api/api/tollrates?AccessCode=${env.WSDOT_ACCESS_CODE}`;
      return handleCachedUpstream(request, upstream, 30);
    }

    // 3. WSDOT Ferries (Terminals & Vessel Status) — 60s Edge Cache
    if (url.pathname.startsWith("/api/ferries")) {
      if (!env.WSDOT_ACCESS_CODE) {
        return new Response(JSON.stringify({ error: "Missing WSDOT_ACCESS_CODE" }), { status: 500 });
      }
      const endpoint = url.searchParams.get("endpoint") || "terminals";
      const upstream = `https://wsdot.wa.gov/ferries/api/${endpoint}/rest/v1/?AccessCode=${env.WSDOT_ACCESS_CODE}`;
      return handleCachedUpstream(request, upstream, 60);
    }

    // 4. OneBusAway Transit (Puget Sound Bus, Light Rail, Sounder) — 30s Edge Cache
    if (url.pathname.startsWith("/api/transit")) {
      if (!env.ONEBUSAWAY_API_KEY) {
        return new Response(JSON.stringify({ error: "Missing ONEBUSAWAY_API_KEY" }), { status: 500 });
      }
      const stopId = url.searchParams.get("stopId") || "1_29261";
      const upstream = `https://api.pugetsound.onebusaway.org/api/where/arrivals-and-departures-for-stop/${stopId}.json?key=${env.ONEBUSAWAY_API_KEY}`;
      return handleCachedUpstream(request, upstream, 30);
    }

    // 5. NOAA Active Weather Alerts (Open API, User-Agent Required) — 60s Edge Cache
    if (url.pathname.startsWith("/api/weather-alerts")) {
      const upstream = "https://api.weather.gov/alerts/active?area=WA";
      return handleCachedUpstream(request, upstream, 60, {
        "User-Agent": "(myseattlesearch.com, api@myseattlesearch.com)"
      });
    }

    // 6. USGS Pacific Northwest Earthquakes (Open API) — 60s Edge Cache
    if (url.pathname.startsWith("/api/earthquakes")) {
      // M2.5+ earthquakes in the last 7 days across PNW bounding box
      const upstream = "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=2.5&minlatitude=45.5&maxlatitude=49.0&minlongitude=-124.8&maxlongitude=-116.9";
      return handleCachedUpstream(request, upstream, 60);
    }

    // Fallback: Serve static HTML/CSS files from Eleventy (_site)
    return env.ASSETS.fetch(request);
  }
};

/**
 * Demand-driven edge cache handler.
 * Does not make upstream calls unless a user hits the endpoint and the cache is cold.
 */
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
        return new Response(JSON.stringify({ error: `Upstream error: ${upstreamRes.statusText}` }), {
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