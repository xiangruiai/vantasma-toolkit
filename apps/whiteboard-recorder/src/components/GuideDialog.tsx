import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { UI_TEXT, type LanguageCode } from '../i18n';
import guideMarkdownEn from '../content/operation-guide.en.md?raw';
import guideMarkdownZh from '../content/operation-guide.zh.md?raw';
import './GuideDialog.css';

interface GuideDialogProps {
  language: LanguageCode;
  onClose: () => void;
}

const removeLeadingTitle = (markdown: string) =>
  markdown.replace(/^# .*(?:\r?\n){1,2}/, '');

function GuideDialog({ language, onClose }: GuideDialogProps) {
  const text = UI_TEXT[language].settings;
  const markdown = removeLeadingTitle(language === 'zh-CN' ? guideMarkdownZh : guideMarkdownEn);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', closeOnEscape, true);
    return () => window.removeEventListener('keydown', closeOnEscape, true);
  }, [onClose]);

  return (
    <div
      className="guide-dialog-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        className="guide-dialog-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="guide-dialog-title"
      >
        <header className="guide-dialog-header">
          <div className="guide-dialog-title-lockup">
            <img
              className="guide-dialog-mark"
              src="/xiangrui-logo.png"
              alt=""
              aria-hidden="true"
            />
            <div>
              <p>{text.guideTitle}</p>
              <h2 id="guide-dialog-title">{text.guideDialogTitle}</h2>
            </div>
          </div>
          <button
            type="button"
            className="guide-dialog-close"
            aria-label={text.guideCloseLabel}
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="guide-dialog-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ children, ...props }) => (
                <a {...props} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
              pre: ({ children }) => (
                <pre className="guide-markdown-codeblock">{children}</pre>
              ),
              code: ({ children, className, ...props }) => (
                <code
                  {...props}
                  className={className ? `guide-markdown-code ${className}` : 'guide-markdown-inline-code'}
                >
                  {children}
                </code>
              ),
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      </section>
    </div>
  );
}

export default GuideDialog;
