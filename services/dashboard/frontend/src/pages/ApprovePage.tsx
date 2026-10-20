import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

/**
 * Opened from the link in an alert email: no login, the token in the URL is the key. Shows ONE card and asks for a second tap before anything happens.
 * Plain fetch (not the app's API client) so a bad link never redirects to the login page.
 */
type Card = {
  student: { name: string; phone?: string; personal_email?: string } | null;
  interview: { type?: string; company?: string; position?: string; date?: string; time?: string; timezone?: string; format?: string };
  email: { subject?: string; from_address?: string; received_date?: string; excerpt?: string } | null;
  authenticity: { verdict: string; note?: string };
  warnings: string[];
  blockers: string[];
  suggestion?: { action: string; text: string } | null;
  draft: { subject?: string; body?: string; recipient_email?: string } | null;
  can_approve: boolean;
  will_happen: string;
  preview: { call: string; text: string; email_subject?: string } | null;
};
type View = {
  state: string;
  used_action?: string;
  draft_status?: string;
  delivery_live?: boolean;
  card?: Card;
  original_email?: { subject?: string; from_address?: string; received_date?: string; text?: string } | null;
};

const MESSAGES: Record<string, string> = {
  used: 'This link was already used.',
  expired: 'This link has expired. Open the Review page in the app instead.',
  decided: 'This card has already been decided. Nothing more to do.',
};

