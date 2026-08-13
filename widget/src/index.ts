/**
 * TriCV embeddable application form.
 *
 *   <div id="tricv-widget"></div>
 *   <script src="https://<host>/widget.js"
 *           data-session-key="PUBLIC_KEY"
 *           data-lang="fr"></script>
 *
 * Renders inside a Shadow DOM so the host page's CSS cannot break it, and
 * posts straight to the TriCV public API. No framework runtime, one file.
 */

import { stringsFor, type Strings } from './i18n'
import { CSS } from './styles'

interface PublicSession {
  title: string
  position: string
  description: string | null
  department: string | null
  language: 'fr' | 'en'
  accepts_applications: boolean
}

interface Config {
  apiUrl: string
  sessionKey: string
  lang: string | null
  target: string
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function readConfig(script: HTMLScriptElement | null): Config | null {
  if (!script) return null
  const sessionKey = script.getAttribute('data-session-key')
  if (!sessionKey) {
    console.error('[TriCV] the widget script needs a data-session-key attribute')
    return null
  }
  // The API host is wherever this script was served from, unless overridden.
  const explicit = script.getAttribute('data-api-url')
  const apiUrl = (explicit ?? new URL(script.src, window.location.href).origin).replace(/\/$/, '')
  return {
    apiUrl,
    sessionKey,
    lang: script.getAttribute('data-lang'),
    target: script.getAttribute('data-target') ?? 'tricv-widget',
  }
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  children: Array<Node | string> = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value)
  for (const child of children) {
    node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child)
  }
  return node
}

function stateBlock(icon: string, title: string, body: string, tone = '#d1fae5'): HTMLElement {
  const iconEl = el('div', { class: 'icon' }, [icon])
  iconEl.style.background = tone
  return el('div', { class: 'state' }, [iconEl, el('h3', {}, [title]), el('p', {}, [body])])
}

function mount(config: Config): void {
  const host = document.getElementById(config.target)
  if (!host) {
    console.error(`[TriCV] no element with id "${config.target}" found`)
    return
  }
  if (host.shadowRoot) return // already mounted (double-included script)

  const root = host.attachShadow({ mode: 'open' })
  const style = document.createElement('style')
  style.textContent = CSS
  root.appendChild(style)

  const container = el('div', { class: 'tricv' })
  root.appendChild(container)

  let strings: Strings = stringsFor(config.lang)
  container.appendChild(el('p', { class: 'hint' }, [strings.loading]))

  fetch(`${config.apiUrl}/api/v1/public/session/${encodeURIComponent(config.sessionKey)}`)
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      return response.json() as Promise<PublicSession>
    })
    .then((session) => {
      // data-lang wins; otherwise follow the session's own language.
      strings = stringsFor(config.lang ?? session.language)
      container.textContent = ''

      if (!session.accepts_applications) {
        container.appendChild(
          stateBlock('—', strings.closedTitle, strings.closedBody, '#fef3c7'),
        )
        return
      }
      renderForm(container, config, session, strings)
    })
    .catch((error: unknown) => {
      console.error('[TriCV]', error)
      container.textContent = ''
      container.appendChild(stateBlock('!', strings.errorTitle, strings.errorBody, '#fee2e2'))
    })
}

