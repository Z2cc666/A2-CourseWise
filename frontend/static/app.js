/**
 * CourseWise — frontend controller.
 *
 * Plain JavaScript: no build step, no framework. The UI is built by rendering
 * functions that return DOM nodes, so no untrusted content is ever injected
 * as HTML.
 *
 * The layout is a conventional chat interface. Evidence and warnings are
 * attached to the answer that produced them rather than shown as separate
 * panels, so the page reads like an ordinary assistant.
 */

(function () {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* Configuration                                                       */
  /* ------------------------------------------------------------------ */

  const API = {
    ask: '/api/ask',
    health: '/api/health',
    conversations: '/api/conversations',
    conversation: (id) => '/api/conversations/' + encodeURIComponent(id),
    confirm: (id) => '/api/actions/' + encodeURIComponent(id) + '/confirm',
    cancel: (id) => '/api/actions/' + encodeURIComponent(id) + '/cancel',
  };

  const FRESHNESS_CLASS = {
    current: 'badge--current',
    expiring: 'badge--expiring',
    expired: 'badge--expired',
    superseded: 'badge--superseded',
    archived: 'badge--archived',
  };

  /* ------------------------------------------------------------------ */
  /* DOM helpers                                                         */
  /* ------------------------------------------------------------------ */

  const $ = (selector, root) => (root || document).querySelector(selector);

  /**
   * Create an element. Children may be nodes or strings; strings become text
   * nodes, never HTML.
   */
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const key of Object.keys(attrs)) {
        const value = attrs[key];
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key === 'style') node.setAttribute('style', value);
        else if (key.startsWith('on') && typeof value === 'function') {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (value === true) node.setAttribute(key, '');
        else node.setAttribute(key, value);
      }
    }
    if (children) {
      for (const child of [].concat(children)) {
        if (child === null || child === undefined || child === false) continue;
        node.appendChild(
          typeof child === 'string' || typeof child === 'number'
            ? document.createTextNode(String(child))
            : child,
        );
      }
    }
    return node;
  }

  /** Inline SVG icon from path definitions. */
  function icon(paths, size) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', size || 16);
    svg.setAttribute('height', size || 16);
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    for (const d of paths) {
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    }
    return svg;
  }

  const ICONS = {
    check: (s) => icon(['M20 6 9 17l-5-5'], s),
    alert: (s) =>
      icon(
        [
          'M12 9v4M12 17h.01',
          'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z',
        ],
        s,
      ),
    info: (s) => icon(['M12 16v-4M12 8h.01', 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z'], s),
    clock: (s) => icon(['M12 6v6l4 2', 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z'], s),
    file: (s) => icon(['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z', 'M14 2v6h6'], s),
    chevron: (s) => icon(['m9 18 6-6-6-6'], s),
    shield: (s) => icon(['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z'], s),
    link: (s) =>
      icon(
        [
          'M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71',
          'M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71',
        ],
        s,
      ),
  };

  /* ------------------------------------------------------------------ */
  /* State                                                               */
  /* ------------------------------------------------------------------ */

  const state = {
    messages: [],
    conversationId: null,
    conversations: [],
  };

  const conversation = $('#conversation');
  const input = $('#composer-input');
  const sendButton = $('#composer-send');

  /* ------------------------------------------------------------------ */
  /* Rendering — an answer                                               */
  /* ------------------------------------------------------------------ */

  function renderSource(source) {
    const isStale = ['superseded', 'expired', 'archived'].indexOf(
      source.freshness.freshness,
    ) !== -1;

    const chevron = ICONS.chevron(13);
    const head = el('button', { class: 'source__head', type: 'button' }, [
      el('span', { class: 'source__main' }, [
        el('span', { class: 'source__title', text: source.title }),
        el('span', { class: 'source__meta', text: source.section }),
        el('span', { class: 'source__meta', text: source.updatedAtLabel }),
      ]),
      el(
        'span',
        { class: 'badge ' + (FRESHNESS_CLASS[source.freshness.freshness] || 'badge--superseded') },
        [source.freshness.label],
      ),
      source.cited ? el('span', { class: 'badge badge--cited', text: 'cited' }) : null,
    ]);

    const body = el('div', { class: 'source__body' }, [
      isStale ? el('div', { class: 'source__stale', text: source.freshness.detail }) : null,
      el('p', { class: 'source__excerpt', text: source.excerpt }),
      source.sourceUrl
        ? el(
            'a',
            {
              class: 'source__link',
              href: source.sourceUrl,
              target: '_blank',
              rel: 'noreferrer noopener',
            },
            [ICONS.link(13), 'Open the original document'],
          )
        : null,
    ]);

    const card = el('div', {
      class: ['source', source.cited ? 'source--cited' : '', isStale ? 'source--stale' : '']
        .filter(Boolean)
        .join(' '),
    });
    card.appendChild(head);

    let expanded = source.cited;
    if (expanded) card.appendChild(body);

    head.addEventListener('click', function () {
      expanded = !expanded;
      if (expanded) card.appendChild(body);
      else body.remove();
      chevron.remove();
    });

    return card;
  }

  function renderSources(sources) {
    if (!sources || sources.length === 0) return null;

    const cited = sources.filter(function (s) {
      return s.cited;
    }).length;

    const head = el('div', { class: 'sources__head' }, [
      ICONS.file(13),
      el('span', { text: 'Sources' }),
      el('span', {
        class: 'sources__count',
        text: sources.length + (sources.length === 1 ? ' passage' : ' passages'),
      }),
    ]);

    const list = el('div');
    for (const source of sources) list.appendChild(renderSource(source));

    return el('div', { class: 'sources' }, [head, list]);
  }

  function renderNotice(title, detail, tone) {
    const iconFn = tone === 'warning' ? ICONS.alert : ICONS.info;
    return el('div', { class: 'notice notice--' + (tone || 'info') }, [
      el('span', { class: 'notice__icon' }, [iconFn(15)]),
      el('span', { class: 'notice__body' }, [
        el('span', { class: 'notice__title', text: title }),
        detail ? el('span', { class: 'notice__detail', text: detail }) : null,
      ]),
    ]);
  }

  function renderWarnings(warnings) {
    if (!warnings || warnings.length === 0) return null;

    const wrap = el('div');
    for (const warning of warnings) {
      wrap.appendChild(
        renderNotice(warning.title, warning.detail, warning.severity === 'warning' ? 'warning' : 'info'),
      );
    }
    return wrap;
  }

  function renderNotFound(notFound) {
    if (!notFound) return null;

    const details = [];
    for (const suggestion of notFound.suggestions || []) {
      details.push(suggestion);
    }

    return renderNotice(
      notFound.reason || 'Not confirmed by the course documents',
      details.join(' '),
      'info',
    );
  }

  function renderAction(action, outcome) {
    const card = el('div', { class: 'action' });

    card.appendChild(
      el('div', { class: 'action__head' }, [
        ICONS.shield(15),
        el('span', { text: outcome ? 'Action resolved' : action.title }),
      ]),
    );

    const body = el('div', { class: 'action__body' });

    if (outcome) {
      body.appendChild(
        el('div', { class: 'notice notice--info' }, [
          el('span', { class: 'notice__icon' }, [outcome.ok ? ICONS.check(15) : ICONS.alert(15)]),
          el('span', { class: 'notice__body' }, [
            el('span', {
              class: 'notice__title',
              text: outcome.ok ? 'Done' : 'Nothing was changed',
            }),
            el('span', { class: 'notice__detail', text: outcome.message }),
          ]),
        ]),
      );
    } else {
      const fields = el('div', { class: 'action__fields' });
      for (const field of action.fields) {
        fields.appendChild(
          el('div', { class: 'action__field' }, [
            el('div', { class: 'action__label', text: field.label }),
            el('div', { class: 'action__value', text: field.value }),
          ]),
        );
      }

      const confirmButton = el('button', { class: 'btn btn--primary', type: 'button' }, [
        'Confirm',
      ]);
      confirmButton.addEventListener('click', function () {
        resolveAction(action, true);
      });

      const cancelButton = el('button', { class: 'btn btn--secondary', type: 'button' }, [
        'Cancel',
      ]);
      cancelButton.addEventListener('click', function () {
        resolveAction(action, false);
      });

      body.appendChild(el('p', { class: 'action__preview', text: action.preview }));
      body.appendChild(fields);
      body.appendChild(
        el('div', { class: 'action__consequence' }, [
          el('strong', { text: 'Before you confirm: ' }),
          action.consequence,
        ]),
      );
      body.appendChild(el('div', { class: 'action__buttons' }, [confirmButton, cancelButton]));
    }

    card.appendChild(body);
    return card;
  }

  function renderAnswer(message) {
    const response = message.response;
    const answer = el('div', { class: 'answer' });

    answer.appendChild(el('p', { class: 'answer__text', text: response.answer }));

    const warnings = renderWarnings(response.warnings);
    if (warnings) answer.appendChild(warnings);

    const notFound = renderNotFound(response.notFound);
    if (notFound) answer.appendChild(notFound);

    if (response.action) {
      answer.appendChild(renderAction(response.action, message.outcome));
    }

    const sources = renderSources(response.sources);
    if (sources) answer.appendChild(sources);

    return answer;
  }

  function renderThinking() {
    return el('div', { class: 'thinking' }, [
      el('span', { class: 'thinking__dots' }, [
        el('span', { class: 'thinking__dot' }),
        el('span', { class: 'thinking__dot' }),
        el('span', { class: 'thinking__dot' }),
      ]),
      'Thinking…',
    ]);
  }

  function render() {
    conversation.innerHTML = '';

    if (state.messages.length === 0) {
      const welcome = el('div', { class: 'welcome' }, [
        el('h1', { text: 'CourseWise' }),
        el('p', {
          text:
            'Ask about deadlines, policies, readings or the exam format. ' +
            'Answers come from the course documents and carry their source.',
        }),
      ]);
      conversation.appendChild(welcome);
      return;
    }

    for (const message of state.messages) {
      if (message.role === 'user') {
        conversation.appendChild(
          el('div', { class: 'turn turn--user' }, [
            el('div', { class: 'bubble-user', text: message.text }),
          ]),
        );
        continue;
      }

      const turn = el('div', { class: 'turn turn--assistant' });
      if (message.busy) turn.appendChild(renderThinking());
      else if (message.response) turn.appendChild(renderAnswer(message));
      conversation.appendChild(turn);
    }

    conversation.scrollTop = conversation.scrollHeight;
  }

  /* ------------------------------------------------------------------ */
  /* Rendering — the conversation list                                   */
  /* ------------------------------------------------------------------ */

  function renderConversations() {
    const list = $('#conversation-list');
    list.innerHTML = '';

    if (state.conversations.length === 0) {
      list.appendChild(
        el('div', {
          class: 'conv',
          style: 'color:var(--text-faint);cursor:default',
          text: 'No conversations yet',
        }),
      );
      return;
    }

    for (const item of state.conversations) {
      const row = el('div', {
        class: 'conv' + (item.id === state.conversationId ? ' conv--active' : ''),
        title: item.title,
        onClick: function () {
          openConversation(item.id);
        },
      });

      row.appendChild(el('span', { class: 'conv__title', text: item.title }));

      const remove = el('button', {
        class: 'conv__del',
        type: 'button',
        title: 'Delete conversation',
        text: '×',
        onClick: function (event) {
          event.stopPropagation();
          deleteConversation(item.id);
        },
      });
      row.appendChild(remove);

      list.appendChild(row);
    }
  }

  async function refreshConversations() {
    try {
      const res = await fetch(API.conversations);
      const data = await res.json();
      state.conversations = data.conversations || [];
      renderConversations();
    } catch (error) {
      /* The sidebar is decorative; a failure must not break the app. */
    }
  }

  /* ------------------------------------------------------------------ */
  /* Behaviour                                                           */
  /* ------------------------------------------------------------------ */

  function setBusy(busy) {
    sendButton.disabled = busy || !input.value.trim();
    input.disabled = busy;
  }

  async function ask(question) {
    const trimmed = String(question || '').trim();
    if (!trimmed) return;

    state.messages.push({ role: 'user', text: trimmed });
    const assistant = { role: 'assistant', busy: true };
    state.messages.push(assistant);

    input.value = '';
    autoGrow();
    setBusy(true);
    render();

    try {
      const res = await fetch(API.ask, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: trimmed,
          conversation_id: state.conversationId,
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(function () {
          return {};
        });
        const error = new Error(
          detail.detail || 'The assistant could not produce an answer.'
        );
        error.status = res.status;
        error.code = detail.error;
        throw error;
      }
      assistant.response = await res.json();
    } catch (error) {
      // A locked database is a 409, and the message explains what to do.
      // Reporting it as "not confirmed by the course documents" would be
      // wrong: the answer may well have been found, it just could not be
      // stored.
      const locked = error.code === 'database-locked';
      assistant.response = {
        status: locked ? 'service-unavailable' : 'insufficient-evidence',
        answer: error.message || 'The assistant could not be reached.',
        verdict: {
          label: locked ? 'Database unavailable' : 'Service unavailable',
          detail: '',
          confidence: 0,
        },
        sources: [],
        warnings: [],
        notFound: null,
        relatedQuestions: [],
        backend: 'extractive',
        model: null,
        consideredDocuments: [],
      };
    } finally {
      assistant.busy = false;
      setBusy(false);
      render();
      input.focus();

      // The first exchange names the conversation after the question.
      if (!state.conversationId) {
        await ensureConversation(trimmed);
      }
      refreshConversations();
    }
  }

  async function ensureConversation(title) {
    try {
      const res = await fetch(API.conversations, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.slice(0, 60) }),
      });
      const data = await res.json();
      state.conversationId = data.conversation ? data.conversation.id : null;
      $('#topbar-title').textContent = data.conversation ? data.conversation.title : 'CourseWise';
    } catch (error) {
      /* Without a conversation id the chat still works, it just is not saved. */
    }
  }

  async function openConversation(conversationId) {
    try {
      const res = await fetch(API.conversation(conversationId));
      const data = await res.json();
      state.conversationId = conversationId;
      state.messages = (data.messages || []).map(function (message) {
        return { role: message.role, text: message.content, response: null };
      });

      // Replay asks the server for the full answers so the evidence and
      // warnings are shown again, not just the plain text.
      const restored = await Promise.all(
        (data.messages || [])
          .filter(function (m) {
            return m.role === 'user';
          })
          .map(async function (message, index) {
            const res2 = await fetch(API.ask, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ question: message.content }),
            });
            return res2.ok ? res2.json() : null;
          }),
      );

      state.messages = [];
      let cursor = 0;
      for (const message of data.messages || []) {
        if (message.role === 'user') {
          state.messages.push({ role: 'user', text: message.content });
          const response = restored[cursor];
          cursor += 1;
          state.messages.push(
            response
              ? { role: 'assistant', response: response }
              : { role: 'assistant', busy: false, response: null, text: message.content },
          );
        }
      }

      $('#topbar-title').textContent = data.conversation ? data.conversation.title : 'CourseWise';
      renderConversations();
      render();
    } catch (error) {
      /* Leave the current conversation in place if it cannot be loaded. */
    }
  }

  async function deleteConversation(conversationId) {
    try {
      await fetch(API.conversation(conversationId), { method: 'DELETE' });
      if (state.conversationId === conversationId) newConversation();
      refreshConversations();
    } catch (error) {
      /* Nothing to do; the list will refresh on the next interaction. */
    }
  }

  function newConversation() {
    state.conversationId = null;
    state.messages = [];
    $('#topbar-title').textContent = 'CourseWise';
    renderConversations();
    render();
    input.focus();
  }

  async function resolveAction(action, confirm) {
    try {
      const url = confirm ? API.confirm(action.id) : API.cancel(action.id);
      const res = await fetch(url, { method: 'POST' });
      const data = await res.json().catch(function () {
        return {};
      });

      // Attach the outcome to the answer that proposed it.
      for (const message of state.messages) {
        if (
          message.response &&
          message.response.action &&
          message.response.action.id === action.id
        ) {
          message.outcome = {
            ok: res.ok && data.ok === true,
            message: data.message || data.detail || 'The action could not be completed.',
          };
        }
      }
      render();
    } catch (error) {
      for (const message of state.messages) {
        if (
          message.response &&
          message.response.action &&
          message.response.action.id === action.id
        ) {
          message.outcome = {
            ok: false,
            message: 'Could not reach the server, so nothing was changed.',
          };
        }
      }
      render();
    }
  }

  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 150) + 'px';
    sendButton.disabled = !input.value.trim();
  }

  /* ------------------------------------------------------------------ */
  /* Wiring                                                              */
  /* ------------------------------------------------------------------ */

  function wire() {
    try {
      wireUp();
    } catch (error) {
      // A silent failure here looks like a working page with no answers.
      // Say what went wrong instead.
      showFatal(error);
    }
  }

  function showFatal(error) {
    const banner = el('div', { class: 'notice notice--warning' }, [
      ICONS.alert(15),
      el('span', { class: 'notice__body' }, [
        el('span', { class: 'notice__title', text: 'The interface failed to start.' }),
        el('span', {
          class: 'notice__detail',
          text: String((error && error.message) || error),
        }),
      ]),
    ]);
    conversation.innerHTML = '';
    conversation.appendChild(banner);
  }

  function wireUp() {
    input.addEventListener('input', autoGrow);

    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        ask(input.value);
      }
    });

    sendButton.addEventListener('click', function () {
      ask(input.value);
    });

    $('#new-chat').addEventListener('click', newConversation);

    $('#clear-chat').addEventListener('click', function () {
      if (state.conversationId) deleteConversation(state.conversationId);
      else newConversation();
    });

    $('#sidebar-toggle').addEventListener('click', function () {
      $('.app').classList.add('app--collapsed');
    });

    $('#sidebar-open').addEventListener('click', function () {
      $('.app').classList.remove('app--collapsed');
    });

    fetch(API.health)
      .then(function (r) {
        return r.json();
      })
      .then(function (health) {
        const label =
          health.backend === 'deepseek'
            ? 'DeepSeek · ' + health.model
            : health.backend === 'llm'
              ? 'Claude · ' + health.model
              : 'Extractive engine';
        $('#health-text').textContent = label;
        $('#health-pill').classList.add('pill--ok');
      })
      .catch(function () {
        $('#health-text').textContent = 'Server unreachable';
      });

    refreshConversations();
    render();
    input.focus();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire, { once: true });
  } else {
    wire();
  }
})();