const ApprovePage = () => {
  const { token = '' } = useParams();
  const [view, setView] = useState<View | null>(null);
  const [gate, setGate] = useState<{ sent_to?: string } | null>(null);
  const [codeSent, setCodeSent] = useState(false);
  const [code, setCode] = useState('');
  const [gateBusy, setGateBusy] = useState(false);
  const [gateMessage, setGateMessage] = useState('');
  const [error, setError] = useState('');
  const [confirming, setConfirming] = useState<'approve' | 'reject' | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState('');
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    const meta = document.createElement('meta');
    meta.name = 'referrer';
    meta.content = 'no-referrer';
    document.head.appendChild(meta);
    return () => { document.head.removeChild(meta); };
  }, []);

  useEffect(() => {
    fetch(`/api/approve-links/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (r.status === 404) throw new Error('This link is not valid.');
        if (!r.ok) throw new Error('Could not load this card. Try again, or open the Review page in the app.');
        const data = await r.json();
        if (data.state === 'needs_code') setGate({ sent_to: data.sent_to });
        else setView(data);
      })
      .catch((e) => setError(e.message));
  }, [token]);

  const act = async (action: 'approve' | 'reject') => {
    setBusy(true);
    setActionError('');
    try {
      const r = await fetch(`/api/approve-links/${encodeURIComponent(token)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true, code, reason: action === 'reject' ? reason || undefined : undefined }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not complete this. Open the Review page in the app.');
      setDone(action === 'approve' ? 'Approved. The follow-up plan has started.' : 'Rejected. Nothing will be sent.');
    } catch (e) {
      setActionError((e as Error).message);
      setConfirming(null);
    } finally {
      setBusy(false);
    }
  };

  const sendCode = async () => {
    setGateBusy(true);
    setGateMessage('');
    try {
      const r = await fetch(`/api/approve-links/${encodeURIComponent(token)}/send-code`, { method: 'POST' });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not send the code.');
      setCodeSent(true);
      setGateMessage(`A code was emailed to ${body.sent_to}. It works for ${body.valid_minutes} minutes. Switch to your email app, copy it, and come back to this page.`);
    } catch (e) {
      setGateMessage((e as Error).message);
    } finally {
      setGateBusy(false);
    }
  };

  const openWithCode = async () => {
    setGateBusy(true);
    setGateMessage('');
    try {
      const r = await fetch(`/api/approve-links/${encodeURIComponent(token)}/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not open the card.');
      setGate(null);
      setView(body);
    } catch (e) {
      setGateMessage((e as Error).message);
    } finally {
      setGateBusy(false);
    }
  };

  const shell = (children: React.ReactNode) => (
    <div className="min-h-screen bg-gray-100 px-4 py-6">
      <div className="max-w-xl mx-auto space-y-4">{children}</div>
    </div>
  );

  if (error) return shell(<div className="bg-white rounded-lg shadow p-4 text-red-800">{error}</div>);
  if (gate) {
    return shell(
      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <div className="text-lg font-semibold text-gray-900">Confirm it is you</div>
        <div className="text-sm text-gray-700">
          For your security we email a 6-digit code to <strong>{gate.sent_to}</strong>. Nothing is shown until you enter it, and each decision needs a fresh code.
        </div>
        <button type="button" disabled={gateBusy} onClick={sendCode}
          className="w-full py-3 rounded-md bg-blue-600 text-white font-medium disabled:opacity-50">{codeSent ? 'Email me a new code' : 'Email me a code'}</button>
        {codeSent && (
          <div className="space-y-2">
            <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code"
              placeholder="6-digit code" className="w-full px-3 py-3 border border-gray-300 rounded-md text-lg tracking-widest text-center" />
            <button type="button" disabled={gateBusy || code.length !== 6} onClick={openWithCode}
              className="w-full py-3 rounded-md bg-green-600 text-white font-medium disabled:opacity-40">Show the card</button>
          </div>
        )}
        {gateMessage && <div className="text-sm text-gray-800 bg-gray-50 border border-gray-200 rounded p-2">{gateMessage}</div>}
      </div>
    );
  }
  if (!view) return shell(<div className="bg-white rounded-lg shadow p-4 text-gray-600">Loading...</div>);
  if (done) return shell(<div className="bg-white rounded-lg shadow p-4 text-green-800 font-medium">{done}</div>);
  if (view.state !== 'ready' || !view.card) {
    return shell(<div className="bg-white rounded-lg shadow p-4 text-gray-800">{MESSAGES[view.state] || 'This link cannot be used.'}</div>);
  }

  const c = view.card;
  const iv = c.interview;
  const when = [iv.date, iv.time, iv.timezone].filter(Boolean).join(' ') || 'Not stated in the email';

  return shell(
    <>
      <div className="bg-white rounded-lg shadow p-4 space-y-2">
        <div className="text-lg font-semibold text-gray-900">{c.student?.name || 'Unknown student'}</div>
        <div className="text-sm text-gray-600">{[c.student?.phone || 'No phone on file', c.student?.personal_email].filter(Boolean).join(' · ')}</div>
        <dl className="text-sm grid grid-cols-3 gap-x-2 gap-y-1 pt-2">
          <dt className="text-gray-500">Type</dt><dd className="col-span-2">{iv.type || '—'}</dd>
          <dt className="text-gray-500">Company</dt><dd className="col-span-2">{iv.company || '—'}</dd>
          <dt className="text-gray-500">Position</dt><dd className="col-span-2">{iv.position || '—'}</dd>
          <dt className="text-gray-500">Interview time</dt><dd className="col-span-2">{when}</dd>
          <dt className="text-gray-500">Format</dt><dd className="col-span-2">{iv.format || '—'}</dd>
        </dl>
      </div>

      {c.suggestion && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-sm text-yellow-900">
          <strong>Suggested: {c.suggestion.action}.</strong> {c.suggestion.text}
        </div>
      )}
      {c.blockers.map((b) => <div key={b} className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">{b}</div>)}
      {c.warnings.map((w) => <div key={w} className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-sm text-yellow-900">{w}</div>)}

      {(view.original_email || c.email) && (
        <div className="bg-white rounded-lg shadow p-4 text-sm space-y-2">
          <div className="font-medium text-gray-900">The original email we received</div>
          <div className="text-gray-500">
            From {(view.original_email || c.email)?.from_address}
            {view.original_email?.received_date ? ` · ${new Date(view.original_email.received_date.endsWith('Z') ? view.original_email.received_date : `${view.original_email.received_date}Z`).toLocaleString('en-US', { timeZone: 'America/Chicago', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })} CT` : ''}
          </div>
          <div className="text-gray-800 font-medium">{(view.original_email || c.email)?.subject}</div>
          <div className="whitespace-pre-wrap text-gray-800 max-h-96 overflow-y-auto border border-gray-100 rounded p-2 bg-gray-50">
            {view.original_email?.text || c.email?.excerpt}
          </div>
        </div>
      )}

      {c.preview && (
        <div className="bg-white rounded-lg shadow p-4 text-sm space-y-3">
          <div className="font-medium text-gray-900">Exactly what the student will receive</div>
          <div>
            <div className="text-gray-500">Phone call (spoken by the AI agent)</div>
            <div className="whitespace-pre-wrap text-gray-800">{c.preview.call}</div>
          </div>
          <div>
            <div className="text-gray-500">Text message</div>
            <div className="whitespace-pre-wrap text-gray-800">{c.preview.text}</div>
          </div>
          <div>
            <div className="text-gray-500">Email{c.draft?.recipient_email ? ` to ${c.draft.recipient_email}` : ''}</div>
            <div className="text-gray-800 font-medium">{c.draft?.subject || c.preview.email_subject}</div>
            {c.draft?.body && <div className="whitespace-pre-wrap text-gray-800 max-h-96 overflow-y-auto border border-gray-100 rounded p-2 bg-gray-50 mt-1">{c.draft.body}</div>}
          </div>
        </div>
      )}

      <div className={`rounded-lg p-3 text-sm ${view.delivery_live ? 'bg-red-50 border border-red-300 text-red-800' : 'bg-gray-50 border border-gray-200 text-gray-700'}`}>
        {view.delivery_live ? <strong>LIVE: </strong> : <strong>Shadow: </strong>}{c.will_happen}
      </div>

      {actionError && <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">{actionError}</div>}

      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        {confirming === null && (
          <div className="flex gap-3">
            <button type="button" disabled={!c.can_approve} onClick={() => setConfirming('approve')}
              className="flex-1 py-3 rounded-md bg-green-600 text-white font-medium disabled:opacity-40">Approve</button>
            <button type="button" onClick={() => setConfirming('reject')}
              className="flex-1 py-3 rounded-md border border-red-300 text-red-700 font-medium">Reject</button>
          </div>
        )}
        {confirming === 'approve' && (
          <div className="space-y-2">
            <div className="text-sm text-gray-900">Confirm: start the notification for <strong>{c.student?.name}</strong>? {view.delivery_live ? 'This calls, texts and emails them now.' : 'Shadow mode: nothing reaches them yet.'}</div>
            <div className="flex gap-3">
              <button type="button" disabled={busy} onClick={() => act('approve')} className="flex-1 py-3 rounded-md bg-green-600 text-white font-medium disabled:opacity-50">Yes, approve</button>
              <button type="button" onClick={() => setConfirming(null)} className="flex-1 py-3 rounded-md border border-gray-300">Cancel</button>
            </div>
          </div>
        )}
        {confirming === 'reject' && (
          <div className="space-y-2">
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)" className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm" />
            <div className="flex gap-3">
              <button type="button" disabled={busy} onClick={() => act('reject')} className="flex-1 py-3 rounded-md bg-red-600 text-white font-medium disabled:opacity-50">Yes, reject</button>
              <button type="button" onClick={() => setConfirming(null)} className="flex-1 py-3 rounded-md border border-gray-300">Cancel</button>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

export default ApprovePage;
