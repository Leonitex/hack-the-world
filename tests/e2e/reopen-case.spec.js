// Reopen cases: unfinished investigations stay open across case switches,
// keep their evidence/hypotheses/pending test, and only an explicit
// technician action marks them solved or reopens them. Runs against the
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

test('unfinished cases switch, solve, and reopen without losing context', async ({
  page,
}) => {
  await page.locator('#problemInput').fill('E2E reopen case A');
  await page.getByRole('button', { name: 'Begin investigation' }).click();
  await expect(page.locator('.card.next .big-action')).toContainText('E2E check one');

  await page.locator('#answerInput').fill('E2E result A1');
  await page.getByRole('button', { name: 'Submit & continue' }).click();
  await expect(page.locator('.card.next .big-action')).toContainText('E2E check two');

  // Starting a second case must not close the first.
  await page.getByRole('button', { name: 'Start a new investigation' }).click();
  await page.locator('#problemInput').fill('E2E reopen case B');
  await page.getByRole('button', { name: 'Begin investigation' }).click();
  await expect(page.locator('.card.next .big-action')).toContainText('E2E check one');

  // Returning to A preserves its pending test and recorded context.
  const rowA = page.locator('.sessions li', { hasText: 'E2E reopen case A' });
  await expect(rowA).toContainText('awaiting result');
  await rowA.getByRole('button', { name: 'Open' }).click();
  await expect(page.locator('.card.next .big-action')).toContainText('E2E check two');
  await expect(page.locator('.timeline')).toContainText('E2E result A1');
  await expect(page.locator('.timeline')).toContainText('E2E Cause C');

  // The investigation continues with its history intact.
  await page.locator('#answerInput').fill('E2E result A2');
  await page.getByRole('button', { name: 'Submit & continue' }).click();
  await expect(page.locator('.card.next .big-action')).toContainText('E2E check three');
  await expect(page.locator('.timeline')).toContainText('E2E result A2');

  // Only the technician closes the case, with an audit trail.
  await page.locator('input[name="note"]').fill('E2E repair note');
  await page.getByRole('button', { name: 'Mark solved' }).click();
  await expect(page.locator('h2', { hasText: 'Case solved' })).toBeVisible();
  await expect(page.locator('.timeline')).toContainText('Marked solved');
  const solvedRow = page.locator('.sessions li', { hasText: 'E2E reopen case A' });
  await expect(solvedRow).toContainText('solved');

  // Reopening restores the open case with its pending test intact.
  await page.getByRole('button', { name: 'Reopen case' }).click();
  await expect(page.locator('.card.next .big-action')).toContainText('E2E check three');
  await expect(page.locator('.timeline')).toContainText('Case reopened');
  const openRow = page.locator('.sessions li', { hasText: 'E2E reopen case A' });
  await expect(openRow).toContainText('awaiting result');
});
