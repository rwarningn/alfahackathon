const $ = (selector) => document.querySelector(selector);
const labels = {submitted:'Подана',review:'На рассмотрении',approved:'Одобрена',declined:'Отказ'};
const recommendations = {approve:'Рекомендовано одобрение',review:'Нужна ручная проверка',decline:'Рекомендован отказ'};
const money = value => new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',maximumFractionDigits:0}).format(value);
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let user;
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Ошибка запроса');
  return value;
}
function notice(error) { $('#notice').textContent = error.message; $('#notice').hidden = false; }
async function action(button, task) {
  button.disabled = true; $('#notice').hidden = true;
  try { await task(); } catch(error) { notice(error); } finally { button.disabled = false; }
}
$('#login-form select').addEventListener('change', event => { $('#login-form input').value = `${event.target.value}-demo`; });
$('#login-form').addEventListener('submit', event => {
  event.preventDefault();
  action(event.submitter, async () => {user = await api('/api/login',Object.fromEntries(new FormData(event.target))); await openWorkspace();});
});
$('#logout').addEventListener('click', event => action(event.target, async () => {await api('/api/logout',{}); location.reload();}));
$('#refresh').addEventListener('click', event => action(event.target, load));
$('#application-form').addEventListener('submit', event => {
  event.preventDefault();
  action(event.submitter, async () => {
    const data = Object.fromEntries(new FormData(event.target));
    Object.keys(data).forEach(key => {if(key !== 'company') data[key] = Number(data[key]);});
    await api('/api/applications',data); await load();
  });
});
async function openWorkspace() {
  $('#login').hidden = true; $('#workspace').hidden = false; $('#logout').hidden = false;
  $('#identity').textContent = user.name;
  const bank = user.role === 'bank';
  $('#application-panel').hidden = bank;
  $('.layout').classList.toggle('bank', bank);
  $('#role-label').textContent = bank ? 'РАБОЧЕЕ МЕСТО АНАЛИТИКА' : 'ВАШ БИЗНЕС / ВАШИ ВОЗМОЖНОСТИ';
  $('#page-title').textContent = bank ? 'Решения для бизнеса' : 'Дело в движении';
  await load();
}
async function load() {
  const apps = await api('/api/applications');
  $('#total').textContent = apps.length;
  $('#pending').textContent = apps.filter(a => ['submitted','review'].includes(a.status)).length;
  $('#done').textContent = apps.filter(a => ['approved','declined'].includes(a.status)).length;
  const latest = apps[0];
  const news = !latest ? 'Выберите сумму и срок. После подачи здесь появятся следующие шаги.' : ({submitted:'Заявка принята. Аналитик проверит финансовые показатели; результат появится в этом кабинете.',review:'Аналитик рассматривает заявку. Повторная подача не требуется — следите за историей.',approved:'Заявка одобрена в демо-сценарии. Реальные договор и выдача средств в прототип не входят.',declined:'По заявке получен отказ. Посмотрите комментарий аналитика и оценку денежного потока.'}[latest.status]);
  $('#feed').innerHTML = `<p class="eyebrow">${user.role === 'bank' ? 'ФОКУС АНАЛИТИКА' : 'ЛЕНТА ВАШЕГО БИЗНЕСА'}</p><h2>${latest ? labels[latest.status] : 'Начните с одного шага'}</h2><p>${escape(news)}</p>`;
  $('#applications').innerHTML = apps.length ? apps.map(render).join('') : '<div class="empty">Пока нет заявок. Ваша первая заявка появится здесь.</div>';
}
function render(app) {
  const a = app.assessment;
  const controls = user.role === 'bank' && ['submitted','review'].includes(app.status) ? `<form data-transition="${app.id}"><label>Комментарий клиенту<textarea name="comment" minlength="5" maxlength="1000" required placeholder="Объясните следующий шаг или решение"></textarea></label><div class="actions">${app.status === 'submitted' ? '<button name="status" value="review">Взять в работу</button>' : '<button name="status" value="approved">Одобрить</button><button class="quiet" name="status" value="declined">Отказать</button>'}</div></form>` : '';
  return `<article class="card application"><div class="application-top"><div><span class="small">№ ${escape(app.id)}</span><h3>${escape(app.data.company)}</h3></div><span class="status ${app.status}">${labels[app.status]}</span></div><div class="amount">${money(app.data.amount)}</div><span class="muted">${app.data.term_months} мес. · Оборотные средства</span><div class="assessment"><strong>${recommendations[a.recommendation]}</strong><p>Расчётный платёж: ${money(a.monthly_payment)} / мес.<br>Покрытие платежей денежным потоком: ${a.coverage.toFixed(2)}×</p><p>${a.reasons.map(escape).join('. ')}</p><span class="small">Демонстрационные правила ${escape(a.policy_version)}. Это рекомендация, решение принимает аналитик.</span></div><ol class="timeline">${app.events.map(e=>`<li><time>${escape(new Date(e.created_at).toLocaleString('ru-RU'))} · ${escape(e.actor)}</time><strong>${labels[e.status]}</strong><p>${escape(e.comment)}</p></li>`).join('')}</ol>${controls}</article>`;
}
$('#applications').addEventListener('submit', event => {
  event.preventDefault(); const form = event.target;
  if (!form.dataset.transition) return;
  action(event.submitter, async () => {await api(`/api/applications/${form.dataset.transition}/transition`, {status:event.submitter.value,comment:new FormData(form).get('comment')}); await load();});
});
(async () => {try { user = await api('/api/me'); await openWorkspace(); } catch { /* Session absent: show login. */ }})();
