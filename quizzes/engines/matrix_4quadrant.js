/* File: /quizzes/engines/matrix_4quadrant.js */

export function initializeQuizTrack(instance) {
    instance.renderQuestion = function() {
        if (this.currentStep >= this.quizData.questions.length) {
            processCalculationsAndSubmit(this);
            return;
        }

        const qObj = this.quizData.questions[this.currentStep];
        const pct = Math.round((this.currentStep / this.quizData.questions.length) * 100);
        this.currentSelection = this.answers[this.currentStep] || null;

        this.innerHTML = `
            <style>
                .m-grid {
                    display: grid !important;
                    grid-template-columns: repeat(10, 1fr) !important;
                    gap: 6px !important;
                    width: 100% !important;
                    margin: 1.5rem 0 !important;
                    box-sizing: border-box !important;
                }
                .m-btn { 
                    padding: 0.6rem 0 !important; 
                    border: 2px solid var(--premier-beige) !important; 
                    background: white !important; 
                    font-weight: bold !important; 
                    border-radius: 6px !important; 
                    cursor: pointer !important; 
                    transition: 0.2s !important; 
                    color: var(--premier-charcoal) !important;
                    text-align: center !important;
                    box-sizing: border-box !important;
                }
                .m-btn:hover { 
                    border-color: var(--card-accent-color) !important; 
                    background: var(--dynamic-bg-highlight) !important; 
                }
                .m-btn.active { 
                    background: var(--card-accent-color) !important; 
                    color: white !important; 
                    border-color: var(--card-accent-color) !important; 
                }
                .scale-labels {
                    display: flex !important;
                    justify-content: space-between !important;
                    width: 100% !important;
                    margin-top: 0.5rem !important;
                    font-size: 0.78rem !important;
                    font-weight: 700 !important;
                    text-transform: uppercase !important;
                    letter-spacing: 0.5px !important;
                    color: var(--premier-charcoal) !important;
                    opacity: 0.6 !important;
                }
                .nav-btn { padding: 0.6rem 1.5rem; font-size: 0.9rem; font-weight: bold; border-radius: 6px; cursor: pointer; }
                .nav-btn:disabled { opacity: 0.3; cursor: not-allowed; }

                @media (max-width: 480px) {
                    .m-btn {
                        padding: 0.45rem 0 !important;
                        font-size: 0.75rem !important;
                    }
                    .scale-labels {
                        font-size: 0.7rem !important;
                    }
                }
            </style>
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background: white; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); border-top:6px solid var(--card-accent-color); min-height:380px; display:flex; flex-direction:column; justify-content:space-between; box-sizing:border-box;">
                <div>
                    <div style="width:100%; background: var(--premier-beige); height:6px; border-radius:3px; margin-bottom:2rem; overflow:hidden;"><div style="width:${pct}%; background: var(--card-accent-color); height:100%;"></div></div>
                    <div style="font-size:0.8rem; font-weight:800; color: var(--card-accent-color); text-transform:uppercase; text-align:center; margin-bottom:0.5rem;">Statement ${this.currentStep + 1} of ${this.quizData.questions.length}</div>
                    <h3 style="text-align:center; font-size:1.2rem; color: var(--premier-charcoal); margin-bottom:1.5rem;">"${qObj.text}"</h3>
                    
                    <div class="m-grid">
                        ${Array.from({length:10}, (_, i) => i + 1).map(num => `
                            <button type="button" class="m-btn ${this.currentSelection === num ? 'active' : ''}" data-val="${num}">${num}</button>
                        `).join('')}
                    </div>
                    
                    <div class="scale-labels">
                        <span class="label-disagree">Completely Disagree</span>
                        <span class="label-agree">Completely Agree</span>
                    </div>
                </div>
                <div style="display:flex; justify-content:space-between; border-top:1px solid var(--premier-beige); padding-top:1.25rem; margin-top:1rem;">
                    <button type="button" id="q-back" class="btn btn-secondary nav-btn" style="background-color: white; border-color: var(--premier-beige); color: var(--premier-charcoal);" ${this.currentStep === 0 ? 'disabled' : ''}>Back</button>
                    <button type="button" id="q-next" class="btn btn-primary nav-btn" style="background-color: var(--card-accent-color); border-color: var(--card-accent-color); color: white;" ${this.currentSelection === null ? 'disabled' : ''}>Next</button>
                </div>
            </div>`;

        this.querySelectorAll('.m-btn').forEach(b => b.addEventListener('click', () => {
            this.querySelectorAll('.m-btn').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            this.currentSelection = parseInt(b.getAttribute('data-val'));
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
    instance.innerHTML = `<div style="text-align:center; padding:4rem;"><h3 style="color: var(--card-accent-color);">Securing Playbook Access...</h3></div>`;
    const tallies = { typeA: 0, typeB: 0, typeC: 0, typeD: 0, typeE: 0, typeF: 0 };
    
    instance.quizData.questions.forEach((q, idx) => {
        const val = instance.answers[idx] || 0;
        if (tallies[q.bucket] !== undefined) tallies[q.bucket] += val;
    });

    let winner = 'typeA', maxVal = -1;
    for (const [k, v] of Object.entries(tallies)) {
        if (v > maxVal) { maxVal = v; winner = k; }
    }

    const match = instance.quizData.routing.find(r => r.key === winner) || instance.quizData.routing[0];
    const payload = {
        quizId: instance.quizData.id, firstName: instance.leadInfo.firstName, lastName: instance.leadInfo.lastName,
        email: instance.leadInfo.email, phone: instance.leadInfo.phone, outcomeKey: winner, finalOutcome: match.heading,
        scores: tallies, answers: instance.answers
    };

    try {
        fetch(instance.quizData.webhookUrl, { method: 'POST', mode: 'no-cors', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    } catch (e) {}

    const link = match.url.includes('?') ? `${match.url}&` : `${match.url}?`;
    setTimeout(() => {
        window.location.href = `${link}quizId=${instance.quizData.id}&result=${winner}&name=${encodeURIComponent(instance.leadInfo.firstName)}`;
    }, 600);
}