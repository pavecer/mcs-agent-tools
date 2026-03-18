// ── Theme toggle
const root = document.documentElement;
const btn = document.getElementById('theme-toggle');
const stored = localStorage.getItem('pp-theme');
if (stored) root.setAttribute('data-theme', stored);
function syncBtn() {
  const t = root.getAttribute('data-theme') || 'dark';
  btn.textContent = t === 'dark' ? 'Light mode' : 'Dark mode';
}
btn.addEventListener('click', () => {
  const next = (root.getAttribute('data-theme') || 'dark') === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  localStorage.setItem('pp-theme', next);
  syncBtn();
});
syncBtn();

// ── Reveal on scroll
const revealEls = [...document.querySelectorAll('.reveal')];
const ro = new IntersectionObserver((entries) => {
  entries.forEach((e, i) => {
    if (e.isIntersecting) {
      e.target.style.transitionDelay = `${Math.min(i * 40, 200)}ms`;
      e.target.classList.add('in-view');
      ro.unobserve(e.target);
    }
  });
}, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
revealEls.forEach(el => ro.observe(el));

// ── Counter animation
function animateCount(el) {
  const target = +el.getAttribute('data-counter');
  if (isNaN(target)) return;
  const dur = 1000, start = performance.now();
  (function tick(now) {
    const p = Math.min((now - start) / dur, 1);
    el.textContent = Math.floor(target * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(tick);
    else el.textContent = target;
  })(start);
}
const co = new IntersectionObserver((entries) => {
  entries.forEach(e => { if (e.isIntersecting) { animateCount(e.target); co.unobserve(e.target); } });
}, { threshold: 0.5 });
document.querySelectorAll('[data-counter]').forEach(el => co.observe(el));

// ── Flow step animation
const flowSection = document.getElementById('analysis-flow');
const flowSteps = flowSection ? [...flowSection.querySelectorAll('.flow-step')] : [];
let fi = 0, ft = null;
function setFlow(i) { flowSteps.forEach((s, j) => s.classList.toggle('is-active', j === i)); }
function startFlow() {
  if (!flowSteps.length || ft) return;
  setFlow(fi);
  ft = setInterval(() => { fi = (fi + 1) % flowSteps.length; setFlow(fi); }, 1200);
}
function stopFlow() { clearInterval(ft); ft = null; }
if (flowSection) {
  new IntersectionObserver(entries => {
    entries.forEach(e => e.isIntersecting ? startFlow() : stopFlow());
  }, { threshold: 0.3 }).observe(flowSection);
}

// ── Tilt on cards
if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  document.querySelectorAll('.cap-card, .gallery-item').forEach(card => {
    card.addEventListener('mousemove', e => {
      const r = card.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      card.style.transform = `perspective(800px) rotateX(${-y * 5}deg) rotateY(${x * 5}deg) translateY(-4px)`;
    });
    card.addEventListener('mouseleave', () => card.style.transform = '');
  });
}
