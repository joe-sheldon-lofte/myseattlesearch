export function initializeQuizTrack(instance) {
    instance.renderQuestion = function() {
        if (this.currentStep >= this.quizData.questions.length) {
            processCalculationsAndSubmit(this);
            return;
        }

        const qObj = this.quizData.questions[this.currentStep];
        const pct = Math.round((this.currentStep / this.quizData.questions.length) * 100);
        this.currentSelection = this.answers[this.currentStep] || null;

        // Extract options from the text column block using single pipes
        const choices = qObj.bucket.split('|').map(c => c.trim());

        this.innerHTML = `
            <style>
                .t-btn { text-align: left; padding: 1rem; border: 1px solid var(--premier-beige); background: white; border-radius: 8px; cursor: pointer; transition: 0.2s; font-size: 0.98rem; font-weight: 500; color: var(--premier-charcoal); }
                .t-btn:hover { border-color: var(--card-accent-color); background: var(--dynamic-bg-highlight); }
                .t-btn.active { background: var(--card-accent-color) !important; color: white !important; border-color: var(--card-accent-color) !important; }
                .nav-btn { padding: 0.6rem 1.5rem; font-size: 0.9rem; font-weight: bold; border-radius: 6px; cursor: pointer; }
                .nav-btn:disabled { opacity: 0.3; cursor: not-allowed; }
            </style>
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background: white; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); border-top:6px solid var(--card-accent-color); min-height:380px; display:flex; flex-direction:column; justify-content:space-between; box-sizing:border-box;">
                <div>
                    <div style="width:100%; background: var(--premier-beige); height:6px; border-radius:3px; margin-bottom:2rem; overflow:hidden;"><div style="width:${pct}%; background: var(--card-accent-color); height:100%;"></div></div>
                    <div style="font-size:0.8rem; font-weight:800; color: var(--card-accent-color); text-transform:uppercase; text-align:center; margin-bottom:0.5rem;">Question ${this.currentStep + 1} of ${this.quizData.questions.length}</div>
                    <h3 style="color: var(--premier-charcoal); margin-bottom:1.5rem; font-size:1.25rem; line-height:1.4;">${qObj.text}</h3>
                    <div style="display:flex; flex-direction:column; gap:12px;">
                        ${choices.map((choice, index) => {
                            const pointsMatch = choice.match(/\[(\d+)\]/);
                            const points = pointsMatch ? parseInt(pointsMatch[1]) : 0;
                            const clearText = choice.replace(/\[\d+\]/, '').trim();
                            const isActive = this.currentSelection && this.currentSelection.index === index ? 'active' : '';
                            return `<button type="button" class="t-btn ${isActive}" data-index="${index}" data-points="${points}" data-text="${clearText}">${clearText}</button>`;
                        }).join('')}
                    </div>
                </div>
                <div style="display:flex; justify-content:space-between; border-top:1px solid var(--premier-beige); padding-top:1.25rem; margin-top:1rem;">
                    <button type="button" id="q-back" class="btn btn-secondary nav-btn" style="background-color: white; border-color: var(--premier-beige); color: var(--premier-charcoal);" ${this.currentStep === 0 ? 'disabled' : ''}>Back</button>
                    <button type="button" id="q-next" class="btn btn-primary nav-btn" style="background-color: var(--card-accent-color); border-color: var(--card-accent-color); color: white;" ${this.currentSelection === null ? 'disabled' : ''}>Next</button>
                </div>
            </div>`;

        this.querySelectorAll('.t-btn').forEach(b => b.addEventListener('click', () => {
            this.querySelectorAll('.t-btn').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            this.currentSelection = {
                index: parseInt(b.getAttribute('data-index')),
                points: parseInt(b.getAttribute('data-points')),
                text: b.getAttribute('data-text')
            };
            this.querySelector('#q-next').removeAttribute('disabled');
        }));

        this.querySelector('#q-next').addEventListener('click', () => {
            this.answers[this.currentStep] = this.currentSelection;
            this.currentStep++;
            this.renderQuestion();
        });
        this.querySelector('#q-back').addEventListener('click', () => {
            this.currentStep--;
            this.renderQuestion();
        });
    };
    instance.renderQuestion();
}

async function processCalculationsAndSubmit(instance) {
    instance.innerHTML = `<div style="text-align:center; padding:4rem;"><h3 style="color: var(--card-accent-color);">Calculating Score Metrics...</h3></div>`;
    let grandTotal = 0;
    instance.answers.forEach(ans => { grandTotal += (ans.points || 0); });

    let match = instance.quizData.routing[0];
    let matchedKey = '0-0';
    for (const route of instance.quizData.routing) {
        const ranges = route.key.split('-');
        const min = parseInt(ranges[0]);
        const max = parseInt(ranges[1]);
        if (grandTotal >= min && grandTotal <= max) {
            match = route;
            matchedKey = route.key;
            break;
        }
    }

    const formattedHistoryAnswers = instance.quizData.questions.map((q, idx) => {
        const choice = instance.answers[idx];
        return `${choice.text} [${choice.points}]`;
    });

    // 1. Establish localized Pacific Time Zone values for spreadsheet tracking
    const timestamp = new Date().toLocaleString("en-US", { timeZone: "America/Los_Angeles" });

    // 2. Flatten data into a chronological array conforming row-by-row with your sheet columns
    const rowData = [
        timestamp,
        instance.quizData.id,
        instance.quizData.name || instance.quizData.webTitle || "",
        instance.leadInfo.firstName || "",
        instance.leadInfo.lastName || "",
        instance.leadInfo.email || "",
        instance.leadInfo.phone || "",
        matchedKey,
        match.heading,
        grandTotal,
        JSON.stringify(formattedHistoryAnswers)
    ];

    // 3. Construct the clean payload structure required by your Cloudflare edge firewall
    const payload = {
        quizId: instance.quizData.id,
        rowData: rowData
    };

    // 4. Hardcoded edge worker gateway URL
    const workerGatewayUrl = "https://myseattlesearch-quiz-gateway.joe-54b.workers.dev/";

    // 5. Fire rapid background transmission bypassing live-site cross-origin locks
    try {
        fetch(workerGatewayUrl, { 
            method: 'POST', 
            mode: 'no-cors',
            headers: { 'Content-Type': 'application/json' }, 
            body: JSON.stringify(payload) 
        });
    } catch (e) {
        console.error("🔒 Gateway Bypass Active", e);
    }

    const link = match.url.includes('?') ? `${match.url}&` : `${match.url}?`;
    setTimeout(() => {
        window.location.href = `${link}quizId=${instance.quizData.id}&result=${matchedKey}&name=${encodeURIComponent(instance.leadInfo.firstName)}`;
    }, 600);
}