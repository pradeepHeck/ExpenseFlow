document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => { document.querySelectorAll('.tab').forEach(b => b.classList.remove('active')); document.querySelectorAll('.auth-panel').forEach(p => p.classList.remove('active')); btn.classList.add('active'); document.getElementById(btn.dataset.target)?.classList.add('active'); history.replaceState(null, '', '#' + btn.dataset.target.replace('Panel', '').toLowerCase()) }));
    if (location.hash === '#register') document.querySelector('[data-target="registerPanel"]')?.click();
    document.querySelectorAll('[data-toggle]').forEach(btn => btn.addEventListener('click', () => { const i = btn.parentElement.querySelector('input'); i.type = i.type === 'password' ? 'text' : 'password'; btn.textContent = i.type === 'password' ? 'Show' : 'Hide' }));
    const menu = document.getElementById('menuBtn'); menu?.addEventListener('click', () => document.getElementById('sidebar')?.classList.toggle('open'));
    setTimeout(() => document.querySelectorAll('.toast').forEach(x => x.remove()), 4500);
    document.querySelectorAll('input[type="number"]').forEach(i => i.addEventListener('input', () => { if (Number(i.value) < 0) i.value = '' }));
});
