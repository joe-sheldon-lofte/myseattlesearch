class YouTubeLite extends HTMLElement {
    connectedCallback() {
        const videoId = this.getAttribute('video-id');
        const customPoster = this.getAttribute('poster');
        const label = this.getAttribute('label') || 'Play Video';

        if (!videoId) return;

        const posterUrl = customPoster || `https://i.ytimg.com/vi_webp/${videoId}/hqdefault.webp`;

        this.style.position = 'relative';
        this.style.display = 'block';
        this.style.width = '100%';
        this.style.aspectRatio = '16 / 9';
        this.style.backgroundColor = 'var(--premier-charcoal)';
        this.style.backgroundImage = `url('${posterUrl}')`;
        this.style.backgroundSize = 'cover';
        this.style.backgroundPosition = 'center';
        this.style.cursor = 'pointer';
        this.style.borderRadius = '8px';
        this.style.overflow = 'hidden';

        this.innerHTML = `
            <button aria-label="${label}" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 68px; height: 48px; background-color: var(--card-accent-color); border: none; border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), background-color 0.2s ease; box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 2;">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="var(--white)" style="margin-left: 3px;"><path d="M8 5v14l11-7z"/></svg>
            </button>
            <div style="position: absolute; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.15); z-index: 1;"></div>
        `;

        this.addEventListener('click', () => {
            const iframe = document.createElement('iframe');
            iframe.setAttribute('src', `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0&modestbranding=1`);
            iframe.setAttribute('title', label);
            iframe.setAttribute('frameborder', '0');
            iframe.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture');
            iframe.setAttribute('allowfullscreen', 'true');
            iframe.style.width = '100%';
            iframe.style.height = '100%';
            iframe.style.position = 'absolute';
            iframe.style.top = '0';
            iframe.style.left = '0';
            iframe.style.borderRadius = '8px';
            iframe.style.border = 'none';

            this.innerHTML = '';
            this.appendChild(iframe);
        }, { once: true });
    }
}