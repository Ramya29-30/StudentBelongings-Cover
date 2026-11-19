import { screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { mockApi, renderApp } from './harness';

const CATS = [
  { id: 1, name: 'Laptop', min_purchase_value: 25000, monthly_premium: 99, annual_premium: 1188, max_coverage: 18000, deductible: 0 },
  { id: 2, name: 'Earbuds', min_purchase_value: 2500, monthly_premium: 50, annual_premium: 600, max_coverage: 2000, deductible: 500 },
];
const noUser = { 'GET /auth/me': { __status: 401, body: { detail: 'Not signed in' } } };

describe('public landing page', () => {
  it('shows the hero, navigation and live category data from the backend', async () => {
    mockApi({ ...noUser, 'GET /v2/categories': CATS });
    renderApp('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Protect What Matters. Study Without Worry.' })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    for (const n of ['Home', 'How it works', 'Coverage plans', 'Why choose us', 'FAQ', 'Sign in', 'Get started']) expect(within(nav).getByRole('link', { name: n })).toBeInTheDocument();
    const table = await screen.findByRole('table');
    expect(within(table).getByText('₹25,000.00')).toBeInTheDocument();   // minimum value of the laptop, from the API
    expect(within(table).getByText('₹1,188.00')).toBeInTheDocument();
    expect(screen.getAllByText('Earbuds').length).toBeGreaterThan(0);
  });

  it('shows an empty state, not invented prices, when the catalogue cannot load', async () => {
    mockApi({ ...noUser });
    renderApp('/');
    expect(await screen.findByText(/catalogue could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('has all eight FAQ questions and the academic prototype disclaimer', async () => {
    mockApi({ ...noUser, 'GET /v2/categories': CATS });
    renderApp('/');
    await screen.findByRole('table');
    const faq = within(document.getElementById('faq') as HTMLElement);
    for (const q of ['What is an insurance premium?', 'What does maximum coverage mean?', 'What happens if my asset is damaged?', 'How do I submit a claim?', 'What is a deductible?', 'What does an exclusion mean?', 'Can I insure an asset below its minimum value?', 'How does AI damage verification work?'])
      expect(faq.getByText(q)).toBeInTheDocument();
    expect(screen.getAllByText(/academic prototype/i).length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: 'Insurance Disclaimer' })).toBeInTheDocument();
  });

  it('does not show the chat button to signed-out visitors', async () => {
    mockApi({ ...noUser, 'GET /v2/categories': CATS });
    renderApp('/');
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByRole('button', { name: /CoverMate AI chat/i })).toBeNull();
  });
});

/** fetch stub that serves normal JSON routes and a streamed SSE answer for the chat endpoint. */
function sseBody(events: [string, unknown][]) {
  const enc = new TextEncoder();
  return new ReadableStream({ start(c) { for (const [e, d] of events) c.enqueue(enc.encode(`event: ${e}\ndata: ${JSON.stringify(d)}\n\n`)); c.close(); } });
}
function mockChat(chat: (body: any) => { status: number; events?: [string, unknown][]; json?: unknown }, available = true) {
  const sent: any[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = String(url).replace(/^\/api/, '');
    const json = (o: unknown, status = 200) => ({ ok: status < 400, status, json: async () => o });
    if (path === '/auth/me') return json({ id: 1, username: 'riya', full_name: 'Riya Menon', role: 'student', email: 'r@e.edu', csrf_token: 'tok', expires_at: '2099-01-01T00:00:00' });
    if (path === '/meta') return json({});
    if (path === '/public-config') return json({ banner: '', demo_mode: false });
    if (path === '/ai/chat/status') return json({ available });
    if (path === '/v2/policies') return json([]);
    if (path === '/v2/dashboard') return json({ active_policies: 0, insured_assets: 0, registered_assets: 0, total_coverage: 0, monthly_commitment: 0, premium_due: [], recent_claims: [], recent_transactions: [] });
    if (path === '/ai/chat/stream') {
      const body = JSON.parse(String(init.body)); sent.push({ body, headers: init.headers });
      const r = chat(body);
      return r.status === 200 ? { ok: true, status: 200, body: sseBody(r.events ?? []), json: async () => ({}) } : json(r.json ?? { detail: 'x' }, r.status);
    }
    return json({ detail: 'no mock for ' + path }, 404);
  }));
  return sent;
}

describe('CoverMate AI widget', () => {
  it('opens, shows the welcome message and suggestions, streams an answer from the backend, and keeps the conversation id', async () => {
    const sent = mockChat(() => ({ status: 200, events: [['meta', { conversation_id: '11111111-1111-1111-1111-111111111111', focus: { policy_number: null, claim_number: null, policy_id: null, claim_id: null } }], ['delta', { text: 'Insurance is ' }], ['delta', { text: 'a safety net.' }], ['done', { message: { id: 1, role: 'assistant', content: 'Insurance is a safety net.', notice: null } }]] }));
    const u = userEvent.setup();
    renderApp('/student');
    await u.click(await screen.findByRole('button', { name: 'Open CoverMate AI chat' }));
    expect(screen.getByRole('dialog', { name: 'CoverMate AI chat' })).toBeInTheDocument();
    expect(screen.getByText(/Hi! I'm CoverMate AI/)).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: 'What is insurance?' }));
    expect(await screen.findByText('Insurance is a safety net.')).toBeInTheDocument();
    expect(sent[0].body).toEqual({ message: 'What is insurance?' });
    expect((sent[0].headers as Record<string, string>)['X-CSRF-Token']).toBe('tok');
    // follow-up reuses the conversation id so the backend can supply context
    await u.type(screen.getByLabelText('Your question'), 'I still do not understand{enter}');
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].body).toMatchObject({ message: 'I still do not understand', conversation_id: '11111111-1111-1111-1111-111111111111' });
  });

  it('shows the exact unavailable message and does not invent an answer when the provider is down', async () => {
    mockChat(() => ({ status: 503, json: { detail: 'CoverMate AI is temporarily unavailable. Please try again later.' } }));
    const u = userEvent.setup();
    renderApp('/student');
    await u.click(await screen.findByRole('button', { name: 'Open CoverMate AI chat' }));
    await u.type(screen.getByLabelText('Your question'), 'hello{enter}');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('CoverMate AI is temporarily unavailable. Please try again later.');
  });

  it('disables input and shows the unavailable message when the status endpoint says it is not configured', async () => {
    mockChat(() => ({ status: 200, events: [] }), false);
    const u = userEvent.setup();
    renderApp('/student');
    await u.click(await screen.findByRole('button', { name: 'Open CoverMate AI chat' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('CoverMate AI is temporarily unavailable. Please try again later.');
    expect(screen.getByLabelText('Your question')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'What is insurance?' })).toBeNull();
  });

  it('retry resends the last question with retry=true, and Escape closes the window', async () => {
    const sent = mockChat(() => ({ status: 200, events: [['done', { message: { id: 2, role: 'assistant', content: 'Answer text', notice: null } }]] }));
    const u = userEvent.setup();
    renderApp('/student');
    await u.click(await screen.findByRole('button', { name: 'Open CoverMate AI chat' }));
    await u.type(screen.getByLabelText('Your question'), 'What is a premium?{enter}');
    await screen.findByText('Answer text');
    await u.click(screen.getByRole('button', { name: /Retry/ }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].body).toMatchObject({ message: 'What is a premium?', retry: true });
    await u.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
