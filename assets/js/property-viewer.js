/**
 * File: assets/js/property-viewer.js
 * Handles dual-state hydration, address/parcel/Near-Me search, map initialization,
 * and Inbound Comms Gateway routing for the Canonical Property Viewer.
 */

document.addEventListener("DOMContentLoaded", () => {
  const API_BASE = "https://livedata.myseattlesearch.com/api";
  const COMMS_GATEWAY_URL = "https://commgateway.myseattlesearch.com";

  const els = {
    landing: document.getElementById("viewer-landing-state"),
    populated: document.getElementById("viewer-populated-state"),
    searchWrap: document.querySelector(".property-viewer-search-wrap"),
    searchInput: document.getElementById("parcel-search-input"),
    btnSearch: document.getElementById("btn-search-parcel"),
    btnNearMe: document.getElementById("btn-near-me"),

    // Flags & Condo
    flagsContainer: document.getElementById("prop-flags-container"),
    flagCcr: document.getElementById("flag-ccr"),
    flagTax: document.getElementById("flag-tax"),
    subdivisionSection: document.getElementById("prop-subdivision-data"),
    fhaBadge: document.getElementById("fha-approval-badge"),
    fhaStatusText: document.getElementById("fha-status-text"),
    vaBadge: document.getElementById("va-approval-badge"),
    vaStatusText: document.getElementById("va-status-text"),

    // Hydration Targets
    address: document.getElementById("prop-address-display"),
    parcelId: document.getElementById("prop-parcel-display"),
    yearBuilt: document.getElementById("prop-year-built"),
    sqft: document.getElementById("prop-sqft"),
    bedsBaths: document.getElementById("prop-beds-baths"),
    lotSize: document.getElementById("prop-lot-size"),
    primaryPhotoImg: document.querySelector("#prop-primary-photo-viewport .viewport-primary-image"),
    primaryPhotoBackdrop: document.querySelector("#prop-primary-photo-viewport .viewport-slide-backdrop"),
    avmValue: document.getElementById("prop-avm-value"),

    // Utilities & Wastewater
    utilElectric: document.getElementById("util-electric"),
    utilWater: document.getElementById("util-water"),
    utilGas: document.getElementById("util-gas"),
    utilRefuse: document.getElementById("util-refuse"),
    sewerBlock: document.getElementById("wastewater-sewer-block"),
    septicBlock: document.getElementById("wastewater-septic-block"),
    wwProvider: document.getElementById("ww-provider"),
    wwCapacityCharge: document.getElementById("ww-capacity-charge"),
    wwSepticYear: document.getElementById("ww-septic-year"),
    wwSepticInspected: document.getElementById("ww-septic-inspected"),
    btnAsBuilt: document.getElementById("btn-view-asbuilt"),

    // History Table
    historyTable: document.querySelector("#transaction-history-table tbody"),

    // Form
    inquiryForm: document.getElementById("avm-inquiry-form"),
    btnSubmitInquiry: document.getElementById("btn-submit-inquiry"),
    statusMsg: document.getElementById("inquiry-status-msg")
  };

  let resultsContainer = document.getElementById("parcel-search-results");
  if (!resultsContainer && els.searchWrap && els.searchWrap.parentNode) {
    resultsContainer = document.createElement("div");
    resultsContainer.id = "parcel-search-results";
    resultsContainer.className = "data-list";
    els.searchWrap.parentNode.appendChild(resultsContainer);
  }

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
    if (num === null || num === undefined || isNaN(num)) return "--";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0
    }).format(num);
  }

  function selectParcel(parcelNumber) {
    if (!parcelNumber) return;
    const newUrl = new URL(window.location);
    newUrl.searchParams.set("parcelid", parcelNumber);
    window.history.pushState({}, "", newUrl);
    hydrateProperty(parcelNumber);
  }

  function renderSearchResults(rows) {
    if (!resultsContainer) return;
    resultsContainer.innerHTML = "";
    if (!rows || rows.length === 0) {
      resultsContainer.innerHTML = `<div class="data-list-item"><span class="text-body-secondary">No matching parcels found in King or Snohomish County.</span></div>`;
      return;
    }

    rows.forEach((row) => {
      const item = document.createElement("div");
      item.className = "data-list-item";
      const unitStr = row.unit_number ? ` Unit ${row.unit_number}` : "";
      const cityLabel = (row.neighborhood_slug || "").replace(/-/g, " ").toUpperCase();
      const addrTitle = row.situs_address ? `${row.situs_address}${unitStr}` : `Parcel ${row.parcel_number}`;

      item.innerHTML = `
        <div class="data-item-left">
          <strong class="text-body-primary">${addrTitle}</strong>
          <span class="text-body-secondary">${cityLabel} ${row.zip_code || ""} &bull; Parcel ${row.parcel_number}</span>
        </div>
        <div class="data-item-right">
          <button type="button" class="link-pill link-pill-primary">View Property</button>
        </div>
      `;
      item.querySelector("button").addEventListener("click", () => selectParcel(row.parcel_number));
      resultsContainer.appendChild(item);
    });
  }

  // --- Hydration Engine ---
  async function hydrateProperty(parcelId) {
    els.landing.classList.add("is-hidden");
    els.populated.classList.remove("is-hidden");
    els.parcelId.textContent = `Parcel: ${parcelId}`;

    try {
      const res = await fetch(`${API_BASE}/parcel?id=${encodeURIComponent(parcelId)}`);
      if (!res.ok) throw new Error("Property not found.");

      const data = await res.json();
      const base = data.base || {};
      const condo = data.condo || null;
      const wastewater = data.wastewater || {};
      const ccr = data.ccr || null;
      const utils = data.utilities_resolved || {};
      const transactions = data.sales_transactions || [];
      const media = data.parcel_media || [];

      // 1. Property Flags (CC&Rs)
      let hasAnyFlag = false;
      if (els.flagCcr) {
        const hasCcrRestriction = Boolean(ccr && ccr.restriction_status && ccr.restriction_status.toLowerCase() !== "none");
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
      const cityDisplay = (base.neighborhood_slug || "").replace(/-/g, " ").toUpperCase();
      const unitDisplay = base.unit_number ? ` #${base.unit_number}` : "";
      els.address.textContent = base.situs_address
        ? `${base.situs_address}${unitDisplay}, ${cityDisplay} ${base.zip_code || ""}`.trim()
        : `Parcel ${parcelId}`;
      els.yearBuilt.textContent = base.year_built || "--";
      els.sqft.textContent = base.square_footage ? Number(base.square_footage).toLocaleString() : "--";

      const bathsTotal = (base.bath_full || 0) + (base.bath_half ? base.bath_half * 0.5 : 0);
      els.bedsBaths.textContent = `${base.bedrooms || "--"} / ${bathsTotal > 0 ? bathsTotal : "--"}`;
      els.lotSize.textContent = base.lot_sqft ? Number(base.lot_sqft).toLocaleString() : "--";

      // Single-Frame Property Photo (R2 Primary -> Source URL -> Placeholder SVG)
      let targetImgUrl = "/assets/graphics/placeholder-home.svg";
      if (media.length > 0) {
        targetImgUrl = media[0].r2_key
          ? `https://assets.myseattlesearch.com/${media[0].r2_key}`
          : (media[0].source_url || targetImgUrl);
      }
      if (els.primaryPhotoImg) els.primaryPhotoImg.src = targetImgUrl;
      if (els.primaryPhotoBackdrop) els.primaryPhotoBackdrop.src = targetImgUrl;

      // 3. Condo Approvals (FHA / VA)
      if (els.subdivisionSection) {
        const isCondo = condo !== null || String(base.property_type || "").toLowerCase().includes("condo");
        if (isCondo) {
          els.subdivisionSection.classList.remove("is-hidden");
          const fhaOk = Number(condo?.fha_approved ?? base.fha_approved ?? 0) === 1;
          const vaOk = Number(condo?.va_approved ?? base.va_approved ?? 0) === 1;

          if (els.fhaStatusText) els.fhaStatusText.textContent = fhaOk ? "Approved" : "Not Approved";
          if (els.fhaBadge) {
            els.fhaBadge.classList.toggle("is-optimal", fhaOk);
            els.fhaBadge.classList.toggle("is-alert", !fhaOk);
          }
          if (els.vaStatusText) els.vaStatusText.textContent = vaOk ? "Approved" : "Not Approved";
          if (els.vaBadge) {
            els.vaBadge.classList.toggle("is-optimal", vaOk);
            els.vaBadge.classList.toggle("is-alert", !vaOk);
          }
        } else {
          els.subdivisionSection.classList.add("is-hidden");
        }
      }

      // 4. AVM Value Estimate
      els.avmValue.textContent = base.assessed_value_total
        ? formatCurrency(Math.round(base.assessed_value_total * 1.15))
        : "Est. Unavailable";

      // 5. Utility Directory Bindings (Resolved Normal Names)
      els.utilElectric.textContent = utils.electric?.normal_name || base.electric_utility_code || "--";
      els.utilWater.textContent = utils.water?.normal_name || base.water_district_name || "--";
      els.utilGas.textContent = utils.gas?.normal_name || base.natural_gas_provider || "--";
      els.utilRefuse.textContent = utils.refuse?.normal_name || base.refuse_provider_name || "--";

      // 6. Wastewater Parsing
      const wwType = String(wastewater.service_type || "").toUpperCase();
      if (wwType === "SEWER") {
        els.septicBlock.classList.add("is-hidden");
        els.sewerBlock.classList.remove("is-hidden");
        els.wwProvider.textContent = utils.sewer?.normal_name || wastewater.sewer_provider_name || base.sewer_provider_name || "--";
        if (els.wwCapacityCharge) {
          els.wwCapacityCharge.classList.toggle("is-hidden", Number(wastewater.has_capacity_charge || 0) !== 1);
        }
      } else if (wwType === "SEPTIC") {
        els.sewerBlock.classList.add("is-hidden");
        els.septicBlock.classList.remove("is-hidden");
        els.wwSepticYear.textContent = wastewater.installed_year || "--";
        els.wwSepticInspected.textContent = wastewater.last_inspection_date || "--";
        if (els.btnAsBuilt) {
          if (Number(wastewater.has_asbuilt || 0) === 1 && wastewater.online_rme_id) {
            els.btnAsBuilt.classList.remove("is-hidden");
            els.btnAsBuilt.href = "https://kingcounty.gov/depts/health/environmental-health/piping/onsite-sewage-systems.aspx";
            els.btnAsBuilt.target = "_blank";
            els.btnAsBuilt.rel = "noopener noreferrer";
          } else {
            els.btnAsBuilt.classList.add("is-hidden");
          }
        }
      } else {
        els.sewerBlock.classList.add("is-hidden");
        els.septicBlock.classList.add("is-hidden");
      }

      // 7. Sales History Table
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
        els.historyTable.innerHTML = `<tr><td colspan="4" class="table-cell-center">No recent transactions found.</td></tr>`;
      }

      // 8. Initialize Parcel Map
      const mapEl = document.getElementById("parcel-map-mount");
      if (mapEl && base.latitude && base.longitude && typeof L !== "undefined") {
        mapEl.innerHTML = "";
        const map = L.map("parcel-map-mount", {
          center: [base.latitude, base.longitude],
          zoom: 17,
          scrollWheelZoom: false
        });
        L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
          attribution: "Esri, Maxar, Earthstar Geographics",
          maxZoom: 19
        }).addTo(map);
        L.circleMarker([base.latitude, base.longitude], {
          radius: 8,
          color: "#FFFFFF",
          weight: 2,
          fillColor: "#1E4D6B",
          fillOpacity: 0.95
        }).addTo(map);
      }
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

    if (els.btnSearch) {
      els.btnSearch.disabled = true;
      els.btnSearch.textContent = "Searching...";
    }

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
      if (els.btnSearch) {
        els.btnSearch.disabled = false;
        els.btnSearch.textContent = "Search";
      }
    }
  }

  if (els.btnSearch) {
    els.btnSearch.addEventListener("click", () => executeSearch(els.searchInput.value));
  }
  if (els.searchInput) {
    els.searchInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") executeSearch(els.searchInput.value);
    });
  }

  if (els.btnNearMe) {
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
  }

  // --- Initial Boot ---
  const urlParams = new URLSearchParams(window.location.search);
  const requestedParcel = urlParams.get("parcelid");
  if (requestedParcel) {
    hydrateProperty(requestedParcel);
  }

  // --- Inbound Form Dispatch (AVM / CMA Request) ---
  if (els.inquiryForm) {
    els.inquiryForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      els.btnSubmitInquiry.disabled = true;
      els.btnSubmitInquiry.textContent = "Sending...";
      els.statusMsg.textContent = "";

      const inquiryType = document.querySelector('input[name="inquiry_type"]:checked')?.value || "avm-inquiry";
      const fName = document.getElementById("inq-first-name").value.trim();
      const lName = document.getElementById("inq-last-name").value.trim();
      const email = document.getElementById("inq-email").value.trim();
      const phone = document.getElementById("inq-phone").value.trim();
      const notes = document.getElementById("inq-notes").value.trim();
      const currentParams = new URLSearchParams(window.location.search);
      const activeParcelId = currentParams.get("parcelid") || "Unknown";

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
          subject: `Property Viewer: ${inquiryType === "cma-request" ? "Manual CMA Request" : "AVM Flag"}`,
          body: `Client: ${fName} ${lName}<br>Email: ${email}<br>Phone: ${phone}<br>Parcel: ${activeParcelId}<br>Notes: ${notes}`
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
        els.statusMsg.textContent = "Your request was received by Operations.";
      } catch (err) {
        els.statusMsg.textContent = "Failed to submit request. Please try again.";
      } finally {
        els.btnSubmitInquiry.disabled = false;
        els.btnSubmitInquiry.textContent = "Submit to Operations";
      }
    });
  }
});
