const menuToggle = document.querySelector('.menu-toggle');
const nav = document.querySelector('.desktop-nav');

menuToggle?.addEventListener('click', () => {
  const open = menuToggle.getAttribute('aria-expanded') === 'true';
  menuToggle.setAttribute('aria-expanded', String(!open));
  nav.classList.toggle('open', !open);
});

document.querySelectorAll('.desktop-nav a').forEach((link) => link.addEventListener('click', () => {
  menuToggle?.setAttribute('aria-expanded', 'false');
  nav?.classList.remove('open');
}));

document.querySelectorAll('.feature-tab').forEach((tab) => tab.addEventListener('click', () => {
  document.querySelectorAll('.feature-tab').forEach((item) => item.classList.remove('active'));
  tab.classList.add('active');
}));

document.querySelectorAll('details').forEach((detail) => detail.addEventListener('toggle', () => {
  if (detail.open) document.querySelectorAll('details').forEach((other) => { if (other !== detail) other.open = false; });
}));

const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
  if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); }
}), { threshold: 0.12 });
document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));

document.querySelector('#demo-form')?.addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button');
  button.disabled = true;
  button.innerHTML = 'Solicitud enviada <span>✓</span>';
  form.querySelector('.form-success').classList.add('show');
  form.reset();
});

const header = document.querySelector('.site-header');
window.addEventListener('scroll', () => header.classList.toggle('scrolled', window.scrollY > 24), { passive: true });
