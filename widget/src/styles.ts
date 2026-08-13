/**
 * Styles live inside the Shadow DOM, so the host page cannot reach them and
 * they cannot leak out.
 *
 * Two layers of defence, because they cover different holes:
 *   - `all: initial` on `:host` blocks inherited properties crossing in.
 *   - the same typography is restated on `.tricv`, because a host page rule
 *     that targets the host element (`div { text-align: center }`) beats any
 *     `:host` rule by spec, whatever the specificity. `.tricv` lives inside
 *     the shadow root, where outside selectors cannot reach it at all.
 */
export const CSS = `
:host {
  all: initial;
  display: block;
}
* { box-sizing: border-box; }

.tricv {
  border: 1px solid #d7dce2;
  border-radius: 12px;
  background: #fff;
  padding: 20px;
  max-width: 520px;
  font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif;
  font-size: 14px;
  font-weight: 400;
  font-style: normal;
  letter-spacing: normal;
  text-transform: none;
  text-align: left;
  color: #1f2933;
  line-height: 1.5;
}
.tricv h2 {
  margin: 0 0 2px;
  font-size: 17px;
  font-weight: 600;
  color: #1f2933;
}
.tricv .position { margin: 0 0 16px; font-size: 13px; color: #6b7280; }

.field { margin-bottom: 14px; }
.field > label {
  display: block;
  margin-bottom: 5px;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
}
.field input[type="text"],
.field input[type="email"],
.field input[type="tel"] {
  width: 100%;
  padding: 9px 11px;
  font: inherit;
  font-size: 14px;
  color: #1f2933;
  background: #fff;
  border: 1px solid #d7dce2;
  border-radius: 8px;
}
.field input:focus {
  outline: none;
  border-color: #3b8fef;
  box-shadow: 0 0 0 1px #3b8fef;
}
.field input[aria-invalid="true"] { border-color: #dc2626; }

.file-row { display: flex; align-items: center; gap: 10px; }
.file-name {
  font-size: 13px;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
input[type="file"] {
  position: absolute;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap; border: 0;
}

button {
  font: inherit;
  font-size: 14px;
  font-weight: 500;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color .15s ease;
}
button.secondary {
  padding: 8px 12px;
  color: #374151;
  background: #fff;
  border: 1px solid #d7dce2;
}
button.secondary:hover { background: #f6f7f9; }
button.primary {
  width: 100%;
  padding: 10px 14px;
  margin-top: 4px;
  color: #fff;
  background: #1f2933;
  border: 0;
}
button.primary:hover:not(:disabled) { background: #252f3b; }
button.primary:disabled { opacity: .55; cursor: not-allowed; }

.hint { margin: 5px 0 0; font-size: 12px; color: #6b7280; }
.error { margin: 5px 0 0; font-size: 12px; color: #dc2626; }
.form-error {
  margin: 0 0 12px;
  padding: 9px 11px;
  font-size: 13px;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
}
.privacy {
  margin: 14px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: #9aa3af;
  text-align: center;
}

.state { padding: 32px 20px; text-align: center; }
.state .icon {
  display: grid;
  place-items: center;
  width: 44px; height: 44px;
  margin: 0 auto 12px;
  font-size: 20px;
  border-radius: 999px;
  background: #d1fae5;
  color: #047857;
}
.state h3 { margin: 0 0 6px; font-size: 16px; font-weight: 600; }
.state p { margin: 0; font-size: 13px; color: #6b7280; }

.spinner {
  display: inline-block;
  width: 14px; height: 14px;
  margin-right: 6px;
  vertical-align: -2px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 999px;
  animation: tricv-spin .7s linear infinite;
}
@keyframes tricv-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 2s; } }

.branding { margin: 12px 0 0; font-size: 11px; color: #b4bdc8; text-align: center; }
`
