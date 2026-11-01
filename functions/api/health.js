export async function onRequestGet() {
  return new Response(
    JSON.stringify({
      status: "live",
      timestamp_utc: new Date().toISOString(),
      service: "edge-gateway-active"
    }),
    {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store"
      }
    }
  );
}