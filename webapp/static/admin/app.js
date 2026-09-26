const state = {
  users: { page: 1, pageSize: 30, search: "" },
  webSubs: { page: 1, pageSize: 30, search: "" },
  payments: { page: 1, pageSize: 30 },
  editingPlanId: null,
  editingPanelId: null,
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    showLogin();
    throw new Error("not authenticated");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : null;
}

function showLogin() {
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("app-shell").classList.add("hidden");
}

function showApp() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-shell").classList.remove("hidden");
  switchView("dashboard");
}

// ---- Auth ----
async function checkAuth() {
  try {
    await api("/admin/api/me");
    showApp();
  } catch (e) {
    showLogin();
  }
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("login-username").value;
  const password = document.getElementById("login-password").value;
  const errBox = document.getElementById("login-error");
  errBox.textContent = "";
  try {
    await api("/admin/api/login", { method: "POST", body: JSON.stringify({ username, password }) });
    showApp();
  } catch (e) {
    errBox.textContent = "Неверный логин или пароль";
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  await api("/admin/api/logout", { method: "POST" });
  showLogin();
});

// ---- Navigation ----
document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

function switchView(view) {
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  if (view === "dashboard") loadDashboard();
  if (view === "plans") loadPlans();
  if (view === "panels") loadPanels();
  if (view === "users") loadUsers();
  if (view === "web-subs") loadWebSubs();
  if (view === "payments") loadPayments();
}

// ---- Dashboard ----
async function loadDashboard() {
  const grid = document.getElementById("stat-grid");
  grid.innerHTML = '<div class="hint">Загрузка…</div>';
  try {
    const s = await api("/admin/api/stats");
    const revenue = Object.entries(s.revenue_month)
      .map(([cur, val]) => `${val.toFixed(cur === "XTR" ? 0 : 2)} ${cur === "XTR" ? "⭐" : cur}`)
      .join(" + ") || "0";
    grid.innerHTML = `
      <div class="stat-card"><div class="value">${s.users_total}</div><div class="label">Пользователей (Telegram)</div></div>
      <div class="stat-card"><div class="value">${s.active_subscriptions}</div><div class="label">Активных подписок (Telegram)</div></div>
      <div class="stat-card"><div class="value">${s.web_active_subscriptions}</div><div class="label">Активных подписок (сайт)</div></div>
      <div class="stat-card"><div class="value">${revenue}</div><div class="label">Доход за месяц</div></div>
      <div class="stat-card"><div class="value">${s.payments_total}</div><div class="label">Оплат всего</div></div>
      <div class="stat-card"><div class="value">${s.panels_total}</div><div class="label">Панелей 3x-ui</div></div>
    `;
  } catch (e) {
    grid.innerHTML = '<div class="hint">Не удалось загрузить статистику</div>';
  }
}

// ---- Plans ----
async function loadPlans() {
  const tbody = document.getElementById("plans-tbody");
  tbody.innerHTML = '<tr><td colspan="7" class="hint">Загрузка…</td></tr>';
  try {
    const plans = await api("/admin/api/plans");
    tbody.innerHTML = plans
      .map(
        (p) => `
      <tr>
        <td>${p.title}</td>
        <td>${p.duration_days}</td>
        <td>${p.data_limit_gb === 0 ? "безлимит" : p.data_limit_gb + " ГБ"}</td>
        <td>${p.price_stars}</td>
        <td>${p.price_rub}</td>
        <td>${p.is_active ? '<span class="badge badge-success">активен</span>' : '<span class="badge badge-muted">скрыт</span>'}</td>
        <td><button class="btn-sm" onclick="editPlan(${p.id})">Изменить</button></td>
      </tr>`
      )
      .join("") || '<tr><td colspan="7" class="hint">Тарифов пока нет</td></tr>';
    window._plansCache = plans;
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="7" class="hint">Ошибка загрузки</td></tr>';
  }
}

function openPlanModal() {
  document.getElementById("plan-modal").classList.remove("hidden");
}
function closePlanModal() {
  document.getElementById("plan-modal").classList.add("hidden");
}

