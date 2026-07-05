/* File: /quizzes/engines/score_tally.js */

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
                .t-btn { text-align:left; padding:1rem; border:1px solid #ddd; background:#fff; border-radius:8px; cursor:pointer; transition:0.2s; font-size:0.98rem; font-weight:500; color:#222; }
                .t-btn:hover { border-color: var(--redfin-red); background:#fff5f5; }
                .t-btn.active { background:var(--redfin-red)!important; color:#fff!important; border-color:var(--redfin-red)!important; }
                .nav-btn { padding: 0.6rem 1.5rem; font-size: 0.9rem; font-weight: bold; border-radius: 6px; cursor: pointer; }
                .nav-btn:disabled { opacity: 0.3; cursor: not-allowed; }
            </style>
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background:#fff; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); border-top:6px solid var(--redfin-red); min-height:380px; display:flex; flex-direction:column; justify-content:space-between; box-sizing:border-box;">
                <div>
                    <div style="width:100%; background:#eee; height:6px; border-radius:3px; margin-bottom:2rem; overflow:hidden;"><div style="width:${pct}%; background:var(--redfin-red); height:100%;"></div></div>
                    <div style="font-size:0.8rem; font-weight:800; color:var(--redfin-red); text-transform:uppercase; text-align:center; margin-bottom:0.5rem;">Question ${this.currentStep + 1} of ${this.quizData.questions.length}</div>
                    <h3 style="color:#222; margin-bottom:1.5rem; font-size:1.25rem; line-height:1.4;">${qObj.text}</h3>
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
                <div style="display:flex; justify-content:space-between; border-top:1px solid #f0f0f0; padding-top:1.25rem; margin-top:1rem;">
                    <button type="button" id="q-back" class="btn btn-secondary nav-btn" ${this.currentStep === 0 ? 'disabled' : ''}>Back</button>
                    <button type="button" id="q-next" class="btn btn-primary nav-btn" ${this.currentSelection === null ? 'disabled' : ''}>Next</button>
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
    instance.innerHTML = `<div style="text-align:center; padding:4rem;"><h3 style="color:var(--redfin-red);">Calculating Score Metrics...</h3></div>`;
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

    const payload = {
        quizId: instance.quizData.id, firstName: instance.leadInfo.firstName, lastName: instance.leadInfo.lastName,
        email: instance.leadInfo.email, phone: instance.leadInfo.phone, outcomeKey: matchedKey, finalOutcome: match.heading,
        totalTallyScore: grandTotal, scores: {}, answers: formattedHistoryAnswers
    };

    try {
        fetch(instance.quizData.webhookUrl, { method: 'POST', mode: 'no-cors', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    } catch (e) {}

    const link = match.url.includes('?') ? `${match.url}&` : `${match.url}?`;
    setTimeout(() => {
        window.location.href = `${link}quizId=${instance.quizData.id}&result=${matchedKey}&name=${encodeURIComponent(instance.leadInfo.firstName)}`;
    }, 600);
}