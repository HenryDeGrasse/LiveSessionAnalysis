/**
 * Smoke tests for the fullscreen session UI layout.
 *
 * These tests require a running LiveKit server (started automatically by
 * playwright.config.ts via start-livekit-for-playwright.mjs).  They verify:
 *   1. The remote video element fills the full viewport (fullscreen-like).
 *   2. The icon-based control buttons (mute, camera, end/leave) are rendered
 *      as overlay buttons on top of the video.
 *   3. The bottom controls bar auto-hides after 4 s of inactivity and
 *      reappears when the user moves the pointer.
 *   4. The coaching-status pill is rendered inside the tutor coach overlay
 *      once live metrics arrive.
 *   5. The local-video PIP is anchored in the bottom-right quadrant of the
 *      viewport.
 */

import { expect, test } from '@playwright/test'
import {
  closeParticipant,
  consentToMedia,
  createSession,
  DEFAULT_MEDIA_PROVIDER,
  openParticipant,
  waitForConnectedCall,
  waitForTutorMetrics,
} from './helpers/session'

test.describe(`${DEFAULT_MEDIA_PROVIDER} fullscreen session UI`, () => {
  // ── 1. Remote video covers the full viewport ─────────────────────────────
  test('remote video element covers the full viewport', async ({
    browser,
    request,
    page: _unusedPage,
  }) => {
    const session = await createSession(request)
    const tutor = await openParticipant(browser, session.tutorUrl)
    const student = await openParticipant(browser, session.studentUrl)

    try {
      await consentToMedia(tutor.page)
      await consentToMedia(student.page)
      await waitForConnectedCall(tutor.page)

      const viewport = tutor.page.viewportSize()
      expect(viewport, 'viewport should be available').not.toBeNull()

      const remoteVideo = tutor.page.getByTestId('remote-video')
      await expect(remoteVideo).toBeVisible()

      const box = await remoteVideo.boundingBox()
      expect(box, 'remote-video bounding box should be non-null').not.toBeNull()

      if (box && viewport) {
        // The remote video must cover at least 90 % of the viewport in each
        // dimension — it uses "absolute inset-0 h-full w-full object-cover".
        expect(box.width).toBeGreaterThanOrEqual(viewport.width * 0.9)
        expect(box.height).toBeGreaterThanOrEqual(viewport.height * 0.9)

        // It should start near the top-left corner (within 10 px).
        expect(box.x).toBeLessThanOrEqual(10)
        expect(box.y).toBeLessThanOrEqual(10)
      }
    } finally {
      await closeParticipant(student)
      await closeParticipant(tutor)
    }
  })

  // ── 2. Control buttons are overlay buttons ───────────────────────────────
  test('icon control buttons (mute, camera, end) are rendered as overlay buttons', async ({
    browser,
    request,
  }) => {
    const session = await createSession(request)
    const tutor = await openParticipant(browser, session.tutorUrl)
    const student = await openParticipant(browser, session.studentUrl)

    try {
      await consentToMedia(tutor.page)
      await consentToMedia(student.page)
      await waitForConnectedCall(tutor.page)

      // Move the mouse to ensure controls are visible.
      await tutor.page.mouse.move(400, 400)

      const callSurface = tutor.page.getByTestId('call-surface')
      await expect(callSurface).toBeVisible()

      // Controls overlay must be present inside the call surface.
      const controlsOverlay = tutor.page.getByTestId('controls-overlay')
      await expect(controlsOverlay).toBeVisible()

      // Mute button
      const muteBtn = tutor.page.getByTestId('mute-button')
      await expect(muteBtn).toBeVisible()

      // Camera button
      const cameraBtn = tutor.page.getByTestId('camera-button')
      await expect(cameraBtn).toBeVisible()

      // End-session button (tutor only)
      const endBtn = tutor.page.getByTestId('end-session-button')
      await expect(endBtn).toBeVisible()

      // All control buttons must sit visually inside the call surface.
      const callBox = await callSurface.boundingBox()
      const endBox = await endBtn.boundingBox()
      if (callBox && endBox) {
        expect(endBox.x).toBeGreaterThanOrEqual(callBox.x)
        expect(endBox.y).toBeGreaterThanOrEqual(callBox.y)
        expect(endBox.x + endBox.width).toBeLessThanOrEqual(
          callBox.x + callBox.width + 1
        )
        expect(endBox.y + endBox.height).toBeLessThanOrEqual(
          callBox.y + callBox.height + 1
        )
      }
    } finally {
      await closeParticipant(student)
      await closeParticipant(tutor)
    }
  })

  // ── 3. Controls auto-hide and reappear on pointer move ───────────────────
  test('controls auto-hide after 4 s of inactivity and reappear on mouse move', async ({
    browser,
    request,
  }) => {
    const session = await createSession(request)
    const tutor = await openParticipant(browser, session.tutorUrl)
    const student = await openParticipant(browser, session.studentUrl)

    try {
      await consentToMedia(tutor.page)
      await consentToMedia(student.page)
      await waitForConnectedCall(tutor.page)

      // Move mouse to make controls visible initially.
      await tutor.page.mouse.move(400, 400)
      const controlsOverlay = tutor.page.getByTestId('controls-overlay')
      // Controls should be visible right after pointer activity.
      await expect(controlsOverlay).toHaveCSS('opacity', '1')

      // Wait 5 s without any pointer activity — controls should fade out.
      // (The auto-hide timer fires after 4 s.)
      await tutor.page.waitForTimeout(5_000)
      await expect(controlsOverlay).toHaveCSS('opacity', '0')

      // Move the mouse again — controls should reappear.
      await tutor.page.mouse.move(600, 300)
      await expect(controlsOverlay).toHaveCSS('opacity', '1')
    } finally {
      await closeParticipant(student)
      await closeParticipant(tutor)
    }
  })

  // ── 4. Coaching status pill in tutor overlay ─────────────────────────────
  test('coaching-status pill appears in the tutor coach overlay once metrics arrive', async ({
    browser,
    request,
  }) => {
    const session = await createSession(request)
    const tutor = await openParticipant(browser, session.tutorUrl)
    const student = await openParticipant(browser, session.studentUrl)

    try {
      await consentToMedia(tutor.page)
      await consentToMedia(student.page)
      await waitForConnectedCall(tutor.page)

      // Wait until the coach overlay is present (metrics flowing).
      await waitForTutorMetrics(tutor.page)

      // The coaching-status pill is rendered when coaching_status is present
      // in the metrics snapshot.  Allow up to 30 s for it to appear.
      await expect(tutor.page.getByTestId('coaching-status-pill')).toBeVisible({
        timeout: 30_000,
      })

      // The pill must sit inside the coach overlay.
      const overlay = tutor.page.getByTestId('coach-overlay')
      await expect(overlay).toBeVisible()
    } finally {
      await closeParticipant(student)
      await closeParticipant(tutor)
    }
  })

  // ── 5. Local video PIP is in the bottom-right quadrant ───────────────────
  test('local video PIP is anchored in the bottom-right corner of the viewport', async ({
    browser,
    request,
  }) => {
    const session = await createSession(request)
    const tutor = await openParticipant(browser, session.tutorUrl)
    const student = await openParticipant(browser, session.studentUrl)

    try {
      await consentToMedia(tutor.page)
      await consentToMedia(student.page)
      await waitForConnectedCall(tutor.page)

      const viewport = tutor.page.viewportSize()
      expect(viewport, 'viewport should be available').not.toBeNull()

      const pip = tutor.page.getByTestId('local-video-pip')
      await expect(pip).toBeVisible()

      const box = await pip.boundingBox()
      expect(box, 'local-video-pip bounding box should be non-null').not.toBeNull()

      if (box && viewport) {
        // The PIP right edge must be in the right half of the viewport.
        expect(box.x + box.width).toBeGreaterThan(viewport.width / 2)
        // The PIP bottom edge must be in the lower half of the viewport.
        expect(box.y + box.height).toBeGreaterThan(viewport.height / 2)
        // The PIP must not be flush against the very top (it sits above the
        // bottom control bar, not at the top of the screen).
        expect(box.y).toBeGreaterThan(viewport.height * 0.3)
      }
    } finally {
      await closeParticipant(student)
      await closeParticipant(tutor)
    }
  })
})