document.getElementById("add-plan-btn").addEventListener("click", () => {
  state.editingPlanId = null;
  document.getElementById("plan-modal-title").textContent = "Новый тариф";
  document.getElementById("plan-title").value = "";
  document.getElementById("plan-description").value = "";
  document.getElementById("plan-duration").value = 30;
  document.getElementById("plan-data-limit").value = 0;
  document.getElementById("plan-price-stars").value = "";
  document.getElementById("plan-price-rub").value = "";
  document.getElementById("plan-is-active").checked = true;
  openPlanModal();
});

window.editPlan = function (id) {
  const p = (window._plansCache || []).find((x) => x.id === id);
  if (!p) return;
  state.editingPlanId = id;
  document.getElementById("plan-modal-title").textContent = "Изменить тариф";
  document.getElementById("plan-title").value = p.title;
  document.getElementById("plan-description").value = p.description;
  document.getElementById("plan-duration").value = p.duration_days;
  document.getElementById("plan-data-limit").value = p.data_limit_gb;
  document.getElementById("plan-price-stars").value = p.price_stars;
  document.getElementById("plan-price-rub").value = p.price_rub;
  document.getElementById("plan-is-active").checked = p.is_active;
  openPlanModal();
};

document.getElementById("plan-cancel-btn").addEventListener("click", closePlanModal);

document.getElementById("plan-save-btn").addEventListener("click", async () => {
  const body = {
    title: document.getElementById("plan-title").value,
    description: document.getElementById("plan-description").value,
    duration_days: parseInt(document.getElementById("plan-duration").value, 10),
    data_limit_gb: parseInt(document.getElementById("plan-data-limit").value, 10) || 0,
    price_stars: parseInt(document.getElementById("plan-price-stars").value, 10),
    price_rub: parseFloat(document.getElementById("plan-price-rub").value) || 0,
    is_active: document.getElementById("plan-is-active").checked,
  };
  try {
    if (state.editingPlanId) {
      await api(`/admin/api/plans/${state.editingPlanId}`, { method: "PUT", body: JSON.stringify(body) });
    } else {
      await api("/admin/api/plans", { method: "POST", body: JSON.stringify(body) });
    }
    closePlanModal();
    loadPlans();
  } catch (e) {
    alert("Не удалось сохранить тариф: " + e.message);
  }
});

// ---- Panels ----
async function loadPanels() {
  const tbody = document.getElementById("panels-tbody");
  tbody.innerHTML = '<tr><td colspan="6" class="hint">Загрузка…</td></tr>';
  try {
    const panels = await api("/admin/api/panels");
    tbody.innerHTML = panels
      .map(
        (p) => `
      <tr>
        <td>${p.name}</td>
        <td>${p.base_url}</td>
        <td>${p.inbound_ids}</td>
        <td>${p.is_primary ? "✅" : ""}</td>
        <td>${p.is_active ? '<span class="badge badge-success">активна</span>' : '<span class="badge badge-muted">выключена</span>'}</td>
        <td class="row-actions">
          <button class="btn-sm" onclick="editPanel(${p.id})">Изменить</button>
          <button class="btn-sm danger" onclick="deletePanel(${p.id})">Удалить</button>
        </td>
      </tr>`
      )
      .join("") || '<tr><td colspan="6" class="hint">Панели ещё не добавлены</td></tr>';
    window._panelsCache = panels;
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" class="hint">Ошибка загрузки</td></tr>';
  }
}

function openPanelModal() {
  document.getElementById("panel-test-result").textContent = "";
  document.getElementById("panel-modal").classList.remove("hidden");
}
function closePanelModal() {
  document.getElementById("panel-modal").classList.add("hidden");
}

document.getElementById("add-panel-btn").addEventListener("click", () => {
  state.editingPanelId = null;
  document.getElementById("panel-modal-title").textContent = "Новая панель";
  document.getElementById("panel-name").value = "";
  document.getElementById("panel-base-url").value = "";
  document.getElementById("panel-api-token").value = "";
  document.getElementById("panel-sub-base-url").value = "";
  document.getElementById("panel-inbound-ids").value = "1";
  document.getElementById("panel-is-primary").checked = false;
  document.getElementById("panel-is-active").checked = true;
  openPanelModal();
});

