module.exports = async function () {
  try {
    const res = await fetch("https://assets.myseattlesearch.com/telemetry/active_alerts.json");
    if (!res.ok) return {};
    return await res.json();
  } catch (err) {
    return {};
  }
};