// Smoke flow: intake -> first test -> real result -> different follow-up
// test -> history survives reload. Runs against the deterministic E2E
// fixture (HTW_E2E_FAKE_PROVIDER=1); no live keys, no network models.
const { test, expect } = require('@playwright/test');

test('technician completes two distinct diagnostic turns', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('svg.orb-svg')).toBeVisible();
  await page.locator('#problemInput').fill('E2E laptop has no display');
  await page.getByRole('button', { name: 'Begin investigation' }).click();

  const firstTest = page.locator('.card.next .big-action');
  await expect(firstTest).toContainText('E2E check one');
  const firstText = (await firstTest.textContent()) || '';

  await page.locator('#answerInput').fill('E2E observed result one');
  await page.getByRole('button', { name: 'Submit & continue' }).click();

  const secondTest = page.locator('.card.next .big-action');
  await expect(secondTest).toContainText('E2E check two');
  const secondText = (await secondTest.textContent()) || '';
  expect(secondText).not.toEqual(firstText);

  // Previous instruction remains available in the persistent history.
  await expect(page.locator('.timeline')).toContainText('E2E check one');
  await expect(page.locator('.timeline')).toContainText('E2E observed result one');
});

test('history survives a page reload', async ({ page }) => {
  await page.goto('/');
  await page.locator('#problemInput').fill('E2E laptop has no display');
  await page.getByRole('button', { name: 'Begin investigation' }).click();
  await expect(page.locator('.card.next .big-action')).toContainText('E2E check one');

  await page.reload();
  await expect(page.locator('.card.next .big-action')).toContainText('E2E check one');
  await expect(page.locator('.timeline')).toContainText('Session started');
});