window.editPanel = function (id) {
  const p = (window._panelsCache || []).find((x) => x.id === id);
  if (!p) return;
  state.editingPanelId = id;
  document.getElementById("panel-modal-title").textContent = "Изменить панель";
  document.getElementById("panel-name").value = p.name;
  document.getElementById("panel-base-url").value = p.base_url;
  document.getElementById("panel-api-token").value = ""; // не показываем реальный токен, только при желании заменить
  document.getElementById("panel-api-token").placeholder = "Оставьте пустым, чтобы не менять (" + p.api_token_masked + ")";
  document.getElementById("panel-sub-base-url").value = p.sub_base_url;
  document.getElementById("panel-inbound-ids").value = p.inbound_ids;
  document.getElementById("panel-is-primary").checked = p.is_primary;
  document.getElementById("panel-is-active").checked = p.is_active;
  openPanelModal();
};

window.deletePanel = async function (id) {
  if (!confirm("Удалить панель? Клиенты, уже созданные на ней, останутся в 3x-ui, но бот перестанет ей управлять.")) return;
  try {
    await api(`/admin/api/panels/${id}`, { method: "DELETE" });
    loadPanels();
  } catch (e) {
    alert("Не удалось удалить: " + e.message);
  }
};

document.getElementById("panel-cancel-btn").addEventListener("click", closePanelModal);

document.getElementById("panel-test-btn").addEventListener("click", async () => {
  const resultEl = document.getElementById("panel-test-result");
  resultEl.textContent = "Проверяем…";
  const id = state.editingPanelId;
  if (!id) {
    resultEl.textContent = "Сначала сохраните панель, потом проверьте связь";
    return;
  }
  try {
    const res = await api(`/admin/api/panels/${id}/test`, { method: "POST" });
    resultEl.textContent = res.ok ? "✅ Связь есть" : "❌ " + res.error;
  } catch (e) {
    resultEl.textContent = "❌ " + e.message;
  }
});

document.getElementById("panel-save-btn").addEventListener("click", async () => {
  const body = {
    name: document.getElementById("panel-name").value,
    base_url: document.getElementById("panel-base-url").value,
    api_token: document.getElementById("panel-api-token").value, // пусто при редактировании = не менять
    sub_base_url: document.getElementById("panel-sub-base-url").value,
    inbound_ids: document.getElementById("panel-inbound-ids").value,
    is_primary: document.getElementById("panel-is-primary").checked,
    is_active: document.getElementById("panel-is-active").checked,
  };
  try {
    if (state.editingPanelId) {
      await api(`/admin/api/panels/${state.editingPanelId}`, { method: "PUT", body: JSON.stringify(body) });
    } else {
      await api("/admin/api/panels", { method: "POST", body: JSON.stringify(body) });
    }
    closePanelModal();
    loadPanels();
  } catch (e) {
    alert("Не удалось сохранить панель: " + e.message);
  }
});

// ---- Users ----
let usersSearchTimer = null;
document.getElementById("users-search").addEventListener("input", (e) => {
  clearTimeout(usersSearchTimer);
  usersSearchTimer = setTimeout(() => {
    state.users.search = e.target.value;
    state.users.page = 1;
    loadUsers();
  }, 350);
});

document.getElementById("add-user-btn").addEventListener("click", async () => {
  document.getElementById("grant-user-id").value = "";
  document.getElementById("grant-username").value = "";
  document.getElementById("grant-first-name").value = "";
  const select = document.getElementById("grant-plan-id");
  select.innerHTML = '<option>Загрузка…</option>';
  document.getElementById("grant-modal").classList.remove("hidden");
  try {
    const plans = await api("/admin/api/plans");
    const visible = plans.filter((p) => p.is_active);
    select.innerHTML = visible.map((p) => `<option value="${p.id}">${p.title}</option>`).join("");
  } catch (e) {
    select.innerHTML = '<option>Не удалось загрузить тарифы</option>';
  }
});

document.getElementById("grant-cancel-btn").addEventListener("click", () => {
  document.getElementById("grant-modal").classList.add("hidden");
});

document.getElementById("grant-save-btn").addEventListener("click", async () => {
  const body = {
    user_id: parseInt(document.getElementById("grant-user-id").value, 10),
    plan_id: parseInt(document.getElementById("grant-plan-id").value, 10),
    username: document.getElementById("grant-username").value,
    first_name: document.getElementById("grant-first-name").value,
  };
  if (!body.user_id || !body.plan_id) {
    alert("Укажи Telegram ID и тариф");
    return;
  }
  try {
    await api("/admin/api/users/grant", { method: "POST", body: JSON.stringify(body) });
    document.getElementById("grant-modal").classList.add("hidden");
    loadUsers();
  } catch (e) {
    alert("Не удалось выдать подписку: " + e.message);
  }
});

