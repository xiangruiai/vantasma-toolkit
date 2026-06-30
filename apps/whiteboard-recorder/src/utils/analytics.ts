/**
 * Analytics utility using PostHog
 *
 * Tracks user behavior to understand:
 * - How many people start vs complete recordings
 * - Which features are most used
 * - Where users drop off
 * - Mobile vs desktop split
 */

import posthog from 'posthog-js';

// Initialize PostHog - call this once when app loads
export function initAnalytics() {
  const apiKey = import.meta.env.VITE_POSTHOG_KEY;

  if (!apiKey) {
    console.log('PostHog not configured - analytics disabled');
    return;
  }

  posthog.init(apiKey, {
    api_host: 'https://us.i.posthog.com',
    // Capture pageviews automatically
    capture_pageview: true,
    // Capture clicks on links and buttons
    autocapture: true,
    // Respect Do Not Track
    respect_dnt: true,
    // Disable in development
    loaded: (posthog) => {
      if (import.meta.env.DEV) {
        posthog.opt_out_capturing();
      }
    }
  });
}

// ============ CUSTOM EVENTS ============

// Track when user views the app (with device type)
export function trackPageView(isMobile: boolean) {
  posthog.capture('page_view', {
    device_type: isMobile ? 'mobile' : 'desktop'
  });
}

// Track when recording starts
export function trackRecordingStarted(settings: {
  aspectRatio: string;
  background: string;
  webcamEnabled: boolean;
  webcamPosition: string;
}) {
  posthog.capture('recording_started', settings);
}

// Track when recording is completed
export function trackRecordingCompleted(data: {
  durationSeconds: number;
  aspectRatio: string;
  background: string;
  webcamEnabled: boolean;
  usedTeleprompter: boolean;
  usedPause: boolean;
}) {
  posthog.capture('recording_completed', {
    ...data,
    duration_minutes: Math.round(data.durationSeconds / 60 * 10) / 10
  });
}

// Track when recording is cancelled
export function trackRecordingCancelled(stage: 'preview' | 'during_recording') {
  posthog.capture('recording_cancelled', { stage });
}

// Track video download
export function trackVideoDownloaded(data: {
  durationSeconds: number;
  format: string;
}) {
  posthog.capture('video_downloaded', {
    ...data,
    duration_minutes: Math.round(data.durationSeconds / 60 * 10) / 10
  });
}

// Track teleprompter usage
export function trackTeleprompterUsed(action: 'opened' | 'closed' | 'scrolled') {
  posthog.capture('teleprompter_used', { action });
}

// Track settings changes
export function trackSettingsChanged(setting: string, value: string) {
  posthog.capture('settings_changed', { setting, value });
}

// Track mobile email sent
export function trackMobileEmailSent(success: boolean) {
  posthog.capture('mobile_email_sent', { success });
}

// Track welcome modal dismissed
export function trackWelcomeModalDismissed() {
  posthog.capture('welcome_modal_dismissed');
}

// Track errors
export function trackError(error: string, context?: Record<string, unknown>) {
  posthog.capture('error_occurred', { error, ...context });
}
