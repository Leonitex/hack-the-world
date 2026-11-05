// Repeat guard: the scripted model re-asks an answered test verbatim and the
// app must block it, presenting a distinct follow-up instead. The first
// instruction stays in the timeline exactly once. Runs against the
// deterministic E2E fixture (HTW_E2E_FAKE_PROVIDER=1); no live keys.
const { test, expect } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page
    .locator('#problemInput, button:has-text("Start a new investigation")')
    .first()
    .waitFor();
  const reset = page.getByRole('button', { name: 'Start a new investigation' });
  if ((await reset.count()) > 0) {
    await reset.click();
  }
});

test('an answered test is never asked twice', async ({ page }) => {
  await page.locator('#problemInput').fill('E2E e2e-repeat device is silent');
  await page.getByRole('button', { name: 'Begin investigation' }).click();

  const firstTest = page.locator('.card.next .big-action');
  await expect(firstTest).toContainText('E2E repeat check');

  await page.locator('#answerInput').fill('E2E observed repeat result');
  await page.getByRole('button', { name: 'Submit & continue' }).click();

  // The verbatim repeat is blocked; a distinct follow-up is presented.
  const secondTest = page.locator('.card.next .big-action');
  await expect(secondTest).toContainText('E2E distinct follow-up');

  // The answered instruction remains in the timeline exactly once.
  const repeatEntries = page.locator('.timeline .t-body:has-text("E2E repeat check")');
  await expect(repeatEntries).toHaveCount(1);
  await expect(page.locator('.timeline')).toContainText('E2E observed repeat result');
  await expect(page.locator('.timeline')).toContainText('E2E distinct follow-up');
});
