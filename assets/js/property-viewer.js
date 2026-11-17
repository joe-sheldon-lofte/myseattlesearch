/**
 * File: assets/js/property-viewer.js
 * Handles dual-state hydration, residential address/parcel/Near-Me search,
 * live edge GIS utility rendering, Leaflet parcel map, and Inbound Comms Gateway routing.
 */

document.addEventListener("DOMContentLoaded", () => {
  const API_BASE = "https://livedata.myseattlesearch.com/api";
  const COMMS_GATEWAY_URL = "https://commgateway.myseattlesearch.com";

  const els = {
    landing: document.getElementById("viewer-landing-state"),
    populated: document.getElementById("viewer-populated-state"),
    btnBackToSearch: document.getElementById("btn-back-to-search"),
    searchInput: document.getElementById("parcel-search-input"),
    btnSearch: document.getElementById("btn-search-parcel"),
    btnNearMe: document.getElementById("btn-near-me"),
    resultsContainer: document.getElementById("parcel-search-results"),

    // Flags & Condo
    flagsContainer: document.getElementById("prop-flags-container"),
    flagCcr: document.getElementById("flag-ccr"),
    flagTax: document.getElementById("flag-tax"),
    subdivisionSection: document.getElementById("prop-subdivision-data"),
    condoComplexName: document.getElementById("condo-complex-name"),
    fhaBadge: document.getElementById("fha-approval-badge"),
    fhaStatusText: document.getElementById("fha-status-text"),
    vaBadge: document.getElementById("va-approval-badge"),
    vaStatusText: document.getElementById("va-status-text"),

    // Core General Property Info
    typeBadge: document.getElementById("prop-type-badge"),
    address: document.getElementById("prop-address-display"),
    parcelId: document.getElementById("prop-parcel-display"),
    yearBuilt: document.getElementById("prop-year-built"),
    sqft: document.getElementById("prop-sqft"),
    bedsBaths: document.getElementById("prop-beds-baths"),
    lotSize: document.getElementById("prop-lot-size"),
    style: document.getElementById("prop-style"),
    county: document.getElementById("prop-county"),
    primaryPhotoImg: document.getElementById("prop-primary-photo"),
    photoPlaceholder: document.getElementById("prop-photo-placeholder"),

    // Valuation & Neighborhood
    assessedValue: document.getElementById("prop-assessed-value"),
    cityHeading: document.getElementById("prop-city-heading"),
    linkCityHub: document.getElementById("link-city-hub"),
    linkCityRealEstate: document.getElementById("link-city-realestate"),

    // Utilities & Wastewater
    utilElectric: document.getElementById("util-electric"),
    utilElectricMeta: document.getElementById("util-electric-meta"),
    utilWater: document.getElementById("util-water"),
    utilWaterMeta: document.getElementById("util-water-meta"),
    utilGas: document.getElementById("util-gas"),
    utilGasMeta: document.getElementById("util-gas-meta"),
    utilRefuse: document.getElementById("util-refuse"),
    utilRefuseMeta: document.getElementById("util-refuse-meta"),
    utilBroadband: document.getElementById("util-broadband"),
    linkFccMap: document.getElementById("link-fcc-map"),

    wwEmptyBlock: document.getElementById("wastewater-empty-block"),
    sewerBlock: document.getElementById("wastewater-sewer-block"),
    septicBlock: document.getElementById("wastewater-septic-block"),
    wwProvider: document.getElementById("ww-provider"),
    wwProviderMeta: document.getElementById("ww-provider-meta"),
    wwCapacityCharge: document.getElementById("ww-capacity-charge"),
    wwSepticYear: document.getElementById("ww-septic-year"),
    wwSepticInspected: document.getElementById("ww-septic-inspected"),
    btnAsBuilt: document.getElementById("btn-view-asbuilt"),

    // Sketch & History Table
    sketchCard: document.getElementById("prop-sketch-card"),
    sketchImg: document.getElementById("prop-sketch-img"),
    historyTable: document.querySelector("#transaction-history-table tbody"),

    // Form
    inquiryForm: document.getElementById("avm-inquiry-form"),
    btnSubmitInquiry: document.getElementById("btn-submit-inquiry"),
    statusMsg: document.getElementById("inquiry-status-msg")
  };

  let activeMapInstance = null;

  function generateId(length = 20) {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    const bytes = crypto.getRandomValues(new Uint8Array(length));
    let result = "";
    for (let i = 0; i < length; i++) {
      result += chars[bytes[i] % chars.length];
    }
    return result;
  }

  function formatCurrency(num) {
    if (num === null || num === undefined || isNaN(Number(num))) return "--";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0
    }).format(Number(num));
  }

  function formatCityTitle(slug) {
    if (!slug) return "Unincorporated";
    return String(slug)
      .split("-")
      .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : ""))
      .join(" ");
  }

  function renderUtilityMeta(metaEl, utilObj) {
    if (!metaEl) return;
    metaEl.innerHTML = "";
    if (!utilObj) return;

    if (utilObj.phone_number) {
      const a = document.createElement("a");
      a.href = `tel:${utilObj.phone_number.replace(/[^\d+]/g, "")}`;
      a.className = "link-subtle";
      a.textContent = utilObj.phone_number;
      metaEl.appendChild(a);
    }
    if (utilObj.website) {
      const a = document.createElement("a");
      a.href = utilObj.website.startsWith("http") ? utilObj.website : `https://${utilObj.website}`;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.className = "link-subtle";
      a.textContent = "Website ↗";
      metaEl.appendChild(a);
    }
  }

  function showLandingState() {
    els.populated.classList.add("is-hidden");
    els.landing.classList.remove("is-hidden");
    const newUrl = new URL(window.location);
    newUrl.searchParams.delete("parcelid");
    window.history.pushState({}, "", newUrl);
  }

  function selectParcel(parcelNumber) {
    if (!parcelNumber) return;
    const newUrl = new URL(window.location);
    newUrl.searchParams.set("parcelid", parcelNumber);
    window.history.pushState({}, "", newUrl);
    hydrateProperty(parcelNumber);
  }

  function renderSearchResults(rows) {
    if (!els.resultsContainer) return;
    els.resultsContainer.classList.remove("is-hidden");
    els.resultsContainer.innerHTML = "";

    if (!rows || rows.length === 0) {
      els.resultsContainer.innerHTML = `<div class="data-list-item"><span class="text-body-secondary">No matching residential properties found in King or Snohomish County.</span></div>`;
      return;
    }

    rows.forEach((row) => {
      const item = document.createElement("div");
      item.className = "data-list-item";
      const unitStr = row.unit_number ? ` #${row.unit_number}` : "";
      const cityLabel = formatCityTitle(row.neighborhood_slug);
      const addrTitle = row.situs_address ? `${row.situs_address}${unitStr}` : `Parcel ${row.parcel_number}`;

      item.innerHTML = `
        <div class="data-item-left">
          <strong class="text-body-primary">${addrTitle}</strong>
          <span class="text-body-secondary">${cityLabel} ${row.zip_code || ""} &bull; ${row.property_type || "Residential"} &bull; Parcel ${row.parcel_number}</span>
        </div>
        <div class="data-item-right">
          <button type="button" class="link-pill link-pill-primary">View Property</button>
        </div>
      `;
      item.querySelector("button").addEventListener("click", () => selectParcel(row.parcel_number));
      els.resultsContainer.appendChild(item);
    });
  }

  function ensureLeafletAndRenderMap(lat, lon, historicalPhotos) {
    const mapEl = document.getElementById("parcel-map-mount");
    if (!mapEl || typeof lat !== "number" || typeof lon !== "number") return;

    function mountMap() {
      if (activeMapInstance) {
        activeMapInstance.remove();
        activeMapInstance = null;
      }
      mapEl.innerHTML = "";

      const map = L.map("parcel-map-mount", {
        center: [lat, lon],
        zoom: 17,
        scrollWheelZoom: false
      });
      activeMapInstance = map;

      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        attribution: "Esri, Maxar, Earthstar Geographics",
        maxZoom: 19
      }).addTo(map);

      L.circleMarker([lat, lon], {
        radius: 8,
        color: "#FFFFFF",
        weight: 2.5,
        fillColor: "#1E4D6B",
        fillOpacity: 0.95
      })
        .bindPopup("<strong>Subject Property</strong>")
        .addTo(map);

      (historicalPhotos || []).forEach((hp) => {
        if (typeof hp.lat === "number" && typeof hp.lng === "number") {
          L.circleMarker([hp.lat, hp.lng], {
            radius: 6,
            color: "#FFFFFF",
            weight: 1.5,
            fillColor: "#D97706",
            fillOpacity: 0.9
          })
            .bindPopup(`<strong>${hp.title || "Historical Photo"}</strong>${hp.year_photo ? ` (${hp.year_photo})` : ""}`)
            .addTo(map);
        }
      });
    }

    if (typeof L !== "undefined") {
      mountMap();
    } else {
      if (!document.querySelector('link[href*="leaflet.css"]')) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(link);
      }
      const script = document.createElement("script");
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.onload = mountMap;
      document.body.appendChild(script);
    }
  }

  // --- Primary Hydration Engine ---
  async function hydrateProperty(parcelId) {
    els.landing.classList.add("is-hidden");
    els.populated.classList.remove("is-hidden");
    els.parcelId.textContent = `Parcel: ${parcelId}`;
    window.scrollTo({ top: 0, behavior: "smooth" });

    try {
      const res = await fetch(`${API_BASE}/parcel?id=${encodeURIComponent(parcelId)}`);
      if (!res.ok) throw new Error("Property not found.");

      const data = await res.json();
      const base = data.base || {};
      const condo = data.condo || null;
      const wastewater = data.wastewater || {};
      const ccr = data.ccr || null;
      const utils = data.utilities_resolved || {};
      const broadband = data.broadband || {};
      const transactions = data.sales_transactions || [];
      const media = data.parcel_media || [];
      const histPhotos = data.historical_photos || [];

      // 1. Property Flags (CC&Rs)
      let hasAnyFlag = false;
      if (els.flagCcr) {
        const hasCcrRestriction = Boolean(
          ccr && ccr.restriction_status && ccr.restriction_status.toLowerCase() !== "none"
        );
        els.flagCcr.classList.toggle("is-hidden", !hasCcrRestriction);
        if (hasCcrRestriction) hasAnyFlag = true;
      }
      if (els.flagTax) {
        els.flagTax.classList.add("is-hidden");
      }
      if (els.flagsContainer) {
        els.flagsContainer.classList.toggle("is-hidden", !hasAnyFlag);
      }

      // 2. Core Base Metrics
      const cityDisplay = formatCityTitle(base.neighborhood_slug);
      const unitDisplay = base.unit_number ? ` #${base.unit_number}` : "";
      els.typeBadge.textContent = (base.property_type || "RESIDENTIAL").toUpperCase();
      els.address.textContent = base.situs_address
        ? `${base.situs_address}${unitDisplay}, ${cityDisplay} ${base.zip_code || ""}`.trim()
        : `Parcel ${parcelId}`;
      els.yearBuilt.textContent = base.year_built || "--";
      els.sqft.textContent = base.square_footage ? Number(base.square_footage).toLocaleString() : "--";

      const bathsTotal = (Number(base.bath_full) || 0) + (Number(base.bath_half) || 0) * 0.5;
      els.bedsBaths.textContent = `${base.bedrooms || "--"} / ${bathsTotal > 0 ? bathsTotal : "--"}`;
      els.lotSize.textContent = base.lot_sqft ? Number(base.lot_sqft).toLocaleString() : "--";
      els.style.textContent = base.building_style || "--";
      els.county.textContent = base.county ? formatCityTitle(base.county.toLowerCase()) : "--";

      // Single-Frame Photo (R2 Photo -> Source URL -> Inline Vector Placeholder)
      const photoMedia = media.find((m) => m.media_type === "photo") || media[0];
      const sketchMedia = media.find((m) => m.media_type === "sketch");

      if (photoMedia && (photoMedia.r2_key || photoMedia.source_url)) {
        const imgUrl = photoMedia.r2_key
          ? `https://assets.myseattlesearch.com/${photoMedia.r2_key}`
          : photoMedia.source_url;
        els.primaryPhotoImg.onload = () => {
          els.primaryPhotoImg.classList.remove("is-hidden");
          els.photoPlaceholder.classList.add("is-hidden");
        };
        els.primaryPhotoImg.onerror = () => {
          els.primaryPhotoImg.classList.add("is-hidden");
          els.photoPlaceholder.classList.remove("is-hidden");
        };
        els.primaryPhotoImg.src = imgUrl;
      } else {
        els.primaryPhotoImg.classList.add("is-hidden");
        els.photoPlaceholder.classList.remove("is-hidden");
      }

      // 3. Condo Approvals (FHA / VA)
      const isCondo = condo !== null || String(base.property_type || "").toLowerCase().includes("condo");
      if (isCondo) {
        els.subdivisionSection.classList.remove("is-hidden");
        els.condoComplexName.textContent = condo?.name || base.complex_or_plat_name || "Condominium Approvals";
        const fhaOk = Number(condo?.fha_approved ?? base.fha_approved ?? 0) === 1;
        const vaOk = Number(condo?.va_approved ?? base.va_approved ?? 0) === 1;

        els.fhaStatusText.textContent = fhaOk ? "Approved" : "Not Approved";
        els.fhaBadge.classList.toggle("is-optimal", fhaOk);
        els.fhaBadge.classList.toggle("is-alert", !fhaOk);

        els.vaStatusText.textContent = vaOk ? "Approved" : "Not Approved";
        els.vaBadge.classList.toggle("is-optimal", vaOk);
        els.vaBadge.classList.toggle("is-alert", !vaOk);
      } else {
        els.subdivisionSection.classList.add("is-hidden");
      }

      // 4. County Assessed Value
      els.assessedValue.textContent = base.assessed_value_total
        ? formatCurrency(base.assessed_value_total)
        : "Unavailable";

      // 5. Connected Neighborhood Links
      const citySlug = base.neighborhood_slug || "";
      els.cityHeading.textContent = cityDisplay;
      if (citySlug && citySlug !== "unincorporated") {
        els.linkCityHub.href = `/neighborhood/${citySlug}/`;
        els.linkCityRealEstate.href = `/neighborhood/${citySlug}/real-estate/`;
        els.linkCityHub.classList.remove("is-hidden");
        els.linkCityRealEstate.classList.remove("is-hidden");
      } else {
        els.linkCityHub.classList.add("is-hidden");
        els.linkCityRealEstate.classList.add("is-hidden");
      }

      // 6. Live Edge GIS + Utility Directory Bindings
      els.utilElectric.textContent = utils.electric?.normal_name || "--";
      renderUtilityMeta(els.utilElectricMeta, utils.electric);

      els.utilWater.textContent = utils.water?.normal_name || "--";
      renderUtilityMeta(els.utilWaterMeta, utils.water);

      els.utilGas.textContent = utils.gas?.normal_name || "--";
      renderUtilityMeta(els.utilGasMeta, utils.gas);

      els.utilRefuse.textContent = utils.refuse?.normal_name || "--";
      renderUtilityMeta(els.utilRefuseMeta, utils.refuse);

      const ispList = Array.isArray(broadband.providers) ? broadband.providers : [];
      if (ispList.length > 0) {
        const ispNames = ispList
          .map((p) => (typeof p === "string" ? p : p.provider || p.brand_name || ""))
          .filter(Boolean);
        els.utilBroadband.textContent = [...new Set(ispNames)].join(", ");
      } else {
        els.utilBroadband.textContent = "Check FCC Coverage Map";
      }
      if (typeof base.latitude === "number" && typeof base.longitude === "number") {
        els.linkFccMap.href = `https://broadbandmap.fcc.gov/location-summary/fixed?lat=${base.latitude}&lon=${base.longitude}`;
        els.linkFccMap.classList.remove("is-hidden");
      } else {
        els.linkFccMap.classList.add("is-hidden");
      }

      // 7. Wastewater Parsing (Mutually Exclusive Panels)
      const wwType = String(wastewater.service_type || "").toUpperCase();
      if (wwType === "SEWER") {
        els.wwEmptyBlock.classList.add("is-hidden");
        els.septicBlock.classList.add("is-hidden");
        els.sewerBlock.classList.remove("is-hidden");
        els.wwProvider.textContent = utils.sewer?.normal_name || wastewater.sewer_provider_name || "--";
        renderUtilityMeta(els.wwProviderMeta, utils.sewer);
        els.wwCapacityCharge.classList.toggle("is-hidden", Number(wastewater.has_capacity_charge || 0) !== 1);
      } else if (wwType === "SEPTIC") {
        els.wwEmptyBlock.classList.add("is-hidden");
        els.sewerBlock.classList.add("is-hidden");
        els.septicBlock.classList.remove("is-hidden");
        els.wwSepticYear.textContent = wastewater.installed_year || "--";
        els.wwSepticInspected.textContent = wastewater.last_inspection_date || "--";
        if (Number(wastewater.has_asbuilt || 0) === 1 && wastewater.online_rme_id) {
          els.btnAsBuilt.classList.remove("is-hidden");
          els.btnAsBuilt.href = "https://kingcounty.gov/depts/health/environmental-health/piping/onsite-sewage-systems.aspx";
        } else {
          els.btnAsBuilt.classList.add("is-hidden");
        }
      } else {
        els.sewerBlock.classList.add("is-hidden");
        els.septicBlock.classList.add("is-hidden");
        els.wwEmptyBlock.classList.remove("is-hidden");
      }

      // 8. Building Dimension Sketch
      if (sketchMedia && (sketchMedia.r2_key || sketchMedia.source_url)) {
        els.sketchImg.src = sketchMedia.r2_key
          ? `https://assets.myseattlesearch.com/${sketchMedia.r2_key}`
          : sketchMedia.source_url;
        els.sketchCard.classList.remove("is-hidden");
      } else {
        els.sketchCard.classList.add("is-hidden");
      }

      // 9. Sales History Table
      els.historyTable.innerHTML = "";
      if (transactions.length > 0) {
        transactions.forEach((tx) => {
          const tr = document.createElement("tr");
          const partyText = [tx.buyer_name, tx.seller_name].filter(Boolean).join(" / ") || "--";
          tr.innerHTML = `
            <td>${tx.document_date || "--"}</td>
            <td>${tx.deed_type || "Transfer"}</td>
            <td>${formatCurrency(tx.sale_price)}</td>
            <td>${partyText}</td>
          `;
          els.historyTable.appendChild(tr);
        });
      } else {
        els.historyTable.innerHTML = `<tr><td colspan="4" class="table-cell-center">No recent recorded transactions found.</td></tr>`;
      }

      // 10. Render Parcel Satellite Map
      ensureLeafletAndRenderMap(base.latitude, base.longitude, histPhotos);
    } catch (err) {
      console.error(err);
      els.address.textContent = "Property Record Not Found";
    }
  }

  // --- Search & Near Me Handlers ---
  async function executeSearch(rawQuery) {
    const query = String(rawQuery || "").trim();
    if (!query) return;

    const cleanDigits = query.replace(/\D/g, "");
    if (/^\d{10,12}$/.test(cleanDigits)) {
      selectParcel(cleanDigits);
      return;
    }

    els.btnSearch.disabled = true;
    els.btnSearch.textContent = "Searching...";

    try {
      const res = await fetch(`${API_BASE}/parcel/search?q=${encodeURIComponent(query)}`);
      const data = res.ok ? await res.json() : { results: [] };
      const rows = data.results || [];
      if (rows.length === 1) {
        selectParcel(rows[0].parcel_number);
      } else {
        renderSearchResults(rows);
      }
    } catch (err) {
      console.error("Parcel search failed:", err);
      renderSearchResults([]);
    } finally {
      els.btnSearch.disabled = false;
      els.btnSearch.textContent = "Search";
    }
  }

  els.btnSearch.addEventListener("click", () => executeSearch(els.searchInput.value));
  els.searchInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") executeSearch(els.searchInput.value);
  });

  if (els.btnBackToSearch) {
    els.btnBackToSearch.addEventListener("click", showLandingState);
  }

  els.btnNearMe.addEventListener("click", () => {
    if (!navigator.geolocation) {
      renderSearchResults([]);
      return;
    }
    els.btnNearMe.disabled = true;
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const { latitude, longitude } = pos.coords;
          const res = await fetch(`${API_BASE}/parcel/search?lat=${latitude}&lon=${longitude}`);
          const data = res.ok ? await res.json() : { results: [] };
          renderSearchResults(data.results || []);
        } catch {
          renderSearchResults([]);
        } finally {
          els.btnNearMe.disabled = false;
        }
      },
      () => {
        els.btnNearMe.disabled = false;
        renderSearchResults([]);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  });

  window.addEventListener("popstate", () => {
    const p = new URLSearchParams(window.location.search).get("parcelid");
    if (p) {
      hydrateProperty(p);
    } else {
      els.populated.classList.add("is-hidden");
      els.landing.classList.remove("is-hidden");
    }
  });

  // --- Initial Boot ---
  const initialParcel = new URLSearchParams(window.location.search).get("parcelid");
  if (initialParcel) {
    hydrateProperty(initialParcel);
  }

  // --- Inbound Comms Gateway Dispatch ("avm-inquiry" / "cam-request") ---
  if (els.inquiryForm) {
    els.inquiryForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      els.btnSubmitInquiry.disabled = true;
      els.btnSubmitInquiry.textContent = "Sending...";
      els.statusMsg.textContent = "";
      els.statusMsg.className = "text-body-secondary pv-status-text";

      const inquiryType = document.querySelector('input[name="inquiry_type"]:checked')?.value || "avm-inquiry";
      const fName = document.getElementById("inq-first-name").value.trim();
      const lName = document.getElementById("inq-last-name").value.trim();
      const email = document.getElementById("inq-email").value.trim();
      const phone = document.getElementById("inq-phone").value.trim();
      const notes = document.getElementById("inq-notes").value.trim();
      const activeParcelId = new URLSearchParams(window.location.search).get("parcelid") || "Unknown";

      const payload = {
        sheetName: "Inbound",
        rowData: [
          generateId(),
          inquiryType,
          fName,
          lName,
          email,
          phone,
          `Parcel: ${activeParcelId} | Notes: ${notes}`
        ],
        emailData: {
          to: "joe@myseattlesearch.com",
          subject: `Property Viewer: ${inquiryType === "cam-request" ? "Manual CMA Request" : "AVM Inquiry"}`,
          body: `Client: ${fName} ${lName}<br>Email: ${email}<br>Phone: ${phone}<br>Parcel: ${activeParcelId}<br>Source: ${inquiryType}<br>Notes: ${notes}`
        }
      };

      try {
        const req = await fetch(COMMS_GATEWAY_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!req.ok) throw new Error("Gateway rejected request.");

        els.inquiryForm.reset();
        els.statusMsg.classList.add("is-success");
        els.statusMsg.textContent = "Your request was received by Operations.";
      } catch {
        els.statusMsg.classList.add("is-error");
        els.statusMsg.textContent = "Failed to submit request. Please try again.";
      } finally {
        els.btnSubmitInquiry.disabled = false;
        els.btnSubmitInquiry.textContent = "Submit to Operations";
      }
    });
  }
});
