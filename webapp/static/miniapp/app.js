const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const initData = tg.initData || "";

function authHeaders() {
  return { "Content-Type": "application/json", "X-Telegram-Init-Data": initData };
}

// ---- Channel gate ----
async function checkGate() {
  try {
    const res = await fetch("/api/gate", { headers: authHeaders() });
    const data = await res.json();
    if (data.subscribed) {
      showApp();
    } else {
      showGate(data.channel_url);
    }
  } catch (e) {
    // Если проверка недоступна — не блокируем пользователя техническим сбоем
    showApp();
  }
}

function showGate(channelUrl) {
  document.getElementById("gate-screen").classList.remove("hidden");
  document.getElementById("app-root").classList.add("hidden");
  const link = document.getElementById("gate-channel-link");
  link.href = channelUrl || "#";
}

function showApp() {
  document.getElementById("gate-screen").classList.add("hidden");
  document.getElementById("app-root").classList.remove("hidden");
  loadPlans();
}

document.getElementById("gate-recheck-btn").addEventListener("click", checkGate);

// ---- Tabs ----
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "account") loadAccount();
    if (btn.dataset.tab === "apps") loadApps();
  });
});

// ---- Payment methods ----
let paymentMethods = [{ id: "telegram_stars", title: "Telegram Stars", icon: "⭐" }];

async function loadPaymentMethods() {
  try {
    const res = await fetch("/api/payment-methods");
    const data = await res.json();
    if (data.methods && data.methods.length) paymentMethods = data.methods;
  } catch (e) {
    // остаётся только Stars по умолчанию
  }
}

// ---- Trial ----
async function loadTrialCard(trialAvailable) {
  const box = document.getElementById("trial-card");
  if (!trialAvailable) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `
    <div class="trial-card">
      <h3>🎁 Пробный период бесплатно</h3>
      <p>Попробуй сервис перед покупкой — один раз на аккаунт.</p>
      <button class="buy-btn" id="trial-btn">Активировать бесплатно</button>
    </div>`;
  document.getElementById("trial-btn").addEventListener("click", startTrial);
}

async function startTrial() {
  try {
    const res = await fetch("/api/trial", { method: "POST", headers: authHeaders() });
    if (res.status === 403) {
      const err = await res.json();
      handleNotSubscribed(err.detail);
      return;
    }
    if (!res.ok) throw new Error(await res.text());
    tg.showAlert("Пробный период активирован! Смотри ссылку во вкладке «Моя подписка».");
    document.getElementById("trial-card").innerHTML = "";
    document.querySelector('.tab-btn[data-tab="account"]').click();
  } catch (e) {
    tg.showAlert("Не удалось активировать пробный период. Попробуй позже.");
  }
}

function handleNotSubscribed(detail) {
  const channelUrl = (detail && detail.channel_url) || "";
  tg.showAlert("Чтобы продолжить, сначала подпишись на канал.");
  showGate(channelUrl);
}

// ---- Plans ----
async function loadPlans() {
  const box = document.getElementById("plans-list");
  try {
    await loadPaymentMethods();
    const meRes = await fetch("/api/me", { headers: authHeaders() });
    const me = meRes.ok ? await meRes.json() : {};
    loadTrialCard(!!me.trial_available);

    const res = await fetch("/api/plans");
    const plans = await res.json();
    if (!plans.length) {
      box.innerHTML = '<div class="hint">Тарифы пока не добавлены</div>';
      return;
    }
    const multiMethod = paymentMethods.length > 1;

    box.innerHTML = plans
      .map((p) => {
        const priceLine = multiMethod
          ? `⭐ ${p.price_stars} <span class="hint"> или </span> ${p.price_rub}₽`
          : `⭐ ${p.price_stars}`;

        const buttons = multiMethod
          ? paymentMethods
              .map(
                (m) =>
                  `<button class="buy-btn" data-plan-id="${p.id}" data-provider="${m.id}">${m.icon} ${m.title}</button>`
              )
              .join("")
          : `<button class="buy-btn" data-plan-id="${p.id}" data-provider="telegram_stars">Купить</button>`;

        return `
      <div class="plan-card-wrap">
        <div class="plan-card">
          <div class="plan-info">
            <h3>${p.title}</h3>
            <p>${p.description || ""}</p>
            <p>${p.data_limit_gb === 0 ? "Безлимит трафика" : p.data_limit_gb + " ГБ"}</p>
          </div>
          <div class="plan-price">${priceLine}</div>
        </div>
        <div class="buy-btn-row">${buttons}</div>
      </div>`;
      })
      .join("");

    box.querySelectorAll(".buy-btn").forEach((btn) => {
      btn.addEventListener("click", () =>
        buyPlan(parseInt(btn.dataset.planId, 10), btn.dataset.provider)
      );
    });
  } catch (e) {
    box.innerHTML = '<div class="hint">Не удалось загрузить тарифы</div>';
  }
}