async function loadUsers() {
  const tbody = document.getElementById("users-tbody");
  tbody.innerHTML = '<tr><td colspan="6" class="hint">Загрузка…</td></tr>';
  try {
    const { page, pageSize, search } = state.users;
    const params = new URLSearchParams({ page, page_size: pageSize, search });
    const data = await api(`/admin/api/users?${params}`);
    tbody.innerHTML = data.items
      .map((u) => {
        const sub = u.subscription;
        const status = !sub
          ? '<span class="badge badge-muted">нет</span>'
          : sub.is_active
          ? '<span class="badge badge-success">активна</span>'
          : '<span class="badge badge-danger">выключена</span>';
        return `
        <tr>
          <td>${u.id}</td>
          <td>${u.first_name || ""}</td>
          <td>${u.username ? "@" + u.username : ""}</td>
          <td>${sub ? new Date(sub.expires_at).toLocaleString("ru-RU") : "—"}</td>
          <td>${status}</td>
          <td><button class="btn-sm" onclick="openUser(${u.id})">Открыть</button></td>
        </tr>`;
      })
      .join("") || '<tr><td colspan="6" class="hint">Никого не найдено</td></tr>';

    renderPagination("users-pagination", data.total, page, pageSize, (p) => {
      state.users.page = p;
      loadUsers();
    });
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" class="hint">Ошибка загрузки</td></tr>';
  }
}

window.openUser = async function (userId) {
  const body = document.getElementById("user-modal-body");
  document.getElementById("user-modal-title").textContent = `Пользователь #${userId}`;
  body.innerHTML = '<div class="hint">Загрузка…</div>';
  document.getElementById("user-modal").classList.remove("hidden");
  try {
    const u = await api(`/admin/api/users/${userId}`);
    body.innerHTML = `
      <div class="user-section">
        <h4>Профиль</h4>
        <p>${u.first_name || ""} ${u.username ? "@" + u.username : ""} — с ${new Date(u.created_at).toLocaleDateString("ru-RU")}</p>
      </div>
      <div class="user-section">
        <h4>Подписки</h4>
        <table class="mini-table">
          <thead><tr><th>До</th><th>Лимит</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            ${
              u.subscriptions
                .map(
                  (s) => `
              <tr>
                <td>${new Date(s.expires_at).toLocaleString("ru-RU")}</td>
                <td>${s.data_limit_gb === 0 ? "безлимит" : s.data_limit_gb + " ГБ"}</td>
                <td>${s.is_active ? '<span class="badge badge-success">вкл</span>' : '<span class="badge badge-danger">выкл</span>'}</td>
                <td class="row-actions">
                  <button class="btn-sm" onclick="extendSub(${s.id}, ${userId})">+30 дней</button>
                  <button class="btn-sm" onclick="toggleSub(${s.id}, ${userId}, ${!s.is_active})">${s.is_active ? "Выключить" : "Включить"}</button>
                </td>
              </tr>`
                )
                .join("") || '<tr><td colspan="4" class="hint">Подписок нет</td></tr>'
            }
          </tbody>
        </table>
      </div>
      <div class="user-section">
        <h4>Платежи</h4>
        <table class="mini-table">
          <thead><tr><th>Сумма</th><th>Способ</th><th>Статус</th><th>Дата</th></tr></thead>
          <tbody>
            ${
              u.payments
                .map(
                  (p) => `
              <tr>
                <td>${p.amount} ${p.currency}</td>
                <td>${p.provider}</td>
                <td>${p.status}</td>
                <td>${new Date(p.created_at).toLocaleString("ru-RU")}</td>
              </tr>`
                )
                .join("") || '<tr><td colspan="4" class="hint">Платежей нет</td></tr>'
            }
          </tbody>
        </table>
      </div>
    `;
  } catch (e) {
    body.innerHTML = '<div class="hint">Не удалось загрузить данные</div>';
  }
};

