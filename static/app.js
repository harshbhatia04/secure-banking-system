document.addEventListener('DOMContentLoaded', () => {
  const menu = document.getElementById('menuToggle');
  const scrim = document.getElementById('mobileScrim');
  if (menu) menu.addEventListener('click', () => document.body.classList.toggle('nav-open'));
  if (scrim) scrim.addEventListener('click', () => document.body.classList.remove('nav-open'));

  const success = document.getElementById('paymentSuccess');
  if (success) {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.setTimeout(() => success.remove(), reducedMotion ? 600 : 2500);
  }

  const form = document.getElementById('transactionForm');
  if (!form) return;
  const destination = document.getElementById('destinationField');
  const destinationSelect = document.getElementById('destinationSelect');
  const key = document.getElementById('requestKey');
  const progress = document.getElementById('paymentProgress');
  const submit = form.querySelector('button[type="submit"]');
  const choices = form.querySelectorAll('input[name="operation"]');
  const update = () => {
    const selected = form.querySelector('input[name="operation"]:checked').value;
    destination.hidden = selected !== 'transfer';
    destinationSelect.disabled = selected !== 'transfer';
  };
  choices.forEach(choice => choice.addEventListener('change', update));
  update();
  form.addEventListener('submit', () => {
    if (!key.value) key.value = crypto.randomUUID();
    if (progress) progress.hidden = false;
    if (submit) submit.disabled = true;
  });
  window.addEventListener('pageshow', () => {
    if (progress) progress.hidden = true;
    if (submit) submit.disabled = false;
  });
});
