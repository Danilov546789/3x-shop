async function loadConfig() {
  try {
    const res = await fetch("/shop/api/config");
    const data = await res.json();
    const titleEls = document.querySelectorAll("#site-title");
    titleEls.forEach((el) => (el.textContent = `🛡️ ${data.title}`));
    if (data.bot_url) {
      const botLink = document.getElementById("bot-link");
      if (botLink) {
        botLink.href = data.bot_url;
        botLink.classList.remove("hidden");
      }
    }
  } catch (e) {
    // остаётся заголовок по умолчанию
  }
}

// ---- Index page: plans + checkout ----
async function loadShopPlans() {
  const box = document.getElementById("plans-list");
  if (!box) return;
  try {
    const res = await fetch("/shop/api/plans");
    const plans = await res.json();
    if (!plans.length) {
      box.innerHTML = '<div class="hint">Тарифы пока не добавлены</div>';
      return;
    }
    box.innerHTML = plans
      .map(
        (p) => `
      <div class="plan-card">
        <h3>${p.title}</h3>
        <p>${p.description || ""}</p>
        <p>${p.data_limit_gb === 0 ? "Безлимит трафика" : p.data_limit_gb + " ГБ"}</p>
        <div class="price">${p.price_rub}₽</div>
        <button class="buy-btn" data-plan-id="${p.id}">Купить</button>
      </div>`
      )
      .join("");

    box.querySelectorAll(".buy-btn").forEach((btn) => {
      btn.addEventListener("click", () => buyPlan(parseInt(btn.dataset.planId, 10), btn));
    });
  } catch (e) {
    box.innerHTML = '<div class="hint">Не удалось загрузить тарифы</div>';
  }
}

async function buyPlan(planId, btn) {
  const email = (document.getElementById("email-input").value || "").trim();
  if (!email || !email.includes("@")) {
    alert("Укажи корректный email перед покупкой — на него не придёт письмо, но по нему привязывается подписка");
    document.getElementById("email-input").focus();
    return;
  }
  btn.disabled = true;
  btn.textContent = "Создаём заказ…";
  try {
    const res = await fetch("/shop/api/order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, plan_id: planId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Не удалось создать заказ");
    }
    const data = await res.json();
    window.location.href = data.redirect_url;
  } catch (e) {
    alert(e.message || "Ошибка. Попробуй ещё раз.");
    btn.disabled = false;
    btn.textContent = "Купить";
  }
}

// ---- success.html: poll order status ----
function getQueryParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

async function renderOrderStatus() {
  const box = document.getElementById("result-box");
  if (!box) return;
  const orderId = getQueryParam("order_id");
  if (!orderId) {
    box.className = "result-box error";
    box.innerHTML = "<h2>Заказ не найден</h2><p class=\"hint\">Не указан номер заказа.</p>";
    return;
  }

  const maxAttempts = 60; // ~2 минуты при интервале 2с
  let attempts = 0;

  async function poll() {
    attempts += 1;
    try {
      const res = await fetch(`/shop/api/order/${orderId}`);
      if (!res.ok) throw new Error("not found");
      const data = await res.json();

      if (data.status === "paid" && data.sub_url) {
        showSuccess(data);
        return;
      }
      if (data.status === "failed") {
        showFailure();
        return;
      }
      if (attempts >= maxAttempts) {
        showPending();
        return;
      }
      setTimeout(poll, 2000);
    } catch (e) {
      if (attempts >= maxAttempts) {
        showFailure();
      } else {
        setTimeout(poll, 2000);
      }
    }
  }

  poll();
}

async function showSuccess(data) {
  const box = document.getElementById("result-box");
  box.className = "result-box success";
  const expires = new Date(data.expires_at).toLocaleString("ru-RU");
  box.innerHTML = `
    <h2>✅ Оплата прошла успешно</h2>
    <p class="hint">Подписка активна до ${expires} (${data.data_limit_gb === 0 ? "безлимит" : data.data_limit_gb + " ГБ"})</p>
    <div id="qrcode"></div>
    <div class="sub-url">${data.sub_url}</div>
    <button class="copy-btn" id="copy-btn">Скопировать ссылку</button>
    <p class="hint" style="margin-top:16px">Сохрани эту ссылку — она понадобится, чтобы добавить подписку в приложение.</p>
    <div id="app-links" class="app-links"></div>
  `;
  new QRCode(document.getElementById("qrcode"), { text: data.sub_url, width: 180, height: 180 });
  document.getElementById("copy-btn").addEventListener("click", () => {
    navigator.clipboard.writeText(data.sub_url);
    alert("Ссылка скопирована");
  });
  loadAppLinks();
}

function showFailure() {
  const box = document.getElementById("result-box");
  box.className = "result-box error";
  box.innerHTML = `
    <h2>❌ Оплата не завершена</h2>
    <p class="hint">Платёж не прошёл или истекло время ожидания. Попробуй оформить заказ ещё раз.</p>
    <a class="buy-btn" style="display:inline-block; text-decoration:none;" href="/">Вернуться к тарифам</a>
  `;
}

function showPending() {
  const box = document.getElementById("result-box");
  box.innerHTML = `
    <h2>⏳ Платёж обрабатывается</h2>
    <p class="hint">Это может занять немного больше времени. Обнови страницу через минуту — обновление ссылки на эту же страницу безопасно.</p>
    <button class="copy-btn" onclick="location.reload()">Обновить</button>
  `;
}

async function loadAppLinks() {
  try {
    const res = await fetch("/api/apps");
    const data = await res.json();
    document.getElementById("app-links").innerHTML = data.items
      .map((a) => `<a href="${a.url}" target="_blank">${a.platform}: ${a.name}</a>`)
      .join("");
  } catch (e) {
    // не критично, просто не покажем ссылки на приложения
  }
}

loadConfig();
loadShopPlans();