async function buyPlan(planId, provider) {
  try {
    const res = await fetch("/api/order", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ plan_id: planId, provider }),
    });
    if (res.status === 403) {
      const err = await res.json();
      handleNotSubscribed(err.detail);
      return;
    }
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    if (data.type === "telegram_invoice") {
      tg.openInvoice(data.invoice_link, (status) => {
        if (status === "paid") {
          tg.showAlert("Оплата прошла успешно! Подписка активирована.");
          loadAccount();
          document.querySelector('.tab-btn[data-tab="account"]').click();
        } else if (status === "failed") {
          tg.showAlert("Платёж не прошёл. Попробуйте ещё раз.");
        }
      });
    } else if (data.type === "redirect") {
      // Оплата картой открывается в браузере (форма ЮKassa, 3-D Secure и т.п.)
      tg.openLink(data.url, { try_instant_view: false });
      tg.showAlert(
        "Открылась страница оплаты в браузере. После оплаты вернитесь сюда и обновите вкладку «Моя подписка»."
      );
    }
  } catch (e) {
    tg.showAlert("Ошибка при создании заказа. Попробуйте позже.");
  }
}

// ---- Account ----
async function loadAccount() {
  const box = document.getElementById("account-box");
  box.innerHTML = '<div class="loading">Загружаем данные…</div>';
  try {
    const res = await fetch("/api/me", { headers: authHeaders() });
    const data = await res.json();

    if (!data.has_subscription) {
      box.innerHTML =
        '<div class="account-card"><p class="hint">У тебя пока нет активной подписки.<br>Оформи её во вкладке «Тарифы».</p>' +
        '<button class="copy-btn" id="refresh-btn">Обновить</button></div>';
      document.getElementById("refresh-btn").addEventListener("click", loadAccount);
      return;
    }

    const expires = new Date(data.expires_at).toLocaleString("ru-RU");
    box.innerHTML = `
      <div class="account-card">
        <h3>Подписка активна</h3>
        <p class="hint">До ${expires}</p>
        <p class="hint">${data.data_limit_gb === 0 ? "Безлимит трафика" : data.data_limit_gb + " ГБ"}</p>
        <div id="qrcode"></div>
        <div class="sub-url" id="sub-url">${data.sub_url}</div>
        <button class="copy-btn" id="copy-btn">Скопировать ссылку</button>
        <button class="copy-btn secondary" id="refresh-btn">Обновить</button>
        <p class="hint" style="margin-top:12px">Не знаешь, куда вставить ссылку? Смотри вкладку «Приложения».</p>
      </div>`;

    new QRCode(document.getElementById("qrcode"), {
      text: data.sub_url,
      width: 180,
      height: 180,
    });

    document.getElementById("copy-btn").addEventListener("click", () => {
      navigator.clipboard.writeText(data.sub_url);
      tg.HapticFeedback.notificationOccurred("success");
      tg.showAlert("Ссылка скопирована");
    });
    document.getElementById("refresh-btn").addEventListener("click", loadAccount);
  } catch (e) {
    box.innerHTML = '<div class="hint">Не удалось загрузить данные подписки</div>';
  }
}

// ---- Apps ----
async function loadApps() {
  const box = document.getElementById("apps-box");
  box.innerHTML = '<div class="loading">Загружаем список…</div>';
  try {
    const res = await fetch("/api/apps");
    const data = await res.json();
    box.innerHTML =
      '<p class="hint" style="margin-bottom:12px">Скачай приложение под свою платформу и вставь в него ссылку-подписку из вкладки «Моя подписка».</p>' +
      data.items
        .map(
          (a) => `
      <a class="app-item" href="${a.url}" target="_blank" style="text-decoration:none;color:inherit;">
        <div>
          <div class="platform">${a.platform}</div>
          <div class="app-name">${a.name}</div>
        </div>
        <div>↗</div>
      </a>`
        )
        .join("");
  } catch (e) {
    box.innerHTML = '<div class="hint">Не удалось загрузить список приложений</div>';
  }
}

checkGate();
