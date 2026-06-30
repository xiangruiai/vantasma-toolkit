/**
 * MobileLanding - Shown to mobile users instead of the main app
 *
 * Since the recorder needs a desktop browser (webcam positioning, canvas recording),
 * we show mobile users a nice landing page where they can send themselves a link.
 */

import { useState, useEffect } from 'react';
import './MobileLanding.css';
import { trackMobileEmailSent } from '../utils/analytics';
import { UI_TEXT, type LanguageCode } from '../i18n';

interface MobileLandingProps {
  language: LanguageCode;
  onLanguageChange: (language: LanguageCode) => void;
}

function MobileLanding({ language, onLanguageChange }: MobileLandingProps) {
  const text = UI_TEXT[language];
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [errorMessage, setErrorMessage] = useState('');

  const appUrl = window.location.href;

  // Override global overflow:hidden to allow scrolling on mobile
  useEffect(() => {
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';
    return () => {
      document.body.style.overflow = '';
      document.documentElement.style.overflow = '';
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!email || !email.includes('@')) {
      setErrorMessage(text.mobile.validEmail);
      setStatus('error');
      return;
    }

    setStatus('sending');

    try {
      const response = await fetch('/api/send-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, url: appUrl }),
      });

      if (response.ok) {
        setStatus('sent');
        trackMobileEmailSent(true);
      } else {
        const data = await response.json();
        setErrorMessage(data.error || text.mobile.sendFailed);
        setStatus('error');
        trackMobileEmailSent(false);
      }
    } catch {
      setErrorMessage(text.mobile.networkError);
      setStatus('error');
    }
  };

  const handleShare = async () => {
    if ('share' in navigator) {
      try {
        await navigator.share({
          title: text.common.appName,
          text: text.mobile.shareText,
          url: appUrl,
        });
      } catch {
        // User cancelled or share failed - that's fine
      }
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(appUrl);
      alert(text.alerts.linkCopied);
    } catch {
      // Fallback for older browsers
      prompt(text.alerts.copyPrompt, appUrl);
    }
  };

  return (
    <div className="mobile-landing">
      {/* Ambient background */}
      <div className="mobile-bg" />

      <div className="mobile-content">
        <div className="mobile-language-switcher">
          <button
            className={language === 'zh-CN' ? 'active' : ''}
            onClick={() => onLanguageChange('zh-CN')}
            aria-label={text.language.ariaLabel}
          >
            {text.language.zh}
          </button>
          <button
            className={language === 'en' ? 'active' : ''}
            onClick={() => onLanguageChange('en')}
            aria-label={text.language.ariaLabel}
          >
            {text.language.en}
          </button>
        </div>

        {/* Logo / Icon */}
        <div className="mobile-icon">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="4" y="6" width="40" height="30" rx="4" stroke="currentColor" strokeWidth="2.5"/>
            <circle cx="34" cy="26" r="7" fill="#ef4444"/>
            <circle cx="34" cy="26" r="3" fill="white"/>
            <path d="M12 16h14M12 22h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        </div>

        {/* Headline */}
        <h1 className="mobile-headline">
          {text.common.appName}
        </h1>

        <p className="mobile-subheadline">
          {text.mobile.subtitle}
        </p>

        {/* Desktop only notice */}
        <div className="mobile-notice">
          <span className="notice-icon">💻</span>
          <span>{text.mobile.desktopRequired}</span>
        </div>

        {/* Email form or success state */}
        {status === 'sent' ? (
          <div className="mobile-success">
            <span className="success-icon">✓</span>
            <p>{text.mobile.sent}</p>
          </div>
        ) : (
          <form className="mobile-form" onSubmit={handleSubmit}>
            <p className="form-label">{text.mobile.formLabel}</p>
            <div className="form-row">
              <input
                type="email"
                placeholder={text.mobile.emailPlaceholder}
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (status === 'error') setStatus('idle');
                }}
                className={status === 'error' ? 'input-error' : ''}
                disabled={status === 'sending'}
              />
              <button type="submit" disabled={status === 'sending'}>
                {status === 'sending' ? text.mobile.sending : text.mobile.send}
              </button>
            </div>
            {status === 'error' && (
              <p className="form-error">{errorMessage}</p>
            )}
          </form>
        )}

        {/* Alternative actions */}
        <div className="mobile-alternatives">
          <span className="alt-divider">{text.mobile.or}</span>
          <div className="alt-buttons">
            {'share' in navigator && (
              <button className="alt-btn" onClick={handleShare}>
                <span>↗</span> {text.mobile.share}
              </button>
            )}
            <button className="alt-btn" onClick={handleCopy}>
              <span>⎘</span> {text.mobile.copyLink}
            </button>
          </div>
        </div>

        {/* Preview image - shows what the recorded video looks like */}
        <div className="mobile-preview">
          <div className="preview-mockup">
            <div className="mockup-canvas">
              {/* Excalidraw-style flowchart */}
              <svg className="whiteboard-content" viewBox="0 0 320 200" fill="none" xmlns="http://www.w3.org/2000/svg">
                {/* Top box - "Start" */}
                <path d="M50 25 C52 24 85 23 110 24 C112 35 113 50 111 62 C85 63 52 64 50 62 C48 50 49 35 50 25" stroke="#1e1e1e" strokeWidth="1.6" fill="none" strokeLinecap="round"/>
                <path d="M65 42 C70 41 85 42 95 41" stroke="#1e1e1e" strokeWidth="1.4" strokeLinecap="round"/>

                {/* Arrow down from top box */}
                <path d="M80 64 C81 75 79 90 80 100" stroke="#1e1e1e" strokeWidth="1.6" fill="none" strokeLinecap="round"/>
                <path d="M74 92 L80 102 L86 92" stroke="#1e1e1e" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round"/>

                {/* Middle diamond - decision */}
                <path d="M80 105 L115 130 L80 155 L45 130 Z" stroke="#1971c2" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M65 130 C70 129 90 130 95 129" stroke="#1971c2" strokeWidth="1.2" strokeLinecap="round"/>

                {/* Arrow right from diamond */}
                <path d="M117 130 C140 131 165 129 185 130" stroke="#1e1e1e" strokeWidth="1.6" fill="none" strokeLinecap="round"/>
                <path d="M177 124 L187 130 L177 136" stroke="#1e1e1e" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round"/>

                {/* Right box */}
                <path d="M190 110 C192 109 225 108 250 109 C252 120 253 140 251 152 C225 153 192 154 190 152 C188 140 189 120 190 110" stroke="#e03131" strokeWidth="1.6" fill="none" strokeLinecap="round"/>
                <path d="M205 128 C210 127 230 128 240 127" stroke="#e03131" strokeWidth="1.4" strokeLinecap="round"/>

                {/* Arrow down from diamond */}
                <path d="M80 157 C81 165 79 175 80 182" stroke="#1e1e1e" strokeWidth="1.6" fill="none" strokeLinecap="round"/>
              </svg>

              {/* Profile avatar with circular outline */}
              <div className="mockup-avatar">
                <img src="/avatar.png" alt={text.mobile.avatarAlt} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default MobileLanding;