window.extendSub = async function (subId, userId) {
  const days = parseInt(prompt("На сколько дней продлить?", "30"), 10);
  if (!days) return;
  try {
    await api(`/admin/api/subscriptions/${subId}/extend`, { method: "POST", body: JSON.stringify({ days }) });
    openUser(userId);
    loadUsers();
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
};

window.toggleSub = async function (subId, userId, enabled) {
  try {
    await api(`/admin/api/subscriptions/${subId}/set-enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    });
    openUser(userId);
    loadUsers();
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
};

document.getElementById("user-close-btn").addEventListener("click", () => {
  document.getElementById("user-modal").classList.add("hidden");
});

// ---- Web shop subscriptions ----
let webSubsSearchTimer = null;
document.getElementById("web-subs-search").addEventListener("input", (e) => {
  clearTimeout(webSubsSearchTimer);
  webSubsSearchTimer = setTimeout(() => {
    state.webSubs.search = e.target.value;
    state.webSubs.page = 1;
    loadWebSubs();
  }, 350);
});

async function loadWebSubs() {
  const tbody = document.getElementById("web-subs-tbody");
  tbody.innerHTML = '<tr><td colspan="5" class="hint">Загрузка…</td></tr>';
  try {
    const { page, pageSize, search } = state.webSubs;
    const params = new URLSearchParams({ page, page_size: pageSize, search });
    const data = await api(`/admin/api/web-subscriptions?${params}`);
    tbody.innerHTML = data.items
      .map(
        (s) => `
      <tr>
        <td>${s.email}</td>
        <td>${new Date(s.expires_at).toLocaleString("ru-RU")}</td>
        <td>${s.data_limit_gb === 0 ? "безлимит" : s.data_limit_gb + " ГБ"}</td>
        <td>${s.is_active ? '<span class="badge badge-success">активна</span>' : '<span class="badge badge-danger">выключена</span>'}</td>
        <td class="row-actions">
          <button class="btn-sm" onclick="extendWebSub(${s.id})">+30 дней</button>
          <button class="btn-sm" onclick="toggleWebSub(${s.id}, ${!s.is_active})">${s.is_active ? "Выключить" : "Включить"}</button>
        </td>
      </tr>`
      )
      .join("") || '<tr><td colspan="5" class="hint">Покупок с сайта пока нет</td></tr>';

    renderPagination("web-subs-pagination", data.total, page, pageSize, (p) => {
      state.webSubs.page = p;
      loadWebSubs();
    });
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="5" class="hint">Ошибка загрузки</td></tr>';
  }
}

window.extendWebSub = async function (subId) {
  const days = parseInt(prompt("На сколько дней продлить?", "30"), 10);
  if (!days) return;
  try {
    await api(`/admin/api/web-subscriptions/${subId}/extend`, { method: "POST", body: JSON.stringify({ days }) });
    loadWebSubs();
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
};

window.toggleWebSub = async function (subId, enabled) {
  try {
    await api(`/admin/api/web-subscriptions/${subId}/set-enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    });
    loadWebSubs();
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
};

// ---- Payments ----
async function loadPayments() {
  const tbody = document.getElementById("payments-tbody");
  tbody.innerHTML = '<tr><td colspan="6" class="hint">Загрузка…</td></tr>';
  try {
    const { page, pageSize } = state.payments;
    const params = new URLSearchParams({ page, page_size: pageSize });
    const data = await api(`/admin/api/payments?${params}`);
    tbody.innerHTML = data.items
      .map(
        (p) => `
      <tr>
        <td>${p.id}</td>
        <td>${p.user_id ? "tg:" + p.user_id : p.email || "—"}</td>
        <td>${p.amount} ${p.currency}</td>
        <td>${p.provider}</td>
        <td>${p.status}</td>
        <td>${new Date(p.created_at).toLocaleString("ru-RU")}</td>
      </tr>`
      )
      .join("") || '<tr><td colspan="6" class="hint">Платежей пока нет</td></tr>';

    renderPagination("payments-pagination", data.total, page, pageSize, (p) => {
      state.payments.page = p;
      loadPayments();
    });
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" class="hint">Ошибка загрузки</td></tr>';
  }
}

// ---- Shared pagination ----
function renderPagination(containerId, total, page, pageSize, onChange) {
  const container = document.getElementById(containerId);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) {
    container.innerHTML = "";
    return;
  }
  let html = "";
  for (let i = 1; i <= totalPages; i++) {
    html += `<button class="btn-sm${i === page ? " active" : ""}" data-page="${i}">${i}</button>`;
  }
  container.innerHTML = html;
  container.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => onChange(parseInt(btn.dataset.page, 10)));
  });
}

checkAuth();
