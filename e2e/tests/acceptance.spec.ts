import { expect, test } from "@playwright/test";

test("AT01 shell opens", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("MAIL-AGENT")).toBeVisible();
  await expect(page.getByRole("link", { name: "Список тредов" })).toBeVisible();
});

test("settings screen and mock connection", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Настройки" })).toBeVisible();
  await expect(page.getByText("пароль приложения")).toBeVisible();
  await page.getByRole("button", { name: "Проверить подключение" }).click();
  await expect(page.getByText("Подключение успешно")).toBeVisible();
});

test("sync mock mailbox and open a thread", async ({ page }) => {
  test.setTimeout(600000);
  await page.goto("/");
  await page.getByRole("button", { name: "Синхронизировать" }).click();
  await expect(page.getByRole("link", { name: /Ромашка/ })).toBeVisible({ timeout: 540000 });
  await page.getByRole("link", { name: /Ромашка/ }).click();
  await expect(page.getByText("От:", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Саммари", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Чат" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Черновик" })).toBeVisible();
});

test("summary, ask, draft and digest", async ({ page }) => {
  test.setTimeout(600000);
  await page.goto("/");
  await page.getByRole("link", { name: /Ромашка/ }).click();
  await page.getByRole("button", { name: "Обновить саммари" }).click();
  await expect(page.locator(".model-text, .banner.error").first()).toBeVisible({ timeout: 300000 });

  await page.getByRole("button", { name: "Чат" }).click();
  await page.getByLabel("Вопрос").fill("На какой срок сдвинули сдачу по п. 4.2?");
  await page.getByRole("button", { name: "Спросить" }).click();
  await expect(page.locator(".model-text, .banner.error").first()).toBeVisible({ timeout: 300000 });

  await page.getByRole("button", { name: "Черновик" }).click();
  await page.getByRole("button", { name: "Составить черновик" }).click();
  await expect(page.locator(".model-text, .banner.error").first()).toBeVisible({ timeout: 300000 });
  const draft = page.locator(".model-text");
  if (await draft.count()) {
    await page.getByRole("button", { name: "Скопировать в почту" }).click();
    await expect(page.getByText(/скопирован|Выделите текст/)).toBeVisible();
  }

  await page.goto("/digest");
  await page.getByRole("button", { name: "Обновить сводку" }).click();
  await expect(page.getByRole("heading", { name: "Срочные письма" })).toBeVisible();
  await expect(page.locator(".urgent, .banner.error, .task").first()).toBeVisible({ timeout: 300000 });
});

test("missing model returns an error and keeps mail", async ({ page, request }) => {
  const settings = await request.get("/api/settings");
  expect(settings.ok()).toBeTruthy();
  const current = await settings.json();
  const broken = await request.put("/api/settings", {
    data: { ...current, model_name: "missing-model-for-at10" },
  });
  expect(broken.ok()).toBeTruthy();

  await page.goto("/");
  await expect(page.getByRole("link", { name: /Ромашка/ })).toBeVisible();
  await page.getByRole("link", { name: /Ромашка/ }).click();
  await page.getByRole("button", { name: "Обновить саммари" }).click();
  await expect(page.getByRole("alert")).toContainText(/Модель|Ollama|генерации/, { timeout: 180000 });
  await expect(page.getByText("От:", { exact: false }).first()).toBeVisible();

  const restored = await request.put("/api/settings", {
    data: { ...current, model_name: current.model_name },
  });
  expect(restored.ok()).toBeTruthy();
});