function renderForm(
  container: HTMLElement,
  config: Config,
  session: PublicSession,
  strings: Strings,
): void {
  container.appendChild(el('h2', {}, [session.position]))
  container.appendChild(
    el('p', { class: 'position' }, [
      session.department ? `${session.title} · ${session.department}` : session.title,
    ]),
  )

  const form = el('form', { novalidate: 'novalidate' })
  const formError = el('p', { class: 'form-error', role: 'alert' })
  formError.style.display = 'none'
  form.appendChild(formError)

  const field = (
    id: string,
    label: string,
    type: string,
    autocomplete: string,
  ): { wrap: HTMLElement; input: HTMLInputElement; error: HTMLElement } => {
    const input = el('input', { id, type, autocomplete }) as HTMLInputElement
    const error = el('p', { class: 'error' })
    error.style.display = 'none'
    const wrap = el('div', { class: 'field' }, [
      el('label', { for: id }, [label]),
      input,
      error,
    ])
    return { wrap, input, error }
  }

  const name = field('tricv-name', strings.fullName, 'text', 'name')
  const email = field('tricv-email', strings.email, 'email', 'email')
  const phone = field('tricv-phone', strings.phone, 'tel', 'tel')
  form.appendChild(name.wrap)
  form.appendChild(email.wrap)
  form.appendChild(phone.wrap)

  // --- file picker (the native control is hidden; the button drives it) ---
  const fileInput = el('input', {
    id: 'tricv-cv',
    type: 'file',
    accept:
      '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  }) as HTMLInputElement
  const fileName = el('span', { class: 'file-name' }, [strings.noFile])
  const fileButton = el('button', { type: 'button', class: 'secondary' }, [strings.chooseFile])
  const fileError = el('p', { class: 'error' })
  fileError.style.display = 'none'

  fileButton.addEventListener('click', () => fileInput.click())
  fileInput.addEventListener('change', () => {
    const picked = fileInput.files?.[0]
    fileName.textContent = picked ? picked.name : strings.noFile
    fileError.style.display = 'none'
  })

  form.appendChild(
    el('div', { class: 'field' }, [
      el('label', { for: 'tricv-cv' }, [strings.cv]),
      fileInput,
      el('div', { class: 'file-row' }, [fileButton, fileName]),
      el('p', { class: 'hint' }, [strings.cvHint]),
      fileError,
    ]),
  )

  const submit = el('button', { type: 'submit', class: 'primary' }, [strings.submit])
  form.appendChild(submit)
  form.appendChild(el('p', { class: 'privacy' }, [strings.privacy]))

  container.appendChild(form)
  container.appendChild(el('p', { class: 'branding' }, ['TriCV']))

  function setError(target: { input: HTMLInputElement; error: HTMLElement }, message: string) {
    target.error.textContent = message
    target.error.style.display = 'block'
    target.input.setAttribute('aria-invalid', 'true')
  }

  function clearError(target: { input: HTMLInputElement; error: HTMLElement }) {
    target.error.style.display = 'none'
    target.input.removeAttribute('aria-invalid')
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault()
    formError.style.display = 'none'
    ;[name, email, phone].forEach(clearError)
    fileError.style.display = 'none'

    let valid = true
    if (!name.input.value.trim()) {
      setError(name, strings.required)
      valid = false
    }
    const emailValue = email.input.value.trim()
    if (!emailValue) {
      setError(email, strings.required)
      valid = false
    } else if (!EMAIL_RE.test(emailValue)) {
      setError(email, strings.invalidEmail)
      valid = false
    }
    const file = fileInput.files?.[0]
    if (!file) {
      fileError.textContent = strings.cvRequired
      fileError.style.display = 'block'
      valid = false
    }
    if (!valid || !file) return

    const body = new FormData()
    body.append('full_name', name.input.value.trim())
    body.append('email', emailValue)
    if (phone.input.value.trim()) body.append('phone', phone.input.value.trim())
    body.append('cv', file)

    submit.disabled = true
    submit.textContent = ''
    submit.appendChild(el('span', { class: 'spinner' }))
    submit.appendChild(document.createTextNode(strings.submitting))

    fetch(`${config.apiUrl}/api/v1/public/apply/${encodeURIComponent(config.sessionKey)}`, {
      method: 'POST',
      body,
    })
      .then(async (response) => {
        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null
          const detail = payload?.detail
          throw new Error(typeof detail === 'string' ? detail : `HTTP ${response.status}`)
        }
        container.textContent = ''
        container.appendChild(
          stateBlock('✓', strings.successTitle, strings.successBody),
        )
      })
      .catch((error: unknown) => {
        formError.textContent = error instanceof Error ? error.message : strings.errorBody
        formError.style.display = 'block'
        submit.disabled = false
        submit.textContent = strings.submit
      })
  })
}

// `document.currentScript` is only valid while the script is executing, so read
// it immediately and defer only the DOM work.
const currentScript = document.currentScript as HTMLScriptElement | null
const config = readConfig(currentScript)

if (config) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => mount(config))
  } else {
    mount(config)
  }
}
